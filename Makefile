VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
Q ?=

.PHONY: install scrape load chunk embed store ingest run ask test lint verify

$(PYTHON):
	python3 -m venv $(VENV)

install: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

scrape:
	$(PYTHON) -m src.ingestion.loader

load:
	$(PYTHON) -m src.ingestion.document_loader

chunk:
	$(PYTHON) -m src.ingestion.chunker

embed:
	$(PYTHON) -m src.indexing.embedder

store:
	$(PYTHON) -m src.indexing.vector_store

ingest:
	$(PYTHON) -m src.pipeline ingest

run:
	$(PYTHON) -m streamlit run app/streamlit_app.py

ask:
	$(PYTHON) -m src.pipeline ask "$(Q)"

test:
	$(PYTHON) -m pytest -q
	$(PYTHON) -m ruff check src tests

lint:
	$(PYTHON) -m ruff check src tests

verify:
	$(PYTHON) -c "from src.config import load_config; c = load_config(); print(f'URLs: {len(c.ingestion.urls)}'); print(f'Collection: {c.vector_db.collection}')"
