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
    """Heuristic: 2-3 tokens, no corporate suffix -> probably a person."""
    if not name:
        return False
    raw = clean(name).split()
    if not (2 <= len(raw) <= 3):
        return False
    return not any(t in _STOPWORDS for t in raw)


def person_key(name: str | None) -> str:
    """For people: 'last first' so 'John Smith' == 'Smith, John' after clean()."""
    toks = clean(name).split()
    if len(toks) < 2:
        return clean(name)
    # treat the longest run as last name heuristically -> just sort tokens
    return " ".join(sorted(toks))
