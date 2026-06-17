# Composite Report Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the composite scoring engine into report generation and rewrite the model-eval skill to be composite-first.

**Architecture:** `build_scorecards()` lives in the CLI layer (not `scoring.py`) to keep `scoring.py` portable to llm-d-planner. It wraps name resolution + existing `compute_scorecards()` into a single call. The CLI computes scorecards and structured `CategoryFinding` objects, passes them to the renderer, and new Jinja2 template sections render composite tables, per-model detail cards, and category analysis. The skill is rewritten to lead with composite percentiles.

**Tech Stack:** Python 3.11+, Click, Jinja2, dataclasses, pytest

**Portability note:** `scoring.py` is the module that will be ported to llm-d-planner. It must have no dependencies on model-eval-specific modules like `resolver.py`. CLI-layer helpers (`build_scorecards`, `parse_weights`) stay in `cli.py`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/model_eval/models.py` | Modify | Move `MatchType` here, add `CategoryFinding`, extend `ComparisonResult` and `ModelScorecard` |
| `src/model_eval/resolver.py` | Modify | Import `MatchType` from `models` instead of defining locally |
| `src/model_eval/tiers.py` | Modify | Add `percentile_tier_label()` and `percentile_gap_significance()` |
| `src/model_eval/scoring.py` | Modify | Add `generate_category_findings()` (stays I/O-free, no resolver dependency) |
| `src/model_eval/cli.py` | Modify | Add `build_scorecards()`, `parse_weights()`, `--weights` to main, refactor `scores_command` |
| `src/model_eval/renderer.py` | Modify | Pass new fields (including categories list) to template context |
| `src/model_eval/templates/macros.j2` | Modify | Add composite rendering macros |
| `src/model_eval/templates/comparison.md.j2` | Modify | Add composite sections, update definitions |
| `.claude/commands/model-eval.md` | Modify | Rewrite to composite-first |
| `tests/test_tiers.py` | Modify | Add percentile tier/gap tests |
| `tests/test_scoring.py` | Modify | Add `generate_category_findings()` tests |
| `tests/test_cli.py` | Modify | Add `build_scorecards()`, `parse_weights()`, and `--weights` flag tests |
| `tests/test_renderer.py` | Modify | Add scorecard rendering tests |

---

### Task 1: Move `MatchType` to `models.py`

**Files:**
- Modify: `src/model_eval/models.py`
- Modify: `src/model_eval/resolver.py`
- Test: `tests/test_resolver.py` (existing tests must still pass)

- [ ] **Step 1: Add `MatchType` to `models.py`**

Add the enum at the top of `models.py`, after the existing imports:

```python
import enum

class MatchType(enum.Enum):
    EXACT = "exact"
    EQUIVALENT = "equivalent"
    FUZZY = "fuzzy"
    NONE = "none"
```

- [ ] **Step 2: Update `resolver.py` to import from `models`**

In `src/model_eval/resolver.py`, remove the `MatchType` class definition and the `import enum` line. Add this import at the top:

```python
from model_eval.models import MatchType
```

Keep the existing `MatchResult` dataclass in `resolver.py` — it references `MatchType` and will now get it via import.

Note: `models.py` already imports `MatchResult` from `resolver.py` under `TYPE_CHECKING` (line 7-8). This creates a conditional circular import, but it's safe: `models.py`'s import of `MatchResult` only runs during type checking, while `resolver.py`'s new import of `MatchType` from `models.py` is a runtime import. No actual circular import at runtime.

- [ ] **Step 3: Update all other files that import `MatchType` from `resolver`**

These files import `MatchType` from `resolver` and need updating:
- `src/model_eval/cli.py`: change `from model_eval.resolver import MatchType, ...` to `from model_eval.models import MatchType` (keep other resolver imports)
- `src/model_eval/sources/arena.py`: change `from model_eval.resolver import MatchType, ...` to add `MatchType` import from `models` (keep other resolver imports)
- `src/model_eval/sources/artificial_analysis.py`: same pattern

- [ ] **Step 4: Run existing tests to verify nothing broke**

Run: `uv run pytest tests/ -v`
Expected: All existing tests pass. The `MatchType` move is purely structural.

- [ ] **Step 5: Commit**

```bash
git add src/model_eval/models.py src/model_eval/resolver.py src/model_eval/cli.py src/model_eval/sources/arena.py src/model_eval/sources/artificial_analysis.py && git commit -s -m "refactor: move MatchType enum to models.py

Prevents dependency cycle when ModelScorecard needs to reference
MatchType at runtime. models.py already has a TYPE_CHECKING import
of MatchResult from resolver.py — this is safe because that import
only runs during type checking, while resolver.py's new runtime
import of MatchType from models.py has no circular dependency.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 2: Add `CategoryFinding` and extend `ComparisonResult` and `ModelScorecard`

**Files:**
- Modify: `src/model_eval/models.py`
- Test: `tests/test_scoring.py` (new tests for new fields)

- [ ] **Step 1: Write tests for the new data model fields**

Add to `tests/test_scoring.py`:

```python
from model_eval.models import CategoryFinding, MatchType, ModelScorecard, ComparisonResult


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scoring.py::TestCategoryFinding -v`
Expected: FAIL — `CategoryFinding` not yet defined.

