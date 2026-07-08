# Porting Guide: model-eval Scoring → llm-d-planner

This document tells the llm-d-planner session exactly what to copy from
model-eval, how the pieces fit together, and how to integrate them. It is
self-contained — the porting session does not need to re-explore model-eval.

## 1. Architecture Overview

### Module Dependency Graph

```
engine.py  ←  the public API (ScoringEngine)
  ├── scoring.py       normalization + composite computation
  │     ├── categories.py    CATEGORY_MAP, DEFAULT_CATEGORIES
  │     ├── models.py        NormalizedScore, CompositeScore, ModelScorecard, MatchType
  │     ├── tiers.py         percentile_gap_significance (used by generate_category_findings)
  │     └── variants.py      quantization discount factors, detect_variant_delta
  ├── resolver.py      13-strategy model name resolution
  │     └── models.py  MatchType
  ├── arena_client.py  Arena data fetching + cache (HuggingFace datasets)
  │     └── (external: datasets, pandas)
  └── aa_client.py     Artificial Analysis API client + cache
        └── (external: httpx)

sources/__init__.py    DataSource protocol + registry
sources/arena.py       Arena source implementation
  ├── arena_client.py
  └── resolver.py
sources/artificial_analysis.py   AA source implementation
  ├── aa_client.py
  └── resolver.py
```

### Data Flow

```
Cache files (.model_cache/arena_models.json, aa_models.json)
  │  ← populated by arena_client.sync() / aa_client.sync()
  │  ← OR checked-in snapshots in the planner repo
  ▼
ScoringEngine.__init__()
  │  loads cache → collects known names → pre-computes normalizations
  │  normalizations = { category → { model_name → NormalizedScore } }
  ▼
ScoringEngine.get_scores("model-name", fuzzy=True/False)
  │  1. resolve_model_names() against known Arena + AA names
  │  2. filter by match type (EXACT/EQUIVALENT always; FUZZY if flag set)
  │  3. look up pre-computed NormalizedScores per category
  │  4. apply variant adjustments (quantization discounts)
  │  5. compute_composite() = weighted average of Arena + AA percentiles
  ▼
ModelScorecard
  ├── model_name, arena_name, aa_name, match types
  ├── overall: CompositeScore (percentile + raw scores from both sources)
  └── categories: { "coding" → CompositeScore, "math" → CompositeScore, ... }
```

## 2. Files to Copy

Source: `model-eval/src/model_eval/`
Target: `llm-d-planner/packages/llm-quality-scoring/src/llm_quality_scoring/`

### Core (stdlib-only dependencies)

| File | Role | Lines |
|------|------|-------|
| `engine.py` | **Public API** — `ScoringEngine` class with `get_scores()` / `get_scores_batch()` | ~150 |
| `scoring.py` | `compute_normalizations()`, tied-rank percentiles, composite computation, category findings | ~280 |
| `models.py` | Dataclasses: `NormalizedScore`, `CompositeScore`, `ModelScorecard`, `MatchType`, etc. | ~170 |
| `categories.py` | `CATEGORY_MAP` (33 categories → Arena category + AA field), `DEFAULT_CATEGORIES`, display names | ~170 |
| `variants.py` | `QUANTIZATION_DISCOUNTS`, `detect_variant_delta()`, reasoning delta computation | ~110 |
| `tiers.py` | Tier classification (rank-based, percentile-based), gap significance functions | ~85 |
| `resolver.py` | 13-strategy model name resolution: exact → case → org-stripped → punctuation → separator → token-set → suffix-stripped → subset → size-aware → version-adjacent → substring | ~400 |

### Data Clients (external deps)

| File | Role | External Deps |
|------|------|---------------|
| `arena_client.py` | HuggingFace Arena leaderboard fetch + JSON cache | `datasets`, `pandas` |
| `aa_client.py` | Artificial Analysis REST API fetch + JSON cache | `httpx` |

### Source Implementations (optional — needed for `fetch_and_compare` workflow)

| File | Role |
|------|------|
| `sources/__init__.py` | `DataSource` protocol, source registry |
| `sources/arena.py` | Arena source: find models, build rankings, head-to-head comparisons |
| `sources/artificial_analysis.py` | AA source: AAModel pydantic model, matching, comparison tables |

