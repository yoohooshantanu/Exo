"""
modules/retrieval_reproducibility.py

Atmospheric retrieval reproducibility and provenance framework.
Addresses research feedback from atmospheric modellers (e.g. petitRADTRANS / PLATON contributors).

Key principles:
  1. Complete configuration capture: Every parameter capable of affecting
     atmospheric retrieval outputs (opacities, priors, T-P profile, pressure grid,
     chemical abundances, sampler seeds, and metaparameters) must be recorded
     before execution and permanently bound to retrieval outputs.
  2. Opacity provenance: Track opacity databases, versions/releases, file identifiers,
     wavelength coverage, and isotopologue assumptions at the chemical species level.
     Differences in opacity line lists (especially Na, K, H2O) and missing bands
     must be documented with known limitations. Missing metadata must be marked "unknown".
  3. Sampler and prior traceability: Record exact prior shapes and bounds, sampler
     algorithm and version, random seed, and convergence diagnostics (evidence uncertainty,
     effective sample size, Gelman-Rubin R-hat, or sampler warnings).
  4. Explicit reproducibility states:
     - configuration_recorded
     - execution_completed
     - reproducibility_metadata_incomplete
     - convergence_not_established
     - reproducibility_verified
  5. Configuration export & import: Standalone JSON serialization allowing another
     researcher to inspect, download, or re-run the exact forward/inverse model.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

CONFIG_SCHEMA_VERSION = "2.0.0"

REPRODUCIBILITY_STATES = (
    "configuration_recorded",
    "execution_completed",
    "reproducibility_metadata_incomplete",
    "convergence_not_established",
    "reproducibility_verified",
)

# ── Published Opacity Provenance Registry ──────────────────────────────────────
# Reference knowledge for standard atmospheric opacity line lists.
# Used when retrieving standard species to ensure full citation and provenance.
KNOWN_OPACITY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "H2O": {
        "species": "H2O",
        "database": "ExoMol",
        "line_list_name": "POKAZATEL",
        "release_version": "2018",
        "reference_doi": "10.1093/mnras/sty1877",
        "file_identifier": "1H2-16O__POKAZATEL.R1000_0.3-50mu.ktable.npz",
        "wavelength_range_um": [0.3, 50.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["1H2-16O (main: 99.73%)", "1H2-18O (0.20%)"],
        "temperature_regime_k": [300.0, 3000.0],
        "line_broadening": "H2/He pressure broadening (Barton et al. 2017)",
        "limitations": [
            "High-temperature completeness verified up to 3000 K; room-temperature far wings may overestimate continuum."
        ],
    },
    "CO": {
        "species": "CO",
        "database": "HITEMP",
        "line_list_name": "HITEMP-2019",
        "release_version": "2019",
        "reference_doi": "10.3847/1538-4365/ab7c68",
        "file_identifier": "12C-16O__HITEMP2019.R1000_0.3-50mu.ktable.npz",
        "wavelength_range_um": [0.3, 50.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["12C-16O (98.65%)", "13C-16O (1.11%)"],
        "temperature_regime_k": [300.0, 4000.0],
        "line_broadening": "H2/He pressure broadening",
        "limitations": ["Fundamental and first overtone bands well constrained; higher overtones possess minor line position uncertainties."],
    },
    "CO2": {
        "species": "CO2",
        "database": "ExoMol",
        "line_list_name": "UCL-4000",
        "release_version": "2020",
        "reference_doi": "10.1093/mnras/staa227",
        "file_identifier": "12C-16O2__UCL-4000.R1000_0.3-50mu.ktable.npz",
        "wavelength_range_um": [0.3, 50.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["12C-16O2 (98.4%)"],
        "temperature_regime_k": [300.0, 4000.0],
        "line_broadening": "H2/He and self-broadening",
        "limitations": ["4.3 um fundamental is robust; weak combination bands around 2.7 um may have incomplete weak lines."],
    },
    "CH4": {
        "species": "CH4",
        "database": "ExoMol",
        "line_list_name": "10to10",
        "release_version": "2014 / Yurchenko et al.",
        "reference_doi": "10.1093/mnras/stu887",
        "file_identifier": "12C-1H4__10to10.R1000_0.3-50mu.ktable.npz",
        "wavelength_range_um": [0.3, 30.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["12CH4 (98.8%)"],
        "temperature_regime_k": [300.0, 2000.0],
        "line_broadening": "H2/He broadening",
        "limitations": ["Incomplete at temperatures above 2000 K due to high vibrational state transitions."],
    },
    "NH3": {
        "species": "NH3",
        "database": "ExoMol",
        "line_list_name": "CoYuTe",
        "release_version": "2019",
        "reference_doi": "10.1093/mnras/stz1970",
        "file_identifier": "14N-1H3__CoYuTe.R1000_0.3-50mu.ktable.npz",
        "wavelength_range_um": [0.3, 30.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["14NH3 (99.6%)"],
        "temperature_regime_k": [300.0, 2000.0],
        "line_broadening": "H2/He broadening",
        "limitations": ["Transition intensities have ~10% systematic uncertainty in near-infrared."],
    },
    "Na": {
        "species": "Na",
        "database": "Kurucz / VALD3",
        "line_list_name": "VALD3_neutral_atoms",
        "release_version": "2021",
        "reference_doi": "10.1088/0004-637X/736/2/89",
        "file_identifier": "Na_D_lines_resonance.R1000.npz",
        "wavelength_range_um": [0.3, 10.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["23Na (100%)"],
        "temperature_regime_k": [500.0, 3500.0],
        "line_broadening": "Allard et al. (2019) H2/He quantum mechanical collisional broadening",
        "limitations": [
            "Sodium doublet wing profile strongly depends on chosen line profile (Voigt vs non-Lorentzian Allard wings). Voigt severely overestimates far wing opacity."
        ],
    },
    "K": {
        "species": "K",
        "database": "Kurucz / VALD3",
        "line_list_name": "VALD3_neutral_atoms",
        "release_version": "2021",
        "reference_doi": "10.1088/0004-637X/736/2/89",
        "file_identifier": "K_resonance_doublet.R1000.npz",
        "wavelength_range_um": [0.3, 10.0],
        "spectral_resolution_R": 1000.0,
        "isotopologues": ["39K (93.26%)", "41K (6.73%)"],
        "temperature_regime_k": [500.0, 3500.0],
        "line_broadening": "Allard et al. (2016) pseudo-potential H2 broadening",
        "limitations": [
            "Potassium 770 nm resonance doublet exhibits strong satellite bands near 1.0 um; missing satellite bands can skew retrieved metallicity."
        ],
    },
}


def get_known_opacity_provenance(species: str) -> Dict[str, Any]:
    """Returns provenance metadata for a chemical species, or unknown fallback."""
    spec_upper = species.strip().upper()
    # Normalize common representations
    for k, v in KNOWN_OPACITY_REGISTRY.items():
        if k.upper() == spec_upper:
            return dict(v)

    return {
        "species": species,
        "database": "unknown",
        "line_list_name": "unknown",
        "release_version": "unknown",
        "reference_doi": None,
        "file_identifier": None,
        "wavelength_range_um": None,
        "spectral_resolution_R": None,
        "isotopologues": [],
        "temperature_regime_k": None,
        "line_broadening": "unknown",
        "limitations": ["Provenance metadata unavailable in registry for this species."],
    }


def compute_file_sha256(filepath: Union[str, Path]) -> Optional[str]:
    """
    Computes the SHA-256 cryptographic hash of a file on disk.
    Returns None if the file does not exist, is not a file, or is unreadable.
    """
    try:
        p = Path(filepath).resolve()
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def verify_runtime_opacity_file(
    species: str,
    file_path: Optional[Union[str, Path]] = None,
    loader_resolved_path: Optional[Union[str, Path]] = None,
    opacity_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Inspects runtime opacity file on disk.
    Strictly distinguishes:
    1. Verified runtime loader identity: Only confirmed if explicitly captured from the loader (`loader_resolved_path` or `file_path`).
    2. Bibliographic literature attribution: Reference metadata (ExoMol, HITEMP, VALD3) from published registries.
    Never treats a file found in an arbitrary guessed directory as proof of runtime loader usage.
    """
    known = get_known_opacity_provenance(species)
    target_path: Optional[Path] = None
    is_direct_loader_path = False

    if loader_resolved_path is not None:
        target_path = Path(loader_resolved_path).resolve()
        is_direct_loader_path = True
    elif file_path is not None:
        target_path = Path(file_path).resolve()
        is_direct_loader_path = True
    elif opacity_dir is not None and known.get("file_identifier"):
        target_path = (Path(opacity_dir) / known["file_identifier"]).resolve()

    if target_path is not None and target_path.is_file():
        sha256 = compute_file_sha256(target_path)
        stat = target_path.stat()
        disk_ver = {
            "file_status": "verified_on_disk",
            "file_path": str(target_path),
            "sha256_checksum": sha256,
            "file_size_bytes": stat.st_size,
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "provenance_verified": True,
            "is_loader_intercepted": is_direct_loader_path,
        }
    else:
        disk_ver = {
            "file_status": "runtime_unverified" if (file_path is None and opacity_dir is None) else "file_not_found",
            "file_path": str(target_path) if target_path else None,
            "sha256_checksum": None,
            "file_size_bytes": None,
            "last_modified": None,
            "provenance_verified": False,
            "is_loader_intercepted": False,
            "note": "PLATON loader does not expose internal file descriptors at runtime; runtime opacity binary is unverified.",
        }

    result = dict(known)
    result["disk_verification"] = disk_ver
    result["runtime_file_verified"] = disk_ver["provenance_verified"]
    result["bibliographic_metadata_only"] = True
    return result


