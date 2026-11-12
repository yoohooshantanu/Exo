"""
Tests for modules/biosignature_detector.py

Covers: classify_detection logic, abiotic reasoning, stellar contamination
penalties, instrument weighting, tier classification, and constants integrity.
"""
import pytest

from modules.biosignature_detector import (
    unmix_spectrum,
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
        assert result["tier"] in ("screening_candidate", "confirmed")

    def test_marginal_tier(self):
        """Moderate sigma + 2 lines → marginal (requires trials-corrected sigma >= 2.0)."""
        det = make_det(sigma=2.8, matches=2)
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
        """H2O + CH4 + O3 all confirmed → candidate photochemical disequilibrium flagged without claiming abiotic ruled out."""
        h2o = make_det(molecule="h2o", sigma=4.0)
        ch4 = make_det(molecule="ch4", sigma=4.0)
        o3 = make_det(molecule="o3", sigma=4.0)
        all_dets = [h2o, ch4, o3]
        result = classify_detection(h2o, all_dets, {}, None)
        assert result["abiotic_ruled_out"] is None  # Cannot rule out abiotic origins without stellar UV & volcanic modeling
        assert "disequilibrium" in result["method_notes"].lower()

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


# ── Unmix Spectrum Tests ───────────────────────────────────────────────────

import numpy as np
import pandas as pd

class TestUnmixSpectrum:
    def test_unmix_spectrum_executes_without_name_error(self):
        """Verify unmix_spectrum runs cleanly without NameError: marginal_sigma."""
        wl = np.linspace(1.0, 5.0, 100)
        depth = np.full(100, 1000.0) + np.random.normal(0, 5.0, 100)
        err = np.full(100, 10.0)
        df_spec = pd.DataFrame({
            "wavelength_um": wl,
            "depth_ppm": depth,
            "depth_err_upper": err,
            "depth_err_lower": err,
        })
        
        # Mock H2O and CO2 templates with discrete peaks
        t_h2o = np.zeros(100)
        t_h2o[20:25] = [20, 50, 100, 50, 20]
        t_h2o[60:65] = [15, 40, 80, 40, 15]
        
        t_co2 = np.zeros(100)
        t_co2[40:45] = [30, 70, 150, 70, 30]
        
        templates = {
            "h2o": pd.DataFrame({"wavelength_um": wl, "flux": t_h2o}),
            "co2": pd.DataFrame({"wavelength_um": wl, "flux": t_co2}),
        }
        phys = {}
        
        # Must execute without raising NameError
        detections = unmix_spectrum(df_spec, templates, phys)
        assert isinstance(detections, list)

    def test_unmix_spectrum_injection_recovery(self):
        """Verify injected template is recovered with positive significance."""
        wl = np.linspace(1.0, 5.0, 100)
        t_flux = np.zeros(100)
        t_flux[30:35] = [50, 120, 300, 120, 50]
        t_flux[70:75] = [40, 100, 250, 100, 40]
        
        # Inject H2O absorption signal
        depth = np.full(100, 1000.0) + t_flux + np.random.normal(0, 5.0, 100)
        err = np.full(100, 10.0)
        df_spec = pd.DataFrame({
            "wavelength_um": wl,
            "depth_ppm": depth,
            "depth_err_upper": err,
            "depth_err_lower": err,
        })
        templates = {
            "h2o": pd.DataFrame({"wavelength_um": wl, "flux": t_flux}),
        }
        phys = {}
        
        detections = unmix_spectrum(df_spec, templates, phys)
        assert len(detections) == 1
        assert detections[0]["molecule"] == "h2o"
        assert detections[0]["detection_sigma"] > 3.0
        assert detections[0]["template_feature_peak_count"] >= 1

    def test_classify_detection_trials_factor_correction(self):
        """Verify trials-corrected sigma is strictly <= raw sigma for M=7 candidate molecules."""
        det = make_det(sigma=4.0, matches=4)
        result = classify_detection(det, [det], {}, None)
        assert "raw_sigma" in result
        assert "trials_corrected_sigma" in result
        assert result["raw_sigma"] == 4.0
        assert result["trials_corrected_sigma"] <= result["raw_sigma"]
        assert result["trials_corrected_sigma"] >= 3.0  # 4 sigma still highly significant after Sidak correction

    def test_tier_governed_by_trials_corrected_sigma(self):
        """
        Verify that detection tiers are strictly governed by trials-corrected sigma,
        so that a nominal 3.0σ raw detection (which drops to ~2.35σ under M=7 trials factor)
        does not falsely qualify as a screening_candidate.
        """
        # Raw 3.0σ with 3 matches:
        det_3sigma = make_det(sigma=3.0, matches=3)
        res_3sigma = classify_detection(det_3sigma, [det_3sigma], {}, None)
        assert res_3sigma["trials_corrected_sigma"] < 3.0
        assert res_3sigma["tier"] == "marginal", "Raw 3.0σ must drop to marginal after M=7 trials correction"

        # Strong 4.0σ with 3 matches (trials-corrected >= 3.0σ):
        det_4sigma = make_det(sigma=4.0, matches=3)
        res_4sigma = classify_detection(det_4sigma, [det_4sigma], {}, None)
        assert res_4sigma["trials_corrected_sigma"] >= 3.0
        assert res_4sigma["tier"] == "screening_candidate", ">=3.0σ trials-corrected must qualify as screening_candidate"

    def test_correlated_red_noise_null_hypothesis(self):
        """
        Null hypothesis test under correlated (red) noise.
        Simulate 50 red-noise spectra (AR(1) phi=0.65) and verify that GLS pre-whitening
        and Sidak trials correction maintain false positive screening_candidate rate < 5%.
        """
        np.random.seed(123)
        wl = np.linspace(1.0, 5.0, 100)
        phi = 0.65
        
        # 3 distinct molecular templates
        templates = {
            "h2o": pd.DataFrame({"wavelength_um": wl, "flux": np.exp(-0.5 * ((wl - 2.5) / 0.1)**2) * 100.0}),
            "ch4": pd.DataFrame({"wavelength_um": wl, "flux": np.exp(-0.5 * ((wl - 3.3) / 0.1)**2) * 100.0}),
            "co2": pd.DataFrame({"wavelength_um": wl, "flux": np.exp(-0.5 * ((wl - 4.3) / 0.1)**2) * 100.0}),
        }
        phys = {}

        candidate_count = 0
        n_trials = 50

        for _ in range(n_trials):
            noise = np.zeros(100)
            white = np.random.normal(0, 5.0, 100)
            noise[0] = white[0]
            for t in range(1, 100):
                noise[t] = phi * noise[t-1] + np.sqrt(1 - phi**2) * white[t]

            depth = np.full(100, 1000.0) + noise
            err = np.full(100, 5.0)
            df_spec = pd.DataFrame({
                "wavelength_um": wl,
                "depth_ppm": depth,
                "depth_err_upper": err,
                "depth_err_lower": err,
            })

            dets = unmix_spectrum(df_spec, templates, phys)
            for d in dets:
                classified = classify_detection(d, dets, phys, None)
                if classified["tier"] == "screening_candidate":
                    candidate_count += 1
                    break

        false_positive_rate = candidate_count / n_trials
        assert false_positive_rate < 0.05, f"False positive rate under red noise ({false_positive_rate:.1%}) must be < 5%"
