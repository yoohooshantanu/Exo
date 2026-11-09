# Exo — Exoplanet Discovery Platform

There are over 6,000 confirmed exoplanets in the NASA archive. Each has measured radius, mass, orbital period, temperature, host star properties — but that data lives across different catalogs, and actually deciding which planets deserve follow-up observation means juggling habitability estimates, spectral data, orbital stability simulations, and anomaly detection separately.

I built this to do all of that in one place. The platform pulls the full NASA archive, scores every planet for habitability and environmental risk, runs N-body simulations to predict where undiscovered planets should be, screens spectra against molecular cross-section templates, flags statistical outliers, and rolls everything into a single 0–100 **Discovery Score**. There's a FastAPI backend, a React dashboard with a 3D star map, and the whole thing runs from `docker-compose up`.

```mermaid
flowchart LR
    A["NASA Archive\n6,467 planets"] --> B["Habitability\nScorer"]
    A --> C["Orbital Gap\nPredictor"]
    A --> D["Biosignature\nDetector"]
    A --> E["Anomaly\nDetector"]
    A --> F["Taxonomy\nEngine"]

    B --> G["Synthesis Engine"]
    C --> G
    D --> G
    E --> G
    F --> G

    G --> H["Discovery Score\n0 – 100"]
    H --> I["React Dashboard\n+ FastAPI"]

    style A fill:#1565c0,color:#fff,stroke:#0d47a1
    style G fill:#e65100,color:#fff,stroke:#bf360c
    style H fill:#2e7d32,color:#fff,stroke:#1b5e20
    style I fill:#4a148c,color:#fff,stroke:#311b92
```

## Table of Contents

