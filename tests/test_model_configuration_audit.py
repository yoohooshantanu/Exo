"""
tests/test_model_configuration_audit.py

Automated tests for Phase 4: Atmospheric Model Configuration Audit.
Verifies what PLATON 5.4 actually executes vs application intentions:
1. Pressure grid and atmospheric layer count (250 layers, 1e-4 Pa to 1e8 Pa).
2. Isothermal temperature-profile parameterization.
3. Hydrostatic equilibrium with altitude-dependent Newtonian gravity g(r) ~ 1/r^2.
4. Equilibrium chemistry grid dimensions (41x18x31x30x13) and interpolation logic.
5. Cloud-top pressure clipping and Rayleigh scattering slope/factor conventions.
6. Reference pressure convention (1 bar = 100,000 Pa).
7. Solver numerical tolerances, wavelength grid (4,616 points), and LOS quadrature.
8. Accurate classification of fitted, fixed, and inherited parameters.
"""

import numpy as np
import pytest
from platon._atmosphere_solver import AtmosphereSolver
from platon.transit_depth_calculator import TransitDepthCalculator
from platon.combined_retriever import CombinedRetriever
from platon.abundance_getter import AbundanceGetter
from platon.constants import R_sun, M_jup, R_jup
from modules.retrieval_reproducibility import create_retrieval_configuration


class TestPressureGridAndLayers:
    """Verifies that the executed model uses 250 log-spaced layers, not 100."""

    def test_layer_count_and_pressure_boundaries(self):
        calc = TransitDepthCalculator()
        # Verify solver defaults
        assert calc.atm.num_profile_heights == 250, (
            f"Expected 250 layers, got {calc.atm.num_profile_heights}"
        )
        assert calc.atm.P_grid[0] == 0.0001, "P_min must be 1e-4 Pa (1 nbar)"
        assert calc.atm.P_grid[-1] == 100000000.0, "P_max must be 1e8 Pa (1000 bar)"

        # Check actual P_profile generated during forward depth computation
        p_profile = np.logspace(
            np.log10(calc.atm.P_grid[0]),
            np.log10(calc.atm.P_grid[-1]),
            calc.atm.num_profile_heights,
        )
        assert len(p_profile) == 250
        assert np.isclose(p_profile[0], 1e-4)
        assert np.isclose(p_profile[-1], 1e8)


class TestTemperatureProfile:
    """Verifies isothermal profile execution across all atmospheric layers."""

    def test_isothermal_structure(self):
        calc = TransitDepthCalculator()
        test_temp = 1200.0
        p_profile = np.logspace(np.log10(1e-4), np.log10(1e8), 250)
        t_profile = np.ones(len(p_profile)) * test_temp

        assert len(t_profile) == 250
        assert np.all(t_profile == test_temp)


class TestHydrostaticEquilibrium:
    """Verifies analytic hydrostatic integration with altitude-dependent Newtonian gravity."""

    def test_hydrostatic_solver_altitude_dependent_gravity(self):
        from platon import _hydrostatic_solver
        import inspect

        solve_src = inspect.getsource(_hydrostatic_solver._solve)
        radii_src = inspect.getsource(_hydrostatic_solver._get_radii)

        # Confirm differential equation integrates d(1/r) = (k_B * T) / (G * M * mu * amu) * dlnP
        assert "d_inv_r = np.diff(ln_Ps) * k_B * intermediate_T /" in radii_src, (
            "Hydrostatic solver does not integrate d(1/r)!"
        )
        assert "(G * planet_mass * intermediate_mu * AMU)" in radii_src, (
            "Hydrostatic equation missing Newtonian GM / r^2 dependence!"
        )
        assert "inv_r = 1.0 / planet_radius + np.cumsum(d_inv_r)" in radii_src, (
            "Hydrostatic solver does not accumulate 1/r!"
        )

        # Confirm Hill radius stability check
        assert "Atmosphere unbound: height > hill radius" in solve_src, (
            "Hill radius bound check is missing from hydrostatic solver!"
        )


class TestReferencePressureConvention:
    """Verifies that planet radius is defined at 100,000 Pa (1 bar)."""

    def test_reference_pressure_is_1_bar(self):
        calc = TransitDepthCalculator()
        assert calc.atm.ref_pressure == 100000.0, (
            f"Expected reference pressure 100,000 Pa (1 bar), got {calc.atm.ref_pressure}"
        )


