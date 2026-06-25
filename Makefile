.PHONY: install ingest contracts pipeline build-site serve serve-static test

# Editable install puts `paytoplay` on the path so `python -m paytoplay.*` works.
install:
	pip install -r requirements.txt
	pip install -e .

# Ingest both sides: real Act 87 contracts + the CF donations export.
# (Drop cf_donations.csv into data/external/ from the CF repo's build_p2p_export.py.)
ingest: contracts
	python -m paytoplay.ingest.cf_import

contracts:
	python -m paytoplay.ingest.contracts_act87

pipeline:
	python -m paytoplay.pipeline

# Build the static JSON the public site serves (published-only).
build-site:
	python -m paytoplay.build_site

# Local dev API over the SQLite DB.
serve:
	uvicorn paytoplay.api.main:app --reload --app-dir src

# Serve the static site locally (after build-site).
serve-static:
	python -m http.server 8000 --directory web

test:
	pytest -q
