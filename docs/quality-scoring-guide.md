# Quality Scoring Guide

model-eval compares LLM models by normalizing scores from multiple benchmark sources onto a common scale, then compositing them into a single rating. This guide explains how each piece works.

## Data Sources

model-eval uses two independent data sources that measure model quality in fundamentally different ways.

### Arena (Human Preference)

[Arena](https://lmarena.ai/) (formerly LMSYS Chatbot Arena) ranks models using **human preference judgments**. Real users interact with pairs of anonymous models and vote for the one they prefer. Votes are aggregated into Bradley-Terry Elo ratings.

- **Score range**: ~700–1550 (Elo-style ratings)
- **Categories**: 27, including general (coding, math, creative writing, instruction following) and industry-specific (legal, science, software/IT, healthcare, etc.), plus 8 language-specific categories
- **Confidence intervals**: Each rating has lower/upper bounds reflecting statistical uncertainty
- **Strengths**: Captures subjective qualities — helpfulness, writing style, conversational fluency
- **Limitations**: Biased toward user-facing chat tasks; less coverage of specialized capabilities

Data is fetched from the HuggingFace dataset `lmarena-ai/leaderboard-dataset` via `model-eval sync-arena`.

### Artificial Analysis (Automated Benchmarks)

[Artificial Analysis](https://artificialanalysis.ai/) evaluates models using **automated benchmark suites** — standardized tests with known correct answers, run programmatically.

- **Score range**: 0–100 for aggregate indices; 0–1 for individual benchmarks
- **Aggregate indices**: Intelligence Index (overall), Coding Index, Math Index
- **Intelligence Index (v4.0)** aggregates scores from 10 evaluations: GPQA Diamond (science), Humanity's Last Exam (cross-domain), SciCode (scientific coding), Terminal-Bench Hard (CLI tasks), IFBench (instruction following), AA-LCR (long-context retrieval), AA-Omniscience (broad knowledge), GDPval-AA (quantitative reasoning), tau2-Bench Telecom (agent tasks), CritPt (critical thinking). See [AA's methodology](https://artificialanalysis.ai/methodology) for the current composition — AA may update this list over time.
- **Individually tracked benchmarks** (7): model-eval tracks these as separate per-model scores: GPQA Diamond, Humanity's Last Exam, SciCode, LiveCodeBench, MMLU-Pro, MATH-500, AIME. Three of these (GPQA Diamond, HLE, SciCode) are also part of the Intelligence Index v4.0; the other four are independent benchmarks not included in the index.
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

Fuzzy steps 10, 11, and 13 require the **model family name** to match. Family names are extracted as the first alphabetic token after org stripping (e.g., `llama`, `qwen`, `mistral`, `granite`). This prevents cross-family false matches like `qwen-7b-instruct` matching `mistral-7b-instruct`. Steps 8–9 (suffix-stripped matching) have no family check. Step 12 (version-adjacent) uses parsed version base comparison instead of family extraction.

### Token Filtering

Token-set matching filters out noise tokens to improve matching:
- **Quantization tokens**: `fp8`, `dynamic`, `nvfp4`, `hf`, and any token starting with `quantized` (e.g., `quantized.w4a16`, `quantized.w8a8`)
- **Date suffixes**: YYMM patterns for years 2024–2029 (e.g., `2501`, `2903`)
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
- Arena Elo ratings span ~700–1550 with mild top-compression
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
- **AA**: Two models are tied if their scores are within `0.1 × standard deviation` of the group anchor.

### Population-Level Normalization

Percentiles are computed against the **full cached population** (all models in the source), not just the models being queried. This ensures stable, meaningful percentiles regardless of which models you compare.

## Composite Scoring

When both sources have data for a model in a category, the composite score is a weighted average of the two percentile ranks:

```
composite = arena_weight × arena_percentile + aa_weight × aa_percentile
```

Default weights are `arena=50,aa=50`, configurable via `--weights arena=60,aa=40`. Values are pure weights, normalized internally. When only one source has data, the composite equals that source's percentile.

### Provenance Flags

Each score carries a provenance flag indicating which sources contributed. The composite scores table uses short codes:
- `[B]` — Both sources (composited)
- `[A]` — Arena only
- `[AA]` — AA only

Category findings use full-word labels: `[Both]`, `[Arena Only]`, `[AA Only]`, `[Mixed]`. The "Mixed" label appears when some models in a category have both sources and others have only one.

## Tiers and Gap Significance

### Tier Classification

Models are classified into tiers for quick positioning. Two tier systems are used depending on context:

**Rank-based tiers** (used in per-source Key Findings):

| Tier | Rank Range |
|---|---|
| Frontier | 1–10 |
| Near-frontier | 11–25 |
| Upper-mid | 26–75 |
| Mid-tier | 76–150 |
| Long-tail | 151+ |

**Percentile-based tiers** (used in Composite Scores and Category Analysis):

| Tier | Percentile Range |
|---|---|
| Frontier | ≥95th |
| Near-frontier | 85th–94th |
| Upper-mid | 50th–84th |
| Mid-tier | 15th–49th |
| Long-tail | Below 15th |

### Gap Significance

Gap descriptions vary by context:

**Composite percentile gaps** (used in Category Analysis findings):

| Gap | Description |
|---|---|
| <5 percentile points | Effectively equivalent |
| 5–15 percentile points | Moderate advantage |
| >15 percentile points | Clear separation |

**Arena gaps** (per-source findings): Based on confidence interval overlap — "statistically indistinguishable" (CIs overlap), "small but statistically significant difference" (CIs don't overlap, gap <20 points), or "clear separation" (gap ≥20 points).

**AA gaps** (per-source findings): Based on gap relative to population standard deviation — "not clearly distinguishable" (<0.5σ), "moderate difference" (0.5–1.0σ), or "clear separation" (>1.0σ).

## Report Features

### Composite Percentile Chart

Reports include a composite percentile chart — a horizontal scale from 0–100 with tier bands marked visually and arrow markers showing each model's position. This provides a quick visual summary of model positioning across tiers.

### Per-Source Distribution Charts

Each data source (Arena, AA) generates a histogram showing the full population score distribution with staggered arrow markers for the evaluated models. These show where models fall within the source's overall population.

### Composite Scores Table

The main summary table shows all models' percentile scores grouped by category group (General Capabilities, Industry, Benchmarks), with provenance flags and the active Arena/AA weighting displayed in the header.

### Model Detail Cards

Each model gets a detail card showing Arena raw score, Arena percentile, AA raw score, AA percentile, composite percentile, and source provenance for every category. Cards also display match type information and fuzzy-match warnings where applicable.

### Head-to-Head Comparisons

When comparing models, the report includes per-dimension delta tables with a winner column. Deltas exceeding 25 points are bolded.

### Per-Source Key Findings

Each data source generates its own findings section with contextual analysis — overall positioning, head-to-head summaries, strengths/weaknesses, and profile differences (STEM vs. humanities leanings).

### Category Findings

The Category Analysis section provides structured findings for each category, ranking all models by composite percentile and describing the gap significance between them. Each finding includes a provenance flag indicating which sources contributed data for that category.

## Category Taxonomy

model-eval defines 34 unified categories across both sources:

| Category Group | Count | Source | Examples |
|---|---|---|---|
| Composited (both sources) | 3 | Arena + AA | overall, coding, math |
| General | 4 | Arena only | creative_writing, instruction_following, hard_prompts, expert |
| Interaction | 2 | Arena only | multi_turn, longer_query |
| Industry | 8 | Arena only | software/IT, legal, science, math, writing, business/finance, entertainment, healthcare |
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

### Reasoning/Instruct Variant Flagging

When the resolver matches across variant boundaries (e.g., a reasoning or thinking model matched to a non-reasoning variant's scores, or an instruct model matched to a base variant), the system flags the mismatch descriptively but does **not** apply a numerical adjustment. The variant detection matches both "reasoning" and "thinking" keywords. The variant description appears in confidence indicators (see below).

The codebase includes functions to compute empirical reasoning deltas from paired models (`compute_reasoning_deltas()`, `compute_arena_thinking_delta()` in `variants.py`), but these are not currently wired into the scoring pipeline.

### Bidirectional Adjustments

Quantization adjustments work in both directions:
- Have full-precision, want quantized → multiply by discount
- Have quantized, want full-precision → divide by discount

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

# Check against specific sources only
model-eval check -m "model1" -s arena
```

### View Scores

```bash
# Compare models with default 50/50 weighting
model-eval scores -m "claude-opus-4-6,gemini-2.5-pro"

# Custom Arena/AA weighting
model-eval scores -m "model1,model2" --weights arena=60,aa=40

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

# Treat names as family prefixes (matches all variants)
model-eval -m "qwen,llama" --families

# Custom output path (auto-generates in reports/ if not set)
model-eval -m "model1,model2" -o path/to/output.md

# Use custom AA data file (bypasses cache)
model-eval -m "model1,model2" --aa-data path/to/aa_data.json
```

## ScoringEngine API

The `ScoringEngine` class in `engine.py` provides the primary programmatic API for external consumers (e.g., llm-d-planner). It pre-computes normalizations across the full population once, then supports cheap per-model lookups via `get_scores()` and `get_scores_batch()`. The CLI delegates to it internally.
