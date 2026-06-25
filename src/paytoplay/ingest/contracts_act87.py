"""Ingest Louisiana state contracts from the Act 87 of 2015 monthly reports.

Source: the Division of Administration / Office of State Procurement publishes a
machine-readable (text) PDF every month at a predictable URL:

    https://checkbook.la.gov/Reports/Act87/YYYY_MM_Act87Report.pdf   (Aug 2015+)

Each PDF is a landscape table of every contract approved that month. pdfplumber's
table extractor recovers the columns cleanly; we map them by header text (robust
to year-to-year column drift) into the canonical CONTRACTS_SCHEMA and dedupe by
contract id (keeping the latest amendment / largest value).

This is the real replacement for the contracts_latrac.py stub.
contracts_latrac.fetch_from_excel remains the manual-Excel fallback.

Run:
  python -m paytoplay.ingest.contracts_act87                 # 2015-08 .. now
  python -m paytoplay.ingest.contracts_act87 --since 2024    # 2024-01 .. now
  python -m paytoplay.ingest.contracts_act87 --month 2025-06 # one month
  python -m paytoplay.ingest.contracts_act87 --force         # re-download cached
  python -m paytoplay.ingest.contracts_act87 --limit 3       # first N months (test)
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date

import pandas as pd
import pdfplumber
import requests

from ..config import CONTRACTS_PARQUET, RAW, ensure_dirs

CONTRACTS_SCHEMA = [
    "id", "vendor_name", "vendor_address", "amount",
    "award_date", "awarding_agency", "source_url", "record_type",
]

PDF_DIR = RAW / "act87_pdfs"
URL = "https://checkbook.la.gov/Reports/Act87/{year}_{month:02d}_Act87Report.pdf"
FIRST = (2015, 8)
_UA = {"User-Agent": "la-pay-to-play/0.1 (public contract transparency)"}


def _norm_hdr(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "").replace("‐", "-")).strip().lower()


def _clean(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "").replace("‐", "-")).strip()


def _money(cell) -> float:
    s = re.sub(r"[^0-9.]", "", str(cell or ""))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _iso_date(cell) -> str:
    s = _clean(cell)
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return pd.to_datetime(s, format=fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return ""


def _month_range(since_year: int):
    y, m = FIRST
    if since_year > y:
        y, m = since_year, 1
    today = date.today()
    while (y, m) <= (today.year, today.month):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def download(year: int, month: int, force: bool) -> tuple[str, str] | None:
    """Return (local_pdf_path, source_url) or None if the month has no report."""
    ensure_dirs()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    url = URL.format(year=year, month=month)
    dest = PDF_DIR / f"{year}_{month:02d}.pdf"
    is_current = (year, month) >= (date.today().year, date.today().month - 1 or 12)
    if dest.exists() and not force and not is_current:
        return str(dest), url
    try:
        r = requests.get(url, headers=_UA, timeout=60)
    except requests.RequestException as e:
        print(f"  {year}-{month:02d}: fetch error ({e})", file=sys.stderr)
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        print(f"  {year}-{month:02d}: HTTP {r.status_code}, not a PDF", file=sys.stderr)
        return None
    dest.write_bytes(r.content)
    return str(dest), url


def _header_map(row) -> dict | None:
    """Map a header row's cells to canonical field -> column index."""
    cells = [_norm_hdr(c) for c in row]
    if not any("vendor name" in c for c in cells):
        return None
    idx = {}
    for i, c in enumerate(cells):
        if c == "contracting agency":
            idx["agency_code"] = i
        elif "contract id" in c:
            idx["contract_id"] = i
        elif c.startswith("amend"):
            idx["amend"] = i
        elif "vendor name" in c:
            idx["vendor"] = i
        elif "approval" in c:
            idx["approval"] = i
        elif "total amount" in c:
            idx["total"] = i
        elif "brief description" in c:
            idx["desc"] = i
    # The agency NAME may be a separate unlabeled column (newer reports) OR
    # merged with the code in one cell like "01-100 Office of the Governor"
    # (older reports). Only treat the next column as the name if it sits BEFORE
    # the contract-id column — otherwise the layout is merged and we parse the
    # name out of the agency-code cell at row time.
    if ("agency_code" in idx and "contract_id" in idx
            and idx["agency_code"] + 1 < idx["contract_id"]):
        idx["agency_name"] = idx["agency_code"] + 1
    return idx if {"contract_id", "vendor", "total"} <= idx.keys() else None


