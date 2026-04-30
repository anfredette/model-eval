from __future__ import annotations

import pandas as pd
import pytest

from model_eval.sources.artificial_analysis import AAModel


@pytest.fixture
def sample_arena_df() -> pd.DataFrame:
    models = [
        ("model-alpha", "OrgA", 1450.0, 10000),
        ("model-beta", "OrgB", 1400.0, 8000),
        ("model-gamma", "OrgA", 1380.0, 5000),
        ("model-delta", "OrgB", 1350.0, 3000),
        ("model-epsilon", "OrgA", 1300.0, 2000),
    ]
    categories = ["overall", "coding", "math", "creative_writing"]

    rows = []
    for name, org, base_rating, votes in models:
        for i, cat in enumerate(categories):
            offset = (i - 1) * 20
            rows.append(
                {
                    "model_name": name,
                    "organization": org,
                    "license": "Apache-2.0",
                    "rating": base_rating + offset,
                    "rating_lower": base_rating + offset - 5,
                    "rating_upper": base_rating + offset + 5,
                    "variance": 10.0,
                    "vote_count": votes,
                    "rank": 0,
                    "category": cat,
                }
            )

    # Version-variant model for fuzzy matching tests
    for i, cat in enumerate(categories):
        offset = (i - 1) * 20
        rows.append(
            {
                "model_name": "model-alpha-v2",
                "organization": "OrgA",
                "license": "Apache-2.0",
                "rating": 1420.0 + offset,
                "rating_lower": 1415.0 + offset,
                "rating_upper": 1425.0 + offset,
                "variance": 10.0,
                "vote_count": 6000,
                "rank": 0,
                "category": cat,
            }
        )

    df = pd.DataFrame(rows)
    for cat in categories:
        mask = df["category"] == cat
        df.loc[mask, "rank"] = (
            df.loc[mask, "rating"].rank(ascending=False, method="min").astype(int)
        )
    return df


@pytest.fixture
def sample_aa_models() -> list[AAModel]:
    return [
        AAModel(
            name="Alpha Thinking",
            slug="alpha-thinking",
            organization="OrgA",
            intelligence_index=35,
            speed_tps=130.0,
            ttft_s=1.0,
            input_price_per_1m=0.20,
            output_price_per_1m=0.80,
            context_window=512000,
            params_total_b=400,
            params_active_b=13,
            reasoning=True,
        ),
        AAModel(
            name="Beta Large",
            slug="beta-large",
            organization="OrgB",
            intelligence_index=30,
            speed_tps=55.0,
            ttft_s=2.9,
            input_price_per_1m=1.20,
            output_price_per_1m=4.80,
            context_window=256000,
            params_total_b=235,
            params_active_b=22,
            reasoning=True,
        ),
        AAModel(
            name="Beta Small",
            slug="beta-small",
            organization="OrgB",
            intelligence_index=20,
            speed_tps=90.0,
            ttft_s=2.5,
            input_price_per_1m=0.60,
            output_price_per_1m=2.40,
            context_window=33000,
            params_total_b=33,
            params_active_b=33,
            reasoning=False,
        ),
    ]
