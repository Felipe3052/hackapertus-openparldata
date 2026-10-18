import json
from pathlib import Path

import streamlit as st

from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.models import Affair, TopicDefinition
from parltopic.topics import load_topic

ROOT = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="ParlTopic", page_icon="🏛️", layout="wide")
st.title("ParlTopic")
st.caption("Mehrsprachige Themenklassifikation für Schweizer Parlamentsdaten mit Apertus")

with st.sidebar:
    st.header("Thema")
    policy = st.selectbox("Konfiguration", ["Digitalisierung (validiert)", "Eigenes Thema"])
    topic_name = st.text_input("Name", "Digitalisierung",
                               disabled=policy.startswith("Digitalisierung"))
    topic_description = st.text_area(
        "Beschreibung",
        "Digitale Verwaltung, E-Government, elektronische Identität, "
        "Cloud, KI und Automatisierung.",
        disabled=policy.startswith("Digitalisierung"),
    )
    synonyms = st.text_input("Synonyme", "E-Government, digitale Verwaltung, E-ID",
                             disabled=policy.startswith("Digitalisierung"))
    if policy == "Eigenes Thema" and topic_name.strip() and topic_description.strip():
        import yaml

        st.download_button("Thema als YAML speichern", yaml.safe_dump({
            "topic_id": topic_name.casefold().strip().replace(" ", "-"),
            "name": topic_name, "description": topic_description,
            "synonyms": [word.strip() for word in synonyms.split(",") if word.strip()],
            "prompt_version": "topic-v1", "keyword_rule": False,
        }, allow_unicode=True), file_name="topic.yaml", mime="application/yaml")

source = st.radio("Eingabe", ["Echtes Geschäft", "OpenParlData-ID (live)", "Manuelle Eingabe"],
                  horizontal=True)
selected = None
if source == "OpenParlData-ID (live)":
    affair_key = st.text_input("Affair-ID aus OpenParlData", "303044",
                               help="z. B. 303044 (BE, eBau), 235308 (Bund), 329562 (TI)")
    if st.button("Von der OpenParlData-API laden") and affair_key.strip().isdigit():
        from parltopic.ingestion.live import fetch_affair

        with st.spinner("Geschäft, Texte und Dokumente werden geladen …"):
            st.session_state["live_affair"] = fetch_affair(int(affair_key)).model_dump(
                mode="json")
    selected = st.session_state.get("live_affair")
    if selected:
        st.caption(f"Live von api.openparldata.ch: {selected['parliament']}, "
                   f"{selected['level']}, {selected['date']}, "
                   f"{len(selected.get('documents') or [])} Dokument(e).")
if source == "Echtes Geschäft":
    rows = [json.loads(line) for line in
            (ROOT / "data/eval/e1_digitalisation_dev.jsonl")
            .read_text("utf-8").splitlines() if line]
    selected_language = st.selectbox("Beispielsprache", ["de", "fr", "it"])
    levels = sorted({row["level"] for row in rows if row["language"] == selected_language})
    selected_level = st.selectbox("Parlamentsebene", levels)
    examples = {row["affair_id"]: row for row in rows
                if row["language"] == selected_language and row["level"] == selected_level}
    identity = st.selectbox("Geschäft", list(examples),
                            format_func=lambda key: f"{key}: {examples[key]['title']}")
    selected = examples[identity]
    st.caption("Originaldaten aus dem geöffneten Dev-Split; keine neue Qualitätsmessung.")

title = st.text_input("Titel des parlamentarischen Geschäfts",
                      value=selected["title"] if selected else "")
text = st.text_area("Text", value=selected.get("text", "") if selected else "", height=260)
languages = ["de", "fr", "it", "rm"]
language = st.selectbox("Sprache", languages,
                        index=languages.index(selected["language"]) if selected else 0)

st.caption("Titel allein genügt. Modellaufrufe können API-Kosten verursachen; "
           "Keyword-Treffer benötigen keinen Modellaufruf.")

