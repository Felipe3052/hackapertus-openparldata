"""Topic compiler: Apertus turns a topic into a multilingual query for OpenParlData's own search.

Instead of reading every affair for every new topic, Apertus reads the topic once and writes the
search terms an affair on it would contain, in German, French, Italian and Romansh. OpenParlData's
existing PostgreSQL full-text search (boolean mode, per-language stemming, titles and documents)
returns the candidates in seconds; Apertus then verifies only those. The compiled terms are plain
text: a person can read, edit and save them with the topic before anything is classified.
"""

import json
import re
import time
from collections.abc import Iterable
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from parltopic.config import Settings
from parltopic.models import TopicDefinition

OPD_API = "https://api.openparldata.ch/v1"
LANGUAGES = ("de", "fr", "it", "rm")
# PostgreSQL tsquery operators and punctuation would change or break the boolean query.
_UNSAFE = re.compile(r"[&|!():*<>'\"\\]")

COMPILER_PROMPTS = {
    "compiler-v1": """You write full-text search terms for Swiss parliamentary affairs (federal,
cantonal and municipal; titles, submitted texts and attached documents).

Given a topic, list for each language the words and short phrases that an affair on this topic is
likely to contain: official terms, everyday words, synonyms, acronyms, names of typical systems,
programmes and laws, and functional equivalents. Swiss usage matters (e.g. "Kantonsrat",
"Velo", "Natel"). Prefer word stems and single words; use a phrase of at most three words only
when the single words would be too general. Avoid generic words that also occur in many affairs
on other topics.

Return one JSON object with exactly these keys: "de", "fr", "it", "rm" — each a list of 15 to 40
strings — and "excluded": a list of up to 10 short notes on what the topic does not cover.""",
    "compiler-v2": """You write the search terms of a high-recall pre-filter for Swiss parliamentary
affairs (federal, cantonal and municipal parliaments; titles and submitted texts). Every term is
matched as a word PREFIX, so a short stem covers compounds and inflections: "cyber" matches
"Cyberangriff" and "Cybermobbing", "elektronisch" matches "elektronischen", "informati" matches
"Informatik" and "informatique". Missing an affair is worse than an extra candidate; a second step
checks every candidate.

For the topic, list per language 40 to 80 terms:
- stems of the topic's core words and of the words around it (verbs, adjectives, nouns);
- concrete technologies, systems, products, services, platforms and practices that affairs name
  instead of the topic itself (brand and system names, devices, acronyms such as KI, IT, AI, IA);
- Swiss administrative and political vocabulary for the topic;
- short phrases (two words) only where a single stem would match mostly unrelated affairs.
Do not list stems shorter than four letters except well-known acronyms.

Return one JSON object with exactly these keys: "de", "fr", "it", "rm" — each a list of strings —
and "excluded": a list of up to 10 short notes on what the topic does not cover.""",
}
COMPILER_PROMPT = COMPILER_PROMPTS["compiler-v2"]


class CompiledTopic(BaseModel):
    topic_id: str
    prompt_version: str = "compiler-v1"
    terms: dict[str, list[str]] = Field(default_factory=dict)
    excluded: list[str] = Field(default_factory=list)
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None

    def query(self, language: str) -> str:
        """Boolean tsquery for OpenParlData: terms joined by OR, phrases as adjacent words."""
        parts = []
        for term in self.terms.get(language, []):
            words = [w for w in _UNSAFE.sub(" ", term).split() if w]
            if words:
                parts.append(" <-> ".join(words) if len(words) > 1 else words[0])
        return " | ".join(dict.fromkeys(parts))


def compile_topic(
    topic: TopicDefinition, settings: Settings, prompt_version: str = "compiler-v2"
) -> CompiledTopic:
    """One Apertus call: topic name, description and examples in, search terms per language out."""
    examples = "\n".join(f"- {e}" for e in topic.positive_examples) or "- none"
    user = (
        f"TOPIC: {topic.name}\nDESCRIPTION: {topic.description}\n"
        f"KNOWN TERMS: {', '.join(topic.synonyms) or 'none'}\nIN-SCOPE EXAMPLES:\n{examples}"
    )
    started = time.perf_counter()
    response = httpx.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_name,
            "temperature": 0,
            "max_tokens": 6000,
            "messages": [
                {"role": "system", "content": COMPILER_PROMPTS[prompt_version]},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=max(settings.llm_timeout_seconds, 180),
    )
    response.raise_for_status()
    body = response.json()
    payload = json.loads(body["choices"][0]["message"]["content"])
    # The user's own terms (often multilingual already) stay in every language's query.
    terms = {
        lang: list(dict.fromkeys([*topic.synonyms, *[str(t) for t in payload.get(lang, [])]]))
        for lang in LANGUAGES
    }
    usage = body.get("usage", {})
    return CompiledTopic(
        topic_id=topic.topic_id,
        prompt_version=prompt_version,
        terms=terms,
        excluded=[str(x) for x in payload.get("excluded", [])][:10],
        model=settings.llm_name,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def search_candidates(
    compiled: CompiledTopic,
    languages: Iterable[str] = ("de", "fr", "it"),
    scope: str = "all",
    bodies: Iterable[str] | None = None,
    page_size: int = 1000,
    client: httpx.Client | None = None,
) -> dict[str, list[int]]:
    """Affair IDs that OpenParlData's full-text search returns for each language's query.

    The search backend ignores date filters and gets slow at deep offsets (about 60 s per page
    at offset 5,000), so the query runs per parliament (`body_key`), which keeps every request
    to one or a few pages; filter by date locally.
    """
    own = client is None
    client = client or httpx.Client(timeout=300, follow_redirects=True)
    found: dict[str, list[int]] = {}
    try:
        for language in languages:
            query = compiled.query(language)
            if not query:
                continue
            ids: list[int] = []
            for body_key in bodies or [None]:
                ids.extend(_search_window(client, query, language, scope, body_key, page_size))
            found[language] = list(dict.fromkeys(ids))
    finally:
        if own:
            client.close()
    return found


def _search_window(client, query, language, scope, body_key, page_size) -> list[int]:
    ids, offset = [], 0
    while True:
        params = {
            "search": query, "search_mode": "boolean", "search_scope": scope,
            "search_language": language, "limit": page_size, "offset": offset, "fields": "id",
        }
        if body_key:
            params["body_key"] = body_key
        page = client.get(f"{OPD_API}/affairs/", params=params)
        page.raise_for_status()
        data = page.json()
        rows = data.get("data", [])
        ids.extend(int(row["id"]) for row in rows)
        total = data.get("meta", {}).get("total_records") or 0
        offset += page_size
        # Stop on the last page; never trust has_more alone (it can stay true).
        if not rows or offset >= total or not data.get("meta", {}).get("has_more"):
            return ids


def save(compiled: CompiledTopic, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(compiled.model_dump_json(indent=2), encoding="utf-8")
