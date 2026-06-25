"""Import campaign-finance donor data exported by la-cf-tool.

la-cf-tool stays the upstream owner of the LA Ethics scrape. It drops flat files
(CSV / JSON / Parquet) into data/external/; this module normalizes them into
`data/external/donations.parquet` with EXACTLY this schema:

    id               str
    donor_name       str
    employer         str    (occupation/employer if present, else "")
    donor_address    str
    amount           float
    date             date   (ISO)
    recipient_name   str    the candidate/committee that received it
    recipient_office str    office sought — used by the agency->official map
    source_url       str    link back to the filing

Point CF_EXPORT_GLOB at whatever the CF tool emits.
"""
from __future__ import annotations

import glob
import sys

import pandas as pd

from ..config import DONATIONS_PARQUET, EXTERNAL, ensure_dirs

DONATIONS_SCHEMA = [
    "id", "donor_name", "employer", "donor_address", "amount",
    "date", "recipient_name", "recipient_office", "source_url",
]

# Adjust to the CF tool's actual export filename(s).
CF_EXPORT_GLOB = str(EXTERNAL / "cf_donations.*")

# Map CF export column names -> our schema. Fill once you see the real export.
COLUMN_MAP: dict[str, str] = {
    # "contributor_name": "donor_name",
    # "contributor_employer": "employer",
    # "contributor_address": "donor_address",
    # "contribution_amount": "amount",
    # "contribution_date": "date",
    # "filer_name": "recipient_name",
    # "office": "recipient_office",
    # "report_url": "source_url",
}


def _read_any(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    if path.endswith((".json", ".ndjson")):
        return pd.read_json(path, lines=path.endswith(".ndjson"))
    return pd.read_csv(path)


def load() -> pd.DataFrame:
    files = sorted(glob.glob(CF_EXPORT_GLOB))
    if not files:
        raise FileNotFoundError(
            f"No CF exports found at {CF_EXPORT_GLOB}. "
            "Drop la-cf-tool's donor export into data/external/."
        )
    frames = [_read_any(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    if COLUMN_MAP:
        df = df.rename(columns=COLUMN_MAP)
    for col in DONATIONS_SCHEMA:
        if col not in df.columns:
            df[col] = "" if col not in ("amount",) else 0.0
    return df[DONATIONS_SCHEMA]


def write(df: pd.DataFrame) -> None:
    ensure_dirs()
    df.to_parquet(DONATIONS_PARQUET, index=False)
    print(f"wrote {len(df):,} donation rows -> {DONATIONS_PARQUET}")


def main(argv: list[str] | None = None) -> None:
    try:
        write(load())
    except FileNotFoundError as e:
        print(e)
        sys.exit(0)


if __name__ == "__main__":
    main()
