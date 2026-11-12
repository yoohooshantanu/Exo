"""
Tests for orbital mechanics helpers in modules/orbital_gap_predictor.py

Since `rebound` (N-body library) may not be installed in test environments,
we mock it before importing the module.

Covers: mass estimation, semi-major axis derivation, mutual Hill radius,
and the M_EARTH_TO_SOLAR conversion constant.
"""
import sys
import pytest
from unittest.mock import MagicMock

# Mock rebound only if not installed in the test environment
try:
    import rebound  # noqa: F401
except ImportError:
    from unittest.mock import MagicMock
    sys.modules["rebound"] = MagicMock()

from modules.orbital_gap_predictor import (
    get_mass_earth,
    get_a_au,
    mutual_hill_radius,
    M_EARTH_TO_SOLAR,
)
from modules.utils import nv


# ── Mass Estimation ──────────────────────────────────────────────────────────

class TestGetMassEarth:
    def test_direct_mass_returned(self):
        """If mass is known, return it directly."""
        assert get_mass_earth(1.0, 5.0) == 5.0

    def test_small_planet_radius_cubed(self):
        """R < 1.5 → M ≈ R^3 (rocky approximation)."""
        result = get_mass_earth(1.0, None)
        assert result == pytest.approx(1.0 ** 3.0)

    def test_large_planet_radius_power(self):
        """R >= 1.5 → M ≈ R^2.06 (volatile-rich approximation)."""
        result = get_mass_earth(2.0, None)
        assert result == pytest.approx(2.0 ** 2.06, rel=1e-3)

    def test_no_data_fallback(self):
        """No radius or mass → fallback to 1.0 Earth mass."""
        assert get_mass_earth(None, None) == 1.0

    def test_mass_priority_over_radius(self):
        """Even if radius is available, known mass takes priority."""
        assert get_mass_earth(2.0, 10.0) == 10.0

    def test_boundary_at_1_5(self):
        """At exactly R=1.5, should use the R^2.06 branch."""
        result = get_mass_earth(1.5, None)
        assert result == pytest.approx(1.5 ** 2.06, rel=1e-3)

    def test_sub_earth(self):
        """R=0.5 → M ≈ 0.125 (rocky)."""
        result = get_mass_earth(0.5, None)
        assert result == pytest.approx(0.5 ** 3.0)


# ── Semi-Major Axis Derivation ───────────────────────────────────────────────

class TestGetAAu:
    def test_direct_value_returned(self):
        """If semi-major axis is known, return it."""
        assert get_a_au(1.0, 365.25, 1.0) == 1.0

    def test_kepler_third_law_earth(self):
        """Earth: P=365.25 days, M*=1.0 → a ≈ 1.0 AU."""
        result = get_a_au(None, 365.25, 1.0)
        assert result == pytest.approx(1.0, rel=0.01)

    def test_short_period_hot_jupiter(self):
        """P=3 days around solar star → a << 1 AU."""
        result = get_a_au(None, 3.0, 1.0)
        assert result is not None
        assert result < 0.1

    def test_longer_period_farther_out(self):
        """Longer period should give larger semi-major axis."""
        a_short = get_a_au(None, 10.0, 1.0)
        a_long = get_a_au(None, 100.0, 1.0)
        assert a_long > a_short

    def test_heavier_star_larger_orbit(self):
        """At same period, heavier star → larger orbit (Kepler's 3rd)."""
        a_light = get_a_au(None, 365.25, 0.5)
        a_heavy = get_a_au(None, 365.25, 2.0)
        assert a_heavy > a_light

    def test_no_period_returns_none(self):
        assert get_a_au(None, None, 1.0) is None

    def test_no_star_mass_returns_none(self):
        assert get_a_au(None, 365.25, None) is None

    def test_zero_star_mass_returns_none(self):
        assert get_a_au(None, 365.25, 0) is None

    def test_direct_value_takes_priority(self):
        """If a is provided directly, period/mass are ignored."""
        assert get_a_au(2.5, 10.0, 0.1) == 2.5


# ── Mutual Hill Radius ───────────────────────────────────────────────────────

class TestMutualHillRadius:
    def test_basic_calculation(self):
        """Two Earth-mass planets at 1 and 1.5 AU around solar star."""
        m1 = 1.0 * M_EARTH_TO_SOLAR
        m2 = 1.0 * M_EARTH_TO_SOLAR
        rh = mutual_hill_radius(1.0, m1, 1.5, m2, 1.0)
        assert rh > 0
        assert rh < 0.5

    def test_heavier_planets_larger_hill(self):
        """More massive planets should have a larger Hill radius."""
        m_light = 1.0 * M_EARTH_TO_SOLAR
        m_heavy = 100.0 * M_EARTH_TO_SOLAR
        rh_light = mutual_hill_radius(1.0, m_light, 1.5, m_light, 1.0)
        rh_heavy = mutual_hill_radius(1.0, m_heavy, 1.5, m_heavy, 1.0)
        assert rh_heavy > rh_light

    def test_symmetry(self):
        """Hill radius should be the same regardless of planet order."""
        m1 = 3.0 * M_EARTH_TO_SOLAR
        m2 = 5.0 * M_EARTH_TO_SOLAR
        rh_12 = mutual_hill_radius(1.0, m1, 1.5, m2, 1.0)
        rh_21 = mutual_hill_radius(1.5, m2, 1.0, m1, 1.0)
        assert rh_12 == pytest.approx(rh_21)

    def test_wider_separation_larger_hill(self):
        """Planets farther apart should have larger mutual Hill radius."""
        m = 5.0 * M_EARTH_TO_SOLAR
        rh_close = mutual_hill_radius(1.0, m, 1.1, m, 1.0)
        rh_far = mutual_hill_radius(1.0, m, 2.0, m, 1.0)
        assert rh_far > rh_close


# ── Constants ────────────────────────────────────────────────────────────────

class TestOrbitalConstants:
    def test_m_earth_to_solar(self):
        """M_earth / M_sun ≈ 3.003e-6."""
        assert M_EARTH_TO_SOLAR == pytest.approx(3.003e-6, rel=0.01)


# ── NV helper (from utils) ───────────────────────────────────────────────────

class TestNvUtils:
    def test_none(self):
        assert nv(None) is None

    def test_nan(self):
        assert nv(float("nan")) is None

    def test_valid(self):
        assert nv(42.0) == 42.0
