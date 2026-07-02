# Architecture

## The core problem

Pay-to-play detection is a **record-linkage problem across two datasets with no shared key**:

```
DONORS (have, from la-cf-tool)        CONTRACTS/PAYMENTS (new, from LaTrac)
- donor_name                          - vendor_name
- employer / occupation               - vendor_address
- address                             - amount, award_date
- amount, date                        - awarding_agency
- recipient (official)         ?--?   - (official who controls that agency)
```

"John Smith, donor" and "Smith Engineering LLC, vendor" have no FK between them. The
product **is** the fuzzy join. Everything else is plumbing.

## Three match lanes

1. **org ↔ org** — vendor name matches an organizational donor name.
2. **org ↔ person** — vendor name (or its registered owner) matches a person donor
   (e.g. "Smith Engineering" ↔ donor "John Smith", employer "Smith Engineering").
3. **address collision** — vendor and donor share a normalized address but names
   differ. The spiciest signal; also the noisiest. Always lowest confidence.

Each candidate pair gets a **confidence score** in `[0,1]`. Pairs above a publish
threshold become rows in `links`; borderline pairs go to a human-review queue and are
never published as fact.

## Pipeline

`src/paytoplay/pipeline.py` orchestrates:

| Stage | Module | Output |
|---|---|---|
| ingest contracts | `ingest/contracts_latrac.py` | `data/raw/contracts.parquet` |
| ingest donations | `ingest/cf_import.py` | `data/external/donations.parquet` |
| normalize | `normalize/names.py`, `normalize/addresses.py` | normalized columns |
| block | `resolve/blocking.py` | candidate pairs (avoids O(n²)) |
| match | `resolve/matcher.py` | scored pairs → `links` |
| score | `resolve/scoring.py` | per-vendor / per-official aggregates |
| load | `db/load.py` | `data/processed/paytoplay.db` (SQLite) |

## Why these tech choices

- **Python + pandas + rapidfuzz** — matches the CF tool's stack; rapidfuzz is fast
  C++ fuzzy matching. `usaddress` for address parsing.
- **SQLite as the served store** — single file, trivial to ship and to query from the
  API; analytical joins happen upstream in pandas, so we don't need Postgres here.
  (Swap `db/load.py` if you'd rather target the CF tool's Postgres.)
- **FastAPI** — thin read API over the SQLite file; auto OpenAPI docs.
- **Parquet** between stages — cheap, typed, lets you re-run any stage in isolation.

## Blocking strategy (the scaling key)

Naively comparing every donor to every vendor is N×M. We **block** so we only score
plausible pairs:

- shared normalized address token, OR
- shared significant name token (after dropping LLC/INC/THE/etc.), OR
- same parish/zip prefix.

Only within-block pairs get the expensive fuzzy comparison.

## Concern score (transparent by design)

`resolve/scoring.py` computes a 0–100 score per (vendor, awarding agency,
office) combination and keeps the strongest one per link. Money and dates are
restricted to that combination — a vendor's contracts from unrelated agencies,
or a donor's gifts to unrelated races, never inflate the score. Components:

- **money weight** — log-scaled min(contract $, donation $); both sides must be material.
- **control weight** — does the donation recipient actually control the awarding
  agency (via `config/agency_officials.yml`)? Direct control scores highest.
- **timing weight** — donations clustered near an award date score higher.
- **match confidence** — multiplies everything; a weak match can't produce a high score.

The score is **always shown with its components** in the UI. No black box — this is
reputationally sensitive and must be auditable.

## Agency → official map

`config/agency_officials.yml` is a small, hand-curated lookup from awarding agency to
the statewide official / board / commission that controls its contracts. This is what
turns "a payment from agency X" into "money the people John donated to can steer."
Start small (the biggest-spend agencies) and expand.

## Build phases

- **P0 Scaffold** (this) — repo skeleton, schema, stubs, pipeline wiring.
- **P1 Contracts ingest** — LaTrac bulk exports first, then scraper. Target the
  `contracts.parquet` schema in `ingest/contracts_latrac.py`.
- **P2 Entity resolution** — the real work. Normalize → block → match → links.
- **P3 Scoring** — aggregates + concern score.
- **P4 Frontend** — reuse CF tool styling: leaderboard, vendor profile, official profile.
- **P5 Automate** — `.github/workflows/refresh.yml` re-runs scrape→resolve→score.

## Decoupling from la-cf-tool

The CF tool stays an upstream dependency. It exports flat files (CSV/JSON/Parquet)
into `data/external/`; this repo never imports CF code or touches the CF database
directly. Keeps deploys and failure domains separate.
