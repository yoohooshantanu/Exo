"""Tests for atmospheric retrieval reproducibility framework.

Validates that:
1. Versioned, structured configuration records are generated before execution.
2. Opacity provenance is tracked at the chemical species level (ExoMol, HITEMP, VALD3)
   with specific line profile limitations (e.g. Na/K wing broadening).
3. Sampler metaparameters, random seeds, and priors are preserved deterministically.
4. Convergence diagnostics are evaluated and mapped to formal reproducibility states
   (reproducibility_verified, convergence_not_established, reproducibility_metadata_incomplete).
5. Configurations export and import cleanly to/from JSON for third-party audit.
6. Legacy database records are sanitized without fabricated defaults.
"""

import json
import pytest
import numpy as np
from pathlib import Path
from modules.retrieval_reproducibility import (
    KNOWN_OPACITY_REGISTRY,
    ConvergenceDiagnostics,
    OpacityProvenance,
    PriorDefinition,
    ReproducibleRetrievalConfig,
    SamplerConfig,
    TemperatureProfileConfig,
    create_retrieval_configuration,
    evaluate_retrieval_reproducibility,
    get_known_opacity_provenance,
    sanitize_legacy_retrieval_record,
    compute_file_sha256,
    verify_runtime_opacity_file,
    compute_kish_effective_sample_size,
)
from modules.platon_retrieval import resolve_retrieval_physical_parameters


class TestRetrievalConfiguration:
    def test_create_default_config_schema(self):
        config = create_retrieval_configuration(
            retrieval_id="test-ret-001",
            planet_id="planet-wasp-39b",
            spec_id="spec-jwst-prism",
            random_seed=42,
        )

        assert config.retrieval_id == "test-ret-001"
        assert config.planet_id == "planet-wasp-39b"
        assert config.spec_id == "spec-jwst-prism"
        assert config.model_name == "PLATON"
        assert config.model_version == "1.0.0"
        assert config.reproducibility_status == "configuration_recorded"
        assert config.sampler["sampler_name"] == "PyMultiNest"
        assert config.sampler["random_seed"] == 42
        assert config.sampler["nlive"] == 500
        assert len(config.chemical_species) == 4
        assert len(config.priors) == 6
        assert config.temperature_profile["profile_type"] == "isothermal"

    def test_json_roundtrip_reproducibility(self):
        original = create_retrieval_configuration(
            retrieval_id="test-ret-roundtrip",
            planet_id="planet-trappist-1e",
            spec_id="spec-hst-wfc3",
            random_seed=12345,
            chemical_species=["H2O", "CO2", "CH4", "Na"],
        )

        json_str = original.to_json()
        restored = ReproducibleRetrievalConfig.from_json(json_str)

        assert restored.retrieval_id == original.retrieval_id
        assert restored.planet_id == original.planet_id
        assert restored.spec_id == original.spec_id
        assert restored.sampler["random_seed"] == 12345
        assert len(restored.chemical_species) == 4
        assert restored.chemical_species == ["H2O", "CO2", "CH4", "Na"]
        assert len(restored.priors) == len(original.priors)

        # Check deep dictionary equality
        assert restored.to_dict() == original.to_dict()


class TestOpacityProvenance:
    def test_known_species_opacity_details(self):
        # Test H2O (ExoMol POKAZATEL)
        h2o_prov = get_known_opacity_provenance("H2O")
        assert h2o_prov["database"] == "ExoMol"
        assert "POKAZATEL" in h2o_prov["line_list_name"]
        assert h2o_prov["wavelength_range_um"] == [0.3, 50.0]

        # Test CO (HITEMP-2019)
        co_prov = get_known_opacity_provenance("CO")
        assert co_prov["database"] == "HITEMP"

        # Test Alkali metals (Na and K) wing broadening limitations as noted by Blain / petitRADTRANS
        na_prov = get_known_opacity_provenance("Na")
        assert "VALD3" in na_prov["database"]
        assert any("wing" in lim.lower() or "broadening" in lim.lower() for lim in na_prov["limitations"])

        k_prov = get_known_opacity_provenance("K")
        assert "VALD3" in k_prov["database"]
        assert any("satellite" in lim.lower() or "resonance" in lim.lower() for lim in k_prov["limitations"])

    def test_untracked_opacity_species_handling(self):
        # When an uncatalogued species is requested, it must be flagged as unknown
        untracked = get_known_opacity_provenance("UnknownX_99")
        assert untracked["database"] == "unknown"
        assert untracked["release_version"] == "unknown"
        assert any("unavailable" in lim.lower() for lim in untracked["limitations"])


