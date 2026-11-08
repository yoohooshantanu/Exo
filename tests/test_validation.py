"""Unit tests for the offline scientific validation checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


class TestESIBenchmark:
    """Tests for ESI benchmark against published UPR values."""

    def test_reference_table_has_enough_planets(self):
        from validation.esi_benchmark import REFERENCE_PLANETS
        assert len(REFERENCE_PLANETS) >= 15, "Need at least 15 reference planets"

    def test_all_reference_planets_have_required_fields(self):
        from validation.esi_benchmark import REFERENCE_PLANETS
        for p in REFERENCE_PLANETS:
            assert "name" in p
            assert "radius" in p and p["radius"] > 0
            assert "mass" in p and p["mass"] > 0
            assert "teq" in p and p["teq"] > 0
            assert "published_esi" in p and 0 < p["published_esi"] <= 1.0

    def test_esi_benchmark_computes_valid_correlation(self):
        from validation.esi_benchmark import run_esi_benchmark
        result = run_esi_benchmark()
        assert result["pearson_r"] is not None, "Pearson r should be computed"
        assert result["spearman_rho"] is not None, "Spearman rho should be computed"
        assert result["n_compared"] >= 15, f"Should compare ≥15 planets, got {result['n_compared']}"

    def test_esi_benchmark_passes_threshold(self):
        from validation.esi_benchmark import run_esi_benchmark
        result = run_esi_benchmark()
        assert result["passed"], (
            f"ESI benchmark should pass (r >= 0.70), got r = {result['pearson_r']}"
        )

    def test_earth_esi_is_near_one(self):
        from modules.habitability_scorer import compute_similarity_esi
        earth_esi = compute_similarity_esi(1.0, 1.0, 255)
        assert earth_esi is not None
        assert earth_esi > 0.99, f"Earth ESI should be ~1.0, got {earth_esi}"


class TestSanityChecks:
    """Tests for Solar System sanity checks."""

    def test_earth_scores_high(self):
        from validation.sanity_checks import run_sanity_checks
        results, scores = run_sanity_checks()
        earth = scores["Earth"]
        assert earth["similarity_score"] is not None
        assert earth["similarity_score"] > 0.85, (
            f"Earth similarity should be > 0.85, got {earth['similarity_score']}"
        )

    def test_jupiter_scores_low(self):
        from validation.sanity_checks import run_sanity_checks
        results, scores = run_sanity_checks()
        jupiter = scores["Jupiter"]
        comp = jupiter.get("composite_score")
        # Jupiter may get None composite (ESI returns None for extreme values)
        # or a very low value — either is correct
        if comp is not None:
            assert comp < 0.40, f"Jupiter composite should be < 0.40, got {comp}"

    def test_all_sanity_checks_pass(self):
        from validation.sanity_checks import run_sanity_checks
        results, _ = run_sanity_checks()
        failures = [r for r in results if not r.passed]
        if failures:
            msgs = "; ".join(f"{r.name}: {r.message}" for r in failures)
            pytest.fail(f"Sanity check failures: {msgs}")
