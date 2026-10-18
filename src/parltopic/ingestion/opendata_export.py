"""Map OpenParlData bulk exports (files.openparldata.ch) onto the Affair contract."""

import csv
import gzip
import html
import json
import re
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from parltopic.models import Affair

EXPORT_URL = "https://files.openparldata.ch/exports"
LABELS_URL = "https://files.openparldata.ch/hackapertus"
RAW_FILES = {
    f"{EXPORT_URL}/affairs.ndjson.gz": "affairs.ndjson.gz",
    f"{EXPORT_URL}/bodies.ndjson.gz": "bodies.ndjson.gz",
    f"{LABELS_URL}/che_affair_texts.ndjson.gz": "che_affair_texts.ndjson.gz",
    f"{LABELS_URL}/che_affairs_keywords.jsonl": "che_affairs_keywords.jsonl",
    f"{LABELS_URL}/che_topics_vocabulary.csv": "che_topics_vocabulary.csv",
    f"{LABELS_URL}/cantonal_affairs_keywords.jsonl": "cantonal_affairs_keywords.jsonl",
    f"{LABELS_URL}/politmonitor_digitalisierung.csv": "politmonitor_digitalisierung.csv",
    f"{LABELS_URL}/dvs_digitalisierung.csv": "dvs_digitalisierung.csv",
    f"{LABELS_URL}/aps_topics.xlsx": "aps_topics.xlsx",
}
LANGUAGES = ("de", "fr", "it", "rm")
LEVELS = {
    "country": "federal",
    "canton": "cantonal",
    "city": "municipal",
    "municipality": "municipal",
}
# Federal texts that describe the request itself; the Federal Council answer is left out
# because it is long and would let the executive's framing drive the topic decision.
CHE_TEXT_TYPES = ("Eingereichter Text", "Begründung", "Lead")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def download_raw(target_dir: str | Path, overwrite: bool = False) -> list[Path]:
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for url, name in RAW_FILES.items():
        path = target / name
        if overwrite or not path.exists():
            urllib.request.urlretrieve(url, path)
        paths.append(path)
    return paths


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", text))).strip()


def read_ndjson(path: str | Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def load_bodies(raw_dir: str | Path) -> dict[str, dict[str, Any]]:
    return {body["body_key"]: body for body in read_ndjson(Path(raw_dir) / "bodies.ndjson.gz")}


def load_che_texts(
    raw_dir: str | Path, affair_ids: Iterable[int] | None = None
) -> dict[int, dict[str, str]]:
    """Return {openparldata_id: {lang: text}} for submitted text, reasoning and lead."""
    wanted = set(affair_ids) if affair_ids is not None else None
    parts: dict[int, dict[str, list[str]]] = {}
    for row in read_ndjson(Path(raw_dir) / "che_affair_texts.ndjson.gz"):
        affair_id = row["openparldata_id"]
        if wanted is not None and affair_id not in wanted:
            continue
        if row.get("type_de") not in CHE_TEXT_TYPES:
            continue
        for lang in ("de", "fr", "it"):
            text = strip_html(row.get(f"text_{lang}"))
            if text:
                parts.setdefault(affair_id, {}).setdefault(lang, []).append(text)
    return {
        affair_id: {lang: "\n\n".join(texts) for lang, texts in by_lang.items()}
        for affair_id, by_lang in parts.items()
    }


def available_languages(record: dict[str, Any]) -> list[str]:
    return [lang for lang in LANGUAGES if record.get(f"title_{lang}")]


def to_affair(
    record: dict[str, Any],
    body: dict[str, Any] | None,
    language: str | None = None,
    text: str = "",
    max_text_chars: int = 4000,
) -> Affair | None:
    """Build an Affair in one language; None when the affair has no title in any language."""
    languages = available_languages(record)
    if not languages:
        return None
    preferred = (body or {}).get("lang")
    if language not in languages:
        language = (
            preferred.lower() if preferred and preferred.lower() in languages else languages[0]
        )
    title = strip_html(record[f"title_{language}"])
    long_title = strip_html(record.get(f"title_long_{language}"))
    body_parts = [long_title] if long_title and long_title != title else []
    if text:
        body_parts.append(text)
    url = record.get(f"url_external_{language}") or next(
        (
            record[f"url_external_{lang}"]
            for lang in LANGUAGES
            if record.get(f"url_external_{lang}")
        ),
        None,
    )
    fields = {
        "affair_id": str(record["id"]),
        "title": title,
        "text": "\n\n".join(body_parts)[:max_text_chars],
        "language": language,
        "parliament": record["body_key"],
        "level": LEVELS.get((body or {}).get("type"), "unknown"),
        "date": (record.get("begin_date") or "")[:10] or None,
        "source_url": url if url and url.startswith("http") else None,
    }
    try:
        return Affair(**fields)
    except ValidationError:
        # Some parliaments publish malformed URLs; the affair is still usable without one.
        return Affair(**{**fields, "source_url": None})
