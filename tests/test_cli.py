from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from model_eval.cli import main, parse_weights


@pytest.mark.unit
class TestCLI:
    def test_group_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--models" in result.output
        assert "sync-aa" in result.output

    def test_no_models_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code != 0

    def test_sync_aa_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["sync-aa", "--help"])
        assert result.exit_code == 0
        assert "--api-key" in result.output

    def test_sync_aa_no_key_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AA_API_KEY", raising=False)
        runner = CliRunner()
        result = runner.invoke(main, ["sync-aa"])
        assert result.exit_code != 0

    def test_fuzzy_flag_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--fuzzy" in result.output

    def test_check_command_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "check" in result.output

    def test_check_command_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["check", "--help"])
        assert result.exit_code == 0
        assert "--models" in result.output

    def test_weights_flag_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--weights" in result.output


from model_eval.models import MatchType
from model_eval.cli import build_scorecards


class TestParseWeights:
    def test_equal_weights(self):
        arena, aa = parse_weights("arena=50,aa=50")
        assert arena == 0.5
        assert aa == 0.5

    def test_unequal_weights(self):
        arena, aa = parse_weights("arena=3,aa=2")
        assert arena == pytest.approx(0.6)
        assert aa == pytest.approx(0.4)

    def test_order_independent(self):
        arena, aa = parse_weights("aa=40,arena=60")
        assert arena == pytest.approx(0.6)
        assert aa == pytest.approx(0.4)

    def test_arbitrary_scale(self):
        arena, aa = parse_weights("arena=1,aa=1")
        assert arena == 0.5
        assert aa == 0.5

    def test_float_values(self):
        arena, aa = parse_weights("arena=0.7,aa=0.3")
        assert arena == pytest.approx(0.7)
        assert aa == pytest.approx(0.3)

    def test_missing_source_raises(self):
        with pytest.raises(click.UsageError):
            parse_weights("arena=50")

    def test_unknown_source_raises(self):
        with pytest.raises(click.UsageError):
            parse_weights("arena=50,openai=50")

    def test_zero_weight_raises(self):
        with pytest.raises(click.UsageError):
            parse_weights("arena=0,aa=0")

    def test_negative_weight_raises(self):
        with pytest.raises(click.UsageError):
            parse_weights("arena=-1,aa=50")

    def test_bad_format_raises(self):
        with pytest.raises(click.UsageError):
            parse_weights("50/50")


class TestBuildScorecards:
    def test_resolves_and_scores(self):
        arena_rows = [
            {"model_name": "model-a", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "model-b", "category": "overall", "rating": 1400, "rating_lower": 1395, "rating_upper": 1405},
        ]
        aa_models = [
            {"name": "model-a", "intelligence_index": 60},
            {"name": "model-b", "intelligence_index": 40},
        ]
        result = build_scorecards(
            model_names=["model-a", "model-b"],
            arena_rows=arena_rows,
            aa_models=aa_models,
            categories=["overall"],
        )
        assert len(result) == 2
        assert result[0].model_name == "model-a"
        assert result[0].overall is not None
        assert result[0].overall.provenance == "both"

    def test_match_types_populated(self):
        arena_rows = [
            {"model_name": "model-a", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        aa_models = [
            {"name": "model-a", "intelligence_index": 60},
        ]
        result = build_scorecards(
            model_names=["model-a"],
            arena_rows=arena_rows,
            aa_models=aa_models,
            categories=["overall"],
        )
        assert result[0].arena_match_type == MatchType.EXACT
        assert result[0].aa_match_type == MatchType.EXACT

    def test_fuzzy_match_excluded_by_default(self):
        arena_rows = [
            {"model_name": "model-alpha-v2", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        result = build_scorecards(
            model_names=["model-alpha"],
            arena_rows=arena_rows,
            aa_models=[],
            categories=["overall"],
            fuzzy=False,
        )
        assert len(result) == 0

    def test_fuzzy_match_included_when_enabled(self):
        arena_rows = [
            {"model_name": "model-alpha-v2", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
        ]
        result = build_scorecards(
            model_names=["model-alpha"],
            arena_rows=arena_rows,
            aa_models=[],
            categories=["overall"],
            fuzzy=True,
        )
        assert len(result) == 1
        assert result[0].arena_match_type == MatchType.FUZZY

    def test_model_not_found_in_either_source(self):
        result = build_scorecards(
            model_names=["nonexistent"],
            arena_rows=[],
            aa_models=[],
            categories=["overall"],
        )
        assert len(result) == 0

    def test_multiple_categories(self):
        arena_rows = [
            {"model_name": "a", "category": "overall", "rating": 1500, "rating_lower": 1495, "rating_upper": 1505},
            {"model_name": "a", "category": "coding", "rating": 1480, "rating_lower": 1475, "rating_upper": 1485},
        ]
        aa_models = [
            {"name": "a", "intelligence_index": 60, "coding_index": 55},
        ]
        result = build_scorecards(
            model_names=["a"],
            arena_rows=arena_rows,
            aa_models=aa_models,
            categories=["overall", "coding"],
        )
        assert len(result) == 1
        assert "overall" in result[0].categories
        assert "coding" in result[0].categories
