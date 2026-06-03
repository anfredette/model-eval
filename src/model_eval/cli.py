from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import click

import model_eval.sources.arena  # noqa: F401
import model_eval.sources.artificial_analysis  # noqa: F401
from model_eval import aa_client, arena_client
from model_eval.charts import generate_distribution_chart
from model_eval.models import ComparisonResult
from model_eval.renderer import render_comparison
from model_eval.resolver import MatchType, suggest_similar
from model_eval.sources import get_available_sources, get_source

REPORTS_DIR = Path("reports")


def _load_catalog_models(path: str) -> list[str]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "models" in data:
        return [m["model_id"] for m in data["models"] if "model_id" in m]
    raise click.UsageError(f"Expected JSON with a 'models' array containing 'model_id' fields: {path}")


def _get_model_names(models: str | None, catalog: str | None) -> list[str]:
    if catalog:
        return _load_catalog_models(catalog)
    if models:
        return [m.strip() for m in models.split(",") if m.strip()]
    raise click.UsageError("Provide either --models/-m or --catalog.")


def generate_output_path(model_names: list[str]) -> Path:
    """Generate an auto-named report path in reports/.

    Format: reports/{short1}_{short2}_{YYYY}_{MM}_{DD}_{NN}.md
    where NN increments from the highest existing file with the same prefix.
    """
    parts = [name.split("-")[0] for name in model_names]
    counts = Counter(parts)
    if any(c > 1 for c in counts.values()):
        parts = []
        for name in model_names:
            tokens = name.split("-")
            parts.append(tokens[1] if len(tokens) > 1 else tokens[0])

    prefix = "_".join(sorted(set(parts)))
    prefix = re.sub(r"[^\w.]", "_", prefix.lower())
    prefix = re.sub(r"_+", "_", prefix).strip("_")
    if len(prefix) > 50:
        prefix = prefix[:50].rsplit("_", 1)[0]
    today = date.today().strftime("%Y_%m_%d")
    base = f"{prefix}_{today}"

    REPORTS_DIR.mkdir(exist_ok=True)

    existing = list(REPORTS_DIR.glob(f"{base}_*.md"))
    max_n = -1
    pattern = re.compile(rf"^{re.escape(base)}_(\d+)\.md$")
    for p in existing:
        m = pattern.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))

    return REPORTS_DIR / f"{base}_{max_n + 1:02d}.md"


