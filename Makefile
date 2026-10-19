.PHONY: install test lint api web demo run run-live

# Clean-checkout jury entrypoint; no .env or paid model request required to view replay.
run:
	docker build -t parltopic-jury .
	docker run --rm -p 8501:8501 parltopic-jury

# Existing image; Python's dotenv parser removes quotes around keys and model names.
run-live:
	$(if $(wildcard .venv/bin/python),.venv/bin/python,python3) scripts/run_live_demo.py

install:
	python -m pip install -e '.[dev]'

test:
	python -m pytest

lint:
	python -m ruff check src tests app

api:
	python -m uvicorn parltopic.api:app --reload --port 8000

web:
	python -m streamlit run app/streamlit_app.py --browser.gatherUsageStats false

demo:
	python -m parltopic.cli classify --input data/demo/affairs.jsonl --topic configs/topics/digitalisation.yaml --offline

