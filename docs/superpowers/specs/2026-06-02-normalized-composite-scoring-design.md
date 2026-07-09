# Normalized Composite Scoring

## Context

model-eval uses two data sources with fundamentally different scoring systems:

- **Arena**: Bradley-Terry Elo ratings (~700–1555) across 27 categories, with human preference judgments. Mild top-compression (30% of models within 100pts of max).
- **Artificial Analysis (AA)**: Automated benchmark aggregate indices on a 0–100 scale, but severely bottom-compressed (95% of models score below 50 on intelligence/coding indices; math index is well-distributed). Also exposes 7 individual benchmark scores (GPQA, HLE, SciCode, LiveCodeBench, MMLU-Pro, MATH-500, AIME).

These scores cannot be compared directly. This design adds normalization, composite scoring, per-category breakdowns, and a debug CLI command. The scoring logic will be ported to llm-d-planner's `UseCaseQualityScorer` to enhance its accuracy scoring dimension.

## Design Decisions

- **Normalization**: Tied-rank percentile — percentile ranks with significance-based tie grouping to prevent inflating meaningless score differences
- **Composite weighting**: Configurable via CLI, default 50/50 Arena/AA
- **Subject areas**: Union of all categories from both sources (34 total); provenance flags when only one source contributes
- **Tie detection**: Bidirectional CI overlap for Arena; epsilon-based (0.1 × stdev) for AA. Anchor-based grouping prevents chaining.
- **Debug CLI**: `model-eval scores` subcommand with Rich terminal table output

## Architecture

```
cli.py (scores + check commands)
  └─> scoring.py (pure normalization + composition math, no I/O)
  └─> categories.py (category taxonomy + cross-source mapping)
  └─> models.py (dataclasses: NormalizedScore, CompositeScore, ModelScorecard)
  └─> resolver.py (model name matching across sources)
  └─> aa_client / arena_client (data loading + caching)
```

`scoring.py` is deliberately I/O-free so it can be lifted into llm-d-planner.

## Data Models (models.py)

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

    @property
    def provenance(self) -> str:  # derived from score presence
        ...  # "both", "arena_only", "aa_only", "none"

@dataclass
class ModelScorecard:
    model_name: str
    arena_name: str | None
    aa_name: str | None
    overall: CompositeScore | None
    categories: dict[str, CompositeScore]
```

## Category Taxonomy (categories.py)

34 unified categories from both sources:

| Source | Categories |
|---|---|
| Both sources (composited) | overall, coding, math |
| Arena only (27 categories) | creative_writing, instruction_following, hard_prompts, expert, multi_turn, longer_query, 8 industry categories, 8 language categories, hard_prompts_english, exclude_ties |
| AA only (7 benchmarks) | mmlu_pro, gpqa, hle, livecodebench, scicode, math_500, aime |

Default display shows 21 key categories. `--all-categories` shows all 34.

## Model Name Resolution (resolver.py)

12-step matching pipeline, in order of confidence:

| Step | Type | Description |
|---|---|---|
| 1 | EXACT | Exact string match |
| 2 | EQUIVALENT | Case-insensitive |
| 3-4 | EQUIVALENT | Org-prefix stripping (bidirectional) |
| 5 | EQUIVALENT | Punctuation-normalized (dashes, underscores, spaces) |
| 6 | EQUIVALENT | Separator-normalized (dots, alpha-digit boundaries) |
| 7 | EQUIVALENT | Token-set (order-independent for non-numeric tokens) |
| 8-9 | FUZZY | Suffix-stripped (quantization, instruct, reasoning) |
| 10 | FUZZY | Size-aware partial word match |
| 11 | FUZZY | Version-adjacent |
| 12 | FUZZY | Normalized substring |

Key features:
- **Suffix stripping**: Iteratively removes quantization (`-fp8`, `-quantized.w4a16`), instruct (`-instruct`, `-instruct-YYMM`), and reasoning suffixes. Uses regex for dated instruct variants.
- **Token filtering**: Filters quantization tokens and YYMM date suffixes from token-set matching.
- **Numeric token ordering**: Pure digit tokens preserve original order (prevents `4-6` matching `6-4`).
- **Size-aware matching**: Only returns a match when the candidate has the same parameter size.

### Planned: Family-name matching

Fuzzy steps currently allow wrong-family matches (e.g., `qwen2.5-7b-instruct` → `mistral-7b-instruct`). Fix: extract the model family name and require it to match before accepting fuzzy matches.

## Normalization Algorithm

### Tied-Rank Percentile

1. Sort all models in a source/category by raw score descending
2. Group adjacent models whose scores are within the tie threshold (anchor-based)
3. Assign each group the same percentile using the mean-rank method:
   `percentile = ((total - models_below - 0.5 * group_size) / total) * 100`

### Tie Thresholds

- **Arena**: Bidirectional CI overlap — two models are tied if `A.upper >= B.lower AND B.upper >= A.lower`
- **AA**: Epsilon-based — tied if scores are within `0.1 × population_stdev`

Percentiles are computed against the **full cached population** (360 Arena models, 519 AA models), not just queried models.

## Composite Scoring

```
if both sources have data:
    composite = arena_weight * arena_percentile + aa_weight * aa_percentile
