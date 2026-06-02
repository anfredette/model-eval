# Normalized Composite Scoring

## Context

model-eval uses two data sources with fundamentally different scoring systems:

- **Arena**: Bradley-Terry Elo ratings (~700–1555) across 27 categories, with human preference judgments. Mild top-compression (30% of models within 100pts of max).
- **Artificial Analysis (AA)**: Automated benchmark aggregate indices on a 0–100 scale, but severely bottom-compressed (95% of models score below 50 on intelligence/coding indices; math index is well-distributed).

These scores cannot be compared directly. This design adds normalization, composite scoring, per-category breakdowns, and a debug CLI command. The scoring logic will later be ported to llm-d-planner's `UseCaseQualityScorer` to enhance its accuracy scoring dimension.

## Design Decisions

- **Normalization**: Tied-rank percentile — percentile ranks with significance-based tie grouping to prevent inflating meaningless score differences
- **Composite weighting**: Configurable via CLI, default 50/50 Arena/AA
- **Subject areas**: Union of all categories from both sources; provenance flags when only one source contributes
- **Debug CLI**: `model-eval scores` subcommand with Rich terminal table output

## Architecture

Layered modules with clean separation of concerns:

```
cli.py (scores command)
  └─> scoring.py (pure normalization + composition math, no I/O)
  └─> categories.py (category taxonomy + cross-source mapping)
  └─> models.py (new dataclasses: NormalizedScore, CompositeScore, ModelScorecard)
  └─> aa_client / arena_client (data loading — existing)
  └─> resolver (model name matching — existing)
```

`scoring.py` is deliberately I/O-free so it can be lifted into llm-d-planner later.

## New Data Models (models.py)

```python
@dataclass
class NormalizedScore:
    raw_score: float
    percentile: float          # 0.0–100.0
    tied_rank: int
    population_size: int
    source: str                # "arena" or "aa"

@dataclass
class CompositeScore:
    category: str
    percentile: float          # weighted composite percentile
    arena_score: NormalizedScore | None
    aa_score: NormalizedScore | None
    provenance: str            # "both", "arena_only", "aa_only"

@dataclass
class ModelScorecard:
    model_name: str
    arena_name: str | None
    aa_name: str | None
    overall: CompositeScore | None
    categories: dict[str, CompositeScore]
```

## Category Taxonomy (categories.py)

The unified namespace uses Arena's category names as the backbone. AA indices map in:

| Unified Category | Arena Category | AA Field |
|---|---|---|
| `overall` | `overall` | `intelligence_index` |
| `coding` | `coding` | `coding_index` |
| `math` | `math` | `math_index` |
| `creative_writing` | `creative_writing` | — |
| `instruction_following` | `instruction_following` | — |
| `hard_prompts` | `hard_prompts` | — |
| ... (24 more Arena-only categories) | ... | — |

The default display set matches the existing 14 KEY_CATEGORIES (corrected to real data names): overall, coding, math, creative_writing, instruction_following, hard_prompts, expert, multi_turn, longer_query, industry_software_and_it_services, industry_legal_and_government, industry_life_and_physical_and_social_science, industry_mathematical, industry_writing_and_literature_and_language. `--all-categories` adds the remaining 13 (language-specific, entertainment, healthcare, business, exclude_ties, hard_prompts_english).

## Normalization Algorithm

### Tied-Rank Percentile

1. Sort all models in a source/category by raw score descending
2. Group adjacent models whose scores are within the tie threshold
3. Assign each group the same percentile using the mean-rank method:
   `percentile = ((total - models_below - 0.5 * group_size) / total) * 100`

### Tie Thresholds

- **Arena**: Two models are tied if their confidence intervals overlap (`A.rating_upper >= B.rating_lower`)
- **AA**: Two models are tied if their scores are within `epsilon = 0.1 * population_stdev` of each other (~1.4 for intelligence/coding indices, ~3.1 for math)

