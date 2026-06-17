# Composite Report Integration

## Context

model-eval has a rich composite scoring engine (`scoring.py`) that normalizes Arena and AA scores via tied-rank percentiles, computes weighted composites across sources, and produces per-category scorecards with provenance tracking and variant estimation. However, this engine is only wired to the `scores` CLI subcommand — the report generation pipeline (`cli.py:main` → `renderer.py` → `comparison.md.j2`) and the `/model-eval` skill know nothing about it.

This design wires composite scoring end-to-end: CLI → renderer → template → skill. Reports become richer out of the box with structured composite data, and the skill shifts from raw-score-based prose to composite-percentile-first analysis.

## Design Decisions

- **Template-side rendering** — Composite tables and per-category findings are rendered directly in the Jinja2 template from structured data, making reports self-contained without Claude's analysis layer
- **Composite-first skill** — The skill leads with composite percentiles; raw scores become supporting evidence
- **CLI-layer scoring helper** — `build_scorecards()` wraps name resolution + the existing `compute_scorecards()` into a single call. It lives in `cli.py` (not `scoring.py`) because it depends on `resolver.py`, which is model-eval-specific. `scoring.py` stays portable to llm-d-planner.
- **Percentile-based vocabulary** — Tier and gap language in the skill maps to percentile ranges rather than absolute ranks. Percentile-based tier/gap functions are added to `tiers.py` alongside the existing rank-based ones.
- **Match type tracking** — Each scorecard records how its model name was resolved (exact, equivalent, fuzzy) so the report can flag lower-confidence matches. `MatchType` moves to `models.py`. Note: `models.py` already has a `TYPE_CHECKING` import of `MatchResult` from `resolver.py` — this is safe because that import only runs during type checking, while `resolver.py`'s new runtime import of `MatchType` from `models.py` creates no circular dependency at runtime.
- **Named weights syntax** — `--weights arena=50,aa=50` with explicit source names. Values are pure weights (not percentages) — the code normalizes by dividing each by the sum.

## Data Model Changes

### `models.py`

**`MatchType`** — Move from `resolver.py` to `models.py` so `ModelScorecard` can reference it at runtime. `models.py` already has a `TYPE_CHECKING` import of `MatchResult` from `resolver.py` (line 7-8), so it's not strictly a leaf module — but the `MatchResult` import only runs during type checking. The new `MatchType` definition in `models.py` creates no circular import because `resolver.py`'s import of `MatchType` is a runtime import while `models.py`'s import of `MatchResult` stays under `TYPE_CHECKING`.

```python
class MatchType(enum.Enum):
    EXACT = "exact"
    EQUIVALENT = "equivalent"
    FUZZY = "fuzzy"
    NONE = "none"
```

**`CategoryFinding`** — New structured dataclass for per-category findings (rather than pre-formatted strings), so the Jinja2 template can render them with full control over formatting. Uses `ranked_models` (all models with data, sorted descending by percentile) instead of leader/trailer — so 3+ model comparisons surface every model, not just the extremes:

```python
@dataclass
class CategoryFinding:
    category: str
    display_name: str
    ranked_models: list[tuple[str, float]]  # (name, percentile) sorted descending
    gap_description: str       # "effectively equivalent", "moderate advantage", "clear separation"
    provenance: str            # "both", "arena_only", "aa_only", "mixed"
    variant_notes: list[str]   # e.g., ["model-A: instruct variant (confidence: 0.97)"]
```

**`ComparisonResult`** — Add scorecard and weight fields:

```python
@dataclass
class ComparisonResult:
    model_names: list[str]
    sources: list[SourceData] = field(default_factory=list)
    overall_conclusions: list[str] = field(default_factory=list)
    scorecards: list[ModelScorecard] = field(default_factory=list)
    category_findings: list[CategoryFinding] = field(default_factory=list)
    arena_weight: float = 0.5
    aa_weight: float = 0.5
```

**`ModelScorecard`** — Add match type fields:

```python
@dataclass
class ModelScorecard:
    model_name: str
    arena_name: str | None
    aa_name: str | None
    arena_match_type: MatchType | None = None
    aa_match_type: MatchType | None = None
    overall: CompositeScore | None = None
    categories: dict[str, CompositeScore] = field(default_factory=dict)
```

