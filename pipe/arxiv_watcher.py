"""
pipelines/arxiv_watcher.py

Watches arXiv astro-ph.EP for new exoplanet papers daily.
For each paper, checks if it mentions any planet or star in our database.
Inserts matched papers into the papers table and links them to objects.

Why this matters:
  arXiv posts papers the SAME DAY as submission — NASA archive ingests
  the same data weeks to months later. This watcher makes our data
  more current than the archive itself.

Uses arXiv's official API (no auth needed):
  https://export.arxiv.org/api/query

Run daily via Prefect schedule (wired up in scheduler.py).
Safe to re-run — skips papers already in database by arxiv_id.
"""

import os
import re
import time
import httpx
import feedparser
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import uuid

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
Session      = sessionmaker(bind=engine)

# ── arXiv API config ──────────────────────────────────────────────────────────
ARXIV_API      = "https://export.arxiv.org/api/query"
ARXIV_RSS      = "https://export.arxiv.org/rss/astro-ph.EP"
MAX_RESULTS    = 2000         # increased for historical backfill
LOOKBACK_DAYS  = 2            # default lookback
SLEEP_BETWEEN  = 3.0          # seconds between API calls — arXiv asks for politeness

HEADERS = {
    "User-Agent": "ExoplanetResearchPlatform/1.0 (academic research; https://github.com/your-repo)",
}

# ── planet/star name patterns ────────────────────────────────────────────────
# These regex patterns match the most common exoplanet naming conventions.
# We match against abstract + title then look up in our database.

PLANET_PATTERNS = [
    r'\b(Kepler-\d+\s*[b-z])\b',
    r'\b(K2-\d+\s*[b-z])\b',
    r'\b(TOI-\d+\s*[b-z])\b',
    r'\b(WASP-\d+\s*[b-z])\b',
    r'\b(HAT-P-\d+\s*[b-z])\b',
    r'\b(TRAPPIST-\d+\s*[b-z])\b',
    r'\b(GJ\s*\d+\s*[b-z])\b',
    r'\b(HD\s*\d+\s*[b-z])\b',
    r'\b(55\s*Cnc\s*[b-z])\b',
    r'\b(tau\s*Cet\s*[b-z])\b',
    r'\b(LHS\s*\d+\s*[b-z])\b',
    r'\b(LP\s*\d+-\d+\s*[b-z])\b',
    r'\b(EPIC\s*\d+\s*[b-z])\b',
]

STAR_PATTERNS = [
    r'\b(Kepler-\d+)\b',
    r'\b(K2-\d+)\b',
    r'\b(TOI-\d+)\b',
    r'\b(WASP-\d+)\b',
    r'\b(HAT-P-\d+)\b',
    r'\b(TRAPPIST-\d+)\b',
    r'\b(GJ\s*\d+)\b',
    r'\b(HD\s*\d+)\b',
    r'\b(HIP\s*\d+)\b',
    r'\b(TIC\s*\d+)\b',
]

COMPILED_PLANET = [re.compile(p, re.IGNORECASE) for p in PLANET_PATTERNS]
COMPILED_STAR   = [re.compile(p, re.IGNORECASE) for p in STAR_PATTERNS]


def new_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── arXiv fetch ───────────────────────────────────────────────────────────────

