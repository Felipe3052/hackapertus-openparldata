from parltopic.classification.keyword import first_keyword_hit
from parltopic.models import TextSegment, TopicDefinition


def test_first_keyword_hit_is_multilingual_and_case_insensitive() -> None:
    topic = TopicDefinition(
        topic_id="digitalisation",
        name="Digitalisierung",
        description="Digital affairs",
        synonyms=["cybersécurité"],
    )
    segment = TextSegment(
        segment_id="a:title:0",
        affair_id="a",
        text="Renforcer la CYBERSÉCURITÉ cantonale",
        language="fr",
        position=0,
    )

    assert first_keyword_hit([segment], topic) == (segment, "cybersécurité")


def test_first_keyword_hit_does_not_infer_unlisted_concepts() -> None:
    topic = TopicDefinition(
        topic_id="digitalisation",
        name="Digitalisierung",
        description="Digital affairs",
    )
    segment = TextSegment(
        segment_id="a:title:0",
        affair_id="a",
        text="Sanierung der Kantonsstrasse",
        language="de",
        position=0,
    )

    assert first_keyword_hit([segment], topic) is None


def test_short_acronym_must_be_a_complete_token() -> None:
    topic = TopicDefinition(
        topic_id="digitalisation",
        name="Digitalisierung",
        description="Digital affairs",
        synonyms=["NFT"],
    )
    false_hit = TextSegment(
        segment_id="a:title:0",
        affair_id="a",
        text="Entwurf für ein neues Gesetz",
        language="de",
        position=0,
    )
    true_hit = false_hit.model_copy(update={"text": "NFT in der Kunstförderung"})

    assert first_keyword_hit([false_hit], topic) is None
    assert first_keyword_hit([true_hit], topic) == (true_hit, "NFT")
