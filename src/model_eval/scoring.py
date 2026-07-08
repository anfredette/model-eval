from __future__ import annotations

import copy
import statistics
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from model_eval.categories import CATEGORY_MAP, display_name
from model_eval.models import CategoryFinding, CompositeScore, ModelScorecard, NormalizedScore
from model_eval.tiers import percentile_gap_significance
from model_eval.variants import detect_variant_delta


def _group_by_ties(
    sorted_items: list[tuple[str, float]],
    are_tied: Callable[[str, str], bool],
) -> list[list[tuple[str, float]]]:
    if not sorted_items:
        return []
    groups: list[list[tuple[str, float]]] = [[sorted_items[0]]]
    for item in sorted_items[1:]:
        anchor_name = groups[-1][0][0]
        if are_tied(anchor_name, item[0]):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _assign_percentiles(
    groups: list[list[tuple[str, float]]], total: int, source: str
) -> dict[str, NormalizedScore]:
    results: dict[str, NormalizedScore] = {}
    models_above = 0
    rank = 1
    for group in groups:
        group_size = len(group)
        percentile = ((total - models_above - 0.5 * group_size) / total) * 100
        for name, score in group:
            results[name] = NormalizedScore(
                raw_score=score,
                percentile=round(percentile, 2),
                tied_rank=rank,
                population_size=total,
                source=source,
            )
        models_above += group_size
        rank += 1
    return results


