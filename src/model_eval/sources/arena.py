from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from model_eval import arena_client
from model_eval.aa_client import cache_age_display, is_cache_stale
from model_eval.models import (
    ComparisonTable,
    DistributionStats,
    HeadToHead,
    ResolutionReport,
    SourceData,
)
from model_eval.resolver import MatchType, resolve_model_names, suggest_similar
from model_eval.sources import register_source
from model_eval.tiers import arena_gap_significance, tier_label

logger = logging.getLogger(__name__)

KEY_CATEGORIES = [
    "overall",
    "coding",
    "math",
    "creative_writing",
    "instruction_following",
    "hard_prompts",
    "if_expert",
    "multi_turn",
    "long_query",
    "software_engineering_it",
    "legal",
    "science",
    "industry_mathematical",
    "writing",
]

CATEGORY_SHORT = {
    "creative_writing": "creative",
    "instruction_following": "instruct",
    "hard_prompts": "hard",
    "if_expert": "expert",
    "software_engineering_it": "sw/it",
    "industry_mathematical": "ind_math",
}

GENERAL_CATEGORIES = [
    "overall",
    "coding",
    "math",
    "creative_writing",
    "instruction_following",
    "hard_prompts",
    "if_expert",
]

INDUSTRY_CATEGORIES = [
    "multi_turn",
    "long_query",
    "software_engineering_it",
    "legal",
    "science",
    "industry_mathematical",
    "writing",
]

METHODOLOGY = """\
[Arena](https://lmarena.ai/) (formerly LMSYS Chatbot Arena) ranks models using \
**head-to-head human preference votes**. Real users submit prompts to two \
anonymous models side-by-side, then choose which response they prefer. These \
pairwise outcomes are aggregated into Bradley-Terry ratings (similar to Elo in \
chess) -- higher is better, with scores typically ranging from ~900 to ~1550.

The `text_style_control` variant adjusts for verbosity bias, so models don't get \
rewarded simply for producing longer responses.

Ratings are broken down into **27 topic-based categories** (coding, math, \
creative writing, legal, etc.) based on conversation content, giving a detailed \
profile of where each model excels relative to the full field. Because these are \
human judgments rather than automated test suites, they reflect what real users \
find helpful -- but they also carry the biases of the voter population (skewed \
toward AI-savvy early adopters) and the preference-vs-correctness gap (a \
confident but wrong answer can still win votes)."""


def _short_cat(cat: str) -> str:
    return CATEGORY_SHORT.get(cat, cat)


def _fetch_arena() -> tuple[pd.DataFrame, str]:
    rows, fetched_at = arena_client.load_cache()
    if not rows:
        logger.info("No Arena cache found, fetching from HuggingFace...")
        count, _ = arena_client.sync()
        logger.info("Synced %d rows from Arena", count)
        rows, fetched_at = arena_client.load_cache()
        status = "fetched from HuggingFace"
    elif is_cache_stale(fetched_at):
        logger.info("Arena cache is stale, refreshing from HuggingFace...")
        try:
            count, _ = arena_client.sync()
            logger.info("Refreshed %d rows from Arena", count)
            rows, fetched_at = arena_client.load_cache()
            status = "refreshed from HuggingFace"
        except Exception:
            age = cache_age_display(fetched_at) if fetched_at else "unknown"
            logger.warning("Arena auto-refresh failed, using stale cache")
            status = f"using stale cache (synced {age})"
    else:
        assert fetched_at is not None
        status = f"using cache (synced {cache_age_display(fetched_at)})"
    return pd.DataFrame(rows), status


def _resolve_family_models(
    df: pd.DataFrame, family_names: list[str]
) -> tuple[list[str], list[str], dict[str, str]]:
    """Returns (matched_names, not_found, model_to_family_map)."""
    overall = df[df["category"] == "overall"]
    matched: list[str] = []
    not_found: list[str] = []
    model_family: dict[str, str] = {}
    for family in family_names:
        family_lower = family.lower()
        matches = overall[overall["model_name"].str.lower().str.contains(family_lower)]
        if not matches.empty:
            names = matches["model_name"].tolist()
            matched.extend(names)
            for name in names:
                model_family[name] = family
        else:
            not_found.append(family)
    return sorted(set(matched)), not_found, model_family


