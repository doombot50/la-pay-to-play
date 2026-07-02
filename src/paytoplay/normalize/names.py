"""Name normalization for both vendors (orgs) and donors (orgs + people).

The goal is a stable `name_key` and a set of `tokens` usable for blocking and
fuzzy comparison. This is intentionally conservative: over-aggressive
normalization creates false matches, which in this product means false
accusations.
"""
from __future__ import annotations

import re

# Corporate suffixes / filler stripped before tokenizing.
_STOPWORDS = {
    "llc", "l.l.c", "inc", "incorporated", "co", "company", "corp", "corporation",
    "ltd", "lp", "llp", "pllc", "pc", "pa", "the", "and", "of", "group", "holdings",
    "enterprises", "services", "service", "associates", "partners", "intl",
    "international", "usa", "us",
}

_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")

# Honorifics / generational suffixes dropped before person comparison.
_HONORIFICS = {
    "dr", "mr", "mrs", "ms", "miss", "jr", "sr", "ii", "iii", "iv", "v",
    "esq", "phd", "md", "hon", "rev",
}

# Nickname bridging, vendored from the CF tool's la_ethics_server._NICK_GROUPS so
# "Bob Smith" and "Robert Smith" resolve to one donor entity. The first form in
# each group is the canonical root. Kept in sync manually (separate repos).
_NICK_GROUPS = [
    "robert bob bobby rob robbie", "william bill billy will willie",
    "richard rick ricky dick rich", "james jim jimmy jimmie",
    "john johnny jack jon", "edward ed eddie eddy ned",
    "gerald gerard jerry jerold jerrold", "michael mike mikey mick",
    "charles charlie chuck chas", "thomas tom tommy",
    "joseph joe joey", "daniel dan danny", "david dave",
    "ronald ron ronnie", "donald don donnie", "kenneth ken kenny",
    "anthony tony", "stephen steven steve stevie", "andrew andy drew",
    "matthew matt", "christopher chris", "nicholas nick",
    "benjamin ben benny", "samuel sam sammy", "timothy tim",
    "patrick pat", "frederick fred freddie", "gregory greg",
    "jeffrey jeff", "jonathan jon", "lawrence larry",
    "raymond ray", "douglas doug", "philip phil phillip",
    "alexander alex", "eugene gene", "vincent vince vinnie",
    "francis frank frankie", "albert al", "walter walt",
    "henry hank harry", "theodore ted teddy", "leonard len lenny",
    "elizabeth liz beth betty lizzie", "margaret maggie meg peggy marge",
    "katherine kathryn kathy kate katie kay", "patricia pat patty tricia",
    "jennifer jen jenny", "deborah deb debbie", "barbara barb",
    "susan sue susie", "rebecca becky", "victoria vicki vicky",
    "cynthia cindy", "christine christina chris tina", "nicole nikki",
    "stephanie steph", "jessica jess", "pamela pam", "sandra sandy",
    "thaddeus thad", "theresa teresa terry terri",
]
_NICK: dict[str, str] = {}
for _grp in _NICK_GROUPS:
    _forms = _grp.split()
    for _f in _forms:
        _NICK[_f] = _forms[0]

# Tokens that pass the 2-3-token person-shape test but are far more likely to
# be a generic / geographic business name ("Gulf Coast", "Crescent City") than
# a human's name. Used to keep the eponymous org<->person publish gate from
# firing on name-prefix collisions between unrelated companies.
GENERIC_PERSON_TOKENS = {
    "louisiana", "gulf", "coast", "coastal", "bayou", "delta", "acadiana",
    "north", "south", "east", "west", "northern", "southern", "eastern",
    "western", "central", "river", "lake", "city", "state", "capital",
    "crescent", "pelican", "cajun", "creole", "parish", "united", "american",
    "national", "global", "premier", "quality", "first", "family",
}


def nick_fold(toks: list[str]) -> list[str]:
    """Fold nickname forms to their canonical root ('bob' -> 'robert')."""
    return [_NICK.get(t, t) for t in toks]


def clean(name: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace."""
    if not name:
        return ""
    s = _PUNCT.sub(" ", name.lower())
    return _WS.sub(" ", s).strip()


def tokens(name: str | None) -> list[str]:
    """Significant tokens with corporate filler removed."""
    return [t for t in clean(name).split() if t and t not in _STOPWORDS]


def name_key(name: str | None) -> str:
    """A stable comparison key: significant tokens, sorted and joined.

    "Smith Engineering, LLC" and "Engineering Smith Inc." -> "engineering smith".
    """
    return " ".join(sorted(tokens(name)))


def looks_like_person(name: str | None) -> bool:
    """Heuristic: 2-3 name tokens (honorifics ignored), no corporate suffix."""
    if not name:
        return False
    raw = [t for t in clean(name).split() if t not in _HONORIFICS]
    if not (2 <= len(raw) <= 3):
        return False
    return not any(t in _STOPWORDS for t in raw)


def person_key(name: str | None) -> str:
    """Order-invariant person key with honorifics dropped and nicknames folded.

    'Bob Smith', 'Smith, Robert' and 'Mr. Robert Smith' all -> 'robert smith'.
    """
    toks = nick_fold([t for t in clean(name).split() if t not in _HONORIFICS])
    if not toks:
        return clean(name)
    return " ".join(sorted(toks))


def entity_key(name: str | None) -> str:
    """Canonical key used to collapse rows into one donor/vendor entity:
    nickname-folded person key for people, corporate-suffix-stripped key for orgs.
    """
    return person_key(name) if looks_like_person(name) else name_key(name)