No changes to `NormalizedScore`, `CompositeScore`, `SourceData`, or other existing models.

## Tier System Changes

### `tiers.py` — Add percentile-based functions

The existing rank-based tier system (`tier_label()`, `arena_gap_significance()`, `aa_gap_significance()`) stays unchanged and continues to be used in source-level report sections where raw ranks and scores are the natural unit.

New percentile-based functions are added alongside them for composite scoring contexts:

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

**Where each system is used:**
- **Rank-based** (`tier_label`, `arena_gap_significance`, `aa_gap_significance`) — Source-level findings in `arena.py` and `artificial_analysis.py`. These operate on raw scores within a single source.
- **Percentile-based** (`percentile_tier_label`, `percentile_gap_significance`) — Composite scoring sections: the Category Analysis, composite scorecard tables, and the skill's analysis prose. These operate on normalized cross-source percentiles.

## CLI Changes

### `--weights` syntax

Both `main` and `scores_command` use named weight syntax:

```
--weights arena=50,aa=50    Source weights (default: arena=50,aa=50)
```

Values are pure weights, not percentages. The code normalizes by dividing each by the sum. `--weights arena=3,aa=2` produces 60%/40%. The report header displays normalized percentages: `## Composite Scores (Arena 60% / AA 40%)`.

A shared `parse_weights()` helper in `cli.py` handles parsing and validation:

```python
def parse_weights(weights_str: str) -> tuple[float, float]:
    """Parse 'arena=N,aa=N' into normalized (arena_weight, aa_weight).

    Values are pure weights — normalized by dividing each by the sum.
    """
    ...
```

Validation:
1. Split on `,`, split each part on `=`
2. Validate source names are `arena` and `aa`
3. Validate values are positive numbers
4. Normalize: `weight / sum(all_weights)`
5. Error if any source name is missing or unrecognized

The `scores_command` migrates from `50/50` positional syntax to the named syntax. This is an intentional breaking change — the old format was ambiguous about which position mapped to which source. The error message clearly shows the expected format.

### `cli.py:main` — Compute scorecards

After all sources have produced `SourceData` and before calling `render_comparison`, the main command:

1. Loads Arena rows and AA models from cache
2. Calls `build_scorecards()` to resolve names and produce `ModelScorecard` list
3. Calls `generate_category_findings()` to produce structured per-category findings
4. Attaches scorecards, weights, and category findings to `ComparisonResult`

### `build_scorecards()` in `cli.py`

`build_scorecards()` lives in `cli.py` — not `scoring.py` — because it depends on `resolver.py` for name resolution, which is model-eval-specific. Keeping it out of `scoring.py` preserves portability to llm-d-planner.

It is a wrapper around the existing `compute_scorecards()`. It handles name resolution (producing match types), builds the `target_models: list[tuple[str, str | None, str | None]]` tuples that `compute_scorecards()` expects, calls it, and populates `arena_match_type`/`aa_match_type` on the returned scorecards.

`compute_scorecards()` remains unchanged — it still accepts pre-resolved `target_models` and does the normalization + composition math.

```python
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

    Wraps compute_scorecards() with name resolution. Lives in the
    CLI layer (not scoring.py) because it depends on resolver.py,
    which is model-eval-specific. scoring.py stays portable to
    llm-d-planner.
    """
    ...
```

`scores_command` migrates from doing its own resolution (cli.py lines ~355–411) to calling `build_scorecards()`. Fuzzy-match notices are printed after the call by reading match types from the returned scorecards.

### `generate_category_findings()` in `scoring.py`

Returns structured `CategoryFinding` objects (not pre-formatted strings) so the template has full rendering control:

```python
def generate_category_findings(
    scorecards: list[ModelScorecard],
    categories: list[str],
) -> list[CategoryFinding]:
    """Generate cross-source findings for each category with data
    for 2+ models.

    Uses percentile_gap_significance() from tiers.py for gap
    descriptions.
    """
    ...
```

Per category with data for 2+ models, produces a `CategoryFinding` with:
1. All models with data, sorted descending by percentile (`ranked_models`)
2. Gap description via `percentile_gap_significance()` — covers the spread from highest to lowest
3. Provenance — "both", "arena_only", "aa_only", or "mixed" if models have different provenance
4. Variant notes for any estimated scores (confidence < 1.0)

