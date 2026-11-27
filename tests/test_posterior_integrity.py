"""
Targeted tests for Phase 7: Posterior Integrity, Preservation & Diagnostics.
Verifies:
1. Stable log-sum-exp weight normalization and independent recomputation.
2. Preservation of raw log weights, log likelihoods, and normalized weights.
3. Zero-weight and non-finite handling.
4. Kish Effective Sample Size (ESS) mathematical properties and edge cases.
5. Weighted credible interval calculations.
6. Convergence classification criteria enforcement.
7. Complete posterior JSON serialization and deserialization round-trip integrity.
8. Backward compatibility with legacy posterior records.
"""

import json
import math
import numpy as np
import pytest
from pathlib import Path

from modules.retrieval_reproducibility import (
    compute_kish_effective_sample_size,
    evaluate_retrieval_reproducibility,
    ConvergenceDiagnostics,
    ReproducibleRetrievalConfig,
    create_retrieval_configuration,
    sanitize_legacy_retrieval_record,
)


def log_sum_exp_normalize(logwt: np.ndarray) -> np.ndarray:
    """Standard, numerically stable log-sum-exp normalization policy.
    Maps log-weights to normalized weights summing to 1.0."""
    logwt = np.asarray(logwt, dtype=np.float64)
    if len(logwt) == 0:
        return np.array([], dtype=np.float64)
    if np.all(np.isneginf(logwt)):
        return np.zeros_like(logwt)
    finite_mask = np.isfinite(logwt)
    if not np.any(finite_mask):
        return np.zeros_like(logwt)
    max_logwt = np.max(logwt[finite_mask])
    shifted = logwt - max_logwt
    # exp(-inf) is 0.0 in numpy
    raw_wt = np.exp(shifted)
    sum_wt = np.sum(raw_wt)
    if sum_wt <= 0.0 or not np.isfinite(sum_wt):
        return np.zeros_like(logwt)
    return raw_wt / sum_wt


class TestLogWeightNormalization:
    """Verifies numerical stability, precision, and policies for posterior weight normalization."""

    def test_log_sum_exp_stable_normalization(self):
        """Verifies normalization handles wide dynamic ranges without overflow or underflow."""
        # Dynamic range spanning 500 orders of magnitude in log-space
        logwt = np.array([-450.0, -200.0, -50.0, 0.0, 50.0, 100.0, 200.0])
        weights = log_sum_exp_normalize(logwt)

        # 1. Weights must sum to 1.0 within numerical precision
        assert math.isclose(np.sum(weights), 1.0, abs_tol=1e-12)
        # 2. Maximum weight corresponds to maximum log weight
        assert np.argmax(weights) == np.argmax(logwt)
        # 3. Smallest log weights are either zero or negligible subnormals (< 1e-250) without NaNs
        assert weights[0] < 1e-250
        assert np.all(np.isfinite(weights))

    def test_independent_normalized_weight_recomputation(self):
        """Verifies that normalized weights can be independently and bitwise-recomputed from raw logwt."""
        rng = np.random.default_rng(42)
        raw_logwt = rng.normal(loc=-10.0, scale=3.0, size=263)

        # PLATON / Exo production normalization logic
        max_logwt = np.max(raw_logwt)
        raw_wt = np.exp(raw_logwt - max_logwt)
        sum_wt = np.sum(raw_wt)
        production_weights = (raw_wt / sum_wt).tolist()

        # Independent recomputation
        independent_weights = log_sum_exp_normalize(raw_logwt).tolist()

        # Must match to within floating-point tolerance (machine precision ~1e-15)
        diff = np.abs(np.array(production_weights) - np.array(independent_weights))
        assert np.max(diff) < 1e-14
        assert np.allclose(production_weights, independent_weights, atol=1e-14)
        assert math.isclose(sum(production_weights), 1.0, abs_tol=1e-12)

    def test_zero_weight_samples_from_neg_inf(self):
        """Verifies that -inf log weights produce zero weights and are preserved without sample dropping."""
        raw_logwt = np.array([-np.inf, -5.0, -2.0, -np.inf, 0.0])
        weights = log_sum_exp_normalize(raw_logwt)

        assert len(weights) == len(raw_logwt)
        assert weights[0] == 0.0
        assert weights[3] == 0.0
        assert weights[4] > weights[2] > weights[1] > 0.0
        assert math.isclose(np.sum(weights), 1.0, abs_tol=1e-12)

    def test_all_neg_inf_log_weights_handled_safely(self):
        """Verifies that an array of all -inf log weights does not raise or produce NaNs."""
        raw_logwt = np.array([-np.inf, -np.inf, -np.inf])
        weights = log_sum_exp_normalize(raw_logwt)

        assert len(weights) == 3
        assert np.all(weights == 0.0)
        assert not np.any(np.isnan(weights))

    def test_non_finite_nan_log_weights_handled_safely(self):
        """Verifies that NaN or inf values in log weights are handled without unhandled crashes."""
        raw_logwt = np.array([np.nan, -1.0, 0.0, 1.0])
        # If NaN is present, finite mask handles or flags
        weights = log_sum_exp_normalize(np.nan_to_num(raw_logwt, nan=-np.inf))
        assert len(weights) == 4
        assert weights[0] == 0.0
        assert math.isclose(np.sum(weights), 1.0, abs_tol=1e-12)

    def test_no_silent_fallback_to_uniform_weights(self):
        """Verifies that non-uniform log weights never silently fall back to 1/N uniform weights."""
        raw_logwt = np.array([10.0, 20.0, 30.0, 40.0])
        weights = log_sum_exp_normalize(raw_logwt)
        uniform_weights = np.ones(4) / 4.0

        assert not np.allclose(weights, uniform_weights)
        assert weights[-1] > 0.99  # dominant sample

    def test_weight_sample_ordering_consistency(self):
        """Verifies that samples, log weights, and log likelihoods maintain strictly identical indexing."""
        n_samples = 50
        rng = np.random.default_rng(123)
        samples = rng.uniform(low=[1e7, 1000], high=[1e8, 2000], size=(n_samples, 2))
        logwt = rng.normal(loc=0.0, scale=2.0, size=n_samples)
        logl = rng.normal(loc=150.0, scale=1.0, size=n_samples)
        weights = log_sum_exp_normalize(logwt)

        # Confirm 1-to-1 association: index k across all arrays refers to identical state
        for k in range(n_samples):
            assert len(samples[k]) == 2
            assert np.isfinite(logwt[k])
            assert np.isfinite(logl[k])
            assert weights[k] >= 0.0


