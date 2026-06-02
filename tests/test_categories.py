from __future__ import annotations

from model_eval.categories import (
    ALL_CATEGORIES,
    CATEGORY_MAP,
    DEFAULT_CATEGORIES,
    DISPLAY_NAMES,
    display_name,
)


class TestCategoryMap:
    def test_overall_maps_to_both_sources(self):
        arena, aa = CATEGORY_MAP["overall"]
        assert arena == "overall"
        assert aa == "intelligence_index"

    def test_coding_maps_to_both_sources(self):
        arena, aa = CATEGORY_MAP["coding"]
        assert arena == "coding"
        assert aa == "coding_index"

    def test_math_maps_to_both_sources(self):
        arena, aa = CATEGORY_MAP["math"]
        assert arena == "math"
        assert aa == "math_index"

    def test_arena_only_categories_have_no_aa_field(self):
        arena_only = [k for k, (_, aa) in CATEGORY_MAP.items() if aa is None]
        assert len(arena_only) > 0
        for cat in arena_only:
            _, aa = CATEGORY_MAP[cat]
            assert aa is None

    def test_all_categories_covers_category_map(self):
        assert set(ALL_CATEGORIES) == set(CATEGORY_MAP.keys())

    def test_default_categories_subset_of_all(self):
        assert set(DEFAULT_CATEGORIES).issubset(set(ALL_CATEGORIES))

    def test_default_includes_key_categories(self):
        expected = {"overall", "coding", "math", "creative_writing", "instruction_following"}
        assert expected.issubset(set(DEFAULT_CATEGORIES))

    def test_all_categories_has_34_entries(self):
        assert len(ALL_CATEGORIES) == 34


class TestDisplayName:
    def test_known_category(self):
        assert display_name("overall") == "Overall"
        assert display_name("industry_software_and_it_services") == "Software & IT"

    def test_unknown_category_returns_key(self):
        assert display_name("unknown_cat") == "unknown_cat"

    def test_all_categories_have_display_names(self):
        for cat in ALL_CATEGORIES:
            assert cat in DISPLAY_NAMES