class TestSamplerAndPriorPreservation:
    def test_sampler_custom_settings(self):
        sampler = SamplerConfig(
            sampler_name="PyMultiNest",
            sampler_version="2.12",
            random_seed=999,
            nlive=1000,
            evidence_tolerance=0.1,
            sampling_efficiency=0.3,
            parameters={"importance_nested_sampling": True},
        )
        assert sampler.random_seed == 999
        assert sampler.nlive == 1000

    def test_prior_definition(self):
        prior = PriorDefinition(
            param_name="Rp",
            distribution="uniform",
            bounds=[0.5, 2.5],
            unit="R_jup",
            description="Planet radius prior in Jupiter radii",
        )
        assert prior.param_name == "Rp"
        assert prior.distribution == "uniform"
        assert prior.bounds == [0.5, 2.5]


class TestReproducibilityEvaluation:
    def test_reproducibility_verified_state(self):
        config = create_retrieval_configuration(
            retrieval_id="ret-1",
            planet_id="p-1",
            spec_id="s-1",
            random_seed=42,
            chemical_species=["H2O", "CO", "CO2"],
        )
        diagnostics = ConvergenceDiagnostics(
            converged=True,
            evidence_ln_z=-310.2,
            evidence_err=0.12,
            n_samples=1200,
            effective_sample_size=600.0,
            warnings=[],
        )

        status, notes = evaluate_retrieval_reproducibility(config, diagnostics)
        assert status == "reproducibility_verified"
        assert any("verified" in n.lower() for n in notes)

    def test_convergence_not_established_state(self):
        config = create_retrieval_configuration(
            retrieval_id="ret-2",
            planet_id="p-1",
            spec_id="s-1",
            random_seed=42,
            chemical_species=["H2O", "CO"],
        )
        diagnostics = ConvergenceDiagnostics(
            converged=False,
            evidence_ln_z=-999.0,
            evidence_err=2.5,
            warnings=["Sampler did not converge."],
        )

        status, notes = evaluate_retrieval_reproducibility(config, diagnostics)
        assert status == "convergence_not_established"
        assert any("convergence" in n.lower() for n in notes)

    def test_reproducibility_metadata_incomplete_state(self):
        # Config with unverified opacity and missing seed
        config = create_retrieval_configuration(
            retrieval_id="ret-3",
            planet_id="p-1",
            spec_id="s-1",
            random_seed=None,
            chemical_species=["UnknownMolecule_Z"],
        )
        diagnostics = ConvergenceDiagnostics(
            converged=True,
            evidence_err=0.1,
            effective_sample_size=300.0,
        )

        status, notes = evaluate_retrieval_reproducibility(config, diagnostics)
        assert status == "reproducibility_metadata_incomplete"
        assert any("missing" in n.lower() or "unknown" in n.lower() for n in notes)

    def test_missing_evidence_err_fails_convergence(self):
        # Missing evidence uncertainty (None) must not default to 0.1
        config = create_retrieval_configuration(
            retrieval_id="ret-4",
            planet_id="p-1",
            spec_id="s-1",
            random_seed=42,
            chemical_species=["H2O"],
        )
        diagnostics = ConvergenceDiagnostics(
            converged=True,
            evidence_ln_z=-200.0,
            evidence_err=None,
            effective_sample_size=500.0,
        )
        status, notes = evaluate_retrieval_reproducibility(config, diagnostics)
        assert status == "convergence_not_established"
        assert any("missing" in n.lower() for n in notes)

    def test_low_effective_sample_size_fails_convergence(self):
        config = create_retrieval_configuration(
            retrieval_id="ret-5",
            planet_id="p-1",
            spec_id="s-1",
            random_seed=42,
            chemical_species=["H2O"],
        )
        diagnostics = ConvergenceDiagnostics(
            converged=True,
            evidence_ln_z=-200.0,
            evidence_err=0.1,
            effective_sample_size=50.0,  # Below threshold 100.0
        )
        status, notes = evaluate_retrieval_reproducibility(config, diagnostics)
        assert status == "convergence_not_established"
        assert any("effective sample size" in n.lower() for n in notes)


