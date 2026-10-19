"""Streamlit view: one topic across parliaments, from a sentence to evidenced hits in minutes.

1. Apertus compiles the topic into search terms per language (editable).
2. OpenParlData's own search returns candidates per parliament (seconds).
3. Apertus checks the newest candidates; hits show the original passage and a link.
4. A person confirms or rejects each hit; the suggestion itself is kept.
"""

import datetime
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import streamlit as st
import ui

from parltopic import integration
from parltopic.classification.service import ClassificationService
from parltopic.compiler import LANGUAGES, CompiledTopic, compile_topic, newest_matches
from parltopic.config import get_settings
from parltopic.ingestion.live import fetch_affair
from parltopic.integration import content_id
from parltopic.models import ClassificationResult, TopicDefinition

ROOT = Path(__file__).resolve().parents[1]
RECORDED = ROOT / "data/demo/search"
PARLIAMENTS = {
    "Bund (CHE)": "CHE", "Bern": "BE", "Zürich": "ZH", "Genf": "GE", "Waadt": "VD",
    "Tessin": "TI", "Wallis": "VS", "Basel-Stadt": "BS", "Luzern": "LU", "St. Gallen": "SG",
    "Aargau": "AG", "Stadt Zürich": "261", "Stadt Bern": "351",
}
BODY_NAMES = {key: name for name, key in PARLIAMENTS.items()}


