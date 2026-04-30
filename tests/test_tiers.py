import pytest

from model_eval.tiers import aa_gap_significance, arena_gap_significance, tier_label


@pytest.mark.unit
class TestTierLabel:
    def test_frontier(self) -> None:
        assert tier_label(1) == "Frontier"
        assert tier_label(10) == "Frontier"

    def test_near_frontier(self) -> None:
        assert tier_label(11) == "Near-frontier"
        assert tier_label(25) == "Near-frontier"

    def test_upper_mid(self) -> None:
        assert tier_label(26) == "Upper-mid"
        assert tier_label(75) == "Upper-mid"

    def test_mid_tier(self) -> None:
        assert tier_label(76) == "Mid-tier"
        assert tier_label(150) == "Mid-tier"

    def test_long_tail(self) -> None:
        assert tier_label(151) == "Long-tail"
        assert tier_label(500) == "Long-tail"


@pytest.mark.unit
class TestArenaGapSignificance:
    def test_overlapping_cis(self) -> None:
        result = arena_gap_significance(1490.0, (1480.0, 1500.0), 1485.0, (1475.0, 1495.0))
        assert result == "statistically indistinguishable"

    def test_non_overlapping_close(self) -> None:
        result = arena_gap_significance(1490.0, (1485.0, 1495.0), 1470.0, (1465.0, 1475.0))
        assert result == "small but statistically significant difference"

    def test_non_overlapping_wide(self) -> None:
        result = arena_gap_significance(1490.0, (1485.0, 1495.0), 1440.0, (1435.0, 1445.0))
        assert result == "clear separation"

    def test_identical_ratings(self) -> None:
        result = arena_gap_significance(1490.0, (1485.0, 1495.0), 1490.0, (1485.0, 1495.0))
        assert result == "statistically indistinguishable"

    def test_boundary_gap_exactly_20(self) -> None:
        # gap = 1495 - 1475 = 20, threshold is >= 20 → "clear separation"
        result = arena_gap_significance(1500.0, (1495.0, 1505.0), 1450.0, (1445.0, 1475.0))
        assert result == "clear separation"

    def test_boundary_gap_just_under_20(self) -> None:
        # gap = 1495 - 1476 = 19 → "small but statistically significant"
        result = arena_gap_significance(1500.0, (1495.0, 1505.0), 1450.0, (1445.0, 1476.0))
        assert result == "small but statistically significant difference"


@pytest.mark.unit
class TestAAGapSignificance:
    def test_small_gap(self) -> None:
        result = aa_gap_significance(50.0, 45.0, 13.3)
        assert result == "not clearly distinguishable"

    def test_moderate_gap(self) -> None:
        result = aa_gap_significance(50.0, 40.0, 13.3)
        assert result == "moderate difference"

    def test_clear_separation(self) -> None:
        result = aa_gap_significance(57.0, 39.0, 13.3)
        assert result == "clear separation"

    def test_zero_stdev(self) -> None:
        result = aa_gap_significance(50.0, 40.0, 0.0)
        assert result == "not clearly distinguishable"

    def test_equal_scores(self) -> None:
        result = aa_gap_significance(50.0, 50.0, 13.3)
        assert result == "not clearly distinguishable"
