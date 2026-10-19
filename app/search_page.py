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
    "Federal (CHE)": "CHE", "Bern": "BE", "Zurich": "ZH", "Geneva": "GE", "Vaud": "VD",
    "Ticino": "TI", "Valais": "VS", "Basel-City": "BS", "Lucerne": "LU", "St. Gallen": "SG",
    "Aargau": "AG", "City of Zurich": "261", "City of Bern": "351",
}
BODY_NAMES = {key: name for name, key in PARLIAMENTS.items()}


def render() -> None:
    st.subheader("Search a topic across parliaments")
    st.caption("One sentence is enough. Apertus writes search terms in four languages; "
               "OpenParlData's own search returns candidates; Apertus checks them and quotes "
               "the evidence.")
    with st.expander("Limits of this live search"):
        st.markdown(
            "Bounded preselection: newest 100 search hits per parliament and language, then "
            "filtered by title terms. **Not a complete corpus search.** The measured prefilters "
            "reached about 59–68 % hit recall; there is no recall evidence for this live ranking. "
            "For high recall, Apertus reads every affair in batch.")

    recordings = sorted(RECORDED.glob("*.json")) if RECORDED.exists() else []
    if recordings:
        with st.expander("Offline: show a recorded search run"):
            chosen = st.selectbox("Recording", recordings, format_func=lambda p: p.stem)
            if st.button("Play recording"):
                st.session_state["s_replay"] = json.loads(chosen.read_text("utf-8"))
            if st.session_state.get("s_replay") and st.button("Back to live search"):
                st.session_state.pop("s_replay")
    replay = st.session_state.get("s_replay")
    if replay:
        st.info(f"Recorded run from {replay.get('recorded_at', '?')[:10]} – "
                f"topic «{replay['topic']['name']}». No model call.")
        show_terms(replay.get("terms") or {})
        show_hits(replay["hits"], replay.get("seconds", 0), replay.get("matched") or {},
                  replay["topic"], replay.get("terms") or {})
        return

    name = st.text_input("Topic", "Artificial intelligence in public administration",
                         key="s_name")
    description = st.text_area(
        "Description", "Use, procurement, regulation and risks of AI systems and chatbots in "
        "public administration, schools and courts.", key="s_desc")
    terms = st.text_input("Own terms (optional, comma-separated)", "KI, IA, ChatGPT",
                          key="s_terms")
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

    if st.button("1 · Let Apertus write the search terms", disabled=not name.strip()):
        try:
            with st.spinner("Apertus turns the topic into search terms (DE/FR/IT/RM) …"):
                compiled = compile_topic(topic, get_settings(), prompt_version="compiler-core")
            st.session_state["s_compiled"] = compiled.model_dump(mode="json")
            st.session_state.pop("s_hits", None)
            for language in LANGUAGES:
                st.session_state[f"s_terms_{language}"] = "\n".join(
                    compiled.terms.get(language, [])
                )
        except Exception as error:
            st.error(f"Compilation failed: {error}")

    if "s_compiled" not in st.session_state:
        return
    compiled = CompiledTopic.model_validate(st.session_state["s_compiled"])
    st.caption(f"{compiled.model} · {compiled.input_tokens}/{compiled.output_tokens} Tokens · "
               f"{(compiled.latency_ms or 0) / 1000:.0f} s. Review and edit the terms – removing "
               "generic words such as «Verwaltung» improves the ranking:")
    columns = st.columns(len(LANGUAGES))
    for column, language in zip(columns, LANGUAGES, strict=True):
        edited = column.text_area(language.upper(), "\n".join(compiled.terms.get(language, [])),
                                  height=220, key=f"s_terms_{language}")
        compiled.terms[language] = [t.strip() for t in edited.splitlines() if t.strip()]

    where, when, how_many = st.columns([2, 1, 1])
    chosen = where.multiselect("Parliaments", list(PARLIAMENTS),
                               ["Federal (CHE)", "Bern", "Ticino"])
    since = when.date_input("Affairs from", datetime.date(2025, 1, 1),
                            format="DD.MM.YYYY").isoformat()
    limit = how_many.slider("Check at most this many candidates", 5, 40, 10)

    if st.button("2 · Search and check candidates", type="primary", disabled=not chosen):
        started = time.perf_counter()
        try:
            with st.spinner("Searching OpenParlData across the selected parliaments …"):
                pool = newest_matches(compiled, [PARLIAMENTS[c] for c in chosen])
        except Exception as error:
            st.error(f"Search failed: {error}")
            return
        ranked = [r for r in pool if r["score"] > 0 and (not r["date"] or r["date"] >= since)]
        candidates = [r["id"] for r in ranked][:limit]
        searched = time.perf_counter() - started
        st.write(f"**{len(pool)} newest search hits** in {searched:.1f} s, "
                 f"{len(ranked)} of them with specific topic terms in the title. Apertus checks "
                 f"the first {len(candidates)}.")

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

        progress = st.progress(0.0, text="Apertus is checking the candidates …")
        done = {}
        with ClassificationService(get_settings()) as service, ThreadPoolExecutor(8) as workers:
            futures = {workers.submit(check, c): c for c in candidates}
            for count, future in enumerate(as_completed(futures), 1):
                done[futures[future]] = future.result()
                fits = sum(1 for r in done.values() if r and r[1]["status"] == "assigned")
                progress.progress(count / len(candidates),
                                  text=f"{count}/{len(candidates)} checked · {fits} match")
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
    cols[0].metric("Checked", len(hits))
    cols[1].metric("✅ Match", counts["assigned"])
    cols[2].metric("⚠️ Uncertain", counts["uncertain"])
    cols[3].metric("⚪ Not related", counts["not_assigned"])
    cols[4].metric("Duration", f"{seconds:.0f} s")
    if counts["failed"]:
        st.warning(f"{counts['failed']} technical errors; these are not negative "
                   "decisions.")
        with st.expander("Technical errors"):
            st.json([r for _, r in hits if r["status"] == "failed"])
    st.download_button("Download search run (JSON)", json.dumps({
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(), "topic": topic,
        "terms": terms, "seconds": seconds, "matched": matched, "hits": hits,
    }, ensure_ascii=False, indent=1), file_name="search-results.json", mime="application/json")

    proposals = [(a, r) for a, r in hits if r["status"] in ("assigned", "uncertain")]
    if not proposals:
        return
    reviewer = st.text_input("Reviewer initials", key="s_reviewer",
                             placeholder="e.g. FW – then confirm or reject each hit")
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
            st.caption((f"Found via: {', '.join(found)} · " if found else "")
                       + f"OpenParlData ID {affair_id} · {ui.decision_path(result)}")
            links, ok, no = st.columns([2, 1, 1])
            url = affair.get("source_url") or next(
                (e.get("source_url") for e in result.get("evidence") or [] if e.get("source_url")),
                None)
            if url:
                links.link_button("Original source", url)
            key = f"{affair_id}:{result['topic_id']}"
            if key in reviewed:
                done = reviewed[key]
                verb = "confirmed" if done["review_decision"] == "confirmed" else "rejected"
                ok.success(f"{verb} ({done['reviewed_by']})")
                continue
            decision = None
            if ok.button("👍 Match", key=f"ok-{key}", disabled=not reviewer.strip(),
                         use_container_width=True):
                decision = "confirmed"
            if no.button("👎 No match", key=f"no-{key}", disabled=not reviewer.strip(),
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
        with st.expander(f"{len(rejected)} candidates not related to the topic"):
            for affair, result in rejected:
                st.markdown(f"- **{affair.get('title', '')[:110]}** – {result['explanation']}")
