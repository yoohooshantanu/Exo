"""
modules/taxonomy_engine.py  v1.0.0

Phase 5 -- Step 2: HDBSCAN-based planet taxonomy clustering.

Features: radius_earth, density_earth, period_days, eq_temperature_k, semi_major_axis_au
Pipeline: median imputation per discovery_method -> log-transform -> StandardScaler -> HDBSCAN

Writes cluster assignments to taxonomy_clusters table.
Generates cluster summary report.

Run:
  python modules/taxonomy_engine.py
  python modules/taxonomy_engine.py --dry-run
  python modules/taxonomy_engine.py --min-cluster-size 50
"""

import os, sys, io, uuid, math, argparse, json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, insert
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from db.models import TaxonomyCluster

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL  = os.environ["DATABASE_URL"]
MODEL_VERSION = "1.0.0"

engine  = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

def new_id(): return str(uuid.uuid4())
def now_utc(): return datetime.now(timezone.utc)
def log(msg): print(f"  {datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}")

FEATURES = ["radius_earth", "density_earth", "period_days",
            "eq_temperature_k", "semi_major_axis_au"]
LOG_FEATURES = ["period_days", "semi_major_axis_au"]
MIN_FEATURES_REQUIRED = 3


# ── Cluster naming heuristic ────────────────────────────────────────────────

def auto_name_cluster(centroid_radius, centroid_teq):
    """Generate descriptive name from centroid properties."""
    # Radius classification
    if centroid_radius < 1.5:
        size = "Rocky"
    elif centroid_radius < 4.0:
        size = "Sub-Neptune"
    elif centroid_radius < 11.0:
        size = "Neptune-class"
    else:
        size = "Giant"

    # Temperature classification
    if centroid_teq is None or np.isnan(centroid_teq):
        temp = ""
    elif centroid_teq < 300:
        temp = "Cold "
    elif centroid_teq < 500:
        temp = "Temperate "
    elif centroid_teq < 1000:
        temp = "Warm "
    else:
        temp = "Hot "

    return f"{temp}{size}"


# NASA standard classification names for cross-reference
NASA_CLASSES = {
    "Hot Jupiter", "Warm Jupiter", "Cold Jupiter",
    "Hot Neptune", "Warm Neptune",
    "Sub-Neptune", "Super-Earth", "Mini-Neptune",
    "Terrestrial", "Earth-like",
}


# ── Data fetching ────────────────────────────────────────────────────────────

def fetch_planet_data(session):
    """Fetch confirmed planets with clustering features."""
    rows = session.execute(text("""
        SELECT
            p.planet_id, p.planet_name, p.discovery_method,
            MAX(CASE WHEN pp.param_name='radius_earth'       THEN pp.value END) AS radius_earth,
            MAX(CASE WHEN pp.param_name='density_earth'      THEN pp.value END) AS density_earth,
            MAX(CASE WHEN pp.param_name='period_days'        THEN pp.value END) AS period_days,
            MAX(CASE WHEN pp.param_name='eq_temperature_k'   THEN pp.value END) AS eq_temperature_k,
            MAX(CASE WHEN pp.param_name='semi_major_axis_au' THEN pp.value END) AS semi_major_axis_au
        FROM planets p
        LEFT JOIN planet_parameters pp
            ON pp.planet_id=p.planet_id AND pp.is_default=true AND pp.valid_to IS NULL
        WHERE p.status='confirmed'
        GROUP BY p.planet_id, p.planet_name, p.discovery_method
    """)).fetchall()
    return pd.DataFrame(rows, columns=[
        "planet_id", "planet_name", "discovery_method",
        "radius_earth", "density_earth", "period_days",
        "eq_temperature_k", "semi_major_axis_au"
    ])


# ── Imputation ──────────────────────────────────────────────────────────────

def impute_per_discovery_method(df):
    """
    Median imputation per discovery_method group.
    Different methods have very different selection biases, so we impute
    within groups to avoid mixing populations.
    """
    df_imp = df.copy()

    for method, group in df_imp.groupby("discovery_method"):
        for feat in FEATURES:
            mask = group[feat].isna()
            if mask.any():
                median_val = group[feat].median()
                if pd.notna(median_val):
                    df_imp.loc[mask.index[mask], feat] = median_val

    # Global fallback for any remaining NaNs (small discovery method groups)
    for feat in FEATURES:
        mask = df_imp[feat].isna()
        if mask.any():
            global_median = df_imp[feat].median()
            if pd.notna(global_median):
                df_imp.loc[mask, feat] = global_median

    return df_imp


# ── Clustering pipeline ─────────────────────────────────────────────────────

