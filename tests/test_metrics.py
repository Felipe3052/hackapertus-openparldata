from parltopic.evaluation.metrics import binary_metrics


def test_binary_metrics() -> None:
    result = binary_metrics([True, True, False, False], [True, False, True, False])
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5
    assert result.accuracy == 0.5