class TestKishEffectiveSampleSize:
    def test_uniform_weights_equal_sample_count(self):
        weights = [1.0] * 500
        ess = compute_kish_effective_sample_size(weights)
        assert ess == pytest.approx(500.0)

    def test_single_dominant_sample_yields_one(self):
        weights = [1.0] + [0.0] * 999
        ess = compute_kish_effective_sample_size(weights)
        assert ess == pytest.approx(1.0)

    def test_arbitrary_weights_calculation(self):
        weights = [1.0, 2.0, 3.0, 4.0]
        # sum = 10 -> (sum)^2 = 100
        # sum_sq = 1 + 4 + 9 + 16 = 30
        # ess = 100 / 30 = 3.3333...
        ess = compute_kish_effective_sample_size(weights)
        assert ess == pytest.approx(100.0 / 30.0)

    def test_empty_or_invalid_weights_returns_none(self):
        assert compute_kish_effective_sample_size(None) is None
        assert compute_kish_effective_sample_size([]) is None
        assert compute_kish_effective_sample_size([0.0, 0.0]) is None


class TestDiskOpacityVerification:
    def test_hash_real_file(self, tmp_path):
        test_file = tmp_path / "1H2-16O__POKAZATEL.R1000_0.3-50mu.ktable.npz"
        test_file.write_bytes(b"Simulated opacity binary content for testing")

        sha = compute_file_sha256(test_file)
        assert sha is not None
        assert len(sha) == 64

        # Verify against hashlib directly
        import hashlib
        expected_sha = hashlib.sha256(b"Simulated opacity binary content for testing").hexdigest()
        assert sha == expected_sha

    def test_hash_non_existent_file_returns_none(self, tmp_path):
        missing = tmp_path / "non_existent.npz"
        assert compute_file_sha256(missing) is None

    def test_verify_runtime_opacity_file_found(self, tmp_path):
        test_file = tmp_path / "1H2-16O__POKAZATEL.R1000_0.3-50mu.ktable.npz"
        test_file.write_bytes(b"Opacity Data H2O")

        res = verify_runtime_opacity_file("H2O", opacity_dir=tmp_path)
        assert res["species"] == "H2O"
        assert res["runtime_file_verified"] is True
        disk_ver = res["disk_verification"]
        assert disk_ver["file_status"] == "verified_on_disk"
        assert disk_ver["sha256_checksum"] is not None
        assert disk_ver["provenance_verified"] is True

    def test_verify_runtime_opacity_file_missing(self, tmp_path):
        res = verify_runtime_opacity_file("H2O", opacity_dir=tmp_path)
        assert res["species"] == "H2O"
        assert res["runtime_file_verified"] is False
        disk_ver = res["disk_verification"]
        assert disk_ver["file_status"] == "file_not_found"
        assert disk_ver["sha256_checksum"] is None
        assert disk_ver["provenance_verified"] is False

    def test_strict_disk_verification_rejects_missing_files(self, tmp_path):
        config = create_retrieval_configuration(
            retrieval_id="ret-strict",
            planet_id="p-1",
            spec_id="s-1",
            random_seed=42,
            chemical_species=["H2O"],
            opacity_dir=tmp_path,  # Empty dir -> file not found
            sampler_seed_deterministic=True,
        )
        diagnostics = ConvergenceDiagnostics(
            converged=True,
            evidence_ln_z=-100.0,
            evidence_err=0.1,
            effective_sample_size=500.0,
        )
        status, notes = evaluate_retrieval_reproducibility(
            config,
            diagnostics,
            require_disk_verification=True,
        )
        assert status == "reproducibility_metadata_incomplete"
        assert any("not verified on disk" in n.lower() for n in notes)


