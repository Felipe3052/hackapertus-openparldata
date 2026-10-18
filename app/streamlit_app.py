import streamlit as st

from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.models import Affair, TopicDefinition

st.set_page_config(page_title="ParlTopic", page_icon="🏛️", layout="wide")
st.title("ParlTopic")
st.caption("Mehrsprachige Themenklassifikation für Schweizer Parlamentsdaten mit Apertus")

with st.sidebar:
    st.header("Thema")
    topic_name = st.text_input("Name", "Digitalisierung")
    topic_description = st.text_area(
        "Beschreibung",
        "Digitale Verwaltung, E-Government, elektronische Identität, "
        "Cloud, KI und Automatisierung.",
    )
    synonyms = st.text_input("Synonyme", "E-Government, digitale Verwaltung, E-ID")

title = st.text_input("Titel des parlamentarischen Geschäfts")
text = st.text_area("Text", height=260)
language = st.selectbox("Sprache", ["de", "fr", "it", "rm"])

if st.button("Mit Apertus klassifizieren", type="primary", disabled=not title or not text):
    affair = Affair(affair_id="demo", title=title, text=text, language=language)
    topic = TopicDefinition(
        topic_id=topic_name.casefold().replace(" ", "-"),
        name=topic_name,
        description=topic_description,
        synonyms=[item.strip() for item in synonyms.split(",") if item.strip()],
    )
    with st.spinner("Apertus analysiert relevante Passagen …"):
        result = ClassificationService(get_settings()).classify(affair, topic)
    if result.error:
        st.error(result.error)
    else:
        st.subheader(result.status.value.replace("_", " ").title())
        st.write(result.explanation)
        if result.score is not None:
            st.metric("Modellbewertung", f"{result.score:.2f}")
        for evidence in result.evidence:
            st.info(evidence.text)
    st.caption("Die Klassifikation bewertet nur Themenzugehörigkeit und keine politische Position.")

