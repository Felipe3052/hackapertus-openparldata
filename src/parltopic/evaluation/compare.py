"""Paired statistical comparison of two classifier runs."""

import random
from pathlib import Path
from typing import Any

from parltopic.evaluation.metrics import binary_metrics
from parltopic.evaluation.run import read_rows
from parltopic.models import ClassificationStatus

DECISIVE = {
    ClassificationStatus.ASSIGNED.value,
    ClassificationStatus.NOT_ASSIGNED.value,
}


def _result_map(path: str | Path) -> dict[str, dict[str, Any]]:
    rows = read_rows(path)
    ids = [row["affair_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate affair IDs in {path}")
    return {row["affair_id"]: row for row in rows}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a percentile of an empty list")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def compare_runs(
    eval_path: str | Path,
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    samples: int = 2_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare macro-F1 on identical, decisive examples with a paired bootstrap."""
    if samples < 1:
        raise ValueError("samples must be at least 1")
    labels = {row["affair_id"]: bool(row["label"]) for row in read_rows(eval_path)}
    baseline = _result_map(baseline_path)
    candidate = _result_map(candidate_path)
    shared_ids = sorted(
        affair_id
        for affair_id in labels.keys() & baseline.keys() & candidate.keys()
        if baseline[affair_id].get("status") in DECISIVE
        and candidate[affair_id].get("status") in DECISIVE
    )
    if not shared_ids:
        raise ValueError("No shared examples with decisive results")

    expected = [labels[affair_id] for affair_id in shared_ids]
    baseline_predicted = [
        baseline[affair_id]["status"] == ClassificationStatus.ASSIGNED.value
        for affair_id in shared_ids
    ]
    candidate_predicted = [
        candidate[affair_id]["status"] == ClassificationStatus.ASSIGNED.value
        for affair_id in shared_ids
    ]
    baseline_metrics = binary_metrics(expected, baseline_predicted)
    candidate_metrics = binary_metrics(expected, candidate_predicted)
    observed_delta = candidate_metrics.macro_f1 - baseline_metrics.macro_f1

    rng = random.Random(seed)
    deltas = []
    size = len(shared_ids)
    for _ in range(samples):
        indices = [rng.randrange(size) for _ in range(size)]
        sampled_expected = [expected[index] for index in indices]
        baseline_sample = [baseline_predicted[index] for index in indices]
        candidate_sample = [candidate_predicted[index] for index in indices]
        deltas.append(
            binary_metrics(sampled_expected, candidate_sample).macro_f1
            - binary_metrics(sampled_expected, baseline_sample).macro_f1
        )

    return {
        "paired_examples": size,
        "excluded": {
            "eval_examples": len(labels),
            "not_shared_or_not_decisive": len(labels) - size,
        },
        "baseline": {
            "model": next(iter(baseline.values()), {}).get("model"),
            "prompt_version": next(iter(baseline.values()), {}).get("prompt_version"),
            "macro_f1": round(baseline_metrics.macro_f1, 4),
        },
        "candidate": {
            "model": next(iter(candidate.values()), {}).get("model"),
            "prompt_version": next(iter(candidate.values()), {}).get("prompt_version"),
            "macro_f1": round(candidate_metrics.macro_f1, 4),
        },
        "macro_f1_delta": round(observed_delta, 4),
        "bootstrap": {
            "samples": samples,
            "seed": seed,
            "confidence_interval_95": [
                round(_percentile(deltas, 0.025), 4),
                round(_percentile(deltas, 0.975), 4),
            ],
            "probability_candidate_better": round(
                sum(delta > 0 for delta in deltas) / samples, 4
            ),
        },
    }
