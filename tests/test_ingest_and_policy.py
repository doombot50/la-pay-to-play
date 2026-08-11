"""Tests for the Act 87 parser helpers, the agency map, and the publish policy.

These cover the bug-prone bits without needing a PDF fixture or a built DB:
the cross-year column-layout handling, money/date parsing, the elected-office
map, the eponymous org<->person gate, and the CF-export consumption contract.
"""
import gzip
import types

import pytest
import requests

from paytoplay import config
from paytoplay.ingest import cf_import
from paytoplay.ingest import contracts_act87 as c87
from paytoplay.resolve import matcher

_CF_HEADER = ("id,donor_name,employer,donor_address,amount,date,"
              "recipient_name,recipient_filer,recipient_office,source_url\n")
_CF_ROW = ('D1,ACME LLC,,"Baton Rouge, LA 70801",500.0,2023-01-01,'
           "AG Candidate,0123,Attorney General,https://example.com/g1\n")

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


def _cf_dir(tmp_path, monkeypatch, text=_CF_HEADER + _CF_ROW, name="cf_donations.csv"):
    (tmp_path / name).write_text(text)
    monkeypatch.setattr(cf_import, "CF_EXPORT_GLOB", str(tmp_path / "cf_donations.*"))
    return tmp_path


def test_cf_export_gz_beside_csv_is_not_counted_twice(tmp_path, monkeypatch):
    # The glob matches cf_donations.csv AND the cf_donations.csv.gz it was
    # unzipped from; pandas reads .gz transparently, so every donation used to
    # be loaded twice (doubling every donor total).
    _cf_dir(tmp_path, monkeypatch)
    with gzip.open(tmp_path / "cf_donations.csv.gz", "wt") as fh:
        fh.write(_CF_HEADER + _CF_ROW)
    assert len(cf_import.load()) == 1


def test_cf_export_identifiers_stay_text(tmp_path, monkeypatch):
    # Inferred dtypes turn filer "0123" into 123 (and into "123.0" once any row
    # has a blank filer) by the time it reaches the served DB.
    _cf_dir(tmp_path, monkeypatch)
    df = cf_import.load()
    assert df["recipient_filer"].iloc[0] == "0123"
    assert df["amount"].iloc[0] == 500.0


def test_cf_export_missing_required_column_raises(tmp_path, monkeypatch):
    # Schema drift used to be filled with a silent default and published.
    _cf_dir(tmp_path, monkeypatch,
            text="id,contributor,amount,date,recipient_name,recipient_office\n"
                 "D1,ACME,500,2023-01-01,AG,Attorney General\n")
    with pytest.raises(ValueError, match="donor_name"):
        cf_import.load()


def test_cf_export_empty_or_moneyless_raises(tmp_path, monkeypatch):
    _cf_dir(tmp_path, monkeypatch, text=_CF_HEADER)
    with pytest.raises(ValueError, match="0 rows"):
        cf_import.load()
    _cf_dir(tmp_path, monkeypatch, text=_CF_HEADER + _CF_ROW.replace(",500.0,", ",,"))
    with pytest.raises(ValueError, match="no positive donation amounts"):
        cf_import.load()


def test_failed_refetch_falls_back_to_the_cached_pdf(tmp_path, monkeypatch):
    # Only the current/previous month is re-fetched; a transient error there
    # used to drop the whole month even with a good PDF already cached.
    monkeypatch.setattr(c87, "PDF_DIR", tmp_path)
    y, m = c87._prev_month(c87.date.today())
    (tmp_path / f"{y}_{m:02d}.pdf").write_bytes(b"%PDF-cached")

    def boom(*a, **k):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(c87.requests, "get", boom)
    assert c87.download(y, m, force=False)[0] == str(tmp_path / f"{y}_{m:02d}.pdf")

    monkeypatch.setattr(c87.requests, "get",
                        lambda *a, **k: types.SimpleNamespace(status_code=503, content=b""))
    assert c87.download(y, m, force=False) is not None
    # ...but a month with no cached copy to fall back on is simply absent.
    assert c87.download(1999, 1, force=False) is None


def test_ingest_refuses_to_clobber_contracts_with_nothing(tmp_path, monkeypatch):
    out = tmp_path / "contracts.parquet"
    monkeypatch.setattr(c87, "CONTRACTS_PARQUET", out)
    monkeypatch.setattr(c87, "download", lambda *a, **k: None)
    with pytest.raises(SystemExit) as e:
        c87.main(["--month", "2024-01"])
    assert e.value.code == 1
    assert not out.exists()


def test_eponymous_person_gate():
    assert matcher._eponymous("Gordon McKernan Injury Attorneys", "Gordon McKernan")
    assert not matcher._eponymous("Smith Construction LLC", "John Smith")
    assert not matcher._eponymous("Acme LLC", "Acme")        # needs >= 2 person tokens
