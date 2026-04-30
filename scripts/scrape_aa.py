#!/usr/bin/env python3
# DEPRECATED: Use `model-eval sync-aa` instead.
# This script scrapes AA's website directly. The sync-aa command
# uses the official AA API, which is the supported access method.
"""Scrape Artificial Analysis model data from individual model pages.

DEPRECATED: Use `model-eval sync-aa` instead.

Extracts data from JSON-LD structured data (FAQPage schema) embedded in each
model page's HTML. No JavaScript rendering needed.

Usage:
    uv run python scripts/scrape_aa.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "artificial_analysis.json"
SITEMAP_URL = "https://artificialanalysis.ai/sitemap.xml"
BASE_URL = "https://artificialanalysis.ai"
HEADERS = {
    "User-Agent": "model-eval-scraper/1.0 (research tool)",
    "Accept": "text/html",
}
DELAY_BETWEEN_REQUESTS = 1.0  # seconds


def get_model_slugs_from_sitemap(client: httpx.Client) -> list[str]:
    resp = client.get(SITEMAP_URL)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [loc.text for loc in root.findall(".//s:loc", ns) if loc.text]

    slugs = []
    seen = set()
    for url in urls:
        m = re.match(r"https://artificialanalysis\.ai/models/([^/]+)$", url)
        if m:
            slug = m.group(1)
            if slug not in seen:
                seen.add(slug)
                slugs.append(slug)
    return slugs


def extract_json_ld(html: str) -> list[dict]:
    pattern = r'<script type="application/ld\+json">([^<]+)</script>'
    blocks = []
    for match in re.finditer(pattern, html):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return blocks


def extract_faq_data(blocks: list[dict]) -> dict:
    for block in blocks:
        if block.get("@type") == "FAQPage":
            return block
    return {}


def parse_number(text: str, prefix: str = "", suffix: str = "") -> float | None:
    pattern = re.escape(prefix) + r"([\d,]+\.?\d*)" + re.escape(suffix)
    m = re.search(pattern, text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def parse_faq(faq: dict, slug: str) -> dict | None:
    if not faq.get("mainEntity"):
        return None

    result = {
        "name": None,
        "slug": slug,
        "organization": None,
        "intelligence_index": None,
        "speed_tps": None,
        "ttft_s": None,
        "input_price_per_1m": None,
        "output_price_per_1m": None,
        "context_window": None,
        "params_total_b": None,
        "params_active_b": None,
        "reasoning": False,
        "url": f"{BASE_URL}/models/{slug}",
        "accessed_date": time.strftime("%Y-%m-%d"),
    }

    for item in faq["mainEntity"]:
        q = item.get("name", "")
        a = item.get("acceptedAnswer", {}).get("text", "")

        if "who created" in q.lower():
            m = re.search(r"was created by (.+)\.", a)
            if m:
                result["organization"] = m.group(1).strip()
            model_name = re.match(r"Who created (.+)\?", q)
            if model_name:
                result["name"] = model_name.group(1).strip()

        elif "how intelligent" in q.lower():
            score = parse_number(a, "scores ")
            if score is not None:
                result["intelligence_index"] = int(round(score))
            if result["name"] is None:
                model_name = re.match(r"How intelligent is (.+)\?", q)
                if model_name:
                    result["name"] = model_name.group(1).strip()

        elif "how fast" in q.lower():
            speed = parse_number(a, "at ")
            if speed is not None:
                result["speed_tps"] = round(speed, 1)

        elif "latency" in q.lower():
            ttft = parse_number(a, "of ")
            if ttft is not None:
                result["ttft_s"] = round(ttft, 2)

        elif "how much does" in q.lower() and "cost" in q.lower():
            inp = parse_number(a, "$")
            if inp is not None:
                result["input_price_per_1m"] = inp
            out_m = re.search(r"and \$([\d,]+\.?\d*) per 1M output", a)
            if out_m:
                result["output_price_per_1m"] = float(out_m.group(1).replace(",", ""))

        elif "reasoning model" in q.lower():
            result["reasoning"] = a.lower().startswith("yes")

        elif "how many parameters" in q.lower():
            b_match = re.search(r"([\d,]+\.?\d*)\s*(?:billion|B)\b", a)
            if b_match:
                result["params_total_b"] = float(b_match.group(1).replace(",", ""))
            active_match = re.search(
                r"([\d,]+\.?\d*)\s*(?:billion|B)\s+active", a, re.IGNORECASE
            )
            if active_match:
                result["params_active_b"] = float(
                    active_match.group(1).replace(",", "")
                )

        elif "context window" in q.lower() or "context length" in q.lower():
            tokens = parse_number(a, "")
            if tokens is not None and tokens > 1000:
                result["context_window"] = int(tokens)

    return result


def extract_context_from_chart(html: str, slug: str) -> int | None:
    pattern = r'"context_window_tokens\\":\s*(\d+)'
    m = re.search(pattern, html)
    if m:
        return int(m.group(1))
    return None


def scrape_model(client: httpx.Client, slug: str) -> dict | None:
    url = f"{BASE_URL}/models/{slug}"
    try:
        resp = client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            print(f"  SKIP {slug}: HTTP {resp.status_code}", file=sys.stderr)
            return None
    except httpx.HTTPError as e:
        print(f"  ERROR {slug}: {e}", file=sys.stderr)
        return None

    html = resp.text
    blocks = extract_json_ld(html)
    faq = extract_faq_data(blocks)
    model = parse_faq(faq, slug)

    if model is None:
        print(f"  SKIP {slug}: no FAQ data", file=sys.stderr)
        return None

    if model["context_window"] is None:
        ctx = extract_context_from_chart(html, slug)
        if ctx:
            model["context_window"] = ctx

    return model


def main():
    print("Fetching sitemap...", file=sys.stderr)
    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        slugs = get_model_slugs_from_sitemap(client)
        print(f"Found {len(slugs)} model slugs", file=sys.stderr)

        models = []
        for i, slug in enumerate(slugs):
            print(
                f"  [{i+1}/{len(slugs)}] Scraping {slug}...",
                file=sys.stderr,
                end="",
            )
            model = scrape_model(client, slug)
            if model and model.get("name"):
                models.append(model)
                intel = model.get("intelligence_index", "?")
                print(f" OK (intelligence={intel})", file=sys.stderr)
            else:
                print(" SKIP (no data)", file=sys.stderr)

            if i < len(slugs) - 1:
                time.sleep(DELAY_BETWEEN_REQUESTS)

        models.sort(key=lambda m: m.get("intelligence_index") or 0, reverse=True)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(models, f, indent=2)

        print(
            f"\nDone! Wrote {len(models)} models to {OUTPUT_PATH}", file=sys.stderr
        )


if __name__ == "__main__":
    main()
