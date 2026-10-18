from parltopic.models import TextSegment, TopicDefinition
from parltopic.retrieval.bm25 import retrieve


def test_retrieval_prefers_topic_terms() -> None:
    topic = TopicDefinition(
        topic_id="digitalisation",
        name="Digitalisierung",
        description="Digitale Verwaltung und elektronische Identität",
        synonyms=["E-ID"],
    )
    segments = [
        TextSegment(
            segment_id="road",
            affair_id="a",
            text="Sanierung einer Strasse",
            language="de",
            position=0,
        ),
        TextSegment(
            segment_id="eid",
            affair_id="a",
            text="Elektronische Identität für die digitale Verwaltung",
            language="de",
            position=1,
        ),
    ]
    ranked = retrieve(segments, topic, top_k=2)
    assert ranked[0][0].segment_id == "eid"
    assert ranked[0][1] > ranked[1][1]

