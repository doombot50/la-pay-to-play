#!/usr/bin/env python3
"""
list_agencies.py — rank awarding agencies by contract spend.

Drives curation of config/agency_officials.yml: shows which agencies carry the
most contract dollars (so the map covers the highest-leverage ones first) and
which are already mapped.

Run:  python tools/list_agencies.py [--top 40]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

sys.path.insert(0, "src")
from paytoplay import config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    if not config.CONTRACTS_PARQUET.exists():
        print("No contracts.parquet — run paytoplay.ingest.contracts_act87 first.")
        sys.exit(1)

    df = pd.read_parquet(config.CONTRACTS_PARQUET)
    mapped = set(config.load_agency_map())  # agency/alias names, lowercased

    g = (df.groupby("awarding_agency")
           .agg(total=("amount", "sum"), n=("amount", "size"))
           .sort_values("total", ascending=False)
           .reset_index())
    print(f"{len(g)} distinct agencies, {len(df):,} contracts, "
          f"${df['amount'].sum():,.0f} total\n")
    print(f"{'mapped':6} {'contracts':>9} {'total $':>16}  agency")
    for r in g.head(args.top).itertuples():
        flag = "  ok  " if r.awarding_agency.strip().lower() in mapped else "  --  "
        print(f"{flag} {r.n:>9,} {r.total:>16,.0f}  {r.awarding_agency}")


if __name__ == "__main__":
    main()