- [ ] **Step 3: Add `CategoryFinding` dataclass to `models.py`**

Add after `ModelScorecard`:

```python
@dataclass
class CategoryFinding:
    """Structured per-category finding for template rendering.

    ranked_models is sorted descending by percentile — all models
    with data in this category, not just the top and bottom.
    """

    category: str
    display_name: str
    ranked_models: list[tuple[str, float]]
    gap_description: str
    provenance: str
    variant_notes: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Add new fields to `ModelScorecard`**

Update `ModelScorecard` to add match type fields. The full class becomes:

```python
@dataclass
class ModelScorecard:
    """Complete scoring profile for a single model."""

    model_name: str
    arena_name: str | None
    aa_name: str | None
    arena_match_type: MatchType | None = None
    aa_match_type: MatchType | None = None
    overall: CompositeScore | None = None
    categories: dict[str, CompositeScore] = field(default_factory=dict)
```

- [ ] **Step 5: Add new fields to `ComparisonResult`**

Update `ComparisonResult` to add scorecard and weight fields. The full class becomes:

```python
@dataclass
class ComparisonResult:
    """Complete comparison result from all sources."""

    model_names: list[str]
    sources: list[SourceData] = field(default_factory=list)
    overall_conclusions: list[str] = field(default_factory=list)
    scorecards: list[ModelScorecard] = field(default_factory=list)
    category_findings: list[CategoryFinding] = field(default_factory=list)
    arena_weight: float = 0.5
    aa_weight: float = 0.5
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_scoring.py::TestCategoryFinding tests/test_scoring.py::TestModelScorecardMatchType tests/test_scoring.py::TestComparisonResultNewFields -v`
Expected: All PASS.

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass. Existing `_make_result()` in `test_renderer.py` constructs `ComparisonResult` with keyword args and new fields have defaults, so it still works.

- [ ] **Step 8: Commit**

```bash
git add src/model_eval/models.py tests/test_scoring.py && git commit -s -m "feat: add CategoryFinding and extend ComparisonResult/ModelScorecard

CategoryFinding holds all ranked models (not just leader/trailer)
so 3+ model comparisons surface every model in findings.
ComparisonResult gains scorecards, category_findings, and weight
fields. ModelScorecard gains match type tracking.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add percentile-based tier and gap functions to `tiers.py`

**Files:**
- Modify: `src/model_eval/tiers.py`
- Modify: `tests/test_tiers.py`

- [ ] **Step 1: Write tests for percentile tier and gap functions**

Add to `tests/test_tiers.py`:

```python
from model_eval.tiers import percentile_gap_significance, percentile_tier_label


@pytest.mark.unit
class TestPercentileTierLabel:
    def test_frontier(self) -> None:
        assert percentile_tier_label(95.0) == "Frontier"
        assert percentile_tier_label(99.9) == "Frontier"

    def test_near_frontier(self) -> None:
        assert percentile_tier_label(85.0) == "Near-frontier"
        assert percentile_tier_label(94.9) == "Near-frontier"

    def test_upper_mid(self) -> None:
        assert percentile_tier_label(50.0) == "Upper-mid"
        assert percentile_tier_label(84.9) == "Upper-mid"

    def test_mid_tier(self) -> None:
        assert percentile_tier_label(15.0) == "Mid-tier"
        assert percentile_tier_label(49.9) == "Mid-tier"

    def test_long_tail(self) -> None:
        assert percentile_tier_label(14.9) == "Long-tail"
        assert percentile_tier_label(0.0) == "Long-tail"


@pytest.mark.unit
class TestPercentileGapSignificance:
    def test_effectively_equivalent(self) -> None:
        assert percentile_gap_significance(3.0) == "effectively equivalent"
        assert percentile_gap_significance(0.0) == "effectively equivalent"
        assert percentile_gap_significance(4.9) == "effectively equivalent"

    def test_moderate_advantage(self) -> None:
        assert percentile_gap_significance(5.0) == "moderate advantage"
        assert percentile_gap_significance(10.0) == "moderate advantage"
        assert percentile_gap_significance(15.0) == "moderate advantage"

    def test_clear_separation(self) -> None:
        assert percentile_gap_significance(15.1) == "clear separation"
        assert percentile_gap_significance(30.0) == "clear separation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tiers.py::TestPercentileTierLabel -v`
Expected: FAIL — `percentile_tier_label` not defined.

- [ ] **Step 3: Implement percentile tier and gap functions**

Add to the end of `src/model_eval/tiers.py`:

```python
PERCENTILE_TIER_BOUNDARIES: list[tuple[float, str]] = [
    (95.0, "Frontier"),
    (85.0, "Near-frontier"),
    (50.0, "Upper-mid"),
    (15.0, "Mid-tier"),
]
PERCENTILE_TIER_DEFAULT = "Long-tail"


def percentile_tier_label(percentile: float) -> str:
    """Return tier name for a composite percentile (0-100)."""
    for cutoff, label in PERCENTILE_TIER_BOUNDARIES:
        if percentile >= cutoff:
            return label
    return PERCENTILE_TIER_DEFAULT


def percentile_gap_significance(gap: float) -> str:
    """Describe the gap between two composite percentiles."""
    if gap < 5.0:
        return "effectively equivalent"
    if gap <= 15.0:
        return "moderate advantage"
    return "clear separation"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tiers.py -v`
