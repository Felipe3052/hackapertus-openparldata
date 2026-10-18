import json

import pytest

from parltopic.integration import affair_topic_rows, export, topic_version
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


def test_export_verifies_topic_and_keeps_all_evidence(tmp_path):
    topic = TopicDefinition(topic_id="digitalisation", name="Digi", description="Definition")
    result = _result(ClassificationStatus.ASSIGNED)
    result.evidence.append(Evidence(segment_id="42-body-y", text="Second original passage"))
    source = tmp_path / "run.jsonl"
    source.write_text(result.model_dump_json() + "\n")
    source.with_suffix(".jsonl.manifest.json").write_text(json.dumps({
        "topic": topic.model_dump(mode="json"), "dataset_sha256": "source-snapshot",
    }))
    output = tmp_path / "export.jsonl"
    assert export(source, topic, output)["rows"] == 1
    row = json.loads(output.read_text())
    assert len(row["evidence"]) == 2
    assert row["prediction_id"] and row["run_id"] != "legacy-unverified"
    assert json.loads((tmp_path / "export.jsonl.run.json").read_text())["manifest_verified"]
    with pytest.raises(FileExistsError):
        export(source, topic, output)
    with pytest.raises(ValueError, match="differs"):
        export(source, topic.model_copy(update={"description": "changed"}), tmp_path / "bad")


def test_historical_export_requires_explicit_opt_in(tmp_path):
    topic = TopicDefinition(topic_id="digitalisation", name="Digi", description="Definition")
    source = tmp_path / "old.jsonl"
    source.write_text(_result(ClassificationStatus.NOT_ASSIGNED).model_dump_json() + "\n")
    with pytest.raises(ValueError, match="No run manifest"):
        export(source, topic, tmp_path / "output")
    output = tmp_path / "legacy"
    export(source, topic, output, allow_unverified=True)
    assert not json.loads((tmp_path / "legacy.run.json").read_text())["manifest_verified"]


def test_export_rejects_foreign_topic_even_for_legacy(tmp_path):
    source = tmp_path / "old.jsonl"
    source.write_text(_result(ClassificationStatus.NOT_ASSIGNED).model_dump_json() + "\n")
    topic = TopicDefinition(topic_id="health", name="Health", description="Definition")
    with pytest.raises(ValueError, match="topic IDs"):
        export(source, topic, tmp_path / "bad", allow_unverified=True)
