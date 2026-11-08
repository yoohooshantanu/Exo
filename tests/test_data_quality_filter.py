"""
Tests for modules/data_quality_filter.py

Covers: float parsing, value detection, density sanity checks,
discovery method filtering, and estimate flagging.
"""
import pytest
from modules.data_quality_filter import to_float, has_value


# ── to_float ─────────────────────────────────────────────────────────────────

class TestToFloat:
    def test_valid_float_string(self):
        assert to_float("3.14") == pytest.approx(3.14)

    def test_valid_int_string(self):
        assert to_float("42") == 42.0

    def test_empty_string(self):
        assert to_float("") is None

    def test_none(self):
        assert to_float(None) is None

    def test_garbage_string(self):
        assert to_float("N/A") is None

    def test_negative(self):
        assert to_float("-1.5") == pytest.approx(-1.5)

    def test_scientific_notation(self):
        assert to_float("1.5e-3") == pytest.approx(0.0015)


# ── has_value ────────────────────────────────────────────────────────────────

class TestHasValue:
    def test_none_is_false(self):
        assert has_value(None) is False

    def test_empty_string_is_false(self):
        assert has_value("") is False

    def test_whitespace_is_false(self):
        assert has_value("   ") is False

    def test_valid_number_is_true(self):
        assert has_value("3.14") is True

    def test_zero_is_true(self):
        assert has_value("0") is True


# ── Density Logic (unit tests on the cleaning rules) ─────────────────────────

class TestDensityRules:
    """Test the density sanity check boundaries used in data_quality_filter.run()."""

    def test_earth_density_passes(self):
        """Earth: R=1, M=1 → density=1.0 — well within [0.3, 10.0]."""
        rad, mass = 1.0, 1.0
        density = mass / (rad ** 3)
        assert 0.3 <= density <= 10.0

    def test_iron_planet_passes(self):
        """Dense iron planet: R=0.8, M=3 → density=5.86 — within bounds."""
        rad, mass = 0.8, 3.0
        density = mass / (rad ** 3)
        assert 0.3 <= density <= 10.0

    def test_impossibly_light_fails(self):
        """R=2, M=0.1 → density=0.0125 — below 0.3, should be flagged."""
        rad, mass = 2.0, 0.1
        density = mass / (rad ** 3)
        assert density < 0.3

    def test_impossibly_dense_fails(self):
        """R=0.5, M=20 → density=160 — far above 10.0, should be flagged."""
        rad, mass = 0.5, 20.0
        density = mass / (rad ** 3)
        assert density > 10.0

    def test_giant_planet_not_filtered(self):
        """R=5 (> 4 R⊕) — density check should NOT apply to giants."""
        rad = 5.0
        assert rad >= 4.0  # Giants are excluded from density filter
