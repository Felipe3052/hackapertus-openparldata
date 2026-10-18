import json
from pathlib import Path

import pytest

from parltopic.ingestion.opendata_export import load_che_texts


def test_canonical_and_hackathon_text_schemas_normalize_equally(tmp_path: Path) -> None:
    shared = {"type_de": "Eingereichter Text", "text_de": "<p>Digitale Verwaltung</p>",
              "text_fr": "Administration numérique", "text_it": None}
    canonical = tmp_path / "canonical.jsonl"
    legacy = tmp_path / "legacy.jsonl"
    canonical.write_text(json.dumps({"affair_id": 7, **shared}) + "\n", encoding="utf-8")
    legacy.write_text(json.dumps({"openparldata_id": 7, **shared}) + "\n", encoding="utf-8")
    assert load_che_texts(tmp_path, [7], canonical) == load_che_texts(tmp_path, [7], legacy)
    assert load_che_texts(tmp_path, [8], canonical) == {}


def test_text_export_rejects_missing_join_key(tmp_path: Path) -> None:
    source = tmp_path / "invalid.jsonl"
    source.write_text('{"type_de":"Begründung"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing its affair join key"):
        load_che_texts(tmp_path, source_path=source)


def test_submitted_text_precedes_reasoning_regardless_of_export_order(tmp_path: Path) -> None:
    source = tmp_path / "texts.jsonl"
    rows = [
        {"id": 1, "affair_id": 7, "type_de": "Begründung", "text_de": "Reasoning"},
        {"id": 2, "affair_id": 7, "type_de": "Eingereichter Text", "text_de": "Request"},
        {"id": 3, "affair_id": 7, "type_de": "Antwort BR / Büro", "text_de": "Answer"},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    assert load_che_texts(tmp_path, source_path=source) == {7: {"de": "Request\n\nReasoning"}}