Expected: All PASS (both old and new tests).

- [ ] **Step 5: Commit**

```bash
git add src/model_eval/tiers.py tests/test_tiers.py && git commit -s -m "feat: add percentile-based tier and gap functions

percentile_tier_label() and percentile_gap_significance() sit
alongside existing rank-based functions. Used for composite scoring
contexts where cross-source percentiles are the natural unit.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add `build_scorecards()` to `cli.py`

`build_scorecards()` lives in the CLI layer — not in `scoring.py` — to keep `scoring.py` portable to llm-d-planner. It wraps name resolution (model-eval-specific) + the existing `compute_scorecards()` (portable) into a single call.

**Files:**
- Modify: `src/model_eval/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write tests for `build_scorecards()`**

Add to `tests/test_cli.py`:

```python
from model_eval.models import MatchType
from model_eval.cli import build_scorecards


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
```

Note: the fuzzy match tests use "model-alpha" vs "model-alpha-v2" (version-adjacent match at resolver step 12), not "model-a" vs "model-a-instruct" (which would be an EQUIVALENT match via suffix stripping, not FUZZY).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestBuildScorecards -v`
Expected: FAIL — `build_scorecards` not defined.

- [ ] **Step 3: Implement `build_scorecards()` in `cli.py`**

Add to `src/model_eval/cli.py`, before the `main` function:

```python
from model_eval.models import MatchType, ModelScorecard
from model_eval.resolver import resolve_model_names
from model_eval.scoring import compute_scorecards


def build_scorecards(
    model_names: list[str],
    arena_rows: list[dict[str, Any]],
    aa_models: list[dict[str, Any]],
    categories: list[str],
    arena_weight: float = 0.5,
    aa_weight: float = 0.5,
    fuzzy: bool = False,
) -> list[ModelScorecard]:
    """Resolve model names against both sources, compute normalized
    composite scorecards.

    Wraps compute_scorecards() with name resolution. Each returned
    scorecard has arena_match_type and aa_match_type populated from
    the resolver results.

    Lives in the CLI layer (not scoring.py) because it depends on
    resolver.py, which is model-eval-specific. scoring.py stays
    portable to llm-d-planner.
    """
    arena_names = sorted(
        {r["model_name"] for r in arena_rows if r.get("category") == "overall"}
    )
    aa_names = [m["name"] for m in aa_models]

    arena_results = resolve_model_names(model_names, arena_names) if arena_names else []
    aa_results = resolve_model_names(model_names, aa_names) if aa_names else []

    target_models: list[tuple[str, str | None, str | None]] = []
    match_types: list[tuple[MatchType | None, MatchType | None]] = []

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

        if not arena_match and not aa_match:
            continue

        target_models.append((name, arena_match, aa_match))
        match_types.append((arena_mt, aa_mt))

    if not target_models:
        return []

    scorecards = compute_scorecards(
        arena_rows=arena_rows,
        aa_models=aa_models,
        target_models=target_models,
        categories=categories,
        arena_weight=arena_weight,
        aa_weight=aa_weight,
    )

    for sc, (arena_mt, aa_mt) in zip(scorecards, match_types, strict=True):
        sc.arena_match_type = arena_mt
        sc.aa_match_type = aa_mt

    return scorecards
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestBuildScorecards -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/model_eval/cli.py tests/test_cli.py && git commit -s -m "feat: add build_scorecards() CLI helper for name resolution + scoring

Wraps resolve_model_names() + compute_scorecards() into a single
call. Lives in cli.py (not scoring.py) to keep scoring.py portable
to llm-d-planner — it depends on resolver.py which is
model-eval-specific. Populates arena_match_type and aa_match_type
on each scorecard.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 5: Add `generate_category_findings()` to `scoring.py`

This function stays in `scoring.py` because it operates on scorecards (already computed) and uses only `tiers.py` and `categories.py` — both portable. No dependency on `resolver.py`.

**Files:**
- Modify: `src/model_eval/scoring.py`
- Modify: `tests/test_scoring.py`

- [ ] **Step 1: Write tests for `generate_category_findings()`**

Add to `tests/test_scoring.py`:

```python
from model_eval.models import CompositeScore, NormalizedScore, CategoryFinding, ModelScorecard
from model_eval.scoring import generate_category_findings


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scoring.py::TestGenerateCategoryFindings -v`
Expected: FAIL — `generate_category_findings` not defined.

- [ ] **Step 3: Implement `generate_category_findings()`**

Add to `src/model_eval/scoring.py`. Note: no new import of `resolver` — only `categories` and `tiers`, both portable:

