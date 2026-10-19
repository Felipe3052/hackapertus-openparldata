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
st.caption("Welche Geschäfte der Schweizer Parlamente betreffen ein Thema? Apertus liest sie "
           "auf Deutsch, Französisch und Italienisch, zeigt die Belegstelle, und ein Mensch "
           "entscheidet.")
ui.headline()

mode = st.radio("Modus", ["Einzelnes Geschäft", "Thema über Parlamente suchen"], horizontal=True)

with st.sidebar:
    st.header("So funktioniert's")
    st.markdown(
        "1. **Thema** in einem Satz beschreiben – kein Training\n"
        "2. **Apertus 70B** (offen, auf CSCS) liest die relevantesten Passagen\n"
        "3. **Belegstelle** im Originaltext, mit Link zur Quelle\n"
        "4. **Mensch** bestätigt oder korrigiert; nichts wird überschrieben\n"
        "5. **Export** als Tabelle `affair_topics` für OpenParlData"
    )
    st.caption("Alle Zahlen oben sind mit `parltopic claims` aus dem Release nachrechenbar.")

if mode == "Thema über Parlamente suchen":
    from search_page import render

    render()
    st.stop()

with st.sidebar:
    st.divider()
    st.header("Thema")
    policy = st.selectbox("Konfiguration", ["Digitalisierung (validiert)", "Eigenes Thema"])
    curated = policy.startswith("Digitalisierung")
    # An own topic starts from a ready example, never from the curated topic's synonyms.
    topic_name = st.text_input("Name", "Digitalisierung" if curated else "Verkehr",
                               disabled=curated)
    topic_description = st.text_area(
        "Beschreibung", CURATED_TOPIC.description if curated else
        "Strassen, öffentlicher Verkehr, Velo, Bahn und Mobilität.", disabled=curated)
    synonyms = st.text_input("Synonyme", ", ".join(CURATED_TOPIC.synonyms) if curated else
                             "Velo, ÖV, Bahn, Strasse", disabled=curated)
    if curated:
        st.caption("Validiert auf 1'200 Testgeschäften 2024–26 (F1 0,876).")
    elif topic_name.strip() and topic_description.strip():
        import yaml

        st.download_button("Thema als YAML speichern", yaml.safe_dump({
            "topic_id": topic_name.casefold().strip().replace(" ", "-"),
            "name": topic_name, "description": topic_description,
            "synonyms": [word.strip() for word in synonyms.split(",") if word.strip()],
            "prompt_version": "topic-v1", "keyword_rule": False,
        }, allow_unicode=True), file_name="topic.yaml", mime="application/yaml")