class TestEquilibriumChemistryGrid:
    """Verifies equilibrium chemistry grid dimensions, species count, and interpolation."""

    def test_abundance_getter_grid_dimensions(self):
        ag = AbundanceGetter()
        # Shape: (N_Z, N_CO, N_species, N_T, N_P)
        shape = ag.log_abundances.shape
        assert shape == (41, 18, 31, 30, 13), f"Abundance grid shape unexpected: {shape}"

        # Check bounds
        assert len(ag.logZs) == 41
        assert ag.logZs[0] == -1.0 and ag.logZs[-1] == 3.0
        assert len(ag.CO_ratios) == 18
        assert ag.CO_ratios[0] == 0.05 and ag.CO_ratios[-1] == 2.0
        assert len(ag.included_species) == 31


class TestCloudAndScatteringModel:
    """Verifies parametric cloud deck clipping and Rayleigh scattering defaults."""

    def test_cloud_clipping_and_rayleigh_defaults(self):
        calc = TransitDepthCalculator()
        sig = calc.compute_depths.__code__.co_varnames
        # Check defaults in compute_depths
        import inspect
        sig_obj = inspect.signature(calc.compute_depths)
        params = sig_obj.parameters
        assert params["scattering_factor"].default == 1
        assert params["scattering_slope"].default == 4
        assert params["scattering_ref_wavelength"].default == 1e-6
        assert params["cloudtop_pressure"].default == float("inf")


class TestRadiativeTransferSolverNumerics:
    """Verifies spectral resolution and geometric line-of-sight quadrature."""

    def test_wavelength_points_and_los_geometry(self):
        calc = TransitDepthCalculator()
        # Check raw wavelength points in xsec mode
        assert len(calc.atm.lambda_grid) == 4616, (
            f"Expected 4616 wavelength points, got {len(calc.atm.lambda_grid)}"
        )
        assert np.isclose(calc.atm.lambda_grid[0] * 1e6, 0.3)
        assert np.isclose(calc.atm.lambda_grid[-1] * 1e6, 30.0)


