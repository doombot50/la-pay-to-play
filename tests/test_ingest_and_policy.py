"""Tests for the Act 87 parser helpers, the agency map, and the publish policy.

These cover the bug-prone bits without needing a PDF fixture or a built DB:
the cross-year column-layout handling, money/date parsing, the elected-office
map, and the eponymous org<->person gate.
"""
from paytoplay import config
from paytoplay.ingest import contracts_act87 as c87
from paytoplay.resolve import matcher

# A header row for the OLD layout: agency code+name share one cell, so the
# Contract ID column sits immediately after "Contracting Agency".
_MERGED_HDR = ["#", "Contracting Agency", "Contract ID", "Amend. #", "Vendor Name",
               "Contract Type", "Begin", "End", "Approval Date",
               "SGF", "IAT", "Fees", "Stat. Ded.", "Federal",
               "Total Amount of Contract", "Brief Description", "Discretionary?"]
_MERGED_ROW = ["1", "01-100 Office of the Governor", "2000629247", "", "Acme LLC",
               "Personal", "1/1/2022", "1/2/2022", "1/14/2022",
               "", "", "", "", "", "$6,900.00", "speaker", "Non-Discretionary"]

# NEW layout: a separate (unlabeled) agency-name column before Contract ID.
_SEP_HDR = ["#", "Contracting Agency", None, "Contract ID", "Amend. #", "Vendor Name",
            "Contract Type", "Begin", "End", "Approval Date",
            "SGF", "IAT", "Fees", "Stat. Ded.", "Federal",
            "Total Amount of Contract", "Brief Description", "Discretionary?"]
_SEP_ROW = ["1", "01-100", "Office of the Governor", "2000919792", "", "Beta Inc",
            "Consulting", "9/1/2025", "9/30/2025", "6/30/2025",
            "", "", "", "", "", "$50,000.00", "purpose", "Non-Discretionary"]


def test_prev_month_rolls_the_year_in_january():
    from datetime import date
    # The old inline expression yielded (2026, 12) in January 2026, so the
    # current month's report was never treated as refreshable.
    assert c87._prev_month(date(2026, 1, 15)) == (2025, 12)
    assert c87._prev_month(date(2026, 7, 2)) == (2026, 6)


def test_money_and_date_parsing():
    assert c87._money("$50,000.00") == 50000.0
    assert c87._money("") == 0.0
    assert c87._iso_date("6/30/2025") == "2025-06-30"
    assert c87._iso_date("garbage") == ""


def test_header_map_distinguishes_layouts():
    merged = c87._header_map(_MERGED_HDR)
    sep = c87._header_map(_SEP_HDR)
    # merged: no separate agency-name column (it would collide with contract id)
    assert "agency_name" not in merged
    # separate: agency-name column detected before contract id
    assert sep["agency_name"] == sep["agency_code"] + 1 < sep["contract_id"]


def test_agency_extracted_from_both_layouts():
    # The bug we fixed: the merged layout must NOT report the contract id as the agency.
    assert c87._agency_from(_MERGED_ROW, c87._header_map(_MERGED_HDR)) == "Office of the Governor"
    assert c87._agency_from(_SEP_ROW, c87._header_map(_SEP_HDR)) == "Office of the Governor"


def test_agency_map_offices_match_sos_strings():
    m = config.load_agency_map()
    # Lieutenant Governor directly heads Culture, Recreation & Tourism
    crt = m["department of culture, recreation, and tourism"][0]
    assert crt["office"] == "Lieutenant Governor" and crt["control"] == "direct"
    # alias resolves to the same official
    assert m["crt"] == m["department of culture, recreation, and tourism"]
    # executive agency routes to the Governor (budget)
    assert m["louisiana department of health"][0]["office"] == "Governor"


def test_eponymous_person_gate():
    assert matcher._eponymous("Gordon McKernan Injury Attorneys", "Gordon McKernan")
    assert not matcher._eponymous("Smith Construction LLC", "John Smith")
    assert not matcher._eponymous("Acme LLC", "Acme")        # needs >= 2 person tokens