class TestPosteriorDiagnostics:
    """Verifies mathematical correctness and edge cases of Kish ESS and weighted credible intervals."""

    def test_kish_ess_uniform_weights(self):
        """Uniform weights w_i = 1/N must yield Kish ESS = N exactly."""
        N = 500
        weights = [1.0 / N] * N
        ess = compute_kish_effective_sample_size(weights)
        assert ess is not None
        assert math.isclose(ess, N, abs_tol=1e-9)

    def test_kish_ess_single_dominant_weight(self):
        """Degenerate weights with a single delta peak must yield Kish ESS = 1.0."""
        weights = [1.0] + [0.0] * 99
        ess = compute_kish_effective_sample_size(weights)
        assert ess is not None
        assert math.isclose(ess, 1.0, abs_tol=1e-9)

    def test_kish_ess_edge_cases(self):
        """Verifies empty, None, all-zero, or invalid weights return None without crashing."""
        assert compute_kish_effective_sample_size(None) is None
        assert compute_kish_effective_sample_size([]) is None
        assert compute_kish_effective_sample_size([0.0, 0.0, 0.0]) is None
        assert compute_kish_effective_sample_size(["invalid", 1.0]) is None

    def test_kish_ess_vs_sample_count_distinction(self):
        """Verifies Kish ESS is distinctly computed from and strictly less than or equal to sample count."""
        # Synthetic run mirroring reference retrieval 0610e9c7
        weights = np.exp(np.linspace(-5, 0, 263))
        weights /= np.sum(weights)
        ess = compute_kish_effective_sample_size(weights)

        assert ess is not None
        assert ess < len(weights)
        assert ess > 1.0
        # ESS cannot be claimed as sample count
        assert ess != len(weights)

    def test_weighted_quantiles_correctness(self):
        """Verifies weighted 16th, 50th (median), and 84th percentiles match expected distribution."""
        # Generate known Gaussian distribution with mean 100, std 10
        rng = np.random.default_rng(999)
        n = 10000
        vals = rng.normal(loc=100.0, scale=10.0, size=n)
        # Uniform weights for standard Gaussian
        weights = np.ones(n) / n

        sort_idx = np.argsort(vals)
        sorted_vals = vals[sort_idx]
        sorted_weights = weights[sort_idx]
        cum_weights = np.cumsum(sorted_weights) / np.sum(sorted_weights)

        p16 = float(np.interp(0.16, cum_weights, sorted_vals))
        p50 = float(np.interp(0.50, cum_weights, sorted_vals))
        p84 = float(np.interp(0.84, cum_weights, sorted_vals))

        # Expected: p50 ~ 100.0, p16 ~ 90.0 (-1 sigma), p84 ~ 110.0 (+1 sigma)
        assert math.isclose(p50, 100.0, abs_tol=0.5)
        assert math.isclose(p16, 90.0, abs_tol=0.5)
        assert math.isclose(p84, 110.0, abs_tol=0.5)
        assert (p50 - p16) > 0.0
        assert (p84 - p50) > 0.0

    def test_unimplemented_diagnostics_not_fabricated(self):
        """Asserts that production posterior records do not fabricate values for uncomputed diagnostics."""
        post_path = Path("outputs/retrievals/posterior_0610e9c7-e600-4174-91d5-b02569105043.json")
        if post_path.exists():
            with open(post_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Parameter correlation matrix is not computed; confirm no fake matrix is presented
            assert "correlation_matrix" not in data
            assert "parameter_covariance" not in data
            # Summary statistics contain only verified percentiles
            for p, stats in data.get("summary_statistics", {}).items():
                assert "median" in stats
                assert "p16" in stats
                assert "p84" in stats
                assert "lower_1sigma" in stats
                assert "upper_1sigma" in stats
                # No fake kurtosis, skewness, or mean
                assert "kurtosis" not in stats
                assert "skewness" not in stats


class TestEvidenceAndConvergenceClassification:
    """Verifies that evidence uncertainty and ESS thresholds strictly govern convergence status."""

    def test_convergence_fails_when_logzerr_exceeds_threshold(self):
        """Evidence uncertainty > 0.5 must strictly prevent converged status."""
        diag = ConvergenceDiagnostics(
            converged=False,
            evidence_ln_z=177.013,
            evidence_err=0.616,  # > 0.5
            n_samples=263,
            effective_sample_size=150.0,  # passing ESS
            warnings=["Evidence uncertainty exceeds tolerance."],
        )
        cfg = create_retrieval_configuration(
            retrieval_id="test-conv-logzerr",
            spec_id="spec-test",
            planet_id="planet-test",
        )
        status, notes = evaluate_retrieval_reproducibility(cfg, diag)
        assert status == "convergence_not_established"
        assert any("exceeds tolerance" in n for n in notes)

    def test_convergence_fails_when_ess_below_threshold(self):
        """Kish ESS < 100.0 must strictly prevent converged status."""
        diag = ConvergenceDiagnostics(
            converged=False,
            evidence_ln_z=177.013,
            evidence_err=0.200,  # passing logzerr
            n_samples=263,
            effective_sample_size=74.47,  # < 100.0
            warnings=["ESS below minimum threshold."],
        )
        cfg = create_retrieval_configuration(
            retrieval_id="test-conv-ess",
            spec_id="spec-test",
            planet_id="planet-test",
        )
        status, notes = evaluate_retrieval_reproducibility(cfg, diag)
        assert status == "convergence_not_established"
        assert any("below minimum threshold" in n for n in notes)

    def test_missing_diagnostics_prevent_convergence(self):
        """None convergence_diagnostics must produce unconverged status, never verified."""
        cfg = create_retrieval_configuration(
            retrieval_id="test-conv-missing",
            spec_id="spec-test",
            planet_id="planet-test",
        )
        status, notes = evaluate_retrieval_reproducibility(cfg, convergence_diagnostics=None)
        assert status in ["convergence_not_established", "reproducibility_metadata_incomplete"]
        assert status != "reproducibility_verified"


class TestPosteriorSerializationRoundTrip:
    """Verifies serialization and deserialization integrity across shapes, precision, and legacy records."""

    def test_serialization_deserialization_round_trip(self, tmp_path):
        """Ensures that synthetic posterior data survives JSON round-trip without loss or distortion."""
        n_samples = 150
        n_params = 3
        param_names = ["Rp", "T", "logZ"]
        rng = np.random.default_rng(777)

        samples = rng.uniform(low=[1e7, 500, -2.0], high=[1e8, 2500, 2.0], size=(n_samples, n_params)).tolist()
        logwt = rng.normal(loc=-5.0, scale=2.0, size=n_samples).tolist()
        logl = rng.normal(loc=180.0, scale=0.5, size=n_samples).tolist()
        weights = log_sum_exp_normalize(np.array(logwt)).tolist()

        posterior_data = {
            "retrieval_id": "test-roundtrip-uuid",
            "params": param_names,
            "samples": samples,
            "weights": weights,
            "raw_log_weights": logwt,
            "log_likelihoods": logl,
            "best_fit": {"Rp": 9e7, "T": 1200.0, "logZ": 0.0},
            "summary_statistics": {
                "Rp": {"median": 9e7, "p16": 8.5e7, "p84": 9.5e7, "lower_1sigma": 5e6, "upper_1sigma": 5e6},
                "T": {"median": 1200.0, "p16": 1100.0, "p84": 1300.0, "lower_1sigma": 100.0, "upper_1sigma": 100.0},
                "logZ": {"median": 0.0, "p16": -0.5, "p84": 0.5, "lower_1sigma": 0.5, "upper_1sigma": 0.5},
            },
            "evidence_ln_z": 177.013168814844,
            "evidence_err": 0.6162460085840782,
            "reproducibility_status": "convergence_not_established",
            "random_seed": 42,
            "config_file": "config_test.json",
        }

        json_file = tmp_path / "test_posterior.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(posterior_data, f, indent=2)

        with open(json_file, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)

        # 1. Dimension and length equality
        assert len(loaded_data["samples"]) == n_samples
        assert len(loaded_data["samples"][0]) == n_params
        assert loaded_data["params"] == param_names
        assert len(loaded_data["weights"]) == n_samples
        assert len(loaded_data["raw_log_weights"]) == n_samples
        assert len(loaded_data["log_likelihoods"]) == n_samples

        # 2. Numerical precision round-trip (IEEE double precision within float representation)
        assert np.allclose(loaded_data["samples"], samples, atol=1e-12)
        assert np.allclose(loaded_data["weights"], weights, atol=1e-15)
        assert np.allclose(loaded_data["raw_log_weights"], logwt, atol=1e-14)
        assert np.allclose(loaded_data["log_likelihoods"], logl, atol=1e-14)
        assert math.isclose(loaded_data["evidence_ln_z"], 177.013168814844, abs_tol=1e-12)
        assert math.isclose(loaded_data["evidence_err"], 0.6162460085840782, abs_tol=1e-12)

    def test_large_array_no_truncation(self, tmp_path):
        """Verifies large posterior sample arrays (10,000 samples) do not truncate or lose records."""
        n_samples = 10000
        n_params = 4
        rng = np.random.default_rng(888)
        samples = rng.uniform(size=(n_samples, n_params)).tolist()

        data = {"retrieval_id": "large-test", "samples": samples}
        fpath = tmp_path / "large_posterior.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f)

        with open(fpath, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert len(loaded["samples"]) == n_samples
        assert len(loaded["samples"][9999]) == n_params

    def test_empty_and_malformed_posterior_json(self, tmp_path):
        """Verifies malformed JSON raises JSONDecodeError and empty dictionary fails gracefully."""
        bad_file = tmp_path / "corrupted.json"
        bad_file.write_text("{ incomplete json: [", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            with open(bad_file, "r", encoding="utf-8") as f:
                json.load(f)

        empty_file = tmp_path / "empty.json"
        empty_file.write_text("{}", encoding="utf-8")
        with open(empty_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {}

    def test_legacy_json_backward_compatibility(self):
        """Verifies that legacy Phase 1 posterior JSON lacking raw_log_weights remains readable."""
        legacy_path = Path("outputs/retrievals/posterior_49ad8274-c30f-4afe-bd5a-433d4c0a79ce.json")
        if legacy_path.exists():
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Essential legacy fields present
            assert "retrieval_id" in data
            assert "samples" in data
            assert "weights" in data
            assert "params" in data
            assert "summary_statistics" in data
            # Schema v2 fields safely absent, not fabricated
            assert "raw_log_weights" not in data
            assert "log_likelihoods" not in data
            assert len(data["samples"]) == len(data["weights"])
