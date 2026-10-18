.PHONY: install test lint api web demo

install:
	python -m pip install -e '.[dev]'

test:
	python -m pytest

lint:
	python -m ruff check src tests app

api:
	python -m uvicorn parltopic.api:app --reload --port 8000

web:
	python -m streamlit run app/streamlit_app.py

demo:
	python -m parltopic.cli classify --input data/demo/affairs.jsonl --topic configs/topics/digitalisation.yaml --offline