def render() -> None:
    st.subheader("Thema über Parlamente suchen")
    st.caption("Ein Satz genügt. Apertus schreibt die Suchbegriffe in vier Sprachen; OpenParlDatas "
               "eigene Suche liefert Kandidaten; Apertus prüft sie und zeigt die Belegstelle.")
    with st.expander("Grenzen dieser Live-Suche"):
        st.markdown(
            "Begrenzte Vorauswahl: neueste 100 Suchtreffer je Parlament und Sprache, zusätzlich "
            "nach Titelbegriffen gefiltert. **Keine vollständige Bestandssuche.** Die gemessenen "
            "Vorfilter erreichten etwa 59–68 % Treffer-Recall; für diese Live-Rangfolge liegt kein "
            "Recall-Nachweis vor. Für hohen Recall liest Apertus im Batch jedes Geschäft.")

    recordings = sorted(RECORDED.glob("*.json")) if RECORDED.exists() else []
    if recordings:
        with st.expander("Ohne Netz: aufgezeichneten Suchlauf zeigen"):
            chosen = st.selectbox("Aufzeichnung", recordings, format_func=lambda p: p.stem)
            if st.button("Aufzeichnung abspielen"):
                st.session_state["s_replay"] = json.loads(chosen.read_text("utf-8"))
            if st.session_state.get("s_replay") and st.button("Zurück zur Live-Suche"):
                st.session_state.pop("s_replay")
    replay = st.session_state.get("s_replay")
    if replay:
        st.info(f"Aufgezeichneter Lauf vom {replay.get('recorded_at', '?')[:10]} – "
                f"Thema «{replay['topic']['name']}». Kein Modellaufruf.")
        show_terms(replay.get("terms") or {})
        show_hits(replay["hits"], replay.get("seconds", 0), replay.get("matched") or {},
                  replay["topic"], replay.get("terms") or {})
        return

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
    topic_hash = hashlib.sha256(topic.model_dump_json().encode()).hexdigest()
    if st.session_state.get("s_topic_hash") != topic_hash:
        st.session_state["s_topic_hash"] = topic_hash
        st.session_state.pop("s_compiled", None)
        st.session_state.pop("s_hits", None)

    if st.button("1 · Suchbegriffe von Apertus schreiben lassen", disabled=not name.strip()):
        try:
            with st.spinner("Apertus übersetzt das Thema in Suchbegriffe (DE/FR/IT/RM) …"):
                compiled = compile_topic(topic, get_settings(), prompt_version="compiler-core")
            st.session_state["s_compiled"] = compiled.model_dump(mode="json")
            st.session_state.pop("s_hits", None)
            for language in LANGUAGES:
                st.session_state[f"s_terms_{language}"] = "\n".join(
                    compiled.terms.get(language, [])
                )
        except Exception as error:
            st.error(f"Kompilierung fehlgeschlagen: {error}")

    if "s_compiled" not in st.session_state:
        return
    compiled = CompiledTopic.model_validate(st.session_state["s_compiled"])
    st.caption(f"{compiled.model} · {compiled.input_tokens}/{compiled.output_tokens} Tokens · "
               f"{(compiled.latency_ms or 0) / 1000:.0f} s. Begriffe prüfen und anpassen – "
               "allgemeine Wörter wie «Verwaltung» löschen verbessert die Rangfolge:")
    columns = st.columns(len(LANGUAGES))
    for column, language in zip(columns, LANGUAGES, strict=True):
        edited = column.text_area(language.upper(), "\n".join(compiled.terms.get(language, [])),
                                  height=220, key=f"s_terms_{language}")
        compiled.terms[language] = [t.strip() for t in edited.splitlines() if t.strip()]

    where, when, how_many = st.columns([2, 1, 1])
    chosen = where.multiselect("Parlamente", list(PARLIAMENTS), ["Bund (CHE)", "Bern", "Tessin"])
    since = when.date_input("Geschäfte ab", datetime.date(2025, 1, 1),
                            format="DD.MM.YYYY").isoformat()
    limit = how_many.slider("Höchstens so viele Kandidaten prüfen", 5, 40, 10)

    if st.button("2 · Kandidaten suchen und prüfen", type="primary", disabled=not chosen):
        started = time.perf_counter()
        try:
            with st.spinner("OpenParlData-Suche über die gewählten Parlamente …"):
                pool = newest_matches(compiled, [PARLIAMENTS[c] for c in chosen])
        except Exception as error:
            st.error(f"Suche fehlgeschlagen: {error}")
            return
        ranked = [r for r in pool if r["score"] > 0 and (not r["date"] or r["date"] >= since)]
        candidates = [r["id"] for r in ranked][:limit]
        searched = time.perf_counter() - started
        st.write(f"**{len(pool)} neueste Suchtreffer** in {searched:.1f} s, davon "
                 f"{len(ranked)} mit spezifischen Themenbegriffen im Titel. Apertus prüft die "
                 f"ersten {len(candidates)}.")

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

        progress = st.progress(0.0, text="Apertus prüft die Kandidaten …")
        done = {}
        with ClassificationService(get_settings()) as service, ThreadPoolExecutor(8) as workers:
            futures = {workers.submit(check, c): c for c in candidates}
            for count, future in enumerate(as_completed(futures), 1):
                done[futures[future]] = future.result()
                fits = sum(1 for r in done.values() if r and r[1]["status"] == "assigned")
                progress.progress(count / len(candidates),
                                  text=f"{count}/{len(candidates)} geprüft · {fits} passen")
        progress.empty()
        st.session_state["s_hits"] = [done[c] for c in candidates if done[c]]
        st.session_state["s_matched"] = {str(r["id"]): r.get("matched_terms", []) for r in ranked}
        st.session_state["s_time"] = time.perf_counter() - started

    hits = st.session_state.get("s_hits")
    if hits is None:
        return
    terms_now = {language: compiled.terms.get(language, []) for language in LANGUAGES}
    show_hits(hits, st.session_state["s_time"], st.session_state.get("s_matched") or {},
              topic.model_dump(mode="json"), terms_now)


def show_terms(terms: dict) -> None:
    columns = st.columns(max(len(terms), 1))
    for column, (language, words) in zip(columns, terms.items(), strict=False):
        column.markdown(f"**{language.upper()}**  \n" + " · ".join(words))


