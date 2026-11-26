"""
modules/habitable_zone.py

Scientifically rigorous habitable-zone (HZ) assessment module.
Implements the temperature-dependent incident stellar flux parameterisation
from Kopparapu et al. (2013) for 1 Earth-mass planets, with orbital
eccentricity dynamics, Stefan-Boltzmann luminosity derivation, and correlated
Monte Carlo uncertainty propagation.

References:
  - Kopparapu, R. K., Ramirez, R., Kasting, J. F., et al. (2013).
    "Habitable Zones Around Main-Sequence Stars: New Estimates."
    The Astrophysical Journal, 765(2), 131. doi:10.1088/0004-637X/765/2/131
  - Kopparapu, R. K., Ramirez, R. M., SchottelKotte, J., et al. (2014).
    "Habitable Zones Around Main-Sequence Stars: Dependence on Planetary Mass."
    The Astrophysical Journal Letters, 787(2), L29. doi:10.1088/2041-8205/787/2/L29

Scientific Principles:
  1. Habitable-zone membership defines incident stellar flux limits where liquid
     surface water could theoretically exist; it does not confirm habitability,
     atmosphere presence, or surface water (Kopparapu et al. 2013).
  2. Incident stellar flux is calculated accounting for orbital eccentricity:
     - Orbit-averaged flux: <S_eff> = L_* / (a^2 * sqrt(1 - e^2))
     - Periastron flux: S_peri = L_* / (a^2 * (1 - e)^2)
     - Apastron flux: S_apo = L_* / (a^2 * (1 + e)^2)
     - Semi-major axis flux: S_semi = L_* / a^2 (preserved for circular baseline)
  3. Stellar luminosity is derived from stellar radius and effective temperature
     via the Stefan-Boltzmann relation when unavailable in catalogues, with full
     provenance tracking ("catalog", "derived", "unavailable"). Solar defaults
     are NEVER silently substituted.
  4. HZ boundaries depend strongly on stellar effective temperature (T_eff) due
     to wavelength-dependent Rayleigh scattering and greenhouse gas absorption.
     Silent extrapolation outside the published validity range [2600 K, 7200 K]
     is explicitly forbidden.
  5. Distance-based or midpoint-based scoring rewards are prohibited: planets
     are not inherently "more habitable" at the centre of the habitable zone.
  6. Observational uncertainties are propagated via correlated Monte Carlo sampling:
     when luminosity is derived, R_* and T_eff are sampled directly, preserving
     their physical covariance in L_*. For temperature distributions crossing
     model limits (>10% out of domain), probabilities are marked uncalculable.
  7. Planetary mass context: Calculations adopt the 1.0 M_earth reference atmosphere
     (Kopparapu et al. 2013 Table 3). Under Kopparapu et al. (2014), higher-mass
     planets experience runaway greenhouse at ~5% lower stellar flux, while
     sub-Earths (0.1 M_earth) can withstand ~4% higher flux before runaway.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union
import numpy as np

# Nominal Solar constants (IAU 2015 Resolution B3 / Prsa et al. 2016)
T_SUN_K = 5778.0           # Nominal solar effective temperature in Kelvin
KOPPARAPU_T_REF_K = 5780.0  # Kopparapu et al. (2013) parameterisation reference temperature

# Published Kopparapu applicability boundaries
TEFF_MIN_K = 2600.0
TEFF_MAX_K = 7200.0

# ── Kopparapu et al. (2013) Table 3 coefficients for 1 Earth-mass planet ──────
# Formula: S_eff = S_eff_sun + a*T_* + b*T_*^2 + c*T_*^3 + d*T_*^4
# where T_* = T_eff - 5780 K
KOPPARAPU_COEFFICIENTS: Dict[str, Dict[str, float]] = {
    "recent_venus": {
        "s_eff_sun": 1.7763,
        "a": 1.4335e-4,
        "b": 3.3954e-9,
        "c": -7.6364e-12,
        "d": -1.1950e-15,
        "description": "Optimistic inner boundary based on empirical recent Venus limit (~1 Ga)",
    },
    "runaway_greenhouse": {
        "s_eff_sun": 1.0385,
        "a": 1.2456e-4,
        "b": 1.4612e-8,
        "c": -9.2307e-12,
        "d": -2.2573e-15,
        "description": "Conservative inner boundary: runaway greenhouse limit for 1 M_earth",
    },
    "moist_greenhouse": {
        "s_eff_sun": 1.0140,
        "a": 8.1774e-5,
        "b": 1.7063e-9,
        "c": -4.3241e-12,
        "d": -6.6462e-16,
        "description": "Alternative conservative inner boundary: water-loss moist greenhouse limit",
    },
    "maximum_greenhouse": {
        "s_eff_sun": 0.3507,
        "a": 5.9578e-5,
        "b": 1.6707e-9,
        "c": -3.0058e-12,
        "d": -5.1925e-16,
        "description": "Conservative outer boundary: maximum CO2 greenhouse limit",
    },
    "early_mars": {
        "s_eff_sun": 0.3207,
        "a": 5.4471e-5,
        "b": 1.5275e-9,
        "c": -2.1709e-12,
        "d": -3.8282e-16,
        "description": "Optimistic outer boundary based on empirical early Mars warm climate (~3.8 Ga)",
    },
}


class IncidentFluxResult(NamedTuple):
    """
    Result container for incident stellar flux calculations.
    Subclasses NamedTuple with custom __iter__ to maintain 100% backward compatibility
    with callers unpacking `s_eff, s_eff_err = calculate_incident_flux(...)`.
    """
    flux_orbit_averaged: Optional[float]
    flux_orbit_averaged_err: Optional[float]
    flux_at_semi_major_axis: Optional[float] = None
    flux_at_semi_major_axis_err: Optional[float] = None
    flux_periastron: Optional[float] = None
    flux_apastron: Optional[float] = None
    is_circular_approximation: bool = True
    eccentricity: Optional[float] = None
    warnings: List[str] = []

    def __iter__(self):
        yield self.flux_orbit_averaged
        yield self.flux_orbit_averaged_err

    def __eq__(self, other):
        if isinstance(other, tuple) and len(other) == 2:
            return (self.flux_orbit_averaged, self.flux_orbit_averaged_err) == other
        return tuple.__eq__(self, other)


@dataclass
class StellarLuminosityResult:
    luminosity_solar: Optional[float]
    luminosity_source: str  # "catalog", "derived", or "unavailable"
    uncertainty_solar: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class HZBoundaries:
    teff_k: float
    is_valid_range: bool
    s_eff_recent_venus: Optional[float] = None       # Optimistic inner flux
    s_eff_runaway_greenhouse: Optional[float] = None # Conservative inner flux
    s_eff_moist_greenhouse: Optional[float] = None   # Alternative conservative inner flux
    s_eff_maximum_greenhouse: Optional[float] = None # Conservative outer flux
    s_eff_early_mars: Optional[float] = None         # Optimistic outer flux

    # Distance boundaries in AU (require stellar luminosity)
    dist_recent_venus_au: Optional[float] = None
    dist_runaway_greenhouse_au: Optional[float] = None
    dist_maximum_greenhouse_au: Optional[float] = None
    dist_early_mars_au: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class HabitableZoneAssessment:
    # Primary incident flux metrics
    incident_stellar_flux: Optional[float]              # Orbit-averaged flux <S_eff> (or L/a^2 if circular)
    incident_stellar_flux_err: Optional[float]          # Propagated uncertainty
    flux_relative_to_earth: Optional[float]             # Matches incident_stellar_flux for backward compatibility
    flux_at_semi_major_axis: Optional[float] = None     # S_semi = L / a^2
    flux_periastron: Optional[float] = None             # S_peri = L / (a^2 * (1 - e)^2)
    flux_apastron: Optional[float] = None               # S_apo = L / (a^2 * (1 + e)^2)
    eccentricity: Optional[float] = None                # Orbital eccentricity
    is_circular_approximation: bool = True              # True if e is None or e == 0

    # Stellar luminosity context
    luminosity_solar: Optional[float] = None
    luminosity_source: str = "unavailable"  # "catalog", "derived", or "unavailable"
    luminosity_err: Optional[float] = None

    # Discrete classification
    conservative_hz: bool = False
    optimistic_hz: bool = False
    hz_classification: str = "unknown"  # "conservative", "optimistic", "too_hot", "too_cold", "unknown"

    # Probabilistic assessment (when input uncertainties exist and domain is valid)
    prob_conservative: Optional[float] = None
    prob_optimistic: Optional[float] = None
    probability_calculable: bool = False
    valid_draw_fraction: float = 1.0
    invalid_draw_fraction: float = 0.0
    is_conditional_probability: bool = False
    domain_crossing_heuristic_threshold: float = 0.10
    sampling_assumptions: Dict[str, Any] = field(default_factory=dict)

    # Planetary mass reference context
    reference_mass_earth: float = 1.0
    mass_reference_note: str = (
        "Boundary fluxes adopt the 1.0 M_earth reference atmosphere (Kopparapu et al. 2013 Table 3). "
        "Under Kopparapu et al. (2014), higher-mass planets (~5 M_earth) experience runaway greenhouse "
        "at ~5% lower stellar flux, while sub-Earths (~0.1 M_earth) withstand ~4% higher flux."
    )

    # Calculated boundaries
    boundaries: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    scientific_notes: List[str] = field(default_factory=list)


def derive_stellar_luminosity(
    radius_solar: Optional[float],
    teff_k: Optional[float],
    radius_err: Optional[float] = None,
    teff_err: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Derives stellar luminosity from stellar radius and effective temperature
    using the Stefan-Boltzmann relation:
        L_* / L_sun = (R_* / R_sun)^2 * (T_eff / T_sun)^4
    
    Returns (luminosity_solar, uncertainty_solar).
    """
    if radius_solar is None or teff_k is None:
        return None, None
    if radius_solar <= 0 or teff_k <= 0:
        return None, None

    lum = float((radius_solar ** 2.0) * ((teff_k / T_SUN_K) ** 4.0))

    lum_err = None
    if radius_err is not None and teff_err is not None and radius_err >= 0 and teff_err >= 0:
        rel_r_err = radius_err / radius_solar
        rel_t_err = teff_err / teff_k
        rel_lum_err = math.sqrt((2.0 * rel_r_err) ** 2.0 + (4.0 * rel_t_err) ** 2.0)
        lum_err = float(lum * rel_lum_err)

    return lum, lum_err


