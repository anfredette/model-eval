"""Arena leaderboard cache management."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from datasets import load_dataset

from model_eval.aa_client import get_cache_dir

logger = logging.getLogger(__name__)


def get_cache_path() -> Path:
    return get_cache_dir() / "arena_models.json"


def fetch_from_hf() -> list[dict]:
    """Fetch the Arena leaderboard dataset from HuggingFace."""
    ds = load_dataset("lmarena-ai/leaderboard-dataset", "text_style_control", split="latest")
    df = pd.DataFrame(ds)
    return df.to_dict(orient="records")  # type: ignore[return-value]


def save_cache(rows: list[dict]) -> Path:
    """Write rows to cache file using atomic write."""
    cache_path = get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }

    fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(envelope, f)
        os.replace(tmp_path, cache_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return cache_path


def load_cache() -> tuple[list[dict], str | None]:
    """Load rows from cache. Returns (row_dicts, fetched_at) or ([], None) if no cache."""
    cache_path = get_cache_path()
    if not cache_path.exists():
        return [], None
    try:
        with open(cache_path) as f:
            envelope = json.load(f)
        return envelope.get("rows", []), envelope.get("fetched_at")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Corrupt cache file %s: %s", cache_path, e)
        return [], None


def get_dist_cache_path() -> Path:
    return get_cache_dir() / "arena_dist.json"


def compute_distribution(rows: list[dict]) -> dict:
    """Compute distribution stats from overall-category ratings."""
    import statistics

    overall = [r["rating"] for r in rows if r.get("category") == "overall"]
    if not overall:
        raise ValueError("No overall-category rows found in Arena data")

    overall_sorted = sorted(overall)
    n = len(overall_sorted)
    p25_idx = int(n * 0.25)
    p75_idx = int(n * 0.75)

    return {
        "stats": {
            "count": n,
            "min": min(overall),
            "max": max(overall),
            "median": statistics.median(overall),
            "mean": statistics.mean(overall),
            "stdev": statistics.stdev(overall) if n > 1 else 0.0,
            "p25": overall_sorted[p25_idx],
            "p75": overall_sorted[p75_idx],
        },
        "scores": overall_sorted,
    }


def save_dist_cache(dist: dict) -> Path:
    """Write distribution stats to cache file."""
    cache_path = get_dist_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(dist, f)
        os.replace(tmp_path, cache_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return cache_path


def load_dist_cache() -> dict | None:
    """Load cached distribution stats. Computes from model cache if missing."""
    cache_path = get_dist_cache_path()
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                return json.load(f)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Corrupt dist cache file %s: %s", cache_path, e)

    rows, _ = load_cache()
    if not rows:
        return None
    try:
        dist = compute_distribution(rows)
        save_dist_cache(dist)
        return dist
    except ValueError:
        return None


def sync() -> tuple[int, Path]:
    """Fetch from HuggingFace and save to cache. Returns (row_count, cache_path)."""
    logger.info("Fetching Arena leaderboard from HuggingFace...")
    rows = fetch_from_hf()
    logger.info("Received %d rows", len(rows))
    cache_path = save_cache(rows)

    dist = compute_distribution(rows)
    dist_path = save_dist_cache(dist)
    logger.info(
        "Distribution stats cached to %s (%d overall models)", dist_path, dist["stats"]["count"]
    )

    return len(rows), cache_path
