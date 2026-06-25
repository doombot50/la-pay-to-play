"""Address normalization, used both as a match signal and a blocking key.

Uses `usaddress` when available for structured parsing; falls back to a simple
regex normalizer so the pipeline still runs without the optional dependency.
"""
from __future__ import annotations

import re

try:
    import usaddress  # type: ignore

    _HAVE_USADDRESS = True
except Exception:  # pragma: no cover - optional dep
    _HAVE_USADDRESS = False

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[.,#]")

_SUFFIX = {
    "street": "st", "st": "st", "avenue": "ave", "ave": "ave", "boulevard": "blvd",
    "blvd": "blvd", "drive": "dr", "dr": "dr", "road": "rd", "rd": "rd",
    "lane": "ln", "ln": "ln", "court": "ct", "ct": "ct", "highway": "hwy",
    "hwy": "hwy", "suite": "ste", "ste": "ste", "apartment": "apt", "apt": "apt",
    "north": "n", "south": "s", "east": "e", "west": "w",
}


def _basic(addr: str) -> str:
    s = _PUNCT.sub(" ", addr.lower())
    s = _WS.sub(" ", s).strip()
    return " ".join(_SUFFIX.get(tok, tok) for tok in s.split())


def normalize(addr: str | None) -> str:
    """Return a normalized single-line address string ('' if empty)."""
    if not addr:
        return ""
    if _HAVE_USADDRESS:
        try:
            parsed, _ = usaddress.tag(addr)
            ordered = [
                parsed.get("AddressNumber", ""),
                parsed.get("StreetNamePreDirectional", ""),
                parsed.get("StreetName", ""),
                parsed.get("StreetNamePostType", ""),
                parsed.get("OccupancyIdentifier", ""),
                parsed.get("PlaceName", ""),
                parsed.get("StateName", ""),
                parsed.get("ZipCode", ""),
            ]
            return _basic(" ".join(p for p in ordered if p))
        except Exception:
            pass
    return _basic(addr)


def block_key(addr: str | None) -> str:
    """A coarse key for blocking: '<street-number> <zip5>'. Empty if unusable."""
    norm = normalize(addr)
    if not norm:
        return ""
    parts = norm.split()
    number = parts[0] if parts and parts[0].isdigit() else ""
    zip5 = ""
    for p in reversed(parts):
        if p.isdigit() and len(p) == 5:
            zip5 = p
            break
    key = f"{number} {zip5}".strip()
    return key
