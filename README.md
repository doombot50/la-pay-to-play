# LA Pay-to-Play

Links **Louisiana state contracts and payments** (LaTrac / Louisiana Checkbook) to
**campaign-finance donations** (LA Ethics Administration) to surface where contractor
money and the officials who control those contracts overlap.

Neither dataset tells the story alone. A vendor payment is just a payment; a donation
is just a donation. The value is the **join** — and because the two datasets share no
common key, the whole product is the quality of that fuzzy match.

> ⚠️ **This tool shows _correlation, not proof._** A match means "this vendor (or its
> owner) appears to have donated to officials connected to its contracts." It is a
> lead, not an accusation. Every figure links back to the underlying public filing.

## How it works

```
  CONTRACTS (LaTrac)          DONATIONS (LA Ethics, via la-cf-tool exports)
  vendor, $, date, agency     donor, employer, address, $, date, recipient
            \                                 /
             \         entity resolution     /
              \   (name + address fuzzy match)
               \                            /
                +----------> links <-------+
                                |
                          scoring layer
                 (totals, donation→award timing,
                  transparent "concern score")
                                |
                          SQLite + FastAPI
                                |
                         vendor / official
                          profile pages
```

Pipeline stages (see `src/paytoplay/pipeline.py`):

1. **ingest** — pull contracts from LaTrac; import donor flat files from the CF tool.
2. **normalize** — standardize names and addresses on both sides.
3. **resolve** — block candidate pairs, fuzzy-match, write a `links` table with scores.
4. **score** — per-vendor / per-official aggregates + concern score.
5. **load** — write everything to SQLite for the API/frontend.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install                                        # deps + editable install

# 1. Export donations from the CF repo (la-cf-tool), stdlib-only, into this repo:
#    python build_p2p_export.py --since 2015 \
#        --out /path/to/la-pay-to-play/data/external/cf_donations.csv
# 2. Normalize that export -> data/external/donations.parquet
python -m paytoplay.ingest.cf_import

# 3. Ingest real state contracts (Act 87 monthly reports, parsed with pdfplumber):
make contracts               # -> data/raw/contracts.parquet  (downloads + caches PDFs)

# 4. Resolve + score + load -> data/processed/paytoplay.db
make pipeline

# 5. Build the static site JSON, then serve it
make build-site              # -> web/data/*.json (published-only)
make serve-static            # http://localhost:8000   (leaderboard-first SPA)
# (or `make serve` for the local FastAPI dev API)
```

> **CF data reality:** the LA Ethics *contributions* export carries no employer,
> no street address, and no office on the contribution row. So the employer-based
> person lane and the street-address lane can't fire from this data; matching is
> name-based, and recipient office is backfilled by filer number from SoS data
> (`build_p2p_export.py`). Bringing in LA SoS business filings (vendor → owner)
> is the highest-value way to recover the person lane later.

## Data sources

| Source | What | Access |
|---|---|---|
| Act 87 of 2015 reports | Monthly state contract awards (vendor, $, agency, dates) | `checkbook.la.gov/Reports/Act87/YYYY_MM_Act87Report.pdf` — parsed by `ingest/contracts_act87.py` |
| LA Ethics Administration | Campaign-finance donations | scraped by **la-cf-tool**; consumed here as a flat `cf_donations.csv` |
| Agency → official map | Which elected official controls each awarding agency | hand-curated, `config/agency_officials.yml` |

## Status

Runs end-to-end on **real Louisiana data**: ~10.7k state contracts (Act 87,
2022+) joined to ~169k donor entities from the CF export, served as a static
**leaderboard-first** site (`web/`, GitHub Pages) backed by precomputed JSON.

Real and wired: the CF export bridge (`build_p2p_export.py` in the CF repo),
`cf_import`, `ingest/contracts_act87.py`, name normalization (nickname +
honorific folding vendored from the CF tool), donor-entity aggregation, blocking,
matching with a tightened publish policy, concern scoring (records the
controlling office), SQLite load, `build_site.py` static artifacts, and the
`web/` SPA. A FastAPI read layer remains for local/dev.

**Reputational firewall:** only strong org↔org matches (confidence ≥ 0.92) with
material money on both sides are published; everything else is review-only and
never reaches the site. Name-prefix (token-subset) matches — "Gulf Coast" vs
"Gulf Coast Bank" — are capped below the publish bar and can only ever reach
the review queue. Matching is **name-based** (the Ethics export has no
employer/address; contract reports have no vendor address), so the person lane
only fires for eponymous vendors. Recipient office is backfilled by filer number
(~27% coverage; statewide constitutional officers are well covered).

Still ahead: LaTrac vendor *payments* (realized $) as a second ingest; LA SoS
business filings (vendor→owner) to recover the person lane; Pages + DNS go-live.

See `docs/ARCHITECTURE.md` for the full design.
