"""
modules/habitable_zone.py

Scientifically rigorous habitable-zone (HZ) assessment module.
Implements the temperature-dependent incident stellar flux parameterisation
from Kopparapu et al. (2013, 2014).

References:
  - Kopparapu, R. K., Ramirez, R., Kasting, J. F., et al. (2013).
    "Habitable Zones Around Main-Sequence Stars: New Estimates."
    The Astrophysical Journal, 765(2), 131. doi:10.1088/0004-637X/765/2/131
  - Kopparapu, R. K., Ramirez, R. M., SchottelKotte, J., et al. (2014).
    "Habitable Zones Around Main-Sequence Stars: Dependence on Planetary Mass."
    The Astrophysical Journal Letters, 787(2), L29. doi:10.1088/2041-8205/787/2/L29

Scientific Principles:
  1. Habitable-zone membership is a necessary but far from sufficient condition
     for planetary habitability; it refers solely to the circumstellar region
     where liquid water could theoretically be sustained on a rocky planet with
     a suitable atmosphere (Kopparapu et al. 2013).
  2. Incident stellar flux (S_eff = L_* / a^2) is used rather than equilibrium
     temperature to avoid implicit, unverified albedo and emissivity assumptions.
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
  6. Observational uncertainties are propagated via analytical error propagation
     and Monte Carlo sampling to compute membership probabilities. When input
     uncertainties are absent, probabilities are marked uncalculable rather than
     manufactured.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
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
    # Incident stellar flux (S_eff = L_* / a^2)
    incident_stellar_flux: Optional[float]
    incident_stellar_flux_err: Optional[float]
    flux_relative_to_earth: Optional[float]

    # Stellar luminosity context
    luminosity_solar: Optional[float]
    luminosity_source: str  # "catalog", "derived", or "unavailable"
    luminosity_err: Optional[float]

    # Discrete classification
    conservative_hz: bool
    optimistic_hz: bool
    hz_classification: str  # "conservative", "optimistic", "too_hot", "too_cold", "unknown"

    # Probabilistic assessment (when input uncertainties exist)
    prob_conservative: Optional[float]
    prob_optimistic: Optional[float]
    probability_calculable: bool

    # Calculated boundaries
    boundaries: Optional[Dict[str, Any]]
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
    luminosity_err: Optional[float] = None,
    semi_major_axis_err: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Computes incident stellar flux: S_eff = L_* / a^2 (relative to Earth).
    Propagates uncertainty if available:
        (sigma_S / S_eff)^2 = (sigma_L / L_*)^2 + (2 * sigma_a / a)^2
    """
    if luminosity_solar is None or semi_major_axis_au is None:
        return None, None
    if luminosity_solar <= 0 or semi_major_axis_au <= 0:
        return None, None

    s_eff = float(luminosity_solar / (semi_major_axis_au ** 2.0))

    s_eff_err = None
    if luminosity_err is not None and semi_major_axis_err is not None:
        if luminosity_err >= 0 and semi_major_axis_err >= 0:
            rel_l = luminosity_err / luminosity_solar
            rel_a = semi_major_axis_err / semi_major_axis_au
            rel_s = math.sqrt(rel_l ** 2.0 + (2.0 * rel_a) ** 2.0)
            s_eff_err = float(s_eff * rel_s)
    elif luminosity_err is not None and luminosity_err >= 0:
        rel_l = luminosity_err / luminosity_solar
        s_eff_err = float(s_eff * rel_l)
    elif semi_major_axis_err is not None and semi_major_axis_err >= 0:
        rel_a = semi_major_axis_err / semi_major_axis_au
        s_eff_err = float(s_eff * (2.0 * rel_a))

    return s_eff, s_eff_err


