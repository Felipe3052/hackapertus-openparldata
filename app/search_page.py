"""Streamlit view: one topic across parliaments, from a sentence to evidenced hits in minutes.

1. Apertus compiles the topic into search terms per language (editable).
2. OpenParlData's own search returns candidates per parliament (seconds).
3. Apertus checks the newest candidates; hits show the original passage and a link.
"""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import streamlit as st

from parltopic.classification.service import ClassificationService
from parltopic.compiler import LANGUAGES, CompiledTopic, compile_topic, newest_matches
from parltopic.config import get_settings
from parltopic.ingestion.live import fetch_affair
from parltopic.models import ClassificationResult, TopicDefinition

PARLIAMENTS = {
    "Bund (CHE)": "CHE", "Bern": "BE", "Zürich": "ZH", "Genf": "GE", "Waadt": "VD",
    "Tessin": "TI", "Wallis": "VS", "Basel-Stadt": "BS", "Luzern": "LU", "St. Gallen": "SG",
    "Aargau": "AG", "Stadt Zürich": "261", "Stadt Bern": "351",
}


def render() -> None:
    st.subheader("Thema über Parlamente suchen")
    st.caption("Ein Satz genügt. Apertus schreibt die Suchbegriffe in vier Sprachen; OpenParlDatas "
               "eigene Suche liefert Kandidaten; Apertus prüft sie und zeigt die Belegstelle.")
    st.warning("Begrenzte Vorauswahl: neueste 100 Suchtreffer je Parlament und Sprache, "
               "zusätzlich nach Titelbegriffen gefiltert. Keine vollständige Bestandssuche. "
               "Die bisher gemessenen Vorfilter erreichten etwa 59–68 % Treffer-Recall; "
               "für diese Live-Rangfolge liegt kein Recall-Nachweis vor.")
    name = st.text_input(
        "Thema", value="", placeholder="z. B. Künstliche Intelligenz in der Schule", key="s_name"
    )
    description = st.text_area(
        "Beschreibung", value="",
        placeholder="Optional: Einsatz, Regulierung und Risiken des Themas beschreiben.",
        key="s_desc",
    )
    terms = st.text_input(
        "Eigene Begriffe (optional, kommagetrennt)", value="",
        placeholder="z. B. KI, ChatGPT, maschinelles Lernen", key="s_terms",
    )
    topic = TopicDefinition(
        topic_id=name.casefold().strip().replace(" ", "-")[:60] or "topic", name=name,
        description=description, synonyms=[t.strip() for t in terms.split(",") if t.strip()],
        prompt_version="topic-v1", keyword_rule=False,
    )
    topic_hash = hashlib.sha256(topic.model_dump_json().encode()).hexdigest()
    if st.session_state.get("s_topic_hash") != topic_hash:
        st.session_state["s_topic_hash"] = topic_hash
        st.session_state.pop("s_compiled", None)
        st.session_state.pop("s_hits", None)

    if st.button("1 · Suchbegriffe von Apertus schreiben lassen", disabled=not name.strip()):
        try:
            with st.spinner("Apertus kompiliert das Thema …"):
                compiled = compile_topic(topic, get_settings(), prompt_version="compiler-core")
            st.session_state["s_compiled"] = compiled.model_dump(mode="json")
            st.session_state.pop("s_hits", None)
            for language in LANGUAGES:
                st.session_state[f"s_terms_{language}"] = "\n".join(
                    compiled.terms.get(language, [])
                )
        except Exception as error:
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 403:
                st.error(
                    "Kompilierung fehlgeschlagen: CSCS verweigert den Zugriff (HTTP 403). "
                    "Der Key ist geladen, aber für diesen Endpoint oder dieses Modell nicht "
                    "berechtigt. Prüfe den CSCS-Zugriff und LLM_NAME; dies ist kein Fehler "
                    "deines eingegebenen Themas."
                )
            else:
                st.error(f"Kompilierung fehlgeschlagen: {error}")

    if "s_compiled" not in st.session_state:
        return
    compiled = CompiledTopic.model_validate(st.session_state["s_compiled"])
    st.caption(f"{compiled.model} · {compiled.input_tokens}/{compiled.output_tokens} Tokens · "
               f"{(compiled.latency_ms or 0) / 1000:.0f} s. Begriffe prüfen und anpassen:")
    columns = st.columns(len(LANGUAGES))
    for column, language in zip(columns, LANGUAGES, strict=True):
        edited = column.text_area(language.upper(), "\n".join(compiled.terms.get(language, [])),
                                  height=220, key=f"s_terms_{language}")
        compiled.terms[language] = [t.strip() for t in edited.splitlines() if t.strip()]

    chosen = st.multiselect("Parlamente", list(PARLIAMENTS), ["Bund (CHE)", "Bern", "Tessin"])
    since = st.text_input("Geschäfte ab (JJJJ-MM-TT)", "2025-01-01")
    limit = st.slider("Höchstens so viele Kandidaten prüfen", 5, 40, 10)

    if st.button("2 · Kandidaten suchen und prüfen", type="primary", disabled=not chosen):
        started = time.perf_counter()
        try:
            with st.spinner("OpenParlData-Suche …"):
                pool = newest_matches(compiled, [PARLIAMENTS[c] for c in chosen])
        except Exception as error:
            st.error(f"Suche fehlgeschlagen: {error}")
            return
        ranked = [r for r in pool if r["score"] > 0 and (not r["date"] or r["date"] >= since)]
        candidates = [r["id"] for r in ranked]
        searched = time.perf_counter() - started
        st.write(f"**{len(pool)} neueste Suchtreffer** in {searched:.1f} s, davon "
                 f"{len(ranked)} mit spezifischen Themenbegriffen im Titel (geprüft wird in "
                 "dieser Reihenfolge).")

        def check(affair_id: int):
            try:
                affair = fetch_affair(affair_id, documents=1)
                if affair.date and affair.date < since:
                    return None
                return affair.model_dump(mode="json"), service.classify(
                    affair, topic
                ).model_dump(mode="json")
            except Exception as error:
                result = ClassificationResult(
                    affair_id=str(affair_id), topic_id=topic.topic_id, status="failed",
                    language="unknown", model=get_settings().llm_name,
                    needs_review=True, error=str(error),
                )
                return {"affair_id": str(affair_id)}, result.model_dump(mode="json")

        with st.spinner(f"Apertus prüft die neuesten {limit} Kandidaten …"):
            with ClassificationService(get_settings()) as service, ThreadPoolExecutor(8) as workers:
                checked = [r for r in workers.map(check, candidates[:limit]) if r]
        st.session_state["s_hits"] = checked
        st.session_state["s_time"] = time.perf_counter() - started

    hits = st.session_state.get("s_hits")
    if hits is None:
        return
    assigned = [(a, r) for a, r in hits if r["status"] in ("assigned", "uncertain")]
    st.success(f"{len(assigned)} von {len(hits)} Ergebnissen sind Vorschläge (inkl. unsicher) "
               f"({st.session_state['s_time']:.0f} s insgesamt).")
    failures = [r for _, r in hits if r["status"] == "failed"]
    if failures:
        st.warning(f"{len(failures)} technische Fehler; diese sind keine negativen Entscheidungen.")
        with st.expander("Technische Fehler"):
            st.json(failures)
    st.download_button("Alle Suchergebnisse als JSON", json.dumps(hits, ensure_ascii=False),
                       file_name="search-results.json", mime="application/json")
    for affair, result in assigned:
        label = "Unsicher – bitte prüfen" if result["status"] == "uncertain" else "Passt"
        with st.expander(f"{label} · {affair['parliament']} · {affair['date']} · "
                         f"{affair['title'][:110]}"):
            st.write(result["explanation"])
            for evidence in result.get("evidence") or []:
                st.info(evidence["text"][:600])
                if evidence.get("source_url"):
                    st.link_button("Originalquelle", evidence["source_url"])
            st.caption(f"OpenParlData-ID {affair['affair_id']} · {affair['language']} · "
                       f"{result['model']}")
    rejected = [a["title"][:90] for a, r in hits if r["status"] == "not_assigned"]
    if rejected:
        with st.expander(f"{len(rejected)} Kandidaten abgelehnt"):
            st.write("\n".join(f"- {t}" for t in rejected))