```python
from model_eval.categories import display_name
from model_eval.models import CategoryFinding
from model_eval.tiers import percentile_gap_significance


def generate_category_findings(
    scorecards: list[ModelScorecard],
    categories: list[str],
) -> list[CategoryFinding]:
    """Generate cross-source findings for each category with data for 2+ models.

    All models with data in a category are included in ranked_models
    (sorted descending by percentile), not just the top and bottom.
    Gap description covers the spread from highest to lowest.
    """
    if len(scorecards) < 2:
        return []

    findings: list[CategoryFinding] = []

    for cat in categories:
        models_with_data: list[tuple[str, CompositeScore]] = []
        for sc in scorecards:
            cs = sc.categories.get(cat)
            if cs is not None:
                models_with_data.append((sc.model_name, cs))

        if len(models_with_data) < 2:
            continue

        models_with_data.sort(key=lambda x: x[1].percentile, reverse=True)
        ranked_models = [(name, cs.percentile) for name, cs in models_with_data]

        top_pct = models_with_data[0][1].percentile
        bottom_pct = models_with_data[-1][1].percentile
        gap = top_pct - bottom_pct
        gap_desc = percentile_gap_significance(gap)

        provenances = {cs.provenance for _, cs in models_with_data}
        if len(provenances) == 1:
            provenance = provenances.pop()
        else:
            provenance = "mixed"

        variant_notes: list[str] = []
        for model_name, cs in models_with_data:
            for score in [cs.arena_score, cs.aa_score]:
                if score and score.confidence < 1.0 and score.adjustment:
                    variant_notes.append(
                        f"{model_name}: {score.adjustment} (confidence: {score.confidence})"
                    )

        findings.append(CategoryFinding(
            category=cat,
            display_name=display_name(cat),
            ranked_models=ranked_models,
            gap_description=gap_desc,
            provenance=provenance,
            variant_notes=variant_notes,
        ))

    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scoring.py::TestGenerateCategoryFindings -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/model_eval/scoring.py tests/test_scoring.py && git commit -s -m "feat: add generate_category_findings() for structured per-category analysis

Returns CategoryFinding objects with all ranked models (not just
leader/trailer) so 3+ model comparisons surface every model.
Uses percentile_gap_significance() for gap descriptions.
No dependency on resolver.py — stays portable to llm-d-planner.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 6: Add `parse_weights()` and `--weights` to CLI

**Breaking change:** This changes the `--weights` syntax on `scores_command` from `50/50` to `arena=50,aa=50`. This is an intentional break — the tool is young, the old format is ambiguous (which position is which source?), and the error message clearly shows the new format. No backward compatibility shim.

**Files:**
- Modify: `src/model_eval/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write tests for `parse_weights()`**

Add to `tests/test_cli.py`:

```python
import pytest
from model_eval.cli import parse_weights


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
        with pytest.raises(SystemExit):
            parse_weights("arena=50")

    def test_unknown_source_raises(self):
        with pytest.raises(SystemExit):
            parse_weights("arena=50,openai=50")

    def test_zero_weight_raises(self):
        with pytest.raises(SystemExit):
            parse_weights("arena=0,aa=0")

    def test_negative_weight_raises(self):
        with pytest.raises(SystemExit):
            parse_weights("arena=-1,aa=50")

    def test_bad_format_raises(self):
        with pytest.raises(SystemExit):
            parse_weights("50/50")
```

- [ ] **Step 2: Write test for `--weights` flag in main help**

Add to the existing `TestCLI` class in `tests/test_cli.py`:

```python
    def test_weights_flag_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--weights" in result.output
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestParseWeights -v`
Expected: FAIL — `parse_weights` not defined.

- [ ] **Step 4: Implement `parse_weights()`**

Add to `src/model_eval/cli.py` (before the `main` function, after `build_scorecards`):

```python
def parse_weights(weights_str: str) -> tuple[float, float]:
    """Parse 'arena=N,aa=N' into normalized (arena_weight, aa_weight).

    Values are pure weights — normalized by dividing each by the sum.
    Raises click.UsageError on invalid input.
    """
    VALID_SOURCES = {"arena", "aa"}
    parsed: dict[str, float] = {}

    for part in weights_str.split(","):
        part = part.strip()
        if "=" not in part:
            raise click.UsageError(
                f"Invalid weight format '{part}'. Expected 'source=value', "
                f"e.g., 'arena=50,aa=50'."
            )
        key, val_str = part.split("=", 1)
        key = key.strip().lower()
        if key not in VALID_SOURCES:
            raise click.UsageError(
                f"Unknown source '{key}'. Valid sources: {', '.join(sorted(VALID_SOURCES))}."
            )
        try:
            val = float(val_str.strip())
        except ValueError:
            raise click.UsageError(f"Weight for '{key}' must be a number, got '{val_str.strip()}'.")
        if val <= 0:
            raise click.UsageError(f"Weight for '{key}' must be positive, got {val}.")
        parsed[key] = val

    missing = VALID_SOURCES - parsed.keys()
    if missing:
        raise click.UsageError(
            f"Missing weight for: {', '.join(sorted(missing))}. "
            f"Provide all sources, e.g., 'arena=50,aa=50'."
        )

    total = sum(parsed.values())
    return parsed["arena"] / total, parsed["aa"] / total
```

- [ ] **Step 5: Add `--weights` to `main` command**

Add the `--weights` option to the `@main` decorator, after the existing `--fuzzy` option:

```python
@click.option(
    "--weights",
    "-w",
    default="arena=50,aa=50",
    help="Source weights, e.g., 'arena=60,aa=40' (default: arena=50,aa=50).",
)
```

Add `weights: str` to the `main` function signature. Parse and store the weights — the actual scorecard computation is wired in Task 8:

```python
    arena_weight, aa_weight = parse_weights(weights)
```

- [ ] **Step 6: Refactor `scores_command` to use `parse_weights()`**

In `scores_command`, replace the `weights.split("/")` block (lines ~342-353) with:

```python
    arena_weight, aa_weight = parse_weights(weights)
```

Update the `--weights` option on `scores_command` from `default="50/50"` to `default="arena=50,aa=50"` and update the help text:

```python
@click.option(
    "--weights",
    "-w",
    default="arena=50,aa=50",
    help="Source weights, e.g., 'arena=60,aa=40' (default: arena=50,aa=50).",
)
```

Also update the summary table title in `scores_command` to use the normalized percentages. Replace:

```python
    summary = Table(
        title=f"Overall (Arena {arena_w:.0f}% / AA {aa_w:.0f}%)",
```

with:

```python
    summary = Table(
        title=f"Overall (Arena {arena_weight * 100:.0f}% / AA {aa_weight * 100:.0f}%)",
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All PASS.

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add src/model_eval/cli.py tests/test_cli.py && git commit -s -m "feat: add parse_weights() with named source syntax

Replaces positional '50/50' format with 'arena=50,aa=50'. This is
an intentional breaking change — the old format was ambiguous about
which position mapped to which source. Values are pure weights
normalized by dividing each by the sum. Added to both main command
and scores subcommand.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 7: Add template macros for composite rendering

**Files:**
- Modify: `src/model_eval/templates/macros.j2`
- Create: `tests/test_macros.py`

- [ ] **Step 1: Add composite rendering macros**

Add the following macros to the end of `src/model_eval/templates/macros.j2`.

Note: the `render_composite_table` macro takes a `categories` parameter passed from the renderer — it does NOT hardcode a category list. This ensures it stays in sync with `DEFAULT_CATEGORIES` from `categories.py`.

The `render_category_finding` macro iterates over `f.ranked_models` to show all models, not just leader/trailer:

```jinja2
{%- macro provenance_label(prov) -%}
{%- if prov == "both" %}[B]{% elif prov == "arena_only" %}[A]{% elif prov == "aa_only" %}[AA]{% elif prov == "mixed" %}[M]{% else %}[?]{% endif -%}
{%- endmacro -%}

{%- macro fmt_percentile(val) -%}
{{ "%.1f"|format(val) }}
{%- endmacro -%}

{%- macro match_type_label(mt) -%}
{%- if mt and mt.value == "exact" %}exact{% elif mt and mt.value == "equivalent" %}equivalent{% elif mt and mt.value == "fuzzy" %}fuzzy{% else %}not found{% endif -%}
{%- endmacro -%}

{%- macro render_composite_table(scorecards, categories, arena_weight, aa_weight) -%}
## Composite Scores (Arena {{ "%.0f"|format(arena_weight * 100) }}% / AA {{ "%.0f"|format(aa_weight * 100) }}%)

{% set active_cats = [] -%}
{% for cat in categories -%}
{% for sc in scorecards -%}
{% if cat in sc.categories -%}
{% if cat not in active_cats -%}
{% if active_cats.append(cat) %}{% endif -%}
{% endif -%}
{% endif -%}
{% endfor -%}
{% endfor -%}
{% if active_cats -%}
| Model |{% for cat in active_cats %} {{ cat | replace('_', ' ') | title }} |{% endfor %}

| ------|{% for cat in active_cats %} ------:|{% endfor %}

{% for sc in scorecards -%}
| **{{ sc.model_name }}** |
{%- for cat in active_cats -%}
{%- set cs = sc.categories.get(cat) -%}
{%- if cs %} {{ fmt_percentile(cs.percentile) }}{{ "*" if cs.arena_score and cs.arena_score.confidence < 1.0 or cs.aa_score and cs.aa_score.confidence < 1.0 else "" }} {{ provenance_label(cs.provenance) }} |
{%- else %} -- |
{%- endif -%}
{%- endfor %}

{% endfor -%}
_[B] = both sources, [A] = Arena only, [AA] = AA only, [M] = mixed. * = estimated (variant adjustment)._
{% endif -%}
{%- endmacro -%}

{%- macro render_scorecard_detail(sc, categories) -%}
### {{ sc.model_name }}
{% set arena_label = match_type_label(sc.arena_match_type) -%}
{% set aa_label = match_type_label(sc.aa_match_type) -%}
_Arena: {{ sc.arena_name or "not found" }} ({{ arena_label }}) · AA: {{ sc.aa_name or "not found" }} ({{ aa_label }})_
{% if sc.arena_match_type and sc.arena_match_type.value == "fuzzy" or sc.aa_match_type and sc.aa_match_type.value == "fuzzy" %}
> **Note:** Scores based on approximate name match — verify model identity.
{% endif %}