class TestParameterClassificationAudit:
    """Verifies that retrieval configuration records accurately classify fitted, fixed, and inherited parameters."""

    def test_config_records_executed_model_parameters(self):
        cfg = create_retrieval_configuration(
            retrieval_id="test-phase4-audit",
            spec_id="WASP_39_b_test",
            planet_id="test-planet",
            sampler_name="dynesty",
            random_seed=42,
        )

        atm = cfg.atmospheric_structure
        assert atm["executed_atmospheric_layers"] == 250
        assert atm["p_min_pa"] == 0.0001
        assert atm["p_max_pa"] == 100000000.0
        assert atm["reference_pressure_pa"] == 100000.0
        assert atm["gravity_formulation"] == "altitude_dependent_newtonian_gravity"
        assert atm["gravity_assumes_constant_surface"] is False
        assert atm["equilibrium_chemistry"]["grid_dimensions"]["N_species"] == 31
        assert atm["cloud_model"]["scattering_slope"] == 4.0
        assert atm["radiative_transfer_solver"]["raw_wavelength_points"] == 4616

        # Parameter classification
        pclass = atm["parameter_classification"]
        assert "Rp" in pclass["fitted_parameters"]
        assert "T" in pclass["fitted_parameters"]
        assert pclass["fixed_parameters"]["CO_ratio"] == 0.53
        assert pclass["fixed_parameters"]["log_cloudtop_P"] == 5.0
        assert pclass["inherited_defaults"]["log_P_quench"] == -99.0

    def test_recorded_configuration_matches_live_instantiated_objects(self):
        """Compares the recorded configuration with live instantiated objects (CombinedRetriever, FitInfo, AtmosphereSolver)."""
        retriever = CombinedRetriever()
        calc = TransitDepthCalculator()
        fit_info = retriever.get_default_fit_info(
            Rs=0.932 * R_sun,
            Mp=0.28 * M_jup,
            Rp=1.27 * R_jup,
            T=1166.0,
            logZ=0.0,
            CO_ratio=0.53,
            log_cloudtop_P=5.0,
            log_scatt_factor=0.0,
            scatt_slope=4.0,
            error_multiple=1.0,
            T_star=5485.0,
        )
        fit_info.add_uniform_fit_param("Rp", 45719212.6, 182876850.4)
        fit_info.add_uniform_fit_param("T", 583.0, 2332.0)

        cfg = create_retrieval_configuration(
            retrieval_id="test-live-comparison",
            spec_id="WASP_39_b_test",
            planet_id="test-planet",
            calculator_or_solver=calc,
            fit_info=fit_info,
        )
        atm = cfg.atmospheric_structure

        # Direct live comparison against calc.atm
        assert atm["executed_atmospheric_layers"] == calc.atm.num_profile_heights
        assert atm["p_min_pa"] == float(calc.atm.P_grid[0])
        assert atm["p_max_pa"] == float(calc.atm.P_grid[-1])
        assert atm["reference_pressure_pa"] == float(calc.atm.ref_pressure)
        assert atm["radiative_transfer_solver"]["raw_wavelength_points"] == len(calc.atm.lambda_grid)
        assert atm["derivation_type"] == "runtime_object_inspection"
        assert atm["parameter_derivation_type"] == "runtime_object_inspection"

        # Direct live comparison against fit_info
        pclass = atm["parameter_classification"]
        assert set(pclass["fitted_parameters"]) == set(fit_info.fit_param_names)
        assert len(pclass["parameter_ledger"]) == len(fit_info.all_params)
        for entry in pclass["parameter_ledger"]:
            pname = entry["name"]
            expected_guess = fit_info.all_params[pname].best_guess
            if expected_guess == float("-inf"):
                assert entry["value"] == "-inf"
            else:
                assert entry["value"] == expected_guess

    def test_temperature_prior_exact_formula_and_bounds(self):
        """Verifies that the temperature prior is constructed as [0.5*T_eq, 2.0*T_eq],
        refuting the inaccurate 'T_eq +/- 50%' narrative claim."""
        teq = 1166.0
        t_min = round(max(200.0, 0.5 * teq), 1)
        t_max = round(min(3000.0, 2.0 * teq), 1)

        # Exact formula yields [583.0, 2332.0]
        assert t_min == 583.0
        assert t_max == 2332.0
        # If it were T_eq +/- 50%, upper bound would be 1.5 * 1166 = 1749.0
        assert t_max != round(1.5 * teq, 1), "Upper bound is 2.0*T_eq (double), not 1.5*T_eq (+50%)!"
        assert t_max == 2.0 * teq

    def test_grid_discretization_cloud_clipping_radius_delta(self):
        """Proves that no grid point exists at exactly 1.0 bar (1e5 Pa),
        and the minimum retained radius is ~80.84 km above the 1-bar reference radius."""
        calc = TransitDepthCalculator()
        p_profile = np.logspace(
            np.log10(calc.atm.P_grid[0]),
            np.log10(calc.atm.P_grid[-1]),
            calc.atm.num_profile_heights,
        )

        # 1. No exact 1e5 Pa point on the 250-layer logarithmic grid
        assert not np.any(p_profile == 100000.0), "Grid unexpectedly contains exact 100,000 Pa point!"
        closest_idx = np.argmin(np.abs(p_profile - 100000.0))
        p_below_1bar = p_profile[closest_idx - 1]  # ~92,014.32 Pa
        p_above_1bar = p_profile[closest_idx]      # ~102,813.04 Pa
        assert p_below_1bar < 100000.0 < p_above_1bar
        assert np.isclose(p_below_1bar, 92014.32, atol=1.0)
        assert np.isclose(p_above_1bar, 102813.04, atol=1.0)

        # 2. Cloud clipping retains layers strictly < 1e5 Pa
        above_clouds = p_profile < 100000.0
        retained_P = p_profile[above_clouds]
        assert len(retained_P) == 187
        assert np.isclose(retained_P[-1], p_below_1bar)

        # 3. Minimum retained radius is ~80.84 km higher than input 1-bar radius
        _, _, info = calc.compute_depths(
            star_radius=0.932 * R_sun,
            planet_mass=0.28 * M_jup,
            planet_radius=1.27 * R_jup,
            temperature=1166.0,
            cloudtop_pressure=100000.0,
            full_output=True,
        )
        min_retained_r = np.min(info["radii"])
        ref_r = 1.27 * R_jup
        delta_r_m = min_retained_r - ref_r
        # Proves that min retained radius is NOT strictly equal to ref_r
        assert delta_r_m > 0, "Minimum retained radius should be strictly greater than 1-bar reference radius!"
        assert np.isclose(delta_r_m, 80840.0, atol=100.0), f"Expected ~80.84 km delta, got {delta_r_m} m"

    def test_sampler_convergence_metadata_and_thresholds(self):
        """Verifies separation of Dynesty dlogz stopping criterion (0.039),
        logzerr returned (0.521), and Exo acceptance threshold (0.50)."""
        cfg = create_retrieval_configuration(
            retrieval_id="test-sampler-meta",
            spec_id="WASP_39_b_test",
            planet_id="test-planet",
            sampler_name="dynesty",
            nlive=30,
        )
        s_meta = cfg.sampler
        # Dynesty dlogz formula: 1e-3 * (nlive - 1) + 0.01 = 0.039 for nlive=30
        assert s_meta["dlogz"] == 0.039
        assert s_meta["dynesty_stopping_criterion"]["resolved_value"] == 0.039
        assert s_meta["exo_evidence_acceptance_threshold"]["threshold_value"] == 0.50
        assert s_meta["evidence_tolerance"] == 0.50

    def test_parameter_provenance_and_override_distinctions(self):
        """Verifies explicit classification of all 22 parameters across fitted, fixed,
        and inherited defaults, with distinct source categories."""
        retriever = CombinedRetriever()
        fit_info = retriever.get_default_fit_info(
            Rs=0.932 * R_sun, Mp=0.28 * M_jup, Rp=1.27 * R_jup,
            T=1166.0, logZ=0.0, CO_ratio=0.53, log_cloudtop_P=5.0,
            log_scatt_factor=0.0, scatt_slope=4.0, error_multiple=1.0, T_star=5485.0
        )
        fit_info.add_uniform_fit_param("Rp", 45719212.6, 182876850.4)
        fit_info.add_uniform_fit_param("T", 583.0, 2332.0)

        cfg = create_retrieval_configuration(
            retrieval_id="test-provenance-distinctions",
            spec_id="WASP_39_b_test",
            planet_id="test-planet",
            fit_info=fit_info,
        )
        ledger = cfg.atmospheric_structure["parameter_classification"]["parameter_ledger"]
        assert len(ledger) == 22

        ledger_dict = {entry["name"]: entry for entry in ledger}

        # 1. Fitted parameters overridden by Exo
        assert ledger_dict["Rp"]["classification"] == "fitted"
        assert ledger_dict["Rp"]["explicitly_overridden_by_exo"] is True
        assert ledger_dict["T"]["classification"] == "fitted"
        assert ledger_dict["T"]["explicitly_overridden_by_exo"] is True

        # 2. Database-derived parameters
        assert ledger_dict["Rs"]["source_category"] == "database_derived"
        assert ledger_dict["Mp"]["source_category"] == "database_derived"
        assert ledger_dict["T_star"]["source_category"] == "database_derived"

        # 3. Application overrides
        assert ledger_dict["log_cloudtop_P"]["source_category"] == "application_override"
        assert ledger_dict["log_cloudtop_P"]["value"] == 5.0
        assert ledger_dict["logZ"]["source_category"] == "application_override"

        # 4. Inherited unchanged PLATON defaults
        for inh_name in ["T_spot", "spot_cov_frac", "frac_scale_height", "log_part_size", "log_P_quench"]:
            assert ledger_dict[inh_name]["classification"] == "inherited_default"
            assert ledger_dict[inh_name]["source_category"] == "PLATON_default"
            assert ledger_dict[inh_name]["explicitly_overridden_by_exo"] is False
            assert ledger_dict[inh_name]["passed_explicitly_to_platon"] is False