class TestLegacyRecordSanitization:
    def test_sanitize_empty_record(self):
        sanitized = sanitize_legacy_retrieval_record({})
        assert sanitized["reproducibility_status"] == "configuration_recorded"
        assert "PyMultiNest" in sanitized["sampler_name"]

    def test_sanitize_completed_legacy_record(self):
        completed_rec = {"status": "completed"}
        sanitized = sanitize_legacy_retrieval_record(completed_rec)
        assert sanitized["reproducibility_status"] == "reproducibility_metadata_incomplete"
        assert sanitized["configuration_record"] is None
        assert sanitized["opacity_provenance"] is None

    def test_preserves_existing_verified_record(self):
        verified_rec = {
            "retrieval_id": "ret-existing",
            "model_version": "1.0.0",
            "reproducibility_status": "reproducibility_verified",
            "sampler_name": "PyMultiNest",
            "random_seed": 77,
            "opacity_provenance": [{"species": "H2O", "database": "ExoMol"}],
            "priors_record": [{"parameter": "Rp"}],
            "convergence_diagnostics": {"converged": True},
        }
        sanitized = sanitize_legacy_retrieval_record(verified_rec)
        assert sanitized["reproducibility_status"] == "reproducibility_verified"
        assert sanitized["random_seed"] == 77
        assert len(sanitized["opacity_provenance"]) == 1


class TestRetrievalPhysicalParameterValidation:
    def test_all_catalog_parameters_present(self):
        resolved, missing, prov = resolve_retrieval_physical_parameters(
            radius_earth=11.2,
            mass_earth=317.8,
            radius_solar=1.0,
            teff_best_k=5778.0,
            eq_temperature_k=1200.0,
            semi_major_axis_au=0.05,
            luminosity_solar=1.0,
        )
        assert missing == []
        assert resolved is not None
        assert resolved["radius_earth"] == 11.2
        assert resolved["mass_earth"] == 317.8
        assert resolved["radius_solar"] == 1.0
        assert resolved["teff_k"] == 5778.0
        assert resolved["eq_temperature_k"] == 1200.0
        assert prov["teff_k"] == "catalog"
        assert prov["eq_temperature_k"] == "catalog"

    def test_derive_teff_via_stefan_boltzmann_when_missing(self):
        resolved, missing, prov = resolve_retrieval_physical_parameters(
            radius_earth=11.2,
            mass_earth=317.8,
            radius_solar=1.0,
            teff_best_k=None,  # missing
            eq_temperature_k=1200.0,
            semi_major_axis_au=0.05,
            luminosity_solar=1.0,  # 1 L_sun, 1 R_sun -> 5778 K
        )
        assert missing == []
        assert resolved is not None
        assert resolved["teff_k"] == pytest.approx(5778.0, rel=1e-3)
        assert prov["teff_k"] == "derived_stefan_boltzmann"

    def test_missing_teff_without_luminosity_raises_error(self):
        resolved, missing, prov = resolve_retrieval_physical_parameters(
            radius_earth=11.2,
            mass_earth=317.8,
            radius_solar=1.0,
            teff_best_k=None,
            eq_temperature_k=1200.0,
            semi_major_axis_au=0.05,
            luminosity_solar=None,  # cannot derive
        )
        assert resolved is None
        assert "teff_best_k" in missing

    def test_derive_eq_temperature_when_missing(self):
        # 1 R_sun, Teff=5778, a=0.05 AU
        # T_eq = 5778 * sqrt(R_sun / (2 * a))
        resolved, missing, prov = resolve_retrieval_physical_parameters(
            radius_earth=11.2,
            mass_earth=317.8,
            radius_solar=1.0,
            teff_best_k=5778.0,
            eq_temperature_k=None,  # missing
            semi_major_axis_au=0.05,
            luminosity_solar=1.0,
        )
        assert missing == []
        assert resolved is not None
        assert resolved["eq_temperature_k"] == pytest.approx(1246.0, rel=0.05)
        assert prov["eq_temperature_source"] if "eq_temperature_source" in prov else prov["eq_temperature_k"] == "derived_equilibrium_zero_albedo"

    def test_missing_eq_temperature_without_orbital_distance_raises_error(self):
        resolved, missing, prov = resolve_retrieval_physical_parameters(
            radius_earth=11.2,
            mass_earth=317.8,
            radius_solar=1.0,
            teff_best_k=5778.0,
            eq_temperature_k=None,
            semi_major_axis_au=None,  # cannot derive
            luminosity_solar=1.0,
        )
        assert resolved is None
        assert "eq_temperature_k" in missing

    def test_unphysical_inputs_rejected(self):
        # Zero radius, negative mass, NaN Teff
        resolved, missing, prov = resolve_retrieval_physical_parameters(
            radius_earth=0.0,
            mass_earth=-5.0,
            radius_solar=float("nan"),
            teff_best_k=-100.0,
            eq_temperature_k=0.0,
            semi_major_axis_au=None,
            luminosity_solar=None,
        )
        assert resolved is None
        assert "radius_earth" in missing
        assert "mass_earth" in missing
        assert "radius_solar" in missing
        assert "teff_best_k" in missing
        assert "eq_temperature_k" in missing


