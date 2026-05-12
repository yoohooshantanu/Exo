"""
modules/synthesis_engine.py  v1.0.0

Phase 5 -- Step 3: Cross-module synthesis engine.

Joins outputs from all 5 phases to produce priority discovery alerts:
  Alert 1: Anomalous + Habitable  (anomaly_flags x habitability_scores)
  Alert 2: Novel Taxonomy          (taxonomy_clusters with no known analog)
  Alert 3: Gap + Biosignature      (orbital_predictions x molecule_detections)

Generates a unified synthesis report with per-planet dossiers.

Run:
  python modules/synthesis_engine.py
  python modules/synthesis_engine.py --dry-run
"""

import os, sys, io, uuid, argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL  = os.environ["DATABASE_URL"]
MODEL_VERSION = "1.0.0"

engine  = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

def log(msg): print(f"  {datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}")


# ── Alert Type 1: Anomalous + Habitable ─────────────────────────────────────

def query_anomalous_habitable(session):
    """Planets with anomaly flags AND high habitability scores."""
    rows = session.execute(text("""
        SELECT
            p.planet_name,
            p.planet_id,
            s.hip_name AS hostname,
            af.anomaly_type,
            af.deviation_sigma,
            af.observed_value,
            af.expected_value,
            af.unit,
            af.model_reference,
            hs.composite_score,
            hs.hz_score
        FROM anomaly_flags af
        JOIN planets p ON af.planet_id = p.planet_id
        JOIN stars s ON p.star_id = s.star_id
        LEFT JOIN habitability_scores hs
            ON hs.planet_id = p.planet_id
            AND hs.model_version = '4.2.0'
        WHERE af.deviation_sigma >= 3.0
        ORDER BY hs.composite_score DESC NULLS LAST, af.deviation_sigma DESC
    """)).fetchall()

    cols = ["planet_name", "planet_id", "hostname", "anomaly_type", "deviation_sigma",
            "observed_value", "expected_value", "unit", "model_reference",
            "composite_score", "hz_score"]
    return pd.DataFrame(rows, columns=cols)


# ── Alert Type 2: Novel Taxonomy ────────────────────────────────────────────

def query_novel_taxonomy(session):
    """Planets in clusters with no NASA classification analog, or noise points."""
    rows = session.execute(text("""
        SELECT *
        FROM (
            SELECT DISTINCT ON (p.planet_id)
                p.planet_name,
                p.planet_id,
                s.hip_name AS hostname,
                tc.cluster_label,
                tc.cluster_name,
                tc.distance_to_centroid,
                hs.composite_score
            FROM taxonomy_clusters tc
            JOIN planets p ON tc.planet_id = p.planet_id
            JOIN stars s ON p.star_id = s.star_id
            LEFT JOIN habitability_scores hs
                ON hs.planet_id = p.planet_id
                AND hs.model_version = '4.2.0'
            WHERE tc.cluster_label = -1
               OR tc.cluster_name NOT IN (
                  'Hot Giant', 'Warm Giant', 'Cold Giant',
                  'Hot Sub-Neptune', 'Warm Sub-Neptune',
                  'Hot Rocky', 'Temperate Rocky',
                  'Neptune-class'
               )
            ORDER BY p.planet_id, tc.run_at DESC
        ) sub
        ORDER BY composite_score DESC NULLS LAST
    """)).fetchall()

    cols = ["planet_name", "planet_id", "hostname", "cluster_label",
            "cluster_name", "distance_to_centroid", "composite_score"]
    return pd.DataFrame(rows, columns=cols)


# ── Alert Type 3: Gap + Biosignature ────────────────────────────────────────

