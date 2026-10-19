import json
import sys
from pathlib import Path

import streamlit as st

from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.integration import content_id, record_review, topic_version
from parltopic.models import Affair, TopicDefinition
from parltopic.topics import load_topic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import ui  # noqa: E402

CURATED_TOPIC = load_topic(ROOT / "configs/topics/digitalisation.yaml")

st.set_page_config(page_title="ParlTopic", page_icon="🏛️", layout="wide")
ui.style()
st.title("🏛️ ParlTopic")
st.caption("Which affairs of Swiss parliaments concern a topic? Apertus reads them in German, "
           "French and Italian, quotes the evidence, and a person decides.")
ui.headline()

mode = st.radio("Mode", ["Single affair", "Search a topic across parliaments"],
                horizontal=True)

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Describe a **topic** in one sentence – no training\n"
        "2. **Apertus 70B** (open, on CSCS) reads the most relevant passages\n"
        "3. **Evidence** quoted from the original text, linked to the source\n"
        "4. A **person** confirms or corrects; nothing is overwritten\n"
        "5. **Export** as table `affair_topics` for OpenParlData"
    )
    st.caption("Every number above can be recomputed from the release with `parltopic claims`.")

if mode == "Search a topic across parliaments":
    from search_page import render

    render()
    st.stop()

with st.sidebar:
    st.divider()
    st.header("Topic")
    policy = st.selectbox("Configuration", ["Digitalisation (validated)", "Custom topic"])
    curated = policy.startswith("Digitalisation")
    # An own topic starts from a ready example, never from the curated topic's synonyms.
    topic_name = st.text_input("Name", "Digitalisierung" if curated else "Transport",
                               disabled=curated)
    topic_description = st.text_area(
        "Description", CURATED_TOPIC.description if curated else
        "Roads, public transport, cycling, rail and mobility.", disabled=curated)
    synonyms = st.text_input("Synonyms", ", ".join(CURATED_TOPIC.synonyms) if curated else
                             "Verkehr, Velo, ÖV, Bahn, transports publics, trasporti",
                             disabled=curated)
    if curated:
        st.caption("Validated on 1,200 test affairs 2024–26 (F1 0.876). The validated "
                   "definition is kept in its original German.")
    elif topic_name.strip() and topic_description.strip():
        import yaml

        st.download_button("Save topic as YAML", yaml.safe_dump({
            "topic_id": topic_name.casefold().strip().replace(" ", "-"),
            "name": topic_name, "description": topic_description,
            "synonyms": [word.strip() for word in synonyms.split(",") if word.strip()],
            "prompt_version": "topic-v1", "keyword_rule": False,
        }, allow_unicode=True), file_name="topic.yaml", mime="application/yaml")