def run_clustering(df, min_cluster_size=30, min_samples=10):
    """Run HDBSCAN clustering pipeline."""
    from sklearn.preprocessing import StandardScaler
    import hdbscan

    # Filter: need at least MIN_FEATURES_REQUIRED non-null features
    feature_count = df[FEATURES].notna().sum(axis=1)
    eligible = df[feature_count >= MIN_FEATURES_REQUIRED].copy()
    log(f"Eligible planets (>={MIN_FEATURES_REQUIRED} features): {len(eligible)}")

    if len(eligible) < min_cluster_size * 2:
        print("  Not enough eligible planets for clustering")
        return eligible, None, None

    # Impute
    log("Imputing missing values per discovery method ...")
    imputed = impute_per_discovery_method(eligible)

    # Log-transform features that span orders of magnitude
    for feat in LOG_FEATURES:
        mask = imputed[feat] > 0
        imputed.loc[mask, feat] = np.log10(imputed.loc[mask, feat])
        imputed.loc[~mask, feat] = imputed.loc[mask, feat].median()

    # Scale
    log("Scaling features ...")
    X = imputed[FEATURES].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Handle any remaining NaN (shouldn't happen but safety)
    nan_mask = np.isnan(X_scaled)
    if nan_mask.any():
        col_medians = np.nanmedian(X_scaled, axis=0)
        for j in range(X_scaled.shape[1]):
            X_scaled[nan_mask[:, j], j] = col_medians[j]

    # HDBSCAN
    log(f"Running HDBSCAN (min_cluster_size={min_cluster_size}, min_samples={min_samples}) ...")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric='euclidean',
        cluster_selection_method='eom',
    )
    labels = clusterer.fit_predict(X_scaled)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    log(f"Clusters found: {n_clusters}")
    log(f"Noise points:   {n_noise}")

    return eligible, labels, X_scaled


# ── Cluster statistics ──────────────────────────────────────────────────────

def compute_cluster_stats(df, labels):
    """Compute summary statistics per cluster."""
    df_clustered = df.copy()
    df_clustered["cluster_label"] = labels

    stats = []
    for label in sorted(set(labels)):
        group = df_clustered[df_clustered["cluster_label"] == label]

        # Centroid in original feature space
        centroid = {}
        for feat in FEATURES:
            vals = group[feat].dropna()
            centroid[feat] = vals.median() if len(vals) > 0 else None

        # Auto-name
        r_centroid = centroid.get("radius_earth")
        t_centroid = centroid.get("eq_temperature_k")
        name = auto_name_cluster(r_centroid, t_centroid) if r_centroid else "Unknown"
        if label == -1:
            name = "NOISE (unique planets)"

        # Check if matches a NASA classification
        has_nasa_match = any(nc.lower() in name.lower() for nc in NASA_CLASSES)

        stats.append({
            "label": label,
            "name": name,
            "count": len(group),
            "centroid": centroid,
            "has_nasa_analog": has_nasa_match,
            "radius_range": (group["radius_earth"].min(), group["radius_earth"].max()),
            "discovery_methods": group["discovery_method"].value_counts().to_dict(),
        })

    return stats


def individual_class(radius, teq):
    """Name a planet based on its own properties, not the cluster centroid."""
    if radius is None or np.isnan(radius):
        size = "Unknown"
    elif radius < 1.5:
        size = "Rocky"
    elif radius < 4.0:
        size = "Sub-Neptune"
    elif radius < 11.0:
        size = "Neptune-class"
    else:
        size = "Giant"

    if teq is None or np.isnan(teq):
        temp = ""
    elif teq < 300:
        temp = "Cold "
    elif teq < 500:
        temp = "Temperate "
    elif teq < 1000:
        temp = "Warm "
    else:
        temp = "Hot "
    return f"{temp}{size}"


# ── Database write ──────────────────────────────────────────────────────────

def write_clusters(session, df, labels, X_scaled, cluster_stats):
    """Write cluster assignments to taxonomy_clusters."""
    run_id = new_id()
    run_at = now_utc()

    # Build name lookup (centroid-based, kept for reference)
    name_lookup = {s["label"]: s["name"] for s in cluster_stats}

    # Compute centroids per cluster in scaled space
    cluster_centroids = {}
    for label in set(labels):
        if label == -1:
            continue
        mask = labels == label
        cluster_centroids[label] = X_scaled[mask].mean(axis=0)

    insert_dicts = []
    for i, (_, row) in enumerate(df.iterrows()):
        label = int(labels[i])
        # Use individual classification so a 0.8 R⊕ planet in a 2 R⊕ cluster
        # is still labeled "Rocky" instead of "Sub-Neptune".
        cluster_name = individual_class(row.get("radius_earth"), row.get("eq_temperature_k"))
        if label == -1:
            cluster_name = f"NOISE ({cluster_name})"

        # Distance to centroid
        if label != -1 and label in cluster_centroids:
            dist = float(np.linalg.norm(X_scaled[i] - cluster_centroids[label]))
        else:
            dist = None

        insert_dicts.append({
            "cluster_id": new_id(),
            "planet_id": row["planet_id"],
            "cluster_run_id": run_id,
            "cluster_label": label,
            "cluster_name": cluster_name,
            "distance_to_centroid": round(dist, 4) if dist is not None else None,
            "features_used": FEATURES,
            "algorithm": "HDBSCAN",
            "run_at": run_at,
        })

    chunk_size = 2000
    for i in range(0, len(insert_dicts), chunk_size):
        session.execute(insert(TaxonomyCluster), insert_dicts[i:i+chunk_size])

    session.commit()
    return len(insert_dicts), run_id