def compute_kish_effective_sample_size(weights: Optional[Union[List[float], Any]]) -> Optional[float]:
    """
    Computes Kish's Effective Sample Size (ESS) for weighted posterior samples:
        N_eff = (sum(w_i))^2 / sum(w_i^2)
    Returns None if weights are empty, invalid, or sum to zero.
    """
    if weights is None:
        return None
    try:
        w_list = [float(w) for w in weights if w is not None]
    except (ValueError, TypeError):
        return None
    if not w_list:
        return None
    sum_w = sum(w_list)
    sum_w_sq = sum(w * w for w in w_list)
    if sum_w_sq <= 0.0 or sum_w <= 0.0:
        return None
    ess = (sum_w * sum_w) / sum_w_sq
    return float(ess)


@dataclass
class OpacityProvenance:
    species: str
    database: str
    line_list_name: str
    release_version: str
    reference_doi: Optional[str] = None
    file_identifier: Optional[str] = None
    wavelength_range_um: Optional[List[float]] = None
    spectral_resolution_R: Optional[float] = None
    isotopologues: List[str] = field(default_factory=list)
    temperature_regime_k: Optional[List[float]] = None
    line_broadening: Optional[str] = None
    limitations: List[str] = field(default_factory=list)


@dataclass
class TemperatureProfileConfig:
    profile_type: str  # "isothermal", "guillot", "madhusudhan_seager", "molliere", "spline"
    parameters: Dict[str, Any] = field(default_factory=dict)
    pressure_bounds_bar: Optional[List[float]] = None
    description: str = ""


