from dataclasses import dataclass


@dataclass(frozen=True)
class BinaryMetrics:
    precision: float
    recall: float
    f1: float
    negative_precision: float
    negative_recall: float
    negative_f1: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    accuracy: float
    count: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


def binary_metrics(expected: list[bool], predicted: list[bool]) -> BinaryMetrics:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have equal length")
    true_positive = sum(a and b for a, b in zip(expected, predicted, strict=True))
    false_positive = sum(not a and b for a, b in zip(expected, predicted, strict=True))
    false_negative = sum(a and not b for a, b in zip(expected, predicted, strict=True))
    true_negative = sum(not a and not b for a, b in zip(expected, predicted, strict=True))
    correct = sum(a == b for a, b in zip(expected, predicted, strict=True))
    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative
    precision = true_positive / predicted_positive if predicted_positive else 0.0
    recall = true_positive / actual_positive if actual_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    predicted_negative = true_negative + false_negative
    actual_negative = true_negative + false_positive
    negative_precision = true_negative / predicted_negative if predicted_negative else 0.0
    negative_recall = true_negative / actual_negative if actual_negative else 0.0
    negative_f1 = (
        2 * negative_precision * negative_recall / (negative_precision + negative_recall)
        if negative_precision + negative_recall
        else 0.0
    )
    macro_f1 = (f1 + negative_f1) / 2
    macro_precision = (precision + negative_precision) / 2
    macro_recall = (recall + negative_recall) / 2
    accuracy = correct / len(expected) if expected else 0.0
    return BinaryMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        negative_precision=negative_precision,
        negative_recall=negative_recall,
        negative_f1=negative_f1,
        macro_precision=macro_precision,
        macro_recall=macro_recall,
        macro_f1=macro_f1,
        accuracy=accuracy,
        count=len(expected),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
    )


def precision_at_prevalence(metrics: BinaryMetrics, prevalence: float) -> float:
    """Estimate positive predictive value for a stated class prevalence."""
    if not 0 <= prevalence <= 1:
        raise ValueError("prevalence must be between 0 and 1")
    positive_support = metrics.true_positive + metrics.false_negative
    negative_support = metrics.true_negative + metrics.false_positive
    sensitivity = metrics.true_positive / positive_support if positive_support else 0.0
    false_positive_rate = metrics.false_positive / negative_support if negative_support else 0.0
    numerator = sensitivity * prevalence
    denominator = numerator + false_positive_rate * (1 - prevalence)
    return numerator / denominator if denominator else 0.0