def query_gap_biosignature(session):
    """
    Systems where we predict unseen planets (orbital gaps)
    AND at least one known planet has a biosignature detection.
    """
    rows = session.execute(text("""
        SELECT DISTINCT
            s.hip_name AS hostname,
            s.star_id,
            op.predicted_period_days,
            op.stability_confidence,
            op.model_version AS gap_model,
            p2.planet_name AS biosig_planet,
            md.molecule,
            md.detection_sigma,
            md.wavelength_um,
            hs.composite_score AS biosig_hab_score
        FROM orbital_predictions op
        JOIN stars s ON op.star_id = s.star_id
        JOIN planets p2 ON p2.star_id = s.star_id
        JOIN molecule_detections md ON md.planet_id = p2.planet_id
        LEFT JOIN habitability_scores hs
            ON hs.planet_id = p2.planet_id
            AND hs.model_version = '4.2.0'
        WHERE md.detection_sigma >= 2.0
          AND op.model_version = '3.1.0'
        ORDER BY md.detection_sigma DESC, op.stability_confidence DESC
    """)).fetchall()

    cols = ["hostname", "star_id", "predicted_period_days", "stability_confidence",
            "gap_model", "biosig_planet", "molecule", "detection_sigma",
            "wavelength_um", "biosig_hab_score"]
    return pd.DataFrame(rows, columns=cols)


# ── Platform summary ────────────────────────────────────────────────────────

def query_platform_summary(session):
    """Get row counts for all major tables."""
    tables = ["stars", "planets", "planet_parameters", "star_parameters",
              "habitability_scores", "orbital_predictions",
              "atmospheric_spectra", "hitran_lines", "molecule_detections",
              "biosignature_detections", "anomaly_flags", "taxonomy_clusters"]
    summary = {}
    for t in tables:
        try:
            cnt = session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            summary[t] = cnt
        except Exception:
            summary[t] = "N/A"
    return summary


# ── Report generation ────────────────────────────────────────────────────────