def _find_models(
    df: pd.DataFrame, model_names: list[str], *, fuzzy: bool = False
) -> tuple[list[str], list[str], dict[str, str], dict[str, list[str]]]:
    overall = df[df["category"] == "overall"]
    available = overall["model_name"].tolist()
    match_results = resolve_model_names(model_names, available)
    found: list[str] = []
    not_found: list[str] = []
    match_details: dict[str, str] = {}
    fuzzy_suggestions: dict[str, list[str]] = {}
    for mr in match_results:
        if mr.match_type in (MatchType.EXACT, MatchType.EQUIVALENT):
            assert mr.matched_name is not None
            found.append(mr.matched_name)
        elif mr.match_type == MatchType.FUZZY:
            assert mr.matched_name is not None
            if fuzzy:
                found.append(mr.matched_name)
                match_details[mr.user_name] = mr.matched_name
                logger.info(
                    'Model "%s" not found exactly in Arena. Used closest match "%s".',
                    mr.user_name,
                    mr.matched_name,
                )
            else:
                not_found.append(mr.user_name)
                candidates = [mr.matched_name]
                for s in suggest_similar(mr.user_name, available, n=3):
                    if s not in candidates:
                        candidates.append(s)
                fuzzy_suggestions[mr.user_name] = candidates[:3]
        else:
            not_found.append(mr.user_name)
    return found, not_found, match_details, fuzzy_suggestions


def _consolidated_ranking_table(
    df: pd.DataFrame, model_names: list[str], window: int = 5
) -> ComparisonTable:
    overall = (
        df[df["category"] == "overall"]
        .sort_values("rating", ascending=False)
        .reset_index(drop=True)
    )
    total = len(overall)
    name_set = set(model_names)

    positions: list[int] = []
    for name in model_names:
        idx = overall[overall["model_name"] == name].index
        if len(idx) > 0:
            positions.append(idx[0])

    if not positions:
        return ComparisonTable(
            title="Global Arena Rankings (no models found)",
            headers=[],
            rows=[],
        )

    ranges: list[tuple[int, int]] = []
    for pos in sorted(positions):
        start = max(0, pos - window)
        end = min(total - 1, pos + window)
        ranges.append((start, end))

    merged: list[tuple[int, int]] = [ranges[0]]
    for start, end in ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= 10:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    rows: list[list[str]] = []
    for seg_idx, (seg_start, seg_end) in enumerate(merged):
        if seg_idx > 0:
            prev_end = merged[seg_idx - 1][1]
            gap = seg_start - prev_end - 1
            rows.append(["", f"*[{gap} models not shown]*", "", ""])

        for i in range(seg_start, seg_end + 1):
            row = overall.iloc[i]
            r = i + 1
            name = row["model_name"]
            is_target = name in name_set
            fmt_rank = f"**{r}**" if is_target else str(r)
            fmt_name = f"**{name}**" if is_target else name
            fmt_rating = f"**{row['rating']:.1f}**" if is_target else f"{row['rating']:.1f}"
            fmt_votes = (
                f"**{int(row['vote_count']):,}**" if is_target else f"{int(row['vote_count']):,}"
            )
            rows.append([fmt_rank, fmt_name, fmt_rating, fmt_votes])

    title = f"Global Arena Rankings ({total} models total)"

    return ComparisonTable(
        title=title,
        headers=["Rank", "Model", "Rating", "Votes"],
        rows=rows,
        alignments=["right", "left", "right", "right"],
    )


def _subset_ranking(df: pd.DataFrame, model_names: list[str]) -> ComparisonTable:
    overall = df[df["category"] == "overall"]
    subset = overall[overall["model_name"].isin(model_names)].sort_values("rating", ascending=False)

    rows: list[list[str]] = []
    for rank, (_, row) in enumerate(subset.iterrows(), 1):
        rows.append(
            [
                str(rank),
                row["model_name"],
                f"{int(row['vote_count']):,}",
                f"{row['rating']:.1f}",
            ]
        )

    return ComparisonTable(
        title=f"Subset Rankings ({len(rows)} models)",
        headers=["Rank", "Model", "Votes", "Overall"],
        rows=rows,
        alignments=["right", "left", "right", "right"],
    )