def resolve_stellar_luminosity(
    luminosity_solar: Optional[float] = None,
    luminosity_log10: Optional[float] = None,
    radius_solar: Optional[float] = None,
    teff_k: Optional[float] = None,
    luminosity_err: Optional[float] = None,
    radius_err: Optional[float] = None,
    teff_err: Optional[float] = None,
) -> StellarLuminosityResult:
    """
    Determines stellar luminosity with strict provenance:
    1. If directly supplied linear luminosity > 0 -> "catalog"
    2. If supplied log10(L/L_sun) -> 10^lum_log -> "catalog"
    3. If radius and Teff are valid -> derived via Stefan-Boltzmann -> "derived"
    4. Otherwise -> "unavailable" (never defaults to solar 1.0).
    """
    warnings: List[str] = []

    # 1. Direct linear luminosity
    if luminosity_solar is not None and luminosity_solar > 0:
        return StellarLuminosityResult(
            luminosity_solar=float(luminosity_solar),
            luminosity_source="catalog",
            uncertainty_solar=float(luminosity_err) if luminosity_err is not None and luminosity_err >= 0 else None,
            warnings=warnings,
        )

    # 2. Log10 luminosity
    if luminosity_log10 is not None:
        try:
            lum_val = float(10.0 ** float(luminosity_log10))
            lum_err_val = None
            if luminosity_err is not None and luminosity_err >= 0:
                # d(10^x)/dx = ln(10) * 10^x
                lum_err_val = float(lum_val * math.log(10.0) * luminosity_err)
            return StellarLuminosityResult(
                luminosity_solar=lum_val,
                luminosity_source="catalog",
                uncertainty_solar=lum_err_val,
                warnings=warnings,
            )
        except (ValueError, OverflowError):
            warnings.append(f"Invalid log10 luminosity value: {luminosity_log10}")

    # 3. Derive from R_* and T_eff
    if radius_solar is not None and teff_k is not None:
        derived_lum, derived_err = derive_stellar_luminosity(
            radius_solar=radius_solar,
            teff_k=teff_k,
            radius_err=radius_err,
            teff_err=teff_err,
        )
        if derived_lum is not None:
            return StellarLuminosityResult(
                luminosity_solar=derived_lum,
                luminosity_source="derived",
                uncertainty_solar=derived_err,
                warnings=warnings,
            )

    # 4. Unavailable
    warnings.append("Stellar luminosity unavailable in catalog and cannot be derived (missing radius or Teff).")
    return StellarLuminosityResult(
        luminosity_solar=None,
        luminosity_source="unavailable",
        uncertainty_solar=None,
        warnings=warnings,
    )


