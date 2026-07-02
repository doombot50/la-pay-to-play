"""Build the static JSON the public site serves (GitHub Pages, no server).

Reads the pipeline's SQLite DB plus the row-level donations parquet (for
gift-level source links) and emits compact, PUBLISHED-ONLY artifacts into
web/data/. Only links that clear the publish confidence AND the money
materiality gates are emitted — this is the reputational firewall.

Artifacts:
  web/data/meta.json          counts, coverage, thresholds, disclaimer
  web/data/leaderboard.json   ranked vendor<->official concern relationships
  web/data/offices.json       per controlling office -> the companies
  web/data/search.json        name -> {type, id}
  web/data/vendor/<id>.json   per-company profile: contracts + gifts + the link

Run:  python -m paytoplay.build_site
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pandas as pd

from . import config
from .config import MIN_CONTRACT_USD, MIN_DONATION_USD, PUBLISH_CONFIDENCE
from .normalize import names
from .pipeline import _entity_id

SITE = config.ROOT / "web" / "data"
LEADERBOARD_N = 250
GIFTS_PER_VENDOR = 60
DISCLAIMER = (
    "Correlation, not proof. A match means a vendor (or its owner) appears to "
    "have donated to officials connected to its state contracts. It is a lead "
    "for further reporting, never an accusation. Every figure links to a public "
    "filing."
)


def _control_label(office: str, agency_map: dict) -> str:
    for officials in agency_map.values():
        for off in officials:
            if off.get("office", "").lower() == (office or "").lower():
                return off.get("control", "")
    return ""


def _gift_detail(published_donor_ids: set) -> dict[str, list[dict]]:
    """entity_id -> its individual gifts (for source links on the profile)."""
    if not config.DONATIONS_PARQUET.exists():
        return {}
    don = pd.read_parquet(config.DONATIONS_PARQUET)
    for c in ("donor_name", "recipient_name", "recipient_office", "source_url", "date"):
        don[c] = don[c].astype("string").fillna("").astype(str)
    don["amount"] = pd.to_numeric(don["amount"], errors="coerce").fillna(0.0)
    don["_id"] = don["donor_name"].map(lambda n: _entity_id("D", names.entity_key(n)))
    don = don[don["_id"].isin(published_donor_ids)]
    out: dict[str, list[dict]] = {}
    for eid, grp in don.groupby("_id"):
        grp = grp.sort_values("amount", ascending=False).head(GIFTS_PER_VENDOR)
        out[eid] = [
            {
                "amount": round(float(r.amount), 2),
                "date": r.date,
                "recipient": r.recipient_name,
                "office": r.recipient_office,
                "source_url": r.source_url,
            }
            for r in grp.itertuples()
        ]
    return out


def _write(path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return len(text)


def build() -> None:
    if not config.DB_PATH.exists():
        raise SystemExit("No DB. Run the pipeline first (make pipeline).")
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    agency_map = config.load_agency_map()

    # The public site shows only genuine pay-to-play relationships: a strong,
    # material name match AND a real control link (the donation reached an office
    # that controls the awarding agency). control_weight==0 is not pay-to-play.
    links = pd.read_sql_query("SELECT * FROM links WHERE status='published'", conn)
    links = links[(links["contract_total"].fillna(0) >= MIN_CONTRACT_USD)
                  & (links["donation_total"].fillna(0) >= MIN_DONATION_USD)
                  & (links["control_weight"].fillna(0) > 0)]
    vendors = pd.read_sql_query("SELECT * FROM vendors", conn).set_index("id")
    dons = pd.read_sql_query("SELECT * FROM donations", conn).set_index("id")
    contracts = pd.read_sql_query("SELECT * FROM contracts", conn)
    conn.close()

    if SITE.exists():
        for f in SITE.rglob("*.json"):
            f.unlink()

    gift_detail = _gift_detail(set(links["donor_id"]))

    # ── leaderboard (one row per company, its strongest relationship) ──────
    links = (links.sort_values("concern_score", ascending=False)
                  .drop_duplicates("vendor_id", keep="first"))
    board = []
    for r in links.itertuples():
        company = vendors.loc[r.vendor_id]["name"] if r.vendor_id in vendors.index else ""
        board.append({
            "vendor_id": r.vendor_id,
            "company": company,
            "office": r.control_office or "",
            "agency": r.agency or "",
            "contract_total": round(float(r.contract_total or 0), 2),
            "donation_total": round(float(r.donation_total or 0), 2),
            "concern_score": float(r.concern_score or 0),
            "components": {
                "money": float(r.money_weight or 0),
                "control": float(r.control_weight or 0),
                "timing": float(r.timing_weight or 0),
                "match": float(r.match_confidence or 0),
            },
            "lane": r.lane,
            "confidence": float(r.confidence or 0),
        })

    # ── per-vendor profiles ───────────────────────────────────────────────
    contracts_by_v = {vid: g for vid, g in contracts.groupby("vendor_id")}
    for row in board:
        vid = row["vendor_id"]
        cg = contracts_by_v.get(vid)
        contract_list = [] if cg is None else [
            {"id": c.id, "amount": round(float(c.amount or 0), 2),
             "award_date": c.award_date, "agency": c.awarding_agency,
             "source_url": c.source_url}
            for c in cg.sort_values("amount", ascending=False).itertuples()
        ]
        link_donor_id = links[links["vendor_id"] == vid].iloc[0]["donor_id"]
        dent = dons.loc[link_donor_id] if link_donor_id in dons.index else None
        # The link's money figures are agency-specific, so the count shown next
        # to them must be too; the contracts table still lists every agency.
        agency_count = 0 if cg is None else int((cg["awarding_agency"] == row["agency"]).sum())
        _write(SITE / "vendor" / f"{vid}.json", {
            "vendor_id": vid,
            "company": row["company"],
            "office": row["office"],
            "agency": row["agency"],
            "concern_score": row["concern_score"],
            "components": row["components"],
            "contract_total": row["contract_total"],
            "donation_total": row["donation_total"],
            "contract_count": agency_count or len(contract_list),
            "donation_count": int(dent["donation_count"]) if dent is not None else 0,
            "contracts": contract_list,
            "gifts": gift_detail.get(link_donor_id, []),
            "disclaimer": DISCLAIMER,
        })

    # ── offices (the "official" side) ─────────────────────────────────────
    offices: dict[str, dict] = {}
    for row in board:
        o = row["office"] or "(unmapped)"
        bucket = offices.setdefault(o, {
            "office": o, "control": _control_label(row["office"], agency_map),
            "companies": [],
        })
        bucket["companies"].append({
            "vendor_id": row["vendor_id"], "company": row["company"],
            "agency": row["agency"], "contract_total": row["contract_total"],
            "donation_total": row["donation_total"], "concern_score": row["concern_score"],
        })
    offices_list = sorted(offices.values(),
                          key=lambda b: -sum(c["concern_score"] for c in b["companies"]))

    # ── search index ──────────────────────────────────────────────────────
    search = [{"name": r["company"], "type": "vendor", "id": r["vendor_id"]}
              for r in board if r["company"]]
    search += [{"name": b["office"], "type": "office", "id": b["office"]}
               for b in offices_list if b["office"] != "(unmapped)"]

    # ── meta ──────────────────────────────────────────────────────────────
    def _span(df, col):
        s = pd.to_datetime(df[col], errors="coerce").dropna()
        return [s.min().date().isoformat(), s.max().date().isoformat()] if len(s) else ["", ""]

    meta = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "disclaimer": DISCLAIMER,
        "thresholds": {
            "publish_confidence": PUBLISH_CONFIDENCE,
            "min_contract_usd": MIN_CONTRACT_USD,
            "min_donation_usd": MIN_DONATION_USD,
        },
        "counts": {
            "published_links": len(board),
            "companies": len({r["vendor_id"] for r in board}),
            "offices": len([b for b in offices_list if b["office"] != "(unmapped)"]),
            "contracts_total": int(len(contracts)),
        },
        "coverage": {
            "contracts": _span(contracts, "award_date"),
        },
    }

    n = 0
    n += _write(SITE / "meta.json", meta)
    n += _write(SITE / "leaderboard.json", board[:LEADERBOARD_N])
    n += _write(SITE / "offices.json", offices_list)
    n += _write(SITE / "search.json", search)
    print(f"build_site: {len(board)} published links, "
          f"{meta['counts']['companies']} companies, "
          f"{len(offices_list)} offices -> {SITE} ({n/1024:.0f} KB core + profiles)")


if __name__ == "__main__":
    build()
