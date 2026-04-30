from __future__ import annotations

from pathlib import Path

import pytest

from model_eval.models import (
    ComparisonResult,
    ComparisonTable,
    HeadToHead,
    SourceData,
)
from model_eval.renderer import render_comparison


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