def _category_table(
    df: pd.DataFrame, model_names: list[str], categories: list[str]
) -> ComparisonTable:
    subset = df[(df["model_name"].isin(model_names)) & (df["category"].isin(categories))]

    pivot = subset.pivot_table(
        index="model_name", columns="category", values="rating", aggfunc="first"
    )

    if "overall" in categories:
        pivot = pivot.sort_values("overall", ascending=False)
    else:
        pivot = pivot.sort_values(pivot.columns[0], ascending=False)

    headers = ["Model"] + [_short_cat(c) for c in categories if c in pivot.columns]
    rows: list[list[str]] = []
    for model_name in pivot.index:
        row_data: list[str] = [model_name]
        for cat in categories:
            if cat in pivot.columns:
                val = pivot.loc[model_name, cat]
                row_data.append(f"{val:.1f}" if pd.notna(val) else "—")
        rows.append(row_data)

    return ComparisonTable(
        title="Category Ratings",
        headers=headers,
        rows=rows,
        alignments=["left"] + ["right"] * (len(headers) - 1),
    )


def _head_to_head(
    df: pd.DataFrame, model_a: str, model_b: str, categories: list[str]
) -> HeadToHead:
    a_data = df[df["model_name"] == model_a].set_index("category")
    b_data = df[df["model_name"] == model_b].set_index("category")

    dims: list[str] = []
    a_scores: list[float] = []
    b_scores: list[float] = []
    deltas: list[float] = []

    for cat in categories:
        if cat in a_data.index and cat in b_data.index:
            a_val = float(a_data.loc[cat, "rating"])  # type: ignore[arg-type]
            b_val = float(b_data.loc[cat, "rating"])  # type: ignore[arg-type]
            dims.append(_short_cat(cat))
            a_scores.append(a_val)
            b_scores.append(b_val)
            deltas.append(round(a_val - b_val, 1))

    sorted_indices = sorted(range(len(deltas)), key=lambda i: deltas[i], reverse=True)
    dims = [dims[i] for i in sorted_indices]
    a_scores = [a_scores[i] for i in sorted_indices]
    b_scores = [b_scores[i] for i in sorted_indices]
    deltas = [deltas[i] for i in sorted_indices]

    a_wins = sum(1 for d in deltas if d > 0)
    b_wins = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)

    return HeadToHead(
        model_a=model_a,
        model_b=model_b,
        dimensions=dims,
        a_scores=a_scores,
        b_scores=b_scores,
        deltas=deltas,
        a_wins=a_wins,
        b_wins=b_wins,
        ties=ties,
    )


def _win_loss_table(h2hs: list[HeadToHead]) -> ComparisonTable:
    rows: list[list[str]] = []
    for h in sorted(h2hs, key=lambda h: h.deltas[0] if h.deltas else 0, reverse=True):
        overall_delta = next(
            (d for dim, d in zip(h.dimensions, h.deltas, strict=False) if dim == "overall"),
            0.0,
        )
        gap_str = f"+{overall_delta:.1f}" if overall_delta > 0 else f"{overall_delta:.1f}"
        rows.append(
            [
                h.model_b,
                str(h.a_wins),
                str(h.b_wins),
                gap_str,
            ]
        )

    return ComparisonTable(
        title="Win/Loss Summary",
        headers=["vs Model", f"{h2hs[0].model_a} Wins", "Opponent Wins", "Overall Gap"],
        rows=rows,
        alignments=["left", "center", "center", "center"],
    )