| Category | Arena Raw | Arena %ile | AA Raw | AA %ile | Composite | Source |
| ---------|----------:|----------:|-------:|--------:|----------:|--------|
{% for cat in categories -%}
{% set cs = sc.categories.get(cat) -%}
{% if cs -%}
{% set a_raw = "%.1f"|format(cs.arena_score.raw_score) if cs.arena_score else "--" -%}
{% set a_pct = fmt_percentile(cs.arena_score.percentile) if cs.arena_score else "--" -%}
{% set aa_raw_val = cs.aa_score.raw_score if cs.aa_score else None -%}
{% set aa_raw = ("%.0f"|format(aa_raw_val) if aa_raw_val == (aa_raw_val|int) else "%.3f"|format(aa_raw_val)) if aa_raw_val is not none else "--" -%}
{% set aa_pct = fmt_percentile(cs.aa_score.percentile) if cs.aa_score else "--" -%}
{% set star = "*" if (cs.arena_score and cs.arena_score.confidence < 1.0) or (cs.aa_score and cs.aa_score.confidence < 1.0) else "" -%}
{% set prov = "Both" if cs.provenance == "both" else ("Arena" if cs.provenance == "arena_only" else "AA") -%}
| {{ cat | replace('_', ' ') | title }} | {{ a_raw }}{{ star }} | {{ a_pct }}{{ star }} | {{ aa_raw }}{{ star }} | {{ aa_pct }}{{ star }} | {{ fmt_percentile(cs.percentile) }}{{ star }} | {{ prov }} |
{% endif -%}
{% endfor -%}
{% set adjustments = [] -%}
{% for cat, cs in sc.categories.items() -%}
{% for score in [cs.arena_score, cs.aa_score] -%}
{% if score and score.confidence < 1.0 and score.adjustment -%}
{% if adjustments.append(score.adjustment) %}{% endif -%}
{% endif -%}
{% endfor -%}
{% endfor -%}
{% if adjustments %}
_* Estimated scores: {{ adjustments | unique | join(", ") }}_
{% endif -%}
{%- endmacro -%}

{%- macro render_category_finding(f) -%}
**{{ f.display_name }}:** {% for name, pct in f.ranked_models %}{{ name }} ({{ fmt_percentile(pct) }} %ile){% if not loop.last %} · {% endif %}{% endfor %} — {{ f.gap_description }}. [{{ f.provenance | replace('_', ' ') | title }}]
{%- if f.variant_notes %} _({{ f.variant_notes | join("; ") }})_{% endif -%}
{%- endmacro -%}
```

- [ ] **Step 2: Write a unit test for the category finding macro**

Create `tests/test_macros.py`:

```python
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
            '{% from "macros.j2" import render_category_finding %}'
            "{{ render_category_finding(f) }}"
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
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_macros.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/model_eval/templates/macros.j2 tests/test_macros.py && git commit -s -m "feat: add Jinja2 macros for composite scorecard rendering

Adds render_composite_table, render_scorecard_detail,
render_category_finding, and helper macros. Category lists are
passed as parameters (not hardcoded) to stay in sync with
DEFAULT_CATEGORIES. Category findings render all ranked models,
not just leader/trailer.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 8: Update template, renderer, and wire CLI plumbing

**Files:**
- Modify: `src/model_eval/templates/comparison.md.j2`
- Modify: `src/model_eval/renderer.py`
- Modify: `src/model_eval/cli.py`
- Modify: `tests/test_renderer.py`

- [ ] **Step 1: Write test for scorecard data in rendered output**

Add to `tests/test_renderer.py`. Use a standalone factory — do NOT mutate `_make_result()`:

```python
from model_eval.models import (
    CategoryFinding,
    CompositeScore,
    ComparisonResult,
    ComparisonTable,
    HeadToHead,
    MatchType,
    ModelScorecard,
    NormalizedScore,
    SourceData,
)


def _make_result_with_scorecards() -> ComparisonResult:
    """Standalone factory — does not depend on _make_result()."""
    arena_score_a = NormalizedScore(
        raw_score=1500.0, percentile=95.0, tied_rank=1,
        population_size=100, source="arena",
    )
    aa_score_a = NormalizedScore(
        raw_score=60, percentile=90.0, tied_rank=1,
        population_size=100, source="aa",
    )
    arena_score_b = NormalizedScore(
        raw_score=1400.0, percentile=80.0, tied_rank=5,
        population_size=100, source="arena",
    )
    aa_score_b = NormalizedScore(
        raw_score=40, percentile=70.0, tied_rank=5,
        population_size=100, source="aa",
    )

    sc_a = ModelScorecard(
        model_name="model-a",
        arena_name="model-a",
        aa_name="Model A",
        arena_match_type=MatchType.EXACT,
        aa_match_type=MatchType.EQUIVALENT,
        overall=CompositeScore(
            category="overall", percentile=92.5,
            arena_score=arena_score_a, aa_score=aa_score_a,
        ),
        categories={
            "overall": CompositeScore(
                category="overall", percentile=92.5,
                arena_score=arena_score_a, aa_score=aa_score_a,
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
            category="overall", percentile=75.0,
            arena_score=arena_score_b, aa_score=aa_score_b,
        ),
        categories={
            "overall": CompositeScore(
                category="overall", percentile=75.0,
                arena_score=arena_score_b, aa_score=aa_score_b,
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
        assert "≥95th" in content

    def test_no_composite_sections_without_scorecards(self, tmp_path: Path) -> None:
        output = tmp_path / "comparison.md"
        content = render_comparison(_make_result(), output)
        assert "Composite Scores" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_renderer.py::TestRenderComparisonWithScorecards -v`
Expected: FAIL — template doesn't render composite sections yet.

- [ ] **Step 3: Update `renderer.py` to pass new context variables**

In `src/model_eval/renderer.py`, update the `render_comparison` function's `template.render()` call. Add the `categories` import and pass the categories list so the template doesn't hardcode it:

