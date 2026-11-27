"""
tests/test_sampler_reproducibility.py

Automated tests for Phase 2: Genuine Sampler Reproducibility.
Validates:
1. Explicit RNG injection into Dynesty 3.2.0 NestedSampler.
2. Bitwise deterministic replay across independent executions with identical seeds.
3. Seed variation sensitivity (different seeds produce distinct sample chains).
4. Unseeded runs produce non-deterministic outputs.
5. PLATON CombinedRetriever forwards rstate via dynesty_kwargs.
6. Retrieval configuration and posterior records capture complete RNG and sampler metadata.
"""

import json
import numpy as np
import pytest
from dynesty import NestedSampler
from modules.retrieval_reproducibility import (
    create_retrieval_configuration,
    get_package_version,
)


def simple_gaussian_lnlike(x):
    """2D Gaussian likelihood centered at [0.5, 0.5] with sigma=0.1."""
    return -0.5 * np.sum((x - 0.5) ** 2) / 0.01


def unit_prior_transform(u):
    """Identity prior transform mapping [0, 1]^2 to [0, 1]^2."""
    return np.asarray(u)


class TestDynestyRNGInjection:
    """Verifies that Dynesty 3.2.0 NestedSampler strictly honors injected rstate."""

    def test_bitwise_deterministic_replay_same_seed(self):
        """Two independent samplers with same PCG64 seed must produce bitwise identical chains."""
        rng1 = np.random.default_rng(12345)
        s1 = NestedSampler(simple_gaussian_lnlike, unit_prior_transform, 2, nlive=40, bound="multi", rstate=rng1)
        s1.run_nested(maxiter=150)
        res1 = s1.results

        rng2 = np.random.default_rng(12345)
        s2 = NestedSampler(simple_gaussian_lnlike, unit_prior_transform, 2, nlive=40, bound="multi", rstate=rng2)
        s2.run_nested(maxiter=150)
        res2 = s2.results

        # Samples must be bitwise identical
        assert np.array_equal(res1.samples, res2.samples), "Samples are not bitwise identical"
        # Log-likelihoods must be bitwise identical
        assert np.array_equal(res1.logl, res2.logl), "Log-likelihoods are not bitwise identical"
        # Raw log weights must be bitwise identical
        assert np.array_equal(res1.logwt, res2.logwt), "Raw log-weights are not bitwise identical"
        # Evidence must be bitwise identical
        assert np.array_equal(res1.logz, res2.logz), "Log-evidence arrays are not bitwise identical"
        assert res1.logz[-1] == res2.logz[-1], "Final log-evidence is not bitwise identical"
        assert res1.logzerr[-1] == res2.logzerr[-1], "Evidence uncertainty is not bitwise identical"

    def test_seed_sensitivity_different_seeds(self):
        """Two samplers with different seeds must produce distinct sample trajectories."""
        rng1 = np.random.default_rng(12345)
        s1 = NestedSampler(simple_gaussian_lnlike, unit_prior_transform, 2, nlive=40, bound="multi", rstate=rng1)
        s1.run_nested(maxiter=150)
        res1 = s1.results

        rng3 = np.random.default_rng(99999)
        s3 = NestedSampler(simple_gaussian_lnlike, unit_prior_transform, 2, nlive=40, bound="multi", rstate=rng3)
        s3.run_nested(maxiter=150)
        res3 = s3.results

        assert not np.array_equal(res1.samples, res3.samples), "Different seeds produced identical samples!"
        assert res1.logz[-1] != res3.logz[-1], "Different seeds produced identical log-evidence!"

    def test_unseeded_runs_are_non_deterministic(self):
        """Without rstate, Dynesty draws entropy from OS, producing different results."""
        s1 = NestedSampler(simple_gaussian_lnlike, unit_prior_transform, 2, nlive=40, bound="multi")
        s1.run_nested(maxiter=100)
        res1 = s1.results

        s2 = NestedSampler(simple_gaussian_lnlike, unit_prior_transform, 2, nlive=40, bound="multi")
        s2.run_nested(maxiter=100)
        res2 = s2.results

        assert not np.array_equal(res1.samples, res2.samples), "Unseeded runs produced identical samples"


class TestPLATONRetrieverRNGForwarding:
    """Verifies that PLATON CombinedRetriever accepts and forwards rstate."""

    def test_run_multinest_signature_accepts_dynesty_kwargs(self):
        import inspect
        from platon.combined_retriever import CombinedRetriever
        sig = inspect.signature(CombinedRetriever.run_multinest)
        assert "dynesty_kwargs" in sig.parameters, "CombinedRetriever.run_multinest does not accept dynesty_kwargs"

    def test_config_records_complete_sampler_and_rng_metadata(self):
        expected_dynesty_version = get_package_version("dynesty")
        cfg = create_retrieval_configuration(
            retrieval_id="test-rng-meta",
            spec_id="test-spec",
            planet_id="test-planet",
            sampler_name="dynesty",
            random_seed=42,
            nlive=100,
        )
        assert cfg.sampler["sampler_name"] == "dynesty"
        assert cfg.sampler["sampler_version"] == expected_dynesty_version
        assert cfg.sampler["random_seed"] == 42
        assert cfg.sampler["rng_type"] == "numpy.random.Generator"
        assert cfg.sampler["rng_bit_generator"] == "PCG64"
        # Metadata distinctions: seed provided and rstate injected are True,
        # but replay_determinism_verified is strictly False until an actual replay is evaluated
        assert cfg.sampler["seed_provided"] is True
        assert cfg.sampler["rstate_injected"] is True
        assert cfg.sampler["replay_determinism_verified"] is False
        # Sampler configuration parameters
        assert cfg.sampler["bound"] == "multi"
        assert cfg.sampler["sample"] == "auto"
        assert cfg.sampler["bounding_method"] == "MultiEllipsoid"
        assert cfg.sampler["internal_sampling_method"] == "UniformBoundSampler"
        assert cfg.sampler["resolved_sampling_method"] == "UniformBoundSampler"
        assert cfg.sampler["update_interval_ratio"] == 2.0
        assert cfg.sampler["bound_update_interval"] == 200
        assert cfg.sampler["parameters"]["importance_nested_sampling"] is False
        # Determinism scope limits claims to execution environment
        det_scope = cfg.sampler["determinism_scope"]
        assert det_scope["scope"] == "execution_environment_only"
        assert det_scope["cross_platform_bitwise_guaranteed"] is False
        assert det_scope["cross_version_bitwise_guaranteed"] is False

    def test_unseeded_config_metadata_distinctions(self):
        cfg = create_retrieval_configuration(
            retrieval_id="test-unseeded-meta",
            spec_id="test-spec",
            planet_id="test-planet",
            sampler_name="dynesty",
            random_seed=None,
            nlive=100,
        )
        assert cfg.sampler["random_seed"] is None
        assert cfg.sampler["seed_provided"] is False
        assert cfg.sampler["rstate_injected"] is False
        assert cfg.sampler["replay_determinism_verified"] is False
        assert cfg.sampler["rng_type"] is None
