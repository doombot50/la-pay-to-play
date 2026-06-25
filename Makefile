.PHONY: install ingest pipeline serve test

install:
	pip install -r requirements.txt

ingest:
	python -m paytoplay.ingest.contracts_latrac
	python -m paytoplay.ingest.cf_import

pipeline:
	python -m paytoplay.pipeline

serve:
	uvicorn paytoplay.api.main:app --reload --app-dir src

test:
	pytest -q
