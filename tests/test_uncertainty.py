import json
from pathlib import Path

import pytest

from parltopic.evaluation.uncertainty import bootstrap_metrics


def test_perfect_classifier_intervals_and_missing_coverage(tmp_path: Path):
    dataset = tmp_path / "eval.jsonl"
    results = tmp_path / "results.jsonl"
    dataset.write_text("\n".join(json.dumps({"affair_id": str(i), "label": label})
                                 for i, label in enumerate([True, False, True])))
    results.write_text("\n".join(json.dumps({"affair_id": str(i), "status": status})
                                 for i, status in enumerate(["assigned", "not_assigned"])))
    first = bootstrap_metrics(dataset, results, samples=100)
    assert first == bootstrap_metrics(dataset, results, samples=100)
    assert first["coverage"] == {"decisive": 2, "total": 3}
    assert first["metrics"]["macro_f1"] == {"estimate": 1.0, "interval_95": [1.0, 1.0]}


def test_bootstrap_requires_both_classes(tmp_path: Path):
    dataset = tmp_path / "eval.jsonl"
    results = tmp_path / "results.jsonl"
    dataset.write_text('{"affair_id":"1","label":true}')
    results.write_text('{"affair_id":"1","status":"assigned"}')
    with pytest.raises(ValueError, match="Both classes"):
        bootstrap_metrics(dataset, results)