def _group_rows_by_category(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[r.get("category", "")].append(r)
    return grouped


def normalize_arena_category(
    rows: list[dict[str, Any]],
    category: str,
) -> dict[str, NormalizedScore]:
    cat_rows = [r for r in rows if r.get("category", category) == category]
    if not cat_rows:
        return {}

    items: list[tuple[str, float, float, float]] = []
    for r in cat_rows:
        rating = r.get("rating")
        if rating is None:
            continue
        lower = r.get("rating_lower", rating)
        upper = r.get("rating_upper", rating)
        items.append((r["model_name"], float(rating), float(lower), float(upper)))

    items.sort(key=lambda x: x[1], reverse=True)

    ci_lookup: dict[str, tuple[float, float]] = {
        name: (lower, upper) for name, _, lower, upper in items
    }
    sorted_pairs = [(name, score) for name, score, _, _ in items]

    def are_tied(anchor_name: str, candidate_name: str) -> bool:
        anchor_lower, anchor_upper = ci_lookup[anchor_name]
        candidate_lower, candidate_upper = ci_lookup[candidate_name]
        return candidate_upper >= anchor_lower and anchor_upper >= candidate_lower

    groups = _group_by_ties(sorted_pairs, are_tied)
    return _assign_percentiles(groups, len(sorted_pairs), "arena")


def normalize_aa_index(
    models: list[dict[str, Any]],
    index_field: str,
) -> dict[str, NormalizedScore]:
    items: list[tuple[str, float]] = []
    for m in models:
        val = m.get(index_field)
        if val is not None:
            items.append((m["name"], float(val)))

    if not items:
        return {}

    scores = [s for _, s in items]
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
    epsilon = 0.1 * stdev

    score_lookup: dict[str, float] = dict(items)
    items.sort(key=lambda x: x[1], reverse=True)

    def are_tied(anchor_name: str, candidate_name: str) -> bool:
        return abs(score_lookup[anchor_name] - score_lookup[candidate_name]) <= epsilon

    groups = _group_by_ties(items, are_tied)
    return _assign_percentiles(groups, len(items), "aa")


def compute_composite(
    category: str,
    arena_norm: NormalizedScore | None,
    aa_norm: NormalizedScore | None,
    arena_weight: float = 0.5,
    aa_weight: float = 0.5,
) -> CompositeScore:
    if arena_norm and aa_norm:
        pct = arena_weight * arena_norm.percentile + aa_weight * aa_norm.percentile
    elif arena_norm:
        pct = arena_norm.percentile
    elif aa_norm:
        pct = aa_norm.percentile
    else:
        pct = 0.0

    return CompositeScore(
        category=category,
        percentile=round(pct, 2),
        arena_score=arena_norm,
        aa_score=aa_norm,
    )


def apply_variant_adjustment(
    score: NormalizedScore, user_name: str, matched_name: str
) -> NormalizedScore:
    factor, description = detect_variant_delta(user_name, matched_name)
    if description is None:
        return score
    adjusted = copy.copy(score)
    adjusted.raw_score = round(score.raw_score * factor, 3)
    adjusted.confidence = 0.8
    adjusted.adjustment = description
    return adjusted


def compute_normalizations(
    arena_rows: list[dict[str, Any]],
    aa_models: list[dict[str, Any]],
    categories: list[str],
) -> tuple[dict[str, dict[str, NormalizedScore]], dict[str, dict[str, NormalizedScore]]]:
    """Compute per-category normalizations across the full population.

    Returns (arena_norms, aa_norms) where each is
    ``{category: {model_name: NormalizedScore}}``.
    """
    arena_norms: dict[str, dict[str, NormalizedScore]] = {}
    aa_norms: dict[str, dict[str, NormalizedScore]] = {}

    arena_by_category = _group_rows_by_category(arena_rows)

    for cat in categories:
        arena_cat, aa_field = CATEGORY_MAP.get(cat, (None, None))

        if arena_cat and arena_cat in arena_by_category:
            arena_norms[cat] = normalize_arena_category(arena_by_category[arena_cat], arena_cat)

        if aa_field:
            aa_norms[cat] = normalize_aa_index(aa_models, aa_field)

    return arena_norms, aa_norms


def compute_scorecards(
    arena_rows: list[dict[str, Any]],
    aa_models: list[dict[str, Any]],
    target_models: list[tuple[str, str | None, str | None]],
    categories: list[str],
    arena_weight: float = 0.5,
    aa_weight: float = 0.5,
) -> list[ModelScorecard]:
    arena_norms, aa_norms = compute_normalizations(arena_rows, aa_models, categories)

    scorecards: list[ModelScorecard] = []
    for display_name_str, arena_name, aa_name in target_models:
        cat_scores: dict[str, CompositeScore] = {}
        for cat in categories:
            a_score = arena_norms.get(cat, {}).get(arena_name) if arena_name else None
            aa_score = aa_norms.get(cat, {}).get(aa_name) if aa_name else None
            if a_score and arena_name:
                a_score = apply_variant_adjustment(a_score, display_name_str, arena_name)
            if aa_score and aa_name:
                aa_score = apply_variant_adjustment(aa_score, display_name_str, aa_name)
            if a_score or aa_score:
                cat_scores[cat] = compute_composite(cat, a_score, aa_score, arena_weight, aa_weight)

        overall = cat_scores.get("overall")
        scorecards.append(
            ModelScorecard(
                model_name=display_name_str,
                arena_name=arena_name,
                aa_name=aa_name,
                overall=overall,
                categories=cat_scores,
            )
        )

    return scorecards


def generate_category_findings(
    scorecards: list[ModelScorecard],
    categories: list[str],
) -> list[CategoryFinding]:
    """Generate cross-source findings for each category with data for 2+ models.

    All models with data in a category are included in ranked_models
    (sorted descending by percentile), not just the top and bottom.
    Gap description covers the spread from highest to lowest.
    """
    if len(scorecards) < 2:
        return []

    findings: list[CategoryFinding] = []

    for cat in categories:
        models_with_data: list[tuple[str, CompositeScore]] = []
        for sc in scorecards:
            cs = sc.categories.get(cat)
            if cs is not None:
                models_with_data.append((sc.model_name, cs))

        if len(models_with_data) < 2:
            continue

        models_with_data.sort(key=lambda x: x[1].percentile, reverse=True)
        ranked_models = [(name, cs.percentile) for name, cs in models_with_data]

        top_pct = models_with_data[0][1].percentile
        bottom_pct = models_with_data[-1][1].percentile
        gap = top_pct - bottom_pct
        gap_desc = percentile_gap_significance(gap)

        provenances = {cs.provenance for _, cs in models_with_data}
        if len(provenances) == 1:
            provenance = provenances.pop()
        else:
            provenance = "mixed"

        variant_notes: list[str] = []
        for model_name, cs in models_with_data:
            for score in [cs.arena_score, cs.aa_score]:
                if score and score.confidence < 1.0 and score.adjustment:
                    variant_notes.append(
                        f"{model_name}: {score.adjustment} (confidence: {score.confidence})"
                    )

        findings.append(
            CategoryFinding(
                category=cat,
                display_name=display_name(cat),
                ranked_models=ranked_models,
                gap_description=gap_desc,
                provenance=provenance,
                variant_notes=variant_notes,
            )
        )

    return findings