saved_path = ROOT / "results/hybrid_v3_actual_dev450.jsonl"
if selected and policy.startswith("Digitalisierung") and saved_path.exists():
    if st.button("Historisches Ergebnis anzeigen (ohne API)"):
        saved = {row["affair_id"]: row for row in
                 (json.loads(line) for line in saved_path.read_text("utf-8").splitlines() if line)}
        if selected["affair_id"] in saved:
            st.session_state["classification"] = saved[selected["affair_id"]]
            st.session_state["result_mode"] = (
                "Historischer Dev-Lauf mit damaliger Themenkonfiguration; "
                "bezieht sich auf den unveränderten Originaldatensatz."
            )
        else:
            st.warning("Kein gespeichertes Ergebnis für dieses Geschäft vorhanden.")

if st.button("Mit Apertus klassifizieren", type="primary", disabled=(
    not title.strip() or (policy == "Eigenes Thema"
                         and (not topic_name.strip() or not topic_description.strip()))
)):
    affair = Affair.model_validate({**(selected or {}), "affair_id":
                                   selected["affair_id"] if selected else "demo",
                                   "title": title, "text": text, "language": language})
    topic = load_topic(ROOT / "configs/topics/digitalisation.yaml") if policy.startswith(
        "Digitalisierung"
    ) else TopicDefinition(
        topic_id=topic_name.casefold().replace(" ", "-"),
        name=topic_name,
        description=topic_description,
        synonyms=[item.strip() for item in synonyms.split(",") if item.strip()],
        prompt_version="topic-v1",
        keyword_rule=False,
    )
    with st.spinner("Apertus analysiert relevante Passagen …"):
        with ClassificationService(get_settings()) as service:
            result = service.classify(affair, topic)
    st.session_state["classification"] = result.model_dump(mode="json")
    st.session_state["result_mode"] = "Neuer Lauf mit aktueller Konfiguration."

if "classification" in st.session_state:
    from parltopic.models import ClassificationResult

    result = ClassificationResult.model_validate(st.session_state["classification"])
    st.info(st.session_state["result_mode"])
    st.caption(f"Ergebnis für Geschäft {result.affair_id}, Thema {result.topic_id}.")
    if result.error:
        st.error(result.error)
    else:
        st.subheader(result.status.value.replace("_", " ").title())
        st.write(result.explanation)
        if result.score is not None:
            st.metric("Entscheidungswert (nicht kalibriert)", f"{result.score:.2f}")
        for evidence in result.evidence:
            st.info(evidence.text)
            if evidence.source_url:
                st.link_button("Originalquelle", str(evidence.source_url))
    st.caption(f"{result.model} · {result.prompt_version} · "
               f"Input/Output-Tokens: {result.input_tokens}/{result.output_tokens} · "
               f"Client-Latenz: {result.latency_ms} ms")
    st.download_button("Strukturiertes Ergebnis (JSON)", result.model_dump_json(indent=2),
                       file_name=f"{result.affair_id}-{result.topic_id}.json",
                       mime="application/json")
    with st.expander("Vollständiges Integrationsergebnis"):
        st.json(result.model_dump(mode="json"))
    st.caption("Die Klassifikation bewertet nur Themenzugehörigkeit und keine politische Position.")

    st.subheader("Prüfung durch eine Person")
    reviews = ROOT / "results/reviews.jsonl"
    reviewer = st.text_input("Kürzel der prüfenden Person", key="reviewer")
    left, right = st.columns(2)
    decision = None
    if left.button("Vorschlag bestätigen", disabled=not reviewer.strip()):
        decision = "confirmed"
    if right.button("Vorschlag ablehnen", disabled=not reviewer.strip()):
        decision = "rejected"
    if decision:
        from datetime import UTC, datetime

        reviews.parent.mkdir(parents=True, exist_ok=True)
        entry = {"affair_id": result.affair_id, "topic_id": result.topic_id,
                 "suggested_status": result.status.value, "review_decision": decision,
                 "reviewed_by": reviewer.strip(), "reviewed_at": datetime.now(UTC).isoformat()}
        with reviews.open("a", encoding="utf-8") as file:  # appended, the suggestion is kept
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        st.success(f"Gespeichert: {decision} durch {reviewer.strip()} ({reviews.name}). "
                   "Für OpenParlData: Spalten review_decision/reviewed_by in affair_topics.")