def generate_synthesis_report(alert1_df, alert2_df, alert3_df, platform_summary):
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Deduplicate alert1 to unique planets
    alert1_planets = alert1_df.drop_duplicates(subset=["planet_name"])
    habitable_anomalous = alert1_df[alert1_df["composite_score"].notna() &
                                     (alert1_df["composite_score"] > 0.5)]

    md = f"""# Exoplanet Discovery Platform -- Synthesis Report
**Date:** {date_str}  |  **Engine:** v{MODEL_VERSION}

## Platform Status

| Phase | Module | Records |
|:------|:-------|:--------|
| 1 | Data Pipeline | {platform_summary.get('planets', '?')} planets, {platform_summary.get('stars', '?')} stars |
| 2 | Habitability Scorer | {platform_summary.get('habitability_scores', '?')} scores |
| 3 | Orbital Gap Predictor | {platform_summary.get('orbital_predictions', '?')} predictions |
| 4 | Biosignature Detector | {platform_summary.get('molecule_detections', '?')} detections, {platform_summary.get('atmospheric_spectra', '?')} spectra |
| 5 | Anomaly + Taxonomy | {platform_summary.get('anomaly_flags', '?')} anomalies, {platform_summary.get('taxonomy_clusters', '?')} clustered |

---

## Alert Type 1: Anomalous + Habitable Planets
Planets with physical anomalies (>3 sigma) that also have habitability scores.
**Total anomalous planets:** {len(alert1_planets)}
**With hab_score > 0.5:** {len(habitable_anomalous.drop_duplicates(subset=['planet_name']))}

| Planet | Anomaly | Sigma | Observed | Expected | Hab Score |
|:-------|:--------|------:|:---------|:---------|----------:|
"""
    # Show habitable ones first, then top anomalies
    shown = set()
    for _, row in habitable_anomalous.sort_values("composite_score", ascending=False).head(20).iterrows():
        hab = f"{row['composite_score']:.3f}" if pd.notna(row['composite_score']) else "--"
        obs = f"{row['observed_value']:.2f}" if pd.notna(row['observed_value']) else "--"
        exp = f"{row['expected_value']:.2f}" if pd.notna(row['expected_value']) else "--"
        key = f"{row['planet_name']}_{row['anomaly_type']}"
        if key not in shown:
            md += f"| {row['planet_name']:<25s} | {row['anomaly_type']:<20s} | {row['deviation_sigma']:.1f} | {obs} | {exp} | {hab} |\n"
            shown.add(key)

    for _, row in alert1_df.sort_values("deviation_sigma", ascending=False).head(20).iterrows():
        key = f"{row['planet_name']}_{row['anomaly_type']}"
        if key not in shown:
            hab = f"{row['composite_score']:.3f}" if pd.notna(row['composite_score']) else "--"
            obs = f"{row['observed_value']:.2f}" if pd.notna(row['observed_value']) else "--"
            exp = f"{row['expected_value']:.2f}" if pd.notna(row['expected_value']) else "--"
            md += f"| {row['planet_name']:<25s} | {row['anomaly_type']:<20s} | {row['deviation_sigma']:.1f} | {obs} | {exp} | {hab} |\n"
            shown.add(key)

    md += f"""
---

## Alert Type 2: Novel Taxonomy (No Known Analog)
Planets in HDBSCAN clusters that don't map to standard NASA classifications,
or classified as noise (truly unique planets).
**Total novel-taxonomy planets:** {len(alert2_df)}

| Planet | Cluster | Name | Dist to Centroid | Hab Score |
|:-------|--------:|:-----|:-----------------|----------:|
"""
    for _, row in alert2_df.sort_values("composite_score", ascending=False).head(30).iterrows():
        hab = f"{row['composite_score']:.3f}" if pd.notna(row['composite_score']) else "--"
        dist = f"{row['distance_to_centroid']:.2f}" if pd.notna(row['distance_to_centroid']) else "N/A"
        md += f"| {row['planet_name']:<25s} | {row['cluster_label']:>3d} | {row['cluster_name']:<18s} | {dist} | {hab} |\n"

    md += f"""
---

## Alert Type 3: Orbital Gap + Biosignature Systems
Systems where we predict unseen planets AND known planets show atmospheric biosignatures.
**These are highest-priority systems for follow-up observation.**
**Systems found:** {alert3_df['hostname'].nunique() if len(alert3_df) > 0 else 0}

"""
    if len(alert3_df) > 0:
        md += "| System | Predicted Period (d) | Stability | Biosig Planet | Molecule | Sigma | Hab Score |\n"
        md += "|:-------|:---------------------|:----------|:--------------|:---------|------:|----------:|\n"
        shown_sys = set()
        for _, row in alert3_df.iterrows():
            key = f"{row['hostname']}_{row['biosig_planet']}_{row['molecule']}"
            if key not in shown_sys:
                hab = f"{row['biosig_hab_score']:.3f}" if pd.notna(row['biosig_hab_score']) else "--"
                stab = f"{row['stability_confidence']:.2f}" if pd.notna(row['stability_confidence']) else "--"
                md += (f"| {row['hostname']:<20s} | {row['predicted_period_days']:.1f} | {stab} "
                       f"| {row['biosig_planet']:<20s} | {row['molecule']:<4s} "
                       f"| {row['detection_sigma']:.1f} | {hab} |\n")
                shown_sys.add(key)
    else:
        md += "*No systems found with both orbital gap predictions and biosignature detections.*\n"

    md += f"""
---

## Priority Dossiers

"""
    # Top 5 most interesting planets (cross all alerts)
    all_planets = set()
    priority = []

    # Habitable + anomalous
    for _, row in habitable_anomalous.drop_duplicates(subset=["planet_name"]).head(5).iterrows():
        if row["planet_name"] not in all_planets:
            priority.append({"name": row["planet_name"], "reason": "Habitable + Anomalous",
                           "score": row["composite_score"], "detail": f"{row['anomaly_type']} ({row['deviation_sigma']:.1f} sigma)"})
            all_planets.add(row["planet_name"])

    # Gap + biosig
    if len(alert3_df) > 0:
        for _, row in alert3_df.drop_duplicates(subset=["biosig_planet"]).head(5).iterrows():
            if row["biosig_planet"] not in all_planets:
                priority.append({"name": row["biosig_planet"], "reason": "Gap System + Biosignature",
                               "score": row.get("biosig_hab_score"),
                               "detail": f"{row['molecule']} ({row['detection_sigma']:.1f} sigma) in {row['hostname']} system"})
                all_planets.add(row["biosig_planet"])

    for p in priority:
        score_str = f"{p['score']:.3f}" if p['score'] and pd.notna(p['score']) else "N/A"
        md += f"### {p['name']}\n"
        md += f"- **Priority reason:** {p['reason']}\n"
        md += f"- **Habitability score:** {score_str}\n"
        md += f"- **Detail:** {p['detail']}\n\n"

    md += f"""
---

## Methodology
This report synthesizes outputs from all five platform phases:
1. **Phase 1** (Data Pipeline): NASA Exoplanet Archive + Gaia DR3
2. **Phase 2** (Habitability): Geometric ESI + risk scoring
3. **Phase 3** (Orbital Gaps): Mutual Hill radius + REBOUND N-body
4. **Phase 4** (Biosignatures): HITRAN line matching on JWST/HST spectra
5. **Phase 5** (Anomaly + Taxonomy): Composition curves, density outliers, HDBSCAN clustering

Cross-module joins identify planets that are simultaneously interesting
across multiple scientific dimensions -- the highest-value discovery candidates.
"""

    out_path = OUTPUT_DIR / f"synthesis_report_{date_str}_v{MODEL_VERSION}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── Main ─────────────────────────────────────────────────────────────────────

