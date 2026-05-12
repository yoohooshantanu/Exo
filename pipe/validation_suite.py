"""
pipelines/validation_suite.py

Automated data quality checks that run after every ingestion.
Catches bad data before it reaches any analysis module.

Checks are organized in four tiers:
  CRITICAL  — pipeline halts, data is corrupt or broken
  WARNING   — data issue flagged, pipeline continues
  INFO      — informational stats, always passes

Run standalone:
  python validation_suite.py

Or called from other pipelines:
  from validation_suite import run_validation
  passed, report = run_validation(session)
"""

import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
Session      = sessionmaker(bind=engine)


# ── result types ──────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name:    str
    level:   str          # CRITICAL | WARNING | INFO
    passed:  bool
    message: str
    value:   float = 0.0  # numeric value for tracking over time


@dataclass
class ValidationReport:
    run_at:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    results:  list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results if r.level == "CRITICAL")

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.level == "CRITICAL" and not r.passed]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.level == "WARNING" and not r.passed]

    def add(self, result: CheckResult):
        self.results.append(result)

    def print(self):
        width = 60
        print(f"\n{'='*width}")
        print(f"  Validation Suite  -  {self.run_at.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*width}")

        for r in self.results:
            icon  = "[+]" if r.passed else "[-]"
            label = f"[{r.level:<8}]"
            print(f"  {icon} {label} {r.name}")
            if not r.passed or r.level == "INFO":
                print(f"           {r.message}")

        print(f"\n{'-'*width}")
        criticals = len(self.critical_failures)
        warns     = len(self.warnings)
        infos     = len([r for r in self.results if r.level == "INFO"])
        total     = len(self.results)
        passed_ct = len([r for r in self.results if r.passed])

        print(f"  Result   : {'PASS [+]' if self.passed else 'FAIL [-]'}")
        print(f"  Checks   : {passed_ct}/{total} passed")
        if criticals: print(f"  Critical : {criticals} failure(s) - ingestion should be blocked")
        if warns:     print(f"  Warnings : {warns} issue(s) - review recommended")
        print(f"{'='*width}\n")


# ── individual checks ─────────────────────────────────────────────────────────

def check_no_orphan_planets(session) -> CheckResult:
    """Every planet must have a parent star."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planets p
        LEFT JOIN stars s ON p.star_id = s.star_id
        WHERE s.star_id IS NULL
    """)).scalar()
    return CheckResult(
        name    = "No orphan planets",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} planets have no parent star" if n else "All planets linked to a star",
        value   = float(n),
    )


def check_no_orphan_parameters(session) -> CheckResult:
    """Every planet_parameter must link to a valid planet and ingestion_run."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters pp
        LEFT JOIN planets p   ON pp.planet_id = p.planet_id
        LEFT JOIN ingestion_runs r ON pp.run_id = r.run_id
        WHERE p.planet_id IS NULL OR r.run_id IS NULL
    """)).scalar()
    return CheckResult(
        name    = "No orphan planet parameters",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} parameter rows have broken foreign keys",
        value   = float(n),
    )


def check_no_duplicate_planets(session) -> CheckResult:
    """Planet names must be unique."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT planet_name, COUNT(*) c
            FROM planets
            GROUP BY planet_name
            HAVING COUNT(*) > 1
        ) dupes
    """)).scalar()
    return CheckResult(
        name    = "No duplicate planet names",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} planet names appear more than once",
        value   = float(n),
    )


def check_no_duplicate_stars(session) -> CheckResult:
    """Star hip_names must be unique."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT hip_name, COUNT(*) c
            FROM stars
            GROUP BY hip_name
            HAVING COUNT(*) > 1
        ) dupes
    """)).scalar()
    return CheckResult(
        name    = "No duplicate star names",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} star names appear more than once",
        value   = float(n),
    )


def check_parameter_units_present(session) -> CheckResult:
    """Every parameter row must have an explicit unit — never implicit."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters
        WHERE unit IS NULL OR unit = ''
    """)).scalar()
    return CheckResult(
        name    = "All planet parameters have units",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} parameter rows missing unit field",
        value   = float(n),
    )


def check_no_negative_mass(session) -> CheckResult:
    """Planetary masses must be positive."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters
        WHERE param_name = 'mass_earth' AND value <= 0
    """)).scalar()
    return CheckResult(
        name    = "No negative planet masses",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} planets have zero or negative mass",
        value   = float(n),
    )


def check_no_negative_radius(session) -> CheckResult:
    """Planetary radii must be positive."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters
        WHERE param_name = 'radius_earth' AND value <= 0
    """)).scalar()
    return CheckResult(
        name    = "No negative planet radii",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} planets have zero or negative radius",
        value   = float(n),
    )


