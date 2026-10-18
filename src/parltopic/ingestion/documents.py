"""Attach a document excerpt to affairs that only have a title (most cantonal parliaments).

Cantonal parliaments publish the content of an affair in attached documents, whose extracted
text the OpenParlData API serves at /v1/affairs/{id}/docs. We keep the document that best
matches the title and attach its opening as an `Affair.documents` entry, so evidence keeps
the document ID and link. Responses are cached on disk.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from parltopic.ingestion.opendata_export import strip_html

API = "https://api.openparldata.ch/v1"
TOKEN_RE = re.compile(r"\w{4,}", re.UNICODE)
SPACE_RE = re.compile(r"[ \t]*\n[\s\n]*")


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(text)}


def fetch_docs(affair_id: str, cache_dir: Path, client: httpx.Client) -> list[dict[str, Any]]:
    path = cache_dir / f"{affair_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = client.get(
        f"{API}/affairs/{affair_id}/docs",
        params={"limit": 20, "fields": "id,name,text,url,url_oparl"},
    )
    response.raise_for_status()
    docs = response.json().get("data", [])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return docs


def best_document(
    title: str, docs: list[dict[str, Any]], max_chars: int = 1500
) -> dict[str, Any] | None:
    """The document whose opening shares most words with the title, cut to its first chars.

    Returned in the shape of `parltopic.models.Document`.
    """
    title_tokens = _tokens(title)
    candidates = [doc for doc in docs if (doc.get("text") or "").strip()]
    if not candidates:
        return None
    best = max(candidates, key=lambda doc: len(title_tokens & _tokens(doc["text"][:3000])))
    text = strip_html(best["text"]) if "<" in best["text"] else best["text"]
    url = best.get("url_oparl") or best.get("url")
    return {
        "document_id": str(best["id"]),
        "text": SPACE_RE.sub("\n", text).strip()[:max_chars],
        "source_url": url if isinstance(url, str) and url.startswith("http") else None,
    }


def enrich_with_documents(
    eval_path: str | Path,
    out_path: str | Path,
    cache_dir: str | Path = "data/cache/docs",
    max_chars: int = 1500,
    workers: int = 8,
) -> dict[str, int]:
    """Copy an eval set, attaching a document excerpt to every title-only affair."""
    rows = [json.loads(line) for line in Path(eval_path).open(encoding="utf-8") if line.strip()]
    todo = [
        row
        for row in rows
        if not row["text"] and not row.get("documents") and row["parliament"] != "CHE"
    ]
    cache = Path(cache_dir)
    with httpx.Client(timeout=60) as client, ThreadPoolExecutor(workers) as pool:
        docs = dict(
            zip(
                (row["affair_id"] for row in todo),
                pool.map(lambda row: fetch_docs(row["affair_id"], cache, client), todo),
                strict=True,
            )
        )
    filled = 0
    for row in todo:
        document = best_document(row["title"], docs[row["affair_id"]], max_chars)
        if document:
            row["documents"] = [document]
            row["text_source"] = "document"
            filled += 1
    out = Path(out_path)
    with out.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"affairs": len(rows), "title_only": len(todo), "filled_from_documents": filled}
