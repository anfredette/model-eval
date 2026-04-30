"""Artificial Analysis API client and local cache management."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://artificialanalysis.ai/api/v2/data/llms/models"

REASONING_PATTERNS = re.compile(
    r"(?i)\b(reasoning|thinking|think)\b|"
    r"\((?:high|medium|low|xhigh)\)"
)


_PROJECT_ROOT = Path(__file__).parent.parent.parent


def get_cache_dir() -> Path:
    return _PROJECT_ROOT / ".model_cache"


def get_cache_path() -> Path:
    return get_cache_dir() / "aa_models.json"


def fetch_from_api(api_key: str) -> list[dict[str, Any]]:
    """Fetch all models from the AA API. Returns raw model dicts from response['data']."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(API_BASE, headers={"x-api-key": api_key})
        if resp.status_code == 401:
            raise RuntimeError("AA API authentication failed (401). Check your API key.")
        if resp.status_code == 429:
            raise RuntimeError("AA API rate limit exceeded (429). Try again later.")
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, dict) and "data" in data:
        result: list[dict[str, Any]] = data["data"]
        return result
    if isinstance(data, list):
        return data  # type: ignore[return-value]
    raise RuntimeError(f"Unexpected API response structure: {type(data)}")


def _infer_reasoning(name: str) -> bool:
    return bool(REASONING_PATTERNS.search(name))


def _safe_float(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(val: object) -> int | None:
    if val is None:
        return None
    try:
        f = float(str(val))
        return int(f)
    except (TypeError, ValueError):
        return None


def _map_api_model(api_obj: dict) -> dict:
    """Map a single API model object to an AAModel-compatible dict."""
    evals = api_obj.get("evaluations") or {}
    pricing = api_obj.get("pricing") or {}
    creator = api_obj.get("model_creator") or {}
    slug = api_obj.get("slug", "")
    name = api_obj.get("name", "")

    return {
        "name": name,
        "slug": slug,
        "organization": creator.get("name", "Unknown"),
        "intelligence_index": _safe_int(evals.get("artificial_analysis_intelligence_index")),
        "coding_index": _safe_int(evals.get("artificial_analysis_coding_index")),
        "math_index": _safe_int(evals.get("artificial_analysis_math_index")),
        "speed_tps": _safe_float(api_obj.get("median_output_tokens_per_second")),
        "ttft_s": _safe_float(api_obj.get("median_time_to_first_token_seconds")),
        "input_price_per_1m": _safe_float(pricing.get("price_1m_input_tokens")),
        "output_price_per_1m": _safe_float(pricing.get("price_1m_output_tokens")),
        "blended_price_api": _safe_float(pricing.get("price_1m_blended_3_to_1")),
        "context_window": _safe_int(api_obj.get("context_window")),
        "params_total_b": _safe_float(api_obj.get("params_total_b")),
        "params_active_b": _safe_float(api_obj.get("params_active_b")),
        "reasoning": api_obj.get("reasoning") if "reasoning" in api_obj else _infer_reasoning(name),
        "url": f"https://artificialanalysis.ai/models/{slug}" if slug else None,
        "accessed_date": datetime.now(UTC).strftime("%Y-%m-%d"),
    }


def save_cache(models: list[dict]) -> Path:
    """Write models to cache file using atomic write."""
    cache_path = get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "model_count": len(models),
        "models": models,
    }

    fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(envelope, f, indent=2)
        os.replace(tmp_path, cache_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return cache_path


def load_cache() -> tuple[list[dict], str | None]:
    """Load models from cache. Returns (model_dicts, fetched_at) or ([], None) if no cache."""
    cache_path = get_cache_path()
    if not cache_path.exists():
        return [], None
    try:
        with open(cache_path) as f:
            envelope = json.load(f)
        return envelope.get("models", []), envelope.get("fetched_at")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Corrupt cache file %s: %s", cache_path, e)
        return [], None


def cache_age_display(fetched_at: str) -> str:
    """Human-readable cache age like '2 hours ago' or '3 days ago'."""
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return "unknown age"

    now = datetime.now(UTC)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)

    delta = now - fetched
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = total_seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def is_cache_stale(fetched_at: str | None, max_age_hours: int = 24) -> bool:
    """Return True if fetched_at is None or older than max_age_hours."""
    if fetched_at is None:
        return True
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    age = datetime.now(UTC) - fetched
    return age.total_seconds() > max_age_hours * 3600


def get_dist_cache_path() -> Path:
    return get_cache_dir() / "aa_dist.json"


def compute_distribution(models: list[dict]) -> dict:
    """Compute distribution stats from intelligence_index values."""
    import statistics

    scores = [m["intelligence_index"] for m in models if m.get("intelligence_index") is not None]
    if not scores:
        raise ValueError("No models with intelligence_index found in AA data")

    scores_sorted = sorted(scores)
    n = len(scores_sorted)
    p25_idx = int(n * 0.25)
    p75_idx = int(n * 0.75)

    return {
        "stats": {
            "count": n,
            "min": min(scores),
            "max": max(scores),
            "median": statistics.median(scores),
            "mean": statistics.mean(scores),
            "stdev": statistics.stdev(scores) if n > 1 else 0.0,
            "p25": scores_sorted[p25_idx],
            "p75": scores_sorted[p75_idx],
        },
        "scores": scores_sorted,
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

    models, _ = load_cache()
    if not models:
        return None
    try:
        dist = compute_distribution(models)
        save_dist_cache(dist)
        return dist
    except ValueError:
        return None


def sync(api_key: str) -> tuple[int, Path]:
    """Fetch from API, map models, save to cache. Returns (model_count, cache_path)."""
    logger.info("Fetching models from AA API...")
    raw_models = fetch_from_api(api_key)
    logger.info("Received %d models from API", len(raw_models))

    mapped = [_map_api_model(m) for m in raw_models]
    with_index = [m for m in mapped if m.get("intelligence_index") is not None]
    logger.info(
        "%d models have intelligence_index (filtered from %d total)",
        len(with_index),
        len(mapped),
    )

    cache_path = save_cache(mapped)

    dist = compute_distribution(mapped)
    dist_path = save_dist_cache(dist)
    logger.info("Distribution stats cached to %s (%d models)", dist_path, dist["stats"]["count"])

    return len(mapped), cache_path
