"""Enrich title-only inputs with cached original document text, independently of labels."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from parltopic.ingestion.opendata_export import strip_html
from parltopic.ingestion.openparldata_client import OpenParlDataClient
from parltopic.models import Affair, Document


def document_from_record(record: dict[str, Any], language: str) -> Document | None:
    text = strip_html(record.get("text"))
    published_language = record.get("language")
    if not text or (published_language and published_language.lower() != language.lower()):
        return None
    fields = {
        "document_id": str(record["id"]),
        "text": text,
        "language": published_language or language,
        "source_url": record.get("url") or record.get("url_oparl"),
    }
    try:
        return Document(**fields)
    except ValidationError:
        return Document(**{**fields, "source_url": None})


def enrich_dataset(
    input_path: Path,
    output_path: Path,
    client: OpenParlDataClient,
    cache_dir: Path,
    workers: int = 4,
) -> dict[str, Any]:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Enrichment requires a separate output file")
    rows = [json.loads(line) for line in input_path.read_text().splitlines() if line.strip()]
    cache_dir.mkdir(parents=True, exist_ok=True)

    def enrich(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
        affair = Affair.model_validate(row)
        if affair.text.strip() or any(doc.text.strip() for doc in affair.documents):
            return row, "already_has_text"
        try:
            endpoint = f"v1/affairs/{affair.affair_id}/docs"
            key = hashlib.sha256(f"{client.base_url}/{endpoint}".encode()).hexdigest()
            cached = cache_dir / f"{key}.json"
            if cached.exists():
                records = json.loads(cached.read_text(encoding="utf-8"))["data"]
            else:
                records = []
                offset = 0
                while True:
                    response = client.get_json(endpoint, params={"offset": offset, "limit": 100})
                    page = response["data"]
                    records.extend(page)
                    if not response.get("meta", {}).get("has_more", False):
                        break
                    if not page:
                        raise ValueError("Document pagination returned an empty non-final page")
                    offset += len(page)
                temporary = cached.with_suffix(".part")
                temporary.write_text(json.dumps({
                    "fetched_at": datetime.now(UTC).isoformat(), "data": records,
                }, ensure_ascii=False), encoding="utf-8")
                temporary.replace(cached)
            existing_ids = {doc.document_id for doc in affair.documents}
            documents = []
            for record in records:
                document = document_from_record(record, affair.language)
                if document and document.document_id not in existing_ids:
                    documents.append(document.model_dump(mode="json"))
                    existing_ids.add(document.document_id)
            if not documents:
                return row, "no_document_text"
            return {**row, "documents": [*row.get("documents", []), *documents]}, "enriched"
        except Exception as error:
            return {**row, "enrichment_error": str(error)}, "failed"

    counts: dict[str, int] = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(output_path.suffix + ".part")
    with ThreadPoolExecutor(max_workers=workers) as pool, temporary_output.open(
        "w", encoding="utf-8"
    ) as output:
        for row, status in pool.map(enrich, rows):
            counts[status] = counts.get(status, 0) + 1
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary_output.replace(output_path)
    return {"input": str(input_path), "output": str(output_path), "counts": counts}
