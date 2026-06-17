from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from model_eval.models import CategoryFinding

TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "model_eval" / "templates"


@pytest.mark.unit
class TestRenderCategoryFindingMacro:
    def _render(self, finding: CategoryFinding) -> str:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.from_string(
            '{% from "macros.j2" import render_category_finding %}{{ render_category_finding(f) }}'
        )
        return template.render(f=finding)

    def test_two_models(self):
        f = CategoryFinding(
            category="overall",
            display_name="Overall",
            ranked_models=[("model-a", 94.2), ("model-b", 82.3)],
            gap_description="moderate advantage",
            provenance="both",
        )
        result = self._render(f)
        assert "model-a" in result
        assert "model-b" in result
        assert "94.2" in result
        assert "82.3" in result
        assert "moderate advantage" in result
        assert "[Both]" in result

    def test_three_models(self):
        f = CategoryFinding(
            category="coding",
            display_name="Coding",
            ranked_models=[("a", 96.0), ("b", 85.0), ("c", 70.0)],
            gap_description="clear separation",
            provenance="both",
        )
        result = self._render(f)
        assert "a" in result
        assert "b" in result
        assert "c" in result

    def test_variant_notes(self):
        f = CategoryFinding(
            category="overall",
            display_name="Overall",
            ranked_models=[("a", 90.0), ("b", 85.0)],
            gap_description="moderate advantage",
            provenance="both",
            variant_notes=["b: instruct variant (confidence: 0.8)"],
        )
        result = self._render(f)
        assert "instruct variant" in result
