# Exo Scientific Methodology & Reproducibility Guide

**Version**: `1.0.0-review`  
**Status**: Open-source scientific prototype seeking independent methodological evaluation.  
**Repository**: [https://github.com/yoohooshantanu/Exo](https://github.com/yoohooshantanu/Exo)

---

## 1. Overview & Architecture

Exo is a modular exoplanet characterization and discovery prioritization platform integrating six scientific engines:

1. **Habitability Scorer (`modules/habitability_scorer.py` · v5.0.0)**: Computes physical Earth similarity (Schulze-Makuch ESI) and environmental retention metrics (Luger & Barnes XUV loss, tidal locking, eccentricity) gated by an explicit continuous Fulton radius valley terrestrial surface transition ($P_{\text{rocky}}$).
2. **Orbital Gap Candidate Generator (`modules/orbital_gap_predictor.py` · v3.1.0)**: Evaluates dynamically permitted orbital niches in multi-planet architectures using Gladman mutual Hill radius clearance ($\Delta > 18 R_H$) and REBOUND MEGNO ($\langle Y \rangle \le 2.2$) symplectic N-body integrations.
3. **Biosignature Screening Engine (`modules/biosignature_detector.py` · v3.0.0)**: Performs regularized GLS molecular template unmixing against HITRAN/ExoMol cross-sections ($\text{H}_2\text{O}$, $\text{CO}_2$, $\text{CH}_4$, $\text{O}_3$, $\text{SO}_2$, $\text{NH}_3$, $\text{CO}$) with Prais-Winsten AR(1) de-correlation, 12-scale-height physical bounds, and strict Šidák multiple-testing correction ($M=7$) governing candidate tiers.
4. **Anomaly Detector (`modules/anomaly_detector.py` · v1.0.0)**: Flags astrophysical and catalog outliers across Zeng et al. (2016) interior composition curves, short-period high-eccentricity systems, and population density bounds.
5. **Taxonomy Engine (`modules/taxonomy_engine.py` · v1.0.0)**: Performs unsupervised HDBSCAN clustering over normalized planetary parameters (radius, density, period, equilibrium temperature, semi-major axis) to identify uncataloged planetary archetypes.
6. **Synthesis Engine (`modules/synthesis_engine.py` · v2.0.0)**: Executes multi-table cross-module joins generating cross-domain alert feeds (Anomalous + Habitable, Gap Candidate + Biosignature, Novel Archetype).

*(Atmospheric property retrieval is supported asynchronously by the PLATON Bayesian nested sampling worker in `modules/platon_retrieval.py`.)*

---

## 2. Validation Framework & Empirical Benchmarks

Exo evaluates its pipelines against four database-backed validation tracks recorded with complete audit provenance:

### Track 1: External Published Baseline (UPR ESI Catalog)
- **Reference**: Planetary Habitability Laboratory (PHL) at the University of Puerto Rico at Arecibo (historical v5.0 benchmark snapshot).
- **Statistical Metric**: Pearson product-moment correlation coefficient ($r \ge 0.70$) and Spearman rank-order correlation ($\rho \ge 0.80$) across 20 benchmark terrestrial exoplanets.
- **Empirical Result**: $r = 0.772$, $\rho = 0.838$ (**PASS**).

### Track 2: Operational Observability Power (JWST Cycles 1–3)
- **Reference**: Approved JWST Cycles 1, 2, and 3 general observer (GO) and guaranteed time (GTO) transmission and emission spectroscopy targets (snapshot October 2024).
- **Temporal Constraint**: Limited strictly to exoplanets discovered on or before 2023 ($\text{discovery\_year} \le 2023$) to prevent post-cycle discovery look-ahead leakage.
- **Statistical Model**: Multivariate logistic regression with host-star clustered standard errors:
  $$\text{Logit}(P(\text{is\_jwst\_target})) = \beta_0 + \beta_{\text{obs}} \cdot \text{Observability\_z} + \beta_{\text{triage}} \cdot \text{Physical\_Triage\_z}$$
- **Threshold**: Adjusted $\text{OR} \ge 2.00$ with $p < 1.0\times 10^{-4}$.
- **Empirical Result**: $\text{OR} = 2.69$ ($95\%\text{ CI: } [2.43, 2.98]$, $p = 5.04\times 10^{-80}$) (**PASS**).

### Track 3: Selection Equivalence Testing (Physical Triage Independence)
- **Scientific Goal**: Verify that physical habitability scoring is not confounded by operational transit selection biases.
- **Equivalence Bounds**: Symmetrical interval on the log-odds scale $|\beta_{\text{triage}}| < 0.37$, corresponding to odds ratio bounds $\text{OR} \in [0.70, 1.45]$.
- **Evaluation Criteria**: Unrounded point estimate and unrounded 95% confidence interval must fall entirely within $[0.70, 1.45]$.
- **Empirical Result**: $\text{OR} = 1.22$ ($95\%\text{ CI: } [1.049, 1.408]$, $p = 0.0093$) (**PASS**).

### Track 4: Solar System Physical Sanity Controls (Zero-Point Calibration)
- **Benchmark Objects**: Earth, Mars, Venus, and Jupiter evaluated through identical pipeline equations.
- **Criteria**:
  - Earth composite score $\ge 0.75$ and similarity score $= 1.000$ (Control baseline).
  - Mars similarity score $< 0.80$ (Sub-optimal mass and cold equilibrium penalty).
  - Venus composite score $< 0.50$ (Runaway greenhouse suppression; $T_{\text{eq}} \approx 735\text{ K}$).
  - Jupiter composite score $< 0.40$ (Gas giant lacking solid surface; $P_{\text{rocky}} = 0.0$).
  - Strict descending monotonicity: $\text{Composite}(\text{Earth}) > \text{Composite}(\text{Mars}) > \text{Composite}(\text{Venus}) > \text{Composite}(\text{Jupiter})$.
- **Empirical Result**: Earth ($0.868$) $>$ Mars ($0.745$) $>$ Venus ($0.406$) $>$ Jupiter ($0.000$) (**PASS**).

---

## 3. Methodological Limitations

1. **Target Selection Context**: JWST telescope allocations reflect Telescope Allocation Committee (TAC) scheduling feasibility, instrumentation constraints, host star brightness, and proposal interest. They are an operational benchmark for detection capture, not ground truth for biological habitability.
2. **Simplified Atmospheric Chemistry**: 1D forward-model retrievals assume clear-sky or parameterized aerosol decks; photochemical equilibrium and 3D global circulation (GCM) dynamics require dedicated follow-up modeling.
3. **Stellar Activity Assumptions**: Flare frequency, coronal mass ejections (CMEs), and extreme ultraviolet (XUV) history are estimated from stellar type and rotation approximations where direct high-energy monitoring is unavailable.
4. **Resonant Chain Phase Sensitivity in Orbital Retrodiction**: The orbital gap engine evaluates dynamically permitted niches via circular phase-blind test particle injection and REBOUND MEGNO integration. While this successfully recovers regular quasi-periodic motion in well-spaced non-resonant systems (such as the Sun-Venus-Mars gap with Earth masked, $\langle Y \rangle \le 2.2$), phase-blind insertion into tightly packed multi-body resonant chains (such as TRAPPIST-1) breaks the delicate Laplace resonant libration angles, yielding MEGNO $> 4.0$ (unstable). Resonant architectures require dedicated three-body resonant angle search.
5. **Correlated Systematics in Transmission Spectroscopy**: Uncorrected correlated (red) noise inflates ordinary least-squares significance. Exo mitigates this via Prais-Winsten AR(1) prewhitening and strictly gates detection tiers on trials-corrected significance across the 7-molecule hypothesis space.

---

## 4. Reproducibility & Verification

### Running the Full Test Suite
```bash
pytest
```
*Current test suite result: 187 passed, 0 failures.*

### Recording Live Validation Runs
```bash
python validation/record_validation_run.py
```
Records dynamic run metadata to `validation_runs` and individual track metrics (including unrounded confidence intervals, $p$-values, and covariance methods) to `validation_results`.

### Building the Dashboard
```bash
cd web
npm install
npm run build
```
Production build compiles via TypeScript (`tsc`) and Vite without errors.
