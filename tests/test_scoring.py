"""Tests for resolve/scoring.py: per-agency isolation and per-office timing."""
from datetime import date

import pandas as pd

from paytoplay.resolve import scoring

AG_MAP = {
    "department of justice": [
        {"name": "Attorney General", "office": "Attorney General", "control": "direct"}
    ],
}


def _donor(**over):
    d = {
        "donation_total": 5_000.0,
        "office_totals": {"Attorney General": 5_000.0},
        "office_dates": {"Attorney General": [date(2023, 5, 1)]},
        "donation_dates": [date(2023, 5, 1)],
        "offices": ["Attorney General"],
    }
    d.update(over)
    return {"D1": d}


def _link():
    return pd.DataFrame(
        [{"vendor_id": "V1", "donor_id": "D1", "lane": "org_org",
          "confidence": 1.0, "status": "published"}]
    )


def test_score_uses_only_the_controlled_agencys_contracts():
    # $2M from DOTD (no control link) must not be credited to the AG
    # relationship; only the $50k DOJ contract counts.
    contracts = pd.DataFrame([
        {"vendor_id": "V1", "amount": 2_000_000.0, "award_date": "2023-06-01",
         "awarding_agency": "Department of Transportation and Development"},
        {"vendor_id": "V1", "amount": 50_000.0, "award_date": "2023-06-01",
         "awarding_agency": "Department of Justice"},
    ])
    out = scoring.score_links(_link(), contracts, _donor(), agency_map=AG_MAP)
    row = out.iloc[0]
    assert row["agency"] == "Department of Justice"
    assert row["contract_total"] == 50_000.0
    assert row["control_office"] == "Attorney General"
    assert row["control_weight"] == 1.0
    assert row["concern_score"] > 0


def test_timing_uses_only_gifts_to_the_scored_office():
    # The donor's only gift NEAR the award went to an unrelated race; the AG
    # gift was years earlier. Timing for the AG relationship must be 0.
    contracts = pd.DataFrame([
        {"vendor_id": "V1", "amount": 50_000.0, "award_date": "2023-06-01",
         "awarding_agency": "Department of Justice"},
    ])
    donors = _donor(
        office_dates={"Attorney General": [date(2018, 1, 1)]},
        donation_dates=[date(2018, 1, 1), date(2023, 6, 1)],  # 2023 gift: other race
    )
    out = scoring.score_links(_link(), contracts, donors, agency_map=AG_MAP)
    assert out.iloc[0]["timing_weight"] == 0.0


def test_money_weight_reference_points():
    assert abs(scoring._money_weight(1_000_000, 999) - 0.5) < 0.01   # ~$1k -> 0.5
    assert scoring._money_weight(1_000_000, 1_000_000) == 1.0        # $1M -> 1.0
    assert scoring._money_weight(0, 1_000) == 0.0
