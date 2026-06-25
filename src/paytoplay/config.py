"""Central paths and tunable thresholds."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
EXTERNAL = DATA / "external"
PROCESSED = DATA / "processed"
CONFIG = ROOT / "config"

CONTRACTS_PARQUET = RAW / "contracts.parquet"
DONATIONS_PARQUET = EXTERNAL / "donations.parquet"
DB_PATH = PROCESSED / "paytoplay.db"
AGENCY_MAP_PATH = CONFIG / "agency_officials.yml"

# --- Resolution / scoring thresholds (tune as you validate) -----------------
# Minimum fuzzy score (0-100) for a pair to even be considered a candidate link.
MATCH_MIN_SCORE = 82
# At/above this confidence (0-1) a link is auto-published; between MIN and this
# it goes to the human-review queue.
PUBLISH_CONFIDENCE = 0.80
REVIEW_CONFIDENCE = 0.55
# Donations within this many days of a contract award get the timing bonus.
TIMING_WINDOW_DAYS = 365


def load_agency_map() -> dict:
    """Load config/agency_officials.yml into a dict keyed by normalized agency name."""
    with open(AGENCY_MAP_PATH) as fh:
        raw = yaml.safe_load(fh) or {}
    index: dict[str, list[dict]] = {}
    for entry in raw.get("agencies", []):
        names = [entry["agency"], *entry.get("aliases", [])]
        for n in names:
            index[n.strip().lower()] = entry["officials"]
    return index


def ensure_dirs() -> None:
    for d in (RAW, EXTERNAL, PROCESSED):
        d.mkdir(parents=True, exist_ok=True)
