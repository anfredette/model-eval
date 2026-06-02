from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import Any

from model_eval.categories import CATEGORY_MAP
from model_eval.models import CompositeScore, ModelScorecard, NormalizedScore


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


def normalize_arena_category(
    rows: list[dict[str, Any]],
    category: str,
) -> dict[str, NormalizedScore]:
    cat_rows = [r for r in rows if r["category"] == category]
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
        anchor_lower = ci_lookup[anchor_name][0]
        candidate_upper = ci_lookup[candidate_name][1]
        return candidate_upper >= anchor_lower

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
        provenance = "both"
    elif arena_norm:
        pct = arena_norm.percentile
        provenance = "arena_only"
    elif aa_norm:
        pct = aa_norm.percentile
        provenance = "aa_only"
    else:
        pct = 0.0
        provenance = "none"

    return CompositeScore(
        category=category,
        percentile=round(pct, 2),
        arena_score=arena_norm,
        aa_score=aa_norm,
        provenance=provenance,
    )


def compute_scorecards(
    arena_rows: list[dict[str, Any]],
    aa_models: list[dict[str, Any]],
    target_models: list[tuple[str, str | None, str | None]],
    categories: list[str],
    arena_weight: float = 0.5,
    aa_weight: float = 0.5,
) -> list[ModelScorecard]:
    arena_norms: dict[str, dict[str, NormalizedScore]] = {}
    aa_norms: dict[str, dict[str, NormalizedScore]] = {}

    for cat in categories:
        arena_cat, aa_field = CATEGORY_MAP.get(cat, (None, None))

        if arena_cat:
            norms = normalize_arena_category(arena_rows, arena_cat)
            arena_norms[cat] = norms

        if aa_field:
            norms = normalize_aa_index(aa_models, aa_field)
            aa_norms[cat] = norms

    scorecards: list[ModelScorecard] = []
    for display_name, arena_name, aa_name in target_models:
        cat_scores: dict[str, CompositeScore] = {}
        for cat in categories:
            a_score = arena_norms.get(cat, {}).get(arena_name) if arena_name else None
            aa_score = aa_norms.get(cat, {}).get(aa_name) if aa_name else None
            if a_score or aa_score:
                cat_scores[cat] = compute_composite(
                    cat, a_score, aa_score, arena_weight, aa_weight
                )

        overall = cat_scores.get("overall")
        scorecards.append(
            ModelScorecard(
                model_name=display_name,
                arena_name=arena_name,
                aa_name=aa_name,
                overall=overall,
                categories=cat_scores,
            )
        )

    return scorecards
