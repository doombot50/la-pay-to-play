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
#    python build_p2p_export.py --since 2016 \
#        --out /path/to/la-pay-to-play/data/external/cf_donations.csv
# 2. Normalize that export -> data/external/donations.parquet
python -m paytoplay.ingest.cf_import

# 3. Contracts. Real LaTrac ingest is still a stub, so for an end-to-end demo:
make sample-contracts        # SAMPLE data: real vendor names, synthetic $/dates
#    (replace with: python -m paytoplay.ingest.contracts_latrac <export.xlsx>)

# 4. Resolve + score + load -> data/processed/paytoplay.db
make pipeline

# 5. Serve the API
make serve   # http://localhost:8000/docs
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
| LaTrac / LA Checkbook | State vendor payments + PPCS contracts | https://checkbook.la.gov , https://wwwprd.doa.louisiana.gov/latrac/portal.cfm |
| LA Ethics Administration | Campaign-finance donations | already scraped by **la-cf-tool**; consumed here as flat files |
| Agency → official map | Which official/board controls each awarding agency | hand-curated, `config/agency_officials.yml` |

## Status

Runs end-to-end on **real LA donations** (2016+) joined to a **sample** contracts
fixture. Real and wired: the CF export bridge (`build_p2p_export.py` in the CF
repo), `cf_import`, name/address normalization (nickname + honorific folding
vendored from the CF tool), donor-entity aggregation, blocking, matching,
concern scoring, SQLite load, and the FastAPI read layer.

Still ahead (the genuinely novel work):
- **Real contracts ingest** — `ingest/contracts_latrac.py` against LaTrac/Checkbook
  exports (currently a sample fixture from `tools/make_sample_contracts.py`).
- **Agency→official map** — expand `config/agency_officials.yml` to the top ~30
  spend agencies (offices must match the SoS office strings the export emits).
- **Frontend** — reuse the CF tool's styling for vendor/official profiles.

See `docs/ARCHITECTURE.md` for the full design and the build phases.
