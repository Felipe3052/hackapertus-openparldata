from fractions import Fraction

import pytest

from parltopic.evaluation.audit import audit_predictions, independent_metrics, normalize
from parltopic.evaluation.metrics import binary_metrics


def pairs_30():
    return [(True, True)] * 8 + [(True, False)] * 2 + [(False, False)] * 20


def test_known_30_case_confusion_and_all_averages():
    independent = independent_metrics(pairs_30())
    expected, predicted = zip(*pairs_30(), strict=True)
    current = binary_metrics(list(expected), list(predicted))
    assert (independent["tp"], independent["fp"], independent["fn"], independent["tn"]) == (
        8, 0, 2, 20
    )
    assert independent["matrix_actual_by_predicted_false_true"] == [[20, 0], [2, 8]]
    report = independent["classification_report"]
    assert report["positive"]["precision"] == current.precision == 1
    assert report["positive"]["recall"] == current.recall == .8
    assert report["positive"]["f1"] == pytest.approx(Fraction(8, 9))
    assert report["negative"]["f1"] == pytest.approx(Fraction(20, 21))
    assert report["macro"]["f1"] == pytest.approx(Fraction(58, 63))
    assert current.macro_f1 == pytest.approx(Fraction(58, 63))
    assert report["micro"]["f1"] == pytest.approx(Fraction(14, 15))
    assert report["weighted"]["f1"] == pytest.approx(Fraction(176, 189))
    assert report["macro"]["f1"] != report["positive"]["f1"]


def test_false_positives_and_false_negatives_both_count():
    result = independent_metrics([(True, True), (True, False), (False, True), (False, False)])
    assert [result[k] for k in ("tp", "fp", "fn", "tn")] == [1, 1, 1, 1]
    assert result["classification_report"]["macro"]["f1"] == .5


def test_fixed_two_class_zero_division_convention_is_explicit():
    result = independent_metrics([(True, True), (True, True)])
    assert result["classification_report"]["positive"]["f1"] == 1
    assert result["classification_report"]["macro"]["f1"] == .5
    assert "negative_precision" in result["undefined"]
    assert "accuracy" in independent_metrics([])["undefined"]


def test_independent_report_agrees_with_optional_sklearn_reference():
    metrics = pytest.importorskip("sklearn.metrics")
    expected, predicted = zip(*pairs_30(), strict=True)
    reference = metrics.classification_report(
        expected, predicted, labels=[False, True], target_names=["negative", "positive"],
        output_dict=True, zero_division=0,
    )
    ours = independent_metrics(pairs_30())["classification_report"]
    for name, reference_name in (("positive", "positive"), ("negative", "negative"),
                                 ("macro", "macro avg"), ("weighted", "weighted avg")):
        for key, ref_key in (("precision", "precision"), ("recall", "recall"), ("f1", "f1-score")):
            assert ours[name][key] == pytest.approx(reference[reference_name][ref_key])


def test_join_uses_affair_ids_not_position_and_ignores_order():
    gold = [{"affair_id": "a", "label": True}, {"affair_id": "b", "label": False}]
    result = audit_predictions(gold, [{"affair_id": "b", "status": "not_assigned"},
                                      {"affair_id": "a", "status": "assigned"}])
    assert result["metrics"]["tp"] == result["metrics"]["tn"] == 1
    assert result["coverage"] == 1


@pytest.mark.parametrize("label", [None, "false", "False", "0", 0, 1, []])
def test_missing_or_nonboolean_gold_is_not_coerced_to_negative_or_positive(label):
    with pytest.raises(ValueError, match="label"):
        audit_predictions([{"affair_id": "a", "label": label}], [])
    with pytest.raises(ValueError, match="label"):
        audit_predictions([{"affair_id": "a"}], [])


@pytest.mark.parametrize("status", ["failed", "uncertain", "not_evaluable", "missing"])
def test_unresolved_predictions_remain_in_coverage_denominator(status):
    gold = [{"affair_id": "a", "label": True}, {"affair_id": "b", "label": False}]
    predicted = [{"affair_id": "b", "status": "not_assigned"}]
    if status != "missing":
        predicted.append({"affair_id": "a", "status": status})
    result = audit_predictions(gold, predicted)
    assert result["expected"] == 2 and result["decisive"] == 1
    assert result["coverage"] == .5
    assert result["status_counts"][status] == 1
    assert result["cases"][0]["prediction"] is None
    assert result["cases"][0]["cell"] is None
    assert result["metrics"]["fn"] == 0  # No invented negative decision for the missing positive.


@pytest.mark.parametrize("kind", ["gold", "prediction", "unknown-id", "unknown-status",
                                 "nested-id", "embedded-label", "empty-id"])
def test_ambiguous_or_inconsistent_id_label_mapping_is_rejected(kind):
    gold = [{"affair_id": "a", "label": True}]
    prediction = [{"affair_id": "a", "status": "assigned"}]
    if kind == "gold":
        gold *= 2
    elif kind == "prediction":
        prediction *= 2
    elif kind == "unknown-id":
        prediction[0]["affair_id"] = "foreign"
    elif kind == "unknown-status":
        prediction[0]["status"] = "looks-positive"
    elif kind == "nested-id":
        prediction = [{"affair_id": "a", "result": {"affair_id": "b", "status": "assigned"}}]
    elif kind == "embedded-label":
        prediction[0]["label"] = False
    else:
        gold[0]["affair_id"] = ""
    with pytest.raises(ValueError):
        audit_predictions(gold, prediction)


def test_labels_and_split_metadata_never_enter_classification_prompt():
    from parltopic.classification.prompts import build_user_prompt
    from parltopic.models import Affair, TopicDefinition
    from parltopic.retrieval.chunker import chunk_affair

    topic = TopicDefinition(topic_id="digital", name="Digital", description="Digital policy")
    source = {"affair_id": "a", "title": "Hospital budget", "text": "New building."}
    positive = Affair.model_validate({**source, "label": True, "split": "train"})
    negative = Affair.model_validate({**source, "label": False, "split": "test"})
    assert "label" not in positive.model_dump()
    assert "split" not in positive.model_dump()
    assert build_user_prompt(topic, chunk_affair(positive)) == build_user_prompt(
        topic, chunk_affair(negative)
    )


def test_duplicate_normalization_preserves_semantic_words():
    assert normalize("  DIGITALE\nVerwaltung ") == normalize("digitale Verwaltung")
    assert normalize("Chancen und Gefahren") != normalize("Chancen")
