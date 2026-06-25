"""Load processed frames into the served SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ..config import DB_PATH, ensure_dirs

SCHEMA = Path(__file__).with_name("schema.sql")


def load(
    vendors: pd.DataFrame,
    contracts: pd.DataFrame,
    donations: pd.DataFrame,
    links: pd.DataFrame,
) -> None:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA.read_text())
        vendors.to_sql("vendors", conn, if_exists="append", index=False)
        contracts.to_sql("contracts", conn, if_exists="append", index=False)
        donations.to_sql("donations", conn, if_exists="append", index=False)
        links.to_sql("links", conn, if_exists="append", index=False)
        conn.commit()
    finally:
        conn.close()
    print(f"loaded SQLite db -> {DB_PATH}")
