from __future__ import annotations

import pytest

from model_eval.engine import ScoringEngine
from model_eval.models import MatchType


def _make_arena_rows() -> list[dict]:
    """Minimal arena data: 3 models, 2 categories, non-overlapping CIs."""
    models = [
        ("Alpha", 1500, 1495, 1505),
        ("Beta", 1400, 1395, 1405),
        ("Gamma", 1300, 1295, 1305),
    ]
    rows = []
    for name, rating, lo, hi in models:
        for cat in ("overall", "coding"):
            rows.append(
                {
                    "model_name": name,
                    "category": cat,
                    "rating": rating,
                    "rating_lower": lo,
                    "rating_upper": hi,
                }
            )
    return rows


def _make_aa_models() -> list[dict]:
    """Minimal AA data: 3 models with intelligence_index and coding_index."""
    return [
        {"name": "Alpha", "intelligence_index": 90, "coding_index": 85},
        {"name": "Beta", "intelligence_index": 80, "coding_index": 75},
        {"name": "Gamma", "intelligence_index": 70, "coding_index": 65},
    ]


class TestGetScores:
    def test_exact_match_both_sources(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.model_name == "Alpha"
        assert sc.arena_name == "Alpha"
        assert sc.aa_name == "Alpha"
        assert sc.arena_match_type == MatchType.EXACT
        assert sc.aa_match_type == MatchType.EXACT
        assert sc.overall is not None
        assert sc.overall.arena_score is not None
        assert sc.overall.aa_score is not None
        assert sc.overall.provenance == "both"

    def test_single_source_arena_only(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=[],
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.overall is not None
        assert sc.overall.arena_score is not None
        assert sc.overall.aa_score is None
        assert sc.overall.provenance == "arena_only"

    def test_single_source_aa_only(self):
        engine = ScoringEngine(
            arena_rows=[],
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.overall is not None
        assert sc.overall.arena_score is None
        assert sc.overall.aa_score is not None
        assert sc.overall.provenance == "aa_only"

    def test_not_found(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        assert engine.get_scores("NonExistentModel") is None

    def test_fuzzy_disabled_rejects_fuzzy_match(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=[],
            categories=["overall"],
        )
        assert engine.get_scores("Alpha-instruct", fuzzy=False) is None

    def test_fuzzy_enabled_accepts_fuzzy_match(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=[],
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha-instruct", fuzzy=True)
        assert sc is not None
        assert sc.model_name == "Alpha-instruct"
        assert sc.arena_name == "Alpha"
        assert sc.arena_match_type == MatchType.FUZZY

    def test_multiple_categories(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall", "coding"],
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert "overall" in sc.categories
        assert "coding" in sc.categories

    def test_custom_categories_limits_output(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["coding"],
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert "coding" in sc.categories
        assert "overall" not in sc.categories
        assert sc.overall is None


class TestGetScoresBatch:
    def test_multiple_models(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        results = engine.get_scores_batch(["Alpha", "Beta", "Gamma"])
        assert len(results) == 3
        names = [sc.model_name for sc in results]
        assert names == ["Alpha", "Beta", "Gamma"]

    def test_partial_matches(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        results = engine.get_scores_batch(["Alpha", "NoSuchModel", "Gamma"])
        assert len(results) == 2
        names = [sc.model_name for sc in results]
        assert "Alpha" in names
        assert "Gamma" in names

    def test_empty_input(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        assert engine.get_scores_batch([]) == []


class TestWeights:
    def test_arena_only_weight(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
            arena_weight=1.0,
            aa_weight=0.0,
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.overall is not None
        assert sc.overall.percentile == sc.overall.arena_score.percentile

    def test_aa_only_weight(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
            arena_weight=0.0,
            aa_weight=1.0,
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.overall is not None
        assert sc.overall.percentile == sc.overall.aa_score.percentile

    def test_custom_weights(self):
        aa_models = [
            {"name": "Alpha", "intelligence_index": 70, "coding_index": 65},
            {"name": "Beta", "intelligence_index": 80, "coding_index": 75},
            {"name": "Gamma", "intelligence_index": 90, "coding_index": 85},
        ]
        engine_equal = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=aa_models,
            categories=["overall"],
            arena_weight=0.5,
            aa_weight=0.5,
        )
        engine_arena_heavy = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=aa_models,
            categories=["overall"],
            arena_weight=0.8,
            aa_weight=0.2,
        )
        sc_equal = engine_equal.get_scores("Alpha")
        sc_heavy = engine_arena_heavy.get_scores("Alpha")
        assert sc_equal is not None and sc_heavy is not None
        assert sc_equal.overall is not None and sc_heavy.overall is not None
        assert sc_equal.overall.percentile != sc_heavy.overall.percentile


class TestCacheLoading:
    def test_loads_from_cache_when_data_not_provided(self, monkeypatch):
        arena_rows = _make_arena_rows()
        aa_models = _make_aa_models()
        monkeypatch.setattr(
            "model_eval.engine.arena_client.load_cache",
            lambda: (arena_rows, "2025-01-01T00:00:00Z"),
        )
        monkeypatch.setattr(
            "model_eval.engine.aa_client.load_cache",
            lambda: (aa_models, "2025-01-01T00:00:00Z"),
        )

        engine = ScoringEngine(categories=["overall"])
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.overall is not None


class TestPercentileOrdering:
    def test_higher_score_gets_higher_percentile(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        results = engine.get_scores_batch(["Alpha", "Beta", "Gamma"])
        pcts = [sc.overall.percentile for sc in results]
        assert pcts[0] > pcts[1] > pcts[2]

    def test_raw_scores_preserved(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha")
        assert sc is not None
        assert sc.overall.arena_score.raw_score == 1500
        assert sc.overall.aa_score.raw_score == 90


class TestVariantAdjustment:
    def test_quantized_variant_gets_discounted(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=[],
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha-quantized.w4a16", fuzzy=True)
        assert sc is not None
        assert sc.overall is not None
        assert sc.overall.arena_score.confidence == 0.8
        assert sc.overall.arena_score.adjustment is not None
        assert sc.overall.arena_score.raw_score < 1500

    def test_fp8_variant_no_penalty(self):
        engine = ScoringEngine(
            arena_rows=_make_arena_rows(),
            aa_models=_make_aa_models(),
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha-FP8")
        assert sc is not None
        assert sc.overall is not None
        assert sc.overall.arena_score.raw_score == 1500


class TestEmptyData:
    def test_both_sources_empty(self):
        engine = ScoringEngine(
            arena_rows=[],
            aa_models=[],
            categories=["overall"],
        )
        assert engine.get_scores("anything") is None
        assert engine.get_scores_batch(["a", "b"]) == []


class TestMixedMatchTypes:
    def test_exact_in_one_fuzzy_in_other_without_flag(self):
        """Model is EXACT in AA but FUZZY in Arena — Arena match rejected."""
        arena_rows = _make_arena_rows()
        aa_models = [
            {"name": "Alpha-instruct", "intelligence_index": 90, "coding_index": 85},
        ]
        engine = ScoringEngine(
            arena_rows=arena_rows,
            aa_models=aa_models,
            categories=["overall"],
        )
        sc = engine.get_scores("Alpha-instruct", fuzzy=False)
        assert sc is not None
        assert sc.aa_name == "Alpha-instruct"
        assert sc.aa_match_type == MatchType.EXACT
        assert sc.arena_name is None


class TestWeightValidation:
    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            ScoringEngine(
                arena_rows=_make_arena_rows(),
                aa_models=_make_aa_models(),
                arena_weight=-1.0,
            )

    def test_both_zero_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            ScoringEngine(
                arena_rows=_make_arena_rows(),
                aa_models=_make_aa_models(),
                arena_weight=0.0,
                aa_weight=0.0,
            )