def _compute_findings(
    model_names: list[str],
    h2hs: list[HeadToHead],
    df: pd.DataFrame,
) -> tuple[list[str], DistributionStats | None]:
    findings: list[str] = []

    if not h2hs:
        return findings, None

    overall = (
        df[df["category"] == "overall"]
        .sort_values("rating", ascending=False)
        .reset_index(drop=True)
    )
    total = len(overall)

    dist_cache = arena_client.load_dist_cache()
    dist_stats: DistributionStats | None = None
    if dist_cache and "stats" in dist_cache:
        s = dist_cache["stats"]
        dist_stats = DistributionStats(
            count=s["count"],
            min=s["min"],
            max=s["max"],
            median=s["median"],
            mean=s["mean"],
            stdev=s["stdev"],
            p25=s["p25"],
            p75=s["p75"],
        )

    orgs: dict[str, list[str]] = {}
    for name in model_names:
        row = overall[overall["model_name"] == name]
        if not row.empty:
            org = row.iloc[0].get("organization", "unknown")
            orgs.setdefault(org, []).append(name)

    org_names = list(orgs.keys())
    if len(org_names) >= 2:
        primary_org, secondary_org = org_names[0], org_names[1]
        primary_models = orgs[primary_org]
        secondary_models = orgs[secondary_org]
    else:
        primary_org = org_names[0] if org_names else "Unknown"
        primary_models = model_names
        secondary_org = ""
        secondary_models = []

    rankings: dict[str, tuple[int, float, tuple[float, float]]] = {}
    for name in model_names:
        idx = overall[overall["model_name"] == name].index
        if len(idx) > 0:
            pos = idx[0]
            row = overall.iloc[pos]
            rating = float(row["rating"])
            ci = (float(row.get("rating_lower", rating)), float(row.get("rating_upper", rating)))
            rankings[name] = (pos + 1, rating, ci)

    if rankings:
        primary_ranked = [(n, rankings[n]) for n in primary_models if n in rankings]
        secondary_ranked = [(n, rankings[n]) for n in secondary_models if n in rankings]

        if primary_ranked and secondary_ranked:
            best_primary = min(primary_ranked, key=lambda x: x[1][0])
            best_secondary = min(secondary_ranked, key=lambda x: x[1][0])
            bp_rank, bp_rating, bp_ci = best_primary[1]
            bs_rank, bs_rating, bs_ci = best_secondary[1]
            bp_tier = tier_label(bp_rank)
            bs_tier = tier_label(bs_rank)

            gap_desc = arena_gap_significance(bp_rating, bp_ci, bs_rating, bs_ci)

            findings.append(
                f"**Overall positioning:** The top {primary_org} model is "
                f"`{best_primary[0]}` (rank {bp_rank} of {total}, rating {bp_rating:.1f}), "
                f"{bp_tier} tier. "
                f"The top {secondary_org} model is `{best_secondary[0]}` "
                f"(rank {bs_rank}, rating {bs_rating:.1f}), {bs_tier} tier — "
                f"{gap_desc}."
            )

            if len(secondary_ranked) > 1:
                closest = min(
                    secondary_ranked,
                    key=lambda x: abs(x[1][1] - bp_rating),
                )
                if closest[0] != best_secondary[0]:
                    cl_rank, cl_rating, cl_ci = closest[1]
                    cl_gap = arena_gap_significance(bp_rating, bp_ci, cl_rating, cl_ci)
                    findings[-1] += (
                        f" The closest {secondary_org} model by rating is "
                        f"`{closest[0]}` (rank {cl_rank}, rating {cl_rating:.1f}) — "
                        f"{cl_gap}."
                    )

    total_cats = len(h2hs[0].dimensions)
    sweeps = sum(1 for h in h2hs if h.a_wins == total_cats)
    wins = sum(1 for h in h2hs if h.a_wins > h.b_wins)
    losses = sum(1 for h in h2hs if h.b_wins > h.a_wins)
    ties = len(h2hs) - wins - losses

    parts = []
    if sweeps == len(h2hs):
        parts.append(f"sweeps all {total_cats} categories in every matchup ({len(h2hs)} matchups)")
    else:
        if sweeps:
            parts.append(f"sweeps all {total_cats} categories in {sweeps} of {len(h2hs)} matchups")
        if wins - sweeps > 0:
            parts.append(f"wins a majority in {wins - sweeps} more")
        if losses:
            parts.append(f"loses the majority in {losses}")
        if ties:
            parts.append(f"ties {ties}")
    primary_label = f"`{h2hs[0].model_a}`"
    findings.append(f"**Head-to-head summary:** {primary_label} " + ", ".join(parts) + ".")

    all_dims: dict[str, list[float]] = {}
    for h in h2hs:
        for dim, delta in zip(h.dimensions, h.deltas, strict=True):
            all_dims.setdefault(dim, []).append(delta)

    strengths = sorted(
        [
            (dim, sum(ds) / len(ds), max(ds), min(ds))
            for dim, ds in all_dims.items()
            if all(d > 0 for d in ds) and dim != "overall"
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    weaknesses = sorted(
        [
            (dim, sum(ds) / len(ds), max(ds), min(ds))
            for dim, ds in all_dims.items()
            if all(d < 0 for d in ds) and dim != "overall"
        ],
        key=lambda x: x[1],
    )

    if strengths:
        primary_label_s = f"{primary_org}'s" if primary_org else "Primary"
        lines = [f"**{primary_label_s} strengths** (wins in every matchup):"]
        for i, (dim, avg, peak, _) in enumerate(strengths):
            rep = next(
                (
                    h
                    for h in h2hs
                    if dim in h.dimensions and h.deltas[h.dimensions.index(dim)] == peak
                ),
                h2hs[0],
            )
            annotation = " -- the largest advantage" if i == 0 else ""
            lines.append(
                f"   - **{dim}** (+{avg:.1f} avg, up to +{peak:.1f} vs `{rep.model_b}`){annotation}"
            )
        findings.append("\n".join(lines))

    if weaknesses:
        primary_label_s = f"{primary_org}'s" if primary_org else "Primary"
        if len(weaknesses) == 1:
            dim, avg, _, trough = weaknesses[0]
            rep = next(
                (
                    h
                    for h in h2hs
                    if dim in h.dimensions and h.deltas[h.dimensions.index(dim)] == trough
                ),
                h2hs[0],
            )
            findings.append(
                f"**{primary_label_s} weakness:** {dim} is the consistent weak spot, "
                f"losing in every matchup (avg {avg:.1f}, worst {trough:.1f} vs `{rep.model_b}`)."
            )
        else:
            lines = [f"**{primary_label_s} weaknesses** (loses in every matchup):"]
            for dim, avg, _, trough in weaknesses:
                rep = next(
                    (
                        h
                        for h in h2hs
                        if dim in h.dimensions and h.deltas[h.dimensions.index(dim)] == trough
                    ),
                    h2hs[0],
                )
                lines.append(
                    f"   - **{dim}** ({avg:.1f} avg, worst {trough:.1f} vs `{rep.model_b}`)"
                )
            findings.append("\n".join(lines))

    stem_cats = {"math", "coding", "ind_math", "sw/it", "science"}
    humanities_cats = {"creative", "legal", "writing", "instruct", "expert"}
    stem_deltas = [
        avg for dim, ds in all_dims.items() if dim in stem_cats for avg in [sum(ds) / len(ds)]
    ]
    humanities_deltas = [
        avg for dim, ds in all_dims.items() if dim in humanities_cats for avg in [sum(ds) / len(ds)]
    ]

    if stem_deltas and humanities_deltas:
        stem_avg = sum(stem_deltas) / len(stem_deltas)
        hum_avg = sum(humanities_deltas) / len(humanities_deltas)
        if abs(stem_avg - hum_avg) > 5:
            p_label = primary_org if primary_org else "Primary model"
            s_label = secondary_org if secondary_org else "opponent"
            if hum_avg > stem_avg:
                findings.append(
                    f"**Profile difference:** {p_label} has a "
                    f"humanities-leaning profile (avg delta +{hum_avg:.1f} in "
                    f"creative/legal/writing/instruct/expert vs {stem_avg:+.1f} in "
                    f"STEM categories). {s_label} models generally skew "
                    f"toward STEM."
                )
            else:
                findings.append(
                    f"**Profile difference:** {p_label} has a "
                    f"STEM-leaning profile (avg delta +{stem_avg:.1f} in "
                    f"STEM categories vs {hum_avg:+.1f} in humanities). "
                    f"{s_label} models lean toward humanities/creative."
                )

    dominates_count = 0
    dominated_by_count = 0
    for h in h2hs:
        if h.a_wins >= total_cats - 2:
            dominates_count += 1
        elif h.b_wins >= total_cats - 2:
            dominated_by_count += 1

    if dominates_count or dominated_by_count:
        primary_label = f"`{h2hs[0].model_a}`"
        parts = []
        if dominates_count:
            parts.append(
                f"dominates {dominates_count} opponent{'s' if dominates_count > 1 else ''} "
                f"(winning nearly all categories)"
            )
        if dominated_by_count:
            parts.append(
                f"is outclassed by {dominated_by_count} "
                f"opponent{'s' if dominated_by_count > 1 else ''}"
            )
        findings.append(f"**Cross-tier pattern:** {primary_label} " + "; ".join(parts) + ".")

    return findings, dist_stats


def _select_h2h_pairs(df: pd.DataFrame, model_names: list[str]) -> list[tuple[str, str]]:
    overall = df[(df["category"] == "overall") & (df["model_name"].isin(model_names))].sort_values(
        "rating", ascending=False
    )

    orgs: dict[str, list[str]] = {}
    for _, row in overall.iterrows():
        name = row["model_name"]
        org = row.get("organization", "unknown")
        orgs.setdefault(org, []).append(name)

    org_groups = list(orgs.values())
    if len(org_groups) < 2:
        models_sorted = overall["model_name"].tolist()
        pairs: list[tuple[str, str]] = []
        for i in range(len(models_sorted)):
            for j in range(i + 1, len(models_sorted)):
                pairs.append((models_sorted[i], models_sorted[j]))
        return pairs[:8]

    pairs = []
    for i, group_a in enumerate(org_groups):
        for group_b in org_groups[i + 1 :]:
            for a in group_a[:3]:
                for b in group_b[:3]:
                    pairs.append((a, b))

    return pairs[:8]


class ArenaSource:
    """Arena data source."""

    @property
    def name(self) -> str:
        return "Arena"

    @property
    def description(self) -> str:
        return "Human Preference Ratings"

    def fetch_and_compare(
        self,
        model_names: list[str],
        *,
        families: bool = False,
        fuzzy: bool = False,
        **kwargs: Any,
    ) -> SourceData:
        df, cache_status = _fetch_arena()

        family_not_found: list[str] = []
        family_map: dict[str, str] = {}
        if families:
            model_names, family_not_found, family_map = _resolve_family_models(df, model_names)

        found, not_found, match_details, fuzzy_suggestions = _find_models(
            df, model_names, fuzzy=fuzzy
        )
        not_found.extend(family_not_found)

        suggestions: dict[str, list[str]] = {}
        suggestions.update(fuzzy_suggestions)
        if not_found:
            overall = df[df["category"] == "overall"]
            available = overall["model_name"].tolist()
            for name in not_found:
                if name not in suggestions:
                    matches = suggest_similar(name, available)
                    if matches:
                        suggestions[name] = matches

        if not found:
            return SourceData(
                source_name=self.name,
                source_description=self.description,
                methodology=METHODOLOGY,
                models_found=[],
                models_not_found=not_found,
                suggestions=suggestions,
                findings=["No matching models found in Arena leaderboard."],
                cache_status=cache_status,
            )

        global_rankings = [_consolidated_ranking_table(df, found)]
        subset = _subset_ranking(df, found)

        general = _category_table(df, found, GENERAL_CATEGORIES)
        general.title = "Part 1: General capabilities"
        industry = _category_table(df, found, INDUSTRY_CATEGORIES)
        industry.title = "Part 2: Conversational and industry categories"

        h2h_pairs = _select_h2h_pairs(df, found)
        h2hs = [_head_to_head(df, a, b, KEY_CATEGORIES) for a, b in h2h_pairs]

        win_loss = _win_loss_table(h2hs) if h2hs else None

        findings, dist_stats = _compute_findings(found, h2hs, df)

        comparison_tables = [subset, general, industry]
        if win_loss:
            comparison_tables.append(win_loss)

        overall = df[df["category"] == "overall"]
        chart_models = []
        for name in found:
            row = overall[overall["model_name"] == name]
            if not row.empty:
                r = row.iloc[0]
                family = family_map.get(name, r.get("organization", "Unknown"))
                chart_models.append(
                    {
                        "name": name,
                        "score": float(r["rating"]),
                        "family": family,
                    }
                )

        return SourceData(
            source_name=self.name,
            source_description=self.description,
            methodology=METHODOLOGY,
            global_rankings=global_rankings,
            comparison_tables=comparison_tables,
            head_to_heads=h2hs,
            findings=findings,
            models_found=found,
            models_not_found=not_found,
            suggestions=suggestions,
            match_details=match_details,
            cache_status=cache_status,
            distribution_stats=dist_stats,
            chart_models=chart_models,
        )


    def resolve_names(self, model_names: list[str]) -> ResolutionReport:
        df, _ = _fetch_arena()
        overall = df[df["category"] == "overall"]
        available = overall["model_name"].tolist()
        results = resolve_model_names(model_names, available)
        return ResolutionReport(results=results, available_names=available)


register_source("arena", ArenaSource)
