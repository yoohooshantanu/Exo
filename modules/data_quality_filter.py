"""
modules/data_quality_filter.py

Cleans planets_enriched.csv before ingestion.

Policies:
  1. If pl_rade or pl_bmasse has no published error (err1 is null/empty),
     treat it as a NASA composite estimate, not a measurement.
  2. If BOTH radius and mass are present, compute Earth-density.
     Reject the mass if density is outside the physical window
     [0.5, 10.0] Earth densities for small planets (R < 4 R⊕).
     For giants we are more lenient.
  3. If discovery method is Microlensing and radius error is missing,
     clear radius (it was interpolated from mass).
  4. If discovery method is Transit or TTV and mass error is missing,
     clear mass (it was interpolated from radius).

Outputs:
  planets_enriched_clean.csv
"""

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV = PROJECT_ROOT / "planets_enriched.csv"
OUTPUT_CSV = PROJECT_ROOT / "planets_enriched_clean.csv"

# ── helpers ──────────────────────────────────────────────────────────────────

def to_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None

def has_value(s):
    return s is not None and str(s).strip() != ""

# ── main ─────────────────────────────────────────────────────────────────────

def run():
    if not INPUT_CSV.exists():
        print(f"FATAL: {INPUT_CSV} not found")
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        rows = list(reader)

    print(f"Loaded {len(rows)} rows from {INPUT_CSV.name}")

    # Ensure output columns exist
    if "radius_flag" not in headers:
        headers.append("radius_flag")
    if "mass_flag" not in headers:
        headers.append("mass_flag")

    stats = {
        "mass_cleared_estimate": 0,
        "radius_cleared_estimate": 0,
        "mass_cleared_density": 0,
        "radius_cleared_density": 0,
        "microlensing_radius_cleared": 0,
        "transit_mass_cleared": 0,
    }

    for r in rows:
        rad = to_float(r.get("pl_rade"))
        mass = to_float(r.get("pl_bmasse"))
        rad_err = r.get("pl_radeerr1")
        mass_err = r.get("pl_bmasseerr1")
        method = (r.get("discoverymethod") or "").strip()

        r_flag = "ok"
        m_flag = "ok"

        # ── 1. Clear estimates based on discovery method + missing error ──
        if method == "Microlensing" and rad is not None and not has_value(rad_err):
            # Microlensing gives mass/separation, not radius.
            r["pl_rade"] = ""
            r_flag = "cleared_estimate_method"
            stats["microlensing_radius_cleared"] += 1

        if method in ("Transit", "Transit Timing Variations") and mass is not None and not has_value(mass_err):
            # Pure transit gives radius, not mass.
            r["pl_bmasse"] = ""
            m_flag = "cleared_estimate_method"
            stats["transit_mass_cleared"] += 1

        # Re-read after possible clearing
        rad = to_float(r.get("pl_rade"))
        mass = to_float(r.get("pl_bmasse"))

        # ── 2. Density sanity check ──
        if rad is not None and mass is not None and rad > 0:
            density = mass / (rad ** 3)
            # For small planets (< 4 R⊕), density should be roughly 0.3–10 Earth rho.
            # Anything outside that window is almost certainly a bad M-R interpolation.
            if rad < 4.0 and (density < 0.3 or density > 10.0):
                # Prefer keeping the *measured* quantity.
                # Heuristic: if mass error is missing but radius error exists,
                # mass is the fake one. Vice-versa.
                mass_is_measured = has_value(r.get("pl_bmasseerr1"))
                rad_is_measured = has_value(r.get("pl_radeerr1"))

                if mass_is_measured and not rad_is_measured:
                    r["pl_rade"] = ""
                    r_flag = "cleared_bad_density"
                    stats["radius_cleared_density"] += 1
                else:
                    r["pl_bmasse"] = ""
                    m_flag = "cleared_bad_density"
                    stats["mass_cleared_density"] += 1

        # ── 3. Generic composite-estimate flag (no error = estimate) ──
        # If we didn't already clear it, at least flag it for the scorer.
        if r.get("pl_rade") and not has_value(r.get("pl_radeerr1")) and r_flag == "ok":
            r_flag = "estimate"
        if r.get("pl_bmasse") and not has_value(r.get("pl_bmasseerr1")) and m_flag == "ok":
            m_flag = "estimate"

        r["radius_flag"] = r_flag
        r["mass_flag"] = m_flag

    print("\nCleaning stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote cleaned CSV -> {OUTPUT_CSV}")

if __name__ == "__main__":
    run()
