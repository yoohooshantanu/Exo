"""
tests/test_habitable_zone.py

Unit and scientific validation tests for modules/habitable_zone.py.
Validates:
  1. Solar-like star incident flux & boundaries (Earth baseline)
  2. M-dwarf star incident flux & temperature-dependent boundaries
  3. Direct vs derived luminosity (Stefan-Boltzmann)
  4. Missing luminosity and missing stellar parameters (no silent fallbacks)
  5. Published Kopparapu applicability boundaries [2600 K, 7200 K] & extrapolation guards
  6. Conservative vs optimistic classification consistency
  7. Flux uncertainty propagation (analytical and Monte Carlo)
  8. Missing uncertainty handling (honest non-calculable state)
  9. Elimination of midpoint-based distance scoring
"""

import pytest
import math
from modules.habitable_zone import (
    derive_stellar_luminosity,
    resolve_stellar_luminosity,
    calculate_incident_flux,
    compute_kopparapu_boundaries,
    assess_habitable_zone,
    TEFF_MIN_K,
    TEFF_MAX_K,
    T_SUN_K,
)


class TestStellarLuminosity:
    def test_direct_catalog_linear_luminosity_used(self):
        res = resolve_stellar_luminosity(luminosity_solar=2.5, luminosity_err=0.1)
        assert res.luminosity_source == "catalog"
        assert res.luminosity_solar == pytest.approx(2.5)
        assert res.uncertainty_solar == pytest.approx(0.1)

    def test_direct_catalog_log10_luminosity_converted(self):
        # log10(L/L_sun) = -1.0 -> L = 0.1
        res = resolve_stellar_luminosity(luminosity_log10=-1.0, luminosity_err=0.05)
        assert res.luminosity_source == "catalog"
        assert res.luminosity_solar == pytest.approx(0.1)
        assert res.uncertainty_solar is not None

    def test_derive_luminosity_via_stefan_boltzmann(self):
        # Star with 2 R_sun and 5778 K -> L = 4 * (1)^4 = 4.0
        lum, err = derive_stellar_luminosity(radius_solar=2.0, teff_k=T_SUN_K)
        assert lum == pytest.approx(4.0)

        # Star with 1 R_sun and 2*T_sun -> L = 1 * (2)^4 = 16.0
        lum2, _ = derive_stellar_luminosity(radius_solar=1.0, teff_k=2.0 * T_SUN_K)
        assert lum2 == pytest.approx(16.0)

    def test_derive_luminosity_error_propagation(self):
        # 10% error in radius, 5% error in Teff
        # rel_L_err = sqrt((2*0.1)^2 + (4*0.05)^2) = sqrt(0.04 + 0.04) = sqrt(0.08) ~ 0.2828
        lum, err = derive_stellar_luminosity(
            radius_solar=1.0,
            teff_k=T_SUN_K,
            radius_err=0.1,
            teff_err=0.05 * T_SUN_K,
        )
        assert lum == pytest.approx(1.0)
        expected_rel_err = math.sqrt((2.0 * 0.1) ** 2.0 + (4.0 * 0.05) ** 2.0)
        assert err == pytest.approx(expected_rel_err, rel=1e-3)

    def test_resolve_derives_when_catalog_missing(self):
        res = resolve_stellar_luminosity(
            luminosity_solar=None,
            luminosity_log10=None,
            radius_solar=0.5,
            teff_k=4000.0,
        )
        assert res.luminosity_source == "derived"
        assert res.luminosity_solar is not None
        assert res.luminosity_solar < 1.0

    def test_resolve_never_silently_assumes_solar_1_when_missing(self):
        res = resolve_stellar_luminosity(
            luminosity_solar=None,
            luminosity_log10=None,
            radius_solar=None,
            teff_k=None,
        )
        assert res.luminosity_source == "unavailable"
        assert res.luminosity_solar is None
        assert any("unavailable" in w.lower() for w in res.warnings)

    def test_catalog_priority_over_derived(self):
        # If both catalog linear and (radius, teff) exist, catalog takes priority
        res = resolve_stellar_luminosity(
            luminosity_solar=0.8,
            radius_solar=2.0,
            teff_k=6000.0,
        )
        assert res.luminosity_source == "catalog"
        assert res.luminosity_solar == pytest.approx(0.8)


