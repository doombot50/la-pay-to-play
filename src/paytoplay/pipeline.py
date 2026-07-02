"""End-to-end pipeline: ingest -> normalize -> resolve -> score -> load.

Run: python -m paytoplay.pipeline
Assumes data/raw/contracts.parquet and data/external/donations.parquet exist
(produce them with the ingest modules first).
"""
from __future__ import annotations

import hashlib
import sys

import pandas as pd

from . import config
from .db import load as db_load
from .normalize import addresses, names
from .resolve import blocking, matcher, scoring


def _entity_id(prefix: str, key: str) -> str:
    return prefix + hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def _clean_str(df: pd.DataFrame, cols: list[str]) -> None:
    """Coerce columns to plain python str — parquet round-trips can hand back
    pyarrow-backed string arrays whose .mode()/.iat path raises IndexError."""
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("").astype(str)


def _first_nonempty_by(don: pd.DataFrame, col: str) -> pd.Series:
    """entity_key -> first non-empty value of `col` (vectorized C path)."""
    sub = don[don[col].str.strip() != ""]
    return sub.groupby("entity_key")[col].first()


def _prep_vendors(contracts: pd.DataFrame) -> pd.DataFrame:
    """Collapse contracts to one row per vendor ENTITY, merging name variants
    ("Berrigan Litchfield LLC" / "Berrigan, Litchfield LLC") via the normalized
    name key, with a representative display name."""
    c = contracts.copy()
    c["_key"] = c["vendor_name"].map(names.name_key)
    c = c[c["_key"].str.len() > 0]
    agg = c.groupby("_key").agg(
        contract_total=("amount", "sum"),
        contract_count=("amount", "size"),
        address=("vendor_address", "first"),
    ).reset_index()
    # display name = most frequent raw vendor_name within the key
    disp = (c.groupby(["_key", "vendor_name"]).size().reset_index(name="n")
              .sort_values("n").drop_duplicates("_key", keep="last")
              .set_index("_key")["vendor_name"])
    agg["name"] = agg["_key"].map(disp)
    agg["id"] = agg["_key"].map(lambda k: _entity_id("V", k))
    agg["name_tokens"] = agg["name"].map(names.tokens)
    agg["addr_block"] = agg["address"].map(addresses.block_key)
    return agg


def _prep_donors(donations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate individual contributions into one row per DONOR ENTITY.

    Each donor gave many gifts to possibly many recipients; the matcher and the
    DB want one entity, not one row per gift. Returns (entity frame, the
    row-level frame) — the caller builds the scorer's per-entity meta lazily for
    just the matched donors, which is far cheaper than for all ~200k entities.
    """
    don = donations.copy()
    _clean_str(don, ["donor_name", "donor_address", "recipient_name",
                     "recipient_filer", "recipient_office", "source_url", "date"])
    don["amount"] = pd.to_numeric(don["amount"], errors="coerce").fillna(0.0)
    don["entity_key"] = don["donor_name"].map(names.entity_key)
    don = don[don["entity_key"].str.len() > 0].copy()
    don["_date"] = pd.to_datetime(don["date"], errors="coerce")

    g = don.groupby("entity_key", sort=True)
    ent = g.agg(
        donation_total=("amount", "sum"),
        donation_count=("amount", "size"),
        date_first=("_date", "min"),
        date_last=("_date", "max"),
    ).reset_index()
    ent["date_first"] = ent["date_first"].dt.strftime("%Y-%m-%d").fillna("")
    ent["date_last"] = ent["date_last"].dt.strftime("%Y-%m-%d").fillna("")

    # Representative display strings: cheap 'first non-empty', not modal.
    for col in ("donor_name", "donor_address", "recipient_name",
                "recipient_filer", "recipient_office", "source_url"):
        ent[col] = ent["entity_key"].map(_first_nonempty_by(don, col)).fillna("")

    ent["id"] = ent["entity_key"].map(lambda k: _entity_id("D", k))
    ent["employer"] = ""
    ent["name"] = ent["donor_name"]
    ent["name_tokens"] = ent["donor_name"].map(names.tokens)
    ent["addr_block"] = ent["donor_address"].map(addresses.block_key)
    return ent, don


def _meta_for(don: pd.DataFrame, donors: pd.DataFrame, donor_ids: set) -> dict:
    """Build the scorer's per-entity meta (total, gift dates, office set) for
    only the donor ids that survived matching."""
    key_by_id = dict(zip(donors["id"], donors["entity_key"]))
    wanted_keys = {key_by_id[i] for i in donor_ids if i in key_by_id}
    sub = don[don["entity_key"].isin(wanted_keys)]
    meta: dict[str, dict] = {}
    for ekey, grp in sub.groupby("entity_key"):
        offices = [o for o in grp["recipient_office"].unique() if o and o.strip()]
        office_totals = {
            o: float(grp.loc[grp["recipient_office"] == o, "amount"].sum())
            for o in offices
        }
        # Dates are kept per office too: the timing weight must only see gifts
        # to the office being scored, not gifts to unrelated races.
        office_dates = {
            o: [d.date() for d in grp.loc[grp["recipient_office"] == o, "_date"].dropna()]
            for o in offices
        }
        meta[_entity_id("D", ekey)] = {
            "donation_total": float(grp["amount"].sum()),
            "office_totals": office_totals,
            "office_dates": office_dates,
            "donation_dates": [d.date() for d in grp["_date"].dropna()],
            "offices": sorted(offices),
        }
    return meta


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
    donors, donor_rows = _prep_donors(donations)
    print(f"resolved {len(vendors):,} vendors, {len(donors):,} donor entities")

    # map contracts to vendor ids (by normalized name key) for downstream scoring
    key2id = dict(zip(vendors["_key"], vendors["id"]))
    contracts = contracts.assign(
        vendor_id=contracts["vendor_name"].map(names.name_key).map(key2id))

    pairs = blocking.candidate_pairs(vendors, donors)
    print(f"blocked to {len(pairs):,} candidate pairs")

    links = matcher.build_links(vendors, donors, pairs)
    print(f"kept {len(links):,} links ({(links.status=='published').sum()} published)")

    donor_meta = _meta_for(donor_rows, donors, set(links["donor_id"]))
    scored = scoring.score_links(links, contracts, donor_meta)
    links = links.merge(
        scored.drop(columns=["confidence", "status"], errors="ignore"),
        on=["vendor_id", "donor_id"],
        how="left",
    )

    donations_db = donors[[
        "id", "donor_name", "employer", "donor_address", "donation_total",
        "donation_count", "date_first", "date_last", "recipient_name",
        "recipient_filer", "recipient_office", "source_url",
    ]]
    db_load.load(
        vendors=vendors[["id", "name", "address", "contract_total", "contract_count"]],
        contracts=contracts[
            ["id", "vendor_id", "amount", "award_date", "awarding_agency",
             "source_url", "record_type"]
        ],
        donations=donations_db,
        links=links,
    )
    print("pipeline complete.")


if __name__ == "__main__":
    run()
