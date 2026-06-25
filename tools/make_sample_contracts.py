#!/usr/bin/env python3
"""
make_sample_contracts.py — SAMPLE/DEMO contracts fixture (NOT real LaTrac data)
===============================================================================
Real contract ingest lives in paytoplay.ingest.contracts_latrac and is still a
stub. To exercise the full pipeline end-to-end on REAL donor data in the
meantime, this builds data/raw/contracts.parquet from actual organizational
donors in the CF export who gave to an elected official that controls some
agency (per config/agency_officials.yml).

  REAL:      vendor names, the office they donated to, the control linkage.
  SYNTHETIC: contract dollar amounts and award dates (clearly fake, derived).

So the "concern score" chain is genuine in structure and names; only the
contract magnitudes are invented. Replace this with contracts_latrac once a
LaTrac/Checkbook export is in hand — the pipeline downstream is identical.

Run:  python tools/make_sample_contracts.py [--limit 40]
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

import pandas as pd

# Make `paytoplay` importable when run as a script from repo root.
sys.path.insert(0, "src")
from paytoplay import config                       # noqa: E402
from paytoplay.normalize import names              # noqa: E402

# Names that read as a real vendor/contractor rather than an individual.
_VENDORISH = (
    "llc", "inc", "corp", "company", "co", "group", "construction", "engineering",
    "contractors", "services", "associates", "architects", "consulting", "energy",
    "capital", "partners", "enterprises", "solutions", "systems", "industries",
    "holdings", "development", "properties", "management", "technologies",
)


def _looks_vendorish(name: str) -> bool:
    toks = names.clean(name).split()
    return any(t in _VENDORISH for t in toks) and not names.looks_like_person(name)


def _office_to_agency() -> dict[str, tuple[str, str]]:
    """office (lower) -> (agency_display, control), inverted from the raw YAML."""
    import yaml

    with open(config.AGENCY_MAP_PATH) as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, tuple[str, str]] = {}
    for entry in raw.get("agencies", []):
        for off in entry["officials"]:
            out[off["office"].strip().lower()] = (entry["agency"], off.get("control", "budget"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="max sample vendors")
    ap.add_argument("--min-donation", type=float, default=1000.0,
                    help="min total donations for a donor to qualify")
    args = ap.parse_args()

    if not config.DONATIONS_PARQUET.exists():
        # fall back to the CSV the CF exporter drops
        csvs = list(config.EXTERNAL.glob("cf_donations.*"))
        if not csvs:
            print("No donations found. Run paytoplay.ingest.cf_import first.")
            sys.exit(1)
        don = pd.read_csv(csvs[0])
    else:
        don = pd.read_parquet(config.DONATIONS_PARQUET)

    don["amount"] = pd.to_numeric(don["amount"], errors="coerce").fillna(0.0)
    don["recipient_office"] = don["recipient_office"].fillna("").astype(str)
    don["_date"] = pd.to_datetime(don["date"], errors="coerce")

    office_to_agency = _office_to_agency()
    controllable = set(office_to_agency)

    don["entity_key"] = don["donor_name"].map(names.entity_key)
    don = don[don["donor_name"].map(_looks_vendorish)]
    # keep only gifts to a controllable elected office
    don = don[don["recipient_office"].str.strip().str.lower().isin(controllable)]
    if don.empty:
        print("No vendor-ish donors gave to a controllable office — widen the map.")
        sys.exit(1)

    rows = []
    for ekey, g in don.groupby("entity_key"):
        total = float(g["amount"].sum())
        if total < args.min_donation:
            continue
        name = g["donor_name"].mode().iat[0]
        office = g["recipient_office"].mode().iat[0]
        agency, _control = office_to_agency[office.strip().lower()]
        last_gift = g["_date"].max()
        award = (last_gift + timedelta(days=120)) if pd.notna(last_gift) else pd.Timestamp("2024-06-01")
        # SYNTHETIC amount: scale donations up to a plausible contract size.
        amount = round(total * 25, 2)
        rows.append({
            "id": "C-SAMPLE-" + ekey.replace(" ", "_")[:40],
            "vendor_name": name,
            "vendor_address": "",
            "amount": amount,
            "award_date": award.date().isoformat(),
            "awarding_agency": agency,
            "source_url": "SAMPLE-DATA-not-a-real-filing",
            "record_type": "contract",
        })

    rows.sort(key=lambda r: -r["amount"])
    rows = rows[: args.limit]
    if not rows:
        print("No qualifying sample vendors above --min-donation.")
        sys.exit(1)

    df = pd.DataFrame(rows)
    config.ensure_dirs()
    df.to_parquet(config.CONTRACTS_PARQUET, index=False)
    print(f"[SAMPLE] wrote {len(df)} synthetic contracts -> {config.CONTRACTS_PARQUET}")
    print("  (real vendor names + control linkage; SYNTHETIC amounts/dates)")
    print(df[["vendor_name", "awarding_agency", "amount"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