left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("1 · Geschäft")
    source = st.radio("Eingabe", ["Echtes Geschäft", "OpenParlData-ID (live)", "Manuelle Eingabe"],
                      horizontal=True)
    selected = None
    if source == "OpenParlData-ID (live)":
        affair_key = st.text_input("Affair-ID aus OpenParlData", "303044",
                                   help="z. B. 303044 (BE, eBau), 235308 (Bund), 329562 (TI)")
        if st.button("Von der OpenParlData-API laden"):
            if not affair_key.strip().isdigit():
                st.error("Bitte eine numerische OpenParlData-ID eingeben.")
            else:
                from parltopic.ingestion.live import fetch_affair

                try:
                    with st.spinner("Geschäft, Texte und Dokumente werden geladen …"):
                        st.session_state["live_affair"] = fetch_affair(
                            int(affair_key)).model_dump(mode="json")
                except Exception as error:
                    st.error(f"Live-Abruf fehlgeschlagen: {error}. "
                             "Die mitgelieferten Originalbeispiele bleiben verfügbar.")
        selected = st.session_state.get("live_affair")
        if selected:
            st.caption(f"Live von api.openparldata.ch: {selected['parliament']}, "
                       f"{selected['level']}, {selected['date']}, "
                       f"{len(selected.get('documents') or [])} Dokument(e).")
    if source == "Echtes Geschäft":
        rows = [json.loads(line) for line in
                (ROOT / "data/demo/jury/affairs.jsonl")
                .read_text("utf-8").splitlines() if line]
        names = {"de": "Deutsch", "fr": "Französisch", "it": "Italienisch"}
        levels_de = {"federal": "Bund", "cantonal": "Kanton"}
        pick_language, pick_level = st.columns(2)
        selected_language = pick_language.selectbox("Beispielsprache", ["de", "fr", "it"],
                                                    index=1, format_func=names.get)
        levels = sorted({row["level"] for row in rows if row["language"] == selected_language})
        selected_level = pick_level.selectbox("Parlamentsebene", levels,
                                              format_func=lambda v: levels_de.get(v, v))
        examples = {row["affair_id"]: row for row in rows
                    if row["language"] == selected_language and row["level"] == selected_level}
        identity = st.selectbox("Geschäft", list(examples),
                                format_func=lambda key: f"{examples[key]['parliament']} · "
                                f"{examples[key]['date']} · {examples[key]['title']}")
        selected = examples[identity]
        st.caption("Sechs mitgelieferte Originalbeispiele aus dem geöffneten Dev-Split, "
                   "DE/FR/IT × Bund/Kanton. Keine neue Qualitätsmessung.")

    title = st.text_input("Titel des parlamentarischen Geschäfts",
                          value=selected["title"] if selected else "")
    text = st.text_area("Text (optional – der Titel allein genügt)",
                        value=selected.get("text", "") if selected else "", height=120)
    languages = ["de", "fr", "it", "rm"]
    language = st.selectbox("Sprache", languages,
                            index=languages.index(selected["language"]) if selected else 0)
    if selected and selected.get("source_url"):
        st.link_button("Geschäft im Originalportal öffnen", str(selected["source_url"]))

    # One key per affair and topic: a result is shown only for the input it belongs to.
    current = content_id({"affair_id": selected["affair_id"] if selected else "demo",
                          "title": title, "text": text, "language": language,
                          "topic": [policy, topic_name, topic_description, synonyms]})

    st.subheader("2 · Klassifizieren")
    saved_path = ROOT / "data/demo/jury/predictions.jsonl"
    historical = bool(selected and curated and saved_path.exists())
    run_col, replay_col = st.columns(2)
    run = run_col.button("Mit Apertus klassifizieren", type="primary", use_container_width=True,
                         disabled=not title.strip() or (not curated and (
                             not topic_name.strip() or not topic_description.strip())))
    replay = historical and replay_col.button("Historisches Ergebnis (ohne API)",
                                              use_container_width=True)
    st.caption("Ein Modellaufruf dauert meist 3–10 s. Treffer der Stichwort-Regel brauchen "
               "keinen Modellaufruf. Das historische Ergebnis funktioniert ohne Netz.")

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
            "Historischer Dev-Lauf mit damaliger Themenkonfiguration; "
            "bezieht sich auf den unveränderten Originaldatensatz."
        )
        st.session_state.pop("last_review", None)
    else:
        left.warning("Kein gespeichertes Ergebnis für dieses Geschäft vorhanden.")

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
    with right, st.spinner("Apertus liest die relevantesten Passagen …"):
        with ClassificationService(get_settings()) as service:
            result = service.classify(affair, topic)
    st.session_state["classification"] = result.model_dump(mode="json")
    st.session_state["classification_key"] = current
    st.session_state["classification_context"] = {
        "source_sha256": content_id(affair.model_dump(mode="json")),
        "topic_version": topic_version(topic),
        "topic_definition": topic.model_dump(mode="json"),
    }
    st.session_state["result_mode"] = "Neuer Lauf mit aktueller Konfiguration."
    st.session_state.pop("last_review", None)

