from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator
from quality_scoring import MatchType, aa_client
from quality_scoring.resolver import MatchResult, resolve_model_names, suggest_similar
from quality_scoring.tiers import aa_gap_significance, tier_label

from model_eval import CACHE_DIR
from model_eval.models import (
    ComparisonTable,
    DistributionStats,
    ResolutionReport,
    SourceData,
)
from model_eval.sources import register_source

logger = logging.getLogger(__name__)

METHODOLOGY = """\
[Artificial Analysis](https://artificialanalysis.ai/) evaluates models using \
**automated benchmark suites** -- standardized tests with known correct answers, \
run programmatically. Their Intelligence Index (v4.1.1) aggregates scores from 9 \
evaluations across four categories:

- **Scientific Reasoning (24%):** GPQA Diamond, Humanity's Last Exam (HLE), CritPt
- **Coding (24%):** Terminal-Bench v2.1, SciCode
- **Agents (34%):** GDPval-AA v2, τ³-Banking
- **General (18%):** AA-LCR, AA-Omniscience

Unlike Arena's human preference votes, these benchmarks have **objectively \
correct answers**. This makes AA scores more precise for measurable capabilities \
(coding, math, factual recall) but less reflective of subjective qualities like \
writing style, helpfulness, or conversational fluency.

AA also independently measures **speed** (output tokens/sec), **latency** (time \
to first token), and **pricing** across API providers, providing a practical \
deployment perspective."""