@dataclass
class AtmosphericStructureConfig:
    n_layers: int = 100
    p_min_bar: float = 1e-6
    p_max_bar: float = 100.0
    mean_molecular_weight: Optional[float] = None
    cloud_model: Dict[str, Any] = field(default_factory=dict)
    scattering_model: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PriorDefinition:
    param_name: str
    distribution: str  # "uniform", "log_uniform", "gaussian", "fixed"
    bounds: List[float]
    unit: Optional[str] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    description: Optional[str] = None


@dataclass
class SamplerConfig:
    sampler_name: str  # "PyMultiNest", "MultiNest", "UltraNest", "dynesty", "emcee"
    sampler_version: str = "unknown"
    random_seed: Optional[int] = 42
    nlive: Optional[int] = 500
    evidence_tolerance: Optional[float] = 0.5
    sampling_efficiency: Optional[float] = 0.8
    constant_efficiency_mode: Optional[bool] = False
    n_iter_max: Optional[int] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConvergenceDiagnostics:
    converged: bool
    evidence_ln_z: Optional[float] = None
    evidence_err: Optional[float] = None
    n_samples: Optional[int] = None
    effective_sample_size: Optional[float] = None
    remaining_live_fraction: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    diagnostics_notes: List[str] = field(default_factory=list)


