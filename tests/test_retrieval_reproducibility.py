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
)


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
        diagnostics = ConvergenceDiagnostics(converged=True, evidence_err=0.1)

        status, notes = evaluate_retrieval_reproducibility(config, diagnostics)
        assert status == "reproducibility_metadata_incomplete"
        assert any("missing" in n.lower() or "unknown" in n.lower() for n in notes)


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
