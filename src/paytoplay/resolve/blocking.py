"""Blocking: generate plausible (vendor, donor) candidate pairs without an O(n*m)
all-pairs comparison.

A pair is a candidate if vendor and donor share ANY of:
  - an address block key (street number + zip5)
  - a significant name token

Each side is expected to be a DataFrame already carrying normalized columns
produced by the `normalize` package:
  vendors: id, name, name_tokens (list[str]), addr_block (str)
  donors:  id, name, name_tokens (list[str]), addr_block (str)
"""
from __future__ import annotations

import sys
from collections import defaultdict

import pandas as pd

# A shared token whose block would produce more candidate pairs than this is
# too common to be a useful signal ("construction", "louisiana") — comparing
# everyone to everyone inside it is noise, so the block is skipped (and logged).
MAX_BLOCK_PAIRS = 50_000


def _index_by(df: pd.DataFrame, key_col_or_tokens: str, is_tokens: bool) -> dict:
    idx: dict[str, list] = defaultdict(list)
    for row_id, val in zip(df["id"], df[key_col_or_tokens]):
        if is_tokens:
            for tok in val or []:
                idx[tok].append(row_id)
        elif val:
            idx[val].append(row_id)
    return idx


def candidate_pairs(vendors: pd.DataFrame, donors: pd.DataFrame) -> set[tuple]:
    """Return a set of (vendor_id, donor_id) candidate pairs."""
    pairs: set[tuple] = set()

    # Address-block collisions
    v_addr = _index_by(vendors, "addr_block", is_tokens=False)
    d_addr = _index_by(donors, "addr_block", is_tokens=False)
    for key, v_ids in v_addr.items():
        for d_id in d_addr.get(key, []):
            for v_id in v_ids:
                pairs.add((v_id, d_id))

    # Shared significant name token
    v_tok = _index_by(vendors, "name_tokens", is_tokens=True)
    d_tok = _index_by(donors, "name_tokens", is_tokens=True)
    skipped: list[tuple[str, int]] = []
    for tok, v_ids in v_tok.items():
        d_ids = d_tok.get(tok)
        if not d_ids:
            continue
        # Skip ultra-common tokens that would explode the block.
        if len(v_ids) * len(d_ids) > MAX_BLOCK_PAIRS:
            skipped.append((tok, len(v_ids) * len(d_ids)))
            continue
        for v_id in v_ids:
            for d_id in d_ids:
                pairs.add((v_id, d_id))

    if skipped:
        top = ", ".join(t for t, _ in sorted(skipped, key=lambda s: -s[1])[:8])
        print(f"blocking: skipped {len(skipped)} oversized token blocks "
              f"(most common: {top})", file=sys.stderr)
    return pairs
