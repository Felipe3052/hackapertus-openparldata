import json
from pathlib import Path

from parltopic.ingestion.enrich import document_from_record, enrich_dataset


class FakeClient:
    base_url = "https://example.org"

    def __init__(self):
        self.offsets = []

    def get_json(self, path, params):
        self.offsets.append(params["offset"])
        offset = params["offset"]
        return {
            "data": [{"id": offset + 1, "text": "<p>Software security</p>",
                      "language": "de", "url": "https://example.org/document"}],
            "meta": {"has_more": offset == 0},
        }


def test_enrichment_paginates_caches_and_preserves_labels_and_order(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "output.jsonl"
    rows = [
        {"affair_id": "1", "title": "Sesam", "language": "de", "label": True},
        {"affair_id": "2", "title": "Other", "text": "Full text", "label": False},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    client = FakeClient()
    report = enrich_dataset(source, output, client, tmp_path / "cache", workers=1)
    enriched = [json.loads(line) for line in output.read_text("utf-8").splitlines()]
    assert client.offsets == [0, 1]
    assert report["counts"] == {"enriched": 1, "already_has_text": 1}
    assert len(enriched[0]["documents"]) == 2
    assert enriched[0]["label"] is True
    assert enriched[1] == rows[1]
    assert enriched[0]["documents"][0]["text"] == "Software security"
    enrich_dataset(source, output, client, tmp_path / "cache", workers=1)
    assert client.offsets == [0, 1]
    assert source.read_text("utf-8").count("documents") == 0


def test_document_language_and_empty_text_filters() -> None:
    assert document_from_record({"id": 1, "text": "", "language": "de"}, "de") is None
    assert document_from_record({"id": 1, "text": "Bonjour", "language": "fr"}, "de") is None
    doc = document_from_record({"id": 1, "text": "Text", "url": "bad-url"}, "de")
    assert doc is not None
    assert doc.source_url is None