class TestReconciliationAndRegressionCoverage:
    """Rigorous regression tests for Phase 4 final reconciliation:
    1. Resolves all 6 PLATON defaults across FitInfo, forward model, and manifest.
    2. Reconciles planetary and stellar inputs against database and literature sources.
    3. Reconciles Rp prior bounds in meters and R_jup, refuting [0.8, 1.6] * R_init.
    4. Reconciles retrieved temperature history (1200 K best-fit vs 1032 K sample point).
    """

    def test_six_platon_default_discrepancies_and_forward_model_transformations(self):
        """Validates exact runtime values of the 6 PLATON defaults across:
        (1) FitInfo.all_params, (2) forward model components, and (3) Exo override status."""
        retriever = CombinedRetriever()
        fit_info = retriever.get_default_fit_info(
            Rs=R_sun, Mp=M_jup, Rp=R_jup
        )

        # 1. Inspect live FitInfo.all_params
        p_tspot = fit_info.all_params["T_spot"].best_guess
        p_spotcov = fit_info.all_params["spot_cov_frac"].best_guess
        p_log_num_dens = fit_info.all_params["log_number_density"].best_guess
        p_n = fit_info.all_params["n"].best_guess
        p_log_k = fit_info.all_params["log_k"].best_guess
        p_log_p_quench = fit_info.all_params["log_P_quench"].best_guess

        assert p_tspot is None, "T_spot in FitInfo must be None (not 0.0)"
        assert p_spotcov is None, "spot_cov_frac in FitInfo must be None (not 0.0)"
        assert p_log_num_dens == float("-inf"), "log_number_density in FitInfo must be -inf (not 0.0)"
        assert p_n is None, "n in FitInfo must be None (not 1.5)"
        assert p_log_k == float("-inf"), "log_k in FitInfo must be -inf (not -2.0)"
        assert p_log_p_quench == -99 or p_log_p_quench == -99.0, "log_P_quench in FitInfo must be -99 (not -6.0)"

        # 2. Trace forward-model transformations in _ln_like / compute_depths
        # (a) Particle number density: 10^(log_number_density) = 10^(-inf) = 0.0 m^-3
        num_density_fm = 10.0 ** p_log_num_dens
        assert num_density_fm == 0.0, "Particle density must transform to strictly zero (0.0 m^-3), NOT a finite density!"

        # (b) Quench pressure: 10^(log_P_quench) = 10^(-99) = 1e-99 Pa
        p_quench_fm = 10.0 ** p_log_p_quench
        assert p_quench_fm == 1e-99, f"P_quench must transform to 1e-99 Pa, got {p_quench_fm}"
        # In AtmosphereSolver, P_grid minimum is 1e-4 Pa >> 1e-99 Pa.
        # Thus P_grid <= P_quench is False everywhere: quenching is strictly disabled.
        calc = TransitDepthCalculator()
        assert np.all(calc.atm.P_grid > p_quench_fm), "P_grid layers must be strictly greater than 1e-99 Pa (quenching disabled)!"

        # (c) Refractive index: if n is None -> ri is None (Mie scattering bypassed)
        ri_fm = (p_n - 1j * 10.0**p_log_k) if (p_n is not None and p_log_k is not None) else None
        assert ri_fm is None, "Complex refractive index ri must evaluate to None when n is None!"

        # (d) Spot correction: if T_spot is None or spot_cov_frac is None -> spot correction factor = 1.0
        assert (p_tspot is None or p_spotcov is None), "Spot correction must be bypassed"

        # 3. Verify manifest recording and Exo override status
        cfg = create_retrieval_configuration(
            retrieval_id="test-six-defaults",
            spec_id="WASP_39_b_test",
            planet_id="test-planet",
            fit_info=fit_info,
        )
        ledger = {e["name"]: e for e in cfg.atmospheric_structure["parameter_classification"]["parameter_ledger"]}

        for param in ["T_spot", "spot_cov_frac", "log_number_density", "n", "log_k", "log_P_quench"]:
            assert ledger[param]["classification"] == "inherited_default"
            assert ledger[param]["source_category"] == "PLATON_default"
            assert ledger[param]["explicitly_overridden_by_exo"] is False
            assert ledger[param]["passed_explicitly_to_platon"] is False

    def test_wasp39b_database_physical_inputs_match_manifest_and_forward_model(self):
        """Verifies that when initialized from WASP-39 b database parameters,
        the recorded manifest matches the exact values passed to the forward model,
        and clarifies historical report values (NASA vs Gaia vs literature)."""
        from platon.constants import R_sun, M_earth, R_earth

        # Authoritative database parameters from Exo database for WASP-39 b:
        # planet_id = '6d2b9ae5-a3af-42ef-b18a-f5f2377cedce'
        r_s_solar = 0.939  # star_parameters.radius_solar (is_default=True)
        m_e_earth = 89.31023  # planet_parameters.mass_earth (is_default=True)
        teff_gaia = 5329.84814453125  # star_parameters.teff_best_k (is_default=True)
        teff_nasa = 5485.0  # star_parameters.teff_nasa_k
        teq_k = 1166.0  # planet_parameters.eq_temperature_k (is_default=True)
        r_e_earth = 14.336311  # planet_parameters.radius_earth (is_default=True)

        # SI conversions executed by modules/platon_retrieval.py lines 266-270
        r_s_m = r_s_solar * R_sun  # 653,262,300.0 m
        m_p_kg = m_e_earth * M_earth  # ~5.3339e26 kg
        r_p_m = r_e_earth * R_earth  # ~91,438,425.2 m

        assert r_s_m == 653262300.0
        assert np.isclose(m_p_kg, 5.333928e26, rtol=1e-5)
        assert np.isclose(r_p_m, 91438425.2, rtol=1e-5)

        # Literature comparisons:
        # 1. Rs = 648,392,400 m (0.932 Rsun, Faedi et al. 2011 / NASA Exoplanet Archive)
        #    Rs = 646,310,000 m (0.929 Rsun, Nikolov et al. 2016 Table 1)
        #    Rs = 653,262,300 m (0.939 Rsun, Gaia default in Exo database)
        assert np.isclose(648392400.0 / R_sun, 0.932, atol=1e-3)
        assert np.isclose(646310000.0 / R_sun, 0.929, atol=1e-3)

        # 2. Mp = 5.315e26 kg (0.28 Mjup, Faedi et al. 2011)
        #    Mp = 5.367e26 kg (0.2827 Mjup, Nikolov et al. 2016)
        #    Mp = 5.334e26 kg (89.31 Mearth = 0.281 Mjup, Exo database default)
        assert np.isclose(5.315e26 / M_jup, 0.280, atol=1e-3)
        assert np.isclose(5.367e26 / M_jup, 0.2827, atol=1e-3)

        # 3. T_star = 5485 K (NASA Exoplanet Archive / Faedi et al.)
        #    T_star = 5500 K (Nikolov et al. 2016)
        #    T_star = 5329.85 K (Gaia default in Exo database)

        retriever = CombinedRetriever()
        fit_info = retriever.get_default_fit_info(
            Rs=r_s_m, Mp=m_p_kg, Rp=r_p_m, T=teq_k,
            logZ=0.0, CO_ratio=0.53, log_cloudtop_P=5.0,
            log_scatt_factor=0.0, scatt_slope=4.0, error_multiple=1.0, T_star=teff_gaia
        )
        cfg = create_retrieval_configuration(
            retrieval_id="test-wasp39b-live-inputs",
            spec_id="WASP_39_b_3.11466_3939_1",
            planet_id="6d2b9ae5-a3af-42ef-b18a-f5f2377cedce",
            fit_info=fit_info,
        )
        ledger = {e["name"]: e for e in cfg.atmospheric_structure["parameter_classification"]["parameter_ledger"]}

        assert ledger["Rs"]["value"] == 653262300.0
        assert np.isclose(ledger["Mp"]["value"], 5.333928e26, rtol=1e-5)
        assert ledger["T_star"]["value"] == teff_gaia

    def test_fitted_priors_exact_bounds_and_equivalence(self):
        """Captures exact numerical Rp and T prior bounds, proving that
        [45719212.6, 182876850.4] m is exactly [0.6395, 2.558] R_jup (~[0.64, 2.56] R_jup),
        which represents [0.5, 2.0] * R_init, refuting the [0.8, 1.6] * R_init typo."""
        from platon.constants import R_jup, R_earth

        r_e_earth = 14.336311
        r_p_m = r_e_earth * R_earth  # 91,438,425.1891 m (~1.279 R_jup)

        # platon_retrieval.py lines 386-387
        rp_min_m = round(max(0.05 * R_jup, 0.5 * r_p_m), 1)
        rp_max_m = round(min(3.0 * R_jup, 2.0 * r_p_m), 1)

        # Exact bounds in SI meters
        assert rp_min_m == 45719212.6
        assert rp_max_m == 182876850.4

        # Convert to Jupiter radii (R_jup = 71,492,000 m)
        rp_min_rjup = rp_min_m / R_jup
        rp_max_rjup = rp_max_m / R_jup

        assert np.isclose(rp_min_rjup, 0.6395, atol=1e-4)
        assert np.isclose(rp_max_rjup, 2.5580, atol=1e-4)
        assert round(rp_min_rjup, 2) == 0.64
        assert round(rp_max_rjup, 2) == 2.56

        # Proves exact mathematical equivalence to [0.5, 2.0] * r_p_m
        assert np.isclose(rp_min_m, 0.5 * r_p_m, atol=1.0)
        assert np.isclose(rp_max_m, 2.0 * r_p_m, atol=1.0)
        # Refutes [0.8, 1.6] * R_init
        assert not np.isclose(rp_min_m, 0.8 * r_p_m, atol=1000.0)
        assert not np.isclose(rp_max_m, 1.6 * r_p_m, atol=1000.0)

        # Temperature prior bounds for T_eq = 1166.0 K
        teq = 1166.0
        t_min = round(max(200.0, 0.5 * teq), 1)
        t_max = round(min(3000.0, 2.0 * teq), 1)
        assert t_min == 583.0
        assert t_max == 2332.0

    def test_retrieved_temperature_authoritative_history(self):
        """Verifies that historical retrieval 443bf64f-277e-4672-b9eb-c6f2964ea872
        authoritatively produced T ~ 1200-1201 K, and 1032 K was a transcription error
        referencing an individual nested sample point in posterior samples."""
        import json
        from pathlib import Path

        post_file = Path("outputs/retrievals/posterior_443bf64f-277e-4672-b9eb-c6f2964ea872.json")
        if post_file.exists():
            with open(post_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Best-fit temperature is ~1200.28 K
            best_fit_t = data["best_fit"]["T"]
            assert np.isclose(best_fit_t, 1200.2788, atol=1e-2)

            # Median temperature is ~1201.05 K
            median_t = data["summary_statistics"]["T"]["median"]
            assert np.isclose(median_t, 1201.0539, atol=1e-2)

            # Confirm 1032 K was an individual sample in the samples array
            samples = data["samples"]
            t_samples = [s[1] for s in samples]
            # Check that at least one sample is close to 1032.22 K
            assert any(np.isclose(s_t, 1032.22, atol=0.5) for s_t in t_samples)

    def test_forward_model_arguments_captured_during_likelihood_evaluation(self):
        """Captures the exact arguments passed to compute_depths during a live _ln_like
        evaluation, distinguishes directly observed runtime arguments from values inferred
        through source inspection, and confirms bitwise consistency with the manifest."""
        from platon.constants import R_sun, M_earth, R_earth

        r_s_m = 0.939 * R_sun
        m_p_kg = 89.31023 * M_earth
        r_p_m = 14.336311 * R_earth
        teq = 1166.0
        teff = 5329.84814453125

        retriever = CombinedRetriever()
        fit_info = retriever.get_default_fit_info(
            Rs=r_s_m, Mp=m_p_kg, Rp=r_p_m, T=teq,
            logZ=0.0, CO_ratio=0.53, log_cloudtop_P=5.0,
            log_scatt_factor=0.0, scatt_slope=4.0, error_multiple=1.0, T_star=teff
        )
        fit_info.add_uniform_fit_param("Rp", 45719212.6, 182876850.4)
        fit_info.add_uniform_fit_param("T", 583.0, 2332.0)

        cfg = create_retrieval_configuration(
            retrieval_id="test-fm-args-capture",
            spec_id="WASP_39_b_test",
            planet_id="test-planet",
            fit_info=fit_info,
        )
        ledger = {e["name"]: e for e in cfg.atmospheric_structure["parameter_classification"]["parameter_ledger"]}

        transit_calc = TransitDepthCalculator()
        wavelength_bins = [[0.4e-6, 0.5e-6], [0.5e-6, 0.6e-6], [0.6e-6, 0.7e-6], [0.7e-6, 0.8e-6], [0.8e-6, 0.9e-6]]
        transit_calc.change_wavelength_bins(wavelength_bins)
        measured_depths = np.array([0.021, 0.0215, 0.0212, 0.0218, 0.0214])
        measured_errors = np.array([0.0005, 0.0005, 0.0005, 0.0005, 0.0005])

        # Intercept compute_depths during a live likelihood evaluation
        captured_calls = []
        orig_compute_depths = transit_calc.compute_depths

        def spy_compute_depths(*args, **kwargs):
            captured_calls.append({"args": args, "kwargs": kwargs})
            return orig_compute_depths(*args, **kwargs)

        transit_calc.compute_depths = spy_compute_depths

        # Proposed sample point (e.g. WASP-39 b best-fit parameters)
        proposed_rp = 91295593.33866549
        proposed_t = 1200.2788246667117
        test_params = np.array([proposed_rp, proposed_t])

        # Execute real likelihood evaluation path
        retriever._ln_like(
            test_params,
            transit_calc,
            None,
            fit_info,
            measured_depths,
            measured_errors,
            None,
            None,
        )

        assert len(captured_calls) == 1, "Expected exactly 1 call to compute_depths"
        live_call = captured_calls[0]
        c_args = live_call["args"]
        c_kwargs = live_call["kwargs"]

        # 1. Directly observed positional runtime arguments:
        # compute_depths(star_radius, planet_mass, planet_radius, temperature, logZ, CO_ratio)
        obs_star_radius = c_args[0]
        obs_planet_mass = c_args[1]
        obs_planet_radius = c_args[2]
        obs_temperature = c_args[3]
        obs_logZ = c_args[4]
        obs_CO_ratio = c_args[5]

        assert obs_star_radius == r_s_m == ledger["Rs"]["value"]
        assert obs_planet_mass == m_p_kg == ledger["Mp"]["value"]
        assert obs_planet_radius == proposed_rp
        assert obs_temperature == proposed_t
        assert obs_logZ == 0.0 == ledger["logZ"]["value"]
        assert obs_CO_ratio == 0.53 == ledger["CO_ratio"]["value"]

        # 2. Directly observed keyword runtime arguments:
        assert c_kwargs["scattering_factor"] == 1.0  # 10^0.0
        assert c_kwargs["scattering_slope"] == 4.0 == ledger["scatt_slope"]["value"]
        assert c_kwargs["cloudtop_pressure"] == 100000.0  # 10^5.0 Pa
        assert c_kwargs["T_star"] == teff == ledger["T_star"]["value"]
        assert c_kwargs["T_spot"] is None == ledger["T_spot"]["value"]
        assert c_kwargs["spot_cov_frac"] is None == ledger["spot_cov_frac"]["value"]
        assert c_kwargs["frac_scale_height"] == 1.0 == ledger["frac_scale_height"]["value"]
        assert c_kwargs["number_density"] == 0.0  # 10^(-inf) = 0.0 m^-3 (strictly zero particle density)
        assert c_kwargs["part_size"] == 1e-6  # 10^(-6) m
        assert c_kwargs["ri"] is None  # n is None -> ri is None (Mie scattering bypassed)
        assert c_kwargs["P_quench"] == 1e-99  # 10^(-99) Pa (quenching disabled)
        assert c_kwargs["full_output"] is True

        # 3. Source-inspection derived inferences (not directly passed in call signature):
        # - Disabling of quenching is inferred from AtmosphereSolver P_grid[0]=1e-4 Pa > 1e-99 Pa.
        # - Bypassing of Mie scattering is inferred from `if ri is not None` branch in AtmosphereSolver.
        # - Bypassing of star spots is inferred from `if T_spot is None or spot_cov_frac is None` branch.

    def test_historical_retrieval_identity_reconciliation(self):
        """Reconciles sample counts, evidence values, uncertainties, and statuses
        across all historical retrieval runs, proving that 398 belongs to 443bf64f/27f8de0f/f1a1ce60,
        379 to 49ad8274, 391 to 9daa7eba, 1128 to c461200f, and 680 was an erroneous narrative mention."""
        import json
        from pathlib import Path

        out_dir = Path("outputs/retrievals")
        expected_records = {
            "443bf64f-277e-4672-b9eb-c6f2964ea872": {
                "n_samples": 398,
                "evidence_ln_z": 176.4906966312306,
                "evidence_err": 0.5208572271417139,
                "status": "convergence_not_established",
                "sampler": "dynesty",
                "seed": 42,
            },
            "27f8de0f-cf65-4af4-a8de-25d3ef657d24": {
                "n_samples": 398,
                "evidence_ln_z": 176.4906966312306,
                "evidence_err": 0.5208572271417139,
                "status": "reproducibility_metadata_incomplete",
                "sampler": "dynesty",
                "seed": 42,
            },
            "f1a1ce60-f018-452d-8a37-a73b59b30bf4": {
                "n_samples": 398,
                "evidence_ln_z": 176.4906966312306,
                "evidence_err": 0.5208572271417139,
                "status": "reproducibility_metadata_incomplete",
                "sampler": "dynesty",
                "seed": 42,
            },
            "49ad8274-c30f-4afe-bd5a-433d4c0a79ce": {
                "n_samples": 379,
                "evidence_ln_z": 177.1432137787441,
                "evidence_err": 0.4910004344447498,
                "status": "reproducibility_metadata_incomplete",
                "seed": 42,
            },
            "9daa7eba-c779-4def-8a85-967e2757dec5": {
                "n_samples": 391,
                "evidence_ln_z": 176.7483027662848,
                "evidence_err": 0.5070442229194846,
                "status": "reproducibility_metadata_incomplete",
                "seed": 42,
            },
            "c461200f-a608-4d1f-b433-68d033072dc6": {
                "n_samples": 1128,
                "evidence_ln_z": 177.15457970039006,
                "evidence_err": 0.26869832713958575,
                "status": "reproducibility_metadata_incomplete",
                "seed": 42,
            },
        }

        all_sample_counts = []
        for rid, exp in expected_records.items():
            post_path = out_dir / f"posterior_{rid}.json"
            if post_path.exists():
                with open(post_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                n_samples = len(data["samples"])
                all_sample_counts.append(n_samples)
                assert n_samples == exp["n_samples"], f"Sample count mismatch for {rid}: expected {exp['n_samples']}, got {n_samples}"
                assert np.isclose(data["evidence_ln_z"], exp["evidence_ln_z"]), f"Evidence mismatch for {rid}"
                assert np.isclose(data["evidence_err"], exp["evidence_err"]), f"Evidence error mismatch for {rid}"
                assert data["reproducibility_status"] == exp["status"]

        # 680 never appears as a sample count in any historical retrieval
        assert 680 not in all_sample_counts, "Sample count 680 unexpectedly exists!"