elif only one source:
    composite = that source's percentile
```

Weights default to 50/50, configurable via `--weights 60/40`.

### Planned: Variant Score Estimation

When the resolver matches a variant to a different variant (e.g., instruct → base, or base → quantized), apply a bidirectional delta — adjusting the available score to estimate the needed variant's score.

| Have | Want | Adjustment |
|---|---|---|
| Base | Instruct | + instruct delta |
| Instruct | Base | - instruct delta |
| Base | Reasoning | + reasoning delta |
| Reasoning | Base | - reasoning delta |
| Full-precision | Quantized (FP8) | ×1.0 |
| Full-precision | Quantized (W8A8) | ×0.97 |
| Full-precision | Quantized (W4A16, NVFP4) | ×0.92 |
| Quantized | Full-precision | ÷ quantization factor |

Quantization factors from planner's existing empirical discounts. Instruct/reasoning deltas computed from paired data in the cache — models where both variants exist, computing the average raw-score difference per source.

Estimated scores will carry a confidence indicator (1.0 for exact, 0.8 for variant-adjusted) and surface the adjustment in CLI output.

## CLI Commands

### `model-eval scores`

```bash
uv run model-eval scores -m "model1,model2" [--catalog file.json] [--weights 60/40] [--all-categories] [--fuzzy]
```

- Summary "Overall" table with all models, per-category tables (one per category with all models when >1 model, per-model breakdown when single model)
- Fuzzy match notices shown before score tables
- `--catalog` reads model IDs from a JSON file (e.g., planner's `model_catalog.json`)

### `model-eval check`

```bash
uv run model-eval check -m "model1,model2" [--catalog file.json] [--fuzzy]
```

Shows how each model name resolves against each source, with similar-name suggestions for not-found models.

## Current File Map

| File | Description |
|---|---|
| `src/model_eval/models.py` | NormalizedScore, CompositeScore, ModelScorecard dataclasses |
| `src/model_eval/categories.py` | 34-category taxonomy, CATEGORY_MAP, display name helpers |
| `src/model_eval/scoring.py` | Tied-rank percentile normalization, composite scoring (pure, no I/O) |
| `src/model_eval/resolver.py` | 12-step model name matching with suffix stripping, token filtering, size-aware matching |
| `src/model_eval/cli.py` | `scores`, `check`, `sync-aa`, `sync-arena` subcommands |
| `src/model_eval/aa_client.py` | AA API client, caches 10 fields (3 indices + 7 benchmarks) |
| `src/model_eval/arena_client.py` | Arena HuggingFace client, caches 27 categories |
| `tests/test_scoring.py` | Normalization and composition unit tests |
| `tests/test_categories.py` | Category mapping unit tests |
| `tests/test_resolver.py` | Resolver matching unit tests |

## Planned Work

### 1. Fix fuzzy matching — family-name requirement
Require model family name to match before accepting fuzzy matches. Add subset token matching for cases like `llama-4-scout-17b-16e-instruct` → `Llama 4 Scout`.

### 2. Variant score estimation
Bring planner's quantization discounts into model-eval. Compute empirical instruct/reasoning uplift from paired data. Add confidence indicators to scores.

### 3. User-facing documentation
Create a user-facing document (`docs/quality-scoring-guide.md`) explaining:
- The two data sources (Arena human preference vs AA automated benchmarks) and what they measure
- How model names are resolved across sources (the 12-step pipeline)
- How scores are normalized (tied-rank percentile) and why
- How composite scores are computed and what provenance flags mean
- Category taxonomy — which categories come from which source
- Variant handling — what happens with quantized/instruct/reasoning variants
- CLI usage examples for `scores`, `check`, `sync-aa`, `sync-arena`

### 4. Port to llm-d-planner
Copy `scoring.py`, `resolver.py`, `categories.py` into planner. Wire into `UseCaseQualityScorer.get_quality_score()` to replace AA-only CSV lookup with composite scoring.
