from dataclasses import dataclass


@dataclass(frozen=True)
class BinaryMetrics:
    precision: float
    recall: float
    f1: float
    accuracy: float
    count: int


def binary_metrics(expected: list[bool], predicted: list[bool]) -> BinaryMetrics:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have equal length")
    true_positive = sum(a and b for a, b in zip(expected, predicted, strict=True))
    false_positive = sum(not a and b for a, b in zip(expected, predicted, strict=True))
    false_negative = sum(a and not b for a, b in zip(expected, predicted, strict=True))
    correct = sum(a == b for a, b in zip(expected, predicted, strict=True))
    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative
    precision = true_positive / predicted_positive if predicted_positive else 0.0
    recall = true_positive / actual_positive if actual_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = correct / len(expected) if expected else 0.0
    return BinaryMetrics(precision, recall, f1, accuracy, len(expected))

