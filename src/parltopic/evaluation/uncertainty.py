"""Class-stratified bootstrap intervals for a fixed binary validation sample."""

import random
from pathlib import Path

from parltopic.evaluation.compare import DECISIVE, _percentile
from parltopic.evaluation.metrics import binary_metrics
from parltopic.evaluation.run import _validated_results, read_rows


def bootstrap_metrics(
    eval_path: str | Path, results_path: str | Path, samples: int = 2000, seed: int = 42
) -> dict:
    if samples < 1:
        raise ValueError("samples must be at least 1")
    rows = read_rows(eval_path)
    results, _ = _validated_results(rows, read_rows(results_path))
    covered = [row for row in rows if results.get(row["affair_id"], {}).get("status") in DECISIVE]
    positive = [row for row in covered if row["label"] is True]
    negative = [row for row in covered if row["label"] is False]
    if len(positive) + len(negative) != len(covered):
        raise ValueError("Binary uncertainty estimation requires boolean labels")
    if not positive or not negative:
        raise ValueError("Both classes must be covered to estimate stratified uncertainty")

    def calculate(sample):
        return binary_metrics(
            [row["label"] for row in sample],
            [results[row["affair_id"]]["status"] == "assigned" for row in sample],
        )

    estimate = calculate(covered)
    rng = random.Random(seed)
    names = ("precision", "recall", "f1", "macro_f1")
    distributions = {name: [] for name in names}
    for _ in range(samples):
        metrics = calculate(
            rng.choices(positive, k=len(positive)) + rng.choices(negative, k=len(negative))
        )
        for name in names:
            distributions[name].append(getattr(metrics, name))
    return {
        "method": "class-stratified percentile bootstrap",
        "samples": samples, "seed": seed,
        "coverage": {"decisive": len(covered), "total": len(rows)},
        "metrics": {
            name: {
                "estimate": round(getattr(estimate, name), 4),
                "interval_95": [round(_percentile(distributions[name], q), 4)
                                for q in (0.025, 0.975)],
            } for name in names
        },
        "interpretation": (
            "Conditional on covered cases, sampled class ratio and supplied proxy labels. "
            "Does not account for label error, model selection, source families "
            "or prevalence shift."
        ),
    }