left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("1 · Affair")
    source = st.radio("Input", ["Real affair", "OpenParlData ID (live)", "Manual input"],
                      horizontal=True)
    selected = None
    if source == "OpenParlData ID (live)":
        affair_key = st.text_input("Affair ID in OpenParlData", "303044",
                                   help="e.g. 303044 (BE, eBau), 235308 (federal), 329562 (TI)")
        if st.button("Load from the OpenParlData API"):
            if not affair_key.strip().isdigit():
                st.error("Please enter a numeric OpenParlData ID.")
            else:
                from parltopic.ingestion.live import fetch_affair

                try:
                    with st.spinner("Loading affair, texts and documents …"):
                        st.session_state["live_affair"] = fetch_affair(
                            int(affair_key)).model_dump(mode="json")
                except Exception as error:
                    st.error(f"Live fetch failed: {error}. "
                             "The bundled original examples remain available.")
        selected = st.session_state.get("live_affair")
        if selected:
            st.caption(f"Live from api.openparldata.ch: {selected['parliament']}, "
                       f"{selected['level']}, {selected['date']}, "
                       f"{len(selected.get('documents') or [])} document(s).")
    if source == "Real affair":
        rows = [json.loads(line) for line in
                (ROOT / "data/demo/jury/affairs.jsonl")
                .read_text("utf-8").splitlines() if line]
        names = {"de": "German", "fr": "French", "it": "Italian"}
        levels_en = {"federal": "Federal", "cantonal": "Cantonal"}
        pick_language, pick_level = st.columns(2)
        selected_language = pick_language.selectbox("Example language", ["de", "fr", "it"],
                                                    index=1, format_func=names.get)
        levels = sorted({row["level"] for row in rows if row["language"] == selected_language})
        selected_level = pick_level.selectbox("Parliament level", levels,
                                              format_func=lambda v: levels_en.get(v, v))
        examples = {row["affair_id"]: row for row in rows
                    if row["language"] == selected_language and row["level"] == selected_level}
        identity = st.selectbox("Affair", list(examples),
                                format_func=lambda key: f"{examples[key]['parliament']} · "
                                f"{examples[key]['date']} · {examples[key]['title']}")
        selected = examples[identity]
        st.caption("Six bundled original examples from the opened dev split, "
                   "DE/FR/IT × federal/cantonal. Not a new quality measurement.")

    title = st.text_input("Title of the parliamentary affair",
                          value=selected["title"] if selected else "")
    text = st.text_area("Text (optional – the title alone is enough)",
                        value=selected.get("text", "") if selected else "", height=120)
    languages = ["de", "fr", "it", "rm"]
    language = st.selectbox("Language", languages,
                            index=languages.index(selected["language"]) if selected else 0)
    if selected and selected.get("source_url"):
        st.link_button("Open affair in the original portal", str(selected["source_url"]))

    # One key per affair and topic: a result is shown only for the input it belongs to.
    current = content_id({"affair_id": selected["affair_id"] if selected else "demo",
                          "title": title, "text": text, "language": language,
                          "topic": [policy, topic_name, topic_description, synonyms]})

    st.subheader("2 · Classify")
    saved_path = ROOT / "data/demo/jury/predictions.jsonl"
    historical = bool(selected and curated and saved_path.exists())
    run_col, replay_col = st.columns(2)
    run = run_col.button("Classify with Apertus", type="primary", use_container_width=True,
                         disabled=not title.strip() or (not curated and (
                             not topic_name.strip() or not topic_description.strip())))
    replay = historical and replay_col.button("Historical result (no API)",
                                              use_container_width=True)
    st.caption("A model call usually takes 3–10 s. Keyword-rule hits need no model call. "
               "The historical result works offline.")

if replay:
    saved = {row["affair_id"]: row for row in
             (json.loads(line) for line in saved_path.read_text("utf-8").splitlines() if line)}
    if selected["affair_id"] in saved:
        st.session_state["classification"] = saved[selected["affair_id"]]
        st.session_state["classification_key"] = current
        st.session_state["classification_context"] = {
            "source_sha256": content_id(Affair.model_validate(selected).model_dump(mode="json")),
            "topic_version": None,
            "historical_snapshot": "data/demo/jury/manifest.json",
            "historical_snapshot_id": content_id(json.loads(
                (ROOT / "data/demo/jury/manifest.json").read_text("utf-8")
            )),
        }
        st.session_state["result_mode"] = (
            "Historical dev run with the topic configuration of that time; "
            "refers to the unchanged original record."
        )
        st.session_state.pop("last_review", None)
    else:
        left.warning("No saved result for this affair.")

if run:
    affair = Affair.model_validate({**(selected or {}), "affair_id":
                                   selected["affair_id"] if selected else "demo",
                                   "title": title, "text": text, "language": language})
    topic = CURATED_TOPIC if curated else TopicDefinition(
        topic_id=topic_name.casefold().replace(" ", "-"),
        name=topic_name,
        description=topic_description,
        synonyms=[item.strip() for item in synonyms.split(",") if item.strip()],
        prompt_version="topic-v1",
        keyword_rule=False,
    )
    with right, st.spinner("Apertus is reading the most relevant passages …"):
        with ClassificationService(get_settings()) as service:
            result = service.classify(affair, topic)
    st.session_state["classification"] = result.model_dump(mode="json")
    st.session_state["classification_key"] = current
    st.session_state["classification_context"] = {
        "source_sha256": content_id(affair.model_dump(mode="json")),
        "topic_version": topic_version(topic),
        "topic_definition": topic.model_dump(mode="json"),
    }
    st.session_state["result_mode"] = "New run with the current configuration."
    st.session_state.pop("last_review", None)

