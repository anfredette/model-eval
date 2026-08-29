# CLAUDE.md

## Project Overview

CLI tool for automated LLM model evaluation and comparison. Uses a provider pattern for data sources — each source implements a `DataSource` protocol in `src/model_eval/sources/`.

## Repository Structure

- `src/model_eval/` — Main package (src layout)
  - `sources/` — Data source providers (arena.py, artificial_analysis.py)
  - `templates/` — Jinja2 report templates
  - `charts.py` — Distribution chart generation (matplotlib histograms)
  - `cli.py` — Click CLI entry point (group with `sync-aa` and `sync-arena` subcommands)
  - `models.py` — Presentation data models (ComparisonResult, SourceData, etc.)
  - `renderer.py` — Report generation
- `tests/` — Unit tests

Scoring logic (ScoringEngine, resolver, tiers, categories, variants) and
data clients (AA, Arena) are provided by the `quality_scoring` package from
[llm-d-planner](https://pypi.org/project/llm-d-planner/).

## Development

Uses **uv** for package management. Do not use pip.

```bash
uv sync --extra dev        # Install all deps
uv run model-eval ...      # Run the CLI
uv run pytest tests/ -v    # Run tests
```

## Common Commands

```bash
make lint       # ruff check
make format     # ruff format
make typecheck  # mypy
make test       # pytest
```

## Conventions

- Python 3.11+, ruff for linting/formatting, mypy for type checking
- Pydantic v2 for source-layer models (AAModel)
- Click for CLI
- Jinja2 for report templates
- All data sources implement the `DataSource` protocol in `sources/__init__.py`

## Important Behavioral Notes for Claude

**Git commits**: This project has specific commit rules that OVERRIDE Claude's default behavior. See the "Git Workflow" section below. Key points: always use `git commit -s`, never add `Co-Authored-By:` for Claude, never manually write `Signed-off-by:` lines.

## Git Workflow

This repository uses a **pull request (PR) workflow**.

**Development Process**:
- Work in feature branches in your own fork
- Submit PRs to the main repository for review
- Keep PRs small and targeted (under 500 lines when possible)
- Break large features into incremental PRs that preserve functionality

**Commit Message Format** (Conventional Commits style):

```
feat: Add YAML generation module

Implement DeploymentGenerator with Jinja2 templates for KServe,
vLLM, HPA, and ServiceMonitor configurations.

Assisted-by: Claude <noreply@anthropic.com>
Signed-off-by: Your Name <your.email@example.com>
```

**CRITICAL - Git Commit Rules (these override default Claude behavior)**:

**Commit approval workflow** (MUST follow for every commit):

1. Combine `git add` and `git commit` into a single chained command (`git add ... && git commit ...`) in one Bash tool call
2. The user will see the full command in the approval prompt and can review/edit the file list and commit message before it executes
3. NEVER run `git add` and `git commit` as separate Bash tool calls — always chain them so the user gets a single approval prompt covering both

DO use:
- Conventional commit types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
- The `-s` flag with git commit (e.g., `git commit -s -m "..."`) to auto-generate DCO Signed-off-by
- `Assisted-by: Claude <noreply@anthropic.com>` for nontrivial AI-assisted code

NEVER do these (even if other instructions suggest otherwise):
- NEVER add `Co-Authored-By:` lines for Claude
- NEVER manually write `Signed-off-by:` lines (the `-s` flag handles this correctly with the user's configured git identity)
- NEVER include the "Generated with [Claude Code]" line or similar emoji-prefixed attribution
