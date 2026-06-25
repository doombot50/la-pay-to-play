from paytoplay.normalize import addresses, names
from paytoplay.resolve import scoring


def test_name_key_order_and_suffix_invariant():
    assert names.name_key("Smith Engineering, LLC") == names.name_key(
        "Engineering Smith Inc."
    )


def test_tokens_drop_corporate_filler():
    assert "llc" not in names.tokens("Acme Holdings LLC")
    assert "acme" in names.tokens("Acme Holdings LLC")


def test_looks_like_person():
    assert names.looks_like_person("John Smith")
    assert names.looks_like_person("Mr. John Smith")          # honorific ignored
    assert not names.looks_like_person("Smith Engineering LLC")


def test_person_key_folds_nicknames_and_honorifics():
    assert names.person_key("Bob Smith") == names.person_key("Robert Smith")
    assert names.person_key("Mr. Robert Smith") == names.person_key("Smith, Robert")


def test_entity_key_collapses_person_variants():
    # 'Bob'/'Robert' fold to one donor entity; an org keeps its corporate key
    assert names.entity_key("Bob Jindal") == names.entity_key("Robert Jindal")
    assert names.entity_key("Acme Holdings LLC") == names.name_key("Acme Holdings LLC")


def test_address_block_key():
    key = addresses.block_key("123 Main Street, Baton Rouge, LA 70801")
    assert key.startswith("123")
    assert "70801" in key


def test_address_block_key_requires_street_number():
    # city/state/zip only (the LA Ethics shape) -> no block, no zip-only collisions
    assert addresses.block_key("Baton Rouge, LA 70801") == ""
    assert addresses.block_key("") == ""


def test_money_weight_requires_both_sides():
    assert scoring._money_weight(0, 5000) == 0.0
    assert scoring._money_weight(100000, 50000) > 0.5


def test_score_relationship_gated_by_confidence():
    from datetime import date

    low = scoring.score_relationship(
        contract_total=1_000_000, donation_total=100_000, confidence=0.1,
        agency="Division of Administration",
        recipient_office="Commissioner of Administration",
        award_dates=[date(2024, 1, 1)], donation_dates=[date(2024, 2, 1)],
    )
    high = scoring.score_relationship(
        contract_total=1_000_000, donation_total=100_000, confidence=0.95,
        agency="Division of Administration",
        recipient_office="Commissioner of Administration",
        award_dates=[date(2024, 1, 1)], donation_dates=[date(2024, 2, 1)],
    )
    assert high["score"] > low["score"]
