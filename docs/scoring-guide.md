# Scoring Guide

model-eval compares LLM models by normalizing scores from multiple benchmark sources onto a common scale, then compositing them into a single rating. This guide explains how each piece works.

## Data Sources

model-eval uses two independent data sources that measure model quality in fundamentally different ways.

### Arena (Human Preference)

[Arena](https://lmarena.ai/) (formerly LMSYS Chatbot Arena) ranks models using **human preference judgments**. Real users interact with pairs of anonymous models and vote for the one they prefer. Votes are aggregated into Bradley-Terry Elo ratings.

- **Score range**: ~700–1555 (Elo-style ratings)
- **Categories**: 27, including general (coding, math, creative writing, instruction following) and industry-specific (legal, science, software/IT, healthcare, etc.), plus 8 language-specific categories
- **Confidence intervals**: Each rating has lower/upper bounds reflecting statistical uncertainty
- **Strengths**: Captures subjective qualities — helpfulness, writing style, conversational fluency
- **Limitations**: Biased toward user-facing chat tasks; less coverage of specialized capabilities

Data is fetched from the HuggingFace dataset `lmarena-ai/leaderboard-dataset` via `model-eval sync-arena`.

### Artificial Analysis (Automated Benchmarks)

[Artificial Analysis](https://artificialanalysis.ai/) evaluates models using **automated benchmark suites** — standardized tests with known correct answers, run programmatically.

- **Score range**: 0–100 for aggregate indices; 0–1 for individual benchmarks
- **Aggregate indices**: Intelligence Index (overall), Coding Index, Math Index
- **Individual benchmarks** (7): GPQA Diamond (science), Humanity's Last Exam (cross-domain), SciCode (scientific coding), LiveCodeBench (coding), MMLU-Pro (language understanding), MATH-500 (math), AIME (competition math)
- **Strengths**: Precise for measurable capabilities; reproducible; covers specific skill areas
- **Limitations**: Less reflective of subjective qualities like writing style or helpfulness

Data is fetched from the AA API via `model-eval sync-aa` (requires `AA_API_KEY`).

## Model Name Resolution

Models are identified differently across sources. Arena uses names like `llama-3.1-8b-instruct`, AA uses names like `Llama 3.1 Instruct 8B`, and deployment catalogs use HuggingFace repo IDs like `meta-llama/llama-3.1-8b-instruct`. The resolver matches these automatically.

### Match Types

- **Exact**: Identical string match
- **Equivalent**: Same model, different formatting (case, punctuation, word order, org prefix, separators)
- **Fuzzy**: Approximate match requiring `--fuzzy` flag to accept (suffix-stripped variants, subset tokens, version-adjacent, size-aware)

### Resolution Pipeline

The resolver tries 13 strategies in order, returning the first match:

| Step | Type | What it does |
|---|---|---|
| 1 | Exact | String equality |
| 2 | Equivalent | Case-insensitive |
| 3–4 | Equivalent | Org-prefix stripping (handles `meta-llama/`, `redhatai/`, and baked-in prefixes like `meta-`, `ibm-`, `nvidia-`, `amazon-`) |
| 5 | Equivalent | Punctuation normalization (dashes, underscores, spaces) |
| 6 | Equivalent | Separator normalization (dots, alpha-digit boundaries: `qwen2.5` = `qwen-2-5`) |
| 7 | Equivalent | Token-set matching (order-independent: `qwen2.5-coder-32b-instruct` = `qwen2.5 coder instruct 32b`) |
| 8–9 | Fuzzy | Suffix stripping (removes quantization, instruct, reasoning suffixes) |
| 10 | Fuzzy | Subset token matching (`Llama 4 Scout` tokens are a subset of `llama-4-scout-17b-16e-instruct`) |
| 11 | Fuzzy | Size-aware word matching (prefers candidates with matching parameter size) |
| 12 | Fuzzy | Version-adjacent (closest version number with same base) |
| 13 | Fuzzy | Normalized substring |

All fuzzy steps (8–13) require the **model family name** to match. Family names are extracted as the first alphabetic token after org stripping (e.g., `llama`, `qwen`, `mistral`, `granite`). This prevents cross-family false matches like `qwen-7b-instruct` matching `mistral-7b-instruct`.

### Token Filtering

Token-set matching filters out noise tokens to improve matching:
- **Quantization tokens**: `fp8`, `dynamic`, `nvfp4`, `hf`
- **Date suffixes**: 4-digit YYMM patterns (e.g., `2501`, `2503`)
- **Numeric token ordering**: Pure digit tokens preserve their original order (`4-6` does not match `6-4`), while other tokens are order-independent

### Org Prefix Stripping

Some model names have vendor org names baked in with a dash separator instead of a slash. The resolver strips these known prefixes:
- `meta-` (e.g., `meta-llama-3.1-8b` → `llama-3.1-8b`)
- `ibm-` (e.g., `ibm-granite-3.1-8b` → `granite-3.1-8b`)
- `nvidia-` (e.g., `nvidia-nemotron-3-nano` → `nemotron-3-nano`)
- `amazon-` (e.g., `amazon-nova-pro` → `nova-pro`)

This list requires periodic review when new models or vendors appear. Check Arena/AA data and deployment catalogs for model names starting with vendor prefixes after each data sync.

## Score Normalization

Arena and AA use incompatible score ranges with very different distributions:
- Arena Elo ratings span ~700–1555 with mild top-compression
- AA intelligence/coding indices are 0–100 but severely bottom-compressed (95% of models score below 50)

### Tied-Rank Percentile

Scores are normalized to percentile ranks — "what percentage of models does this one beat?" — using a tied-rank approach:

1. **Sort** all models in a source/category by raw score (descending)
2. **Group** adjacent models whose scores are within the tie threshold into tied ranks
3. **Assign** each group the same percentile using the mean-rank method

A percentile of 85.0 means "this model scores higher than 85% of all models in this source."

### Tie Thresholds

Tie grouping prevents inflating meaningless score differences:

- **Arena**: Two models are tied if their confidence intervals overlap bidirectionally (`A.upper >= B.lower AND B.upper >= A.lower`). Uses the anchor model's CI — each new model is compared against the group's first (highest-rated) model, not the previous one.
- **AA**: Two models are tied if their scores are within `0.1 × population standard deviation` of the group anchor.

### Population-Level Normalization

Percentiles are computed against the **full cached population** (all models in the source), not just the models being queried. This ensures stable, meaningful percentiles regardless of which models you compare.

## Composite Scoring

When both sources have data for a model in a category, the composite score is a weighted average of the two percentile ranks:

```
composite = arena_weight × arena_percentile + aa_weight × aa_percentile
```

Default weights are 50/50, configurable via `--weights`. When only one source has data, the composite equals that source's percentile.

### Provenance Flags

Each score carries a provenance flag indicating which sources contributed:
- `[B]` — Both sources (composited)
- `[A]` — Arena only
- `[AA]` — AA only

## Category Taxonomy

model-eval defines 34 unified categories across both sources:

| Category Group | Count | Source | Examples |
|---|---|---|---|
| Composited (both sources) | 3 | Arena + AA | overall, coding, math |
| General | 4 | Arena only | creative_writing, instruction_following, hard_prompts, expert |
| Interaction | 2 | Arena only | multi_turn, longer_query |
| Industry | 7 | Arena only | software/IT, legal, science, healthcare, etc. |
| Language | 8 | Arena only | english, chinese, french, japanese, etc. |
| Other Arena | 2 | Arena only | hard_prompts_english, exclude_ties |
| AA Benchmarks | 7 | AA only | GPQA, HLE, SciCode, LiveCodeBench, MMLU-Pro, MATH-500, AIME |

The default display shows 21 key categories. Use `--all-categories` to show all 34.

## Variant Handling

When the resolver matches a model variant (quantized, instruct, reasoning) to a different variant's benchmark score, the scoring pipeline applies an adjustment and marks it with reduced confidence.

### Quantization Discounts

Applied as a multiplicative factor to the raw score:

| Quantization | Factor | Quality Impact |
|---|---|---|
| FP8, FP8-dynamic | ×1.0 | Negligible |
| W8A8 | ×0.97 | Minor (3%) |
| W4A16, NVFP4 | ×0.92 | Moderate (8%) |

These factors are from empirical measurements in llm-d-planner.

### Reasoning/Thinking Deltas

Computed empirically from paired models in the cached data where both reasoning and non-reasoning variants exist:
- **AA Intelligence Index**: Median delta +5.0 (from 66 paired models)
- **Arena Elo**: Median delta +3.7 (from 16 paired models)

### Bidirectional Adjustments

All adjustments work in both directions:
- Have full-precision, want quantized → multiply by discount
- Have quantized, want full-precision → divide by discount
- Have base, want reasoning → add delta
- Have reasoning, want base → subtract delta

### Confidence Indicators

Adjusted scores display `*` next to the percentile and a footnote explaining the adjustment:

```
│ llama-3.3-70b-w4a16 │ 1212.7 │ 12.880 │  40.4* │ 31.0* │ 35.7 [B] │

* Estimated scores:
  llama-3.3-70b-w4a16 (Arena): quantized.w4a16: x0.92
  llama-3.3-70b-w4a16 (AA): quantized.w4a16: x0.92
```

## CLI Usage

### Sync Data

```bash
# Fetch Arena leaderboard from HuggingFace
model-eval sync-arena

# Fetch AA models from API (requires AA_API_KEY env var)
AA_API_KEY=your-key model-eval sync-aa
```

### Check Model Resolution

```bash
# Check how model names resolve in each source
model-eval check -m "claude-opus-4-6,gpt-4o"

# Accept fuzzy matches
model-eval check -m "Llama-3.1-70B-Instruct-FP8" --fuzzy

# Check all models from a catalog file
model-eval check --catalog path/to/model_catalog.json --fuzzy
```

### View Scores

```bash
# Compare models with default 50/50 weighting
model-eval scores -m "claude-opus-4-6,gemini-2.5-pro"

# Custom Arena/AA weighting
model-eval scores -m "model1,model2" --weights 60/40

# Show all 34 categories
model-eval scores -m "model1" --all-categories

# Score all models from a catalog file
model-eval scores --catalog path/to/model_catalog.json --fuzzy

# Accept fuzzy matches
model-eval scores -m "Llama-3.1-70B-Instruct-FP8" --fuzzy
```

### Generate Full Reports

```bash
# Generate markdown comparison report
model-eval -m "claude-opus-4-6,gpt-4o" -s arena,artificial_analysis

# Generate PDF
model-eval -m "model1,model2" --pdf
```
