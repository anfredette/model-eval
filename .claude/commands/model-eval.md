Evaluate and compare LLM models using Arena and Artificial Analysis data.

## Evaluating Models

When the user asks to evaluate or compare models:

1. Parse which models or families they want to evaluate from their message
2. Build the appropriate CLI command:
   - For specific models: `uv run model-eval -m "model1,model2"`
   - For model families: `uv run model-eval -m "family1,family2" --families`
   - For specific sources only: add `--sources arena` or `--sources artificial_analysis`
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

   a. **Enhance the Key Findings sections with interpretive prose:**
      - Read the Arena Key Findings and AA Key Findings sections in the generated file
      - Rewrite each finding in-place with narrative interpretation, adding:
        - Context about what the numbers mean practically (e.g., "this places it alongside models like X and Y")
        - Relative tier placement and what it implies
        - Implications for deployment decisions (e.g., "well-suited for latency-sensitive applications")
        - Caveats and limitations worth noting
      - Keep the same numbered-list format but with richer, more readable prose
      - Example: transform `**Speed:** X is 2.5x faster (132 vs 52 t/s).` into `**Speed advantage:** X is dramatically faster than comparable Y models: 132 t/s vs 52-55 t/s for the Y 235B variants. This is likely due to X's much smaller active parameter count (13B active vs 22B active) despite having more total parameters.`

   b. **Write an Overall Conclusions section and insert it after the intro/section table (before Part 1).** The template reserves this position. Structure it as:
      1. **Overall positioning** — Where each model/family sits using standardized tier names (Frontier, Near-frontier, Upper-mid, Mid-tier, Long-tail) with specific rank and score evidence from both Arena and AA
      2. **Lineup depth** — How broad each family's lineup is (number of models on each platform)
      3. **Value proposition** — Each side's niche: speed/cost vs quality vs breadth, with specific numbers
      4. **Quality profile differences** — STEM-leaning vs humanities-leaning, citing specific category deltas from head-to-head data
      5. **Evaluation coverage** — Note any limitations (different variants evaluated on different platforms, missing data)
      6. **Summary table** — A markdown table comparing key factors side by side:

         | Factor | Model A | Model B |
         |--------|---------|---------|
         | Top-tier quality | ... | ... |
         | Same-tier quality | ... | ... |
         | Speed | ... | ... |
         | Latency | ... | ... |
         | Price | ... | ... |
         | Context window | ... | ... |
         | Strength categories | ... | ... |
         | Weakness categories | ... | ... |
         | Model variety | ... | ... |
         | Open weights | ... | ... |

      7. **Bottom line** — 2-3 sentence prose summary of when to pick each model family
      - Write the conclusions using the actual data from the report — cite specific numbers, ranks, scores, and category names

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
- "Sync the AA data" (run sync-aa)
- "Sync the Arena data" (run sync-arena)

## Tier and Gap Language

When writing findings and conclusions, use the standardized vocabulary from the report's Definitions section:

**Tier names** (based on absolute rank): Frontier (1-10), Near-frontier (11-25), Upper-mid (26-75), Mid-tier (76-150), Long-tail (151+). Use these consistently instead of ad-hoc phrases like "top tier" or "upper third."

**Gap significance language:**
- Arena: "statistically indistinguishable" / "small but statistically significant difference" / "clear separation" (based on confidence interval overlap)
- AA: "not clearly distinguishable" / "moderate difference" / "clear separation" (based on population stdev)

Calibrate language about model gaps to the actual distribution. A 42-point Arena gap may sound large but could be only 0.35 stdev — don't overstate it. The generated findings already use these terms; align your prose analysis accordingly.

**Distribution charts** are auto-generated alongside the report (PNG files). No manual action needed — they appear in the report between the About section and Key Findings for each source.

## Notes

- Both data sources cache locally in `.model_cache/` and auto-refresh if older than 24 hours
- Distribution stats are cached in `.model_cache/` and recomputed on sync
- Arena data is public (HuggingFace); AA data requires `AA_API_KEY`