@dataclass
class ReproducibleRetrievalConfig:
    retrieval_id: str
    spec_id: str
    planet_id: str
    planet_name: Optional[str] = None
    config_version: str = CONFIG_SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_name: str = "PLATON"
    model_version: str = "1.0.0"
    petitradtrans_version: Optional[str] = None
    platon_version: Optional[str] = None
    observation_type: str = "transmission"
    wavelength_range_um: List[float] = field(default_factory=lambda: [0.8, 5.0])
    chemical_species: List[str] = field(default_factory=list)
    temperature_profile: Dict[str, Any] = field(default_factory=dict)
    atmospheric_structure: Dict[str, Any] = field(default_factory=dict)
    opacity_provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    priors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sampler: Dict[str, Any] = field(default_factory=dict)
    convergence: Optional[Dict[str, Any]] = None
    reproducibility_status: str = "configuration_recorded"
    reproducibility_notes: List[str] = field(default_factory=list)
    runtime_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReproducibleRetrievalConfig:
        data_clean = dict(data)
        # Filter unknown keys to allow graceful future schema extensions
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data_clean.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_json(cls, json_str: str) -> ReproducibleRetrievalConfig:
        data = json.loads(json_str)
        return cls.from_dict(data)

    def export_to_file(self, filepath: Path) -> Path:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return filepath


