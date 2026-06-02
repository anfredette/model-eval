from __future__ import annotations

import difflib
import enum
import re
from dataclasses import dataclass


class MatchType(enum.Enum):
    EXACT = "exact"
    EQUIVALENT = "equivalent"
    FUZZY = "fuzzy"
    NONE = "none"


_SUFFIXES_TO_STRIP = [
    "-nvfp4",
    "-fp8-dynamic",
    "-fp8",
    "-quantized.w4a16",
    "-quantized.w8a8",
    "-instruct-2501",
    "-instruct-2503",
    "-instruct-2509",
    "-instruct-2512",
    "-instruct-hf",
    "-instruct-v0.1",
    "-instruct",
    "-reasoning",
]

_QUANT_TOKENS = frozenset({"fp8", "dynamic", "nvfp4", "hf"})
_DATE_SUFFIX_RE = re.compile(r"^2\d{3}$")
_SIZE_RE = re.compile(r"\b(\d+(?:\.\d+)?[bB])\b")


@dataclass
class MatchResult:
    user_name: str
    matched_name: str | None
    match_type: MatchType


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _normalize_punctuation(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s).lower()


def _sorted_tokens(s: str) -> tuple[str, ...]:
    raw = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", s.lower())
    return tuple(sorted(
        t for t in raw
        if t not in _QUANT_TOKENS
        and not t.startswith("quantized")
        and not _DATE_SUFFIX_RE.match(t)
    ))


def _strip_org(s: str) -> str:
    return s.split("/", 1)[-1] if "/" in s else s


def _strip_suffixes(s: str) -> str:
    result = s
    changed = True
    while changed:
        changed = False
        lower = result.lower()
        for suffix in _SUFFIXES_TO_STRIP:
            if lower.endswith(suffix):
                result = result[: len(result) - len(suffix)].rstrip("-").strip()
                changed = True
                break
    return result


def _extract_sizes(s: str) -> set[str]:
    return {m.lower() for m in _SIZE_RE.findall(s)}


_VERSION_RE = re.compile(
    r"^(?P<base>.+?)"
    r"[.\-_]?"
    r"(?P<version>\d+(?:\.\d+)*(?:[a-z])?)"
    r"(?P<suffix>.*)$",
    re.IGNORECASE,
)


def _parse_version(name: str) -> tuple[str, list[int | str], str] | None:
    m = _VERSION_RE.match(_normalize_punctuation(name))
    if not m:
        return None
    base = m.group("base")
    ver_str = m.group("version")
    suffix = m.group("suffix")
    parts: list[int | str] = []
    for segment in re.split(r"[.]", ver_str):
        num_match = re.match(r"^(\d+)([a-z]?)$", segment)
        if num_match:
            parts.append(int(num_match.group(1)))
            if num_match.group(2):
                parts.append(num_match.group(2))
        else:
            parts.append(segment)
    return base, parts, suffix


def _version_to_scalar(parts: list[int | str]) -> float:
    """Convert version parts to a scalar for distance comparison.

    Each level gets a fixed weight (10000, 100, 1) so that
    3.6.1 (30601) is closer to 3.7 (30700) than 3.5 (30500).
    """
    weights = [10000, 100, 1]
    total = 0.0
    for i, part in enumerate(parts):
        w = weights[i] if i < len(weights) else 1
        if isinstance(part, int):
            total += part * w
        elif isinstance(part, str):
            total += ord(part[0]) * 0.01 * w if part else 0
    return total


def _version_distance(a: list[int | str], b: list[int | str]) -> float:
    return abs(_version_to_scalar(a) - _version_to_scalar(b))


def resolve_model_names(
    user_names: list[str], known_names: list[str]
) -> list[MatchResult]:
    known_set = set(known_names)

    lower_map: dict[str, str] = {}
    for k in known_names:
        lower_map.setdefault(k.lower(), k)

    punct_map: dict[str, str] = {}
    for k in known_names:
        punct_map.setdefault(_normalize_punctuation(k), k)

    org_stripped_lower_map: dict[str, str] = {}
    for k in known_names:
        org_stripped_lower_map.setdefault(_strip_org(k).lower(), k)

    org_stripped_punct_map: dict[str, str] = {}
    for k in known_names:
        org_stripped_punct_map.setdefault(_normalize_punctuation(_strip_org(k)), k)

    token_map: dict[tuple[str, ...], str] = {}
    for k in known_names:
        token_map.setdefault(_sorted_tokens(_strip_org(k)), k)

    suffix_stripped_lower_map: dict[str, str] = {}
    for k in known_names:
        suffix_stripped_lower_map.setdefault(_strip_suffixes(_strip_org(k)).lower(), k)

    suffix_stripped_token_map: dict[tuple[str, ...], str] = {}
    for k in known_names:
        suffix_stripped_token_map.setdefault(
            _sorted_tokens(_strip_suffixes(_strip_org(k))), k
        )

    results: list[MatchResult] = []
    for name in user_names:
        result = _resolve_one(
            name,
            known_set,
            known_names,
            lower_map,
            punct_map,
            org_stripped_lower_map,
            org_stripped_punct_map,
            token_map,
            suffix_stripped_lower_map,
            suffix_stripped_token_map,
        )
        results.append(result)
    return results


