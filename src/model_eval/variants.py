from __future__ import annotations

import re
import statistics
from typing import Any

QUANTIZATION_DISCOUNTS: dict[str, float] = {
    "fp8-dynamic": 1.0,
    "fp8": 1.0,
    "quantized.w8a8": 0.97,
    "quantized.w4a16": 0.92,
    "nvfp4": 0.92,
}

_QUANT_PATTERN = re.compile(
    r"(?:fp8-dynamic|fp8|quantized\.w8a8|quantized\.w4a16|nvfp4)", re.IGNORECASE
)
_INSTRUCT_PATTERN = re.compile(r"\binstruct\b", re.IGNORECASE)
_REASONING_PATTERN = re.compile(r"\b(?:reasoning|thinking)\b", re.IGNORECASE)


def detect_variant_delta(user_name: str, matched_name: str) -> tuple[float, str | None]:
    user_lower = user_name.lower()
    matched_lower = matched_name.lower()

    factor = 1.0
    descriptions: list[str] = []

    user_quant = _QUANT_PATTERN.search(user_lower)
    matched_quant = _QUANT_PATTERN.search(matched_lower)

    if user_quant and not matched_quant:
        discount = QUANTIZATION_DISCOUNTS.get(user_quant.group(0).lower(), 1.0)
        factor *= discount
        if discount < 1.0:
            descriptions.append(f"{user_quant.group(0)}: x{discount}")
    elif matched_quant and not user_quant:
        discount = QUANTIZATION_DISCOUNTS.get(matched_quant.group(0).lower(), 1.0)
        if discount < 1.0:
            factor /= discount
            descriptions.append(f"reverse {matched_quant.group(0)}: /{discount}")

    user_instruct = bool(_INSTRUCT_PATTERN.search(user_lower))
    matched_instruct = bool(_INSTRUCT_PATTERN.search(matched_lower))
    user_reasoning = bool(_REASONING_PATTERN.search(user_lower))
    matched_reasoning = bool(_REASONING_PATTERN.search(matched_lower))

    if user_instruct != matched_instruct:
        descriptions.append("instruct variant")
    if user_reasoning != matched_reasoning:
        descriptions.append("reasoning variant")

    if not descriptions:
        return 1.0, None
    return factor, "; ".join(descriptions)


def compute_reasoning_deltas(
    aa_models: list[dict[str, Any]],
) -> dict[str, float]:
    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for m in aa_models:
        name = m["name"]
        lower = name.lower()
        base = re.sub(r"\s*\((?:non-)?reasoning\).*$", "", lower, flags=re.IGNORECASE).strip()

        if "(non-reasoning)" in lower:
            pairs.setdefault(base, {})["non_reasoning"] = m
        elif "(reasoning)" in lower:
            pairs.setdefault(base, {})["reasoning"] = m

    deltas: dict[str, list[float]] = {}
    for _base, variants in pairs.items():
        nr = variants.get("non_reasoning")
        r = variants.get("reasoning")
        if not nr or not r:
            continue
        for field in ["intelligence_index", "coding_index", "math_index"]:
            nr_val = nr.get(field)
            r_val = r.get(field)
            if nr_val is not None and r_val is not None:
                deltas.setdefault(field, []).append(r_val - nr_val)

    result: dict[str, float] = {}
    for field, values in deltas.items():
        if len(values) >= 3:
            result[field] = statistics.median(values)
    return result


def compute_arena_thinking_delta(
    arena_rows: list[dict[str, Any]],
) -> float | None:
    ratings: dict[str, float] = {}
    for r in arena_rows:
        if r.get("category") == "overall" and r.get("rating"):
            ratings[r["model_name"]] = r["rating"]

    deltas: list[float] = []
    for name, rating in ratings.items():
        if "-thinking" in name.lower():
            base = re.sub(r"-thinking.*$", "", name.lower())
            for other, other_rating in ratings.items():
                if other.lower() == base:
                    deltas.append(rating - other_rating)
                    break

    if len(deltas) >= 3:
        return statistics.median(deltas)
    return None