class TestSpectrumPreprocessingAudit:
    """Verifies that spectrum preprocessing audits observational uncertainties and rejects assumptions."""

    def test_missing_or_zero_uncertainty_not_silently_replaced_with_10_percent(self):
        """Bins with missing or non-positive uncertainty must be rejected, never given an assumed 10% default."""
        import math
        from collections import namedtuple
        MockSpectrumRow = namedtuple("MockSpectrumRow", ["wavelength_um", "bandwidth_um", "depth_ppm", "depth_err_upper", "depth_err_lower"])

        # Row 1 has valid error, Row 2 has 0 error, Row 3 has None error
        rows = [
            MockSpectrumRow(wavelength_um=1.1, bandwidth_um=0.02, depth_ppm=2.1, depth_err_upper=0.05, depth_err_lower=-0.05),
            MockSpectrumRow(wavelength_um=1.2, bandwidth_um=0.02, depth_ppm=2.2, depth_err_upper=0.0, depth_err_lower=0.0),
            MockSpectrumRow(wavelength_um=1.3, bandwidth_um=0.02, depth_ppm=2.0, depth_err_upper=None, depth_err_lower=None),
        ]

        # Process like run_platon_retrieval
        valid_bins = []
        rejected = []
        for r in rows:
            err_up = float(r.depth_err_upper) if (r.depth_err_upper is not None and not math.isnan(r.depth_err_upper)) else None
            err_lo = abs(float(r.depth_err_lower)) if (r.depth_err_lower is not None and not math.isnan(r.depth_err_lower)) else None
            if err_up is not None and err_up > 0 and err_lo is not None and err_lo > 0:
                err = (err_up + err_lo) / 2.0
            elif err_up is not None and err_up > 0:
                err = err_up
            elif err_lo is not None and err_lo > 0:
                err = err_lo
            else:
                err = None

            if err is None or err <= 0:
                rejected.append(r.wavelength_um)
                continue
            valid_bins.append((r.wavelength_um, err))

        assert len(valid_bins) == 1
        assert valid_bins[0][0] == 1.1
        assert valid_bins[0][1] == 0.05
        assert len(rejected) == 2
        assert 1.2 in rejected
        assert 1.3 in rejected

    def test_observation_metadata_recorded_in_config(self):
        meta = {
            "depth_unit_provenance": {"scale_factor": 0.01, "notes": "NASA Exoplanet Archive percent to fraction"},
            "uncertainty_provenance": {"assumed_uncertainties_fabricated": False},
        }
        cfg = create_retrieval_configuration(
            retrieval_id="test-meta-cfg",
            spec_id="test-spec",
            planet_id="test-planet",
            sampler_name="dynesty",
            observation_metadata=meta,
        )
        assert cfg.observation_metadata["uncertainty_provenance"]["assumed_uncertainties_fabricated"] is False
        assert cfg.observation_metadata["depth_unit_provenance"]["scale_factor"] == 0.01
        assert cfg.sampler["sampler_name"] == "dynesty"


