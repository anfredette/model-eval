# model-eval

Automated LLM model evaluation tool that generates detailed reports from
multiple evaluation sources. It pulls data from [Arena](https://lmarena.ai/)
(human preference ratings) and [Artificial
Analysis](https://artificialanalysis.ai/) (automated benchmarks, speed, latency,
and pricing), then produces a report with global rankings, category breakdowns,
head-to-head comparisons, and key findings.

Works for **single-model evaluation** (where does this model rank?) and
**multi-model comparison** (how do these models or families stack up?).

The tool works in two modes: a `model-eval` **CLI** that generates data-driven
reports with deterministic findings, and a `/model-eval` **Claude skill** that
runs the CLI and then layers on narrative analysis with an Overall Assessment
section.

See [sample_report.md](docs/examples/sample_report.md) or
[sample_report.pdf](docs/examples/sample_report.pdf) for examples created with
the `/model-eval` Claude skill.

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/anfredette/model-eval.git
cd model-eval
uv sync
```

## Setup

### Data Sources

Both data sources cache locally in `.model_cache/` inside the project directory.
Caches auto-refresh if older than 24 hours, and auto-fetch if empty on first
run.

**Arena** (no setup needed): Data is fetched from HuggingFace automatically.

**Artificial Analysis**: Requires a free API key from
[artificialanalysis.ai](https://artificialanalysis.ai/):

```bash
export AA_API_KEY=your_api_key_here
```

On first run, both caches will auto-populate. You can also sync manually:

```bash
uv run model-eval sync-aa       # Refresh AA data (requires AA_API_KEY)
uv run model-eval sync-arena    # Refresh Arena data (no key needed)
```

If AA auto-sync fails with an auth error, check that `AA_API_KEY` is set
correctly.

**Optional -- PDF output** requires [pandoc](https://pandoc.org/installing.html)
and a LaTeX engine (pdflatex, xelatex, or lualatex):

```bash
# macOS
brew install pandoc basictex          # or: brew install pandoc mactex-no-gui

# Debian/Ubuntu
sudo apt install pandoc texlive-latex-recommended

# Fedora
sudo dnf install pandoc texlive-latex
```

## Usage

### Claude Skill (recommended)

The best results come from running inside a [Claude
Code](https://docs.anthropic.com/en/docs/claude-code) session. The `/model-eval`
skill provides a natural language interface -- just describe what you want to
evaluate and Claude handles the rest. It builds the right CLI command, reads the
generated report, then enhances it with interpretive Key Findings and a full
Overall Assessment section covering positioning, value proposition, quality
profiles, and a side-by-side summary table.

From the `model-eval` project directory:

```bash
cd /path/to/model-eval
claude
```

Then use the skill:

```
/model-eval Evaluate claude-opus-4-6
/model-eval Compare Trinity vs Qwen model families
/model-eval How does Gemini 3 stack up against Gemma 4?
/model-eval Compare just Arena data for trinity and qwen, and generate a PDF
```

Claude will:

1. Parse the natural language request and build the appropriate CLI command
2. Run the CLI to generate data tables, head-to-head comparisons, and findings
3. Enhance the Key Findings with narrative interpretation
4. Write an Overall Assessment section with positioning analysis, a summary
   table, and a bottom-line recommendation
5. Summarize the key findings in the chat

If a model isn't found, Claude will present fuzzy-matched suggestions. If none
match, it will offer to sync the caches to pick up newly added models.

### CLI

Use the CLI directly if you don't have a Claude Code session or don't need the
narrative interpretation.

```bash
# Evaluate a single model -- report auto-named in reports/
uv run model-eval -m "claude-opus-4-6"

# Compare specific models
uv run model-eval -m "trinity-large-preview,qwen3-235b-a22b"

# Compare entire model families
uv run model-eval -m "trinity,qwen" --families

# Use only specific sources
uv run model-eval -m "claude-opus-4-6" --sources arena

# Generate a PDF alongside the markdown report
uv run model-eval -m "trinity-large-preview,qwen3-235b-a22b" --pdf

# Override the output path (skips auto-naming)
uv run model-eval -m "trinity,qwen" --families -o custom_report.md

# Use a custom AA data file instead of the cache
uv run model-eval -m "trinity,qwen" --aa-data path/to/data.json
```

Reports are saved to `reports/` with auto-generated names based on the models
compared, date, and a sequence number (e.g., `qwen_trinity_2026_05_01_00.md`).
Use `-o` to override the path.

### Fuzzy Matching

If a model name isn't found, the CLI suggests similar models:

```
Model "gemni-3" not found. Similar models: gemini-3-pro, gemini-3-flash, gemini-3.1-pro-preview
```

## Output Structure

The generated markdown report includes:

- **Global Rankings** -- Consolidated leaderboard showing each subject model's
  neighborhood (+-5 models), with `[N models not shown]` gap markers for distant
  models
- **Category Ratings** -- General capabilities (7 categories) and industry
  categories (7 categories) side-by-side
- **Head-to-Head** -- Pairwise comparison across all 14 categories with deltas
  and winner per category (multi-model reports)
- **Win/Loss Summary** -- Cross-matchup overview (multi-model reports)
- **Distribution Charts** -- Histogram showing where evaluated models sit in the
  full population, with staggered arrow markers and family-color coding (PNG,
  one per source)
- **Key Findings** -- Analytical findings with tier labels (Frontier through
  Long-tail based on absolute rank) and statistically grounded gap descriptions
  (CI overlap for Arena, stdev-relative for AA)
- **Definitions** -- Reference table for tier boundaries and gap significance
  methodology
- **Overall Assessment** -- Narrative analysis (added by the `/model-eval`
  skill)

## Development

```bash
uv sync --extra dev
make lint       # Ruff linter
make format     # Ruff auto-format
make typecheck  # Mypy type checking
make test       # Run all tests
```

## Adding a New Data Source

1. Create a new module in `src/model_eval/sources/`
2. Implement the `DataSource` protocol (see `sources/__init__.py`)
3. Call `register_source("name", YourSourceClass)` at module level
4. Import the module in `cli.py` to trigger registration

## Attribution

Data provided by *Artificial Analysis*
([https://artificialanalysis.ai](https://artificialanalysis.ai/)) and *Arena*
([https://lmarena.ai](https://lmarena.ai/)).

## License

Apache-2.0
