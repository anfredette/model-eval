from __future__ import annotations

from model_eval.models import (
    CategoryFinding,
    ComparisonResult,
    CompositeScore,
    MatchType,
    ModelScorecard,
    NormalizedScore,
)
from model_eval.scoring import (
    compute_composite,
    compute_scorecards,
    generate_category_findings,
    normalize_aa_index,
    normalize_arena_category,
)


class TestNormalizeArenaCategory:
    def test_basic_ranking(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "B", "category": "overall", "rating": 1400, "rating_lower": 1395, "rating_upper": 1405},
            {"model_name": "C", "category": "overall", "rating": 1300, "rating_lower": 1295, "rating_upper": 1305},
        ]
        result = normalize_arena_category(rows, "overall")
        assert result["A"].percentile > result["B"].percentile > result["C"].percentile

    def test_tied_models_via_ci_overlap(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1490, "rating_upper": 1510},
            {"model_name": "B", "category": "overall", "rating": 1498, "rating_lower": 1488, "rating_upper": 1508},
            {"model_name": "C", "category": "overall", "rating": 1300, "rating_lower": 1290, "rating_upper": 1310},
        ]
        result = normalize_arena_category(rows, "overall")
        assert result["A"].percentile == result["B"].percentile
        assert result["A"].tied_rank == result["B"].tied_rank
        assert result["C"].percentile < result["A"].percentile

    def test_no_overlap_means_not_tied(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1498, "rating_upper": 1502},
            {"model_name": "B", "category": "overall", "rating": 1400, "rating_lower": 1398, "rating_upper": 1402},
        ]
        result = normalize_arena_category(rows, "overall")
        assert result["A"].percentile != result["B"].percentile

    def test_filters_by_category(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "B", "category": "coding", "rating": 1400, "rating_lower": 1395, "rating_upper": 1405},
        ]
        result = normalize_arena_category(rows, "overall")
        assert "A" in result
        assert "B" not in result

    def test_empty_category(self):
        result = normalize_arena_category([], "overall")
        assert result == {}

    def test_single_model(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        result = normalize_arena_category(rows, "overall")
        assert result["A"].percentile == 50.0

    def test_population_size_set(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "B", "category": "overall", "rating": 1400, "rating_lower": 1395, "rating_upper": 1405},
        ]
        result = normalize_arena_category(rows, "overall")
        assert result["A"].population_size == 2
        assert result["B"].population_size == 2

    def test_source_is_arena(self):
        rows = [
            {"model_name": "A", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        result = normalize_arena_category(rows, "overall")
        assert result["A"].source == "arena"


class TestNormalizeAAIndex:
    def test_basic_ranking(self):
        models = [
            {"name": "A", "intelligence_index": 60},
            {"name": "B", "intelligence_index": 40},
            {"name": "C", "intelligence_index": 20},
        ]
        result = normalize_aa_index(models, "intelligence_index")
        assert result["A"].percentile > result["B"].percentile > result["C"].percentile

    def test_tied_within_epsilon(self):
        models = [
            {"name": f"m{i}", "intelligence_index": v}
            for i, v in enumerate([60, 59, 40, 39, 20, 19, 10, 5])
        ]
        result = normalize_aa_index(models, "intelligence_index")
        assert result["m0"].percentile == result["m1"].percentile
        assert result["m2"].percentile == result["m3"].percentile
        assert result["m4"].percentile == result["m5"].percentile
        assert result["m0"].percentile > result["m2"].percentile > result["m4"].percentile

    def test_skips_none_values(self):
        models = [
            {"name": "A", "intelligence_index": 60},
            {"name": "B", "intelligence_index": None},
            {"name": "C", "intelligence_index": 20},
        ]
        result = normalize_aa_index(models, "intelligence_index")
        assert "A" in result
        assert "B" not in result
        assert result["A"].population_size == 2

    def test_empty_list(self):
        result = normalize_aa_index([], "intelligence_index")
        assert result == {}

    def test_single_model(self):
        models = [{"name": "A", "intelligence_index": 50}]
        result = normalize_aa_index(models, "intelligence_index")
        assert result["A"].percentile == 50.0

    def test_source_is_aa(self):
        models = [{"name": "A", "intelligence_index": 50}]
        result = normalize_aa_index(models, "intelligence_index")
        assert result["A"].source == "aa"

    def test_coding_index(self):
        models = [
            {"name": "A", "coding_index": 55},
            {"name": "B", "coding_index": 30},
        ]
        result = normalize_aa_index(models, "coding_index")
        assert result["A"].percentile > result["B"].percentile

    def test_all_same_score_all_tied(self):
        models = [
            {"name": "A", "intelligence_index": 20},
            {"name": "B", "intelligence_index": 20},
            {"name": "C", "intelligence_index": 20},
        ]
        result = normalize_aa_index(models, "intelligence_index")
        assert result["A"].percentile == result["B"].percentile == result["C"].percentile
        assert result["A"].percentile == 50.0


class TestComputeComposite:
    def test_both_sources(self):
        arena = NormalizedScore(raw_score=1500, percentile=90.0, tied_rank=1, population_size=100, source="arena")
        aa = NormalizedScore(raw_score=60, percentile=80.0, tied_rank=1, population_size=100, source="aa")
        result = compute_composite("overall", arena, aa)
        assert result.percentile == 85.0
        assert result.provenance == "both"

    def test_arena_only(self):
        arena = NormalizedScore(raw_score=1500, percentile=90.0, tied_rank=1, population_size=100, source="arena")
        result = compute_composite("coding", arena, None)
        assert result.percentile == 90.0
        assert result.provenance == "arena_only"

    def test_aa_only(self):
        aa = NormalizedScore(raw_score=60, percentile=80.0, tied_rank=1, population_size=100, source="aa")
        result = compute_composite("overall", None, aa)
        assert result.percentile == 80.0
        assert result.provenance == "aa_only"

    def test_neither_source(self):
        result = compute_composite("overall", None, None)
        assert result.percentile == 0.0
        assert result.provenance == "none"

    def test_custom_weights(self):
        arena = NormalizedScore(raw_score=1500, percentile=100.0, tied_rank=1, population_size=100, source="arena")
        aa = NormalizedScore(raw_score=60, percentile=0.0, tied_rank=1, population_size=100, source="aa")
        result = compute_composite("overall", arena, aa, arena_weight=0.7, aa_weight=0.3)
        assert result.percentile == 70.0


class TestComputeScorecards:
    def test_basic_scorecard(self):
        arena_rows = [
            {"model_name": "model-a", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "model-b", "category": "overall", "rating": 1400, "rating_lower": 1395, "rating_upper": 1405},
        ]
        aa_models = [
            {"name": "Model A", "intelligence_index": 60},
            {"name": "Model B", "intelligence_index": 40},
        ]
        targets = [("Model A", "model-a", "Model A")]
        result = compute_scorecards(arena_rows, aa_models, targets, ["overall"])
        assert len(result) == 1
        sc = result[0]
        assert sc.model_name == "Model A"
        assert sc.overall is not None
        assert sc.overall.provenance == "both"

    def test_arena_only_model(self):
        arena_rows = [
            {"model_name": "model-a", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        targets = [("Model A", "model-a", None)]
        result = compute_scorecards(arena_rows, [], targets, ["overall"])
        sc = result[0]
        assert sc.overall is not None
        assert sc.overall.provenance == "arena_only"

    def test_multiple_categories(self):
        arena_rows = [
            {"model_name": "a", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "a", "category": "coding", "rating": 1480, "rating_lower": 1475, "rating_upper": 1485},
        ]
        aa_models = [
            {"name": "A", "intelligence_index": 60, "coding_index": 55},
        ]
        targets = [("A", "a", "A")]
        result = compute_scorecards(arena_rows, aa_models, targets, ["overall", "coding"])
        sc = result[0]
        assert "overall" in sc.categories
        assert "coding" in sc.categories

    def test_model_not_in_source(self):
        arena_rows = [
            {"model_name": "other", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        targets = [("Missing", None, None)]
        result = compute_scorecards(arena_rows, [], targets, ["overall"])
        sc = result[0]
        assert sc.overall is None


class TestCategoryFinding:
    def test_construction(self):
        f = CategoryFinding(
            category="coding",
            display_name="Coding",
            ranked_models=[("model-a", 96.1), ("model-b", 82.3)],
            gap_description="clear separation",
            provenance="both",
            variant_notes=[],
        )
        assert f.category == "coding"
        assert f.ranked_models[0] == ("model-a", 96.1)
        assert f.gap_description == "clear separation"

    def test_with_variant_notes(self):
        f = CategoryFinding(
            category="overall",
            display_name="Overall",
            ranked_models=[("model-a", 94.2), ("model-b", 91.5)],
            gap_description="effectively equivalent",
            provenance="both",
            variant_notes=["model-a: instruct variant (confidence: 0.97)"],
        )
        assert len(f.variant_notes) == 1

    def test_three_models(self):
        f = CategoryFinding(
            category="overall",
            display_name="Overall",
            ranked_models=[("a", 96.0), ("b", 85.0), ("c", 70.0)],
            gap_description="clear separation",
            provenance="both",
            variant_notes=[],
        )
        assert len(f.ranked_models) == 3
        assert f.ranked_models[0][0] == "a"
        assert f.ranked_models[-1][0] == "c"


class TestModelScorecardMatchType:
    def test_default_match_types_are_none(self):
        sc = ModelScorecard(
            model_name="test",
            arena_name=None,
            aa_name=None,
            overall=None,
        )
        assert sc.arena_match_type is None
        assert sc.aa_match_type is None

    def test_match_types_set(self):
        sc = ModelScorecard(
            model_name="test",
            arena_name="test-arena",
            aa_name="Test AA",
            arena_match_type=MatchType.EXACT,
            aa_match_type=MatchType.EQUIVALENT,
            overall=None,
        )
        assert sc.arena_match_type == MatchType.EXACT
        assert sc.aa_match_type == MatchType.EQUIVALENT


class TestComparisonResultNewFields:
    def test_default_scorecards_empty(self):
        r = ComparisonResult(model_names=["a"])
        assert r.scorecards == []
        assert r.category_findings == []
        assert r.arena_weight == 0.5
        assert r.aa_weight == 0.5


class TestGenerateCategoryFindings:
    def _make_scorecard(self, name, overall_pct, coding_pct=None, provenance="both"):
        arena_score = NormalizedScore(
            raw_score=1500, percentile=overall_pct, tied_rank=1,
            population_size=100, source="arena",
        )
        aa_score = NormalizedScore(
            raw_score=60, percentile=overall_pct, tied_rank=1,
            population_size=100, source="aa",
        ) if provenance == "both" else None

        categories = {
            "overall": CompositeScore(
                category="overall", percentile=overall_pct,
                arena_score=arena_score,
                aa_score=aa_score,
            ),
        }
        if coding_pct is not None:
            categories["coding"] = CompositeScore(
                category="coding", percentile=coding_pct,
                arena_score=arena_score, aa_score=aa_score,
            )

        return ModelScorecard(
            model_name=name, arena_name=name, aa_name=name,
            overall=categories["overall"], categories=categories,
        )

    def test_two_models_one_category(self):
        sc_a = self._make_scorecard("model-a", 94.2)
        sc_b = self._make_scorecard("model-b", 82.3)
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, CategoryFinding)
        assert f.category == "overall"
        assert len(f.ranked_models) == 2
        assert f.ranked_models[0] == ("model-a", 94.2)
        assert f.ranked_models[1] == ("model-b", 82.3)

    def test_three_models_all_present(self):
        sc_a = self._make_scorecard("a", 96.0)
        sc_b = self._make_scorecard("b", 85.0)
        sc_c = self._make_scorecard("c", 70.0)
        findings = generate_category_findings([sc_a, sc_b, sc_c], ["overall"])
        assert len(findings) == 1
        f = findings[0]
        assert len(f.ranked_models) == 3
        assert f.ranked_models[0] == ("a", 96.0)
        assert f.ranked_models[1] == ("b", 85.0)
        assert f.ranked_models[2] == ("c", 70.0)

    def test_gap_description_uses_top_to_bottom_spread(self):
        sc_a = self._make_scorecard("a", 96.0)
        sc_b = self._make_scorecard("b", 70.0)
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert findings[0].gap_description == "clear separation"

    def test_gap_description_moderate(self):
        sc_a = self._make_scorecard("a", 90.0)
        sc_b = self._make_scorecard("b", 80.0)
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert findings[0].gap_description == "moderate advantage"

    def test_gap_description_equivalent(self):
        sc_a = self._make_scorecard("a", 92.0)
        sc_b = self._make_scorecard("b", 90.0)
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert findings[0].gap_description == "effectively equivalent"

    def test_multiple_categories(self):
        sc_a = self._make_scorecard("a", 94.0, coding_pct=96.0)
        sc_b = self._make_scorecard("b", 82.0, coding_pct=70.0)
        findings = generate_category_findings([sc_a, sc_b], ["overall", "coding"])
        assert len(findings) == 2
        cats = [f.category for f in findings]
        assert "overall" in cats
        assert "coding" in cats

    def test_skips_category_with_single_model(self):
        sc_a = self._make_scorecard("a", 94.0, coding_pct=96.0)
        sc_b = self._make_scorecard("b", 82.0, coding_pct=None)
        findings = generate_category_findings([sc_a, sc_b], ["overall", "coding"])
        cats = [f.category for f in findings]
        assert "overall" in cats
        assert "coding" not in cats

    def test_provenance_tracked(self):
        arena_only = NormalizedScore(
            raw_score=1500, percentile=90.0, tied_rank=1,
            population_size=100, source="arena",
        )
        sc_a = ModelScorecard(
            model_name="a", arena_name="a", aa_name=None,
            overall=CompositeScore(
                category="overall", percentile=90.0,
                arena_score=arena_only, aa_score=None,
            ),
            categories={"overall": CompositeScore(
                category="overall", percentile=90.0,
                arena_score=arena_only, aa_score=None,
            )},
        )
        sc_b = ModelScorecard(
            model_name="b", arena_name="b", aa_name=None,
            overall=CompositeScore(
                category="overall", percentile=70.0,
                arena_score=arena_only, aa_score=None,
            ),
            categories={"overall": CompositeScore(
                category="overall", percentile=70.0,
                arena_score=arena_only, aa_score=None,
            )},
        )
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert findings[0].provenance == "arena_only"

    def test_mixed_provenance(self):
        arena_score = NormalizedScore(
            raw_score=1500, percentile=90.0, tied_rank=1,
            population_size=100, source="arena",
        )
        aa_score = NormalizedScore(
            raw_score=60, percentile=85.0, tied_rank=1,
            population_size=100, source="aa",
        )
        sc_a = ModelScorecard(
            model_name="a", arena_name="a", aa_name="A",
            overall=CompositeScore(
                category="overall", percentile=90.0,
                arena_score=arena_score, aa_score=aa_score,
            ),
            categories={"overall": CompositeScore(
                category="overall", percentile=90.0,
                arena_score=arena_score, aa_score=aa_score,
            )},
        )
        sc_b = ModelScorecard(
            model_name="b", arena_name="b", aa_name=None,
            overall=CompositeScore(
                category="overall", percentile=70.0,
                arena_score=arena_score, aa_score=None,
            ),
            categories={"overall": CompositeScore(
                category="overall", percentile=70.0,
                arena_score=arena_score, aa_score=None,
            )},
        )
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert findings[0].provenance == "mixed"

    def test_variant_notes_included(self):
        adjusted = NormalizedScore(
            raw_score=1450, percentile=85.0, tied_rank=2,
            population_size=100, source="arena",
            confidence=0.8, adjustment="instruct variant",
        )
        sc_a = ModelScorecard(
            model_name="a", arena_name="a", aa_name=None,
            overall=CompositeScore(
                category="overall", percentile=90.0,
                arena_score=NormalizedScore(
                    raw_score=1500, percentile=90.0, tied_rank=1,
                    population_size=100, source="arena",
                ),
                aa_score=None,
            ),
            categories={"overall": CompositeScore(
                category="overall", percentile=90.0,
                arena_score=NormalizedScore(
                    raw_score=1500, percentile=90.0, tied_rank=1,
                    population_size=100, source="arena",
                ),
                aa_score=None,
            )},
        )
        sc_b = ModelScorecard(
            model_name="b", arena_name="b", aa_name=None,
            overall=CompositeScore(
                category="overall", percentile=85.0,
                arena_score=adjusted, aa_score=None,
            ),
            categories={"overall": CompositeScore(
                category="overall", percentile=85.0,
                arena_score=adjusted, aa_score=None,
            )},
        )
        findings = generate_category_findings([sc_a, sc_b], ["overall"])
        assert len(findings[0].variant_notes) == 1
        assert "instruct variant" in findings[0].variant_notes[0]

    def test_empty_scorecards(self):
        findings = generate_category_findings([], ["overall"])
        assert findings == []
