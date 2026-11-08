"""
Biosignature Cross-Check — compare detections against published JWST results.

Queries the platform's molecule_detections table and checks whether our
detections agree with confirmed JWST molecular identifications from published
Nature/ApJL papers.

Requires: live DB connection (run with --live flag).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from dataclasses import dataclass


@dataclass
class CrossCheckResult:
    planet: str
    molecule: str
    reference: str
    our_sigma: float | None
    our_detected: bool
    published_min_sigma: float
    agreement: bool
    message: str


# Confirmed JWST molecular detections from peer-reviewed publications
JWST_CONFIRMED = [
    {"planet": "WASP-39 b", "molecule": "co2", "min_sigma": 20.0,
     "reference": "Ahrer et al. 2023, Nature 614, 653"},
    {"planet": "WASP-39 b", "molecule": "so2", "min_sigma": 4.0,
     "reference": "Alderson et al. 2023, Nature 614, 659"},
    {"planet": "WASP-39 b", "molecule": "h2o", "min_sigma": 10.0,
     "reference": "Feinstein et al. 2023, Nature 614, 670"},
    {"planet": "K2-18 b", "molecule": "ch4", "min_sigma": 3.0,
     "reference": "Madhusudhan et al. 2023, ApJL 956, L13"},
    {"planet": "K2-18 b", "molecule": "co2", "min_sigma": 2.5,
     "reference": "Madhusudhan et al. 2023, ApJL 956, L13"},
]


def run_biosig_crosscheck(session):
    """Cross-check our detections against published JWST results."""
    results = []
    agreements = 0
    total = 0

    for ref in JWST_CONFIRMED:
        row = session.execute(text("""
            SELECT md.detection_sigma
            FROM molecule_detections md
            JOIN planets p ON md.planet_id = p.planet_id
            WHERE p.planet_name = :planet AND md.molecule = :molecule
            ORDER BY md.detection_sigma DESC
            LIMIT 1
        """), {"planet": ref["planet"], "molecule": ref["molecule"]}).fetchone()

        our_sigma = row[0] if row else None
        our_detected = our_sigma is not None and our_sigma >= 2.0
        agreement = our_detected  # We should detect what JWST confirmed
        total += 1
        if agreement:
            agreements += 1

        results.append(CrossCheckResult(
            planet=ref["planet"],
            molecule=ref["molecule"],
            reference=ref["reference"],
            our_sigma=round(our_sigma, 3) if our_sigma else None,
            our_detected=our_detected,
            published_min_sigma=ref["min_sigma"],
            agreement=agreement,
            message=f"{'✓ Agree' if agreement else '✗ Missed'}: "
                    f"ours={our_sigma:.1f}σ" if our_sigma else f"{'✓' if agreement else '✗'}: not in our DB",
        ))

    return {
        "results": results,
        "agreement_rate": agreements / total if total > 0 else 0,
        "agreements": agreements,
        "total": total,
        "passed": (agreements / total >= 0.60) if total > 0 else False,
        "message": f"{agreements}/{total} JWST detections matched ({agreements/total*100:.0f}%)"
                   if total > 0 else "No comparisons possible",
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    from sqlalchemy.orm import sessionmaker
    from db_sync import create_sync_engine

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    engine = create_sync_engine()
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        result = run_biosig_crosscheck(session)
        print(f"\n{'='*70}")
        print(f"  Biosignature Cross-Check — JWST Confirmed Detections")
        print(f"{'='*70}\n")
        for r in result["results"]:
            icon = "[+]" if r.agreement else "[-]"
            sigma_str = f"{r.our_sigma:.1f}σ" if r.our_sigma else "N/A"
            print(f"  {icon} {r.planet} {r.molecule}: ours={sigma_str}, "
                  f"published≥{r.published_min_sigma}σ — {r.reference}")
        print(f"\n  {result['message']}")
        print(f"{'='*70}\n")
    finally:
        session.close()
