# Distribution Context & Tier Standardization

## Problem

Report findings use qualitative labels ("a full tier below", "a large gap") based
on hardcoded thresholds that don't reflect the actual score distributions. At the
top of both Arena and AA, scores are heavily compressed — a 42-point Arena gap is
only 0.35 standard deviations, but the language suggests a dramatic difference.
Readers have no visual reference for where evaluated models sit in the global
population, and there is no standardized vocabulary for model tiers or gap
significance.

## Design

Three interconnected changes:

1. **Standardized tier definitions** — rank-based labels applied consistently
   across all data sources
2. **Distribution-aware gap significance** — Arena uses confidence interval
   overlap; AA uses population standard deviations
3. **Distribution charts** — histogram with staggered model markers showing the
   full population and where evaluated models sit

### Tier Definitions

Fixed rank-based tiers, same boundaries for all sources:

| Tier | Rank Range |
|------|-----------|
| Frontier | 1–10 |
| Near-frontier | 11–25 |
| Upper-mid | 26–75 |
| Mid-tier | 76–150 |
| Long-tail | 151+ |

These are absolute ranks, not percentile-based. "Frontier" means the same thing
whether the source has 354 models (Arena) or 503 models (AA).

### Gap Significance

**Arena** — uses per-model confidence intervals (`rating_lower`, `rating_upper`)
already present in the data:

| Condition | Language |
|-----------|----------|
| CIs overlap | "statistically indistinguishable" |
| CIs don't overlap, gap between closest bounds < 20 | "small but statistically significant difference" |
| CIs don't overlap, gap between closest bounds >= 20 | "clear separation" |

Example: Gemini 3.1 Pro Preview [1488.3–1497.4] vs Gemma 4 31B [1443.3–1458.6]
— CIs don't overlap, closest-bound gap is 29.7 → "clear separation."

**AA** — no per-model confidence intervals available; uses gap relative to
population standard deviation:

| Condition | Language |
|-----------|----------|
| Gap < 0.5 stdev | "not clearly distinguishable" |
| Gap 0.5–1.0 stdev | "moderate difference" |
| Gap > 1.0 stdev | "clear separation" |

AA population stdev is ~13.3 points. Example: Gemini 3.1 Pro (57) vs Gemma 4 31B
(39) = 18 points = 1.35 stdev → "clear separation."

### Distribution Charts

**Chart type:** Histogram of the full score population (Approach D) with
staggered arrow markers for evaluated models.

**Visual design:**
- Gray histogram bars showing the distribution of all models
- Vertical arrows from x-axis pointing up to staggered heights
- Labels at the top of each arrow, positioned to the left to avoid overlap
- Stagger height increases with score (lowest-rated model gets shortest line)
- Color-coded by family/organization
- Median marked with a dotted vertical line
- Legend showing family colors and total model count

**One chart per source** (Arena rating distribution, AA Intelligence Index
distribution), placed after the About section and before Key Findings.

**File placement:** Chart PNGs saved alongside the report file:
```
reports/
  gemini_gemma_2026_05_01_05.md
  gemini_gemma_2026_05_01_05.pdf
  gemini_gemma_2026_05_01_05_arena_dist.png
  gemini_gemma_2026_05_01_05_aa_dist.png
```

### Report Definitions Section

A new "Definitions" section added to the report template, placed after the last
source section and before the attribution line. Contains:

- Tier definitions table (as above)
- Gap significance methodology for each source
- Brief explanation of confidence intervals (Arena) and standard deviation
  thresholds (AA)

## Components

### New Files

**`src/model_eval/tiers.py`**

Tier classification and gap significance logic:

- `tier_label(rank: int) -> str` — returns "Frontier", "Near-frontier", etc.
- `arena_gap_significance(rating_a: float, ci_a: tuple[float, float], rating_b: float, ci_b: tuple[float, float]) -> str` — returns gap description using CI overlap
- `aa_gap_significance(score_a: float, score_b: float, population_stdev: float) -> str` — returns gap description using stdev thresholds
- `TIER_BOUNDARIES` — constant defining rank ranges

**`src/model_eval/charts.py`**

Chart generation using matplotlib:

- `generate_distribution_chart(all_scores: list[float], evaluated_models: list[dict], output_path: Path, source_name: str, median: float) -> Path` — generates Approach D histogram, returns image path
- Each evaluated model dict contains: `name`, `score`, `family`, `color`

### Modified Files

**`src/model_eval/models.py`**

Add:
```python
@dataclass
class DistributionStats:
    count: int
    min: float
    max: float
    median: float
    mean: float
    stdev: float
    p25: float
    p75: float
```

Add fields to `SourceData`:
- `distribution_stats: DistributionStats | None = None`
- `chart_path: Path | None = None`

**`src/model_eval/sources/arena.py`**

- `_compute_findings()`: replace `_tier_descriptor()` calls with
  `tiers.tier_label()`. Use `tiers.arena_gap_significance()` for gap
  descriptions. Compute and return `DistributionStats` from the full DataFrame.
- Remove `_tier_descriptor()` (replaced by `tiers.tier_label()`)

**`src/model_eval/sources/artificial_analysis.py`**

- `_compute_findings()`: replace `_aa_tier_descriptor()` and `_gap_descriptor()`
  with `tiers.tier_label()` and `tiers.aa_gap_significance()`. Compute and
  return `DistributionStats` from the full model list.
- Remove `_aa_tier_descriptor()` and `_gap_descriptor()` (replaced by tiers
  module)

**`src/model_eval/cli.py`**

- After each source returns `SourceData`, call `charts.generate_distribution_chart()`
  with the full dataset scores and evaluated model positions
- Set `source_data.chart_path` to the returned image path
- Pass chart path relative to report file for template embedding

**`src/model_eval/templates/comparison.md.j2`**

- After "About" section and "Models evaluated" line: embed chart image if
  `source.chart_path` is set: `![{{ source.source_name }} Distribution]({{ source.chart_path }})`
- Add "Definitions" section before the attribution line with tier table and gap
  significance methodology

**`pyproject.toml`**

- Add `matplotlib>=3.8` to core dependencies

### Tests

**`tests/test_tiers.py`** (new):
- `tier_label()` returns correct tier for boundary and mid-range ranks
- `arena_gap_significance()` returns correct language for overlapping CIs,
  close non-overlapping CIs, and wide gaps
- `aa_gap_significance()` returns correct language for each stdev threshold

**`tests/test_charts.py`** (new):
- `generate_distribution_chart()` creates a PNG file at the expected path
- Chart handles edge cases: single evaluated model, many evaluated models

**`tests/test_arena.py`** and **`tests/test_aa.py`** (modify):
- Update findings tests to expect new tier/gap language

### Report Fix

Update `reports/gemini_gemma_2026_05_01_05.md`:
- Replace "a full tier below" and similar language with tier-aware,
  gap-significance-aware phrasing
- Regenerate PDF

## Verification

1. `make test` — all tests pass (existing + new)
2. `make lint && make typecheck` — clean
3. Generate a fresh report: `uv run model-eval -m "gemini-3,gemma-4" --families`
   - Verify chart PNGs are created alongside the report
   - Verify findings use tier labels and gap significance language
   - Verify Definitions section appears at the end
4. Generate PDF and verify charts render correctly in the PDF
5. Update the Gemini vs Gemma report and regenerate its PDF
