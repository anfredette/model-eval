from pathlib import Path

import pytest

from model_eval.charts import generate_distribution_chart


@pytest.mark.unit
class TestGenerateDistributionChart:
    def test_creates_png(self, tmp_path: Path) -> None:
        scores = list(range(900, 1500, 10))
        models = [
            {"name": "model-a", "score": 1400.0, "family": "Org A"},
            {"name": "model-b", "score": 1300.0, "family": "Org B"},
        ]
        out = tmp_path / "test_chart.png"
        result = generate_distribution_chart(scores, models, out, "Test Rating", 1200.0)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_single_model(self, tmp_path: Path) -> None:
        scores = list(range(900, 1500, 10))
        models = [{"name": "solo", "score": 1450.0, "family": "Solo Org"}]
        out = tmp_path / "single.png"
        result = generate_distribution_chart(scores, models, out, "Rating", 1200.0)
        assert result.exists()

    def test_no_models(self, tmp_path: Path) -> None:
        scores = list(range(900, 1500, 10))
        out = tmp_path / "empty.png"
        result = generate_distribution_chart(scores, [], out, "Rating", 1200.0)
        assert result.exists()

    def test_many_models(self, tmp_path: Path) -> None:
        scores = list(range(0, 60))
        models = [
            {"name": f"model-{i}", "score": float(50 - i), "family": f"Org {'A' if i < 5 else 'B'}"}
            for i in range(10)
        ]
        out = tmp_path / "many.png"
        result = generate_distribution_chart(scores, models, out, "Intelligence Index", 30.0)
        assert result.exists()

    def test_custom_colors(self, tmp_path: Path) -> None:
        scores = list(range(0, 100))
        models = [
            {"name": "m1", "score": 80.0, "family": "X", "color": "#FF0000"},
            {"name": "m2", "score": 60.0, "family": "Y", "color": "#00FF00"},
        ]
        out = tmp_path / "colors.png"
        result = generate_distribution_chart(scores, models, out, "Score", 50.0)
        assert result.exists()
