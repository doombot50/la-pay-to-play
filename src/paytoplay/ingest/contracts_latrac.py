"""Ingest Louisiana state contracts / vendor payments from LaTrac & LA Checkbook.

  LaTrac portal:     https://wwwprd.doa.louisiana.gov/latrac/portal.cfm
  LA Checkbook:      https://checkbook.la.gov/
  PPCS contracts:    submitted monthly to the JLCB (PDF + Excel)

STRATEGY (do the cheap thing first):
  1. Start with the downloadable Excel/CSV exports (Checkbook lets you export
     search results; JLCB publishes monthly contract spreadsheets). Parse those.
  2. Only build a full HTML/AJAX scraper if the exports are insufficient.

This module is a STUB. Its job is to produce `data/raw/contracts.parquet` with
EXACTLY this schema so the rest of the pipeline is decoupled from the source:

    id              str   stable contract/payment id
    vendor_name     str
    vendor_address  str   (may be empty)
    amount          float dollars
    award_date      date  (ISO) — for payments, the payment date
    awarding_agency str   must align with config/agency_officials.yml names
    source_url      str   deep link back to the filing (for the UI citation)
    record_type     str   "contract" | "payment"
"""
from __future__ import annotations

import sys

import pandas as pd

from ..config import CONTRACTS_PARQUET, ensure_dirs

CONTRACTS_SCHEMA = [
    "id", "vendor_name", "vendor_address", "amount",
    "award_date", "awarding_agency", "source_url", "record_type",
]


def fetch_from_excel(path: str) -> pd.DataFrame:
    """Parse a downloaded Checkbook/JLCB export into the canonical schema.

    TODO: map the export's columns to CONTRACTS_SCHEMA. Column names vary by
    export; inspect the file and fill the rename map below.
    """
    df = pd.read_excel(path)
    raise NotImplementedError(
        "Map this export's columns to CONTRACTS_SCHEMA. Columns found: "
        + ", ".join(map(str, df.columns))
    )


def fetch_from_portal() -> pd.DataFrame:  # pragma: no cover - network
    """Scrape the LaTrac portal directly. Implement only if exports fall short."""
    raise NotImplementedError("Portal scraper not implemented; prefer exports.")


def write(df: pd.DataFrame) -> None:
    missing = set(CONTRACTS_SCHEMA) - set(df.columns)
    if missing:
        raise ValueError(f"contracts frame missing columns: {sorted(missing)}")
    ensure_dirs()
    df[CONTRACTS_SCHEMA].to_parquet(CONTRACTS_PARQUET, index=False)
    print(f"wrote {len(df):,} contract rows -> {CONTRACTS_PARQUET}")


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if argv:
        write(fetch_from_excel(argv[0]))
    else:
        print(
            "Usage: python -m paytoplay.ingest.contracts_latrac <export.xlsx>\n"
            "Stub: implement fetch_from_excel() against a real Checkbook export."
        )


if __name__ == "__main__":
    main()