def calculate_incident_flux(
    luminosity_solar: Optional[float],
    semi_major_axis_au: Optional[float],
    eccentricity: Optional[float] = None,
    luminosity_err: Optional[float] = None,
    semi_major_axis_err: Optional[float] = None,
    eccentricity_err: Optional[float] = None,
) -> IncidentFluxResult:
    """
    Computes incident stellar flux accounting for orbital eccentricity:
    - Orbit-averaged flux: <S_eff> = L_* / (a^2 * sqrt(1 - e^2))
    - Semi-major axis flux: S_semi = L_* / a^2
    - Periastron flux: S_peri = L_* / (a^2 * (1 - e)^2)
    - Apastron flux: S_apo = L_* / (a^2 * (1 + e)^2)

    Propagates uncertainty if available:
        (sigma_<S> / <S>)^2 = (sigma_L / L_*)^2 + (2 * sigma_a / a)^2 + (e * sigma_e / (1 - e^2))^2
    """
    warnings: List[str] = []
    if luminosity_solar is None or semi_major_axis_au is None:
        return IncidentFluxResult(None, None, warnings=warnings)
    if luminosity_solar <= 0 or semi_major_axis_au <= 0:
        return IncidentFluxResult(None, None, warnings=warnings)

    s_semi = float(luminosity_solar / (semi_major_axis_au ** 2.0))

    # Validate eccentricity
    ecc_val: Optional[float] = None
    is_circ = True
    if eccentricity is not None:
        if math.isnan(eccentricity) or eccentricity < 0.0 or eccentricity >= 1.0:
            warnings.append(
                f"Invalid orbital eccentricity {eccentricity}: must satisfy 0 <= e < 1 for bound orbits. "
                "Defaulting to circular orbit approximation."
            )
        else:
            ecc_val = float(eccentricity)
            is_circ = (ecc_val == 0.0)

    if ecc_val is not None and ecc_val > 0.0:
        geom_factor = math.sqrt(1.0 - (ecc_val ** 2.0))
        s_avg = float(s_semi / geom_factor)
        s_peri = float(s_semi / ((1.0 - ecc_val) ** 2.0))
        s_apo = float(s_semi / ((1.0 + ecc_val) ** 2.0))
    else:
        s_avg = s_semi
        s_peri = s_semi if ecc_val == 0.0 else None
        s_apo = s_semi if ecc_val == 0.0 else None

    # Error propagation for orbit-averaged flux
    s_avg_err: Optional[float] = None
    s_semi_err: Optional[float] = None

    rel_l = (luminosity_err / luminosity_solar) if (luminosity_err is not None and luminosity_err >= 0) else 0.0
    rel_a = (semi_major_axis_err / semi_major_axis_au) if (semi_major_axis_err is not None and semi_major_axis_err >= 0) else 0.0

    if ecc_val is not None and ecc_val > 0.0 and eccentricity_err is not None and eccentricity_err >= 0:
        denom = max(1e-4, 1.0 - (ecc_val ** 2.0))
        rel_e = (ecc_val * eccentricity_err) / denom
    else:
        rel_e = 0.0

    has_any_unc = (luminosity_err is not None) or (semi_major_axis_err is not None) or (rel_e > 0.0)
    if has_any_unc:
        rel_s_semi = math.sqrt((rel_l ** 2.0) + (4.0 * (rel_a ** 2.0)))
        rel_s_avg = math.sqrt((rel_l ** 2.0) + (4.0 * (rel_a ** 2.0)) + (rel_e ** 2.0))
        s_semi_err = float(s_semi * rel_s_semi) if rel_s_semi > 0 else None
        s_avg_err = float(s_avg * rel_s_avg) if rel_s_avg > 0 else None

    return IncidentFluxResult(
        flux_orbit_averaged=s_avg,
        flux_orbit_averaged_err=s_avg_err,
        flux_at_semi_major_axis=s_semi,
        flux_at_semi_major_axis_err=s_semi_err,
        flux_periastron=s_peri,
        flux_apastron=s_apo,
        is_circular_approximation=is_circ,
        eccentricity=ecc_val,
        warnings=warnings,
    )