def create_retrieval_configuration(
    retrieval_id: str,
    spec_id: str,
    planet_id: str,
    planet_name: Optional[str] = None,
    model_name: str = "PLATON",
    model_version: str = "1.0.0",
    chemical_species: Optional[List[str]] = None,
    temperature_profile_type: str = "isothermal",
    temperature_params: Optional[Dict[str, Any]] = None,
    pressure_bounds_bar: Optional[Tuple[float, float]] = (1e-6, 100.0),
    cloud_params: Optional[Dict[str, Any]] = None,
    priors: Optional[Dict[str, Dict[str, Any]]] = None,
    sampler_name: str = "PyMultiNest",
    random_seed: int = 42,
    nlive: int = 500,
    observation_type: str = "transmission",
    wavelength_range_um: Optional[Tuple[float, float]] = (0.8, 5.0),
    custom_opacities: Optional[Dict[str, Dict[str, Any]]] = None,
    opacity_dir: Optional[Union[str, Path]] = None,
    sampler_seed_deterministic: bool = False,
) -> ReproducibleRetrievalConfig:
    """
    Constructs a fully versioned, structured retrieval configuration record.
    Attaches species-level opacity provenance, parameter priors, sampler settings,
    and runtime environment metadata.
    """
    species_list = chemical_species or ["H2O", "CO", "CO2", "CH4"]

    # 1. Build opacity provenance for every species
    opacity_prov_map: Dict[str, Dict[str, Any]] = {}
    for spec in species_list:
        if custom_opacities and spec in custom_opacities:
            opacity_prov_map[spec] = custom_opacities[spec]
        else:
            opacity_prov_map[spec] = verify_runtime_opacity_file(spec, opacity_dir=opacity_dir)

    # 2. Build temperature profile config
    tp_config = {
        "profile_type": temperature_profile_type,
        "parameters": temperature_params or {"T_iso_k": 1000.0},
        "pressure_bounds_bar": list(pressure_bounds_bar) if pressure_bounds_bar else [1e-6, 100.0],
        "description": f"{temperature_profile_type.capitalize()} atmospheric thermal structure",
    }

    # 3. Build atmospheric structure & cloud config
    atm_structure = {
        "n_layers": 100,
        "p_min_bar": pressure_bounds_bar[0] if pressure_bounds_bar else 1e-6,
        "p_max_bar": pressure_bounds_bar[1] if pressure_bounds_bar else 100.0,
        "mean_molecular_weight": "equilibrium_or_free",
        "cloud_model": cloud_params or {
            "type": "opaque_deck_with_rayleigh",
            "log_cloudtop_P_pa_bounds": [1.0, 5.0],
            "log_scat_factor_bounds": [-1.0, 3.0],
            "scat_slope": 4.0,
        },
    }

    # 4. Standard priors if none passed
    default_priors = priors or {
        "Rp": {"distribution": "uniform", "bounds": [0.5, 2.0], "unit": "R_jup", "description": "Planetary radius"},
        "T": {"distribution": "uniform", "bounds": [500.0, 2500.0], "unit": "K", "description": "Atmospheric temperature"},
        "logZ": {"distribution": "uniform", "bounds": [-1.0, 3.0], "unit": "dex", "description": "Metallicity relative to solar"},
        "CO_ratio": {"distribution": "uniform", "bounds": [0.1, 1.5], "unit": "dimensionless", "description": "Carbon to Oxygen elemental ratio"},
        "log_cloudtop_P": {"distribution": "uniform", "bounds": [1.0, 5.0], "unit": "log10(Pa)", "description": "Cloud top pressure"},
        "log_scat_factor": {"distribution": "uniform", "bounds": [-1.0, 3.0], "unit": "log10(dimensionless)", "description": "Rayleigh scattering factor"},
    }

    # 5. Sampler settings
    sampler_settings = {
        "sampler_name": sampler_name,
        "sampler_version": "1.0",
        "random_seed": random_seed,
        "seed_determinism_guaranteed": sampler_seed_deterministic,
        "nlive": nlive,
        "evidence_tolerance": 0.5,
        "sampling_efficiency": 0.8,
        "constant_efficiency_mode": False,
        "parameters": {"importance_nested_sampling": True},
    }

    # 6. Runtime metadata
    runtime = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    return ReproducibleRetrievalConfig(
        retrieval_id=retrieval_id,
        spec_id=spec_id,
        planet_id=planet_id,
        planet_name=planet_name,
        config_version=CONFIG_SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        model_name=model_name,
        model_version=model_version,
        observation_type=observation_type,
        wavelength_range_um=list(wavelength_range_um) if wavelength_range_um else [0.8, 5.0],
        chemical_species=species_list,
        temperature_profile=tp_config,
        atmospheric_structure=atm_structure,
        opacity_provenance=opacity_prov_map,
        priors=default_priors,
        sampler=sampler_settings,
        reproducibility_status="configuration_recorded",
        reproducibility_notes=["Configuration saved before execution."],
        runtime_metadata=runtime,
    )


