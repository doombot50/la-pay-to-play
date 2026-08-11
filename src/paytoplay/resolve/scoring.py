"""Concern scoring: turn published links + the money on each side into a
transparent 0-100 score per (vendor, official) relationship.

The score is the product of four interpretable components, each returned
alongside the total so the UI can show the math. No black box.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from ..config import TIMING_WINDOW_DAYS, load_agency_map

_CONTROL_WEIGHT = {"direct": 1.0, "board": 0.7, "budget": 0.5}

# Declared so an empty result still carries its columns: pipeline.run() merges
# this frame onto `links` by (vendor_id, donor_id), and a column-less empty
# DataFrame makes that merge raise KeyError instead of yielding empty scores.
SCORED_COLUMNS = [
    "vendor_id", "donor_id", "contract_total", "donation_total", "concern_score",
    "money_weight", "control_weight", "timing_weight", "match_confidence",
    "control_office", "agency", "confidence", "status",
]


def _money_weight(contract_total: float, donation_total: float) -> float:
    """Both sides must be material. Log-scaled, 0-1."""
    if contract_total <= 0 or donation_total <= 0:
        return 0.0
    smaller = min(contract_total, donation_total)
    # ~$1k -> 0.5, ~$50k -> ~0.78, >= $1M -> 1.0
    return min(1.0, math.log10(smaller + 1) / 6.0)


def _timing_weight(award_dates: list[date], donation_dates: list[date]) -> float:
    """Fraction of donations that fall within TIMING_WINDOW_DAYS of any award."""
    if not award_dates or not donation_dates:
        return 0.0
    near = 0
    for dd in donation_dates:
        if any(abs((dd - ad).days) <= TIMING_WINDOW_DAYS for ad in award_dates):
            near += 1
    return near / len(donation_dates)


def _control_weight(agency: str, recipient_office: str, agency_map: dict) -> float:
    officials = agency_map.get((agency or "").strip().lower(), [])
    best = 0.0
    for off in officials:
        if off.get("office", "").lower() == (recipient_office or "").lower():
            best = max(best, _CONTROL_WEIGHT.get(off.get("control", "budget"), 0.5))
    return best


def score_relationship(
    *,
    contract_total: float,
    donation_total: float,
    confidence: float,
    agency: str,
    recipient_office: str,
    award_dates: list[date],
    donation_dates: list[date],
    agency_map: dict | None = None,
) -> dict:
    """Return the concern score (0-100) and its components."""
    agency_map = agency_map if agency_map is not None else load_agency_map()
    money = _money_weight(contract_total, donation_total)
    control = _control_weight(agency, recipient_office, agency_map)
    timing = _timing_weight(award_dates, donation_dates)

    # confidence gates the whole thing; control gates by relevance.
    raw = money * (0.4 + 0.6 * control) * (0.5 + 0.5 * timing) * confidence
    return {
        "score": round(100 * raw, 1),
        "components": {
            "money_weight": round(money, 3),
            "control_weight": round(control, 3),
            "timing_weight": round(timing, 3),
            "match_confidence": round(confidence, 3),
        },
    }


def score_links(
    links: pd.DataFrame,
    contracts: pd.DataFrame,
    donors: dict,
    agency_map: dict | None = None,
) -> pd.DataFrame:
    """Aggregate money per link and attach a concern score to each.

    Expects:
      links:     vendor_id, donor_id, confidence, status
      contracts: vendor_id, amount, award_date, awarding_agency
      donors:    {donor_id: {donation_total: float,
                             donation_dates: list[date],
                             office_totals: {office: float},
                             office_dates: {office: list[date]},
                             offices: list[str]}}  -- pre-aggregated donor entities

    Scoring runs per (awarding agency, recipient office) pair and keeps the
    strongest combination: contract money, award dates and donation money/dates
    are all restricted to that pair, so a vendor's unrelated contracts (or a
    donor's gifts to unrelated races) can't inflate the score of a specific
    control relationship.
    """
    agency_map = agency_map if agency_map is not None else load_agency_map()
    out = []
    c_by_v = contracts.groupby("vendor_id")

    for _, link in links.iterrows():
        donor = donors.get(link["donor_id"])
        if donor is None:
            continue
        try:
            cv = c_by_v.get_group(link["vendor_id"])
        except KeyError:
            continue
        cv = cv.assign(_award=pd.to_datetime(cv["award_date"], errors="coerce"))

        best = None
        best_office = ""
        best_agency = ""
        best_contract_total = 0.0
        office_totals = donor.get("office_totals", {})
        office_dates = donor.get("office_dates", {})
        for agency, cg in cv.groupby("awarding_agency"):
            contract_total = float(cg["amount"].sum())
            award_dates = [d.date() for d in cg["_award"].dropna()]
            for office in donor["offices"] or [""]:
                scored = score_relationship(
                    contract_total=contract_total,
                    donation_total=office_totals.get(office, donor["donation_total"]),
                    confidence=float(link["confidence"]),
                    agency=agency,
                    recipient_office=office,
                    award_dates=award_dates,
                    donation_dates=office_dates.get(office, donor["donation_dates"]),
                    agency_map=agency_map,
                )
                if best is None or scored["score"] > best["score"]:
                    best, best_office = scored, office
                    best_agency, best_contract_total = agency, contract_total

        if best is None:
            continue
        out.append(
            {
                "vendor_id": link["vendor_id"],
                "donor_id": link["donor_id"],
                "contract_total": best_contract_total,
                "donation_total": office_totals.get(best_office, donor["donation_total"]),
                "concern_score": best["score"],
                **best["components"],
                # Only name an office when it actually controls the agency; a 0
                # control weight means no real relationship — don't fabricate one.
                "control_office": best_office if best["components"]["control_weight"] > 0 else "",
                "agency": best_agency,
                "confidence": link["confidence"],
                "status": link["status"],
            }
        )
    return pd.DataFrame(out, columns=SCORED_COLUMNS)