def compute_kopparapu_boundaries(
    teff_k: Optional[float],
    luminosity_solar: Optional[float] = None,
) -> HZBoundaries:
    """
    Calculates temperature-dependent HZ flux and distance boundaries
    using Kopparapu et al. (2013, 2014) polynomial parameterisation for 1 M_earth.

    Strictly validates that Teff is within [2600 K, 7200 K].
    Does NOT extrapolate outside this range.
    """
    warnings: List[str] = []
    if teff_k is None:
        warnings.append("Stellar effective temperature Teff is missing; HZ boundaries cannot be computed.")
        return HZBoundaries(teff_k=0.0, is_valid_range=False, warnings=warnings)

    if teff_k < TEFF_MIN_K or teff_k > TEFF_MAX_K:
        warnings.append(
            f"Stellar effective temperature {teff_k:.1f} K is outside the published Kopparapu validity range "
            f"[{TEFF_MIN_K:.0f} K, {TEFF_MAX_K:.0f} K]. Silent extrapolation is forbidden."
        )
        return HZBoundaries(teff_k=float(teff_k), is_valid_range=False, warnings=warnings)

    t_star = teff_k - KOPPARAPU_T_REF_K
    flux_bounds: Dict[str, float] = {}

    for key, c in KOPPARAPU_COEFFICIENTS.items():
        s_val = (
            c["s_eff_sun"]
            + c["a"] * t_star
            + c["b"] * (t_star ** 2.0)
            + c["c"] * (t_star ** 3.0)
            + c["d"] * (t_star ** 4.0)
        )
        flux_bounds[key] = float(max(1e-4, s_val))

    # Calculate distance boundaries in AU if luminosity is provided
    dist_bounds: Dict[str, Optional[float]] = {}
    if luminosity_solar is not None and luminosity_solar > 0:
        for key, s_val in flux_bounds.items():
            dist_bounds[key] = float(math.sqrt(luminosity_solar / s_val))
    else:
        for key in flux_bounds:
            dist_bounds[key] = None

    return HZBoundaries(
        teff_k=float(teff_k),
        is_valid_range=True,
        s_eff_recent_venus=flux_bounds["recent_venus"],
        s_eff_runaway_greenhouse=flux_bounds["runaway_greenhouse"],
        s_eff_moist_greenhouse=flux_bounds["moist_greenhouse"],
        s_eff_maximum_greenhouse=flux_bounds["maximum_greenhouse"],
        s_eff_early_mars=flux_bounds["early_mars"],
        dist_recent_venus_au=dist_bounds.get("recent_venus"),
        dist_runaway_greenhouse_au=dist_bounds.get("runaway_greenhouse"),
        dist_maximum_greenhouse_au=dist_bounds.get("maximum_greenhouse"),
        dist_early_mars_au=dist_bounds.get("early_mars"),
        warnings=warnings,
    )