def show_hits(hits: list, seconds: float, matched: dict, topic: dict, terms: dict) -> None:
    counts = {status: sum(1 for _, r in hits if r["status"] == status)
              for status in ("assigned", "uncertain", "not_assigned", "failed")}
    cols = st.columns(5)
    cols[0].metric("Geprüft", len(hits))
    cols[1].metric("✅ Passen", counts["assigned"])
    cols[2].metric("⚠️ Unsicher", counts["uncertain"])
    cols[3].metric("⚪ Kein Bezug", counts["not_assigned"])
    cols[4].metric("Dauer", f"{seconds:.0f} s")
    if counts["failed"]:
        st.warning(f"{counts['failed']} technische Fehler; diese sind keine negativen "
                   "Entscheidungen.")
        with st.expander("Technische Fehler"):
            st.json([r for _, r in hits if r["status"] == "failed"])
    st.download_button("Suchlauf als JSON sichern", json.dumps({
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(), "topic": topic,
        "terms": terms, "seconds": seconds, "matched": matched, "hits": hits,
    }, ensure_ascii=False, indent=1), file_name="search-results.json", mime="application/json")

    proposals = [(a, r) for a, r in hits if r["status"] in ("assigned", "uncertain")]
    if not proposals:
        return
    reviewer = st.text_input("Kürzel der prüfenden Person", key="s_reviewer",
                             placeholder="z. B. FW – dann jeden Treffer bestätigen oder ablehnen")
    reviewed = st.session_state.setdefault("s_reviews", {})
    highlight = [*topic.get("synonyms", []), *(w for words in terms.values() for w in words)]
    for affair, result in proposals:
        affair_id = str(affair["affair_id"])
        with st.container(border=True):
            parliament = BODY_NAMES.get(affair.get("parliament"), affair.get("parliament"))
            st.markdown(f"**{ui.badge(result['status'])}** · {parliament} · {affair.get('date')} "
                        f"· {affair.get('language', '').upper()}")
            st.markdown(f"#### {affair.get('title', '')}")
            st.write(result["explanation"])
            for evidence in (result.get("evidence") or [])[:2]:
                ui.quote(evidence["text"], highlight, limit=500)
            found = matched.get(affair_id)
            st.caption((f"Gefunden über: {', '.join(found)} · " if found else "")
                       + f"OpenParlData-ID {affair_id} · {ui.decision_path(result)}")
            links, ok, no = st.columns([2, 1, 1])
            url = affair.get("source_url") or next(
                (e.get("source_url") for e in result.get("evidence") or [] if e.get("source_url")),
                None)
            if url:
                links.link_button("Originalquelle", url)
            key = f"{affair_id}:{result['topic_id']}"
            if key in reviewed:
                done = reviewed[key]
                verb = "bestätigt" if done["review_decision"] == "confirmed" else "abgelehnt"
                ok.success(f"{verb} ({done['reviewed_by']})")
                continue
            decision = None
            if ok.button("👍 Passt", key=f"ok-{key}", disabled=not reviewer.strip(),
                         use_container_width=True):
                decision = "confirmed"
            if no.button("👎 Passt nicht", key=f"no-{key}", disabled=not reviewer.strip(),
                         use_container_width=True):
                decision = "rejected"
            if decision:
                reviewed[key] = integration.record_review({
                    "affair_id": affair_id, "topic_id": result["topic_id"],
                    "suggested_status": result["status"], "review_decision": decision,
                    "reviewed_by": reviewer.strip(),
                    "reviewed_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "prediction_id": content_id(result), "prediction": result,
                    "context": {"view": "search", "topic_definition": topic,
                                "compiled_terms": terms},
                    "review_note": None,
                    "corrected_status": "not_assigned" if decision == "rejected" else None,
                }, ROOT / "results/reviews.jsonl")
                st.rerun()
    rejected = [(a, r) for a, r in hits if r["status"] == "not_assigned"]
    if rejected:
        with st.expander(f"{len(rejected)} Kandidaten ohne Bezug zum Thema"):
            for affair, result in rejected:
                st.markdown(f"- **{affair.get('title', '')[:110]}** – {result['explanation']}")