This prevents inflating differences in dense score regions (AA's 10–20 zone where 51% of models cluster) while preserving real differentiation where scores spread out.

## Composite Scoring

```
if both sources have data:
    composite = arena_weight * arena_percentile + aa_weight * aa_percentile
    provenance = "both"
elif only arena:
    composite = arena_percentile
    provenance = "arena_only"
elif only aa:
    composite = aa_percentile
    provenance = "aa_only"
```

Weights default to 50/50, configurable via `--weights 60/40`.

## CLI Command

```bash
uv run model-eval scores -m "claude-opus-4-6,gpt-5.5,gemini-2.5-pro" [--weights 60/40] [--all-categories] [--fuzzy]
```

### Output Format

Summary table (Rich):
```
Model Scores (Arena 50% / AA 50%)
┌─────────────────────┬────────┬───────┬───────┬────────┬────────────┐
│ Model               │ Arena  │  AA   │ Arena │  AA    │ Composite  │
│                     │  Raw   │  Raw  │  %ile │  %ile  │    %ile    │
├─────────────────────┼────────┼───────┼───────┼────────┼────────────┤
│ claude-opus-4-6     │ 1502.2 │   61  │ 100.0 │  100.0 │ 100.0 [B] │
│ gpt-5.5             │ 1498.3 │   59  │  99.3 │   99.2 │  99.3 [B] │
│ gemini-2.5-pro      │ 1480.1 │   --  │  97.5 │    --  │  97.5 [A] │
└─────────────────────┴────────┴───────┴───────┴────────┴────────────┘
[B] = both sources, [A] = Arena only, [AA] = AA only
```

Per-category breakdown (one table per model):
```
Category Scores: claude-opus-4-6
┌──────────────────┬────────┬───────┬───────┬────────┬───────────┐
│ Category         │ Arena  │  AA   │ Arena │  AA    │ Composite │
│                  │  Raw   │  Raw  │  %ile │  %ile  │   %ile    │
├──────────────────┼────────┼───────┼───────┼────────┼───────────┤
│ overall          │ 1502.2 │   61  │ 100.0 │  100.0 │ 100.0 [B] │
│ coding           │ 1495.1 │   59  │  99.1 │   99.6 │  99.4 [B] │
│ math             │ 1488.3 │   88  │  98.2 │   89.1 │  93.7 [B] │
│ creative_writing │ 1510.5 │   --  │ 100.0 │    --  │ 100.0 [A] │
└──────────────────┴────────┴───────┴───────┴────────┴───────────┘
```

## File Changes

| File | Action | Description |
|---|---|---|
| `src/model_eval/models.py` | Modify | Add NormalizedScore, CompositeScore, ModelScorecard |
| `src/model_eval/categories.py` | New | Category taxonomy, CATEGORY_MAP, display helpers |
| `src/model_eval/scoring.py` | New | Normalization, tie detection, composite scoring (pure, no I/O) |
| `src/model_eval/cli.py` | Modify | Add `scores` subcommand with Rich table output |
| `pyproject.toml` | Modify | Add `rich>=13.0` dependency |
| `tests/test_scoring.py` | New | Unit tests for normalization and composition |
| `tests/test_categories.py` | New | Unit tests for category mapping |

## Key Implementation Details

### Data Loading

The `scores` command loads the full population from both caches (not just queried models) since normalization needs population-level percentile ranks:
- `arena_client.load_cache()` — all 360 models × 27 categories
- `aa_client.load_cache()` — all 519 models

User-specified model names are resolved against both sources using the existing resolver. A model needs to be found in only one source to appear in results.

### Population Normalization

Percentile ranks are computed against the **full cached population** for each source/category, not just the queried models. This ensures stable, meaningful percentiles regardless of which models the user asks about.

### Portability to llm-d-planner

`scoring.py` takes raw score arrays and returns dataclass results — no file paths, no CLI, no Rich. When porting to llm-d-planner:
1. Copy `scoring.py` and the new dataclasses from `models.py`
2. Call the normalization functions from `UseCaseQualityScorer.get_quality_score()`
3. Replace the current AA-only CSV lookup with the composite scoring pipeline

## Verification

1. **Unit tests**: `pytest tests/test_scoring.py tests/test_categories.py -v`
   - Tied-rank correctness with known inputs
   - Arena CI-based tie detection
   - AA epsilon-based tie detection
   - Composite with both/single sources
   - Edge cases: single model, all tied, missing data
2. **Integration test**: `uv run model-eval scores -m "claude-opus-4-6,gpt-4o" --fuzzy`
   - Verify table renders with real cached data
   - Check provenance flags are correct
3. **Lint/type checks**: `make lint && make typecheck`
