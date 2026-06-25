"""Thin read-only FastAPI over the served SQLite database.

Run: uvicorn paytoplay.api.main:app --reload --app-dir src
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException

from ..config import DB_PATH

app = FastAPI(
    title="LA Pay-to-Play",
    description="Correlation, not proof. Every figure links to a public filing.",
    version="0.1.0",
)


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(503, "Database not built yet. Run the pipeline first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db_exists": DB_PATH.exists()}


@app.get("/leaderboard")
def leaderboard(limit: int = 50, min_score: float = 0.0) -> list[dict]:
    """Top vendor↔official relationships by concern score (published only)."""
    conn = _conn()
    try:
        cur = conn.execute(
            """
            SELECT l.*, v.name AS vendor_name, d.recipient_name, d.recipient_office
            FROM links l
            JOIN vendors v ON v.id = l.vendor_id
            JOIN donations d ON d.id = l.donor_id
            WHERE l.status = 'published' AND l.concern_score >= ?
            ORDER BY l.concern_score DESC
            LIMIT ?
            """,
            (min_score, limit),
        )
        return _rows(cur)
    finally:
        conn.close()


@app.get("/vendor/{vendor_id}")
def vendor(vendor_id: str) -> dict:
    conn = _conn()
    try:
        v = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if not v:
            raise HTTPException(404, "vendor not found")
        contracts = _rows(
            conn.execute("SELECT * FROM contracts WHERE vendor_id = ?", (vendor_id,))
        )
        links = _rows(
            conn.execute(
                "SELECT * FROM links WHERE vendor_id = ? ORDER BY concern_score DESC",
                (vendor_id,),
            )
        )
        return {"vendor": dict(v), "contracts": contracts, "links": links}
    finally:
        conn.close()
