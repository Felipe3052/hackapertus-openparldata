from parltopic.evaluation.metrics import binary_metrics, precision_at_prevalence


def test_binary_metrics() -> None:
    result = binary_metrics([True, True, False, False], [True, False, True, False])
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5
    assert result.negative_f1 == 0.5
    assert result.macro_precision == 0.5
    assert result.macro_recall == 0.5
    assert result.macro_f1 == 0.5
    assert result.accuracy == 0.5
    assert (result.true_positive, result.false_positive) == (1, 1)
    assert (result.false_negative, result.true_negative) == (1, 1)


def test_precision_at_prevalence() -> None:
    result = binary_metrics([True, True, False, False], [True, True, True, False])
    assert precision_at_prevalence(result, 0.5) == result.precision
    assert precision_at_prevalence(result, 0.01) < result.precision

