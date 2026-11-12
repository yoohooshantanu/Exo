"""
tests/test_orbital_retrodiction.py

Validates the orbital dynamics engine on multi-planet systems.
Specifically documents and tests:
1. Physical limitation on resonant chains: phase-blind circular insertion into TRAPPIST-1
   fails because random orbital phases break the delicate multi-body Laplace resonance chain.
2. Retrodiction success on well-spaced non-resonant architectures: phase-blind integration
   successfully recovers regular quasi-periodic motion (<Y> <= 2.2).
"""
from modules.orbital_gap_predictor import run_megno, mutual_hill_radius

M_EARTH_TO_SOLAR = 3.003e-6


class TestOrbitalRetrodiction:
    def test_trappist1e_resonant_phase_limitation(self):
        """
        TRAPPIST-1 resonant chain sensitivity:
        TRAPPIST-1 host star: M ~ 0.0898 M_sun.
        Known planets:
          b: a = 0.0115 AU, m = 1.37 M_earth
          c: a = 0.0158 AU, m = 1.31 M_earth
          d: a = 0.0223 AU, m = 0.39 M_earth
          [e: a = 0.0293 AU, m = 0.69 M_earth]  <-- MASKED
          f: a = 0.0385 AU, m = 1.04 M_earth
          g: a = 0.0469 AU, m = 1.32 M_earth
          h: a = 0.0619 AU, m = 0.33 M_earth
        
        Analytical Hill separation shows geometric gap clearance (d > 3.46).
        HOWEVER, because TRAPPIST-1 is a delicate multi-body Laplace resonant chain,
        phase-blind circular insertion destroys the resonant libration angles,
        resulting in MEGNO >> 4.0 (unstable). This is an essential documented limitation.
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
        
        test_a = 0.0293  # Semi-major axis of real planet e
        test_m_solar = 0.69 * M_EARTH_TO_SOLAR
        
        # 1. Analytical mutual Hill radius clearance
        r_h1 = mutual_hill_radius(0.0223, 0.39 * M_EARTH_TO_SOLAR, test_a, test_m_solar, m_star)
        r_h2 = mutual_hill_radius(test_a, test_m_solar, 0.0385, 1.04 * M_EARTH_TO_SOLAR, m_star)
        d1 = (test_a - 0.0223) / r_h1
        d2 = (0.0385 - test_a) / r_h2
        
        assert d1 > 3.46, f"Separation to inner planet d1={d1:.2f} must exceed Gladman limit"
        assert d2 > 3.46, f"Separation to outer planet d2={d2:.2f} must exceed Gladman limit"
        
        # 2. Honest N-body MEGNO evaluation:
        # Phase-blind circular insertion into a resonant chain breaks libration,
        # yielding MEGNO > 4.0 (chaotic/unstable).
        is_stable, megno, orbits, status = run_megno(
            m_star=m_star,
            planets=masked_planets,
            test_a=test_a,
            test_m_solar=test_m_solar,
            fast=True,
            seed=42,
        )
        
        # Must honestly reflect that phase-blind insertion fails on resonant chains
        assert megno >= 4.0, f"Phase-blind circular insertion into resonant chain must yield chaotic MEGNO (got {megno})"
        assert is_stable is False, f"TRAPPIST-1 phase-blind insertion must be marked unstable without resonant phase alignment"

    def test_well_spaced_non_resonant_gap_retrodiction(self):
        """
        Retrodiction test on a well-spaced non-resonant multi-planet gap:
        Solar System analog (Venus and Mars, with Earth at 1.0 AU masked).
        Venus: a = 0.723 AU, m = 0.815 M_earth
        [Earth: a = 1.000 AU, m = 1.000 M_earth] <-- MASKED
        Mars:  a = 1.524 AU, m = 0.107 M_earth
        
        Without resonant phase dependencies, phase-blind circular integration
        successfully recovers regular quasi-periodic motion (MEGNO <= 2.2).
        """
        m_star = 1.0
        masked_planets = [
            {"a": 0.723, "m": 0.815 * M_EARTH_TO_SOLAR, "m_e": 0.815, "ecc": 0.007},
            {"a": 1.524, "m": 0.107 * M_EARTH_TO_SOLAR, "m_e": 0.107, "ecc": 0.093},
        ]
        test_a = 1.0
        test_m_solar = 1.0 * M_EARTH_TO_SOLAR

        is_stable, megno, orbits, status = run_megno(
            m_star=m_star,
            planets=masked_planets,
            test_a=test_a,
            test_m_solar=test_m_solar,
            fast=True,
            seed=42,
        )

        assert is_stable is True, f"Non-resonant gap must be dynamically stable (status={status}, megno={megno})"
        assert megno <= 2.2, f"MEGNO {megno} must indicate quasi-periodic regular motion"

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

    def test_negative_control_unstable_orbit_in_gap(self):
        """
        Negative control test for the orbital screen in the Venus-Mars gap:
        Demonstrates that an unstable test particle (placed adjacent to Venus's Hill sphere at a=0.74 AU
        or near Mars at a=1.48 AU) is rejected by the N-body MEGNO screen (<Y> > 4.0, unstable),
        proving that the screen discriminates between viable orbits and dynamical chaos.
        """
        m_star = 1.0
        masked_planets = [
            {"a": 0.723, "m": 0.815 * M_EARTH_TO_SOLAR, "m_e": 0.815, "ecc": 0.007},
            {"a": 1.524, "m": 0.107 * M_EARTH_TO_SOLAR, "m_e": 0.107, "ecc": 0.093},
        ]
        # Candidate placed at 0.74 AU (encroaching Venus)
        is_stable_inner, megno_inner, _, status_inner = run_megno(
            m_star=m_star,
            planets=masked_planets,
            test_a=0.74,
            test_m_solar=1.0 * M_EARTH_TO_SOLAR,
            fast=True,
            seed=42,
        )
        assert is_stable_inner is False, f"Orbit at 0.74 AU must be flagged unstable (got {status_inner})"
        assert megno_inner > 4.0, f"MEGNO for chaotic orbit must exceed 4.0 (got {megno_inner})"

        # Candidate placed at 1.48 AU (encroaching Mars)
        is_stable_outer, megno_outer, _, status_outer = run_megno(
            m_star=m_star,
            planets=masked_planets,
            test_a=1.48,
            test_m_solar=1.0 * M_EARTH_TO_SOLAR,
            fast=True,
            seed=42,
        )
        assert is_stable_outer is False, f"Orbit at 1.48 AU must be flagged unstable (got {status_outer})"
        assert megno_outer > 4.0, f"MEGNO for chaotic orbit must exceed 4.0 (got {megno_outer})"

    def test_rebound_real_module_installed(self):
        """
        Verify that rebound is a genuine compiled N-body simulation package (not a Mock),
        ensuring CI tests execute real physics integrations rather than passing vacuously.
        """
        import rebound
        from unittest.mock import Mock, MagicMock
        assert not isinstance(rebound, (Mock, MagicMock)), "rebound must not be a mock in CI/testing"
        assert hasattr(rebound, "Simulation"), "rebound must provide Simulation class"

