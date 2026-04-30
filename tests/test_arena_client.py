from __future__ import annotations

from pathlib import Path

import pytest

from model_eval.arena_client import (
    compute_distribution,
    load_cache,
    load_dist_cache,
    save_cache,
    save_dist_cache,
)


@pytest.mark.unit
class TestCacheRoundTrip:
    def test_save_and_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        rows = [
            {"model_name": "test-model", "category": "overall", "rating": 1400.0, "vote_count": 100}
        ]
        path = save_cache(rows)
        assert path.exists()

        loaded, fetched_at = load_cache()
        assert len(loaded) == 1
        assert loaded[0]["model_name"] == "test-model"
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
        cache_file = cache_dir / "arena_models.json"
        cache_file.write_text("not json{{{")
        loaded, fetched_at = load_cache()
        assert loaded == []
        assert fetched_at is None


@pytest.mark.unit
class TestDistribution:
    def test_compute_distribution(self) -> None:
        rows = [{"category": "overall", "rating": 1000.0 + i * 10} for i in range(50)] + [
            {"category": "coding", "rating": 900.0}
        ]
        dist = compute_distribution(rows)
        assert dist["stats"]["count"] == 50
        assert dist["stats"]["min"] == 1000.0
        assert dist["stats"]["max"] == 1490.0
        assert len(dist["scores"]) == 50

    def test_compute_distribution_no_overall(self) -> None:
        rows = [{"category": "coding", "rating": 900.0}]
        with pytest.raises(ValueError, match="No overall-category"):
            compute_distribution(rows)

    def test_dist_cache_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        dist = {
            "stats": {
                "count": 10,
                "min": 1.0,
                "max": 10.0,
                "median": 5.0,
                "mean": 5.5,
                "stdev": 3.0,
                "p25": 3.0,
                "p75": 8.0,
            },
            "scores": list(range(1, 11)),
        }
        path = save_dist_cache(dist)
        assert path.exists()

        loaded = load_dist_cache()
        assert loaded is not None
        assert loaded["stats"]["count"] == 10
        assert len(loaded["scores"]) == 10

    def test_dist_cache_missing_bootstraps(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import model_eval.aa_client as mod

        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)

        rows = [{"category": "overall", "rating": 1000.0 + i} for i in range(20)]
        save_cache(rows)

        loaded = load_dist_cache()
        assert loaded is not None
        assert loaded["stats"]["count"] == 20
