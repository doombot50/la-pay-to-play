"""Regression tests for the publish firewall in resolve/matcher.py.

The core property: a token-subset name collision ("Gulf Coast" vs "Gulf Coast
Bank") must NEVER auto-publish, while exact-key matches and genuinely
eponymous person<->org matches still do.
"""
import pandas as pd

from paytoplay import config
from paytoplay.resolve import matcher


def _links(vendor_name, donor_name):
    vendors = pd.DataFrame([{"id": "V1", "name": vendor_name, "addr_block": ""}])
    donors = pd.DataFrame(
        [{"id": "D1", "name": donor_name, "employer": "", "addr_block": ""}]
    )
    return matcher.build_links(vendors, donors, {("V1", "D1")})


def test_exact_org_match_publishes():
    out = _links("Acme Engineering LLC", "Acme Engineering Inc")
    assert out.iloc[0]["status"] == "published"
    assert out.iloc[0]["confidence"] == 1.0


def test_subset_cap_below_publish_bar():
    assert config.SUBSET_CONFIDENCE_CAP < config.PUBLISH_CONFIDENCE


def test_subset_org_match_goes_to_review_not_publish():
    # "acme construction" is a strict token-subset of the vendor key; before the
    # cap, token_set_ratio scored this 1.0 and it auto-published.
    out = _links("Acme Construction Group of Louisiana", "Acme Construction Group")
    assert len(out) == 1
    assert out.iloc[0]["status"] == "review"
    assert out.iloc[0]["confidence"] <= config.SUBSET_CONFIDENCE_CAP


def test_generic_two_token_donor_cannot_pose_as_eponymous():
    # "Gulf Coast" passes the 2-3-token person-shape test, and its tokens are
    # embedded in the vendor name — but they're generic, not a person.
    out = _links("Gulf Coast Bank", "Gulf Coast")
    assert len(out) == 1
    assert out.iloc[0]["status"] == "review"


def test_eponymous_person_still_publishes():
    out = _links("Gordon McKernan Injury Attorneys", "Gordon McKernan")
    assert out.iloc[0]["status"] == "published"


def test_eponymous_folds_nicknames():
    assert matcher._eponymous("Robert Smith Construction LLC", "Bob Smith")
    assert not matcher._eponymous("Gulf Coast Bank", "Gulf Coast")