```python
from model_eval.categories import DEFAULT_CATEGORIES

# ... in render_comparison():
    content = template.render(
        model_names=result.model_names,
        sources=result.sources,
        overall_conclusions=result.overall_conclusions,
        scorecards=result.scorecards,
        category_findings=result.category_findings,
        categories=DEFAULT_CATEGORIES,
        arena_weight=result.arena_weight,
        aa_weight=result.aa_weight,
        introduction=_generate_introduction(result),
        date=date.today().isoformat(),
    )
```

- [ ] **Step 4: Update `comparison.md.j2` template**

Update the macro import at the top of the template:

```jinja2
{% from "macros.j2" import render_table, render_h2h, render_composite_table, render_scorecard_detail, render_category_finding %}
```

After the section table (`{% endif %}` on line 16) and before `{% if overall_conclusions %}`, insert:

```jinja2
{% if scorecards %}

{{ render_composite_table(scorecards, categories, arena_weight, aa_weight) }}

---

## Model Detail Cards
{% for sc in scorecards %}

{{ render_scorecard_detail(sc, categories) }}
{% endfor %}
{% endif %}
{% if category_findings %}

---

## Category Analysis

{% for f in category_findings %}
{{ loop.index }}. {{ render_category_finding(f) }}
{% endfor %}
{% endif %}
```

Update the Definitions section at the bottom to add percentile-based tiers. After the existing "Gap Significance" tables, add:

```jinja2
### Composite Tiers (percentile-based)

Used in the Composite Scores and Category Analysis sections:

| Tier | Percentile Range |
|------|-----------------|
| Frontier | ≥95th |
| Near-frontier | 85th–94th |
| Upper-mid | 50th–84th |
| Mid-tier | 15th–49th |
| Long-tail | Below 15th |

### Gap Significance (composite percentiles)

| Gap | Description |
|-----|-------------|
| <5 percentile points | Effectively equivalent |
| 5–15 percentile points | Moderate advantage |
| >15 percentile points | Clear separation |
```

- [ ] **Step 5: Wire scorecard computation into `cli.py:main`**

In `cli.py:main`, after the distribution chart loop and before `render_comparison(result, output_path)`, add the scorecard computation:

```python
    from model_eval.categories import DEFAULT_CATEGORIES
    from model_eval.scoring import generate_category_findings

    arena_rows_raw, _ = arena_client.load_cache()
    aa_models_raw, _ = aa_client.load_cache()

    if arena_rows_raw or aa_models_raw:
        scorecards = build_scorecards(
            model_names=model_names,
            arena_rows=arena_rows_raw,
            aa_models=aa_models_raw,
            categories=DEFAULT_CATEGORIES,
            arena_weight=arena_weight,
            aa_weight=aa_weight,
            fuzzy=fuzzy,
        )
        result.scorecards = scorecards
        result.arena_weight = arena_weight
        result.aa_weight = aa_weight
        result.category_findings = generate_category_findings(
            scorecards, DEFAULT_CATEGORIES
        )
```

Note: `build_scorecards` is already defined in `cli.py` (from Task 4), and `generate_category_findings` is imported from `scoring.py`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_renderer.py -v`
Expected: All PASS.

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add src/model_eval/renderer.py src/model_eval/templates/comparison.md.j2 src/model_eval/cli.py tests/test_renderer.py && git commit -s -m "feat: wire composite scorecards into report generation

Adds Composite Scores table, per-model detail cards, and Category
Analysis section to generated reports. Categories are passed from
the renderer (via DEFAULT_CATEGORIES) — not hardcoded in the
template — so they stay in sync as categories are added.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 9: Refactor `scores_command` to use `build_scorecards()`

**Files:**
- Modify: `src/model_eval/cli.py`

- [ ] **Step 1: Replace resolution logic in `scores_command` with `build_scorecards()`**

In `scores_command`, replace the entire resolution block (from `arena_names = sorted(...)` through `if not target_models:`) with:

```python
    scorecards = build_scorecards(
        model_names=model_names,
        arena_rows=arena_rows,
        aa_models=aa_models,
        categories=categories,
        arena_weight=arena_weight,
        aa_weight=aa_weight,
        fuzzy=fuzzy,
    )

    if not scorecards:
        raise click.ClickException("No models found in any source.")
```

`build_scorecards` is already defined earlier in `cli.py` (from Task 4) — no new import needed.

Update the fuzzy notice printing to read from scorecards:

```python
    fuzzy_notices: list[str] = []
    for sc in scorecards:
        if sc.arena_match_type == MatchType.FUZZY and sc.arena_name:
            fuzzy_notices.append(
                f'  "{sc.model_name}" -> "{sc.arena_name}" (fuzzy match in Arena)'
            )
        if sc.aa_match_type == MatchType.FUZZY and sc.aa_name:
            fuzzy_notices.append(
                f'  "{sc.model_name}" -> "{sc.aa_name}" (fuzzy match in AA)'
            )
```

Remove the now-unused local imports of `resolve_model_names` and `MatchType` from inside `scores_command` (the top-level imports of these still exist and are used by `build_scorecards` and `check_models`).

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add src/model_eval/cli.py && git commit -s -m "refactor: scores_command uses build_scorecards() for name resolution

Replaces inline resolution logic with the shared build_scorecards()
helper. Fuzzy notices now read from scorecard match types.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 10: Rewrite the model-eval skill

**Files:**
- Modify: `.claude/commands/model-eval.md`

- [ ] **Step 1: Rewrite the skill to composite-first**

Replace the contents of `.claude/commands/model-eval.md` with the updated skill. Key changes from the current version:

**CLI invocation (step 2):** Add `--weights` option documentation:
```
   - For custom weights: add `--weights arena=60,aa=40` (values are pure weights, normalized internally)
