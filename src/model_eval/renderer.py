from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from model_eval.models import ComparisonResult

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _generate_introduction(result: ComparisonResult) -> str:
    names = " and ".join(result.model_names)
    n_sources = len(result.sources)

    if n_sources == 1:
        intro = f"This document compares {names} using data from {result.sources[0].source_name}."
    else:
        intro = f"This document compares {names} using {n_sources} independent evaluation sources."

    if n_sources >= 2:
        found_sets = [frozenset(s.models_found) for s in result.sources if s.models_found]
        if len(found_sets) >= 2 and len(set(found_sets)) > 1:
            intro += (
                " Each source may evaluate different model variants, so the "
                "sections should be read as complementary views rather than "
                "direct cross-references."
            )

    return intro


def render_comparison(result: ComparisonResult, output_path: Path) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("comparison.md.j2")

    content = template.render(
        model_names=result.model_names,
        sources=result.sources,
        overall_conclusions=result.overall_conclusions,
        introduction=_generate_introduction(result),
        date=date.today().isoformat(),
    )

    content = _clean_blank_lines(content)

    output_path.write_text(content)
    return content


def _clean_blank_lines(text: str) -> str:
    lines = text.split("\n")
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    while cleaned and cleaned[-1].strip() == "":
        cleaned.pop()
    cleaned.append("")

    return "\n".join(cleaned)