- [Why This Exists](#-why-this-exists)
- [How It Works — The Five Engines](#-how-it-works--the-five-engines)
- [Decision Layer (Three Decoupled Indices)](#-decision-layer-three-decoupled-discovery-indices)
- [Platform & Observatory UI Features](#-platform--observatory-ui-features)
- [Data Sources](#-data-sources)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Project Map](#-project-map)
- [References](#-references)
- [Validation](#-validation)
- [Methodology Notes](#-methodology-notes)
- [Limitations](#%EF%B8%8F-limitations)

---

## 🔍 Why This Exists

Existing tools each solve a piece of the problem but not the whole thing:

| Tool | What It Does | What It Misses |
|:---|:---|:---|
| **UPR Habitable Exoplanets Catalog** | Computes an Earth Similarity Index (ESI) | Ignores environmental hazards. An M-dwarf planet with ESI 0.95 ranks equally to one around a quiet G-dwarf — even though the M-dwarf's UV flares are probably stripping the atmosphere. |
| **REBOUND** | N-body orbital simulations | You set up each system manually, pick test particle positions, and interpret MEGNO values yourself. No automation across the full archive. |
| **HITRAN** | Molecular absorption line lists | Getting from raw transit depths to "H₂O detected at 3.2σ" requires continuum fitting, contamination checks, and abiotic reasoning — usually done ad-hoc in notebooks. |

Exo connects these tools into an automated pipeline. Each module writes to the same PostgreSQL database, and the **Synthesis Engine** joins their outputs to surface planets that are interesting across *multiple* scientific dimensions simultaneously.

---

## ⚙ How It Works — The Five Engines

Each engine is a standalone Python script that reads from and writes to the shared database. Run them individually or orchestrate with Prefect.

<br>

### Engine 1 · Habitability Scorer

> `modules/habitability_scorer.py` · v5.0.0

Scores every confirmed planet through a rigorous three-stage pipeline: **Physical Earth Similarity**, **Environmental Safety (with Bayesian Priors)**, and a **Terrestrial Surface Gate** grounded in the Fulton et al. (2017) radius valley. Existing exoplanet catalogs only compute the first one, leading to temperate sub-Neptunes being erroneously classified as habitable.

<details>
<summary><b>Track 1 — Earth Similarity Index (ESI)</b> &nbsp;·&nbsp; <i>click to expand</i></summary>

<br>

Geometric mean of four physical parameters, following Schulze-Makuch et al. (2011):

$$\text{ESI} = \prod_{i=1}^{n} \left( 1 - \left| \frac{x_i - x_0}{x_i + x_0} \right| \right)^{w_i / n}$$

| Parameter | Earth Reference | Weight |
|:---|:---|---:|
| Radius | 1.0 R⊕ | 0.57 |
| Bulk Density | 1.0 ρ⊕ | 1.07 |
| Escape Velocity | 1.0 v⊕ | 0.70 |
| Equilibrium Temp | 255 K | 5.58 |

- Bulk density and escape velocity are derived from radius + mass when available.
- If only radius and temperature exist, the index computes with $n = 2$ (minimum 2 components, must include temperature).
- Implausible mass values (mass > 10 × R^2.5 — likely upper limits, not measurements) are treated as missing.

**Validation:** Pearson correlation against UPR's published ESI for 20 reference planets (TRAPPIST-1 e, Proxima Cen b, Kepler-442 b, etc.). Target: **r ≥ 0.70**. Run `python -m validation.run_validation` to verify.

</details>

<details>
<summary><b>Track 2 — Environmental Safety & Bayesian Shrinkage</b> &nbsp;·&nbsp; <i>click to expand</i></summary>

<br>

Measures atmospheric retention and environmental viability over gigayear timescales:

$$\text{Safety} = 0.45 \cdot \text{XUV Escape} + 0.30 \cdot \text{Tidal Lock} + 0.15 \cdot \text{Eccentricity} + 0.10 \cdot \text{Stellar Age}$$

| Factor | Weight | Logic |
|:---|---:|:---|
| **XUV Escape (Retention)** | 0.45 | Energy-limited hydrodynamic escape over time (Luger & Barnes 2015). Atmosphere stripping is the primary failure mode for habitable-zone planets around active M dwarfs. |
| **Tidal locking** | 0.30 | Timescale proxy $\tau_{\text{lock}} \propto a^6 / (M_\star^2 R_p^5)$. Close-in planets are penalized for severe permanent day/night temperature splits. |
| **Eccentricity** | 0.15 | $\exp(-2.057 \cdot e^2)$. High orbital eccentricity drives extreme seasonal climate instability. |
| **Stellar age** | 0.10 | Inverse-sqrt magnetic activity proxy. Young stars drive violent coronal mass ejections and flare activity. |

**Bayesian Population Priors:**  
To prevent uncharacterized exoplanets from artificially inflating their safety scores by omitting missing observational values, missing dimensions shrink to empirical population priors rather than dropping from the weighted average:
- `xuv_escape_score`: $0.50$
- `tidal_lock_score`: $0.35$
- `ecc_score`: $0.70$
- `age_score`: $0.60$

</details>

<details>
<summary><b>Stage 3 — Terrestrial Surface Gate ($P_{\text{rocky}}$)</b> &nbsp;·&nbsp; <i>click to expand</i></summary>

<br>

A planet cannot be habitable if it lacks a distinct liquid/solid interface. Under the Fulton et al. (2017) radius valley, Rogers (2015), and Zeng et al. (2019) composition models, planets above $1.8\,R_\oplus$ almost universally retain volatile hydrogen/helium gas envelopes (mini-Neptunes).

We implement an explicit logistic surface gate:

$$P_{\text{rocky}}(R_p, M_p) = \frac{1}{1 + \exp\left(\frac{R_p - 1.80\,R_\oplus}{0.12}\right)}$$

- **Density check**: When measured mass is present, if bulk density $\rho = M_p / R_p^3 \ge 0.8\,\rho_\oplus$ and $R_p \le 1.8\,R_\oplus$, $P_{\text{rocky}} = 0.95$. If $\rho < 0.5\,\rho_\oplus$, the planet is heavily penalized via a steep gas-envelope gate centered at $1.50\,R_\oplus$.
- This surface gate directly resolves false positives where gaseous sub-Neptunes (such as K2-332 b or Kepler-22 b) ranked high merely because their equilibrium temperatures matched Earth's.

</details>

$$\mathbf{\text{Composite Habitability}} = \Big(0.70 \cdot \text{ESI} + 0.30 \cdot \text{Safety}\Big) \times P_{\text{rocky}}(R_p, M_p)$$

- **Uncertainty Propagation**: Every score includes a 30-trial Monte Carlo IQR ($\pm \text{IQR} = Q_{75} - Q_{25}$) sampled over measured radius and mass parameter error distributions.
- **Provenance & Imputation**: Planets lacking measured masses fall back to empirical mass-radius relations ($M \sim R^{3.5}$ for rocky / $M \sim R^{2.06}$ for gaseous) and are explicitly flagged with a `Mass Imputed` badge.

<br>

---

### Engine 2 · Orbital Gap Predictor

> `modules/orbital_gap_predictor.py` · v3.1.0

Scans every multi-planet system (≥ 2 confirmed planets) for dynamically stable gaps where additional planets could exist undetected.

<details>
<summary><b>Full methodology</b> &nbsp;·&nbsp; <i>click to expand</i></summary>

<br>

**Step 1 — Gap identification**
For every adjacent planet pair, compute mutual Hill radius separation Δ. Pairs with Δ > 18 R_H,m are anomalously wide (Gladman 1993 stability boundary).

**Step 2 — Test particle injection**
Five candidates per gap:
- 2:1, 3:2, 4:3 mean-motion resonances (inner)
- 1:2 MMR (outer)
- Geometric center √(a₁ · a₂)

Test mass: √(M_inner · M_outer), clamped to 0.5–2.0 M⊕.

**Step 3 — Analytical pre-filter**
Candidates with Δ < 10 R_H to either neighbor → rejected without integration.

**Step 4 — MEGNO stability (REBOUND)**

| Stage | Trials | Duration | Reject If |
|:---|---:|:---|:---|
| Fast screen | 5 | 5,000 orbits | MEGNO > 3.0 or ΔE/E > 10⁻⁴. Require ≥ 75% pass. |
| Deep validation | 20 | 50,000 orbits | Integration duration strictly checked (≥90% of requested orbits). e_max > 0.25 or Δa/a > 0.1. |

**Step 5 — One prediction per gap.**
First stable resonance wins (MMRs first — physically motivated).

</details>

**Key design decisions:**
- `predicted_at` timestamps are **immutable** in the database — never overwritten on re-runs. This is the proof of prediction priority if a telescope later confirms the planet.
- All data fetched in **2 SQL queries** (not 1 per system). N-body work is parallelized via `ProcessPoolExecutor`. ~1,200 systems in **2–3 minutes** on 8 cores.

<br>

---

### Engine 3 · Biosignature Detector

> `modules/biosignature_detector.py` · v3.0.0

Compares transit/eclipse spectra against HITRAN molecular templates to identify atmospheric molecules.

**Target molecules:** &ensp; H₂O &nbsp;·&nbsp; CO₂ &nbsp;·&nbsp; O₃ &nbsp;·&nbsp; CH₄ &nbsp;·&nbsp; CO &nbsp;·&nbsp; NH₃ &nbsp;·&nbsp; SO₂

<details>
<summary><b>Detection pipeline (8 stages)</b> &nbsp;·&nbsp; <i>click to expand</i></summary>

<br>

| Stage | What It Does |
|:---|:---|
| **1. GP Continuum** | Gaussian Process regression (Matérn ν=1.5) trained on points *outside* known absorption bands. Models the spectral baseline without fitting the features. |
| **2. Spectral Unmixing** | All 7 molecular templates fit simultaneously via regularized OLS. Prevents misattribution when absorption bands overlap. Each molecule → coefficient β ± σ_β. |
| **3. Scale-Height Filter** | Expected max transit depth from planet gravity + star radius: Δ_max = 2R_p·H/R_s². Excess beyond 2× this → masked as systematic. |
| **4. Stellar Contamination** | M-dwarf hosts: H₂O penalized −0.5σ, CO −0.3σ. K-dwarfs: H₂O −0.3σ. Unocculted starspots mimic planetary absorption. |
| **5. Instrument Weighting** | JWST = 1.0×, HST = 0.85×, Spitzer = 0.70×, ground/unknown = 0.60×. |
| **6. Abiotic Reasoning** | CH₄ without CO₂ → −1.0σ. H₂O+CH₄+O₃ all ≥3σ → "triple biosignature" (abiotic unlikely). NH₃ on rocky → +0.5σ boost. SO₂ on rocky → volcanic flag. |
| **7. Multi-Epoch** | Detected in ≥2 independent spectra → +0.5σ. Only 1 of N spectra → −0.5σ. |
| **8. Classification** | ≥3σ + ≥3 template feature peaks → **Statistically significant screening candidate**. ≥2σ + ≥2 peaks → **Tier 2 marginal candidate**. |

</details>

**Validation:** `--validate` flag runs injection-recovery — synthetic signals at 1σ/2σ/3σ/5σ injected into real spectra, recovery rate measured, false positive rate from null injections.

<br>

---

### Engine 4 · Anomaly Detector

> `modules/anomaly_detector.py` · v1.0.0

Three detection engines running in parallel:

| Engine | What It Flags | Method |
|:---|:---|:---|
| **Mass-Radius Outliers** | Planets deviating >3σ from all Zeng et al. (2016) composition curves (pure iron, Earth-like, pure water) | Per-planet mass uncertainties from NASA archive. RV/TTV-measured masses get tighter error bars than transit-inferred masses (≥60% fractional error). Only R < 4 R⊕. |
| **Eccentricity-Period** | Short-period (P<10d) planets with e > 0.3 | Tidal circularization should make these nearly circular (expected e ≈ 0.05 ± 0.08). |
| **Density Outliers** | Density > 3σ from type-group mean | Four radius bins: Rocky (<1.5 R⊕), Sub-Neptune (<4), Neptune-class (<11), Giant. |

<br>

---

### Engine 5 · Taxonomy Engine

> `modules/taxonomy_engine.py` · v1.0.0

Unsupervised HDBSCAN clustering of the full catalog on five features:

```
radius · density · period · equilibrium temperature · semi-major axis
```

- Missing values imputed **per discovery-method group** (transit vs. RV vs. imaging have different selection biases — global imputation would mix populations).
- Period and semi-major axis log-transformed before StandardScaler.
- Clusters auto-named from centroid properties (e.g., "Hot Giant", "Temperate Rocky").
- Clusters with no NASA classification analog → flagged as **novel populations**.
- HDBSCAN noise points (label = −1) → truly unique planets that fit nothing.

<br>

---

### Engine 6 · Synthesis Engine

> `modules/synthesis_engine.py` · v1.0.0

Cross-module joins that surface planets interesting across *multiple* scientific dimensions:

```mermaid
flowchart LR
    AF["anomaly_flags"] -- "JOIN" --> AH["🔴 Alert 1\nAnomalous + Habitable"]
    HS["habitability_scores"] -- "JOIN" --> AH

    TC["taxonomy_clusters"] -- "label = -1\nor no NASA analog" --> NT["🟡 Alert 2\nNovel Taxonomy"]

    OP["orbital_predictions"] -- "JOIN" --> GB["🟢 Alert 3\nGap + Biosignature"]
    MD["molecule_detections"] -- "JOIN" --> GB

    style AH fill:#d32f2f,color:#fff,stroke:#b71c1c
    style NT fill:#f9a825,color:#000,stroke:#f57f17
    style GB fill:#2e7d32,color:#fff,stroke:#1b5e20
```

---

## 📊 Decision Layer (Three Decoupled Discovery Indices)

Rather than conflating physical properties, observational constraints, and post-hoc observational data into a single circular metric, the platform explicitly separates triage into three independent, uncoupled indices stored in `mv_discovery_scores`:

```mermaid
pie title The Three Decoupled Discovery Indices
    "Physical Triage (Habitability - Anomaly)" : 40
    "Observability (Geometric SNR)" : 30
    "Characterization (Spectra + Biosigs)" : 30
```

### 1. Physical Triage Index ($0 - 100$)
Measures **intrinsic physical habitability and dynamical stability** prior to any observation bias:

$$\text{Physical Triage} = \text{clamp}\left(0, 100, \left[\text{Composite Habitability} \times 40 - \min(N_{\text{anomalies}} \times 3.0, 10)\right] \times \frac{100}{40}\right)$$

- Grounded in physical properties ($R_p$, $M_p$, $T_{\text{eq}}$, $S_{\text{eff}}$, orbital architecture).
- Gated by $P_{\text{rocky}}(R_p, M_p)$ to filter out volatile sub-Neptune envelopes.
- Downweighted by physical anomalies (e.g., extreme density outliers, super-eccentric short periods).

### 2. Observability Index ($0 - 100$)
Measures **how feasible the planet is to observe spectroscopically** (transmission SNR proxy) without regard to habitability:

$$\text{SNR}_{\text{geom}} = \log_{10}\left( \frac{(R_p / [R_\star \times 109.2])^2}{d_{\text{pc}}^2} \right)$$

$$\text{Observability} = \text{clamp}\left(0, 100, \Big[\max(\text{SNR}_{\text{geom}}, -10) + 10\Big] \times \frac{100}{7.0}\right)$$

- Follows the geometric scaling of transmission spectroscopy metric (TSM) formulations (Kempton et al. 2018).
- Scaled such that prime targets (e.g., HD 209458 b with $\text{SNR}_{\text{geom}} \approx -2.5$) score $\approx 100$, while distant or faint targets ($\le -10$) score $0$.

### 3. Characterization Index ($0 - 100$)
Measures **what the astronomical community has already verified** post-observation:

$$\text{Characterization} = \text{clamp}\left(0, 100, \Big[\min(\text{Biosig Score}, 25) + \text{Data Quality Score}\Big] \times \frac{100}{40}\right)$$

- **Biosig Score** ($0 - 25$): Weighted by the count of $\ge 3\sigma$ candidate molecular-template detections scaled by signal significance:
  $$\text{Biosig Score} = N_{\ge 3\sigma} \times 5.0 \times \left(0.5 + 0.5 \times \frac{\min(\overline{\sigma}, 10.0)}{5.0}\right)$$
- **Data Quality Score** ($0 - 15$): Spectra presence ($+5$), best instrument tier ($+5$ for JWST, $+3.5$ for HST, $+2$ for other), and parameter completeness ($+1$ each for $R_p, M_p, P, T_{\text{eq}}, a$).

---

### Legacy Composite Discovery Score ($0 - 100$)
For backward compatibility and unified holistic ranking, the legacy Discovery Score combines all dimensions:

$$\text{Discovery Score} = \text{clamp}\left(0, 100, 40 \cdot \text{Hab} + 25 \cdot \text{Bio} + 15 \cdot \text{DataQual} + 10 \cdot \text{Orbital} - 10 \cdot \text{Anom}\right)$$

> **Why decouple the three indices?**  
> In our empirical validation against JWST Cycles 1–3 target allocations, physical habitability *does not predict* telescope time allocation (odds ratio $\text{OR} \approx 1.03$). JWST target selection is almost entirely driven by the **Observability** index (TSM/transit depth/host brightness). When habitability and data quality were merged into a single number, the score falsely appeared to "predict" JWST targets simply because targets already observed by JWST received high data quality points (circular tautology). Decoupling them provides an honest, actionable triage framework for astronomical proposals.

---

## 🖥 Platform & Observatory UI Features

- **7-Axis Calibrated Radar Telemetry**:  
  Visualizes planetary health profiles with an explicitly pinned $[0, 1]$ radial domain ($0\%$ center, $100\%$ outer rim) across **Radius ESI**, **Mass ESI**, **Equilibrium Temperature**, **Habitable Zone Proximity**, **Tidal Locking Safety**, **XUV Atmospheric Retention**, and **Orbital Eccentricity**.
- **Interactive 3D Star Map**:  
  WebGL/Three.js starfield mapping confirmed hosts in galactic coordinates with habitability clustering.
- **Atmospheric Spectrum & HITRAN Template Cross-Correlation**:  
  Interactive transmission spectrum viewer matching observational points against laboratory molecular absorption lines with scale-height filters and stellar contamination corrections.
- **PLATON Bayesian Retrieval Posterior Viewer**:  
  Displays nested sampling posterior distribution curves for atmospheric parameters ($T_{\text{surf}}$, metallicity, C/O ratio, cloud pressure).
- **Multi-System Orbital Architectures & Hill Stability Predictor**:  
  Interactive layout of multi-planet systems showing confirmed planets alongside dynamically stable predicted orbital gaps.
- **Modern Minimalist Observatory Aesthetic**:  
  Engineered for dark astronomical environments with high-contrast data tables, monospace numerical readouts, and zero generic decorative gradients.

---

## 🌐 Data Sources

| Source | Ingests | Cadence |
|:---|:---|:---|
| [**NASA Exoplanet Archive**](https://exoplanetarchive.ipac.caltech.edu/) | Confirmed planets, stellar params, orbital elements (TAP API) | Nightly |
| [**arXiv astro-ph.EP**](https://arxiv.org/list/astro-ph.EP/recent) | Paper abstracts, regex-matched to known planets/stars | Daily |
| **NASA Spectroscopy Table** | Transit/eclipse depths from JWST, HST, Spitzer | Weekly |
| [**HITRAN**](https://hitran.org/) / **ExoMol** | Molecular line lists for spectral templates | Seeded once |
| **Gaia DR3** | Stellar ages (`age_flame`), luminosities | On new ingestion |

> **Why the arXiv watcher?** &ensp; arXiv posts papers the same day as submission. The NASA archive ingests the same data weeks to months later. Matching abstracts against our catalog keeps the platform more current than the archive alone.

---

## 🏗 Architecture

```mermaid
flowchart TD
    subgraph Orchestration
        SCHED["Prefect Scheduler"]
    end

    subgraph External["External Data Feeds"]
        NASA["NASA Exoplanet Archive"]
        ARXIV["arXiv astro-ph.EP"]
        JWST["JWST / HST Spectra"]
        HITRAN["HITRAN / ExoMol"]
        GAIA["Gaia DR3"]
    end

    subgraph Ingestors["Data Ingestors"]
        NI["nasa_ingestor"]
        AW["arxiv_watcher"]
        SI["spectra_ingestor"]
        HS_SEED["hitran_seeder"]
    end

    subgraph Engines["Scientific Engines"]
        HAB["Habitability Scorer\nv4.2.0"]
        OGP["Orbital Gap Predictor\nv3.1.0"]
        BIO["Biosignature Detector\nv3.0.0"]
        ANOM["Anomaly Detector\nv1.0.0"]
        TAX["Taxonomy Engine\nv1.0.0"]
        SYN["Synthesis Engine\nv1.0.0"]
    end

    subgraph Storage["Database"]
        PG[("PostgreSQL + PostGIS\n17 tables · EAV params\nFull provenance chain")]
    end

    subgraph Workers["Async Workers"]
        CEL["Celery + Redis"]
        PLAT["PLATON Retrieval"]
    end

    subgraph API_Layer["Web Tier"]
        API["FastAPI :8000\n/planets · /rankings\n/alerts · /spectrum"]
        WEB["React Dashboard :5173\nPlanet profiles · 3D map\nSpectral viewer · Alerts"]
    end

    SCHED --> NI & AW & SI
    SCHED --> HAB & OGP & BIO & ANOM & TAX

    NASA --> NI
    ARXIV --> AW
    JWST --> SI
    HITRAN --> HS_SEED
    GAIA --> NI

    NI & AW & SI & HS_SEED --> PG
    PG --> HAB & OGP & BIO & ANOM & TAX
    HAB & OGP & BIO & ANOM & TAX --> SYN
    SYN --> PG
    HAB & OGP & BIO & ANOM & TAX --> PG

    PG <--> API
    API --> CEL --> PLAT --> PG
    API <--> WEB

    style PG fill:#1565c0,color:#fff,stroke:#0d47a1
    style API fill:#00695c,color:#fff,stroke:#004d40
    style WEB fill:#4a148c,color:#fff,stroke:#311b92
    style SYN fill:#e65100,color:#fff,stroke:#bf360c
```

<details>
<summary><b>Database design notes</b></summary>

<br>

Parameters are stored in an **EAV (entity-attribute-value)** pattern — `planet_parameters` and `star_parameters` tables — with `is_default` flags and `valid_from`/`valid_to` timestamps.

When the NASA archive updates a planet's mass estimate, the old value is kept and marked non-default rather than overwritten. Every parameter row links back to an `ingestion_run` and optionally a `paper` for full provenance.

The `orbital_predictions.predicted_at` column is deliberately immutable — the timestamp is set once and never updated, so it constitutes proof of prediction priority relative to any later telescope confirmation.

</details>

---

## 🚀 Quick Start

```bash
# 1 — Clone
git clone https://github.com/yoohooshantanu/Exo.git && cd Exo

# 2 — Configure secrets (copy and edit)
cp .env.example .env

# 3 — Start the full stack (PostGIS, Redis, API, Celery worker, React)
docker-compose up -d

# 4 — Ingest the NASA archive (~2 min)
docker-compose exec api python pipe/nasa_ingestor.py

# 5 — Run the analytical engines
docker-compose exec api python modules/habitability_scorer.py
docker-compose exec api python modules/orbital_gap_predictor.py
docker-compose exec api python modules/biosignature_detector.py
docker-compose exec api python modules/anomaly_detector.py
docker-compose exec api python modules/taxonomy_engine.py
docker-compose exec api python modules/synthesis_engine.py
```

| Endpoint | URL |
|:---|:---|
| API docs (Swagger) | [`http://localhost:8000/docs`](http://localhost:8000/docs) |
| Interactive dashboard | [`http://localhost:5173`](http://localhost:5173) |

> **Tip:** Every module supports `--dry-run` to preview output without writing to the database.

---

## 📁 Project Map

```
Exo/
│
├── api/                            # REST API
│   ├── main.py                     # Routes + Discovery Score computation
│   ├── models.py                   # Pydantic response schemas
│   ├── queries.py                  # Raw SQL for all endpoints
│   └── db.py                       # Async SQLAlchemy session
│
├── db/                             # Database layer
│   ├── models.py                   # SQLAlchemy ORM — 17 tables
│   └── ingest_to_db.py             # Bulk CSV bootstrap ingestor
│
├── modules/                        # Scientific engines
│   ├── habitability_scorer.py      #  ↳ ESI + environmental risk scoring
│   ├── orbital_gap_predictor.py    #  ↳ Hill radius gaps + REBOUND N-body
│   ├── biosignature_detector.py    #  ↳ GP continuum + HITRAN matching
│   ├── anomaly_detector.py         #  ↳ Zeng curves, ecc/density outliers
│   ├── taxonomy_engine.py          #  ↳ HDBSCAN clustering
│   ├── synthesis_engine.py         #  ↳ Cross-module alert generation
│   ├── platon_retrieval.py         #  ↳ PLATON + dynesty retrieval
│   ├── spectra_ingestor.py         #  ↳ NASA spectroscopy ingestion
│   ├── hitran_seeder.py            #  ↳ HITRAN line list seeder
│   ├── exomol_seeder.py            #  ↳ ExoMol cross-sections
│   └── data_quality_filter.py      #  ↳ Pre-processing filters
│
├── pipe/                           # Orchestration
│   ├── nasa_ingestor.py            #  ↳ NASA TAP API ingestor
│   ├── arxiv_watcher.py            #  ↳ arXiv paper tracker
│   ├── scheduler.py                #  ↳ Prefect flows + cron schedules
│   ├── celery_worker.py            #  ↳ Async task runner
│   └── validation_suite.py         #  ↳ Data integrity checks
│
├── web/                            # React + Vite + TypeScript
├── alembic/                        # Database migrations
├── docker-compose.yml              # Full stack definition
└── requirements.txt                # Python 3.11+
```

---

## 📚 References

| Paper | Used In |
|:---|:---|
| Schulze-Makuch et al. (2011). *A Two-Tiered Approach to Assessing the Habitability of Exoplanets.* Astrobiology 11(10). | ESI formula + exponents |
| Gladman, B. (1993). *Dynamics of Systems of Two Close Planets.* Icarus 106(1), 247–263. | Hill radius stability boundary |
| Rein & Liu (2012). *REBOUND: An open-source multi-purpose N-body code.* A&A 537, A128. | N-body integrator |
| Rein & Tamayo (2015). *WHFAST: a fast and unbiased implementation of a symplectic Wisdom–Holman integrator.* MNRAS 452(1), 376–388. | MEGNO indicator |
| Zeng et al. (2016). *Mass–Radius Relation for Rocky Planet Interiors.* ApJ 819, 127. | Composition curves |
| Gordon et al. (2022). *The HITRAN2020 molecular spectroscopic database.* JQSRT 277, 107949. | Molecular line lists |
| Winn & Fabrycky (2015). *The Occurrence and Architecture of Exoplanetary Systems.* ARA&A 53. | Eccentricity benchmarks |
| Kopparapu et al. (2013). *Habitable Zones Around Main-Sequence Stars: New Estimates.* ApJ 765:131. | HZ boundaries |
| Rackham, Apai & Giampapa (2018). *The Transit Light Source Effect.* ApJ 853:122. | Stellar contamination risk |
| Luger & Barnes (2015). *Extreme Water Loss and Abiotic O2 Buildup on Planets Throughout the Habitable Zones of M Dwarfs.* Astrobiology 15:2. | XUV escape & atmospheric retention |
| Bean, Stevenson & Batalha (2018). *A Statistical Comparative Planetology Approach.* PASP 130:114402. | JWST performance baseline |

---

<p align="center">
  <sub>Built for the question that keeps astronomers up at night: <i>where should we point the telescope next?</i></sub>
</p>

---

## 🔬 Validation

The platform includes a scientific validation suite (`validation/`) separate from data integrity checks (`pipe/validation_suite.py`).

| Check | What It Tests | Pass Criterion | Mode |
|:---|:---|:---|:---|
| **ESI Benchmark** | `compute_similarity_esi()` vs UPR published values for 20 planets | Pearson r ≥ 0.70 | Offline |
| **Solar System Sanity** | Earth, Venus, Mars, Jupiter through `score_planet()` | Earth composite > 0.75, Jupiter < 0.40 | Offline |
| **Biosig Cross-Check** | Our detections vs confirmed JWST results (WASP-39 b, K2-18 b) | ≥ 60% agreement | Live DB |
| **Weight Stability** | Top-20 ranking under ±20% weight perturbation (1000 trials) | ≥ 70% retention | Live DB |
| **Sensitivity Analysis** | MC perturbation of fundamentals (radius, mass) through scorer | Report IQR per planet | Live DB |
| **XUV Escape Empirical Check** | Consistency against JWST/HST retained/stripped labels for 8 independent targets | Physically-motivated replacement; empirical consistency check on 8 JWST targets is directionally positive but statistically inconclusive (AUC ≈ 0.67) and dominated by planet size. | Live DB |

```bash
python -m validation.run_validation              # offline checks
python -m validation.run_validation --live        # + DB-dependent checks
python -m validation.run_validation --thorough    # + MC sensitivity analysis
```

Report saved to `outputs/validation_report.md`.

---

## 📋 Methodology Notes

Every hardcoded constant in the scoring pipeline is annotated with its classification:

| Classification | Meaning | Example |
|:---|:---|:---|
| **LITERATURE-DERIVED** | Directly from a published paper | ESI exponents (Schulze-Makuch 2011) |
| **STANDARD VALUE** | Community-accepted default | 3σ detection threshold |
| **TRIAGE HEURISTIC** | Hand-chosen for triage, not fitted | Risk weights (0.45/0.30/0.15/0.10) |
| **DECISION-SUPPORT HEURISTIC** | Composite ranking metric | Discovery Score weights |

See the source-level comments in `modules/habitability_scorer.py`, `modules/biosignature_detector.py`, and `modules/discovery_score.py` for per-constant citations.

---

## ⚠️ Limitations

1. **Discovery Score weights are hand-chosen.** The 40/25/15/10/−10 weights encode expert judgment but have not been fitted to outcomes or validated against observation proposals. See `validation/weight_stability.py` for sensitivity analysis.

2. **Penalty constants are triage heuristics.** XUV escape models, stellar contamination sigma penalties, instrument quality scalars, and abiotic adjustment values are deliberately conservative approximations. Each is labeled in source with its classification and caveats.

3. **No uncertainty propagation beyond Habitability.** The habitability composite score now includes a Monte Carlo IQR and flags when mass is imputed. However, the three triage indices and specific sub-components (like XUV escape) do not yet fully propagate this structural uncertainty.
4. **Data quality component was circular for validation.** The old monolithic Discovery Score's data_quality term rewarded having JWST/HST spectra. Correlating the score against "was observed by JWST" partly recovered this component's own definition — which is why the indices were explicitly separated.

5. **Solar System bodies are not in the dataset.** Earth, Venus, Mars, Jupiter are used as sanity checks with hardcoded parameters, not as DB entries.
