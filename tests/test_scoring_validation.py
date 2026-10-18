import json

import pytest

from parltopic.evaluation.audit import legacy_validation_probes
from parltopic.evaluation.compare import compare_runs
from parltopic.evaluation.run import score_results


def write(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


@pytest.mark.parametrize("problem", ["label", "duplicate", "status", "foreign"])
def test_standard_scorer_rejects_ambiguous_inputs(tmp_path, problem):
    gold = [{"affair_id": "1", "label": True, "language": "de", "level": "federal"}]
    predictions = [{"affair_id": "1", "status": "assigned"}]
    if problem == "label":
        gold[0]["label"] = "false"
    elif problem == "duplicate":
        gold *= 2
    elif problem == "status":
        predictions[0]["status"] = "unknown"
    else:
        predictions[0]["affair_id"] = "foreign"
    dataset, results = tmp_path / "gold", tmp_path / "results"
    write(dataset, gold)
    write(results, predictions)
    with pytest.raises(ValueError):
        score_results(dataset, results)


def test_comparison_reports_lost_decisions_despite_perfect_intersection(tmp_path):
    gold = [{"affair_id": str(i), "label": bool(i % 2)} for i in range(4)]
    base = [{"affair_id": str(i), "status": "assigned" if i % 2 else "not_assigned"}
            for i in range(4)]
    candidate = [{**row, "status": "failed"} if i == 0 else row
                 for i, row in enumerate(base)]
    paths = [tmp_path / name for name in ("gold", "base", "candidate")]
    for path, rows in zip(paths, (gold, base, candidate), strict=True):
        write(path, rows)
    report = compare_runs(*paths, samples=10)
    assert report["macro_f1_delta"] == 0
    assert report["coverage"]["lost_baseline_decisions"] == 1
    assert report["coverage_non_regression"] is False


def test_historical_audit_probes_now_report_rejections():
    report = legacy_validation_probes()
    assert report["unknown_status_accepted_by_validator"] is False
    for key in ("null_label_treated_as_negative", "string_false_treated_as_positive",
                "duplicate_gold_counted_twice", "foreign_prediction_silently_ignored"):
        assert report[key]["rejected"]