def run(dry_run=False):
    print(f"\nSynthesis Engine v{MODEL_VERSION}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    session = Session()
    try:
        # Platform summary
        print("\n[1/5] Platform summary ...")
        summary = query_platform_summary(session)
        for table, count in summary.items():
            print(f"    {table:<25s}: {count}")

        # Alert 1
        print(f"\n[2/5] Alert Type 1: Anomalous + Habitable ...")
        alert1 = query_anomalous_habitable(session)
        n_planets = alert1["planet_name"].nunique() if len(alert1) > 0 else 0
        n_hab = len(alert1[alert1["composite_score"].notna() & (alert1["composite_score"] > 0.5)].drop_duplicates(subset=["planet_name"])) if len(alert1) > 0 else 0
        print(f"    Anomalous planets:     {n_planets}")
        print(f"    With hab_score > 0.5:  {n_hab}")
        if n_hab > 0:
            top = alert1[alert1["composite_score"] > 0.5].sort_values("composite_score", ascending=False).head(5)
            for _, r in top.iterrows():
                print(f"      * {r['planet_name']:<25s}  hab={r['composite_score']:.3f}  "
                      f"{r['anomaly_type']}  {r['deviation_sigma']:.1f} sigma")

        # Alert 2
        print(f"\n[3/5] Alert Type 2: Novel Taxonomy ...")
        alert2 = query_novel_taxonomy(session)
        print(f"    Novel-taxonomy planets: {len(alert2)}")
        if len(alert2) > 0:
            noise = alert2[alert2["cluster_label"] == -1]
            novel_clusters = alert2[alert2["cluster_label"] != -1]
            print(f"    Noise (unique):        {len(noise)}")
            print(f"    In novel clusters:     {len(novel_clusters)}")

        # Alert 3
        print(f"\n[4/5] Alert Type 3: Gap + Biosignature ...")
        alert3 = query_gap_biosignature(session)
        n_systems = alert3["hostname"].nunique() if len(alert3) > 0 else 0
        print(f"    Systems found:         {n_systems}")
        if len(alert3) > 0:
            for _, r in alert3.drop_duplicates(subset=["hostname", "biosig_planet", "molecule"]).head(5).iterrows():
                print(f"      * {r['hostname']:<15s}  gap P={r['predicted_period_days']:.1f}d  "
                      f"{r['biosig_planet']} {r['molecule']} {r['detection_sigma']:.1f} sigma")

        # Report
        print(f"\n[5/5] Generating synthesis report ...")
        out_path = generate_synthesis_report(alert1, alert2, alert3, summary)
        print(f"    Saved -> {out_path}")

        print(f"\n{'='*60}")
        print(f"  Synthesis complete.")
        print(f"  Alert 1 (Anomalous + Habitable): {n_hab} high-priority planets")
        print(f"  Alert 2 (Novel Taxonomy):        {len(alert2)} planets")
        print(f"  Alert 3 (Gap + Biosignature):    {n_systems} systems")
        print(f"{'='*60}")

    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback; traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthesis Engine")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