class TestIncidentStellarFlux:
    def test_earth_sun_baseline(self):
        flux, err = calculate_incident_flux(luminosity_solar=1.0, semi_major_axis_au=1.0)
        assert flux == pytest.approx(1.0)
        assert err is None

    def test_inverse_square_law(self):
        # 1 solar luminosity at 2 AU -> flux = 1/4 = 0.25
        flux, _ = calculate_incident_flux(luminosity_solar=1.0, semi_major_axis_au=2.0)
        assert flux == pytest.approx(0.25)

        # 0.01 solar luminosity at 0.1 AU -> flux = 0.01 / 0.01 = 1.0
        flux2, _ = calculate_incident_flux(luminosity_solar=0.01, semi_major_axis_au=0.1)
        assert flux2 == pytest.approx(1.0)

    def test_flux_uncertainty_propagation(self):
        # L = 1.0 +- 0.1 (10%), a = 1.0 +- 0.05 (5%)
        # rel_flux_err = sqrt((0.1)^2 + (2*0.05)^2) = sqrt(0.01 + 0.01) = sqrt(0.02) ~ 0.1414
        flux, err = calculate_incident_flux(
            luminosity_solar=1.0,
            semi_major_axis_au=1.0,
            luminosity_err=0.1,
            semi_major_axis_err=0.05,
        )
        assert flux == pytest.approx(1.0)
        assert err == pytest.approx(math.sqrt(0.01 + 0.01), rel=1e-3)

    def test_invalid_negative_or_zero_inputs(self):
        assert calculate_incident_flux(luminosity_solar=0.0, semi_major_axis_au=1.0) == (None, None)
        assert calculate_incident_flux(luminosity_solar=1.0, semi_major_axis_au=0.0) == (None, None)
        assert calculate_incident_flux(luminosity_solar=-1.0, semi_major_axis_au=1.0) == (None, None)
        assert calculate_incident_flux(luminosity_solar=1.0, semi_major_axis_au=-1.0) == (None, None)
        assert calculate_incident_flux(luminosity_solar=None, semi_major_axis_au=1.0) == (None, None)


class TestKopparapuBoundaries:
    def test_sun_like_star_boundaries(self):
        bounds = compute_kopparapu_boundaries(teff_k=5780.0, luminosity_solar=1.0)
        assert bounds.is_valid_range is True
        # At T_* = 0, flux limits equal S_eff_sun values
        assert bounds.s_eff_runaway_greenhouse == pytest.approx(1.0385, abs=1e-3)
        assert bounds.s_eff_maximum_greenhouse == pytest.approx(0.3507, abs=1e-3)
        assert bounds.s_eff_recent_venus == pytest.approx(1.7763, abs=1e-3)
        assert bounds.s_eff_early_mars == pytest.approx(0.3207, abs=1e-3)

        # In solar units, distance boundaries:
        # dist = sqrt(1 / S_eff)
        # runaway: sqrt(1 / 1.0385) ~ 0.981 AU
        # max greenhouse: sqrt(1 / 0.3507) ~ 1.689 AU
        assert bounds.dist_runaway_greenhouse_au == pytest.approx(math.sqrt(1.0 / 1.0385), abs=1e-3)
        assert bounds.dist_maximum_greenhouse_au == pytest.approx(math.sqrt(1.0 / 0.3507), abs=1e-3)

    def test_temperature_dependent_m_dwarf_shift(self):
        # For M-dwarfs (cooler stars, e.g. 3000 K), the peak emission shifts redward,
        # where H2O and CO2 absorption is stronger, requiring LOWER incident flux to maintain habitable temperatures.
        # Thus S_eff_runaway_greenhouse and S_eff_maximum_greenhouse should be lower than for G-dwarfs.
        bounds_g = compute_kopparapu_boundaries(teff_k=5780.0)
        bounds_m = compute_kopparapu_boundaries(teff_k=3200.0)
        assert bounds_m.is_valid_range is True
        assert bounds_m.s_eff_runaway_greenhouse < bounds_g.s_eff_runaway_greenhouse
        assert bounds_m.s_eff_maximum_greenhouse < bounds_g.s_eff_maximum_greenhouse

    def test_strict_validity_range_rejection(self):
        # Ultra-cool dwarf below 2600 K
        bounds_cold = compute_kopparapu_boundaries(teff_k=2400.0)
        assert bounds_cold.is_valid_range is False
        assert any("validity range" in w.lower() for w in bounds_cold.warnings)

        # Hot star above 7200 K
        bounds_hot = compute_kopparapu_boundaries(teff_k=8500.0)
        assert bounds_hot.is_valid_range is False
        assert any("validity range" in w.lower() for w in bounds_hot.warnings)

    def test_none_teff_handled(self):
        bounds_none = compute_kopparapu_boundaries(teff_k=None)
        assert bounds_none.is_valid_range is False
        assert any("missing" in w.lower() for w in bounds_none.warnings)


