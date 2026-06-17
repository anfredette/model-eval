from __future__ import annotations

from pathlib import Path

import pytest

from model_eval.models import (
    CategoryFinding,
    ComparisonResult,
    ComparisonTable,
    CompositeScore,
    HeadToHead,
    MatchType,
    ModelScorecard,
    NormalizedScore,
    SourceData,
)
from model_eval.renderer import render_comparison


def _make_result_with_scorecards() -> ComparisonResult:
    """Standalone factory — does not depend on _make_result()."""
    arena_score_a = NormalizedScore(
        raw_score=1500.0,
        percentile=95.0,
        tied_rank=1,
        population_size=100,
        source="arena",
    )
    aa_score_a = NormalizedScore(
        raw_score=60,
        percentile=90.0,
        tied_rank=1,
        population_size=100,
        source="aa",
    )
    arena_score_b = NormalizedScore(
        raw_score=1400.0,
        percentile=80.0,
        tied_rank=5,
        population_size=100,
        source="arena",
    )
    aa_score_b = NormalizedScore(
        raw_score=40,
        percentile=70.0,
        tied_rank=5,
        population_size=100,
        source="aa",
    )

    sc_a = ModelScorecard(
        model_name="model-a",
        arena_name="model-a",
        aa_name="Model A",
        arena_match_type=MatchType.EXACT,
        aa_match_type=MatchType.EQUIVALENT,
        overall=CompositeScore(
            category="overall",
            percentile=92.5,
            arena_score=arena_score_a,
            aa_score=aa_score_a,
        ),
        categories={
            "overall": CompositeScore(
                category="overall",
                percentile=92.5,
                arena_score=arena_score_a,
                aa_score=aa_score_a,
            ),
        },
    )
    sc_b = ModelScorecard(
        model_name="model-b",
        arena_name="model-b",
        aa_name="Model B",
        arena_match_type=MatchType.EXACT,
        aa_match_type=MatchType.EXACT,
        overall=CompositeScore(
            category="overall",
            percentile=75.0,
            arena_score=arena_score_b,
            aa_score=aa_score_b,
        ),
        categories={
            "overall": CompositeScore(
                category="overall",
                percentile=75.0,
                arena_score=arena_score_b,
                aa_score=aa_score_b,
            ),
        },
    )

    finding = CategoryFinding(
        category="overall",
        display_name="Overall",
        ranked_models=[("model-a", 92.5), ("model-b", 75.0)],
        gap_description="clear separation",
        provenance="both",
        variant_notes=[],
    )

    return ComparisonResult(
        model_names=["model-a", "model-b"],
        sources=[
            SourceData(
                source_name="Test Source",
                source_description="Test Benchmarks",
                methodology="This is a test methodology.",
                findings=["Test finding."],
                models_found=["model-a", "model-b"],
                models_not_found=[],
            )
        ],
        overall_conclusions=["Model A is better overall."],
        scorecards=[sc_a, sc_b],
        category_findings=[finding],
        arena_weight=0.6,
        aa_weight=0.4,
    )


def _make_result() -> ComparisonResult:
    return ComparisonResult(
        model_names=["model-a", "model-b"],
        sources=[
            SourceData(
                source_name="Test Source",
                source_description="Test Benchmarks",
                methodology="This is a test methodology.",
                global_rankings=[
                    ComparisonTable(
                        title="model-a (rank 5 of 100)",
                        headers=["Rank", "Model", "Score"],
                        rows=[
                            ["4", "other", "95"],
                            ["**5**", "**model-a**", "**90**"],
                            ["6", "another", "85"],
                        ],
                        alignments=["right", "left", "right"],
                    )
                ],
                comparison_tables=[
                    ComparisonTable(
                        title="All Models",
                        headers=["Model", "Score", "Speed"],
                        rows=[
                            ["model-a", "90", "100"],
                            ["model-b", "80", "50"],
                        ],
                        alignments=["left", "right", "right"],
                    )
                ],
                head_to_heads=[
                    HeadToHead(
                        model_a="model-a",
                        model_b="model-b",
                        dimensions=["overall", "coding"],
                        a_scores=[90.0, 95.0],
                        b_scores=[80.0, 85.0],
                        deltas=[10.0, 10.0],
                        a_wins=2,
                        b_wins=0,
                        ties=0,
                    )
                ],
                findings=["Model A beats Model B in all categories."],
                models_found=["model-a", "model-b"],
                models_not_found=[],
            )
        ],
        overall_conclusions=["Model A is better overall."],
    )


@pytest.mark.unit
class TestRenderComparison:
    def test_produces_markdown(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        result = _make_result()
        content = render_comparison(result, output)
        assert output.exists()
        assert "# Model Comparison" in content
        assert "model-a" in content
        assert "model-b" in content

    def test_contains_source_sections(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "Test Source" in content

    def test_contains_methodology(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "test methodology" in content

    def test_contains_tables(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "| Model | Score | Speed |" in content

    def test_contains_h2h(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "Head-to-Head" in content

    def test_contains_conclusions(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "Overall Conclusions" in content

    def test_no_triple_blank_lines(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "\n\n\n" not in content


@pytest.mark.unit
class TestRenderComparisonWithScorecards:
    def test_contains_composite_scores_section(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result_with_scorecards(), output)
        assert "Composite Scores" in content
        assert "Arena 60%" in content

    def test_contains_per_model_detail(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result_with_scorecards(), output)
        assert "### model-a" in content
        assert "(exact)" in content
        assert "(equivalent)" in content

    def test_contains_category_analysis(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result_with_scorecards(), output)
        assert "Category Analysis" in content
        assert "clear separation" in content

    def test_contains_percentile_tier_definitions(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result_with_scorecards(), output)
        assert "Composite Tiers" in content

    def test_no_composite_sections_without_scorecards(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        result = _make_result()
        content = render_comparison(result, output)
        assert "Composite Scores" not in content
