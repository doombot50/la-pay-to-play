"""End-to-end pipeline test on synthetic frames: ingest parquet -> resolve ->
score -> SQLite -> build_site JSON, all under a temp directory.

Covers the wiring the unit tests can't: entity collapsing, blocking, the
publish policy, per-agency scoring, the DB load, and the site's publish gates.
"""
import json

import pandas as pd

from paytoplay import build_site, config, pipeline
from paytoplay.db import load as db_load

CONTRACTS = [
    # published case: exact org<->org name match, real control link (DOJ -> AG)
    {"id": "C1", "vendor_name": "Acme Engineering LLC", "vendor_address": "",
     "amount": 60_000.0, "award_date": "2023-06-01",
     "awarding_agency": "Department of Justice",
     "source_url": "https://example.com/c1", "record_type": "contract"},
    # same vendor, unrelated agency: must not inflate the AG relationship
    {"id": "C2", "vendor_name": "Acme Engineering, LLC", "vendor_address": "",
     "amount": 2_000_000.0, "award_date": "2023-06-01",
     "awarding_agency": "Department of Transportation and Development",
     "source_url": "https://example.com/c2", "record_type": "contract"},
    # subset-collision case: must stay review-only
    {"id": "C3", "vendor_name": "Gulf Coast Bank", "vendor_address": "",
     "amount": 500_000.0, "award_date": "2023-06-01",
     "awarding_agency": "Department of Justice",
     "source_url": "https://example.com/c3", "record_type": "contract"},
]

DONATIONS = [
    {"id": "g1", "donor_name": "Acme Engineering Inc", "employer": "",
     "donor_address": "", "amount": 2_500.0, "date": "2023-05-15",
     "recipient_name": "AG Candidate", "recipient_filer": "F1",
     "recipient_office": "Attorney General",
     "source_url": "https://example.com/g1"},
    {"id": "g2", "donor_name": "Gulf Coast", "employer": "",
     "donor_address": "", "amount": 5_000.0, "date": "2023-05-15",
     "recipient_name": "AG Candidate", "recipient_filer": "F1",
     "recipient_office": "Attorney General",
     "source_url": "https://example.com/g2"},
]


def test_pipeline_and_site(tmp_path, monkeypatch):
    raw, ext, proc = tmp_path / "raw", tmp_path / "external", tmp_path / "processed"
    db = proc / "paytoplay.db"
    site = tmp_path / "site"
    monkeypatch.setattr(config, "RAW", raw)
    monkeypatch.setattr(config, "EXTERNAL", ext)
    monkeypatch.setattr(config, "PROCESSED", proc)
    monkeypatch.setattr(config, "CONTRACTS_PARQUET", raw / "contracts.parquet")
    monkeypatch.setattr(config, "DONATIONS_PARQUET", ext / "donations.parquet")
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(db_load, "DB_PATH", db)
    monkeypatch.setattr(build_site, "SITE", site)
    config.ensure_dirs()

    pd.DataFrame(CONTRACTS).to_parquet(config.CONTRACTS_PARQUET, index=False)
    pd.DataFrame(DONATIONS).to_parquet(config.DONATIONS_PARQUET, index=False)

    pipeline.run()
    build_site.build()

    meta = json.loads((site / "meta.json").read_text())
    board = json.loads((site / "leaderboard.json").read_text())

    # Only the exact Acme match is published; "Gulf Coast" stays in review.
    assert meta["counts"]["published_links"] == 1
    assert len(board) == 1
    row = board[0]
    assert row["company"].startswith("Acme Engineering")
    assert row["office"] == "Attorney General"
    assert row["agency"] == "Department of Justice"
    # Per-agency isolation: the $2M DOTD contract must not be in this figure.
    assert row["contract_total"] == 60_000.0
    assert row["donation_total"] == 2_500.0
    assert row["components"]["control"] == 1.0
    assert 0 < row["concern_score"] <= 100

    profile = json.loads((site / "vendor" / f"{row['vendor_id']}.json").read_text())
    assert profile["contract_count"] == 1            # DOJ contracts only
    assert len(profile["contracts"]) == 2            # table still shows all
    assert profile["gifts"][0]["source_url"] == "https://example.com/g1"
    assert profile["disclaimer"]
