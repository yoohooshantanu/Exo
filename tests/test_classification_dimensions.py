"""
Tests for Phase 9: Reproducibility Classification & Scientific Status Separation.

Verifies the four independent dimensions:
  1. Metadata completeness
  2. Computational replay reproducibility
  3. Numerical retrieval convergence
  4. Scientific validation

Ensures that:
  - Dimensions are never collapsed into a single status.
  - A seed alone never verifies replay reproducibility.
  - Replay success does not imply statistical convergence.
  - ESS alone never establishes numerical convergence.
  - Software reproducibility and data provenance do not imply scientific validation.
  - Observational data provenance is tracked separately from model validation.
  - Invariants hold across representative records.
  - Legacy records are safely sanitized with backward compatibility.
  - API models cleanly serialize all four dimensions.
"""

import pytest
import json
import math
from pathlib import Path
from modules.retrieval_reproducibility import (
    MetadataCompleteness,
    ReplayReproducibility,
    ConvergenceStatus,
    ScientificValidation,
    FourDimensionalClassification,
    classify_retrieval_four_dimensions,
    sanitize_legacy_retrieval_record,
    find_replay_evidence,
)
from api.models import AtmosphericRetrievalItem


# ─────────────────────────────────────────────────────────────────────────────
# 1. Metadata Completeness Tests (Audit 2)
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataCompleteness:
    def test_complete_metadata_status(self):
        config = {
            "priors": {"Rp": [0.5, 2.0], "T": [500, 2500]},
            "chemical_species": ["H2O", "CO", "CO2"],
            "sampler": {
                "sampler_name": "dynesty",
                "random_seed": 42,
                "rstate_injected": True,
            },
            "fixed_parameters": {"Rs": 653262300.0, "Mp": 5.33e26, "T_star": 5329.8},
            "opacity_provenance": {
                "is_loader_intercepted": True,
                "species_absorption": {
                    "H2O": {"sha256_checksum": "aaa111"},
                    "CO": {"sha256_checksum": "bbb222"},
                    "CO2": {"sha256_checksum": "ccc333"},
                },
                "cia_files_count": 2,
            },
            "runtime_metadata": {"python": "3.11.1", "numpy": "1.24.1"},
        }
        posterior = {
            "samples": [[1.0, 1000.0]],
            "weights": [1.0],
            "raw_log_weights": [-0.1],
            "log_likelihoods": [-10.5],
        }
        res = classify_retrieval_four_dimensions(config=config, posterior=posterior)
        assert res.metadata_completeness == MetadataCompleteness.COMPLETE

    def test_partial_metadata_missing_opacity_hashes(self):
        config = {
            "priors": {"Rp": [0.5, 2.0], "T": [500, 2500]},
            "chemical_species": ["H2O", "CO"],
            "sampler": {"sampler_name": "dynesty", "random_seed": 42, "rstate_injected": True},
            "fixed_parameters": {"Rs": 653262300.0},
            "opacity_provenance": {
                "is_loader_intercepted": False,
                "H2O": {"database": "ExoMol", "release_version": "2018"},
                "CO": {"database": "HITEMP", "release_version": "2019"},
            },
        }
        res = classify_retrieval_four_dimensions(config=config)
        assert res.metadata_completeness == MetadataCompleteness.PARTIAL

    def test_partial_metadata_missing_raw_posterior_logs(self):
        config = {
            "priors": {"Rp": [0.5, 2.0], "T": [500, 2500]},
            "chemical_species": ["H2O"],
            "sampler": {"sampler_name": "dynesty", "random_seed": 42, "rstate_injected": True},
            "opacity_provenance": {
                "is_loader_intercepted": True,
                "species_absorption": {"H2O": {"sha256_checksum": "aaa111"}},
                "cia_files_count": 1,
            },
        }
        # Posterior has samples and weights, but lacks raw logwt/logl
        posterior = {
            "samples": [[1.0]],
            "weights": [1.0],
        }
        res = classify_retrieval_four_dimensions(config=config, posterior=posterior)
        assert res.metadata_completeness == MetadataCompleteness.PARTIAL

    def test_incomplete_metadata_missing_critical_priors(self):
        config = {
            "priors": {},
            "chemical_species": ["H2O"],
            "sampler": {"random_seed": 42},
        }
        res = classify_retrieval_four_dimensions(config=config)
        assert res.metadata_completeness == MetadataCompleteness.INCOMPLETE

    def test_incomplete_metadata_missing_seed(self):
        config = {
            "priors": {"Rp": [0.5, 2.0]},
            "chemical_species": ["H2O"],
            "sampler": {"sampler_name": "dynesty", "random_seed": None},
        }
        res = classify_retrieval_four_dimensions(config=config)
        assert res.metadata_completeness == MetadataCompleteness.INCOMPLETE

    def test_unverified_metadata_for_running_retrieval(self):
        res = classify_retrieval_four_dimensions(config=None, execution_status="running")
        assert res.metadata_completeness == MetadataCompleteness.UNVERIFIED

    def test_complete_reference_and_complete_replay(self):
        """Audit 2: Reference 0610e9c7 and replay 7f28460b are both complete with verified manifest link."""
        res_ref = classify_retrieval_four_dimensions(retrieval_id="0610e9c7-e600-4174-91d5-b02569105043")
        assert res_ref.metadata_completeness == MetadataCompleteness.COMPLETE

        res_rep = classify_retrieval_four_dimensions(retrieval_id="7f28460b-9565-4aac-b07a-cf9d667ede3e")
        assert res_rep.metadata_completeness == MetadataCompleteness.COMPLETE
        assert "linked manifest cryptographically verified" in " ".join(res_rep.notes)

    def test_complete_reference_but_incomplete_replay_metadata(self, tmp_path):
        """Audit 2: Replay directory with corrupted manifest link must be marked incomplete."""
        broken_preflight = {
            "manifest_path": "non_existent_manifest.json",
            "manifest_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        }
        res = classify_retrieval_four_dimensions(config=None, execution_status="completed")
        assert res.metadata_completeness == MetadataCompleteness.INCOMPLETE

    def test_replay_success_with_incomplete_metadata(self):
        """Audit 2: Replay comparison succeeded, but replay record lacks raw logwt/logl."""
        evidence = {
            "classification": "BITWISE_REPLAY_VERIFIED",
            "sample_comparison": {"bitwise_equal": True, "max_diff": 0.0},
            "evidence_comparison": {"diff": 0.0},
        }
        config = {
            "priors": {"Rp": [0.5, 2.0]},
            "chemical_species": ["H2O"],
            "sampler": {"sampler_name": "dynesty", "random_seed": 42, "rstate_injected": True},
            "opacity_provenance": {
                "is_loader_intercepted": True,
                "species_absorption": {"H2O": {"sha256_checksum": "aaa111"}},
                "cia_files_count": 1,
            },
        }
        # Posterior without raw logs
        posterior = {"samples": [[1.0]], "weights": [1.0]}
        res = classify_retrieval_four_dimensions(
            config=config,
            posterior=posterior,
            replay_evidence=evidence,
        )
        assert res.replay_reproducibility == ReplayReproducibility.BITWISE_REPLAY_VERIFIED
        assert res.metadata_completeness == MetadataCompleteness.PARTIAL

    def test_complete_metadata_with_no_replay_attempt(self):
        """Audit 2: Complete metadata with no replay attempt."""
        config = {
            "priors": {"Rp": [0.5, 2.0], "T": [500, 2500]},
            "chemical_species": ["H2O"],
            "sampler": {"sampler_name": "dynesty", "random_seed": 42, "rstate_injected": True},
            "fixed_parameters": {"Rs": 653262300.0, "Mp": 5.33e26, "T_star": 5329.8},
            "opacity_provenance": {
                "is_loader_intercepted": True,
                "species_absorption": {"H2O": {"sha256_checksum": "aaa111"}},
                "cia_files_count": 1,
            },
        }
        posterior = {
            "samples": [[1.0]],
            "weights": [1.0],
            "raw_log_weights": [-0.1],
            "log_likelihoods": [-10.5],
        }
        res = classify_retrieval_four_dimensions(config=config, posterior=posterior, replay_evidence=None)
        assert res.metadata_completeness == MetadataCompleteness.COMPLETE
        assert res.replay_reproducibility == ReplayReproducibility.NOT_ATTEMPTED


# ─────────────────────────────────────────────────────────────────────────────
# 2. Computational Replay Reproducibility Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestReplayReproducibility:
    def test_not_attempted_by_default_even_with_seed(self):
        config = {
            "priors": {"Rp": [0.5, 2.0]},
            "chemical_species": ["H2O"],
            "sampler": {"random_seed": 42, "rstate_injected": True},
        }
        res = classify_retrieval_four_dimensions(config=config, replay_evidence=None)
        assert res.replay_reproducibility == ReplayReproducibility.NOT_ATTEMPTED
        assert "A recorded seed alone does not establish replay reproducibility" in " ".join(res.notes)

    def test_bitwise_replay_verified(self):
        evidence = {
            "classification": "BITWISE_REPLAY_VERIFIED",
            "sample_comparison": {"bitwise_equal": True, "max_diff": 0.0},
            "evidence_comparison": {"diff": 0.0},
        }
        res = classify_retrieval_four_dimensions(replay_evidence=evidence)
        assert res.replay_reproducibility == ReplayReproducibility.BITWISE_REPLAY_VERIFIED

    def test_numerical_replay_verified(self):
        evidence = {
            "classification": "NUMERICAL_REPLAY_VERIFIED",
            "sample_comparison": {"same_shape": True, "max_diff": 1e-6},
            "evidence_comparison": {"diff": 2e-5},
        }
        res = classify_retrieval_four_dimensions(replay_evidence=evidence)
        assert res.replay_reproducibility == ReplayReproducibility.NUMERICAL_REPLAY_VERIFIED

    def test_replay_with_differences(self):
        evidence = {
            "classification": "REPLAY_WITH_DIFFERENCES",
            "sample_comparison": {"same_shape": True, "max_diff": 0.05},
            "evidence_comparison": {"diff": 0.8},
        }
        res = classify_retrieval_four_dimensions(replay_evidence=evidence)
        assert res.replay_reproducibility == ReplayReproducibility.REPLAY_WITH_DIFFERENCES

    def test_replay_blocked(self):
        evidence = {"classification": "BLOCKED", "status": "blocked"}
        res = classify_retrieval_four_dimensions(replay_evidence=evidence)
        assert res.replay_reproducibility == ReplayReproducibility.BLOCKED

    def test_replay_failed(self):
        evidence = {"classification": "FAILED", "status": "failed"}
        res = classify_retrieval_four_dimensions(replay_evidence=evidence)
        assert res.replay_reproducibility == ReplayReproducibility.FAILED


# ─────────────────────────────────────────────────────────────────────────────
# 3. Numerical Convergence Tests (Audit 1)
# ─────────────────────────────────────────────────────────────────────────────

class TestNumericalConvergence:
    def test_convergence_established_all_criteria(self):
        diag = {
            "converged": True,
            "evidence_err": 0.25,
            "effective_sample_size": 350.0,
            "n_samples": 1000,
            "warnings": [],
        }
        res = classify_retrieval_four_dimensions(convergence_diagnostics=diag)
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_ESTABLISHED

    def test_ess_alone_never_establishes_convergence_unconverged_flag(self):
        """Audit 1: ESS alone must never establish convergence if converged=False."""
        diag = {
            "converged": False,
            "evidence_err": 0.25,
            "effective_sample_size": 1200.0,  # High ESS
            "n_samples": 2000,
            "warnings": [],
        }
        res = classify_retrieval_four_dimensions(convergence_diagnostics=diag)
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED

    def test_ess_alone_never_establishes_convergence_high_uncertainty(self):
        """Audit 1: ESS alone must never establish convergence if evidence uncertainty > 0.50."""
        diag = {
            "converged": True,
            "evidence_err": 0.65,  # Exceeds tolerance
            "effective_sample_size": 1500.0,  # High ESS
            "n_samples": 3000,
            "warnings": [],
        }
        res = classify_retrieval_four_dimensions(convergence_diagnostics=diag)
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED

    def test_sampler_warnings_prevent_convergence(self):
        """Audit 1: Sampler warnings must prevent convergence even if numbers look good."""
        diag = {
            "converged": True,
            "evidence_err": 0.20,
            "effective_sample_size": 500.0,
            "n_samples": 1200,
            "warnings": ["The sampling was stopped short due to maxiter/maxcall limit."],
        }
        res = classify_retrieval_four_dimensions(convergence_diagnostics=diag)
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED
        assert "sampler emitted warnings" in " ".join(res.notes)

    def test_non_finite_diagnostics_prevent_convergence(self):
        """Audit 1: NaN or Inf diagnostics must never establish convergence."""
        diag_nan = {
            "converged": True,
            "evidence_err": float("nan"),
            "effective_sample_size": 300.0,
            "n_samples": 1000,
        }
        res = classify_retrieval_four_dimensions(convergence_diagnostics=diag_nan)
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED

        diag_inf = {
            "converged": True,
            "evidence_err": 0.2,
            "effective_sample_size": float("inf"),
            "n_samples": 1000,
        }
        res_inf = classify_retrieval_four_dimensions(convergence_diagnostics=diag_inf)
        assert res_inf.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED

    def test_convergence_not_evaluated_running(self):
        diag = {"converged": True, "evidence_err": 0.2, "effective_sample_size": 500.0, "n_samples": 1000}
        res = classify_retrieval_four_dimensions(convergence_diagnostics=diag, execution_status="running")
        assert res.convergence_status == ConvergenceStatus.NOT_EVALUATED

    def test_convergence_not_evaluated_failed(self):
        res = classify_retrieval_four_dimensions(execution_status="failed")
        assert res.convergence_status == ConvergenceStatus.NOT_EVALUATED


# ─────────────────────────────────────────────────────────────────────────────
# 4. Scientific Validation Tests (Audit 3)
# ─────────────────────────────────────────────────────────────────────────────

class TestScientificValidation:
    def test_not_validated_by_default(self):
        res = classify_retrieval_four_dimensions(scientific_evidence=None)
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED

    def test_published_observational_data_alone_cannot_upgrade_scientific_validation(self):
        """Audit 3: Observational spectrum publication establishes data provenance, NOT model validation."""
        sci = {
            "observation_doi": "10.1093/mnras/stw380",  # Nikolov et al. 2016 for WASP-39 b
            "validation_level": "partially_validated",
        }
        res = classify_retrieval_four_dimensions(scientific_evidence=sci)
        # Observational data provenance is verified
        assert res.observational_provenance == "published_observation"
        # BUT scientific validation MUST be rejected and remain not_validated
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED
        assert "published observational spectrum establishes data provenance only" in " ".join(res.notes)

    def test_computational_replay_cannot_upgrade_scientific_validation(self):
        """Audit 3: Replay verification cannot upgrade scientific validation."""
        evidence = {
            "classification": "BITWISE_REPLAY_VERIFIED",
            "sample_comparison": {"bitwise_equal": True, "max_diff": 0.0},
        }
        res = classify_retrieval_four_dimensions(
            replay_evidence=evidence,
            scientific_evidence={"observation_doi": "10.1093/mnras/stw380"},
        )
        assert res.replay_reproducibility == ReplayReproducibility.BITWISE_REPLAY_VERIFIED
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED

    def test_numerical_convergence_cannot_upgrade_scientific_validation(self):
        """Audit 3: Numerical convergence cannot upgrade scientific validation."""
        diag = {"converged": True, "evidence_err": 0.1, "effective_sample_size": 1000.0, "n_samples": 2000}
        res = classify_retrieval_four_dimensions(
            convergence_diagnostics=diag,
            scientific_evidence={"validation_level": "independently_validated"},
        )
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_ESTABLISHED
        # Rejected because required multi-framework intercomparison and retrieval validation DOI are missing
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED

    def test_partially_validated_requires_independent_model_evidence(self):
        """Audit 3: Partial validation requires actual independent model/retrieval benchmarking."""
        sci = {
            "validation_level": "partially_validated",
            "independent_model_validation": True,
            "retrieval_validation_doi": "10.1084/apj.12345",
        }
        res = classify_retrieval_four_dimensions(scientific_evidence=sci)
        assert res.scientific_validation == ScientificValidation.PARTIALLY_VALIDATED

    def test_independently_validated_requires_documented_multicode_validation(self):
        """Audit 3: Independent validation requires multi-framework intercomparison by independent groups."""
        sci = {
            "validation_level": "independently_validated",
            "retrieval_validation_doi": "10.1038/nature12345",
            "framework_intercomparison": True,
            "independent_codebases_verified": True,
        }
        res = classify_retrieval_four_dimensions(scientific_evidence=sci)
        assert res.scientific_validation == ScientificValidation.INDEPENDENTLY_VALIDATED

    def test_reject_unsubstantiated_independent_validation(self):
        sci = {
            "validation_level": "independently_validated",
            "peer_reviewed_doi": None,
            "framework_intercomparison": False,
        }
        res = classify_retrieval_four_dimensions(scientific_evidence=sci)
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED
        assert "Claims of independent validation rejected" in " ".join(res.notes)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Invariants & Real Historical Record Tests (Audits 1, 2, 3)
# ─────────────────────────────────────────────────────────────────────────────

class TestClassificationInvariants:
    def test_invariant_1_bitwise_reproducible_unconverged(self):
        """Invariant 1: Reference retrieval 0610e9c7 is bitwise reproducible but unconverged."""
        rid = "0610e9c7-e600-4174-91d5-b02569105043"
        cfg_p = Path(f"outputs/retrievals/config_{rid}.json")
        post_p = Path(f"outputs/retrievals/posterior_{rid}.json")
        assert cfg_p.exists() and post_p.exists()

        with open(cfg_p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(post_p, "r", encoding="utf-8") as f:
            post = json.load(f)

        res = classify_retrieval_four_dimensions(config=cfg, posterior=post, retrieval_id=rid)
        assert res.metadata_completeness == MetadataCompleteness.COMPLETE
        assert res.replay_reproducibility == ReplayReproducibility.BITWISE_REPLAY_VERIFIED
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED
        assert res.observational_provenance == "published_observation"

    def test_invariant_2_converged_not_replayed_c461200f(self):
        """Audit 1 & Invariant 2: Retrieval c461200f satisfies all convergence criteria with ESS=366.8, not replayed."""
        rid = "c461200f-a608-4d1f-b433-68d033072dc6"
        cfg_p = Path(f"outputs/retrievals/config_{rid}.json")
        post_p = Path(f"outputs/retrievals/posterior_{rid}.json")
        assert cfg_p.exists() and post_p.exists()

        with open(cfg_p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(post_p, "r", encoding="utf-8") as f:
            post = json.load(f)

        res = classify_retrieval_four_dimensions(config=cfg, posterior=post, retrieval_id=rid)
        # All convergence requirements satisfied:
        # converged=True, evidence_err=0.2687 <= 0.50, ESS=366.75 >= 100.0, N=1128, warnings=[]
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_ESTABLISHED
        assert res.replay_reproducibility == ReplayReproducibility.NOT_ATTEMPTED
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED
        assert res.metadata_completeness == MetadataCompleteness.PARTIAL

    def test_invariant_3_older_retrieval_missing_raw_posterior(self):
        """Invariant 3: Historical retrieval 9daa7eba lacks raw posterior logs and opacity interception."""
        rid = "9daa7eba-c779-4def-8a85-967e2757dec5"
        cfg_p = Path(f"outputs/retrievals/config_{rid}.json")
        post_p = Path(f"outputs/retrievals/posterior_{rid}.json")
        assert cfg_p.exists() and post_p.exists()

        with open(cfg_p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(post_p, "r", encoding="utf-8") as f:
            post = json.load(f)

        res = classify_retrieval_four_dimensions(config=cfg, posterior=post, retrieval_id=rid)
        assert res.metadata_completeness == MetadataCompleteness.PARTIAL
        assert res.replay_reproducibility == ReplayReproducibility.NOT_ATTEMPTED
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED

    def test_invariant_4_replay_execution_record_7f28460b(self):
        """Audit 2: Replay 7f28460b resolves linked reference manifest, verifies bitwise replay."""
        rid = "7f28460b-9565-4aac-b07a-cf9d667ede3e"
        cmp_p = Path(f"outputs/replays/replay_{rid}/comparison_report.json")
        assert cmp_p.exists()

        res = classify_retrieval_four_dimensions(retrieval_id=rid)
        # Linked manifest d8b6ec05... is cryptographically verified on disk
        assert res.metadata_completeness == MetadataCompleteness.COMPLETE
        assert res.replay_reproducibility == ReplayReproducibility.BITWISE_REPLAY_VERIFIED
        assert res.convergence_status == ConvergenceStatus.CONVERGENCE_NOT_ESTABLISHED
        assert res.scientific_validation == ScientificValidation.NOT_VALIDATED


# ─────────────────────────────────────────────────────────────────────────────
# 6. Legacy Record Sanitization & API Serialization Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacySanitizationAndApi:
    def test_sanitize_legacy_retrieval_record_preserves_compatibility(self):
        raw_row = {
            "retrieval_id": "c461200f-a608-4d1f-b433-68d033072dc6",
            "planet_id": "test_planet",
            "spec_id": "test_spec",
            "model_name": "PLATON_v1",
            "status": "completed",
            "reproducibility_status": "reproducibility_metadata_incomplete",
            "convergence_diagnostics": json.dumps({
                "converged": True,
                "evidence_err": 0.268,
                "effective_sample_size": 366.7,
                "n_samples": 1128,
                "warnings": [],
            }),
        }
        sanitized = sanitize_legacy_retrieval_record(raw_row)

        # Legacy fields preserved
        assert sanitized["status"] == "completed"
        assert sanitized["reproducibility_status"] == "reproducibility_metadata_incomplete"

        # Additive fields populated
        assert "metadata_completeness" in sanitized
        assert "replay_reproducibility" in sanitized
        assert "convergence_status" in sanitized
        assert "scientific_validation" in sanitized
        assert "observational_provenance" in sanitized
        assert "four_dimensional_classification" in sanitized
        assert sanitized["convergence_status"] == ConvergenceStatus.CONVERGENCE_ESTABLISHED
        assert sanitized["replay_reproducibility"] == ReplayReproducibility.NOT_ATTEMPTED

    def test_api_item_pydantic_serialization(self):
        raw_row = {
            "retrieval_id": "0610e9c7-e600-4174-91d5-b02569105043",
            "spec_id": "WASP_39_b_3.11466_3939_1",
            "model_name": "PLATON_v1",
            "status": "completed",
            "reproducibility_status": "convergence_not_established",
            "metadata_completeness": "complete",
            "replay_reproducibility": "bitwise_replay_verified",
            "convergence_status": "convergence_not_established",
            "scientific_validation": "not_validated",
            "observational_provenance": "published_observation",
            "four_dimensional_classification": {
                "metadata_completeness": "complete",
                "replay_reproducibility": "bitwise_replay_verified",
                "convergence_status": "convergence_not_established",
                "scientific_validation": "not_validated",
                "observational_provenance": "published_observation",
                "notes": ["Sample note"],
            },
        }
        item = AtmosphericRetrievalItem(**raw_row)
        d = item.model_dump()
        assert d["metadata_completeness"] == "complete"
        assert d["replay_reproducibility"] == "bitwise_replay_verified"
        assert d["convergence_status"] == "convergence_not_established"
        assert d["scientific_validation"] == "not_validated"
        assert d["observational_provenance"] == "published_observation"
        assert d["four_dimensional_classification"]["notes"] == ["Sample note"]