def assess_habitable_zone(
    semi_major_axis_au: Optional[float],
    luminosity_solar: Optional[float] = None,
    luminosity_log10: Optional[float] = None,
    radius_solar: Optional[float] = None,
    teff_k: Optional[float] = None,
    eccentricity: Optional[float] = None,
    semi_major_axis_err: Optional[float] = None,
    luminosity_err: Optional[float] = None,
    radius_err: Optional[float] = None,
    teff_err: Optional[float] = None,
    eccentricity_err: Optional[float] = None,
    n_mc_samples: int = 2000,
    random_seed: Optional[int] = 42,
) -> HabitableZoneAssessment:
    """
    Performs full scientific habitable zone assessment:
    - Resolves stellar luminosity and records provenance (never defaults to solar)
    - Calculates incident stellar flux <S_eff> accounting for orbital eccentricity
    - Evaluates temperature-dependent Kopparapu conservative & optimistic boundaries
    - Performs correlated Monte Carlo uncertainty propagation when observational errors exist
    - Prevents arbitrary midpoint/distance scoring rewards
    - Tracks and reports model domain crossings (>10% invalid draws invalidates probability)
    """
    warnings: List[str] = []
    scientific_notes: List[str] = [
        "Habitable-zone membership defines incident stellar flux limits where liquid surface water "
        "could theoretically exist; it does not confirm habitability, atmosphere presence, or surface water.",
        "Primary classification uses annual orbit-averaged stellar flux <S_eff> = L_* / (a^2 * sqrt(1 - e^2)).",
    ]

    # 1. Resolve stellar luminosity
    lum_res = resolve_stellar_luminosity(
        luminosity_solar=luminosity_solar,
        luminosity_log10=luminosity_log10,
        radius_solar=radius_solar,
        teff_k=teff_k,
        luminosity_err=luminosity_err,
        radius_err=radius_err,
        teff_err=teff_err,
    )
    warnings.extend(lum_res.warnings)

    lum_val = lum_res.luminosity_solar
    lum_source = lum_res.luminosity_source
    lum_err_val = lum_res.uncertainty_solar

    # 2. Compute incident stellar flux (including eccentricity)
    flux_res = calculate_incident_flux(
        luminosity_solar=lum_val,
        semi_major_axis_au=semi_major_axis_au,
        eccentricity=eccentricity,
        luminosity_err=lum_err_val,
        semi_major_axis_err=semi_major_axis_err,
        eccentricity_err=eccentricity_err,
    )
    warnings.extend(flux_res.warnings)

    s_avg = flux_res.flux_orbit_averaged
    s_avg_err = flux_res.flux_orbit_averaged_err
    s_semi = flux_res.flux_at_semi_major_axis
    s_peri = flux_res.flux_periastron
    s_apo = flux_res.flux_apastron
    is_circ = flux_res.is_circular_approximation

    if s_avg is None:
        warnings.append("Incident stellar flux cannot be computed (missing semi-major axis or luminosity).")

    # 3. Compute Kopparapu boundaries
    bounds = compute_kopparapu_boundaries(teff_k=teff_k, luminosity_solar=lum_val)
    warnings.extend(bounds.warnings)

    # 4. Classify based on deterministic orbit-averaged flux
    conservative_hz = False
    optimistic_hz = False
    hz_classification = "unknown"

    if s_avg is not None and bounds.is_valid_range:
        s_inner_cons = bounds.s_eff_runaway_greenhouse
        s_outer_cons = bounds.s_eff_maximum_greenhouse
        s_inner_opt = bounds.s_eff_recent_venus
        s_outer_opt = bounds.s_eff_early_mars

        if s_inner_cons is not None and s_outer_cons is not None:
            # Note: flux decreases outward; outer boundary has smaller S_eff than inner boundary
            if s_outer_cons <= s_avg <= s_inner_cons:
                conservative_hz = True
                optimistic_hz = True  # Conservative is a subset of optimistic
                hz_classification = "conservative"
            elif s_inner_opt is not None and s_outer_opt is not None and (s_outer_opt <= s_avg <= s_inner_opt):
                optimistic_hz = True
                hz_classification = "optimistic"
            elif s_inner_opt is not None and s_avg > s_inner_opt:
                hz_classification = "too_hot"
            elif s_outer_opt is not None and s_avg < s_outer_opt:
                hz_classification = "too_cold"

        # Check orbital flux excursion (periastron/apastron crossing)
        if s_peri is not None and s_inner_cons is not None and s_peri > s_inner_cons and conservative_hz:
            warnings.append(
                f"Orbital excursion: While orbit-averaged flux ({s_avg:.2f} S_earth) is inside conservative HZ, "
                f"periastron flux ({s_peri:.2f} S_earth) exceeds runaway greenhouse boundary ({s_inner_cons:.2f} S_earth)."
            )
        if s_apo is not None and s_outer_cons is not None and s_apo < s_outer_cons and conservative_hz:
            warnings.append(
                f"Orbital excursion: While orbit-averaged flux ({s_avg:.2f} S_earth) is inside conservative HZ, "
                f"apastron flux ({s_apo:.2f} S_earth) drops below maximum greenhouse boundary ({s_outer_cons:.2f} S_earth)."
            )

    elif s_avg is not None and not bounds.is_valid_range:
        hz_classification = "unknown"
        warnings.append("HZ classification marked unknown due to invalid stellar Teff range.")

    # 5. Correlated Monte Carlo error propagation for membership probabilities
    prob_conservative: Optional[float] = None
    prob_optimistic: Optional[float] = None
    probability_calculable = False
    valid_draw_fraction = 1.0
    invalid_draw_fraction = 0.0
    is_conditional_probability = False
    domain_crossing_threshold = 0.10

    sampling_assumptions = {
        "stellar_parameter_covariance": "uncorrelated_independent_sampling",
        "covariance_note": "Stellar radius and effective temperature errors are sampled independently; observational covariance is not modeled.",
        "asymmetric_uncertainties": "unsupported (symmetric 1-sigma Gaussian assumed)",
        "domain_crossing_threshold": domain_crossing_threshold,
        "domain_crossing_note": "10% cutoff is an empirical engineering heuristic; evaluated probabilities are conditional on Teff within published Kopparapu range [2600 K, 7200 K].",
        "conditional_domain_k": [TEFF_MIN_K, TEFF_MAX_K],
    }

    has_orbit_unc = semi_major_axis_err is not None and semi_major_axis_err > 0
    has_lum_unc = lum_err_val is not None and lum_err_val > 0
    has_teff_unc = teff_err is not None and teff_err > 0
    has_rad_unc = radius_err is not None and radius_err > 0
    has_ecc_unc = eccentricity_err is not None and eccentricity_err > 0

    can_mc = (
        s_avg is not None
        and bounds.is_valid_range
        and semi_major_axis_au is not None
        and (has_orbit_unc or has_lum_unc or (lum_source == "derived" and (has_rad_unc or has_teff_unc)))
    )

    if can_mc:
        rng = np.random.default_rng(random_seed)
        a_sigma = float(semi_major_axis_err) if has_orbit_unc else 0.0
        e_sigma = float(eccentricity_err) if has_ecc_unc else 0.0
        ecc_base = flux_res.eccentricity if flux_res.eccentricity is not None else 0.0

        # Positive-valued semi-major axis draws
        a_draws = np.maximum(0.001, rng.normal(semi_major_axis_au, a_sigma, n_mc_samples)) if a_sigma > 0 else np.full(n_mc_samples, semi_major_axis_au)

        # Eccentricity draws constrained to physical bound Keplerian range [0, 0.99]
        if e_sigma > 0:
            e_draws = np.clip(rng.normal(ecc_base, e_sigma, n_mc_samples), 0.0, 0.99)
        else:
            e_draws = np.full(n_mc_samples, ecc_base)

        # ── Correlated Stellar Parameter Sampling ───────────────────────────
        if lum_source == "derived" and radius_solar is not None and teff_k is not None:
            # Physical correlation: sample R_* and T_eff independently, then derive L_* per draw!
            r_sigma = float(radius_err) if has_rad_unc else 0.0
            t_sigma = float(teff_err) if has_teff_unc else 0.0

            r_draws = np.maximum(0.001, rng.normal(radius_solar, r_sigma, n_mc_samples)) if r_sigma > 0 else np.full(n_mc_samples, radius_solar)
            t_draws = np.maximum(100.0, rng.normal(teff_k, t_sigma, n_mc_samples)) if t_sigma > 0 else np.full(n_mc_samples, teff_k)
            l_draws = (r_draws ** 2.0) * ((t_draws / T_SUN_K) ** 4.0)
        else:
            # Catalog luminosity: sample L directly
            l_sigma = float(lum_err_val) if has_lum_unc else 0.0
            t_sigma = float(teff_err) if has_teff_unc else 0.0

            l_draws = np.maximum(1e-8, rng.normal(lum_val, l_sigma, n_mc_samples)) if l_sigma > 0 else np.full(n_mc_samples, lum_val)
            t_draws = np.maximum(100.0, rng.normal(teff_k, t_sigma, n_mc_samples)) if (t_sigma > 0 and teff_k is not None) else np.full(n_mc_samples, teff_k if teff_k is not None else 0.0)

        # Orbit-averaged flux per draw
        geom_factors = np.sqrt(np.maximum(0.01, 1.0 - (e_draws ** 2.0)))
        s_draws = l_draws / ((a_draws ** 2.0) * geom_factors)

        # ── Track Model Domain Crossings ─────────────────────────────────────
        out_of_domain = (t_draws < TEFF_MIN_K) | (t_draws > TEFF_MAX_K)
        out_of_domain_count = int(np.sum(out_of_domain))
        invalid_draw_fraction = round(float(out_of_domain_count / n_mc_samples), 4)
        valid_draw_fraction = round(float(1.0 - invalid_draw_fraction), 4)

        if invalid_draw_fraction > domain_crossing_threshold:
            probability_calculable = False
            prob_conservative = None
            prob_optimistic = None
            warnings.append(
                f"{invalid_draw_fraction * 100:.1f}% of stellar effective temperature Monte Carlo draws "
                f"fall outside published Kopparapu validity range [{TEFF_MIN_K:.0f} K, {TEFF_MAX_K:.0f} K] "
                f"(exceeds {domain_crossing_threshold * 100:.0f}% heuristic threshold); "
                f"HZ membership probabilities cannot be reliably evaluated."
            )
        else:
            in_cons_count = 0
            in_opt_count = 0
            valid_eval_count = 0

            for s_i, t_i in zip(s_draws, t_draws):
                if TEFF_MIN_K <= t_i <= TEFF_MAX_K:
                    t_star_i = t_i - KOPPARAPU_T_REF_K
                    c_rg = KOPPARAPU_COEFFICIENTS["runaway_greenhouse"]
                    s_rg = (c_rg["s_eff_sun"] + c_rg["a"] * t_star_i + c_rg["b"] * (t_star_i**2) + c_rg["c"] * (t_star_i**3) + c_rg["d"] * (t_star_i**4))

                    c_mg = KOPPARAPU_COEFFICIENTS["maximum_greenhouse"]
                    s_mg = (c_mg["s_eff_sun"] + c_mg["a"] * t_star_i + c_mg["b"] * (t_star_i**2) + c_mg["c"] * (t_star_i**3) + c_mg["d"] * (t_star_i**4))

                    c_rv = KOPPARAPU_COEFFICIENTS["recent_venus"]
                    s_rv = (c_rv["s_eff_sun"] + c_rv["a"] * t_star_i + c_rv["b"] * (t_star_i**2) + c_rv["c"] * (t_star_i**3) + c_rv["d"] * (t_star_i**4))

                    c_em = KOPPARAPU_COEFFICIENTS["early_mars"]
                    s_em = (c_em["s_eff_sun"] + c_em["a"] * t_star_i + c_em["b"] * (t_star_i**2) + c_em["c"] * (t_star_i**3) + c_em["d"] * (t_star_i**4))

                    valid_eval_count += 1
                    if s_mg <= s_i <= s_rg:
                        in_cons_count += 1
                        in_opt_count += 1
                    elif s_em <= s_i <= s_rv:
                        in_opt_count += 1

            if valid_eval_count > 0:
                prob_conservative = round(float(in_cons_count / valid_eval_count), 4)
                prob_optimistic = round(float(in_opt_count / valid_eval_count), 4)
                probability_calculable = True
                is_conditional_probability = True
    else:
        if s_avg is not None:
            warnings.append("Observational uncertainties unavailable for orbit/star; HZ probabilities cannot be evaluated.")

    scientific_notes = [
        "Incident flux calculations account for Keplerian orbital eccentricity via time-averaged flux <S_eff> = L_* / (a^2 * sqrt(1 - e^2)).",
        "Monte Carlo uncertainty propagation samples stellar radius and effective temperature independently without observational covariance. Asymmetric catalogue errors are treated as symmetric 1-sigma standard deviations.",
    ]
    if is_conditional_probability:
        scientific_notes.append(
            f"Calculated HZ membership probabilities are conditional on stellar Teff lying within the valid Kopparapu "
            f"parameterisation domain [{TEFF_MIN_K:.0f} K, {TEFF_MAX_K:.0f} K] (valid draw fraction: {valid_draw_fraction * 100:.1f}%)."
        )

    boundaries_dict = {
        "teff_k": bounds.teff_k,
        "is_valid_range": bounds.is_valid_range,
        "flux_limits": {
            "recent_venus": round(bounds.s_eff_recent_venus, 4) if bounds.s_eff_recent_venus else None,
            "runaway_greenhouse": round(bounds.s_eff_runaway_greenhouse, 4) if bounds.s_eff_runaway_greenhouse else None,
            "moist_greenhouse": round(bounds.s_eff_moist_greenhouse, 4) if bounds.s_eff_moist_greenhouse else None,
            "maximum_greenhouse": round(bounds.s_eff_maximum_greenhouse, 4) if bounds.s_eff_maximum_greenhouse else None,
            "early_mars": round(bounds.s_eff_early_mars, 4) if bounds.s_eff_early_mars else None,
        },
        "distance_limits_au": {
            "recent_venus": round(bounds.dist_recent_venus_au, 4) if bounds.dist_recent_venus_au else None,
            "runaway_greenhouse": round(bounds.dist_runaway_greenhouse_au, 4) if bounds.dist_runaway_greenhouse_au else None,
            "maximum_greenhouse": round(bounds.dist_maximum_greenhouse_au, 4) if bounds.dist_maximum_greenhouse_au else None,
            "early_mars": round(bounds.dist_early_mars_au, 4) if bounds.dist_early_mars_au else None,
        },
    }

    return HabitableZoneAssessment(
        incident_stellar_flux=round(s_avg, 4) if s_avg is not None else None,
        incident_stellar_flux_err=round(s_avg_err, 4) if s_avg_err is not None else None,
        flux_relative_to_earth=round(s_avg, 4) if s_avg is not None else None,
        flux_at_semi_major_axis=round(s_semi, 4) if s_semi is not None else None,
        flux_periastron=round(s_peri, 4) if s_peri is not None else None,
        flux_apastron=round(s_apo, 4) if s_apo is not None else None,
        eccentricity=flux_res.eccentricity,
        is_circular_approximation=is_circ,
        luminosity_solar=round(lum_val, 6) if lum_val is not None else None,
        luminosity_source=lum_source,
        luminosity_err=round(lum_err_val, 6) if lum_err_val is not None else None,
        conservative_hz=conservative_hz,
        optimistic_hz=optimistic_hz,
        hz_classification=hz_classification,
        prob_conservative=prob_conservative,
        prob_optimistic=prob_optimistic,
        probability_calculable=probability_calculable,
        valid_draw_fraction=valid_draw_fraction,
        invalid_draw_fraction=invalid_draw_fraction,
        is_conditional_probability=is_conditional_probability,
        domain_crossing_heuristic_threshold=domain_crossing_threshold,
        sampling_assumptions=sampling_assumptions,
        boundaries=boundaries_dict,
        warnings=warnings,
        scientific_notes=scientific_notes,
    )
