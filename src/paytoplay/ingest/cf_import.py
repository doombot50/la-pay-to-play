"""Import campaign-finance donor data exported by la-cf-tool.

la-cf-tool stays the upstream owner of the LA Ethics scrape. It drops flat files
(CSV / JSON / Parquet) into data/external/; this module normalizes them into
`data/external/donations.parquet` with EXACTLY this schema:

    id               str
    donor_name       str
    employer         str    (always "" — not in the LA Ethics contributions export)
    donor_address    str    "<city>, <state> <zip>" — no street line upstream
    amount           float
    date             date   (ISO)
    recipient_name   str    the candidate/committee that received it
    recipient_filer  str    Ethics FilerNumber — collision-free recipient identity
    recipient_office str    office sought — used by the agency->official map
    source_url       str    link back to the filing

The CF repo's build_p2p_export.py emits exactly these columns as cf_donations.csv,
so COLUMN_MAP is empty by default. Point CF_EXPORT_GLOB at that file.

This is the only coupling point with an upstream repo we don't control, and the
weekly Pages build runs unattended, so the load path REFUSES to guess: a missing
required column, an empty export, or an export with no money in it raises rather
than being padded with defaults and published as fact.
"""
from __future__ import annotations

import glob
import os
import sys

import pandas as pd

from ..config import DONATIONS_PARQUET, EXTERNAL, ensure_dirs

DONATIONS_SCHEMA = [
    "id", "donor_name", "employer", "donor_address", "amount",
    "date", "recipient_name", "recipient_filer", "recipient_office", "source_url",
]

# Columns whose absence means the upstream export changed shape in a way that
# would silently produce wrong output: no donor to match on, no money, no dates
# for the timing weight, or no office for the control weight. Fail loudly
# instead of filling a default and publishing a degraded site. `employer` is
# deliberately NOT here — the LA Ethics contributions export never carries it.
REQUIRED_COLUMNS = [
    "donor_name", "amount", "date", "recipient_name", "recipient_office",
]

# Compression suffixes that pandas reads transparently — so a leftover
# cf_donations.csv.gz sitting next to the cf_donations.csv it was unzipped from
# would otherwise be loaded a SECOND time and double every donation total.
_COMPRESSED = (".gz", ".bz2", ".zip", ".xz", ".zst")

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
        return pd.read_json(path, lines=path.endswith(".ndjson"), dtype=str)
    # Everything as text: recipient_filer / id are opaque identifiers, and
    # letting pandas infer them turns filer "0123" into 123 (and, once any row
    # has a blank filer, the whole column into floats -> "123.0"). `amount` is
    # coerced back to a number below.
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _pick_files() -> list[str]:
    """Export files to read, with compressed duplicates of an already-present
    plain file dropped (see _COMPRESSED)."""
    files = sorted(glob.glob(CF_EXPORT_GLOB))
    plain = {f for f in files if not f.endswith(_COMPRESSED)}
    keep = []
    for f in files:
        if f.endswith(_COMPRESSED) and os.path.splitext(f)[0] in plain:
            print(f"skipping {os.path.basename(f)}: already present uncompressed",
                  file=sys.stderr)
            continue
        keep.append(f)
    return keep


def load() -> pd.DataFrame:
    files = _pick_files()
    if not files:
        raise FileNotFoundError(
            f"No CF exports found at {CF_EXPORT_GLOB}. "
            "Drop la-cf-tool's donor export into data/external/."
        )
    frames = [_read_any(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    if COLUMN_MAP:
        df = df.rename(columns=COLUMN_MAP)

    # Schema drift: a renamed/dropped upstream column used to be filled with a
    # silent default here, which publishes a wrong site instead of failing.
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"CF export is missing required column(s) {missing}. "
            f"Columns found: {sorted(df.columns)}. "
            "Upstream (la-campaign-finance/build_p2p_export.py) changed shape — "
            "fix COLUMN_MAP or the export, don't publish from this."
        )
    for col in DONATIONS_SCHEMA:
        if col not in df.columns:
            print(f"note: optional column '{col}' absent from the export",
                  file=sys.stderr)
            df[col] = "" if col != "amount" else 0.0

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    if df.empty:
        raise ValueError(
            f"CF export {files} parsed to 0 rows — empty or truncated download."
        )
    if float(df["amount"].sum()) <= 0:
        raise ValueError(
            "CF export has rows but no positive donation amounts — the `amount` "
            "column is empty or non-numeric (schema drift)."
        )
    return df[DONATIONS_SCHEMA]


def write(df: pd.DataFrame) -> None:
    ensure_dirs()
    df.to_parquet(DONATIONS_PARQUET, index=False)
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    # The date span is the cheapest tell that the upstream handoff went stale or
    # truncated — print it so it is visible in the build log.
    span = (f"{dates.min().date()}..{dates.max().date()}" if len(dates)
            else "no parseable dates")
    print(f"wrote {len(df):,} donation rows ({span}) -> {DONATIONS_PARQUET}")


def main(argv: list[str] | None = None) -> None:
    try:
        write(load())
    except (FileNotFoundError, ValueError) as e:
        # Fail loudly: in CI a missing/broken export must stop the run here, not
        # let a later stage fail confusingly (or run against stale data).
        print(f"cf_import: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
