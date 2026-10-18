"""Fetch one affair live from the OpenParlData API and map it onto the Affair contract.

The API's flat record uses the same field names as the bulk export, so the export mapper applies
unchanged. Federal texts (submitted text, reasoning, lead) and the first attached documents are
added; the Federal Council's answer is left out, as in the evaluation data.
"""

from functools import lru_cache
from typing import Any

import httpx

from parltopic.ingestion.opendata_export import CHE_TEXT_TYPES, strip_html, to_affair
from parltopic.models import Affair, Document

API = "https://api.openparldata.ch/v1"


def _get(client: httpx.Client, path: str, **params: Any) -> Any:
    response = client.get(f"{API}{path}", params=params)
    response.raise_for_status()
    body = response.json()
    return body.get("data", body)


@lru_cache(maxsize=512)
def _body(body_id: int) -> dict[str, Any]:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        data = _get(client, f"/bodies/{body_id}", lang_format="flat")
    return data[0] if isinstance(data, list) else data


def fetch_affair(
    affair_id: int | str,
    language: str | None = None,
    documents: int = 2,
    max_chars: int = 1500,
    client: httpx.Client | None = None,
) -> Affair:
    own = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True)
    try:
        record = _get(client, f"/affairs/{affair_id}", lang_format="flat")
        record = record[0] if isinstance(record, list) else record
        body = _body(record["body_id"]) if record.get("body_id") else None
        affair = to_affair(record, body, language=language)
        if affair is None:
            raise ValueError(f"Affair {affair_id} has no title in any language")
        texts = _get(client, f"/affairs/{affair_id}/texts", limit=50) or []
        parts = []
        for row in texts:
            kind = row.get("type") or {}
            kind_de = kind.get("de") if isinstance(kind, dict) else kind
            body_text = row.get("text") or {}
            if kind_de in CHE_TEXT_TYPES and isinstance(body_text, dict):
                text = strip_html(body_text.get(affair.language) or body_text.get("de"))
                if text:
                    parts.append(text)
        docs = []
        if documents:
            for row in (_get(client, f"/affairs/{affair_id}/docs", limit=documents,
                             fields="id,text,url_oparl,url") or [])[:documents]:
                text = (row.get("text") or "").strip()
                url = row.get("url_oparl") or row.get("url")
                if text:
                    docs.append(Document(
                        document_id=str(row["id"]), text=text[:max_chars],
                        source_url=url if isinstance(url, str) and url.startswith("http") else None,
                    ))
        update = {"documents": docs}
        if parts:
            update["text"] = "\n\n".join([affair.text, *parts]).strip()[:4000]
        return affair.model_copy(update=update)
    finally:
        if own:
            client.close()