def _resolve_one(
    name: str,
    known_set: set[str],
    known_names: list[str],
    lower_map: dict[str, str],
    punct_map: dict[str, str],
    org_stripped_lower_map: dict[str, str],
    org_stripped_punct_map: dict[str, str],
    token_map: dict[tuple[str, ...], str],
    suffix_stripped_lower_map: dict[str, str],
    suffix_stripped_token_map: dict[tuple[str, ...], str],
) -> MatchResult:
    # 1. Exact
    if name in known_set:
        return MatchResult(name, name, MatchType.EXACT)

    # 2. Case-insensitive
    hit = lower_map.get(name.lower())
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 3. Org-stripped (user input has org prefix)
    user_stripped = _strip_org(name)
    if user_stripped != name:
        hit = lower_map.get(user_stripped.lower())
        if hit:
            return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 4. Org-stripped (known name has org prefix)
    hit = org_stripped_lower_map.get(name.lower())
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 5. Punctuation-normalized (with org-strip variants)
    user_punct = _normalize_punctuation(name)
    hit = punct_map.get(user_punct)
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    if user_stripped != name:
        hit = punct_map.get(_normalize_punctuation(user_stripped))
        if hit:
            return MatchResult(name, hit, MatchType.EQUIVALENT)

    hit = org_stripped_punct_map.get(user_punct)
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 6. Token-set (order-independent match, filters quant/date tokens)
    hit = token_map.get(_sorted_tokens(_strip_org(name)))
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 7. Suffix-stripped + case-insensitive
    user_base = _strip_suffixes(_strip_org(name))
    hit = suffix_stripped_lower_map.get(user_base.lower())
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 8. Suffix-stripped + token-set
    hit = suffix_stripped_token_map.get(_sorted_tokens(user_base))
    if hit:
        return MatchResult(name, hit, MatchType.EQUIVALENT)

    # 9. Size-aware partial word match (only when input has a parameter size like 8B, 70B)
    user_words = set(re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", _strip_org(name).lower()))
    user_sizes = _extract_sizes(name)
    if user_sizes and len(user_words) >= 2:
        best_match: str | None = None
        best_common = 0
        best_has_size = False
        for known in known_names:
            known_words = set(
                re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", _strip_org(known).lower())
            )
            common = user_words & known_words
            if len(common) < 2:
                continue
            known_sizes = _extract_sizes(known)
            has_size = bool(user_sizes and user_sizes & known_sizes)
            if has_size and not best_has_size:
                best_match = known
                best_common = len(common)
                best_has_size = True
            elif has_size == best_has_size and len(common) > best_common:
                best_match = known
                best_common = len(common)
                best_has_size = has_size
        if best_match is not None:
            return MatchResult(name, best_match, MatchType.FUZZY)

    # 10. Version-adjacent
    user_parsed = _parse_version(name)
    if user_parsed:
        user_ver_base, user_ver, _ = user_parsed
        best_match = None
        best_dist = float("inf")
        for known in known_names:
            known_parsed = _parse_version(known)
            if not known_parsed:
                continue
            known_base, known_ver, _ = known_parsed
            if user_ver_base == known_base:
                dist = _version_distance(user_ver, known_ver)
                if 0 < dist < best_dist:
                    best_dist = dist
                    best_match = known
        if best_match is not None:
            return MatchResult(name, best_match, MatchType.FUZZY)

    # 11. Normalized substring
    norm_name = _normalize(name)
    if norm_name:
        for known in known_names:
            if norm_name in _normalize(known):
                return MatchResult(name, known, MatchType.FUZZY)

    return MatchResult(name, None, MatchType.NONE)


def suggest_similar(name: str, known_names: list[str], n: int = 3) -> list[str]:
    query = name.lower()
    lower_known = [k.lower() for k in known_names]

    matches = difflib.get_close_matches(query, lower_known, n=n)
    if matches:
        return matches

    norm_query = _normalize(name)
    if not norm_query:
        return []
    scored: list[tuple[float, str]] = []
    for known in lower_known:
        norm_known = _normalize(known)
        prefix = norm_known[: len(norm_query) + 2]
        ratio = difflib.SequenceMatcher(None, norm_query, prefix).ratio()
        if ratio >= 0.6:
            scored.append((ratio, known))

    scored.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    results: list[str] = []
    for _, known in scored:
        if known not in seen:
            seen.add(known)
            results.append(known)
            if len(results) >= n:
                break
    return results