This function stays I/O-free (consistent with `scoring.py`'s design for portability to llm-d-planner).

## Renderer Changes

### `renderer.py`

Pass scorecards, weights, category findings, and categories list to the template context. The categories list comes from `DEFAULT_CATEGORIES` — not hardcoded in the template — so it stays in sync as categories are added:

```python
from model_eval.categories import DEFAULT_CATEGORIES

content = template.render(
    model_names=result.model_names,
    sources=result.sources,
    overall_conclusions=result.overall_conclusions,
    scorecards=result.scorecards,
    arena_weight=result.arena_weight,
    aa_weight=result.aa_weight,
    category_findings=result.category_findings,
    categories=DEFAULT_CATEGORIES,
    introduction=_generate_introduction(result),
    date=date.today().isoformat(),
)
```

## Template Changes

### New report structure

```
1. Title + date + intro
2. Section table (existing)
3. Composite Scores table (NEW)
4. Per-model detail cards (NEW)
5. Category Analysis (NEW — auto-generated findings)
6. Overall Conclusions (existing — hand-written by skill)
7. Part 1, Part 2, etc. (existing source details — loop.index unaffected)
8. Definitions (existing — updated with percentile-based tiers)
```

The `Part N` numbering uses `{{ loop.index }}` over `sources`, which is inside a `{% for source in sources %}` loop. The new sections are outside this loop, so existing numbering is unaffected.

### Section 3: Composite Scores table

Unified cross-source comparison — models as rows, categories as columns, composite percentiles as values:

```markdown
## Composite Scores (Arena 60% / AA 40%)

| Model | Overall | Coding | Math | Creative | Instruct | ... |
|-------|---------|--------|------|----------|----------|-----|
| **claude-opus-4-6** | 94.2 [B] | 96.1 [B] | 91.0 [B] | 88.3 [A] | ... |
| **gpt-4.1** | 91.5 [B] | 89.7 [B] | 87.2 [B] | 90.1 [A] | ... |

_[B] = both sources, [A] = Arena only, [AA] = AA only. * = estimated (variant adjustment)._
```

The header shows normalized percentages (e.g., "Arena 60% / AA 40%") regardless of what raw weights the user passed.

Only categories with data for at least one evaluated model are shown. Categories with no data for any model are omitted.

### Section 4: Per-model detail cards

One card per model with full breakdown:

```markdown
### claude-opus-4-6
_Arena: claude-opus-4-6 (exact) · AA: Claude Opus 4.6 (equivalent)_

| Category | Arena Raw | Arena %ile | AA Raw | AA %ile | Composite | Source |
|----------|-----------|-----------|--------|---------|-----------|--------|
| Overall | 1389.2 | 96.1 | 82 | 92.3 | 94.2 | Both |
| Coding | 1412.0 | 97.3 | 79 | 95.0 | 96.1 | Both |
| ...
```

Match type annotations:
- `(exact)` or `(equivalent)` — no special treatment
- `(fuzzy)` — flagged with a note: "scores based on approximate name match"
- Not found in source — shown as "not found"

Variant adjustment notes appear below the card when any score has confidence < 1.0:

```markdown
_* Estimated scores: instruct variant (confidence: 0.97)_
```

### Section 5: Category Analysis

Rendered from structured `CategoryFinding` objects. The template controls formatting — bolding model names, styling gap descriptors, choosing between bullet list or table layout:

```markdown
## Category Analysis

1. **Overall:** claude-opus-4-6 (94.2 %ile) · gemini-2.5-pro (91.5 %ile) · gpt-4.1 (88.0 %ile) — moderate advantage. [Both]
2. **Coding:** claude-opus-4-6 (96.1 %ile) · gpt-4.1 (89.7 %ile) · gemini-2.5-pro (85.2 %ile) — clear separation. [Both]
3. **Creative Writing:** gpt-4.1 (90.1 %ile) · claude-opus-4-6 (88.3 %ile) — effectively equivalent. [Arena Only]
...
```

All models with data appear in each finding, sorted by percentile. The gap description covers the spread from highest to lowest.

### Template macros (`macros.j2`)

New macros:
- `render_composite_table(scorecards, categories, arena_weight, aa_weight)` — the unified comparison table
- `render_scorecard_detail(scorecard, categories)` — per-model detail card
- `render_category_finding(finding)` — single category finding line
- `fmt_percentile(value)` — formats percentile with ordinal suffix
- `provenance_label(provenance)` — maps "both"→"[B]", "arena_only"→"[A]", "aa_only"→"[AA]"

### Definitions section update

Add percentile-based tier definitions alongside the existing rank-based ones:

```markdown
### Composite Tiers (percentile-based)

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

## Skill Rewrite

### `.claude/commands/model-eval.md`

The skill shifts to composite-first analysis. Key changes:

**Step 6 (Enhance with analysis):**

6a. **Enhance Category Analysis** — Rewrite each auto-generated category finding with interpretive prose:
- What the percentile gap means practically ("96th percentile in coding places it in the top handful of models globally")
- Cross-category patterns ("strong across STEM but drops to 88th in creative writing")
- Deployment implications ("if your workload is coding-heavy, the 7-percentile composite gap matters")

6b. **Enhance source-level Key Findings** — Same as today, but referencing composite percentiles as context alongside raw scores.

6c. **Write Overall Conclusions** — Structure becomes composite-first:

1. **Overall positioning** — Lead with composite percentiles and tiers. Raw ranks are supporting evidence: "claude-opus-4-6 sits at the 94th composite percentile (Frontier tier), combining Arena rank 4/360 and AA rank 3/519."
2. **Topic profile** — Characterize each model using Category Analysis data: "STEM-dominant (96th coding, 91st math) with a relative dip in creative writing (88th)."
3. **Cross-source agreement** — Note where Arena and AA agree vs diverge.
4. **Confidence and caveats** — Note variant estimations, single-source categories, fuzzy matches.
5. **Summary table** — Values are composite percentiles.
6. **Bottom line** — 2-3 sentences using percentile language.

**Tier and Gap Language:**

Replace rank-based vocabulary with percentile-based:
- Frontier: ≥95th percentile
- Near-frontier: 85th–94th
- Upper-mid: 50th–84th
- Mid-tier: 15th–49th
- Long-tail: below 15th

Gap significance:
- <5 percentile points: "effectively equivalent"
- 5–15 points: "moderate advantage"
- >15 points: "clear separation"

## File Change Summary

| File | Change |
|------|--------|
| `models.py` | Move `MatchType` here from `resolver.py`. Add `CategoryFinding` dataclass (with `ranked_models` for all models, not just leader/trailer). Add `scorecards`, `category_findings`, `arena_weight`, `aa_weight` to `ComparisonResult`. Add `arena_match_type`, `aa_match_type` to `ModelScorecard`. |
| `scoring.py` | Add `generate_category_findings()` returning `list[CategoryFinding]`. No new dependencies — stays portable to llm-d-planner. |
| `tiers.py` | Add `percentile_tier_label()` and `percentile_gap_significance()` alongside existing rank-based functions. |
| `cli.py` | Add `build_scorecards()` CLI helper (wraps resolver + `compute_scorecards()`). Add `--weights` (named syntax `arena=N,aa=N`, intentional breaking change from `50/50`). Add shared `parse_weights()` helper. Refactor `scores_command` to use both. |
| `resolver.py` | Import `MatchType` from `models.py` instead of defining it locally. |
| `renderer.py` | Pass scorecards, weights, category findings to template context. |
| `templates/comparison.md.j2` | Add Composite Scores table, per-model detail cards, Category Analysis section. Update Definitions with percentile-based tiers. |
| `templates/macros.j2` | Add macros for scorecard rendering (`render_composite_table`, `render_scorecard_detail`, `render_category_finding`, `fmt_percentile`, `provenance_label`). |
| `.claude/commands/model-eval.md` | Rewrite to composite-first. Percentile-based tier/gap vocabulary. |

## Files Unchanged

`categories.py`, `variants.py`, `sources/__init__.py`, `sources/arena.py`, `sources/artificial_analysis.py`, `charts.py`, `aa_client.py`, `arena_client.py`
