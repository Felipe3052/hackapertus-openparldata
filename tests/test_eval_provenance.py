import json
from pathlib import Path

import pytest

from parltopic.config import Settings
from parltopic.evaluation.run import run_classifier, score_results
from parltopic.models import TopicDefinition


def test_resume_rejects_topic_changes_and_preserves_results(tmp_path: Path) -> None:
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(json.dumps({
        "affair_id": "1", "title": "Digitalisierung", "label": True,
        "language": "de", "level": "cantonal",
    }) + "\n", encoding="utf-8")
    output = tmp_path / "result.jsonl"
    topic = TopicDefinition(topic_id="digital", name="Digitalisierung", description="Digital")
    settings = Settings(_env_file=None, llm_api_key="secret-test-key")
    run_classifier(dataset, topic, output, settings)
    original = output.read_bytes()
    run_classifier(dataset, topic, output, settings)
    assert output.read_bytes() == original
    assert "secret-test-key" not in output.with_suffix(".jsonl.manifest.json").read_text()
    with pytest.raises(ValueError, match="Run inputs changed"):
        changed_topic = topic.model_copy(update={"description": "Changed"})
        run_classifier(dataset, changed_topic, output, settings)
    assert output.read_bytes() == original


def test_failed_results_are_excluded_from_both_selective_metrics(tmp_path: Path) -> None:
    dataset = tmp_path / "eval.jsonl"
    output = tmp_path / "result.jsonl"
    dataset.write_text(
        '\n'.join(json.dumps({"affair_id": str(i), "label": True, "language": "de",
                              "level": "federal"}) for i in range(2)), encoding="utf-8"
    )
    output.write_text(
        '\n'.join(json.dumps({"affair_id": str(i), "status": status})
                  for i, status in enumerate(["assigned", "failed"])), encoding="utf-8"
    )
    report = score_results(dataset, output)
    assert report["assigned"]["coverage"] == "1/2"
    assert report["assigned_or_uncertain"]["coverage"] == "1/2"
    assert report["result_integrity"]["coverage"] == 0.5