def compute_kopparapu_boundaries(
    teff_k: Optional[float],
    luminosity_solar: Optional[float] = None,
) -> HZBoundaries:
    """
    Calculates temperature-dependent HZ flux and distance boundaries
    using Kopparapu et al. (2013, 2014) polynomial parameterisation.

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
    semi_major_axis_err: Optional[float] = None,
    luminosity_err: Optional[float] = None,
    radius_err: Optional[float] = None,
    teff_err: Optional[float] = None,
    n_mc_samples: int = 2000,
    random_seed: Optional[int] = 42,
) -> HabitableZoneAssessment:
    """
    Performs full scientific habitable zone assessment:
    - Resolves stellar luminosity and records provenance
    - Calculates incident stellar flux S_eff and uncertainty
    - Evaluates temperature-dependent Kopparapu conservative & optimistic boundaries
    - Performs Monte Carlo uncertainty propagation when observational errors exist
    - Removes any midpoint/distance scoring rewards
    """
    warnings: List[str] = []
    scientific_notes: List[str] = [
        "Habitable-zone membership defines incident stellar flux limits where liquid surface water "
        "could theoretically exist; it does not confirm habitability, atmosphere presence, or surface water."
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

    # 2. Compute incident stellar flux
    s_eff, s_eff_err = calculate_incident_flux(
        luminosity_solar=lum_val,
        semi_major_axis_au=semi_major_axis_au,
        luminosity_err=lum_err_val,
        semi_major_axis_err=semi_major_axis_err,
    )

    if s_eff is None:
        warnings.append("Incident stellar flux cannot be computed (missing semi-major axis or luminosity).")

    # 3. Compute Kopparapu boundaries
    bounds = compute_kopparapu_boundaries(teff_k=teff_k, luminosity_solar=lum_val)
    warnings.extend(bounds.warnings)

    # 4. Classify based on deterministic flux
    conservative_hz = False
    optimistic_hz = False
    hz_classification = "unknown"

    if s_eff is not None and bounds.is_valid_range:
        s_inner_cons = bounds.s_eff_runaway_greenhouse
        s_outer_cons = bounds.s_eff_maximum_greenhouse
        s_inner_opt = bounds.s_eff_recent_venus
        s_outer_opt = bounds.s_eff_early_mars

        if s_inner_cons is not None and s_outer_cons is not None:
            # Note: flux decreases outward; outer boundary has smaller S_eff than inner boundary
            if s_outer_cons <= s_eff <= s_inner_cons:
                conservative_hz = True
                optimistic_hz = True  # Conservative is a subset of optimistic
                hz_classification = "conservative"
            elif s_inner_opt is not None and s_outer_opt is not None and (s_outer_opt <= s_eff <= s_inner_opt):
                optimistic_hz = True
                hz_classification = "optimistic"
            elif s_inner_opt is not None and s_eff > s_inner_opt:
                hz_classification = "too_hot"
            elif s_outer_opt is not None and s_eff < s_outer_opt:
                hz_classification = "too_cold"
    elif s_eff is not None and not bounds.is_valid_range:
        hz_classification = "unknown"
        warnings.append("HZ classification marked unknown due to invalid stellar Teff range.")

    # 5. Monte Carlo error propagation for membership probabilities
    prob_conservative: Optional[float] = None
    prob_optimistic: Optional[float] = None
    probability_calculable = False

    has_orbit_unc = semi_major_axis_err is not None and semi_major_axis_err > 0
    has_lum_unc = lum_err_val is not None and lum_err_val > 0
    can_mc = (
        s_eff is not None
        and bounds.is_valid_range
        and semi_major_axis_au is not None
        and lum_val is not None
        and (has_orbit_unc or has_lum_unc)
    )

    if can_mc:
        rng = np.random.default_rng(random_seed)
        a_sigma = float(semi_major_axis_err) if has_orbit_unc else 0.0
        l_sigma = float(lum_err_val) if has_lum_unc else 0.0
        t_sigma = float(teff_err) if (teff_err is not None and teff_err > 0) else 0.0

        a_draws = np.maximum(0.001, rng.normal(semi_major_axis_au, a_sigma, n_mc_samples)) if a_sigma > 0 else np.full(n_mc_samples, semi_major_axis_au)
        l_draws = np.maximum(1e-8, rng.normal(lum_val, l_sigma, n_mc_samples)) if l_sigma > 0 else np.full(n_mc_samples, lum_val)

        if t_sigma > 0 and teff_k is not None:
            t_draws = rng.normal(teff_k, t_sigma, n_mc_samples)
        else:
            t_draws = np.full(n_mc_samples, teff_k if teff_k is not None else 5780.0)

        s_draws = l_draws / (a_draws ** 2.0)

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
    else:
        if s_eff is not None:
            warnings.append("Observational uncertainties unavailable for orbit/star; HZ probabilities cannot be evaluated.")

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
        incident_stellar_flux=round(s_eff, 4) if s_eff is not None else None,
        incident_stellar_flux_err=round(s_eff_err, 4) if s_eff_err is not None else None,
        flux_relative_to_earth=round(s_eff, 4) if s_eff is not None else None,
        luminosity_solar=round(lum_val, 6) if lum_val is not None else None,
        luminosity_source=lum_source,
        luminosity_err=round(lum_err_val, 6) if lum_err_val is not None else None,
        conservative_hz=conservative_hz,
        optimistic_hz=optimistic_hz,
        hz_classification=hz_classification,
        prob_conservative=prob_conservative,
        prob_optimistic=prob_optimistic,
        probability_calculable=probability_calculable,
        boundaries=boundaries_dict,
        warnings=warnings,
        scientific_notes=scientific_notes,
    )
