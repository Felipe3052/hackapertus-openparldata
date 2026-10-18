from parltopic.classification.apertus_client import ApertusResponse
from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.models import Affair, ClassificationStatus, Document, ModelDecision, TopicDefinition


class FailingClient:
    def classify(self, system_prompt: str, user_prompt: str) -> None:
        raise AssertionError("Apertus must not be called for a deterministic keyword hit")


def test_hybrid_policy_short_circuits_clear_keyword_hit() -> None:
    settings = Settings(
        llm_api_key="unused",
        keyword_rescue_enabled=True,
        classifier_prompt_version="topic-v1",
    )
    service = ClassificationService(settings, client=FailingClient())  # type: ignore[arg-type]
    topic = TopicDefinition(
        topic_id="digitalisation",
        name="Digitalisierung",
        description="Digital affairs",
        synonyms=["E-ID"],
    )

    result = service.classify(
        Affair(affair_id="a", title="Einführung einer kantonalen E-ID", language="de"),
        topic,
    )

    assert result.status == ClassificationStatus.ASSIGNED
    assert result.score == 1.0
    assert result.input_tokens == 0
    assert result.evidence[0].segment_id.startswith("a-title-")


def test_evidence_id_repair_requires_unique_matching_content_hash() -> None:
    selected = {
        "172231-affair-4ae5fb10b901": object(),
        "172231-title-cd7c45914743": object(),
    }

    assert ClassificationService._resolve_evidence_ids(
        ["1722231-affair-4ae5fb10b901"], selected
    ) == ["172231-affair-4ae5fb10b901"]


class RecordingClient:
    def __init__(self):
        self.user_prompt = None

    def classify(self, system_prompt, user_prompt):
        self.user_prompt = user_prompt
        return ApertusResponse(
            payload=ModelDecision(status="not_assigned", score=0,
                                  explanation="Incidental document mention", evidence_ids=[]),
            input_tokens=10, output_tokens=5, latency_ms=1,
        )


def test_document_keyword_requires_semantic_verification_and_title_is_pinned() -> None:
    client = RecordingClient()
    service = ClassificationService(
        Settings(_env_file=None, keyword_document_gate_enabled=False, retrieval_pin_title=True,
                 retrieval_top_k=2), client=client,
    )
    affair = Affair(
        affair_id="a", title="Road construction budget",
        documents=[Document(document_id="d", text="Digitalisierung in a footnote")],
    )
    topic = TopicDefinition(topic_id="digital", name="Digitalisierung", description="Digital")
    result = service.classify(affair, topic)
    assert result.status == ClassificationStatus.NOT_ASSIGNED
    assert client.user_prompt is not None
    assert "Road construction budget" in client.user_prompt
    assert "Digitalisierung in a footnote" in client.user_prompt
    assert client.user_prompt.index("Road construction budget") < client.user_prompt.index(
        "Digitalisierung in a footnote"
    )


def test_title_synonyms_do_not_trigger_on_body_mentions() -> None:
    topic = TopicDefinition(topic_id="digital", name="Digitalisierung", description="Digital",
                            title_synonyms=["fake news"])
    client = RecordingClient()
    service = ClassificationService(Settings(_env_file=None), client=client)
    assert service.classify(
        Affair(affair_id="a", title="CO2 emissions", text="A passing mention of fake news"), topic
    ).status == ClassificationStatus.NOT_ASSIGNED
    assert service.classify(
        Affair(affair_id="b", title="Fake news and media literacy"), topic
    ).status == ClassificationStatus.ASSIGNED


class PromptRecordingClient:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    def classify(self, system_prompt: str, user_prompt: str) -> ApertusResponse:
        self.system_prompts.append(system_prompt)
        return ApertusResponse(
            payload=ModelDecision(
                status=ClassificationStatus.NOT_ASSIGNED, score=0.0, explanation="No topic."
            ),
            input_tokens=10,
            output_tokens=5,
            latency_ms=1.0,
        )


def test_topic_policy_overrides_settings() -> None:
    from parltopic.classification.prompts import system_prompt

    settings = Settings(
        llm_api_key="unused", keyword_rescue_enabled=True, classifier_prompt_version="topic-v2"
    )
    client = PromptRecordingClient()
    service = ClassificationService(settings, client=client)  # type: ignore[arg-type]
    topic = TopicDefinition(
        topic_id="health",
        name="Gesundheit",
        description="Health affairs",
        synonyms=["Spital"],
        prompt_version="topic-v1",
        keyword_rule=False,
    )

    result = service.classify(
        Affair(affair_id="h", title="Parkplätze beim Spital", language="de"), topic
    )

    # The term occurs, but the topic disables the rule, so Apertus decides with prompt v1.
    assert result.status == ClassificationStatus.NOT_ASSIGNED
    assert result.prompt_version == "topic-v1"
    assert client.system_prompts == [system_prompt("topic-v1")]


def test_aps_context_is_opt_in_and_reports_reduction() -> None:
    client = RecordingClient()
    settings = Settings(
        _env_file=None,
        aps_context_enabled=True,
        aps_context_max_segments=2,
        keyword_rescue_enabled=False,
        retrieval_top_k=2,
    )
    service = ClassificationService(settings, client=client)
    affair = Affair(
        affair_id="aps",
        title="Verwaltung und Parlament",
        text="Verwaltung und Parlament. " * 300,
    )
    topic = TopicDefinition(topic_id="test", name="Verwaltung", description="Verwaltung")
    result = service.classify(affair, topic)
    assert result.context_policy == "aps-shadow-context"
    assert result.aps_taxonomy_version == "aps-2026-10-18"
    assert result.context_segments_before is not None
    assert result.context_segments_after == 2
    assert result.context_segments_after < result.context_segments_before
    assert result.context_tokens_approx_after < result.context_tokens_approx_before


def test_aps_context_falls_back_without_language_topic_candidates() -> None:
    settings = Settings(
        _env_file=None,
        aps_context_enabled=True,
        keyword_rescue_enabled=False,
        retrieval_top_k=1,
    )
    service = ClassificationService(settings, client=RecordingClient())
    prepared = service.prepare(
        Affair(affair_id="it", title="Amministrazione", language="it"),
        TopicDefinition(topic_id="test", name="Test", description="Test"),
    )
    assert prepared.context_policy == "aps-fallback:no_taxonomy_term_match"
    assert prepared.context_segments_before == prepared.context_segments_after
