"""Run classifiers over a frozen eval set and score the results per language and level."""

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.evaluation.metrics import binary_metrics
from parltopic.models import Affair, ClassificationStatus, TopicDefinition

POSITIVE = {ClassificationStatus.ASSIGNED.value}
POSITIVE_OR_UNCERTAIN = POSITIVE | {ClassificationStatus.UNCERTAIN.value}


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def run_classifier(
    eval_path: str | Path,
    topic: TopicDefinition,
    out_path: str | Path,
    settings: Settings,
    workers: int = 8,
    limit: int | None = None,
) -> Path:
    """Classify every affair of the eval set; resumes by skipping affairs already in out_path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {row["affair_id"] for row in read_rows(out)} if out.exists() else set()
    todo = [row for row in read_rows(eval_path) if row["affair_id"] not in done][:limit]
    service = ClassificationService(settings)
    with out.open("a", encoding="utf-8") as file, ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(service.classify, Affair.model_validate(row), topic) for row in todo]
        for future in as_completed(futures):
            file.write(future.result().model_dump_json() + "\n")
            file.flush()
    return out


def keyword_predictions(eval_path: str | Path, topic: TopicDefinition) -> dict[str, bool]:
    """Baseline B0, today's full-text search: any topic name or synonym occurs in the affair."""
    terms = [term.casefold() for term in [topic.name, *topic.synonyms]]
    return {
        row["affair_id"]: any(
            term in Affair.model_validate(row).combined_text().casefold() for term in terms
        )
        for row in read_rows(eval_path)
    }


def _metrics_row(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    expected, predicted = zip(*pairs, strict=True) if pairs else ((), ())
    m = binary_metrics(list(expected), list(predicted))
    return {
        "n": m.count,
        "positives": sum(expected),
        "precision": round(m.precision, 3),
        "recall": round(m.recall, 3),
        "f1": round(m.f1, 3),
    }


def score_binary(
    eval_path: str | Path,
    predictions: dict[str, bool],
    statuses: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Overall and per-language / per-level precision, recall and F1."""
    rows = read_rows(eval_path)
    groups: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for row in rows:
        if row["affair_id"] not in predictions:
            continue
        pair = (bool(row["label"]), predictions[row["affair_id"]])
        groups["all"].append(pair)
        groups[f"lang={row['language']}"].append(pair)
        groups[f"level={row['level']}"].append(pair)
    report: dict[str, Any] = {key: _metrics_row(pairs) for key, pairs in sorted(groups.items())}
    report["coverage"] = f"{len(groups['all'])}/{len(rows)}"
    if statuses:
        counts: dict[str, int] = defaultdict(int)
        for status in statuses.values():
            counts[status] += 1
        report["statuses"] = dict(counts)
    return report


def score_results(eval_path: str | Path, results_path: str | Path) -> dict[str, Any]:
    results = {row["affair_id"]: row for row in read_rows(results_path)}
    statuses = {i: r["status"] for i, r in results.items()}
    evaluated = {i: s for i, s in statuses.items() if s != ClassificationStatus.FAILED.value}
    tokens_in = sum(r.get("input_tokens") or 0 for r in results.values())
    tokens_out = sum(r.get("output_tokens") or 0 for r in results.values())
    latencies = sorted(r["latency_ms"] for r in results.values() if r.get("latency_ms"))
    return {
        "model": next(iter(results.values()), {}).get("model"),
        "assigned": score_binary(
            eval_path, {i: s in POSITIVE for i, s in evaluated.items()}, statuses
        ),
        "assigned_or_uncertain": score_binary(
            eval_path, {i: s in POSITIVE_OR_UNCERTAIN for i, s in evaluated.items()}
        ),
        "usage_per_1000_affairs": {
            "input_tokens": round(tokens_in / len(results) * 1000) if results else 0,
            "output_tokens": round(tokens_out / len(results) * 1000) if results else 0,
        },
        "latency_ms_p50": latencies[len(latencies) // 2] if latencies else None,
    }
