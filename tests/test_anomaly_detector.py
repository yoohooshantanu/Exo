"""
Tests for modules/anomaly_detector.py

Covers: Zeng composition curves, distance_to_composition calculations,
null handling, and physical boundary conditions.
"""
import math

from modules.anomaly_detector import (
    zeng_pure_iron,
    zeng_earth_like,
    zeng_pure_water,
    distance_to_composition,
    nv,
)


# ── Zeng Composition Curves ──────────────────────────────────────────────────

class TestZengCurves:
    """Verify the polynomial coefficients produce physically correct results."""

    def test_earth_on_earth_like_curve(self):
        """Earth (R=1, M=1) should land close to the earth-like curve.
        log10(1) = 0, so earth_like(0) ≈ 0.09 → M ≈ 1.23."""
        log_m = zeng_earth_like(0.0)
        assert abs(log_m) < 0.2

    def test_ordering_at_large_radii(self):
        """At R >= 2, the physical ordering iron > earth > water holds.
        (Polynomial fits cross at small radii — known limitation.)"""
        for r in [2.0, 3.0, 4.0]:
            log_r = math.log10(r)
            iron = zeng_pure_iron(log_r)
            earth = zeng_earth_like(log_r)
            water = zeng_pure_water(log_r)
            assert iron > earth > water, f"Ordering failed at R={r}"

    def test_mass_increases_with_radius(self):
        """For each curve, mass should increase with radius."""
        for curve_fn in [zeng_pure_iron, zeng_earth_like, zeng_pure_water]:
            prev = curve_fn(math.log10(0.5))
            for r in [1.0, 1.5, 2.0, 3.0]:
                curr = curve_fn(math.log10(r))
                assert curr > prev, f"{curve_fn.__name__} not monotonic at R={r}"
                prev = curr

    def test_iron_steepest_slope(self):
        """Iron curve should have the steepest slope (highest exponent)."""
        r1, r2 = math.log10(2.0), math.log10(3.0)
        slope_iron = zeng_pure_iron(r2) - zeng_pure_iron(r1)
        slope_water = zeng_pure_water(r2) - zeng_pure_water(r1)
        assert slope_iron > slope_water

    def test_coefficients_are_positive(self):
        """All leading polynomial terms should produce positive masses at R > 1."""
        for r in [1.5, 2.0, 5.0]:
            log_r = math.log10(r)
            assert zeng_pure_iron(log_r) > 0
            assert zeng_earth_like(log_r) > 0
            assert zeng_pure_water(log_r) > 0


# ── Distance to Composition ──────────────────────────────────────────────────

class TestDistanceToComposition:
    def test_earth_returns_finite_sigma(self):
        """Earth (R=1, M=1) should return a finite, small sigma."""
        sigma, curve = distance_to_composition(1.0, 1.0, mass_err=0.1)
        assert sigma is not None
        assert sigma < 5.0
        assert curve is not None

    def test_massive_planet_at_r2_near_iron(self):
        """A very massive planet at R=2 (M=20) should be near pure iron."""
        sigma, curve = distance_to_composition(2.0, 20.0, mass_err=1.0)
        assert curve == "pure_iron"

    def test_light_planet_at_r2_near_water(self):
        """A light planet at R=2 (M=15) should be near pure water."""
        sigma, curve = distance_to_composition(2.0, 15.0, mass_err=1.0)
        assert curve == "pure_water"

    def test_none_radius_returns_none(self):
        sigma, curve = distance_to_composition(None, 1.0)
        assert sigma is None
        assert curve is None

    def test_none_mass_returns_none(self):
        sigma, curve = distance_to_composition(1.0, None)
        assert sigma is None
        assert curve is None

    def test_zero_radius_returns_none(self):
        sigma, curve = distance_to_composition(0, 1.0)
        assert sigma is None

    def test_negative_mass_returns_none(self):
        sigma, curve = distance_to_composition(1.0, -5.0)
        assert sigma is None

    def test_no_error_uses_generous_fallback(self):
        """Without mass_err, the function should use 50% fractional error."""
        sigma_with, _ = distance_to_composition(1.0, 1.0, mass_err=0.1)
        sigma_without, _ = distance_to_composition(1.0, 1.0, mass_err=None)
        # Generous fallback → larger denominator → smaller sigma
        assert sigma_without <= sigma_with

    def test_inferred_mass_widens_acceptance(self):
        """Inferred masses should have wider error bars (≥60%)."""
        sigma_direct, _ = distance_to_composition(1.0, 5.0, mass_err=0.5, is_direct_mass=True)
        sigma_inferred, _ = distance_to_composition(1.0, 5.0, mass_err=0.5, is_direct_mass=False)
        assert sigma_inferred <= sigma_direct

    def test_sigma_always_non_negative(self):
        """Distance in sigma should never be negative."""
        for r, m in [(0.5, 0.3), (1.0, 1.0), (2.0, 10.0), (3.0, 50.0)]:
            sigma, _ = distance_to_composition(r, m, mass_err=0.5)
            if sigma is not None:
                assert sigma >= 0


# ── NV helper ────────────────────────────────────────────────────────────────

class TestNv:
    def test_none_returns_none(self):
        assert nv(None) is None

    def test_nan_returns_none(self):
        assert nv(float("nan")) is None

    def test_inf_returns_none(self):
        assert nv(float("inf")) is None

    def test_valid_float(self):
        assert nv(3.14) == 3.14

    def test_valid_int(self):
        assert nv(5) == 5.0
