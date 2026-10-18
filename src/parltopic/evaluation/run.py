"""Run classifiers over a frozen eval set and score the results per language and level."""

import json
from collections import defaultdict
from collections.abc import Callable
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
    topic_for: Callable[[Affair], TopicDefinition] | None = None,
) -> Path:
    """Classify every affair of the eval set; resumes by skipping affairs already in out_path.

    `topic_for` builds a per-affair topic (e.g. with retrieved few-shot examples). Failed calls
    are retried on the next run; the later line for an affair wins when scoring.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {r["affair_id"] for r in read_rows(out) if r["status"] != ClassificationStatus.FAILED.value}
        if out.exists()
        else set()
    )
    todo = [row for row in read_rows(eval_path) if row["affair_id"] not in done][:limit]
    service = ClassificationService(settings)
    affairs = [Affair.model_validate(row) for row in todo]
    with out.open("a", encoding="utf-8") as file, ThreadPoolExecutor(workers) as pool:
        futures = [
            pool.submit(service.classify, affair, topic_for(affair) if topic_for else topic)
            for affair in affairs
        ]
        for future in as_completed(futures):
            file.write(future.result().model_dump_json() + "\n")
            file.flush()
    return out


def run_rethink(
    eval_path: str | Path,
    topic: TopicDefinition,
    base_path: str | Path,
    out_path: str | Path,
    settings: Settings,
    workers: int = 8,
) -> Path:
    """Re-check the fast pass's not_assigned answers with reasoning; write the merged results.

    Raw reasoning answers go to `<out>.thinking.jsonl` (resumable). In the merged file a
    re-checked affair takes the reasoning label, with the tokens and latency of both calls.
    """
    from parltopic.classification.thinking import rethink

    out = Path(out_path)
    raw = out.with_suffix(".thinking.jsonl")
    base = {row["affair_id"]: row for row in read_rows(base_path)}
    affairs = {row["affair_id"]: row for row in read_rows(eval_path)}
    done = {row["affair_id"] for row in read_rows(raw)} if raw.exists() else set()
    todo = [
        i
        for i, row in base.items()
        if row["status"] == ClassificationStatus.NOT_ASSIGNED.value and i not in done
    ]
    with raw.open("a", encoding="utf-8") as file, ThreadPoolExecutor(workers) as pool:
        futures = [
            pool.submit(rethink, Affair.model_validate(affairs[i]), topic, settings) for i in todo
        ]
        for future in as_completed(futures):
            file.write(future.result().model_dump_json() + "\n")
            file.flush()

    second = {row["affair_id"]: row for row in read_rows(raw)}
    with out.open("w", encoding="utf-8") as file:
        for affair_id, row in base.items():
            merged = dict(row)
            again = second.get(affair_id)
            if again and again["status"] != ClassificationStatus.FAILED.value:
                merged = {
                    **again,
                    "model": f"{row['model']} + {again['model']}",
                    "input_tokens": (row.get("input_tokens") or 0) + (again["input_tokens"] or 0),
                    "output_tokens": (row.get("output_tokens") or 0)
                    + (again["output_tokens"] or 0),
                    "latency_ms": (row.get("latency_ms") or 0) + (again["latency_ms"] or 0),
                }
            file.write(json.dumps(merged, ensure_ascii=False) + "\n")
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
