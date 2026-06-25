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
    assert not names.looks_like_person("Smith Engineering LLC")


def test_address_block_key():
    key = addresses.block_key("123 Main Street, Baton Rouge, LA 70801")
    assert key.startswith("123")
    assert "70801" in key


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
