"""
Unified validation runner for the Exo platform.

Usage:
    python -m validation.run_validation              # offline checks only
    python -m validation.run_validation --live        # includes DB-dependent checks
    python -m validation.run_validation --thorough    # includes sensitivity analysis
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root AND modules/ are on sys.path BEFORE any module-level imports cascade
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
_MODULES_DIR = str(Path(__file__).resolve().parent.parent / "modules")
for _p in [_PROJECT_ROOT, _MODULES_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(_PROJECT_ROOT)

from validation.esi_benchmark import run_esi_benchmark
from validation.sanity_checks import run_sanity_checks


def main():
    parser = argparse.ArgumentParser(description="Exo Platform Scientific Validation")
    parser.add_argument("--live", action="store_true",
                        help="Include DB-dependent checks (biosig crosscheck, weight stability)")
    parser.add_argument("--thorough", action="store_true",
                        help="Include sensitivity analysis (MC sampling, slower)")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_passed = True
    report_lines = [
        f"# Exo Platform — Scientific Validation Report",
        f"",
        f"**Generated:** {timestamp}",
        f"**Mode:** {'thorough' if args.thorough else 'live' if args.live else 'offline'}",
        f"",
    ]

    # ─── 1. ESI Benchmark ───────────────────────────────────────────────
    print("\n[1/6] ESI Benchmark...")
    esi = run_esi_benchmark()
    if not esi["passed"]:
        all_passed = False
    print(f"  {'[PASS]' if esi['passed'] else '[FAIL]'} {esi['message']}")

    report_lines += [
        "## 1. ESI Benchmark",
        f"",
        f"**Result:** {'PASS' if esi['passed'] else 'FAIL'}",
        f"- Pearson r = {esi['pearson_r']} (threshold >= 0.70)",
        f"- Spearman rho = {esi['spearman_rho']}",
        f"- Planets compared: {esi['n_compared']}",
        f"",
        f"| Planet | Ours | Published | Delta |",
        f"|---|---|---|---|",
    ]
    for p in esi["per_planet"]:
        ours = f"{p['our_esi']:.4f}" if p["our_esi"] is not None else "N/A"
        delta = f"{p['delta']:+.4f}" if p["delta"] is not None else "N/A"
        report_lines.append(f"| {p['name']} | {ours} | {p['published_esi']:.4f} | {delta} |")
    report_lines.append("")

    # ─── 2. Solar System Sanity Checks ──────────────────────────────────
    print("\n[2/6] Solar System Sanity Checks...")
    sanity_results, sanity_scores = run_sanity_checks()
    sanity_pass = all(r.passed for r in sanity_results)
    if not sanity_pass:
        all_passed = False
    for r in sanity_results:
        print(f"  {'[PASS]' if r.passed else '[FAIL]'} {r.name}: {r.message}")

    report_lines += [
        "## 2. Solar System Sanity Checks",
        f"",
        f"**Result:** {'PASS' if sanity_pass else 'FAIL'}",
        f"",
        "| Planet | Similarity | Safety | Composite |",
        "|---|---|---|---|",
    ]
    for name, s in sanity_scores.items():
        sim = f"{s.get('similarity_score', 0):.4f}" if s.get("similarity_score") else "N/A"
        saf = f"{s.get('safety_score', 0):.4f}" if s.get("safety_score") else "N/A"
        comp = f"{s.get('composite_score', 0):.4f}" if s.get("composite_score") else "N/A"
        report_lines.append(f"| {name} | {sim} | {saf} | {comp} |")
    report_lines += [
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for r in sanity_results:
        report_lines.append(f"| {r.name} | {'✓ PASS' if r.passed else '✗ FAIL'}: {r.message} |")
    report_lines.append("")

    # ─── 3-6: DB-dependent checks ───────────────────────────────────────
    if args.live or args.thorough:
        from dotenv import load_dotenv
        from sqlalchemy.orm import sessionmaker
        from db_sync import create_sync_engine

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        engine = create_sync_engine()
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            # 3. Biosig cross-check
            print("\n[3/6] Biosignature Cross-Check...")
            from validation.biosig_crosscheck import run_biosig_crosscheck
            biosig = run_biosig_crosscheck(session)
            if not biosig["passed"]:
                all_passed = False
            print(f"  {'[PASS]' if biosig['passed'] else '[FAIL]'} {biosig['message']}")

            report_lines += [
                "## 3. Biosignature Cross-Check (JWST)",
                f"",
                f"**Result:** {'PASS' if biosig['passed'] else 'FAIL'}",
                f"- Agreement rate: {biosig['agreement_rate']*100:.0f}%",
                f"",
            ]

            # 4. Weight stability
            print("\n[4/6] Weight Stability Analysis...")
            from validation.weight_stability import run_weight_stability
            weights = run_weight_stability(session)
            if not weights["passed"]:
                all_passed = False
            print(f"  {'[PASS]' if weights['passed'] else '[FAIL]'} {weights['message']}")

            report_lines += [
                "## 4. Weight Stability",
                f"",
                f"**Result:** {'PASS' if weights['passed'] else 'FAIL'}",
                f"- {weights['message']}",
                f"",
            ]

            # 5-6. Sensitivity analysis (thorough only)
            if args.thorough:
                print("\n[5/6] Sensitivity Analysis (MC)...")
                from validation.sensitivity_analysis import run_sensitivity_analysis
                sens = run_sensitivity_analysis(session, n_planets=30, n_draws=200)
                print(f"  {sens['message']}")

                report_lines += [
                    "## 5. Sensitivity Analysis",
                    f"",
                    f"- {sens['message']}",
                    f"- Tier-unstable planets: {', '.join(sens['unstable_planets']) if sens['unstable_planets'] else 'None'}",
                    f"",
                ]
            else:
                print("\n[5/6] Sensitivity Analysis — skipped (use --thorough)")

            print("\n[6/6] Orbital Leave-One-Out — not yet implemented")

        finally:
            session.close()
    else:
        print("\n[3-6] DB-dependent checks skipped (use --live)")
        report_lines.append("## 3-6. DB-Dependent Checks\n\nSkipped (offline mode).\n")

    # ─── Summary ────────────────────────────────────────────────────────
    report_lines += [
        "---",
        "",
        f"**Overall: {'ALL CHECKS PASSED' if all_passed else 'SOME CHECKS FAILED'}**",
    ]

    # Save report
    output_dir = Path(__file__).resolve().parent.parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    report_path = output_dir / "validation_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Overall: {'ALL CHECKS PASSED' if all_passed else 'SOME CHECKS FAILED'}")
    print(f"  Report saved to: {report_path}")
    print(f"{'='*60}\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
