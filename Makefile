.PHONY: install ingest sample-contracts pipeline serve test

# Editable install puts `paytoplay` on the path so `python -m paytoplay.*` works.
install:
	pip install -r requirements.txt
	pip install -e .

ingest:
	python -m paytoplay.ingest.contracts_latrac
	python -m paytoplay.ingest.cf_import

# SAMPLE/DEMO contracts so the pipeline runs end-to-end before real LaTrac
# ingest exists. Real vendor names + control linkage; synthetic $/dates.
sample-contracts:
	python tools/make_sample_contracts.py

pipeline:
	python -m paytoplay.pipeline

serve:
	uvicorn paytoplay.api.main:app --reload --app-dir src

test:
	pytest -q
