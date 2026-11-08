"""
Tests for modules/biosignature_detector.py

Covers: classify_detection logic, abiotic reasoning, stellar contamination
penalties, instrument weighting, tier classification, and constants integrity.
"""
import pytest

from modules.biosignature_detector import (
    classify_detection,
    CONFIRMED_SIGMA,
    MARGINAL_SIGMA,
    TRIPLE_BIOSIG,
    DISEQ_PAIR,
    ABIOTIC_MOLECULES,
    TARGET_MOLECULES,
    MOL_BAND_CENTERS,
    INSTRUMENT_WEIGHTS,
    STELLAR_CONTAM_RISK,
)


# ── Helper to build detection dicts ──────────────────────────────────────────

def make_det(molecule="h2o", sigma=4.0, matches=5, instrument="JWST/NIRSpec",
             facility="JWST", is_muted=False):
    return {
        "molecule": molecule,
        "detection_sigma": sigma,
        "hitran_match_count": matches,
        "wavelength_um": 1.4,
        "depth_excess_ppm": 50.0,
        "log_evidence": 10.0,
        "is_muted": is_muted,
        "instrument": instrument,
        "facility": facility,
    }


# ── Tier Classification ─────────────────────────────────────────────────────

class TestTierClassification:
    def test_confirmed_tier(self):
        """High sigma + many lines → confirmed."""
        det = make_det(sigma=4.0, matches=5)
        result = classify_detection(det, [det], {}, None)
        assert result["tier"] == "confirmed"

    def test_marginal_tier(self):
        """Moderate sigma + 2 lines → marginal."""
        det = make_det(sigma=2.5, matches=2)
        result = classify_detection(det, [det], {}, None)
        assert result["tier"] == "marginal"

    def test_rejected_tier(self):
        """Low sigma → rejected."""
        det = make_det(sigma=1.0, matches=1)
        result = classify_detection(det, [det], {}, None)
        assert result["tier"] == "rejected"

    def test_high_sigma_few_lines_rejected(self):
        """High sigma but only 1 line → should not be confirmed."""
        det = make_det(sigma=5.0, matches=1)
        result = classify_detection(det, [det], {}, None)
        assert result["tier"] != "confirmed"


# ── Instrument Weighting ─────────────────────────────────────────────────────

class TestInstrumentWeighting:
    def test_jwst_no_penalty(self):
        """JWST observations should get weight = 1.0 (no penalty)."""
        det = make_det(sigma=4.0, facility="JWST")
        result = classify_detection(det, [det], {}, None)
        # Sigma should remain high (no instrument penalty)
        assert result["detection_sigma"] >= 3.5

    def test_ground_based_penalized(self):
        """Unknown ground-based facility should be penalized."""
        det = make_det(sigma=4.0, instrument="unknown", facility="Keck")
        result = classify_detection(det, [det], {}, None)
        assert result["detection_sigma"] < 4.0

    def test_hst_moderate_penalty(self):
        """HST should get weight = 0.85."""
        det = make_det(sigma=4.0, instrument="HST/WFC3", facility="HST")
        result = classify_detection(det, [det], {}, None)
        assert result["detection_sigma"] < 4.0
        assert result["detection_sigma"] > 3.0


# ── Stellar Contamination ────────────────────────────────────────────────────

class TestStellarContamination:
    def test_m_dwarf_h2o_penalized(self):
        """H2O detection around M-dwarf should get contamination penalty."""
        det = make_det(molecule="h2o", sigma=4.0)
        result = classify_detection(det, [det], {}, "M3V")
        assert result["detection_sigma"] < 4.0
        assert "contamination" in result["method_notes"].lower()

    def test_g_dwarf_h2o_no_penalty(self):
        """H2O detection around G-dwarf should NOT get contamination penalty."""
        det = make_det(molecule="h2o", sigma=4.0)
        result = classify_detection(det, [det], {}, "G2V")
        # No stellar contamination for G-type
        assert "contamination" not in result["method_notes"].lower()


# ── Abiotic Reasoning ────────────────────────────────────────────────────────

class TestAbioticReasoning:
    def test_ch4_without_co2_penalized(self):
        """CH4 without CO2 → possible abiotic origin, penalty applied."""
        det = make_det(molecule="ch4", sigma=4.0)
        all_dets = [det]  # No CO2 in detections
        result = classify_detection(det, all_dets, {}, None)
        assert result["detection_sigma"] < 4.0
        assert "abiotic" in result["method_notes"].lower()

    def test_triple_biosignature(self):
        """H2O + CH4 + O3 all confirmed → abiotic_ruled_out = True."""
        h2o = make_det(molecule="h2o", sigma=4.0)
        ch4 = make_det(molecule="ch4", sigma=4.0)
        o3 = make_det(molecule="o3", sigma=4.0)
        all_dets = [h2o, ch4, o3]
        result = classify_detection(h2o, all_dets, {}, None)
        assert result["abiotic_ruled_out"] is True
        assert "TRIPLE" in result["method_notes"]

    def test_so2_on_rocky_flagged_volcanic(self):
        """SO2 on a rocky world should be flagged as volcanic."""
        det = make_det(molecule="so2", sigma=3.5)
        phys = {"m_e": 5.0, "r_e": 1.5}
        result = classify_detection(det, [det], phys, None)
        assert "volcanic" in result["method_notes"].lower()
        assert result["abiotic_ruled_out"] is False

    def test_nh3_on_rocky_boosted(self):
        """NH3 on a rocky world is anomalous → sigma boost."""
        det = make_det(molecule="nh3", sigma=3.0)
        phys = {"m_e": 3.0, "r_e": 1.2}
        result = classify_detection(det, [det], phys, None)
        assert result["detection_sigma"] > 3.0
        assert "anomalous" in result["method_notes"].lower()

    def test_nh3_on_gas_giant_penalized(self):
        """NH3 on a gas giant is expected → sigma penalty."""
        det = make_det(molecule="nh3", sigma=3.0)
        phys = {"m_e": 300.0, "r_e": 11.0}
        result = classify_detection(det, [det], phys, None)
        assert result["detection_sigma"] < 3.0
        assert "expected" in result["method_notes"].lower()


# ── Cloud/Haze Muting ───────────────────────────────────────────────────────

class TestCloudMuting:
    def test_muted_spectrum_penalized(self):
        """Muted spectrum → -0.5σ penalty."""
        det = make_det(sigma=3.5, is_muted=True)
        result = classify_detection(det, [det], {}, None)
        assert result["detection_sigma"] <= 3.0
        assert "muting" in result["method_notes"].lower()


# ── Constants Integrity ──────────────────────────────────────────────────────

class TestBiosigConstants:
    def test_confirmed_above_marginal(self):
        assert CONFIRMED_SIGMA > MARGINAL_SIGMA

    def test_target_molecules_complete(self):
        expected = {"h2o", "co2", "o3", "ch4", "co", "nh3", "so2"}
        assert set(TARGET_MOLECULES) == expected

    def test_triple_biosig_subset(self):
        assert TRIPLE_BIOSIG.issubset(set(TARGET_MOLECULES))

    def test_all_molecules_have_band_centers(self):
        for mol in TARGET_MOLECULES:
            assert mol in MOL_BAND_CENTERS, f"{mol} missing from MOL_BAND_CENTERS"
