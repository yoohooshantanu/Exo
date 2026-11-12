"""Tests for modules/discovery_score.py"""
import pytest

from modules.discovery_score import (
    compute_data_quality_component,
    instrument_tier_points,
)


class TestInstrumentTierPoints:
    def test_jwst(self):
        assert instrument_tier_points("JWST/NIRSpec") == 5.0

    def test_hst(self):
        assert instrument_tier_points("HST/WFC3") == 3.5

    def test_other(self):
        assert instrument_tier_points("Keck") == 2.0


class TestComputeDataQualityComponent:
    def test_no_spectra_caps_at_completeness_only(self):
        assert compute_data_quality_component(False, None, 3) == 3.0

    def test_full_jwst_planet_hits_cap(self):
        # 5 spectra + 5 JWST + 5 completeness = 15
        assert compute_data_quality_component(True, "JWST", 5) == 15.0

    def test_uncapped_param_count_would_exceed_15_without_cap(self):
        # Even with 99 "known" params, completeness is capped at 5
        score = compute_data_quality_component(True, "JWST", 99)
        assert score == 15.0

    def test_hst_with_partial_completeness(self):
        # 5 + 3.5 + 2 = 10.5
        assert compute_data_quality_component(True, "HST", 2) == pytest.approx(10.5)


class TestDiscoveryScoreMigration:
    def test_migration_uses_correct_habitability_version(self):
        from pathlib import Path
        
        project_root = Path(__file__).resolve().parent.parent
        migration_file = project_root / "alembic" / "versions" / "46149d200533_add_materialized_view_for_discovery_.py"
        
        content = migration_file.read_text(encoding="utf-8")
        assert "hs.model_version = '{HABITABILITY_MODEL_VERSION}'" in content, "Migration must use the correct HABITABILITY_MODEL_VERSION variable"