with right:
    st.subheader("3 · Result")
    fresh = st.session_state.get("classification_key") == current
    if "classification" not in st.session_state or not fresh:
        st.info("No result for this affair yet. Choose *Classify with Apertus* or "
                "*Historical result* on the left.")
        st.stop()

    from parltopic.models import ClassificationResult

    result = ClassificationResult.model_validate(st.session_state["classification"])
    raw = result.model_dump(mode="json")
    if result.error:
        ui.status_card("failed", "Technical state, not a topic decision.")
        st.error(result.error)
    else:
        detail = (f"Decision score {result.score:.2f} (not calibrated)"
                  if result.score and result.status.value != "not_assigned" else "")
        ui.status_card(result.status.value, detail)
        st.markdown(f"**Apertus' reasoning:** {result.explanation}")
        definition = (st.session_state.get("classification_context") or {}).get(
            "topic_definition") or CURATED_TOPIC.model_dump(mode="json")
        terms = [*definition.get("synonyms", []), definition.get("name", "")]
        if result.evidence:
            st.markdown("**Evidence in the original text**")
        for evidence in result.evidence:
            origin = "title" if "-title-" in evidence.segment_id else (
                f"document {evidence.document_id}" if evidence.document_id else "affair text")
            ui.quote(evidence.text, terms, f"Source: {origin}")
            if evidence.source_url:
                st.link_button("Original source", str(evidence.source_url))
        st.caption(ui.decision_path(raw))
    st.caption(f"{st.session_state['result_mode']} Affair {result.affair_id}, "
               f"topic {result.topic_id}. Only topic membership is assessed, "
               "never a political position.")
    with st.expander("Technical details and export"):
        st.caption(f"{result.model} · {result.prompt_version} · {result.classifier_version} · "
                   f"Input/output tokens: {result.input_tokens}/{result.output_tokens} · "
                   f"Client latency: {result.latency_ms} ms")
        st.download_button("Structured result (JSON)", result.model_dump_json(indent=2),
                           file_name=f"{result.affair_id}-{result.topic_id}.json",
                           mime="application/json")
        st.json(raw, expanded=False)

    st.subheader("4 · Human review")
    with st.container(border=True):
        reviews = ROOT / "results/reviews.jsonl"
        reviewer = st.text_input("Reviewer initials", key="reviewer", placeholder="e.g. FW")
        review_note = st.text_input("Reason or correction (optional)", key="review_note")
        corrected_status = st.selectbox(
            "Corrected status if rejected (optional)",
            [None, "assigned", "not_assigned", "uncertain"],
            format_func=lambda value: ui.STATUS_EN[value] if value else "No correction")
        confirm_col, reject_col = st.columns(2)
        decision = None
        if confirm_col.button("Confirm suggestion", disabled=not reviewer.strip(),
                              use_container_width=True):
            decision = "confirmed"
        if reject_col.button("Reject suggestion", disabled=not reviewer.strip(),
                             use_container_width=True):
            decision = "rejected"
        if not reviewer.strip():
            st.caption("Enter your initials to confirm or reject.")
        if decision:
            from datetime import UTC, datetime

            reviews.parent.mkdir(parents=True, exist_ok=True)
            entry = {"affair_id": result.affair_id, "topic_id": result.topic_id,
                     "suggested_status": result.status.value, "review_decision": decision,
                     "reviewed_by": reviewer.strip(),
                     "reviewed_at": datetime.now(UTC).isoformat(),
                     "prediction_id": content_id(raw), "prediction": raw,
                     "context": st.session_state.get("classification_context"),
                     "review_note": review_note.strip() or None,
                     "corrected_status": corrected_status if decision == "rejected" else None}
            st.session_state["last_review"] = record_review(entry, reviews)
        if "last_review" in st.session_state:
            last = st.session_state["last_review"]
            verb = "confirmed" if last["review_decision"] == "confirmed" else "rejected"
            st.success(f"Suggestion {verb} by {last['reviewed_by']} and saved "
                       f"({reviews.name}). The original suggestion is kept; in OpenParlData "
                       "both end up in the table affair_topics.")
            st.download_button("Download review (JSON)", json.dumps(
                last, ensure_ascii=False, indent=2,
            ), file_name="review.json", mime="application/json")
