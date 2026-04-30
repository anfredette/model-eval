"""Distribution chart generation for model evaluation reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

FAMILY_COLORS = [
    "#4285F4",  # blue
    "#EA4335",  # red
    "#34A853",  # green
    "#FF6D01",  # orange
    "#A142F4",  # purple
    "#24C1E0",  # cyan
    "#E8710A",  # dark orange
    "#F538A0",  # pink
]


def _assign_family_colors(families: list[str]) -> dict[str, str]:
    """Assign consistent colors to each unique family."""
    unique = list(dict.fromkeys(families))
    return {fam: FAMILY_COLORS[i % len(FAMILY_COLORS)] for i, fam in enumerate(unique)}


def generate_distribution_chart(
    all_scores: list[float],
    evaluated_models: list[dict[str, Any]],
    output_path: Path,
    source_name: str,
    median: float,
) -> Path:
    """Generate a histogram with staggered arrow markers for evaluated models.

    Args:
        all_scores: All scores in the population (for histogram).
        evaluated_models: List of dicts with keys: name, score, family, color (optional).
        output_path: Where to save the PNG.
        source_name: Name for the chart title (e.g. "Arena Rating").
        median: Population median for the dotted line.

    Returns:
        The output path.
    """
    fig, ax = plt.subplots(figsize=(14, 6))

    scores_arr = np.array(all_scores)
    n_bins = max(20, min(40, len(all_scores) // 10))
    ax.hist(
        scores_arr,
        bins=n_bins,
        color="#D0D0D0",
        edgecolor="#B0B0B0",
        alpha=0.8,
        label=f"All models ({len(all_scores)})",
    )

    ax.axvline(median, color="gray", linestyle=":", linewidth=1, alpha=0.7)
    hist_max = ax.get_ylim()[1]
    ax.text(
        median + (scores_arr.max() - scores_arr.min()) * 0.005,
        hist_max * 0.85,
        f"median: {median:.0f}",
        fontsize=8,
        color="gray",
        alpha=0.7,
    )

    if not evaluated_models:
        ax.set_xlabel(source_name)
        ax.set_ylabel("Number of Models")
        ax.set_title(f"{source_name} Distribution")
        ax.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path

    families = [m.get("family", "Unknown") for m in evaluated_models]
    family_colors = _assign_family_colors(families)
    for m in evaluated_models:
        if "color" not in m or m["color"] is None:
            m["color"] = family_colors[m.get("family", "Unknown")]

    sorted_models = sorted(evaluated_models, key=lambda m: m["score"])
    n = len(sorted_models)
    min_height = hist_max * 0.25
    max_height = hist_max * 0.95
    if n == 1:
        heights = [max_height]
    else:
        heights = [min_height + (max_height - min_height) * i / (n - 1) for i in range(n)]

    legend_families: dict[str, str] = {}
    for i, model in enumerate(sorted_models):
        color = model["color"]
        family = model.get("family", "Unknown")
        score = model["score"]
        name = model["name"]
        h = heights[i]

        ax.annotate(
            "",
            xy=(score, 0),
            xytext=(score, h),
            arrowprops={"arrowstyle": "->", "color": color, "lw": 1.8},
        )

        ax.text(
            score - (scores_arr.max() - scores_arr.min()) * 0.005,
            h + hist_max * 0.01,
            name,
            fontsize=9,
            color=color,
            ha="right",
            va="bottom",
            fontweight="bold",
        )

        if family not in legend_families:
            legend_families[family] = color

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, fc="#D0D0D0", ec="#B0B0B0", alpha=0.8),
    ]
    legend_labels = [f"All models ({len(all_scores)})"]
    for fam, col in legend_families.items():
        legend_handles.append(plt.Rectangle((0, 0), 1, 1, fc=col))
        legend_labels.append(fam)

    ax.legend(legend_handles, legend_labels, loc="upper left", fontsize=8)
    ax.set_xlabel(source_name)
    ax.set_ylabel("Number of Models")
    ax.set_title(f"{source_name} Distribution")
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