## 3. Target Layout

```
llm-d-planner/
├── packages/
│   └── llm-quality-scoring/
│       ├── pyproject.toml
│       └── src/
│           └── llm_quality_scoring/
│               ├── __init__.py          # export ScoringEngine
│               ├── engine.py
│               ├── scoring.py
│               ├── models.py
│               ├── categories.py
│               ├── variants.py
│               ├── tiers.py
│               ├── resolver.py
│               ├── arena_client.py
│               ├── aa_client.py
│               └── sources/
│                   ├── __init__.py
│                   ├── arena.py
│                   └── artificial_analysis.py
├── data/
│   └── quality_cache/               # checked-in data snapshots
│       ├── arena_models.json
│       ├── aa_models.json
│       ├── arena_dist.json
│       └── aa_dist.json
└── src/
    └── planner/
        └── recommendation/
            └── quality/
                └── adapter.py        # thin wrapper implementing QualityScorer Protocol
```

### pyproject.toml for the scoring package

```toml
[project]
name = "llm-quality-scoring"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",       # AA API client
    "datasets>=3.0",     # Arena data from HuggingFace
    "pandas>=2.0",       # Arena data processing
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/llm_quality_scoring"]
```

The planner's own `pyproject.toml` would reference it as a path dependency:
```toml
[project]
dependencies = [
    "llm-quality-scoring @ {root:uri}/packages/llm-quality-scoring",
    # ... other deps
]
```

## 4. Import Rename

All internal imports change from `model_eval.X` to `llm_quality_scoring.X`.
This is a mechanical find-and-replace across the copied files:

```
model_eval.categories  →  llm_quality_scoring.categories
model_eval.models      →  llm_quality_scoring.models
model_eval.scoring     →  llm_quality_scoring.scoring
model_eval.resolver    →  llm_quality_scoring.resolver
model_eval.tiers       →  llm_quality_scoring.tiers
model_eval.variants    →  llm_quality_scoring.variants
model_eval.engine      →  llm_quality_scoring.engine
model_eval.aa_client   →  llm_quality_scoring.aa_client
model_eval.arena_client → llm_quality_scoring.arena_client
```

Also update `_PROJECT_ROOT` in `aa_client.py` (line 26) to point to the
appropriate location for cache files in the planner repo layout.

## 5. What to Delete in Planner

Once the scoring package is integrated, these become redundant:

| File / Symbol | Why |
|---------------|-----|
| `src/planner/recommendation/quality/usecase_scorer.py` | Replaced entirely by `ScoringEngine` + adapter |
| `src/planner/recommendation/quality/__init__.py` | Re-export from adapter instead |
| `BENCHMARK_TO_AA_MAP` (in usecase_scorer.py) | The 13-strategy resolver handles all matching |
| `QUANTIZATION_DISCOUNTS` (in usecase_scorer.py) | Duplicated in `variants.py` (same values) |
| `data/benchmarks/accuracy/weighted_scores/*.csv` | Pre-computed scores replaced by live percentile normalization |
| `scripts/recalculate_weighted_scores.py` | No longer needed |
| `scripts/interpolate_benchmark_scores.py` | No longer needed |
| `scripts/interpolate_benchmark_scores_robust.py` | No longer needed |
| `ACCURACY_TIERS` dict in `scorer.py` | Parameter-count fallback; use composite percentile instead |

**Keep** the `Scorer` class in `scorer.py` — it handles price, latency, and
complexity scoring which are independent of quality. Only `score_accuracy()`
changes to use the new engine.

## 6. Integration: QualityScorer Adapter

The planner's `ConfigFinder` expects `QualityScorer` Protocol:
```python
class QualityScorer(Protocol):
    def get_quality_score(self, model_name: str, use_case: str) -> float: ...
```

Create a thin adapter in `src/planner/recommendation/quality/adapter.py`:

```python
from llm_quality_scoring.engine import ScoringEngine

# Map planner use cases to scoring categories.
# Each use case maps to one or more categories with weights.
#
# *** PLACEHOLDER WEIGHTS — these are starting estimates, NOT validated. ***
# Tune based on domain expertise and empirical comparison against the
# existing UseCaseQualityScorer before relying on them in production.
USE_CASE_CATEGORY_MAP: dict[str, list[tuple[str, float]]] = {
    "chatbot_conversational": [
        ("overall", 0.4), ("instruction_following", 0.3),
        ("creative_writing", 0.15), ("multi_turn", 0.15),
    ],
    "code_completion": [
        ("coding", 0.5), ("livecodebench", 0.3), ("scicode", 0.2),
    ],
    "code_generation_detailed": [
        ("coding", 0.4), ("livecodebench", 0.3),
        ("instruction_following", 0.15), ("scicode", 0.15),
    ],
    "translation": [
        ("overall", 0.5), ("instruction_following", 0.3),
        ("creative_writing", 0.2),
    ],
    "content_generation": [
        ("creative_writing", 0.4), ("instruction_following", 0.3),
        ("overall", 0.3),
    ],
    "summarization_short": [
        ("overall", 0.4), ("instruction_following", 0.4),
        ("longer_query", 0.2),
    ],
    "document_analysis_rag": [
        ("overall", 0.3), ("expert", 0.3),
        ("longer_query", 0.2), ("instruction_following", 0.2),
    ],
    "long_document_summarization": [
        ("longer_query", 0.4), ("overall", 0.3),
        ("instruction_following", 0.3),
    ],
    "research_legal_analysis": [
        ("expert", 0.3), ("overall", 0.25),
        ("industry_legal_and_government", 0.25), ("hard_prompts", 0.2),
    ],
}


class ScoringEngineAdapter:
    """Wraps ScoringEngine to implement the QualityScorer protocol."""

    def __init__(self, engine: ScoringEngine) -> None:
        self._engine = engine

    def get_quality_score(self, model_name: str, use_case: str) -> float:
        sc = self._engine.get_scores(model_name, fuzzy=True)
        if sc is None:
            return 0.0

        use_case_key = use_case.lower().replace(" ", "_").replace("-", "_")
        cat_weights = USE_CASE_CATEGORY_MAP.get(use_case_key)
        if not cat_weights:
            # Fallback: use overall composite
            return sc.overall.percentile if sc.overall else 0.0

        total_weight = 0.0
        weighted_sum = 0.0
        for cat, weight in cat_weights:
            cs = sc.categories.get(cat)
            if cs is not None:
                weighted_sum += weight * cs.percentile
                total_weight += weight

        if total_weight <= 0:
            return sc.overall.percentile if sc.overall else 0.0

        return round(weighted_sum / total_weight, 2)
```

### Wiring into ConfigFinder

In `api/dependencies.py` (or wherever `ConfigFinder` is constructed):

```python
from llm_quality_scoring.engine import ScoringEngine
from planner.recommendation.quality.adapter import ScoringEngineAdapter

# At startup — load once, reuse across requests
engine = ScoringEngine()  # loads from cache
adapter = ScoringEngineAdapter(engine)

config_finder = ConfigFinder(
    benchmark_repo=benchmark_repo,
    catalog=catalog,
    quality_scorer=adapter,
)
```

### Wiring into Scorer

In `recommendation/scorer.py`, replace `score_accuracy()`:

```python
def score_accuracy(self, model_name: str, use_case: str,
                   quality_scorer=None, ...) -> int:
    if quality_scorer:
        score = quality_scorer.get_quality_score(model_name, use_case)
        if score > 0:
            return int(score)
    return self.score_accuracy_by_size(param_count)
```

## 7. Category-to-Use-Case Mapping

The model-eval system has **categories** (benchmark dimensions — what we
measure). The planner has **use cases** (deployment scenarios — what the
customer wants to do).

**Categories** (33 total, 21 default):
- General: overall, coding, math, creative_writing, instruction_following,
  hard_prompts, expert, multi_turn, longer_query
- Industry: software_and_it, legal_and_government, life_and_physical_science,
  mathematical, writing_and_literature
- AA Benchmarks: mmlu_pro, gpqa, hle, livecodebench, scicode, math_500, aime

**Use cases** (9 in planner):
- chatbot_conversational, code_completion, code_generation_detailed,
  translation, content_generation, summarization_short,
  document_analysis_rag, long_document_summarization, research_legal_analysis

