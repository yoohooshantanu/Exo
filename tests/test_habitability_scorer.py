"""
Tests for modules/habitability_scorer.py

Covers: ESI formula, individual score functions, composite scoring,
risk weighting, and edge cases (None inputs, zero values, boundary conditions).
"""
import math
import pytest

from modules.habitability_scorer import (
    esi_component,
    compute_similarity_esi,
    score_hz,
    score_teq,
    score_radius,
    score_mass,
    score_flare,
    score_tidal_lock,
    score_eccentricity,
    score_age,
    derive_teq,
    weighted_average,
    ESI_EXPONENTS,
    TEQ_REF_K,
    RISK_WEIGHTS,
    SIMILARITY_WEIGHT,
    SAFETY_WEIGHT,
)


# ── ESI Component ────────────────────────────────────────────────────────────

class TestEsiComponent:
    """Tests for the core ESI component formula: (1 - |x - x0| / (x + x0))^w"""

    def test_earth_values_return_1(self):
        """Earth values (x == x0) should yield exactly 1.0."""
        assert esi_component(1.0, 1.0, 0.57) == pytest.approx(1.0)
        assert esi_component(255.0, 255.0, 5.58) == pytest.approx(1.0)

    def test_none_returns_none(self):
        assert esi_component(None, 1.0, 0.57) is None

    def test_zero_returns_none(self):
        assert esi_component(0, 1.0, 0.57) is None

    def test_negative_returns_none(self):
        assert esi_component(-1.0, 1.0, 0.57) is None

    def test_larger_value_reduces_score(self):
        """A planet twice Earth's radius should score < 1.0."""
        score = esi_component(2.0, 1.0, 0.57)
        assert score is not None
        assert 0.0 < score < 1.0

    def test_very_different_value_scores_low(self):
        """A planet 10x Earth's radius should score very low."""
        score = esi_component(10.0, 1.0, 0.57)
        assert score is not None
        assert score < 0.5

    def test_higher_exponent_more_sensitive(self):
        """Higher exponent should amplify the penalty."""
        low_w = esi_component(2.0, 1.0, 0.57)
        high_w = esi_component(2.0, 1.0, 5.58)
        assert high_w < low_w


# ── Compute Similarity ESI ───────────────────────────────────────────────────

class TestComputeSimilarityEsi:
    """Tests for the geometric-mean ESI calculation."""

    def test_earth_twin_scores_near_1(self):
        """Earth (R=1, M=1, T=255K) should score very close to 1.0."""
        score = compute_similarity_esi(1.0, 1.0, TEQ_REF_K)
        assert score is not None
        assert score > 0.95

    def test_requires_temperature(self):
        """ESI requires temperature as one of the components."""
        score = compute_similarity_esi(1.0, 1.0, None)
        assert score is None

    def test_radius_only_with_temp(self):
        """If only radius + temp are available (no mass), should still compute with n=2."""
        score = compute_similarity_esi(1.0, None, TEQ_REF_K)
        assert score is not None
        assert score > 0.9

    def test_hot_jupiter_scores_low(self):
        """A hot Jupiter (R=11, M=300, T=1500K) should score very low."""
        score = compute_similarity_esi(11.0, 300.0, 1500.0)
        assert score is not None
        assert score < 0.3

    def test_super_earth_scores_moderate(self):
        """A warm super-Earth (R=1.5, M=5, T=300K) should score moderately."""
        score = compute_similarity_esi(1.5, 5.0, 300.0)
        assert score is not None
        assert 0.3 < score < 0.9


# ── Habitable Zone Score ─────────────────────────────────────────────────────

class TestScoreHz:
    def test_earth_position_scores_high(self):
        """Earth at 1 AU around a solar-luminosity star."""
        score = score_hz(1.0, 0.0)  # log(L) = 0 → L = 1.0 solar
        assert score is not None
        assert score > 0.5  # Earth is inside the HZ but not at the midpoint (~1.35 AU)

    def test_too_close_scores_low(self):
        """Planet at 0.1 AU (inside inner HZ)."""
        score = score_hz(0.1, 0.0)
        assert score is not None
        assert score < 0.5

    def test_too_far_scores_low(self):
        """Planet at 5 AU (outside outer HZ)."""
        score = score_hz(5.0, 0.0)
        assert score is not None
        assert score < 0.5

    def test_none_returns_none(self):
        assert score_hz(None, 0.0) is None


# ── Temperature Score ────────────────────────────────────────────────────────

class TestScoreTeq:
    def test_earth_temp_scores_1(self):
        """255K (Earth equilibrium) should score 1.0."""
        score = score_teq(TEQ_REF_K)
        assert score == pytest.approx(1.0)

    def test_hot_planet_scores_low(self):
        score = score_teq(2000.0)
        assert score is not None
        assert score < 0.3

    def test_none_returns_none(self):
        assert score_teq(None) is None


# ── Radius & Mass Scores ────────────────────────────────────────────────────