class AAModel(BaseModel):
    """Flattens the V2 API nested structure into a flat model."""

    model_config = ConfigDict(extra="ignore")

    name: str
    slug: str
    organization: str = "Unknown"
    intelligence_index: int | None = None
    coding_index: int | None = None
    agentic_index: int | None = None
    speed_tps: float | None = None
    ttft_s: float | None = None
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None

    @model_validator(mode="before")
    @classmethod
    def flatten_nested(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        creator = data.get("model_creator")
        if isinstance(creator, dict):
            data.setdefault("organization", creator.get("name", "Unknown"))
        perf = data.get("performance")
        if isinstance(perf, dict):
            data.setdefault("speed_tps", perf.get("median_output_tokens_per_second"))
            data.setdefault("ttft_s", perf.get("median_time_to_first_token_seconds"))
        pricing = data.get("pricing")
        if isinstance(pricing, dict):
            data.setdefault("input_price_per_1m", pricing.get("price_1m_input_tokens"))
            data.setdefault("output_price_per_1m", pricing.get("price_1m_output_tokens"))
        return data

    @property
    def blended_price(self) -> float | None:
        if self.input_price_per_1m is not None and self.output_price_per_1m is not None:
            return round((3 * self.input_price_per_1m + self.output_price_per_1m) / 4, 2)
        return None


def _load_models(data_path: Path | None) -> tuple[list[AAModel], str]:
    if data_path is not None:
        with open(data_path) as f:
            raw = json.load(f)
        status = f"loaded from {data_path}"
    else:
        raw, fetched_at = aa_client.load_cache(cache_dir=CACHE_DIR)
        if not raw:
            api_key = os.environ.get("AA_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "No Artificial Analysis cache found and AA_API_KEY is not set. "
                    "Set AA_API_KEY in your environment for auto-sync, "
                    "or run 'model-eval sync-aa --api-key <key>'."
                )
            logger.info("No Artificial Analysis cache found, fetching from API...")
            try:
                count, _ = aa_client.sync(api_key, cache_dir=CACHE_DIR)
                logger.info("Synced %d models from Artificial Analysis API", count)
            except RuntimeError as e:
                raise RuntimeError(f"Artificial Analysis auto-sync failed: {e}") from e
            raw, fetched_at = aa_client.load_cache(cache_dir=CACHE_DIR)
            status = "fetched from API"
        elif aa_client.is_cache_stale(fetched_at):
            api_key = os.environ.get("AA_API_KEY")
            if api_key:
                logger.info("Artificial Analysis cache is stale, refreshing from API...")
                try:
                    count, _ = aa_client.sync(api_key, cache_dir=CACHE_DIR)
                    logger.info("Synced %d models from Artificial Analysis API", count)
                    raw, fetched_at = aa_client.load_cache(cache_dir=CACHE_DIR)
                    status = "refreshed from API"
                except Exception:
                    age = aa_client.cache_age_display(fetched_at) if fetched_at else "unknown"
                    logger.warning(
                        "Artificial Analysis auto-refresh failed, using stale cache (synced %s)",
                        age,
                    )
                    status = f"using stale cache (synced {age})"
            else:
                age = aa_client.cache_age_display(fetched_at) if fetched_at else "unknown"
                logger.warning(
                    "Artificial Analysis cache is stale (synced %s) but AA_API_KEY is not set"
                    " — using stale data",
                    age,
                )
                status = f"using stale cache (synced {age}, no AA_API_KEY)"
        else:
            assert fetched_at is not None
            status = f"using cache (synced {aa_client.cache_age_display(fetched_at)})"
    models = [m for m in (AAModel(**entry) for entry in raw) if m.intelligence_index is not None]
    return models, status


def _try_slug_match(models: list[AAModel], user_name: str) -> tuple[AAModel | None, MatchType]:
    slug_names = [m.slug for m in models]
    results = resolve_model_names([user_name], slug_names)
    mr = results[0]
    if mr.matched_name is not None:
        model = next(m for m in models if m.slug == mr.matched_name)
        return model, mr.match_type
    return None, MatchType.NONE


def _match_models(
    models: list[AAModel],
    names: list[str],
    *,
    families: bool = False,
    fuzzy: bool = False,
) -> tuple[list[AAModel], list[str], dict[str, str], dict[str, str], dict[str, list[str]]]:
    """Returns (matched_models, not_found, family_map, match_details, fuzzy_suggestions)."""
    if families:

        def _normalize(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", s.lower())

        matched: list[AAModel] = []
        not_found_families: list[str] = []
        family_map: dict[str, str] = {}
        for name in names:
            norm = _normalize(name)
            family_matches = [m for m in models if norm in _normalize(m.name)]
            if family_matches:
                matched.extend(family_matches)
                for m in family_matches:
                    family_map[m.name] = name
            else:
                not_found_families.append(name)
        deduped = list({m.name: m for m in matched}.values())
        return deduped, not_found_families, family_map, {}, {}

    model_by_name = {m.name: m for m in models}
    known_names = list(model_by_name.keys())
    match_results = resolve_model_names(names, known_names)

    found: list[AAModel] = []
    not_found_names: list[str] = []
    match_details: dict[str, str] = {}
    fuzzy_suggestions: dict[str, list[str]] = {}

    for mr in match_results:
        if mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT):
            assert mr.matched_name is not None
            found.append(model_by_name[mr.matched_name])
        elif mr.match_type == MatchType.FUZZY:
            assert mr.matched_name is not None
            slug_model, slug_type = _try_slug_match(models, mr.user_name)
            if slug_model is not None and slug_type in (MatchType.EXACT, MatchType.EQUIVALENT):
                found.append(slug_model)
                match_details[mr.user_name] = slug_model.name
            elif fuzzy:
                found.append(model_by_name[mr.matched_name])
                match_details[mr.user_name] = mr.matched_name
                logger.info(
                    'Model "%s" not found exactly in AA data. Used closest match "%s".',
                    mr.user_name,
                    mr.matched_name,
                )
            else:
                not_found_names.append(mr.user_name)
                candidates = [mr.matched_name]
                for s in suggest_similar(mr.user_name, known_names, n=3):
                    if s not in candidates:
                        candidates.append(s)
                fuzzy_suggestions[mr.user_name] = candidates[:3]
        else:
            slug_model, slug_type = _try_slug_match(models, mr.user_name)
            if slug_model is not None:
                found.append(slug_model)
                if slug_type in (MatchType.EXACT, MatchType.EQUIVALENT):
                    pass
                else:
                    match_details[mr.user_name] = slug_model.name
            else:
                not_found_names.append(mr.user_name)

    return found, not_found_names, {}, match_details, fuzzy_suggestions


def _comparison_table(models: list[AAModel], *, title: str) -> ComparisonTable:
    sorted_models = sorted(models, key=lambda m: m.intelligence_index or 0, reverse=True)

    has_coding = any(m.coding_index is not None for m in sorted_models)
    has_agentic = any(m.agentic_index is not None for m in sorted_models)

    headers: list[str] = ["Model", "AA Intelligence"]
    if has_coding:
        headers.append("Coding")
    if has_agentic:
        headers.append("Agentic")
    headers.extend(["Speed (t/s)", "TTFT (s)", "Price ($/1M blend)"])

    rows: list[list[str]] = []
    for m in sorted_models:
        speed = f"{m.speed_tps:.1f}" if m.speed_tps else "--"
        ttft = f"{m.ttft_s:.2f}" if m.ttft_s else "--"
        price = f"${m.blended_price:.2f}" if m.blended_price else "--"

        row: list[str] = [m.name, str(m.intelligence_index)]
        if has_coding:
            row.append(str(m.coding_index) if m.coding_index is not None else "--")
        if has_agentic:
            row.append(str(m.agentic_index) if m.agentic_index is not None else "--")
        row.extend([speed, ttft, price])
        rows.append(row)

    return ComparisonTable(
        title=title,
        headers=headers,
        rows=rows,
        alignments=["left"] + ["right"] * (len(headers) - 1),
    )


def _consolidated_ranking_table(
    all_models: list[AAModel], matched: list[AAModel], window: int = 5
) -> ComparisonTable:
    sorted_all = sorted(all_models, key=lambda m: m.intelligence_index or 0, reverse=True)
    total = len(sorted_all)
    target_names = {m.name for m in matched}

    positions: list[int] = []
    for i, m in enumerate(sorted_all):
        if m.name in target_names:
            positions.append(i)

    if not positions:
        return ComparisonTable(
            title="Global AA Rankings (no models found)",
            headers=[],
            rows=[],
        )

    ranges: list[tuple[int, int]] = []
    for pos in sorted(positions):
        start = max(0, pos - window)
        end = min(total - 1, pos + window)
        ranges.append((start, end))

    merged: list[tuple[int, int]] = [ranges[0]]
    for start, end in ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= 10:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    rows: list[list[str]] = []
    for seg_idx, (seg_start, seg_end) in enumerate(merged):
        if seg_idx > 0:
            prev_end = merged[seg_idx - 1][1]
            gap = seg_start - prev_end - 1
            rows.append(["", f"*[{gap} models not shown]*", ""])

        for i in range(seg_start, seg_end + 1):
            m = sorted_all[i]
            r = i + 1
            is_target = m.name in target_names
            fmt_rank = f"**{r}**" if is_target else str(r)
            fmt_name = f"**{m.name}**" if is_target else m.name
            fmt_score = f"**{m.intelligence_index}**" if is_target else str(m.intelligence_index)
            rows.append([fmt_rank, fmt_name, fmt_score])

    title = f"Global AA Rankings ({total} models total)"

    return ComparisonTable(
        title=title,
        headers=["Rank", "Model", "AA Intelligence"],
        rows=rows,
        alignments=["right", "left", "center"],
    )


def _ratio_qualifier(ratio: float) -> str:
    if ratio >= 3.0:
        return "dramatically"
    if ratio >= 2.0:
        return "significantly"
    if ratio >= 1.5:
        return "notably"
    return "moderately"


def _compute_findings(
    matched: list[AAModel],
    all_models: list[AAModel],
) -> tuple[list[str], DistributionStats | None]:
    findings: list[str] = []

    if not matched:
        return ["No matching models found in AA data."], None

    sorted_all = sorted(all_models, key=lambda m: m.intelligence_index or 0, reverse=True)
    total = len(sorted_all)

    dist_cache = aa_client.load_dist_cache(cache_dir=CACHE_DIR)
    dist_stats: DistributionStats | None = None
    population_stdev = 0.0
    if dist_cache and "stats" in dist_cache:
        s = dist_cache["stats"]
        dist_stats = DistributionStats(
            count=s["count"],
            min=s["min"],
            max=s["max"],
            median=s["median"],
            mean=s["mean"],
            stdev=s["stdev"],
            p25=s["p25"],
            p75=s["p75"],
        )
        population_stdev = s["stdev"]

    orgs: dict[str, list[AAModel]] = {}
    for m in matched:
        orgs.setdefault(m.organization, []).append(m)

    for org, models in orgs.items():
        best = max(models, key=lambda m: m.intelligence_index or 0)
        rank = next((i + 1 for i, m in enumerate(sorted_all) if m.name == best.name), None)
        tier_str = ""
        if rank:
            rank_str = f", ~rank {rank} of {total}"
            tier_str = f", {tier_label(rank)} tier"
        else:
            rank_str = ""
        findings.append(
            f"**{org}:** Top model is {best.name} "
            f"(Intelligence Index: {best.intelligence_index}{rank_str}){tier_str}. "
            f"{len(models)} model(s) evaluated."
        )

    if len(orgs) >= 2:
        org_list = list(orgs.values())
        a_best = max(org_list[0], key=lambda m: m.intelligence_index or 0)
        b_best = max(org_list[1], key=lambda m: m.intelligence_index or 0)

        a_score = a_best.intelligence_index or 0
        b_score = b_best.intelligence_index or 0
        if a_score != b_score:
            higher = a_best if a_score > b_score else b_best
            lower = b_best if higher == a_best else a_best
            h_score = higher.intelligence_index or 0
            l_score = lower.intelligence_index or 0
            gap = h_score - l_score
            gap_desc = aa_gap_significance(float(h_score), float(l_score), population_stdev)
            findings.append(
                f"**Intelligence:** {higher.name} scores {higher.intelligence_index} vs "
                f"{lower.name} at {lower.intelligence_index} "
                f"({gap} points, {gap_desc}). "
                f"For context, the top model in AA is {sorted_all[0].name} "
                f"at {sorted_all[0].intelligence_index}."
            )

        if a_best.coding_index is not None and b_best.coding_index is not None:
            higher_c = a_best if a_best.coding_index > b_best.coding_index else b_best
            lower_c = b_best if higher_c == a_best else a_best
            assert higher_c.coding_index is not None and lower_c.coding_index is not None
            gap = higher_c.coding_index - lower_c.coding_index
            gap_desc = aa_gap_significance(
                float(higher_c.coding_index),
                float(lower_c.coding_index),
                population_stdev,
            )
            findings.append(
                f"**Coding:** {higher_c.name} leads with Coding Index {higher_c.coding_index} vs "
                f"{lower_c.name} at {lower_c.coding_index} ({gap} points, {gap_desc})."
            )

        if a_best.speed_tps and b_best.speed_tps:
            faster = a_best if a_best.speed_tps > b_best.speed_tps else b_best
            slower = b_best if faster == a_best else a_best
            assert faster.speed_tps and slower.speed_tps
            ratio = faster.speed_tps / slower.speed_tps
            qualifier = _ratio_qualifier(ratio)
            findings.append(
                f"**Speed:** {faster.name} is {qualifier} faster at {ratio:.1f}x "
                f"({faster.speed_tps:.0f} vs {slower.speed_tps:.0f} t/s)."
            )

        if a_best.ttft_s and b_best.ttft_s:
            faster_ttft = a_best if a_best.ttft_s < b_best.ttft_s else b_best
            slower_ttft = b_best if faster_ttft == a_best else a_best
            assert slower_ttft.ttft_s and faster_ttft.ttft_s
            ratio = slower_ttft.ttft_s / faster_ttft.ttft_s
            qualifier = _ratio_qualifier(ratio)
            findings.append(
                f"**Latency:** {faster_ttft.name} has {qualifier} lower TTFT at {ratio:.1f}x "
                f"({faster_ttft.ttft_s:.2f}s vs {slower_ttft.ttft_s:.2f}s)."
            )

        if a_best.blended_price and b_best.blended_price:
            cheaper = a_best if a_best.blended_price < b_best.blended_price else b_best
            pricier = b_best if cheaper == a_best else a_best
            assert pricier.blended_price and cheaper.blended_price
            ratio = pricier.blended_price / cheaper.blended_price
            qualifier = _ratio_qualifier(ratio)
            findings.append(
                f"**Price:** {cheaper.name} is {qualifier} cheaper at {ratio:.1f}x "
                f"(${cheaper.blended_price:.2f} vs ${pricier.blended_price:.2f}/1M blended tokens)."
            )

    return findings, dist_stats


class ArtificialAnalysisSource:
    """Artificial Analysis data source."""

    def __init__(self, data_path: Path | None = None):
        self._data_path = data_path

    @property
    def name(self) -> str:
        return "Artificial Analysis"

    @property
    def description(self) -> str:
        return "Automated Benchmarks"

    def fetch_and_compare(
        self,
        model_names: list[str],
        *,
        families: bool = False,
        fuzzy: bool = False,
        **kwargs: Any,
    ) -> SourceData:
        all_models, cache_status = _load_models(self._data_path)
        matched, not_found, family_map, match_details, fuzzy_suggestions = _match_models(
            all_models, model_names, families=families, fuzzy=fuzzy
        )

        suggestions: dict[str, list[str]] = {}
        suggestions.update(fuzzy_suggestions)
        if not_found:
            available = [m.name for m in all_models]
            for name in not_found:
                if name not in suggestions:
                    matches = suggest_similar(name, available)
                    if matches:
                        suggestions[name] = matches

        if not matched:
            return SourceData(
                source_name=self.name,
                source_description=self.description,
                methodology=METHODOLOGY,
                models_found=[],
                models_not_found=not_found,
                suggestions=suggestions,
                findings=["No matching models found in Artificial Analysis data."],
                cache_status=cache_status,
            )

        orgs: dict[str, list[AAModel]] = {}
        for m in matched:
            orgs.setdefault(m.organization, []).append(m)

        global_rankings = [_consolidated_ranking_table(all_models, matched)]

        comparison_tables = [_comparison_table(matched, title="All Models")]

        findings, dist_stats = _compute_findings(matched, all_models)

        chart_models = [
            {
                "name": m.name,
                "score": float(m.intelligence_index or 0),
                "family": family_map.get(m.name, m.organization),
            }
            for m in matched
            if m.intelligence_index is not None
        ]

        return SourceData(
            source_name=self.name,
            source_description=self.description,
            methodology=METHODOLOGY,
            global_rankings=global_rankings,
            comparison_tables=comparison_tables,
            findings=findings,
            models_found=[m.name for m in matched],
            models_not_found=not_found,
            suggestions=suggestions,
            match_details=match_details,
            cache_status=cache_status,
            distribution_stats=dist_stats,
            chart_models=chart_models,
        )

    def resolve_names(self, model_names: list[str]) -> ResolutionReport:
        all_models, _ = _load_models(self._data_path)
        known_names = [m.name for m in all_models]
        results = resolve_model_names(model_names, known_names)

        slug_map = {m.slug: m.name for m in all_models}
        slug_names = list(slug_map.keys())
        enhanced: list[MatchResult] = []
        for mr in results:
            if mr.match_type in (MatchType.FUZZY, MatchType.NONE):
                slug_results = resolve_model_names([mr.user_name], slug_names)
                slug_mr = slug_results[0]
                if slug_mr.matched_name is not None and (
                    mr.match_type == MatchType.NONE
                    or slug_mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT)
                ):
                    real_name = slug_map[slug_mr.matched_name]
                    enhanced.append(MatchResult(mr.user_name, real_name, slug_mr.match_type))
                    continue
            enhanced.append(mr)

        return ResolutionReport(results=enhanced, available_names=known_names)


register_source("artificial_analysis", ArtificialAnalysisSource)