with right:
    st.subheader("3 · Ergebnis")
    fresh = st.session_state.get("classification_key") == current
    if "classification" not in st.session_state or not fresh:
        st.info("Noch kein Ergebnis für dieses Geschäft. Links *Mit Apertus klassifizieren* "
                "oder *Historisches Ergebnis* wählen.")
        st.stop()

    from parltopic.models import ClassificationResult

    result = ClassificationResult.model_validate(st.session_state["classification"])
    raw = result.model_dump(mode="json")
    if result.error:
        ui.status_card("failed", "Technischer Zustand, keine Themenentscheidung.")
        st.error(result.error)
    else:
        detail = (f"Entscheidungswert {result.score:.2f} (nicht kalibriert)".replace(".", ",")
                  if result.score and result.status.value != "not_assigned" else "")
        ui.status_card(result.status.value, detail)
        st.markdown(f"**Begründung von Apertus:** {result.explanation}")
        definition = (st.session_state.get("classification_context") or {}).get(
            "topic_definition") or CURATED_TOPIC.model_dump(mode="json")
        terms = [*definition.get("synonyms", []), definition.get("name", "")]
        if result.evidence:
            st.markdown("**Belegstelle im Originaltext**")
        for evidence in result.evidence:
            origin = "Titel" if "-title-" in evidence.segment_id else (
                f"Dokument {evidence.document_id}" if evidence.document_id else "Geschäftstext")
            ui.quote(evidence.text, terms, f"Quelle: {origin}")
            if evidence.source_url:
                st.link_button("Originalquelle", str(evidence.source_url))
        st.caption(ui.decision_path(raw))
    st.caption(f"{st.session_state['result_mode']} Geschäft {result.affair_id}, "
               f"Thema {result.topic_id}. Bewertet wird nur die Themenzugehörigkeit, "
               "keine politische Position.")
    with st.expander("Technische Details und Export"):
        st.caption(f"{result.model} · {result.prompt_version} · {result.classifier_version} · "
                   f"Input/Output-Tokens: {result.input_tokens}/{result.output_tokens} · "
                   f"Client-Latenz: {result.latency_ms} ms")
        st.download_button("Strukturiertes Ergebnis (JSON)", result.model_dump_json(indent=2),
                           file_name=f"{result.affair_id}-{result.topic_id}.json",
                           mime="application/json")
        st.json(raw, expanded=False)

    st.subheader("4 · Prüfung durch eine Person")
    with st.container(border=True):
        reviews = ROOT / "results/reviews.jsonl"
        reviewer = st.text_input("Kürzel der prüfenden Person", key="reviewer",
                                 placeholder="z. B. FW")
        review_note = st.text_input("Begründung oder Korrektur (optional)", key="review_note")
        corrected_status = st.selectbox(
            "Korrigierter Status bei Ablehnung (optional)",
            [None, "assigned", "not_assigned", "uncertain"],
            format_func=lambda value: ui.STATUS_DE[value] if value else "Keine Korrektur")
        confirm_col, reject_col = st.columns(2)
        decision = None
        if confirm_col.button("Vorschlag bestätigen", disabled=not reviewer.strip(),
                              use_container_width=True):
            decision = "confirmed"
        if reject_col.button("Vorschlag ablehnen", disabled=not reviewer.strip(),
                             use_container_width=True):
            decision = "rejected"
        if not reviewer.strip():
            st.caption("Kürzel eintragen, um zu bestätigen oder abzulehnen.")
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
            verb = "bestätigt" if last["review_decision"] == "confirmed" else "abgelehnt"
            st.success(f"Vorschlag {verb} durch {last['reviewed_by']} und gespeichert "
                       f"({reviews.name}). Der ursprüngliche Vorschlag bleibt erhalten; in "
                       "OpenParlData landen beide in der Tabelle affair_topics.")
            st.download_button("Prüfung als JSON sichern", json.dumps(
                last, ensure_ascii=False, indent=2,
            ), file_name="review.json", mime="application/json")