# ── Report ──────────────────────────────────────────────────────────────────

def generate_report(cluster_stats, total_planets, run_id):
    date_str = datetime.now().strftime("%Y-%m-%d")
    n_clusters = sum(1 for s in cluster_stats if s["label"] != -1)
    noise_count = sum(s["count"] for s in cluster_stats if s["label"] == -1)
    novel = [s for s in cluster_stats if not s["has_nasa_analog"] and s["label"] != -1]

    md = f"""# Planet Taxonomy Report
**Date:** {date_str}  |  **Model:** v{MODEL_VERSION}  |  **Algorithm:** HDBSCAN
**Run ID:** {run_id}

## Summary
- **Planets clustered:** {total_planets}
- **Clusters found:** {n_clusters}
- **Noise (unique) planets:** {noise_count}
- **Novel clusters (no NASA analog):** {len(novel)}
- **Features:** {', '.join(FEATURES)}
- **Imputation:** median per discovery_method group

## Cluster Overview

| # | Name | Count | Median R (R_E) | Median Teq (K) | NASA Analog |
|:--|:-----|:------|:---------------|:---------------|:------------|
"""
    for s in sorted(cluster_stats, key=lambda x: x["count"], reverse=True):
        r = s["centroid"].get("radius_earth")
        t = s["centroid"].get("eq_temperature_k")
        r_str = f"{r:.2f}" if r and not np.isnan(r) else "--"
        t_str = f"{t:.0f}" if t and not np.isnan(t) else "--"
        nasa = "Yes" if s["has_nasa_analog"] else "**NO**"
        md += f"| {s['label']:>2d} | {s['name']:<22s} | {s['count']:>5d} | {r_str:>8s} | {t_str:>8s} | {nasa} |\n"

    if novel:
        md += f"""
## Novel Clusters (No NASA Classification Analog)
These clusters may represent previously unrecognized planet populations.

"""
        for s in novel:
            md += f"### Cluster {s['label']}: {s['name']}\n"
            md += f"- **Count:** {s['count']} planets\n"
            r = s["centroid"]
            md += f"- **Centroid:** R={r.get('radius_earth','?'):.2f} R_E, "
            md += f"rho={r.get('density_earth','?'):.2f} rho_E, "
            t = r.get('eq_temperature_k')
            md += f"Teq={t:.0f} K\n" if t and not np.isnan(t) else "Teq=?\n"
            md += f"- **Discovery methods:** {s['discovery_methods']}\n\n"

    md += f"""
## Methodology
1. Feature extraction: {', '.join(FEATURES)}
2. Missing values: median imputation per discovery_method group
3. Log-transform: {', '.join(LOG_FEATURES)}
4. Normalization: sklearn StandardScaler
5. Clustering: HDBSCAN (EOM selection)
"""

    out_path = OUTPUT_DIR / f"taxonomy_report_{date_str}_v{MODEL_VERSION}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── Main ─────────────────────────────────────────────────────────────────────

def run(min_cluster_size=30, min_samples=10, dry_run=False):
    print(f"\nTaxonomy Engine v{MODEL_VERSION}")
    print(f"  Algorithm: HDBSCAN")
    print(f"  Features: {', '.join(FEATURES)}")
    print(f"  min_cluster_size: {min_cluster_size}")
    print(f"  min_samples: {min_samples}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    session = Session()
    try:
        print("\nLoading planet data ...")
        df = fetch_planet_data(session)
        print(f"  {len(df)} planets loaded")

        for feat in FEATURES:
            n = df[feat].notna().sum()
            print(f"    {feat:<25s}: {n:>5d} values")

        print(f"\nRunning clustering pipeline ...")
        eligible, labels, X_scaled = run_clustering(df, min_cluster_size, min_samples)

        if labels is None:
            print("  Clustering failed — not enough data")
            return

        # Stats
        print(f"\nComputing cluster statistics ...")
        stats = compute_cluster_stats(eligible, labels)

        print(f"\n  Cluster summary:")
        for s in sorted(stats, key=lambda x: x["count"], reverse=True):
            nasa_tag = "" if s["has_nasa_analog"] else " [NOVEL]"
            print(f"    [{s['label']:>3d}] {s['name']:<22s}  n={s['count']:>5d}{nasa_tag}")

        if dry_run:
            print(f"\n[DRY RUN] No database writes.")
        else:
            print(f"\nWriting cluster assignments to database ...")
            n, run_id = write_clusters(session, eligible, labels, X_scaled, stats)
            print(f"  Written: {n} assignments  (run_id: {run_id})")

        print(f"\nGenerating report ...")
        run_id_report = new_id()
        out_path = generate_report(stats, len(eligible), run_id_report)
        print(f"  Saved -> {out_path}")

    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback; traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Taxonomy Engine")
    parser.add_argument("--min-cluster-size", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        dry_run=args.dry_run)