```

**Step 6 (Enhance with analysis) — rewrite to three sub-steps:**

6a. **Enhance the Category Analysis section** — The generated report now contains a Category Analysis section with structured findings showing all models' percentiles per category. Rewrite each finding in-place with interpretive prose:
- What the percentile gap means practically ("96th percentile in coding places it in the top handful of models globally")
- Cross-category patterns ("strong across STEM categories but drops to 88th percentile in creative writing")
- Deployment implications ("if your workload is coding-heavy, the 7-percentile composite gap matters")
- For 3+ model comparisons, discuss the full ranking — don't just compare top vs bottom

6b. **Enhance the source-level Key Findings** — Same as current, but reference composite percentiles alongside raw scores for context.

6c. **Write Overall Conclusions** — Structure becomes composite-first:
1. **Overall positioning** — Lead with composite percentiles and tiers. Raw ranks become supporting evidence.
2. **Topic profile** — Characterize each model using Category Analysis data.
3. **Cross-source agreement** — Note where Arena and AA agree vs diverge.
4. **Confidence and caveats** — Note variant estimations, single-source categories, fuzzy matches.
5. **Summary table** — Values are composite percentiles.
6. **Bottom line** — 2-3 sentences using percentile language.

**Tier and Gap Language section — replace with percentile-based:**

```markdown
## Tier and Gap Language

When writing findings and conclusions, use percentile-based vocabulary from the report's Definitions section:

**Tier names** (based on composite percentile): Frontier (≥95th), Near-frontier (85th–94th), Upper-mid (50th–84th), Mid-tier (15th–49th), Long-tail (below 15th). Use these consistently instead of ad-hoc phrases.

**Gap significance** (composite percentile distance):
- <5 percentile points: "effectively equivalent"
- 5–15 percentile points: "moderate advantage"
- >15 percentile points: "clear separation"

**Source-level language** (used when enhancing per-source Key Findings):
- Arena: "statistically indistinguishable" / "small but statistically significant difference" / "clear separation" (based on confidence interval overlap)
- AA: "not clearly distinguishable" / "moderate difference" / "clear separation" (based on population stdev)
```

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/model-eval.md && git commit -s -m "feat: rewrite model-eval skill to composite-first analysis

Skill now leads with composite percentiles. Adds guidance for
enhancing Category Analysis section, cross-source agreement,
and confidence caveats. Tier/gap vocabulary maps to percentile
ranges. Documents --weights option.

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 11: Run linting, type checking, and full test suite

**Files:** None (validation only)

- [ ] **Step 1: Run linting**

Run: `make lint`
Expected: No errors. Fix any ruff issues.

- [ ] **Step 2: Run formatting**

Run: `make format`
Expected: No changes needed (or auto-fixed).

- [ ] **Step 3: Run type checking**

Run: `make typecheck`
Expected: No mypy errors. The `MatchType` move and new imports should type-check cleanly.

- [ ] **Step 4: Run full test suite**

Run: `make test`
Expected: All tests pass.

- [ ] **Step 5: Fix any issues found, commit if needed**

If any lint/type/test issues found, fix them and commit with specific file names:

```bash
git add src/model_eval/models.py src/model_eval/scoring.py src/model_eval/cli.py && git commit -s -m "fix: address lint and type-check issues

Assisted-by: Claude <noreply@anthropic.com>"
```

---

### Task 12: End-to-end smoke test

**Files:** None (manual validation)

- [ ] **Step 1: Run a comparison with composite scoring**

Run: `uv run model-eval -m "claude-opus-4-6,gpt-4.1" --weights arena=60,aa=40`

Verify the generated report contains:
- "Composite Scores (Arena 60% / AA 40%)" section with a table
- Per-model detail cards with match type annotations
- Category Analysis section with structured findings showing all models
- Updated Definitions section with percentile-based tiers

- [ ] **Step 2: Run the scores command with new weight syntax**

Run: `uv run model-eval scores -m "claude-opus-4-6,gpt-4.1" --weights arena=60,aa=40`

Verify the Rich table output still works correctly with the new weight parsing.

- [ ] **Step 3: Run a 3-model comparison to verify middle model appears**

Run: `uv run model-eval -m "claude-opus-4-6,gpt-4.1,gemini-2.5-pro"`

Verify the Category Analysis findings show all three models with percentiles, not just the top and bottom.

- [ ] **Step 4: Verify the skill works**

Invoke `/model-eval` to compare two models. Verify that:
- The generated report has the new composite sections
- The skill's analysis references composite percentiles
- The Category Analysis findings are enhanced with prose

- [ ] **Step 5: Commit the spec and plan docs**

```bash
git add docs/superpowers/specs/2026-06-16-composite-report-integration-design.md docs/superpowers/plans/2026-06-16-composite-report-integration.md && git commit -s -m "docs: add composite report integration design and implementation plan

Assisted-by: Claude <noreply@anthropic.com>"
```