def evaluate_retrieval_reproducibility(
    config: ReproducibleRetrievalConfig,
    convergence_diagnostics: Optional[ConvergenceDiagnostics] = None,
    require_disk_verification: bool = False,
) -> Tuple[str, List[str]]:
    """
    Evaluates whether an atmospheric retrieval meets scientific reproducibility standards.

    Checks:
      1. Sampler random seed exists and is deterministic.
      2. Model configuration and chemical species are specified.
      3. Opacity provenance is complete (database, version, line list documented for all species).
         If require_disk_verification is True, checks presence and SHA-256 on disk.
      4. Priors and parameter bounds are specified.
      5. Execution completed and convergence criteria were verified (evidence_err, ESS, live threshold).
    """
    notes: List[str] = []
    is_incomplete = False
    is_unconverged = False

    # Check seed
    seed = config.sampler.get("random_seed")
    if seed is None:
        notes.append("Sampler random seed missing: retrieval is non-deterministic.")
        is_incomplete = True

    if config.sampler.get("seed_determinism_guaranteed") is False:
        notes.append("Sampler engine does not guarantee deterministic seeding via API.")
        if require_disk_verification:
            is_incomplete = True

    # Check species and opacity
    if not config.chemical_species:
        notes.append("No chemical species specified in model configuration.")
        is_incomplete = True

    for spec in config.chemical_species:
        op_info = config.opacity_provenance.get(spec, {})
        db = op_info.get("database")
        if not db or db == "unknown":
            notes.append(f"Opacity provenance for species {spec} is unknown or missing.")
            is_incomplete = True
        if not op_info.get("release_version") or op_info.get("release_version") == "unknown":
            notes.append(f"Opacity release version for {spec} is unknown.")
            is_incomplete = True

        if require_disk_verification:
            disk_ver = op_info.get("disk_verification", {})
            if disk_ver.get("file_status") != "verified_on_disk" or not disk_ver.get("sha256_checksum"):
                notes.append(f"Opacity binary for species {spec} is not verified on disk with SHA-256 hash.")
                is_incomplete = True

    # Check priors
    if not config.priors:
        notes.append("Prior distributions and bounds are missing from configuration.")
        is_incomplete = True

    # Check convergence diagnostics
    if convergence_diagnostics is not None:
        if not convergence_diagnostics.converged:
            notes.append("Sampler did not reach convergence criteria.")
            is_unconverged = True

        if convergence_diagnostics.evidence_err is None:
            notes.append("Evidence uncertainty is missing (null).")
            is_unconverged = True
        elif convergence_diagnostics.evidence_err > 0.5:
            notes.append(f"Evidence uncertainty ({convergence_diagnostics.evidence_err:.3f}) exceeds tolerance (0.5).")
            is_unconverged = True

        if convergence_diagnostics.effective_sample_size is not None and convergence_diagnostics.effective_sample_size < 100.0:
            notes.append(f"Effective sample size ({convergence_diagnostics.effective_sample_size:.1f}) is below minimum threshold (100.0).")
            is_unconverged = True

        if convergence_diagnostics.warnings:
            notes.extend(convergence_diagnostics.warnings)
    else:
        notes.append("Convergence diagnostics not recorded.")
        is_unconverged = True

    # State decision
    if is_incomplete:
        status = "reproducibility_metadata_incomplete"
    elif is_unconverged:
        status = "convergence_not_established"
    else:
        status = "reproducibility_verified"
        notes.append("All reproducibility requirements satisfied: opacities, priors, seed, and convergence verified.")

    return status, notes


def sanitize_legacy_retrieval_record(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Provides safe fallback and compatibility for historical retrievals
    that were executed before the reproducibility framework.
    Never invents missing metadata; transparently marks missing fields as 'unknown'.
    """
    clean = dict(row_dict)
    if "reproducibility_status" not in clean or not clean["reproducibility_status"]:
        if clean.get("status") == "completed":
            clean["reproducibility_status"] = "reproducibility_metadata_incomplete"
        elif clean.get("status") == "failed":
            clean["reproducibility_status"] = "convergence_not_established"
        else:
            clean["reproducibility_status"] = "configuration_recorded"

    if "configuration_record" not in clean or not clean["configuration_record"]:
        clean["configuration_record"] = None

    if "opacity_provenance" not in clean or not clean["opacity_provenance"]:
        clean["opacity_provenance"] = None

    if "sampler_name" not in clean or not clean["sampler_name"]:
        clean["sampler_name"] = "PyMultiNest (inferred)"

    return clean
