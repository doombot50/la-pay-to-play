"""Score candidate (vendor, donor) pairs into a `links` table.

Match lanes (see docs/ARCHITECTURE.md):
  1. org  <-> org     vendor name vs organizational donor name
  2. org  <-> person  vendor name vs person donor / their employer
  3. address          same normalized address, different names

Confidence is in [0,1]. Anything below REVIEW_CONFIDENCE is dropped; between
REVIEW and PUBLISH goes to review; >= PUBLISH is auto-published.
"""
from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz

from ..config import PUBLISH_CONFIDENCE, REVIEW_CONFIDENCE
from ..normalize import names


def _name_similarity(a: str, b: str) -> float:
    """0-1 token-set similarity, robust to word order and corporate filler."""
    ka, kb = names.name_key(a), names.name_key(b)
    if not ka or not kb:
        return 0.0
    return fuzz.token_set_ratio(ka, kb) / 100.0


def _lane_and_confidence(vendor: dict, donor: dict) -> tuple[str, float]:
    name_sim = _name_similarity(vendor["name"], donor["name"])
    employer_sim = _name_similarity(vendor["name"], donor.get("employer") or "")
    addr_match = bool(
        vendor.get("addr_block")
        and vendor.get("addr_block") == donor.get("addr_block")
    )

    best_name = max(name_sim, employer_sim)
    donor_is_person = names.looks_like_person(donor["name"])

    if best_name >= 0.95:
        lane = "org_person" if donor_is_person else "org_org"
        conf = best_name
    elif best_name >= 0.85:
        lane = "org_person" if donor_is_person else "org_org"
        # an address match lifts a medium name match
        conf = min(1.0, best_name + (0.10 if addr_match else 0.0))
    elif addr_match:
        lane = "address"
        # address-only is inherently weaker; cap it
        conf = 0.60 + 0.25 * best_name
    else:
        lane = "none"
        conf = best_name

    return lane, round(conf, 3)


def build_links(
    vendors: pd.DataFrame, donors: pd.DataFrame, pairs: set[tuple]
) -> pd.DataFrame:
    """Score candidate pairs; return a links DataFrame with a status column."""
    v_by_id = vendors.set_index("id").to_dict("index")
    d_by_id = donors.set_index("id").to_dict("index")

    rows = []
    for v_id, d_id in pairs:
        vendor, donor = v_by_id[v_id], d_by_id[d_id]
        lane, conf = _lane_and_confidence(vendor, donor)
        if lane == "none" or conf < REVIEW_CONFIDENCE:
            continue
        rows.append(
            {
                "vendor_id": v_id,
                "donor_id": d_id,
                "lane": lane,
                "confidence": conf,
                "status": "published" if conf >= PUBLISH_CONFIDENCE else "review",
            }
        )
    return pd.DataFrame(
        rows,
        columns=["vendor_id", "donor_id", "lane", "confidence", "status"],
    )
