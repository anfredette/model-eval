from __future__ import annotations

from pathlib import Path

import pytest

from model_eval.aa_client import (
    _infer_reasoning,
    _map_api_model,
    cache_age_display,
    compute_distribution,
    is_cache_stale,
    load_cache,
    load_dist_cache,
    save_cache,
    save_dist_cache,
)


@pytest.mark.unit
class TestMapApiModel:
    def test_basic_mapping(self) -> None:
        api_obj = {
            "name": "Test Model",
            "slug": "test-model",
            "model_creator": {"name": "TestOrg"},
            "evaluations": {
                "artificial_analysis_intelligence_index": 42,
                "artificial_analysis_coding_index": 35,
                "artificial_analysis_math_index": 28,
            },
            "median_output_tokens_per_second": 100.5,
            "median_time_to_first_token_seconds": 0.85,
            "pricing": {
                "price_1m_input_tokens": 1.0,
                "price_1m_output_tokens": 3.0,
                "price_1m_blended_3_to_1": 1.5,
            },
        }
        result = _map_api_model(api_obj)
        assert result["name"] == "Test Model"
        assert result["slug"] == "test-model"
        assert result["organization"] == "TestOrg"
        assert result["intelligence_index"] == 42
        assert result["coding_index"] == 35
        assert result["math_index"] == 28
        assert result["speed_tps"] == 100.5
        assert result["ttft_s"] == 0.85
        assert result["input_price_per_1m"] == 1.0
        assert result["output_price_per_1m"] == 3.0
        assert result["blended_price_api"] == 1.5
        assert result["url"] == "https://artificialanalysis.ai/models/test-model"

    def test_missing_fields(self) -> None:
        api_obj = {"name": "Minimal", "slug": "minimal"}
        result = _map_api_model(api_obj)
        assert result["name"] == "Minimal"
        assert result["organization"] == "Unknown"
        assert result["intelligence_index"] is None
        assert result["coding_index"] is None
        assert result["speed_tps"] is None

    def test_reasoning_from_api(self) -> None:
        api_obj = {"name": "Test", "slug": "test", "reasoning": True}
        result = _map_api_model(api_obj)
        assert result["reasoning"] is True

    def test_reasoning_inferred(self) -> None:
        api_obj = {"name": "GPT-5 Thinking", "slug": "gpt-5-thinking"}
        result = _map_api_model(api_obj)
        assert result["reasoning"] is True


@pytest.mark.unit
class TestInferReasoning:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("GPT-5 Thinking", True),
            ("Claude Reasoning", True),
            ("o1 (high)", True),
            ("o1 (low)", True),
            ("o1 (xhigh)", True),
            ("GPT-4o", False),
            ("Gemini Pro", False),
        ],
    )
    def test_patterns(self, name: str, expected: bool) -> None:
        assert _infer_reasoning(name) == expected


@pytest.mark.unit
class TestCacheRoundTrip:
    def test_save_and_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        models = [{"name": "Test", "slug": "test", "organization": "Org", "intelligence_index": 30}]
        path = save_cache(models)
        assert path.exists()

        loaded, fetched_at = load_cache()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "Test"
        assert fetched_at is not None

    def test_load_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        loaded, fetched_at = load_cache()
        assert loaded == []
        assert fetched_at is None

    def test_load_corrupt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        cache_dir = tmp_path / ".model_cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "aa_models.json"
        cache_file.write_text("not json{{{")
        loaded, fetched_at = load_cache()
        assert loaded == []
        assert fetched_at is None


@pytest.mark.unit
class TestCacheAgeDisplay:
    def test_just_now(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        assert cache_age_display(now) == "just now"

    def test_invalid(self) -> None:
        assert cache_age_display("not-a-date") == "unknown age"

    def test_hours_ago(self) -> None:
        from datetime import UTC, datetime, timedelta

        two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        assert cache_age_display(two_hours_ago) == "2 hours ago"

    def test_days_ago(self) -> None:
        from datetime import UTC, datetime, timedelta

        three_days_ago = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        assert cache_age_display(three_days_ago) == "3 days ago"


@pytest.mark.unit
class TestIsCacheStale:
    def test_none_is_stale(self) -> None:
        assert is_cache_stale(None) is True

    def test_recent_is_fresh(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        assert is_cache_stale(now) is False

    def test_old_is_stale(self) -> None:
        from datetime import UTC, datetime, timedelta

        old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        assert is_cache_stale(old) is True

    def test_invalid_is_stale(self) -> None:
        assert is_cache_stale("not-a-date") is True


@pytest.mark.unit
class TestDistribution:
    def test_compute_distribution(self) -> None:
        models = [{"intelligence_index": i} for i in range(10, 60)]
        dist = compute_distribution(models)
        assert dist["stats"]["count"] == 50
        assert dist["stats"]["min"] == 10
        assert dist["stats"]["max"] == 59
        assert len(dist["scores"]) == 50

    def test_compute_distribution_filters_none(self) -> None:
        models = [
            {"intelligence_index": 50},
            {"intelligence_index": None},
            {"intelligence_index": 30},
        ]
        dist = compute_distribution(models)
        assert dist["stats"]["count"] == 2

    def test_compute_distribution_all_none(self) -> None:
        models = [{"intelligence_index": None}]
        with pytest.raises(ValueError, match="No models with intelligence_index"):
            compute_distribution(models)

    def test_dist_cache_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        dist = {
            "stats": {
                "count": 5,
                "min": 10.0,
                "max": 50.0,
                "median": 30.0,
                "mean": 30.0,
                "stdev": 15.0,
                "p25": 20.0,
                "p75": 40.0,
            },
            "scores": [10, 20, 30, 40, 50],
        }
        path = save_dist_cache(dist)
        assert path.exists()

        loaded = load_dist_cache()
        assert loaded is not None
        assert loaded["stats"]["count"] == 5