The `USE_CASE_CATEGORY_MAP` in the adapter (section 6) maps each use case
to a weighted combination of categories. **These weights are placeholders —
they have not been validated against the existing `UseCaseQualityScorer`
output.** Before deploying, compare the adapter's scores against the current
weighted-CSV scores for a representative set of models and tune the weights
to match or improve on them.

## 8. Data Management

### Option A: Checked-in Snapshots (recommended for CI/offline)

Check cache files into `data/quality_cache/`:
```
data/quality_cache/arena_models.json    # ~3 MB, ~9000 rows
data/quality_cache/aa_models.json       # ~400 KB, ~540 models
```

Configure `ScoringEngine` to load from this path:
```python
engine = ScoringEngine(
    arena_rows=load_json("data/quality_cache/arena_models.json")["rows"],
    aa_models=load_json("data/quality_cache/aa_models.json")["models"],
)
```

Update snapshots periodically (weekly/monthly) by running sync commands and
committing the result.

### Option B: Live Refresh

Use the client `sync()` functions to fetch fresh data:
```python
from llm_quality_scoring import arena_client, aa_client

# Refresh Arena data (no API key needed)
count, path = arena_client.sync()

# Refresh AA data (requires API key)
count, path = aa_client.sync(api_key="...")

# Then load the engine from fresh cache
engine = ScoringEngine()
```

The `is_cache_stale()` function in `aa_client.py` checks if cached data is
older than a configurable threshold (default 24 hours).

### Cache Path Configuration

`aa_client.py` computes `_PROJECT_ROOT` as `Path(__file__).parent.parent.parent`.
For the monorepo layout, update this to point to the planner repo root or
accept a configurable cache directory:

```python
_CACHE_DIR = Path(os.environ.get(
    "LLM_QUALITY_CACHE_DIR",
    str(Path(__file__).parent.parent.parent / ".model_cache")
))
```

## 9. Migration Checklist

1. [ ] Create `packages/llm-quality-scoring/` directory structure
2. [ ] Copy the 12 source files from model-eval (section 2)
3. [ ] Create `pyproject.toml` for the scoring package (section 3)
4. [ ] Find-and-replace `model_eval.` → `llm_quality_scoring.` in all copied files
5. [ ] Update `_PROJECT_ROOT` / cache path in `aa_client.py` (section 8)
6. [ ] Create `data/quality_cache/` with snapshots from model-eval's `.model_cache/`
7. [ ] Add path dependency to planner's `pyproject.toml`
8. [ ] Create `quality/adapter.py` with `ScoringEngineAdapter` (section 6)
9. [ ] Wire adapter into `ConfigFinder` construction (section 6)
10. [ ] Update `Scorer.score_accuracy()` to use the adapter (section 6)
11. [ ] Delete replaced code (section 5)
12. [ ] Copy relevant tests from model-eval's `tests/` (test_engine.py,
    test_scoring.py, test_resolver.py, test_tiers.py)
13. [ ] Run planner test suite — verify no regressions
14. [ ] Tune `USE_CASE_CATEGORY_MAP` weights based on domain knowledge

## 10. Key Differences from Current Planner Scoring

| Aspect | Current (UseCaseQualityScorer) | New (ScoringEngine) |
|--------|-------------------------------|---------------------|
| Score type | Absolute weighted benchmark score (0-100) | Population-relative percentile (0-100) |
| Data source | Pre-computed CSVs from AA benchmarks | Live normalization from Arena + AA |
| Sources | AA only | Arena + AA (configurable weights) |
| Name matching | 5 strategies + manual BENCHMARK_TO_AA_MAP | 13 strategies, no manual map needed |
| Quantization | Same discounts (FP8=1.0, W8A8=0.97, W4A16=0.92) | Same discounts, applied as variant adjustments |
| Categories | 9 use cases | 33 categories (mapped to use cases via adapter) |
| Update frequency | Manual CSV regeneration | Cache refresh via `sync()` |

The main behavioral change: scores become **relative to the population**.
A model scoring 85/100 today means "better than 85% of all models in the
dataset." As new, better models arrive and data is refreshed, that same
model's score may decrease — which correctly reflects its position in the
evolving landscape. This is a feature, not a bug, but stakeholders should
be informed.