def fetch_recent_papers(lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """
    Fetch recent astro-ph.EP papers from arXiv API.
    Returns list of dicts with: arxiv_id, doi, title, abstract, published_at, authors
    
    arXiv API returns Atom XML — feedparser handles it cleanly.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days))
    date_filter = since.strftime("%Y%m%d")

    params = {
        "search_query": f"cat:astro-ph.EP AND submittedDate:[{date_filter}0000 TO 99991231235959]",
        "sortBy":       "submittedDate",
        "sortOrder":    "descending",
        "max_results":  MAX_RESULTS,
        "start":        0,
    }

    print(f"  Fetching arXiv astro-ph.EP papers since {since.date()} ...")

    try:
        r = httpx.get(ARXIV_API, params=params, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"  arXiv API failed: {e} — falling back to RSS")
        return fetch_via_rss()

    feed    = feedparser.parse(r.text)
    papers  = []

    for entry in feed.entries:
        # extract arxiv ID from the URL-format id field
        # e.g. "http://arxiv.org/abs/2403.12345v1" → "2403.12345"
        raw_id   = entry.get("id", "")
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0].strip()
        if not arxiv_id:
            continue

        # extract DOI if present in links
        doi = None
        for link in entry.get("links", []):
            if link.get("rel") == "related" and "doi" in link.get("href", ""):
                doi = link["href"].replace("http://dx.doi.org/", "").strip()
                break

        # parse published date
        published = None
        raw_pub   = entry.get("published", "")
        if raw_pub:
            try:
                published = datetime.strptime(raw_pub[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        papers.append({
            "arxiv_id":    arxiv_id,
            "doi":         doi,
            "title":       entry.get("title", "").replace("\n", " ").strip(),
            "abstract":    entry.get("summary", "").replace("\n", " ").strip(),
            "published_at": published,
            "authors":     [a.get("name", "") for a in entry.get("authors", [])],
        })

    print(f"  Fetched {len(papers)} papers from arXiv API")
    return papers


def fetch_via_rss() -> list[dict]:
    """
    RSS fallback — less structured but same content.
    Used if API is slow or returns errors.
    """
    try:
        r    = httpx.get(ARXIV_RSS, headers=HEADERS, timeout=60)
        feed = feedparser.parse(r.text)
    except Exception as e:
        print(f"  RSS also failed: {e}")
        return []

    papers = []
    for entry in feed.entries:
        raw_id   = entry.get("id", "")
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0].strip()
        if not arxiv_id:
            continue

        papers.append({
            "arxiv_id":    arxiv_id,
            "doi":         None,
            "title":       entry.get("title", "").replace("\n", " ").strip(),
            "abstract":    entry.get("summary", "").replace("\n", " ").strip(),
            "published_at": None,
            "authors":     [],
        })

    print(f"  Fetched {len(papers)} papers from RSS fallback")
    return papers


# ── name extraction ───────────────────────────────────────────────────────────

def extract_names(text: str) -> tuple[set[str], set[str]]:
    """
    Extract planet and star names from title + abstract text.
    Returns (planet_names, star_names) as sets of normalized strings.
    """
    planet_names = set()
    star_names   = set()

    for pattern in COMPILED_PLANET:
        for match in pattern.finditer(text):
            # normalize: collapse internal whitespace
            name = re.sub(r'\s+', ' ', match.group(1)).strip()
            planet_names.add(name)

    for pattern in COMPILED_STAR:
        for match in pattern.finditer(text):
            name = re.sub(r'\s+', ' ', match.group(1)).strip()
            # don't add if already covered by a planet match (subset name)
            if not any(name in p for p in planet_names):
                star_names.add(name)

    return planet_names, star_names


# ── database matching ─────────────────────────────────────────────────────────

def get_all_planet_names(session) -> dict[str, str]:
    """Returns {planet_name_lower: planet_id}"""
    rows = session.execute(
        text("SELECT planet_name, planet_id FROM planets WHERE status = 'confirmed'")
    ).fetchall()
    return {row[0].lower(): row[1] for row in rows}


def get_all_star_names(session) -> dict[str, str]:
    """Returns {hip_name_lower: star_id}"""
    rows = session.execute(
        text("SELECT hip_name, star_id FROM stars")
    ).fetchall()
    return {row[0].lower(): row[1] for row in rows}


def paper_exists(session, arxiv_id: str) -> str | None:
    """Returns paper_id if already ingested, else None."""
    row = session.execute(
        text("SELECT paper_id FROM papers WHERE arxiv_id = :arxiv_id"),
        {"arxiv_id": arxiv_id}
    ).fetchone()
    return row[0] if row else None


# ── database writes ───────────────────────────────────────────────────────────

def insert_paper(session, paper: dict) -> str:
    """Insert paper record. Returns paper_id."""
    paper_id = new_id()
    session.execute(text("""
        INSERT INTO papers (paper_id, doi, arxiv_id, title, published_at, ingested_at)
        VALUES (:paper_id, :doi, :arxiv_id, :title, :published_at, :ingested_at)
        ON CONFLICT (arxiv_id) DO NOTHING
    """), {
        "paper_id":     paper_id,
        "doi":          paper["doi"],
        "arxiv_id":     paper["arxiv_id"],
        "title":        paper["title"][:500] if paper["title"] else None,
        "published_at": paper["published_at"],
        "ingested_at":  now_utc(),
    })
    return paper_id


def insert_mentions(session, paper_id: str,
                    matched_planets: list,
                    matched_stars: list):
    """Write matched names to paper_planet_mentions junction table."""
    for name, planet_id in matched_planets:
        session.execute(text("""
            INSERT INTO paper_planet_mentions
                (id, paper_id, planet_id, star_id, name_found, created_at)
            VALUES (:id, :paper_id, :planet_id, NULL, :name_found, :now)
            ON CONFLICT DO NOTHING
        """), {"id": new_id(), "paper_id": paper_id,
               "planet_id": planet_id, "name_found": name, "now": now_utc()})

    for name, star_id in matched_stars:
        session.execute(text("""
            INSERT INTO paper_planet_mentions
                (id, paper_id, planet_id, star_id, name_found, created_at)
            VALUES (:id, :paper_id, NULL, :star_id, :name_found, :now)
            ON CONFLICT DO NOTHING
        """), {"id": new_id(), "paper_id": paper_id,
               "star_id": star_id, "name_found": name, "now": now_utc()})


# ── main loop ─────────────────────────────────────────────────────────────────

def run(lookback_days: int = LOOKBACK_DAYS):
    session = Session()
    NOW     = now_utc()

    try:
        # load all known names into memory — faster than per-paper DB queries
        print("Loading known planet and star names from database ...")
        planet_lookup = get_all_planet_names(session)
        star_lookup   = get_all_star_names(session)
        print(f"  {len(planet_lookup)} planets, {len(star_lookup)} stars loaded")

        # fetch recent papers
        papers = fetch_recent_papers(lookback_days)
        if not papers:
            print("No papers fetched — check arXiv connectivity")
            return

        time.sleep(SLEEP_BETWEEN)

        # process each paper
        stats = {
            "total":     len(papers),
            "new":       0,
            "skipped":   0,
            "matched":   0,
            "unmatched": 0,
        }

        print(f"\nProcessing {len(papers)} papers ...")

        for paper in papers:
            arxiv_id = paper["arxiv_id"]

            # skip if already in database
            if paper_exists(session, arxiv_id):
                stats["skipped"] += 1
                continue

            # extract names from title + abstract
            full_text = f"{paper['title']} {paper['abstract']}"
            planet_names, star_names = extract_names(full_text)

            # match against known objects
            matched_planets = []
            matched_stars   = []

            for name in planet_names:
                planet_id = planet_lookup.get(name.lower())
                if planet_id:
                    matched_planets.append((name, planet_id))

            for name in star_names:
                star_id = star_lookup.get(name.lower())
                if star_id:
                    matched_stars.append((name, star_id))

            # always insert the paper — even unmatched ones
            # (they may match after future planet discoveries)
            paper_id = insert_paper(session, paper)
            stats["new"] += 1

            if matched_planets or matched_stars:
                insert_mentions(session, paper_id, matched_planets, matched_stars)

            has_match = matched_planets or matched_stars
            if has_match:
                stats["matched"] += 1
                safe_title = paper['title'][:70].encode('ascii', 'replace').decode('ascii')
                print(
                    f"  [+] [{arxiv_id}] {safe_title}"
                    f"\n      planets: {[n for n,_ in matched_planets]}"
                    f"\n      stars:   {[n for n,_ in matched_stars]}"
                )
            else:
                stats["unmatched"] += 1

        session.commit()

        # ── summary ───────────────────────────────────────────────────────────
        print(f"""
-- arXiv watcher summary ------------------------------
  Run time        {NOW.strftime('%Y-%m-%d %H:%M UTC')}
  Papers fetched  {stats['total']}
  New inserted    {stats['new']}
  Already known   {stats['skipped']}
  Matched objects {stats['matched']}
  No match        {stats['unmatched']}
--------------------------------------------------------
        """)

    except Exception as e:
        session.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        session.close()


# ── paper_planet_mentions table ───────────────────────────────────────────────
# This is a lightweight junction table to add via a second migration.
# Tracks which papers mention which planets — soft provenance link.
# Run this SQL against your database after the main migration:
JUNCTION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS paper_planet_mentions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id   UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    planet_id  UUID REFERENCES planets(planet_id) ON DELETE SET NULL,
    star_id    UUID REFERENCES stars(star_id)   ON DELETE SET NULL,
    name_found TEXT NOT NULL,    -- exact string matched in the abstract
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ppm_paper_id  ON paper_planet_mentions(paper_id);
CREATE INDEX IF NOT EXISTS ix_ppm_planet_id ON paper_planet_mentions(planet_id);
CREATE INDEX IF NOT EXISTS ix_ppm_star_id   ON paper_planet_mentions(star_id);
"""


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS
    print(f"arXiv watcher — lookback {days} day(s)\n")
    run(lookback_days=days)