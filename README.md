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
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Drop CF donor exports into data/external/ (CSV/JSON/Parquet from la-cf-tool)
# 2. Pull contracts (see TODOs in ingest/contracts_latrac.py)
make ingest

# 3. Run the full pipeline -> data/processed/paytoplay.db
make pipeline

# 4. Serve the API
make serve   # http://localhost:8000/docs
```

## Data sources

| Source | What | Access |
|---|---|---|
| LaTrac / LA Checkbook | State vendor payments + PPCS contracts | https://checkbook.la.gov , https://wwwprd.doa.louisiana.gov/latrac/portal.cfm |
| LA Ethics Administration | Campaign-finance donations | already scraped by **la-cf-tool**; consumed here as flat files |
| Agency → official map | Which official/board controls each awarding agency | hand-curated, `config/agency_officials.yml` |

## Status

Scaffold. Real logic lives in `normalize/`, `resolve/`, and `resolve/scoring.py`.
The LaTrac ingest and CF import are stubbed with the exact shape they must produce —
fill them against the live portal and your CF export schema.

See `docs/ARCHITECTURE.md` for the full design and the build phases.
