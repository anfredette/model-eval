"""Programmatic scoring API.

ScoringEngine pre-computes normalizations across the full population once,
then supports cheap per-model lookups.  This is the primary API for external
consumers (e.g. llm-d-planner); the CLI delegates to it via build_scorecards().
"""

from __future__ import annotations

from typing import Any, NamedTuple

from model_eval import aa_client, arena_client
from model_eval.categories import DEFAULT_CATEGORIES
from model_eval.models import CompositeScore, MatchType, ModelScorecard, NormalizedScore
from model_eval.resolver import resolve_model_names
from model_eval.scoring import (
    apply_variant_adjustment,
    compute_composite,
    compute_normalizations,
)


class _ResolvedModel(NamedTuple):
    display_name: str
    arena_name: str | None
    aa_name: str | None
    arena_match_type: MatchType | None
    aa_match_type: MatchType | None


class ScoringEngine:
    """Pre-loads data and normalizations; provides per-model score lookup.

    Construct once with source data (or let it load from cache), then call
    ``get_scores`` / ``get_scores_batch`` any number of times.
    """

    def __init__(
        self,
        arena_rows: list[dict[str, Any]] | None = None,
        aa_models: list[dict[str, Any]] | None = None,
        categories: list[str] | None = None,
        arena_weight: float = 0.5,
        aa_weight: float = 0.5,
    ) -> None:
        if arena_weight < 0 or aa_weight < 0:
            raise ValueError("Weights must be non-negative.")
        if arena_weight == 0 and aa_weight == 0:
            raise ValueError("At least one weight must be positive.")

        if arena_rows is None:
            arena_rows, _ = arena_client.load_cache()
        if aa_models is None:
            aa_models, _ = aa_client.load_cache()

        self._arena_rows = arena_rows
        self._aa_models = aa_models
        self._categories = categories or DEFAULT_CATEGORIES
        self._arena_weight = arena_weight
        self._aa_weight = aa_weight

        self._arena_names = sorted(
            {r["model_name"] for r in self._arena_rows if r.get("category") == "overall"}
        )
        self._aa_names = sorted({m["name"] for m in self._aa_models})

        self._arena_norms, self._aa_norms = compute_normalizations(
            self._arena_rows, self._aa_models, self._categories
        )

    def _resolve_and_filter(
        self,
        model_names: list[str],
        fuzzy: bool,
    ) -> list[_ResolvedModel]:
        arena_results = (
            resolve_model_names(model_names, self._arena_names) if self._arena_names else []
        )
        aa_results = resolve_model_names(model_names, self._aa_names) if self._aa_names else []

        accepted: list[_ResolvedModel] = []
        for i, name in enumerate(model_names):
            arena_match: str | None = None
            arena_mt: MatchType | None = None
            aa_match: str | None = None
            aa_mt: MatchType | None = None

            if arena_results:
                mr = arena_results[i]
                if mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT) or (
                    fuzzy and mr.match_type == MatchType.FUZZY and mr.matched_name
                ):
                    arena_match = mr.matched_name
                    arena_mt = mr.match_type

            if aa_results:
                mr = aa_results[i]
                if mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT) or (
                    fuzzy and mr.match_type == MatchType.FUZZY and mr.matched_name
                ):
                    aa_match = mr.matched_name
                    aa_mt = mr.match_type

            if arena_match or aa_match:
                accepted.append(_ResolvedModel(name, arena_match, aa_match, arena_mt, aa_mt))

        return accepted

    def _build_scorecard(self, resolved: _ResolvedModel) -> ModelScorecard:
        cat_scores: dict[str, CompositeScore] = {}
        for cat in self._categories:
            a_score: NormalizedScore | None = (
                self._arena_norms.get(cat, {}).get(resolved.arena_name)
                if resolved.arena_name
                else None
            )
            aa_score: NormalizedScore | None = (
                self._aa_norms.get(cat, {}).get(resolved.aa_name)
                if resolved.aa_name
                else None
            )

            if a_score and resolved.arena_name:
                a_score = apply_variant_adjustment(
                    a_score, resolved.display_name, resolved.arena_name
                )
            if aa_score and resolved.aa_name:
                aa_score = apply_variant_adjustment(
                    aa_score, resolved.display_name, resolved.aa_name
                )

            if a_score or aa_score:
                cat_scores[cat] = compute_composite(
                    cat, a_score, aa_score, self._arena_weight, self._aa_weight
                )

        return ModelScorecard(
            model_name=resolved.display_name,
            arena_name=resolved.arena_name,
            aa_name=resolved.aa_name,
            arena_match_type=resolved.arena_match_type,
            aa_match_type=resolved.aa_match_type,
            overall=cat_scores.get("overall"),
            categories=cat_scores,
        )

    def get_scores(self, model_name: str, *, fuzzy: bool = False) -> ModelScorecard | None:
        """Return all scores for a single model, or ``None`` if not found."""
        resolved = self._resolve_and_filter([model_name], fuzzy)
        if not resolved:
            return None
        return self._build_scorecard(resolved[0])

    def get_scores_batch(
        self, model_names: list[str], *, fuzzy: bool = False
    ) -> list[ModelScorecard]:
        """Return scores for multiple models.  Only includes models that resolved."""
        resolved = self._resolve_and_filter(model_names, fuzzy)
        return [self._build_scorecard(r) for r in resolved]
