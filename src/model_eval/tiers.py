"""Standardized tier classification and gap significance logic."""

from __future__ import annotations

TIER_BOUNDARIES: list[tuple[int, str]] = [
    (10, "Frontier"),
    (25, "Near-frontier"),
    (75, "Upper-mid"),
    (150, "Mid-tier"),
]
TIER_DEFAULT = "Long-tail"


def tier_label(rank: int) -> str:
    """Return tier name for an absolute rank (1-based)."""
    for cutoff, label in TIER_BOUNDARIES:
        if rank <= cutoff:
            return label
    return TIER_DEFAULT


def arena_gap_significance(
    rating_a: float,
    ci_a: tuple[float, float],
    rating_b: float,
    ci_b: tuple[float, float],
) -> str:
    """Describe the gap between two Arena models using confidence interval overlap.

    ci_a and ci_b are (lower, upper) bounds.
    """
    a_lo, a_hi = ci_a
    b_lo, b_hi = ci_b

    upper_lo = min(a_hi, b_hi)
    lower_hi = max(a_lo, b_lo)

    if lower_hi <= upper_lo:
        return "statistically indistinguishable"

    closest_bound_gap = lower_hi - upper_lo
    if closest_bound_gap < 20:
        return "small but statistically significant difference"
    return "clear separation"


def aa_gap_significance(score_a: float, score_b: float, population_stdev: float) -> str:
    """Describe the gap between two AA models using population standard deviation."""
    if population_stdev <= 0:
        return "not clearly distinguishable"

    gap_in_stdev = abs(score_a - score_b) / population_stdev

    if gap_in_stdev < 0.5:
        return "not clearly distinguishable"
    if gap_in_stdev <= 1.0:
        return "moderate difference"
    return "clear separation"