_AGENCY_CODE = re.compile(r"^\d{2}-\d{3,4}\s*")


def _agency_from(row, idx) -> str:
    """Agency name, handling both the separate-column and merged-cell layouts."""
    if "agency_name" in idx and idx["agency_name"] < len(row):
        name = _clean(row[idx["agency_name"]])
        if name and not name.isdigit():
            return name
    if "agency_code" in idx and idx["agency_code"] < len(row):
        raw = _clean(row[idx["agency_code"]])
        stripped = _AGENCY_CODE.sub("", raw).strip()
        return stripped or raw
    return ""


def parse_pdf(path: str, url: str) -> list[dict]:
    rows: list[dict] = []
    with pdfplumber.open(path) as pdf:
        idx = None
        for pageno, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for row in table:
                    if row is None:
                        continue
                    hm = _header_map(row)
                    if hm:
                        idx = hm
                        continue
                    if idx is None:
                        continue
                    first = _clean(row[0]) if row else ""
                    if not first.isdigit():          # data rows are numbered
                        continue
                    cid = _clean(row[idx["contract_id"]]) if idx["contract_id"] < len(row) else ""
                    vendor = _clean(row[idx["vendor"]]) if idx["vendor"] < len(row) else ""
                    if not cid or not vendor:
                        continue
                    amount = _money(row[idx["total"]]) if idx["total"] < len(row) else 0.0
                    agency = _agency_from(row, idx)
                    award = _iso_date(row[idx["approval"]]) if "approval" in idx and idx["approval"] < len(row) else ""
                    amend = _clean(row[idx["amend"]]) if "amend" in idx and idx["amend"] < len(row) else ""
                    rows.append({
                        "id": cid if not amend else f"{cid}-A{amend}",
                        "_contract_id": cid,
                        "_amend": amend,
                        "vendor_name": vendor,
                        "vendor_address": "",
                        "amount": amount,
                        "award_date": award,
                        "awarding_agency": agency,
                        "source_url": f"{url}#page={pageno}",
                        "record_type": "contract",
                    })
    return rows


def _dedupe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=CONTRACTS_SCHEMA)
    # one row per contract id: keep the latest amendment, else the largest amount
    df["_amend_n"] = pd.to_numeric(df["_amend"], errors="coerce").fillna(0)
    df = (df.sort_values(["_contract_id", "_amend_n", "amount"])
            .drop_duplicates("_contract_id", keep="last"))
    return df[CONTRACTS_SCHEMA].reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=int, default=FIRST[0], help="start year (default 2015)")
    ap.add_argument("--month", help="single month YYYY-MM")
    ap.add_argument("--force", action="store_true", help="re-download cached PDFs")
    ap.add_argument("--limit", type=int, help="cap number of months (testing)")
    args = ap.parse_args(argv)

    if args.month:
        y, m = map(int, args.month.split("-"))
        months = [(y, m)]
    else:
        months = list(_month_range(args.since))
    if args.limit:
        months = months[: args.limit]

    all_rows: list[dict] = []
    ok = missing = 0
    for y, m in months:
        got = download(y, m, args.force)
        if not got:
            missing += 1
            continue
        path, url = got
        try:
            rows = parse_pdf(path, url)
        except Exception as e:
            print(f"  {y}-{m:02d}: parse error ({e})", file=sys.stderr)
            continue
        ok += 1
        all_rows.extend(rows)
        print(f"  {y}-{m:02d}: {len(rows):,} contract rows")

    df = _dedupe(all_rows)
    ensure_dirs()
    df.to_parquet(CONTRACTS_PARQUET, index=False)
    print(f"\n{ok} months parsed, {missing} missing; "
          f"{len(all_rows):,} rows -> {len(df):,} unique contracts -> {CONTRACTS_PARQUET}")


if __name__ == "__main__":
    main()