class TestHabitableZoneAssessment:
    def test_earth_in_solar_system(self):
        # Earth: a = 1.0 AU around Sun (L = 1.0, Teff = 5780 K)
        # With small orbital uncertainty
        res = assess_habitable_zone(
            semi_major_axis_au=1.0,
            luminosity_solar=1.0,
            teff_k=5780.0,
            semi_major_axis_err=0.01,
            luminosity_err=0.01,
        )
        assert res.incident_stellar_flux == pytest.approx(1.0, abs=1e-2)
        assert res.conservative_hz is True
        assert res.optimistic_hz is True
        assert res.hz_classification == "conservative"
        assert res.probability_calculable is True
        assert res.prob_conservative is not None and res.prob_conservative >= 0.90
        assert res.prob_optimistic is not None and res.prob_optimistic >= 0.98

    def test_recent_venus_optimistic_only(self):
        # Venus gets S_eff ~ 1.776 / a ~ 0.723 AU
        # Planet placed between runaway greenhouse (1.0385) and recent venus (1.7763), say S_eff = 1.40
        # a = sqrt(1.0 / 1.40) ~ 0.845 AU
        res = assess_habitable_zone(
            semi_major_axis_au=math.sqrt(1.0 / 1.40),
            luminosity_solar=1.0,
            teff_k=5780.0,
        )
        assert res.conservative_hz is False
        assert res.optimistic_hz is True
        assert res.hz_classification == "optimistic"

    def test_too_hot_planet(self):
        # Mercury at 0.387 AU gets S_eff ~ 6.67
        res = assess_habitable_zone(
            semi_major_axis_au=0.387,
            luminosity_solar=1.0,
            teff_k=5780.0,
        )
        assert res.conservative_hz is False
        assert res.optimistic_hz is False
        assert res.hz_classification == "too_hot"

    def test_too_cold_planet(self):
        # Jupiter at 5.2 AU gets S_eff ~ 0.037
        res = assess_habitable_zone(
            semi_major_axis_au=5.2,
            luminosity_solar=1.0,
            teff_k=5780.0,
        )
        assert res.conservative_hz is False
        assert res.optimistic_hz is False
        assert res.hz_classification == "too_cold"

    def test_m_dwarf_system_proxima_cen_b(self):
        # Proxima Centauri b: L ~ 0.0017 L_sun, a ~ 0.0485 AU, Teff ~ 3050 K
        # S_eff = 0.0017 / (0.0485^2) ~ 0.722
        res = assess_habitable_zone(
            semi_major_axis_au=0.0485,
            luminosity_solar=0.0017,
            teff_k=3050.0,
            semi_major_axis_err=0.001,
            luminosity_err=0.0001,
        )
        assert res.incident_stellar_flux is not None
        assert res.conservative_hz is True
        assert res.hz_classification == "conservative"

    def test_m_dwarf_derived_luminosity(self):
        # Proxima with catalog luminosity missing, but R_* = 0.1542 R_sun, Teff = 3050 K
        # L_derived = (0.1542)^2 * (3050 / 5778)^4 ~ 0.02377 * 0.0776 ~ 0.00184 L_sun
        res = assess_habitable_zone(
            semi_major_axis_au=0.0485,
            luminosity_solar=None,
            radius_solar=0.1542,
            teff_k=3050.0,
        )
        assert res.luminosity_source == "derived"
        assert res.luminosity_solar is not None
        assert 0.0010 < res.luminosity_solar < 0.0025
        assert res.hz_classification in ("conservative", "optimistic")

    def test_missing_uncertainty_does_not_manufacture_probabilities(self):
        # Planet with deterministic parameters but NO uncertainties provided
        res = assess_habitable_zone(
            semi_major_axis_au=1.0,
            luminosity_solar=1.0,
            teff_k=5780.0,
            semi_major_axis_err=None,
            luminosity_err=None,
        )
        assert res.conservative_hz is True
        assert res.probability_calculable is False
        assert res.prob_conservative is None
        assert res.prob_optimistic is None
        assert any("uncertainties unavailable" in w.lower() for w in res.warnings)

    def test_invalid_temperature_prevents_extrapolation(self):
        # Hot A-type star (Teff = 9000 K)
        res = assess_habitable_zone(
            semi_major_axis_au=2.5,
            luminosity_solar=20.0,
            teff_k=9000.0,
        )
        assert res.hz_classification == "unknown"
        assert res.conservative_hz is False
        assert res.optimistic_hz is False
        assert any("validity range" in w.lower() for w in res.warnings)

    def test_no_arbitrary_midpoint_reward(self):
        # Two planets both inside conservative HZ:
        # Planet 1: S_eff = 0.70 (near midpoint of ~0.35 - 1.04)
        # Planet 2: S_eff = 0.95 (closer to inner edge)
        # Neither should have an arbitrary scoring penalty or reward for position
        res1 = assess_habitable_zone(
            semi_major_axis_au=math.sqrt(1.0 / 0.70),
            luminosity_solar=1.0,
            teff_k=5780.0,
        )
        res2 = assess_habitable_zone(
            semi_major_axis_au=math.sqrt(1.0 / 0.95),
            luminosity_solar=1.0,
            teff_k=5780.0,
        )
        assert res1.conservative_hz is True
        assert res2.conservative_hz is True
        assert res1.hz_classification == "conservative"
        assert res2.hz_classification == "conservative"
        # The assessment does not contain a midpoint distance multiplier
        assert "score" not in res1.__dict__

    def test_trappist_1e_out_of_domain_returns_unknown_and_warning(self):
        # TRAPPIST-1 e actual stellar temperature Teff ~ 2566 K (< 2600 K Kopparapu lower limit)
        # a = 0.0293 AU, L derived from R_* = 0.1192 R_sun, Teff = 2566 K -> L ~ 0.00055 L_sun
        res = assess_habitable_zone(
            semi_major_axis_au=0.0293,
            teff_k=2566.0,
            radius_solar=0.1192,
            eccentricity=0.006,
        )
        # Must return unknown classification, never falsely claim conservative or optimistic
        assert res.hz_classification == "unknown"
        assert res.conservative_hz is False
        assert res.optimistic_hz is False
        assert res.prob_conservative is None
        assert res.prob_optimistic is None
        assert any("2566.0 K" in w and "2600 K" in w for w in res.warnings)

    def test_eccentric_orbit_flux_calculations(self):
        # Star: Sun-like (L = 1.0, Teff = 5780 K)
        # Planet: a = 1.0 AU, e = 0.2
        # <S_eff> = 1.0 / (1.0^2 * sqrt(1 - 0.2^2)) = 1 / sqrt(0.96) ~ 1.02062
        # S_peri = 1.0 / (1.0 * (1 - 0.2))^2 = 1.0 / 0.64 = 1.5625
        # S_apo = 1.0 / (1.0 * (1 + 0.2))^2 = 1.0 / 1.44 ~ 0.69444
        res = assess_habitable_zone(
            semi_major_axis_au=1.0,
            luminosity_solar=1.0,
            teff_k=5780.0,
            eccentricity=0.2,
        )
        assert res.incident_stellar_flux == pytest.approx(1.0 / math.sqrt(0.96), rel=1e-3)
        assert res.flux_at_semi_major_axis == pytest.approx(1.0, rel=1e-3)
        assert res.flux_periastron == pytest.approx(1.5625, rel=1e-3)
        assert res.flux_apastron == pytest.approx(1.0 / 1.44, rel=1e-3)
        assert res.is_circular_approximation is False

    def test_circular_orbit_fallback(self):
        # When eccentricity is None or 0.0, falls back to circular approximation
        res = assess_habitable_zone(
            semi_major_axis_au=1.0,
            luminosity_solar=1.0,
            teff_k=5780.0,
            eccentricity=None,
        )
        assert res.incident_stellar_flux == pytest.approx(1.0)
        assert res.is_circular_approximation is True
        assert res.flux_periastron is None
        assert res.flux_apastron is None

    def test_invalid_eccentricity_handled_safely(self):
        # e >= 1.0 or e < 0.0 is unphysical for bound orbits
        res = assess_habitable_zone(
            semi_major_axis_au=1.0,
            luminosity_solar=1.0,
            teff_k=5780.0,
            eccentricity=1.05,
        )
        assert res.is_circular_approximation is True
        assert any("eccentricity" in w.lower() for w in res.warnings)

    def test_reference_mass_metadata(self):
        res = assess_habitable_zone(
            semi_major_axis_au=1.0,
            luminosity_solar=1.0,
            teff_k=5780.0,
        )
        assert res.reference_mass_earth == 1.0
        assert "1.0 M_earth" in res.mass_reference_note

    def test_monte_carlo_domain_crossing_guard(self):
        # Star Teff = 2620 K (very close to 2600 K cutoff) with uncertainty 100 K
        # Large fraction of draws will fall below 2600 K
        res = assess_habitable_zone(
            semi_major_axis_au=0.03,
            luminosity_solar=0.0006,
            teff_k=2620.0,
            semi_major_axis_err=0.001,
            luminosity_err=0.00005,
            teff_err=100.0,
        )
        # Because >10% of draws cross below 2600 K, probability_calculable must be False
        assert res.probability_calculable is False
        assert res.prob_conservative is None
        assert res.prob_optimistic is None
        assert any("validity range" in w.lower() or "fall outside" in w.lower() for w in res.warnings)
