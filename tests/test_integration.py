from parltopic.integration import affair_topic_rows, topic_version
from parltopic.models import ClassificationResult, ClassificationStatus, Evidence, TopicDefinition


def _result(status, evidence=True):
    return ClassificationResult(
        affair_id="42", topic_id="digitalisation", status=status, language="de", model="m",
        evidence=[Evidence(segment_id="42-title-x", text="eBau", document_id="7")] if evidence
        else [],
    )


def test_rows_keep_original_evidence_and_skip_failed_calls():
    rows = affair_topic_rows(
        [_result(ClassificationStatus.ASSIGNED), _result(ClassificationStatus.FAILED, False)], "v1"
    )
    assert len(rows) == 1
    assert rows[0]["affair_id"] == 42
    assert rows[0]["evidence_text"] == "eBau" and rows[0]["evidence_document_id"] == "7"


def test_topic_version_changes_with_the_definition():
    topic = TopicDefinition(topic_id="t", name="T", description="a")
    changed = topic.model_copy(update={"description": "b"})
    assert topic_version(topic) != topic_version(changed)
