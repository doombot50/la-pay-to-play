"""End-to-end pipeline: ingest -> normalize -> resolve -> score -> load.

Run: python -m paytoplay.pipeline
Assumes data/raw/contracts.parquet and data/external/donations.parquet exist
(produce them with the ingest modules first).
"""
from __future__ import annotations

import sys

import pandas as pd

from . import config
from .db import load as db_load
from .normalize import addresses, names
from .resolve import blocking, matcher, scoring


def _prep_vendors(contracts: pd.DataFrame) -> pd.DataFrame:
    """Collapse contracts to one row per vendor, with normalized match columns."""
    agg = contracts.groupby("vendor_name").agg(
        contract_total=("amount", "sum"),
        contract_count=("amount", "size"),
        address=("vendor_address", "first"),
    ).reset_index()
    agg["id"] = "V" + agg.index.astype(str)
    agg = agg.rename(columns={"vendor_name": "name"})
    agg["name_tokens"] = agg["name"].map(names.tokens)
    agg["addr_block"] = agg["address"].map(addresses.block_key)
    return agg


def _prep_donors(donations: pd.DataFrame) -> pd.DataFrame:
    don = donations.copy()
    don["id"] = don["id"].astype(str)
    don["name"] = don["donor_name"]
    don["name_tokens"] = don["name"].map(names.tokens)
    don["addr_block"] = don["donor_address"].map(addresses.block_key)
    return don


def run() -> None:
    config.ensure_dirs()
    if not config.CONTRACTS_PARQUET.exists() or not config.DONATIONS_PARQUET.exists():
        print(
            "Missing inputs. Run:\n"
            "  python -m paytoplay.ingest.contracts_latrac <export.xlsx>\n"
            "  python -m paytoplay.ingest.cf_import"
        )
        sys.exit(1)

    contracts = pd.read_parquet(config.CONTRACTS_PARQUET)
    donations = pd.read_parquet(config.DONATIONS_PARQUET)
    print(f"loaded {len(contracts):,} contracts, {len(donations):,} donations")

    vendors = _prep_vendors(contracts)
    donors = _prep_donors(donations)

    # map contracts to vendor ids for downstream scoring
    vid = vendors.set_index("name")["id"]
    contracts = contracts.assign(vendor_id=contracts["vendor_name"].map(vid))

    pairs = blocking.candidate_pairs(vendors, donors)
    print(f"blocked to {len(pairs):,} candidate pairs")

    links = matcher.build_links(vendors, donors, pairs)
    print(f"kept {len(links):,} links ({(links.status=='published').sum()} published)")

    scored = scoring.score_links(
        links,
        contracts.rename(columns={"vendor_id": "vendor_id"}),
        donations.rename(columns={"id": "donor_id"}),
    )
    # merge concern fields back onto links
    links = links.merge(
        scored.drop(columns=["confidence", "status"], errors="ignore"),
        on=["vendor_id", "donor_id"],
        how="left",
    )

    db_load.load(
        vendors=vendors[["id", "name", "address", "contract_total", "contract_count"]],
        contracts=contracts[
            ["id", "vendor_id", "amount", "award_date", "awarding_agency",
             "source_url", "record_type"]
        ],
        donations=donations,
        links=links,
    )
    print("pipeline complete.")


if __name__ == "__main__":
    run()
