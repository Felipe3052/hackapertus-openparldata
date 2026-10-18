"""Run a compiled topic query on the bulk export (local pre-filter), e.g. over 326,000 affairs.

OpenParlData's search has no prefix matching (`digital:*` returns nothing), so German compounds
such as "Digitalisierungsstrategie" or "Cyberangriff" are missed. Locally, each compiled term is
matched case-insensitively as a word prefix (short acronyms as whole tokens), in every language
version of the title and long title and in the federal submitted text and reasoning.
"""

import re
import time
from pathlib import Path

from parltopic.compiler import CompiledTopic
from parltopic.ingestion.opendata_export import LANGUAGES, load_che_texts, read_ndjson, strip_html


def _pattern(compiled: CompiledTopic) -> re.Pattern:
    alternatives = set()
    for terms in compiled.terms.values():
        for term in terms:
            words = [re.escape(w.casefold()) for w in term.split() if w.strip()]
            if not words:
                continue
            if len(words) == 1 and len(term) <= 3:  # acronyms such as NFT, 5G, KI: whole token
                alternatives.add(rf"(?<!\w){words[0]}(?!\w)")
            else:  # every word is a prefix: keeps compounds and inflections (künstlicher KI)
                alternatives.add(r"(?<!\w)" + r"\w*[\s-]+".join(words))
    return re.compile("|".join(sorted(alternatives, key=len, reverse=True)))


def local_candidates(
    raw_dir: str | Path, compiled: CompiledTopic, ids: set[int] | None = None
) -> tuple[set[int], float]:
    """(matching affair IDs, seconds) for all affairs, or only for `ids`."""
    raw = Path(raw_dir)
    pattern = _pattern(compiled)
    started = time.perf_counter()
    records = [r for r in read_ndjson(raw / "affairs.ndjson.gz") if ids is None or r["id"] in ids]
    che = {r["id"] for r in records if r["body_key"] == "CHE"}
    texts = load_che_texts(raw, che)
    found = set()
    for record in records:
        fields = [record.get(f"{k}_{lang}") for lang in LANGUAGES for k in ("title", "title_long")]
        fields.extend(texts.get(record["id"], {}).values())
        haystack = strip_html(" ".join(f for f in fields if f)).casefold()
        if haystack and pattern.search(haystack):
            found.add(record["id"])
    return found, time.perf_counter() - started
