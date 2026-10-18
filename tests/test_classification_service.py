from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.models import Affair, ClassificationStatus, TopicDefinition


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