class TestScoreRadiusMass:
    def test_earth_radius_scores_1(self):
        assert score_radius(1.0) == pytest.approx(1.0)

    def test_earth_mass_scores_1(self):
        assert score_mass(1.0) == pytest.approx(1.0)

    def test_jupiter_radius_scores_low(self):
        score = score_radius(11.2)
        assert score is not None
        assert score < 0.4  # Jupiter is 11.2x Earth — very un-Earth-like


# ── Flare Score ──────────────────────────────────────────────────────────────

class TestScoreFlare:
    def test_g_dwarf_scores_highest(self):
        """G-type stars (5200-6000K) are safest, should score ~1.0."""
        score = score_flare(5500)
        assert score is not None
        assert score > 0.8

    def test_m_dwarf_scores_low(self):
        """M-dwarfs (2400-3700K) are dangerous flarers, should score low."""
        score = score_flare(3000)
        assert score is not None
        assert score < 0.7

    def test_extreme_hot_scores_low(self):
        """O/B stars (>10000K) have harsh UV, score low."""
        score = score_flare(15000)
        assert score is not None
        assert score <= 0.2

    def test_none_returns_none(self):
        assert score_flare(None) is None

    def test_hostile_stars_can_score_below_floor(self):
        """Measured hostile environments should not be artificially floored."""
        score = score_flare(15000)
        assert score is not None
        assert score <= 0.1


# ── Tidal Lock Score ─────────────────────────────────────────────────────────

class TestScoreTidalLock:
    def test_close_in_planet_scores_low(self):
        """Planet at 0.02 AU around a solar-mass star — likely tidally locked."""
        score = score_tidal_lock(0.02, 1.0, 1.0)
        assert score is not None
        assert score < 0.5

    def test_far_out_planet_scores_high(self):
        """Planet at 1 AU — not tidally locked."""
        score = score_tidal_lock(1.0, 1.0, 1.0)
        assert score is not None
        assert score > 0.5

    def test_none_returns_none(self):
        assert score_tidal_lock(None, 1.0, 1.0) is None
        assert score_tidal_lock(1.0, None, 1.0) is None
        assert score_tidal_lock(1.0, 1.0, None) is None


# ── Eccentricity Score ───────────────────────────────────────────────────────

class TestScoreEccentricity:
    def test_circular_orbit_scores_1(self):
        score = score_eccentricity(0.0)
        assert score == pytest.approx(1.0)

    def test_high_ecc_scores_low(self):
        score = score_eccentricity(0.8)
        assert score is not None
        assert score < 0.5

    def test_none_returns_none(self):
        assert score_eccentricity(None) is None

    def test_high_ecc_can_score_below_old_floor(self):
        score = score_eccentricity(0.99)
        assert score is not None
        assert score < 0.2


# ── Age Score ────────────────────────────────────────────────────────────────

class TestScoreAge:
    def test_solar_age_scores_well(self):
        """The Sun is ~4.6 Gyr old — should score well."""
        score = score_age(4.6)
        assert score is not None
        assert score > 0.5

    def test_very_young_scores_low(self):
        """Very young star (0.1 Gyr) — high activity, dangerous."""
        score = score_age(0.1)
        assert score is not None
        assert score < 0.5

    def test_none_returns_none(self):
        assert score_age(None) is None

    def test_zero_returns_none(self):
        assert score_age(0) is None


# ── Derive Teq ───────────────────────────────────────────────────────────────

class TestDeriveTeq:
    def test_earth_values(self):
        """Earth at 1 AU with solar luminosity should give ~255K."""
        teq = derive_teq(1.0, 0.0)  # log(L) = 0 → L = 1.0
        assert teq is not None
        assert 200 < teq < 300

    def test_none_returns_none(self):
        assert derive_teq(None, 0.0) is None

    def test_zero_distance_returns_none(self):
        assert derive_teq(0, 0.0) is None


# ── Weighted Average ─────────────────────────────────────────────────────────

class TestWeightedAverage:
    def test_basic_average(self):
        scores = {"a": 0.8, "b": 0.6}
        weights = {"a": 0.5, "b": 0.5}
        result = weighted_average(scores, weights)
        assert result == pytest.approx(0.7)

    def test_skips_none_values(self):
        scores = {"a": 0.8, "b": None, "c": 0.6}
        weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        result = weighted_average(scores, weights)
        assert result is not None

    def test_too_few_returns_none(self):
        """Needs at least 2 non-null components."""
        scores = {"a": 0.8, "b": None}
        weights = {"a": 0.5, "b": 0.5}
        result = weighted_average(scores, weights)
        assert result is None

    def test_result_clamped_0_1(self):
        scores = {"a": 1.0, "b": 1.0}
        weights = {"a": 0.5, "b": 0.5}
        result = weighted_average(scores, weights)
        assert 0.0 <= result <= 1.0


# ── Constants Integrity ──────────────────────────────────────────────────────

class TestConstants:
    def test_risk_weights_sum_to_1(self):
        assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9

    def test_composite_weights_sum_to_1(self):
        assert abs(SIMILARITY_WEIGHT + SAFETY_WEIGHT - 1.0) < 1e-9

    def test_esi_exponents_positive(self):
        for name, exp in ESI_EXPONENTS.items():
            assert exp > 0, f"ESI exponent '{name}' should be positive"