@click.group(invoke_without_command=True)
@click.option(
    "--models",
    "-m",
    default=None,
    help="Comma-separated model or family names to evaluate.",
)
@click.option(
    "--families",
    is_flag=True,
    default=False,
    help="Treat model names as family prefixes (e.g., 'qwen' matches all qwen* models).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Output markdown file path. Auto-generates in reports/ if not set.",
)
@click.option(
    "--sources",
    "-s",
    default=None,
    help=f"Comma-separated source names. Available: {', '.join(get_available_sources())}",
)
@click.option(
    "--aa-data",
    type=click.Path(exists=True),
    default=None,
    help="Path to custom Artificial Analysis JSON data file (bypasses cache).",
)
@click.option("--pdf", is_flag=True, default=False, help="Also generate a PDF via pandoc.")
@click.option(
    "--fuzzy",
    is_flag=True,
    default=False,
    help="Accept fuzzy model name matches instead of treating them as not-found.",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
@click.pass_context
def main(
    ctx: click.Context,
    models: str | None,
    families: bool,
    output: str | None,
    sources: str | None,
    aa_data: str | None,
    pdf: bool,
    fuzzy: bool,
    verbose: bool,
) -> None:
    """Evaluate and compare LLM models using data from multiple sources."""
    if ctx.invoked_subcommand is not None:
        return

    if not models:
        raise click.UsageError("Missing option '-m' / '--models'.")

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    model_names = [m.strip() for m in models.split(",") if m.strip()]
    if not model_names:
        raise click.UsageError("No model names provided.")

    source_names = (
        [s.strip() for s in sources.split(",") if s.strip()] if sources else get_available_sources()
    )

    result = ComparisonResult(model_names=model_names)

    for source_name in source_names:
        kwargs: dict[str, Any] = {}
        if source_name == "artificial_analysis" and aa_data:
            kwargs["data_path"] = Path(aa_data)

        try:
            source = get_source(source_name, **kwargs)
        except ValueError as e:
            click.echo(f"Warning: {e}", err=True)
            continue

        source_data = source.fetch_and_compare(model_names, families=families, fuzzy=fuzzy)
        result.sources.append(source_data)

        found_count = len(source_data.models_found)
        not_found_count = len(source_data.models_not_found)
        status = source_data.cache_status or ""
        parts = [f"{source.name}: {status}"]
        parts.append(f"found {found_count} model{'s' if found_count != 1 else ''}")
        if not_found_count:
            parts.append(f"{not_found_count} not found")
        click.echo(", ".join(parts) + ".")

        for name, similar in source_data.suggestions.items():
            click.echo(f'  Model "{name}" not found. Similar models: {", ".join(similar)}')

    if not result.sources:
        raise click.ClickException("No data sources produced results.")

    output_path = Path(output) if output else generate_output_path(model_names)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dist_loaders = {
        "Arena": arena_client.load_dist_cache,
        "Artificial Analysis": aa_client.load_dist_cache,
    }
    for source_data in result.sources:
        loader = dist_loaders.get(source_data.source_name)
        if not loader or not source_data.chart_models:
            continue
        dist_cache = loader()
        if not dist_cache or "scores" not in dist_cache:
            continue
        stats = dist_cache.get("stats", {})
        chart_name = source_data.source_name.lower().replace(" ", "_")
        chart_path = output_path.with_name(f"{output_path.stem}_{chart_name}_dist.png")
        generate_distribution_chart(
            all_scores=dist_cache["scores"],
            evaluated_models=source_data.chart_models,
            output_path=chart_path,
            source_name=f"{source_data.source_name} Rating",
            median=stats.get("median", 0),
        )
        source_data.chart_path = Path(chart_path.name)
        click.echo(f"Chart written to {chart_path}")

    render_comparison(result, output_path)
    click.echo(f"Comparison written to {output_path}")

    if pdf:
        if not shutil.which("pandoc"):
            raise click.ClickException(
                "pandoc is required for --pdf. Install: brew install pandoc (macOS) or apt install pandoc (Linux)."
            )
        pdf_path = output_path.with_suffix(".pdf")
        proc = subprocess.run(
            [
                "pandoc",
                str(output_path),
                "-o",
                str(pdf_path),
                "--resource-path",
                str(output_path.parent),
                "-V",
                "geometry:margin=1.5cm",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise click.ClickException(
                f"pandoc failed — a LaTeX engine is required for PDF output.\n"
                f"Install one: brew install mactex-no-gui (macOS) or apt install texlive-xetex (Linux).\n"
                f"pandoc error: {proc.stderr.strip()}"
            )
        click.echo(f"PDF written to {pdf_path}")


@main.command("sync-aa")
@click.option(
    "--api-key",
    envvar="AA_API_KEY",
    required=True,
    help="Artificial Analysis API key (or set AA_API_KEY env var).",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def sync_aa(api_key: str, verbose: bool) -> None:
    """Sync Artificial Analysis model data from the API."""
    from model_eval import aa_client

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    click.echo("Fetching models from Artificial Analysis API...")
    try:
        count, cache_path = aa_client.sync(api_key)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Synced {count} models to {cache_path}")


@main.command("sync-arena")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def sync_arena(verbose: bool) -> None:
    """Sync Arena leaderboard data from HuggingFace."""
    from model_eval import arena_client

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    click.echo("Fetching Arena leaderboard from HuggingFace...")
    try:
        count, cache_path = arena_client.sync()
    except Exception as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Synced {count} rows to {cache_path}")


@main.command("scores")
@click.option(
    "--models",
    "-m",
    default=None,
    help="Comma-separated model names to score.",
)
@click.option(
    "--catalog",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON model catalog file (e.g., model_catalog.json).",
)
@click.option(
    "--weights",
    "-w",
    default="50/50",
    help="Arena/AA weight ratio (default: 50/50).",
)
@click.option(
    "--all-categories",
    is_flag=True,
    default=False,
    help="Show all categories (default: key categories only).",
)
@click.option(
    "--fuzzy",
    is_flag=True,
    default=False,
    help="Accept fuzzy model name matches.",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def scores_command(
    models: str | None,
    catalog: str | None,
    weights: str,
    all_categories: bool,
    fuzzy: bool,
    verbose: bool,
) -> None:
    """Show normalized and composite scores for models across sources."""
    from rich.console import Console
    from rich.table import Table

    from model_eval.categories import ALL_CATEGORIES, DEFAULT_CATEGORIES, display_name
    from model_eval.models import NormalizedScore
    from model_eval.resolver import MatchType, resolve_model_names
    from model_eval.scoring import compute_scorecards

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    model_names = _get_model_names(models, catalog)

    parts = weights.split("/")
    if len(parts) != 2:
        raise click.UsageError("Weights must be in format 'arena/aa', e.g., '60/40'.")
    try:
        arena_w, aa_w = float(parts[0]), float(parts[1])
    except ValueError as e:
        raise click.UsageError("Weights must be numeric, e.g., '60/40'.") from e
    total = arena_w + aa_w
    if total == 0:
        raise click.UsageError("Weights cannot both be zero.")
    arena_weight = arena_w / total
    aa_weight = aa_w / total

    arena_rows, arena_fetched = arena_client.load_cache()
    aa_models, aa_fetched = aa_client.load_cache()

    if not arena_rows and not aa_models:
        raise click.ClickException(
            "No cached data. Run 'model-eval sync-arena' and/or 'model-eval sync-aa' first."
        )

    arena_names = sorted({r["model_name"] for r in arena_rows if r.get("category") == "overall"})
    aa_names = [m["name"] for m in aa_models]

    arena_results = resolve_model_names(model_names, arena_names) if arena_names else []
    aa_results = resolve_model_names(model_names, aa_names) if aa_names else []

    target_models: list[tuple[str, str | None, str | None]] = []
    fuzzy_notices: list[str] = []
    for i, name in enumerate(model_names):
        arena_match: str | None = None
        aa_match: str | None = None

        if arena_results:
            mr = arena_results[i]
            if mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT) or (
                fuzzy and mr.match_type == MatchType.FUZZY and mr.matched_name
            ):
                arena_match = mr.matched_name
            if arena_match and mr.match_type == MatchType.FUZZY:
                fuzzy_notices.append(f'  "{name}" -> "{arena_match}" (fuzzy match in Arena)')

        if aa_results:
            mr = aa_results[i]
            if mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT) or (
                fuzzy and mr.match_type == MatchType.FUZZY and mr.matched_name
            ):
                aa_match = mr.matched_name
            if aa_match and mr.match_type == MatchType.FUZZY:
                fuzzy_notices.append(f'  "{name}" -> "{aa_match}" (fuzzy match in AA)')

        if not arena_match and not aa_match:
            click.echo(f'Warning: "{name}" not found in either source.', err=True)
            continue

        target_models.append((name, arena_match, aa_match))

    if not target_models:
        raise click.ClickException("No models found in any source.")

    categories = ALL_CATEGORIES if all_categories else DEFAULT_CATEGORIES

    scorecards = compute_scorecards(
        arena_rows=arena_rows,
        aa_models=aa_models,
        target_models=target_models,
        categories=categories,
        arena_weight=arena_weight,
        aa_weight=aa_weight,
    )

    console = Console()

    if fuzzy_notices:
        console.print("[yellow]Fuzzy matches used:[/yellow]")
        for notice in fuzzy_notices:
            console.print(f"[yellow]{notice}[/yellow]")
        console.print()

    def fmt_aa_raw(score: NormalizedScore | None) -> str:
        if not score:
            return "--"
        v = score.raw_score
        if v == int(v):
            return f"{v:.0f}"
        return f"{v:.3f}"

    prov_labels = {"both": "B", "arena_only": "A", "aa_only": "AA", "none": "?"}

    summary = Table(
        title=f"Overall (Arena {arena_w:.0f}% / AA {aa_w:.0f}%)",
        show_lines=True,
    )
    summary.add_column("Model", style="bold")
    summary.add_column("Arena Raw", justify="right")
    summary.add_column("AA Raw", justify="right")
    summary.add_column("Arena %ile", justify="right")
    summary.add_column("AA %ile", justify="right")
    summary.add_column("Composite", justify="right")

    for sc in scorecards:
        ov = sc.overall
        if not ov:
            summary.add_row(sc.model_name, "--", "--", "--", "--", "--")
            continue
        a_raw = f"{ov.arena_score.raw_score:.1f}" if ov.arena_score else "--"
        aa_raw = fmt_aa_raw(ov.aa_score)
        a_pct = f"{ov.arena_score.percentile:.1f}" if ov.arena_score else "--"
        aa_pct = f"{ov.aa_score.percentile:.1f}" if ov.aa_score else "--"
        prov = prov_labels.get(ov.provenance, "?")
        comp = f"{ov.percentile:.1f} [{prov}]"
        summary.add_row(sc.model_name, a_raw, aa_raw, a_pct, aa_pct, comp)

    console.print(summary)

    if len(scorecards) > 1:
        for cat in categories:
            if cat == "overall":
                continue
            has_data = any(cat in sc.categories for sc in scorecards)
            if not has_data:
                continue
            cat_table = Table(
                title=display_name(cat),
                show_lines=True,
            )
            cat_table.add_column("Model", style="bold")
            cat_table.add_column("Arena Raw", justify="right")
            cat_table.add_column("AA Raw", justify="right")
            cat_table.add_column("Arena %ile", justify="right")
            cat_table.add_column("AA %ile", justify="right")
            cat_table.add_column("Composite", justify="right")

            for sc in scorecards:
                cs = sc.categories.get(cat)
                if not cs:
                    cat_table.add_row(sc.model_name, "--", "--", "--", "--", "--")
                    continue
                a_raw = f"{cs.arena_score.raw_score:.1f}" if cs.arena_score else "--"
                aa_raw = fmt_aa_raw(cs.aa_score)
                a_pct = f"{cs.arena_score.percentile:.1f}" if cs.arena_score else "--"
                aa_pct = f"{cs.aa_score.percentile:.1f}" if cs.aa_score else "--"
                prov = prov_labels.get(cs.provenance, "?")
                comp = f"{cs.percentile:.1f} [{prov}]"
                cat_table.add_row(sc.model_name, a_raw, aa_raw, a_pct, aa_pct, comp)

            console.print(cat_table)
    else:
        for sc in scorecards:
            if not sc.categories:
                continue
            cat_table = Table(
                title=f"Category Scores: {sc.model_name}",
                show_lines=True,
            )
            cat_table.add_column("Category", style="bold")
            cat_table.add_column("Arena Raw", justify="right")
            cat_table.add_column("AA Raw", justify="right")
            cat_table.add_column("Arena %ile", justify="right")
            cat_table.add_column("AA %ile", justify="right")
            cat_table.add_column("Composite", justify="right")

            for cat in categories:
                cs = sc.categories.get(cat)
                if not cs:
                    continue
                a_raw = f"{cs.arena_score.raw_score:.1f}" if cs.arena_score else "--"
                aa_raw = fmt_aa_raw(cs.aa_score)
                a_pct = f"{cs.arena_score.percentile:.1f}" if cs.arena_score else "--"
                aa_pct = f"{cs.aa_score.percentile:.1f}" if cs.aa_score else "--"
                prov = prov_labels.get(cs.provenance, "?")
                comp = f"{cs.percentile:.1f} [{prov}]"
                cat_table.add_row(display_name(cat), a_raw, aa_raw, a_pct, aa_pct, comp)

            console.print(cat_table)


@main.command("check")
@click.option(
    "--models",
    "-m",
    default=None,
    help="Comma-separated model names to check.",
)
@click.option(
    "--catalog",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON model catalog file (e.g., model_catalog.json).",
)
@click.option(
    "--sources",
    "-s",
    default=None,
    help=f"Comma-separated source names. Available: {', '.join(get_available_sources())}",
)
@click.option(
    "--fuzzy",
    is_flag=True,
    default=False,
    help="Accept fuzzy model name matches instead of treating them as not-found.",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def check_models(
    models: str | None, catalog: str | None, sources: str | None, fuzzy: bool, verbose: bool
) -> None:
    """Check how model names resolve in each data source (no report generated)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    model_names = _get_model_names(models, catalog)

    source_names = (
        [s.strip() for s in sources.split(",") if s.strip()] if sources else get_available_sources()
    )

    for source_name in source_names:
        kwargs: dict[str, Any] = {}
        try:
            source = get_source(source_name, **kwargs)
        except ValueError as e:
            click.echo(f"Warning: {e}", err=True)
            continue

        click.echo(f"\n=== {source.name} ===")
        report = source.resolve_names(model_names)

        for mr in report.results:
            if mr.match_type == MatchType.EXACT:
                click.echo(f'  "{mr.user_name}" -> {mr.matched_name} (exact)')
            elif mr.match_type == MatchType.EQUIVALENT:
                click.echo(f'  "{mr.user_name}" -> {mr.matched_name} (equivalent)')
            elif mr.match_type == MatchType.FUZZY:
                if fuzzy and mr.matched_name:
                    click.echo(f'  "{mr.user_name}" -> {mr.matched_name} (fuzzy)')
                else:
                    candidates = [mr.matched_name] if mr.matched_name else []
                    for s in suggest_similar(mr.user_name, report.available_names, n=3):
                        if s not in candidates:
                            candidates.append(s)
                    candidates = candidates[:3]
                    click.echo(f'  "{mr.user_name}" -> not found')
                    if candidates:
                        click.echo(f"    Similar: {', '.join(candidates)}")
            else:
                suggestions = suggest_similar(mr.user_name, report.available_names, n=3)
                click.echo(f'  "{mr.user_name}" -> not found')
                if suggestions:
                    click.echo(f"    Similar: {', '.join(suggestions)}")
