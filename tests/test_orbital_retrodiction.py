"""
tests/test_orbital_retrodiction.py

Validates the orbital dynamics engine's retrodiction capability on known multi-planet systems.
Specifically tests whether masking a known planet leaves a dynamically permitted stable niche
that is successfully recovered by N-body MEGNO integration.
"""
import pytest
import math
from modules.orbital_gap_predictor import run_megno, mutual_hill_radius

M_EARTH_TO_SOLAR = 3.003e-6


class TestOrbitalRetrodiction:
    def test_trappist1e_masked_retrodiction(self):
        """
        Retrodiction test on TRAPPIST-1:
        TRAPPIST-1 host star: M ~ 0.0898 M_sun.
        Known planets:
          b: a = 0.0115 AU, m = 1.37 M_earth
          c: a = 0.0158 AU, m = 1.31 M_earth
          d: a = 0.0223 AU, m = 0.39 M_earth
          [e: a = 0.0293 AU, m = 0.69 M_earth]  <-- MASKED
          f: a = 0.0385 AU, m = 1.04 M_earth
          g: a = 0.0469 AU, m = 1.32 M_earth
          h: a = 0.0619 AU, m = 0.33 M_earth
        
        When planet e is masked, the dynamical gap between d (0.0223 AU) and f (0.0385 AU)
        should permit a stable test particle at a ~ 0.0293 AU.
        """
        m_star = 0.0898
        
        # Architecture with planet 'e' masked
        masked_planets = [
            {"a": 0.0115, "m": 1.37 * M_EARTH_TO_SOLAR, "m_e": 1.37, "ecc": 0.006},
            {"a": 0.0158, "m": 1.31 * M_EARTH_TO_SOLAR, "m_e": 1.31, "ecc": 0.007},
            {"a": 0.0223, "m": 0.39 * M_EARTH_TO_SOLAR, "m_e": 0.39, "ecc": 0.008},
            {"a": 0.0385, "m": 1.04 * M_EARTH_TO_SOLAR, "m_e": 1.04, "ecc": 0.010},
            {"a": 0.0469, "m": 1.32 * M_EARTH_TO_SOLAR, "m_e": 1.32, "ecc": 0.002},
            {"a": 0.0619, "m": 0.33 * M_EARTH_TO_SOLAR, "m_e": 0.33, "ecc": 0.006},
        ]
        
        test_a = 0.0293  # Exact semi-major axis of real planet e
        test_m_solar = 0.69 * M_EARTH_TO_SOLAR
        
        # Test 1: Analytical mutual Hill radius clearance
        r_h1 = mutual_hill_radius(0.0223, 0.39 * M_EARTH_TO_SOLAR, test_a, test_m_solar, m_star)
        r_h2 = mutual_hill_radius(test_a, test_m_solar, 0.0385, 1.04 * M_EARTH_TO_SOLAR, m_star)
        d1 = (test_a - 0.0223) / r_h1
        d2 = (0.0385 - test_a) / r_h2
        
        # Hill separation to neighbors should exceed Hill stability limits
        assert d1 > 3.46, f"Separation to inner planet d1={d1:.2f} must exceed Gladman limit"
        assert d2 > 3.46, f"Separation to outer planet d2={d2:.2f} must exceed Gladman limit"
        
        # Test 2: Fast N-body MEGNO screen
        is_stable, megno, orbits, status = run_megno(
            m_star=m_star,
            planets=masked_planets,
            test_a=test_a,
            test_m_solar=test_m_solar,
            fast=True,
            seed=42,
        )
        
        assert is_stable is True, f"Masked planet e niche must be dynamically stable (status={status}, megno={megno})"
        assert megno <= 2.5, f"MEGNO {megno} must indicate quasi-periodic regular motion"

    def test_close_in_instability_rejection(self):
        """
        Verify that placing a test particle too close to a major planet produces dynamical overlap
        inside the mutual Hill sphere (violating Gladman stability).
        """
        m_star = 1.0
        p_jupiter_m = 1.0e-3
        p_jupiter_a = 1.0
        test_a = 1.01  # Too close to Jupiter (inside Hill sphere)
        test_m_solar = 1.0 * M_EARTH_TO_SOLAR

        r_h = mutual_hill_radius(p_jupiter_a, p_jupiter_m, test_a, test_m_solar, m_star)
        d = abs(test_a - p_jupiter_a) / r_h
        # Must fail Gladman stability threshold (< 3.46 mutual Hill radii)
        assert d < 3.46, f"Separation d={d:.2f} inside Hill sphere must fail Gladman stability criterion"
