"""Streamlit view: one topic across parliaments, from a sentence to evidenced hits in minutes.

1. Apertus compiles the topic into search terms per language (editable).
2. OpenParlData's own search returns candidates per parliament (seconds).
3. Apertus checks the newest candidates; hits show the original passage and a link.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from parltopic.classification.service import ClassificationService
from parltopic.compiler import LANGUAGES, CompiledTopic, compile_topic, search_candidates
from parltopic.config import get_settings
from parltopic.ingestion.live import fetch_affair
from parltopic.models import TopicDefinition

PARLIAMENTS = {
    "Bund (CHE)": "CHE", "Bern": "BE", "Zürich": "ZH", "Genf": "GE", "Waadt": "VD",
    "Tessin": "TI", "Wallis": "VS", "Basel-Stadt": "BS", "Luzern": "LU", "St. Gallen": "SG",
    "Aargau": "AG", "Stadt Zürich": "261", "Stadt Bern": "351",
}


def render() -> None:
    st.subheader("Thema über Parlamente suchen")
    st.caption("Ein Satz genügt. Apertus schreibt die Suchbegriffe in vier Sprachen; OpenParlDatas "
               "eigene Suche liefert Kandidaten; Apertus prüft sie und zeigt die Belegstelle.")
    name = st.text_input("Thema", "Künstliche Intelligenz in der Verwaltung", key="s_name")
    description = st.text_area(
        "Beschreibung", "Einsatz, Beschaffung, Regulierung und Risiken von KI-Systemen und "
        "Chatbots in Verwaltung, Schulen und Justiz.", key="s_desc")
    terms = st.text_input("Eigene Begriffe (optional, kommagetrennt)", "KI, ChatGPT", key="s_terms")
    topic = TopicDefinition(
        topic_id=name.casefold().strip().replace(" ", "-")[:60] or "topic", name=name,
        description=description, synonyms=[t.strip() for t in terms.split(",") if t.strip()],
        prompt_version="topic-v1", keyword_rule=False,
    )

    if st.button("1 · Suchbegriffe von Apertus schreiben lassen", disabled=not name.strip()):
        with st.spinner("Apertus kompiliert das Thema …"):
            compiled = compile_topic(topic, get_settings())
        st.session_state["s_compiled"] = compiled.model_dump(mode="json")

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
    limit = st.slider("Neueste Kandidaten von Apertus prüfen", 5, 40, 10)

    if st.button("2 · Kandidaten suchen und prüfen", type="primary", disabled=not chosen):
        started = time.perf_counter()
        with st.spinner("OpenParlData-Suche …"):
            found = search_candidates(compiled, scope="metadata",
                                      bodies=[PARLIAMENTS[c] for c in chosen],
                                      newest_first=True, max_pages=1, page_size=100)
        candidates = sorted({i for ids in found.values() for i in ids}, reverse=True)
        searched = time.perf_counter() - started
        st.write(f"**{len(candidates)} neueste Kandidaten** in {searched:.1f} s "
                 f"({', '.join(f'{k.upper()} {len(v)}' for k, v in found.items())}).")

        def check(affair_id: int):
            affair = fetch_affair(affair_id, documents=1)
            if affair.date and affair.date < since:
                return None
            return affair, service.classify(affair, topic)

        with st.spinner(f"Apertus prüft die neuesten {limit} Kandidaten …"):
            with ClassificationService(get_settings()) as service, ThreadPoolExecutor(8) as pool:
                checked = [r for r in pool.map(check, candidates[: limit * 2]) if r][:limit]
        st.session_state["s_hits"] = [(a.model_dump(mode="json"), r.model_dump(mode="json"))
                                      for a, r in checked]
        st.session_state["s_time"] = time.perf_counter() - started

    hits = st.session_state.get("s_hits")
    if hits is None:
        return
    assigned = [(a, r) for a, r in hits if r["status"] in ("assigned", "uncertain")]
    st.success(f"{len(assigned)} von {len(hits)} geprüften Geschäften passen zum Thema "
               f"({st.session_state['s_time']:.0f} s insgesamt).")
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