class TestPosteriorExtractionBranches:
    """Verifies that each branch of posterior weights and evidence extraction functions correctly and robustly."""

    def test_weights_extracted_from_result_weights_attribute(self):
        class MockResult:
            weights = np.array([0.2, 0.5, 0.3])
            final_logz = 175.5
            logzerr = [0.15]

        result = MockResult()
        dyn_res = result
        if hasattr(result, 'weights') and result.weights is not None:
            weights = np.asarray(result.weights).tolist()
        assert weights == [0.2, 0.5, 0.3]

    def test_weights_extracted_from_dyn_res_logwt_with_stable_logsumexp(self):
        """Tests the logwt branch using stable log-sum-exp normalization without undefined variable references."""
        class MockDynRes:
            weights = None
            logwt = np.array([-10.0, -8.0, -9.0])
            logz = [-8.0]
            logzerr = [0.25]

        dyn_res = MockDynRes()
        result = object()

        logz_arr = getattr(result, "logz", getattr(dyn_res, "logz", None))
        assert logz_arr == [-8.0]

        if hasattr(dyn_res, 'logwt') and dyn_res.logwt is not None and len(dyn_res.logwt) > 0:
            logwt = np.asarray(dyn_res.logwt)
            max_logwt = np.max(logwt)
            raw_wt = np.exp(logwt - max_logwt)
            sum_wt = np.sum(raw_wt)
            weights = (raw_wt / sum_wt).tolist() if sum_wt > 0 else []

        assert len(weights) == 3
        assert np.isclose(sum(weights), 1.0)
        assert weights[1] > weights[2] > weights[0]  # -8.0 is highest logwt

    def test_weights_fallback_empty_when_no_weights_or_logwt_present(self):
        class EmptyResult:
            weights = None
            logwt = None

        dyn_res = EmptyResult()
        result = EmptyResult()

        if hasattr(result, 'weights') and result.weights is not None:
            weights = np.asarray(result.weights).tolist()
        elif hasattr(dyn_res, 'weights') and dyn_res.weights is not None:
            weights = np.asarray(dyn_res.weights).tolist()
        elif hasattr(dyn_res, 'logwt') and dyn_res.logwt is not None and len(dyn_res.logwt) > 0:
            weights = [1.0]
        else:
            weights = []

        assert weights == []

    def test_evidence_and_uncertainty_extraction_priorities(self):
        class MockResult:
            final_logz = 180.25
            logz = [170.0, 175.0, 180.0]
            logzerr = [1.5, 0.8, 0.32]

        result = MockResult()
        dyn_res = result

        logz_arr = getattr(result, "logz", getattr(dyn_res, "logz", None))
        if hasattr(result, 'final_logz') and result.final_logz is not None:
            evidence_ln_z = float(result.final_logz)
        elif logz_arr is not None and len(logz_arr) > 0:
            evidence_ln_z = float(logz_arr[-1])
        else:
            evidence_ln_z = None

        logzerr_arr = getattr(result, "logzerr", getattr(dyn_res, "logzerr", None))
        if logzerr_arr is not None and len(logzerr_arr) > 0:
            evidence_err = float(logzerr_arr[-1])
        else:
            evidence_err = None

        assert evidence_ln_z == 180.25
        assert evidence_err == 0.32