def check_no_default_version_conflict(session) -> CheckResult:
    """
    For each (planet_id, param_name), at most one row should be is_default=true
    with valid_to IS NULL. More than one means the retire_old_default logic failed.
    """
    n = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT planet_id, param_name, COUNT(*) c
            FROM planet_parameters
            WHERE is_default = true AND valid_to IS NULL
            GROUP BY planet_id, param_name
            HAVING COUNT(*) > 1
        ) conflicts
    """)).scalar()
    return CheckResult(
        name    = "No default version conflicts",
        level   = "CRITICAL",
        passed  = (n == 0),
        message = f"{n} (planet, param) pairs have multiple active defaults — versioning broken",
        value   = float(n),
    )


def check_period_range(session) -> CheckResult:
    """Orbital periods: flag anything under 0.2 days (physically unlikely but not impossible)."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters
        WHERE param_name = 'period_days' AND value < 0.2
    """)).scalar()
    return CheckResult(
        name    = "Orbital period range check",
        level   = "WARNING",
        passed  = (n == 0),
        message = f"{n} planets have period < 0.2 days — verify these are not unit errors",
        value   = float(n),
    )


def check_temperature_range(session) -> CheckResult:
    """Equilibrium temperatures: 50K–10000K is the physically plausible range."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters
        WHERE param_name = 'eq_temperature_k'
          AND (value < 50 OR value > 10000)
    """)).scalar()
    return CheckResult(
        name    = "Equilibrium temperature range",
        level   = "WARNING",
        passed  = (n == 0),
        message = f"{n} planets have Teq outside 50–10000 K",
        value   = float(n),
    )


def check_stellar_teff_range(session) -> CheckResult:
    """Stellar Teff: 2300K–50000K covers M dwarfs to O stars."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM star_parameters
        WHERE param_name IN ('teff_best_k', 'teff_nasa_k', 'teff_gaia_k')
          AND (value < 2300 OR value > 50000)
    """)).scalar()
    return CheckResult(
        name    = "Stellar Teff range check",
        level   = "WARNING",
        passed  = (n == 0),
        message = f"{n} stellar Teff values outside 2300–50000 K",
        value   = float(n),
    )


def check_eccentricity_range(session) -> CheckResult:
    """Eccentricity must be 0 ≤ e < 1."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM planet_parameters
        WHERE param_name = 'eccentricity'
          AND (value < 0 OR value >= 1)
    """)).scalar()
    return CheckResult(
        name    = "Eccentricity range 0–1",
        level   = "WARNING",
        passed  = (n == 0),
        message = f"{n} planets have eccentricity outside [0, 1)",
        value   = float(n),
    )


def check_ruwe_flagged_stars(session) -> CheckResult:
    """Report count of stars with RUWE > 1.4 — not a failure, just tracking."""
    n = session.execute(text("""
        SELECT COUNT(*) FROM star_parameters
        WHERE param_name = 'ruwe' AND value > 1.4
    """)).scalar()
    return CheckResult(
        name    = "RUWE > 1.4 flagged stars",
        level   = "WARNING",
        passed  = (n < 500),   # >500 would be unusual
        message = f"{n} stars have RUWE > 1.4 (poor astrometric fit — likely binaries)",
        value   = float(n),
    )


def check_ingestion_run_completed(session) -> CheckResult:
    """Most recent ingestion run should not be stuck in 'running' status."""
    row = session.execute(text("""
        SELECT status, started_at FROM ingestion_runs
        ORDER BY started_at DESC LIMIT 1
    """)).fetchone()

    if not row:
        return CheckResult(
            name="Latest ingestion run status", level="WARNING",
            passed=False, message="No ingestion runs found in database"
        )

    status, started = row
    if status == "running":
        # if it's been running more than 2 hours something is wrong
        age = (datetime.now(timezone.utc) - started).total_seconds() / 3600
        stuck = age > 2.0
        return CheckResult(
            name    = "Latest ingestion run status",
            level   = "WARNING",
            passed  = not stuck,
            message = f"Run has been in 'running' state for {age:.1f}h — may be stuck",
        )

    return CheckResult(
        name    = "Latest ingestion run status",
        level   = "WARNING",
        passed  = status in ("success", "partial"),
        message = f"Latest run status: {status}",
    )


# ── info stats (always pass) ──────────────────────────────────────────────────

def stat_planet_count(session) -> CheckResult:
    n = session.execute(text("SELECT COUNT(*) FROM planets")).scalar()
    return CheckResult(
        name="Total confirmed planets", level="INFO",
        passed=True, message=f"{n:,} planets in database", value=float(n)
    )


def stat_star_count(session) -> CheckResult:
    n = session.execute(text("SELECT COUNT(*) FROM stars")).scalar()
    return CheckResult(
        name="Total host stars", level="INFO",
        passed=True, message=f"{n:,} stars in database", value=float(n)
    )


def stat_parameter_rows(session) -> CheckResult:
    p = session.execute(text("SELECT COUNT(*) FROM planet_parameters")).scalar()
    s = session.execute(text("SELECT COUNT(*) FROM star_parameters")).scalar()
    return CheckResult(
        name="Total parameter rows", level="INFO",
        passed=True, message=f"{p:,} planet params + {s:,} star params = {p+s:,} total",
        value=float(p + s)
    )


def stat_paper_coverage(session) -> CheckResult:
    papers  = session.execute(text("SELECT COUNT(*) FROM papers")).scalar()
    matched = session.execute(text("SELECT COUNT(DISTINCT paper_id) FROM paper_planet_mentions")).scalar()
    return CheckResult(
        name="arXiv paper coverage", level="INFO",
        passed=True,
        message=f"{papers:,} papers tracked, {matched:,} matched to known objects",
        value=float(papers)
    )


def stat_hz_coverage(session) -> CheckResult:
    total  = session.execute(text("SELECT COUNT(*) FROM habitability_scores")).scalar()
    in_hz  = session.execute(text("SELECT COUNT(*) FROM habitability_scores WHERE hz_score = 1.0")).scalar()
    return CheckResult(
        name="Habitable zone candidates", level="INFO",
        passed=True,
        message=f"{in_hz:,} planets in habitable zone out of {total:,} scored",
        value=float(in_hz)
    )


def stat_gaia_match_rate(session) -> CheckResult:
    total   = session.execute(text("SELECT COUNT(*) FROM stars")).scalar()
    matched = session.execute(text("""
        SELECT COUNT(DISTINCT star_id) FROM star_identifiers
        WHERE catalogue = 'gaia_dr3'
    """)).scalar()
    pct = 100 * matched / total if total else 0
    return CheckResult(
        name="Gaia crossmatch rate", level="INFO",
        passed=True,
        message=f"{matched:,}/{total:,} stars matched to Gaia DR3 ({pct:.1f}%)",
        value=pct
    )


def stat_mass_completeness(session) -> CheckResult:
    total = session.execute(text("SELECT COUNT(*) FROM planets")).scalar()
    has_mass = session.execute(text("""
        SELECT COUNT(DISTINCT planet_id) FROM planet_parameters
        WHERE param_name = 'mass_earth' AND is_default = true AND valid_to IS NULL
    """)).scalar()
    pct = 100 * has_mass / total if total else 0
    return CheckResult(
        name="Planet mass completeness", level="INFO",
        passed=True,
        message=f"{has_mass:,}/{total:,} planets have mass measurement ({pct:.1f}%)",
        value=pct
    )


# ── runner ────────────────────────────────────────────────────────────────────

ALL_CHECKS = [
    # CRITICAL
    check_no_orphan_planets,
    check_no_orphan_parameters,
    check_no_duplicate_planets,
    check_no_duplicate_stars,
    check_parameter_units_present,
    check_no_negative_mass,
    check_no_negative_radius,
    check_no_default_version_conflict,
    # WARNING
    check_period_range,
    check_temperature_range,
    check_stellar_teff_range,
    check_eccentricity_range,
    check_ruwe_flagged_stars,
    check_ingestion_run_completed,
    # INFO
    stat_planet_count,
    stat_star_count,
    stat_parameter_rows,
    stat_paper_coverage,
    stat_hz_coverage,
    stat_gaia_match_rate,
    stat_mass_completeness,
]


def run_validation(session=None) -> tuple[bool, ValidationReport]:
    """
    Run all checks. Returns (passed, report).
    passed = True only when no CRITICAL checks fail.
    Can be called with an existing session or will create its own.
    """
    own_session = session is None
    if own_session:
        session = Session()

    report = ValidationReport()

    try:
        for check_fn in ALL_CHECKS:
            try:
                result = check_fn(session)
                report.add(result)
            except Exception as e:
                report.add(CheckResult(
                    name    = check_fn.__name__,
                    level   = "CRITICAL",
                    passed  = False,
                    message = f"Check raised exception: {e}",
                ))
    finally:
        if own_session:
            session.close()

    return report.passed, report


if __name__ == "__main__":
    print("Running validation suite ...")
    passed, report = run_validation()
    report.print()
    exit(0 if passed else 1)