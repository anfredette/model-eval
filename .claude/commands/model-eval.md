Evaluate and compare LLM models using Arena and Artificial Analysis data.

## Evaluating Models

When the user asks to evaluate or compare models:

1. Parse which models or families they want to evaluate from their message
2. Build the appropriate CLI command:
   - For specific models: `uv run model-eval -m "model1,model2"`
   - For model families: `uv run model-eval -m "family1,family2" --families`
   - For specific sources only: add `--sources arena` or `--sources artificial_analysis`
   - For custom weights: add `--weights arena=60,aa=40` (values are pure weights, normalized internally)
   - The CLI auto-generates a report name in `reports/` (e.g., `reports/claude_gpt_2025_05_01_00.md`). Use `-o path` only to override.
   - Do NOT add `--pdf` yet — generate the PDF after adding analysis (see step 7)
3. Run the command from the model-eval project directory (`/Users/anfredet/go/src/github.com/model-eval/`)
4. **If models are not found:** Check the CLI output for suggestion lines and not-found counts.
   - The CLI prints `Model "xyz" not found. Similar models: a, b, c` for each not-found model with fuzzy matches.
   - **Present suggestions to the user:** "Model 'xyz' wasn't found. Did you mean one of: a, b, c?"
   - Wait for the user's response, then re-run the CLI with the corrected model names.
   - **If no good fuzzy matches exist** (or the user says none of those), suggest syncing the cache: "The model might be new. Want me to run `uv run model-eval sync-aa` and/or `uv run model-eval sync-arena` to refresh the data?"
   - If the user says yes, sync the relevant cache(s) and re-run the command.
   - If AA reports 0 models total (empty cache), suggest running `uv run model-eval sync-aa` first.
5. Read the generated report file (parse the path from the CLI's "Comparison written to ..." output)
6. **Enhance the report with analysis** (do not ask for permission — this is what the user is requesting by invoking /model-eval):

   a. **Enhance the Category Analysis section** — The generated report contains a Category Analysis section with structured findings showing all models' percentiles per category. Rewrite each finding in-place with interpretive prose:
      - What the percentile gap means practically ("96th percentile in coding places it in the top handful of models globally")
      - Cross-category patterns ("strong across STEM categories but drops to 88th percentile in creative writing")
      - Deployment implications ("if your workload is coding-heavy, the 7-percentile composite gap matters")
      - For 3+ model comparisons, discuss the full ranking — don't just compare top vs bottom

   b. **Enhance the source-level Key Findings** — Read the Arena Key Findings and AA Key Findings sections and rewrite each finding in-place with narrative interpretation. Reference composite percentiles alongside raw scores for context. Keep the same numbered-list format but with richer, more readable prose.
      - Example: transform `**Speed:** X is 2.5x faster (132 vs 52 t/s).` into `**Speed advantage:** X is dramatically faster than comparable Y models: 132 t/s vs 52-55 t/s for the Y 235B variants. This is likely due to X's much smaller active parameter count (13B active vs 22B active) despite having more total parameters.`

   c. **Write an Overall Conclusions section and insert it after the intro/section table (before Part 1).** The template reserves this position. Structure it as composite-first:
      1. **Overall positioning** — Lead with composite percentiles and tiers. Raw ranks become supporting evidence.
      2. **Topic profile** — Characterize each model using Category Analysis data.
      3. **Cross-source agreement** — Note where Arena and AA agree vs diverge.
      4. **Confidence and caveats** — Note variant estimations, single-source categories, fuzzy matches.
      5. **Summary table** — Values are composite percentiles:

         | Factor | Model A | Model B |
         |--------|---------|---------|
         | Composite percentile | ... | ... |
         | Arena percentile | ... | ... |
         | AA percentile | ... | ... |
         | Top category | ... | ... |
         | Weakest category | ... | ... |
         | Speed | ... | ... |
         | Latency | ... | ... |
         | Price | ... | ... |

      6. **Bottom line** — 2-3 sentences using percentile language
      - Write the conclusions using the actual data from the report — cite specific composite percentiles, category scores, and tier placements

   **Accuracy checks** (apply when writing analysis in steps a–c):
   - **Top/weakest category:** When populating the summary table, scan ALL composite percentile values for each model (including Industry categories) to find the actual highest and lowest. Do not eyeball — compare numerically. Exclude "Overall" from top/weakest.
   - **Variant data cross-referencing:** A model may show data in the AA "All Models" table (which displays the matched variant) that is absent from the composite/detail cards (which use the variant-adjusted baseline). Before claiming a model "has no data" for a category, check the AA table — if the matched variant has data but the composite excludes it, say so explicitly (e.g., "Gemma's reasoning variant has an AA Agentic score of 11, but the non-reasoning baseline used for compositing lacks this data").
   - **Arithmetic:** Double-check any computed deltas (e.g., "exceeds by 30+ points") against the actual numbers in the tables before writing them.

7. **Generate PDF if the user requested it** (do not ask for permission — just generate it):
   - Run pandoc AFTER all analysis has been added to the markdown file
   - `pandoc <report>.md -o <report>.pdf --pdf-engine=xelatex -V geometry:margin=1in -V fontsize=10pt`
   - This ensures the PDF includes the enhanced findings and conclusions
8. Summarize the key findings for the user
9. Offer to explain specific sections in more detail

## Data Caching

Both sources cache data locally in `.model_cache/` inside the project directory. Caches auto-refresh:
- **Empty cache**: auto-fetched on first run (AA requires `AA_API_KEY` in environment)
- **Stale cache (>24 hours)**: auto-refreshed in the background; falls back to stale data if refresh fails
- **Manual sync**: use `sync-aa` or `sync-arena` to force a refresh

```bash
uv run model-eval sync-aa       # Refresh AA data (requires AA_API_KEY)
uv run model-eval sync-arena    # Refresh Arena data (no key needed)
```

If AA auto-sync fails with an auth error, tell the user to check that `AA_API_KEY` is set correctly.
The `--aa-data` flag can override the AA cache with a custom JSON file.

## Usage Examples

- "Evaluate claude-opus-4-6"
- "Compare trinity-large-preview with qwen3-235b-a22b"
- "How does Trinity stack up against Qwen models?" (use --families)
- "Compare just Arena data for trinity and qwen" (use --sources arena)
- "Compare with 70/30 Arena weighting" (use --weights arena=70,aa=30)
- "Sync the AA data" (run sync-aa)
- "Sync the Arena data" (run sync-arena)

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

**Distribution charts** are auto-generated alongside the report (PNG files). No manual action needed — they appear in the report between the About section and Key Findings for each source.

## Notes

- Both data sources cache locally in `.model_cache/` and auto-refresh if older than 24 hours
- Distribution stats are cached in `.model_cache/` and recomputed on sync
- Arena data is public (HuggingFace); AA data requires `AA_API_KEY`
