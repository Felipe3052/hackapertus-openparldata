"""Run classifiers over a frozen eval set and score the results per language and level."""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from parltopic.classification.keyword import first_keyword_hit
from parltopic.classification.prompts import system_prompt
from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.evaluation.metrics import binary_metrics, precision_at_prevalence
from parltopic.models import Affair, ClassificationStatus, TopicDefinition
from parltopic.retrieval.chunker import chunk_affair

POSITIVE = {ClassificationStatus.ASSIGNED.value}
POSITIVE_OR_UNCERTAIN = POSITIVE | {ClassificationStatus.UNCERTAIN.value}


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _run_manifest(eval_path: str | Path, topic: TopicDefinition, settings: Settings) -> dict:
    """Capture prediction-affecting inputs without credentials or evaluation labels in prompts."""
    source_root = Path(__file__).resolve().parents[1]
    source_files = [
        "classification/service.py", "classification/keyword.py", "classification/prompts.py",
        "classification/apertus_client.py", "retrieval/chunker.py", "retrieval/bm25.py",
        "models.py",
    ]
    return {
        "schema_version": 1,
        "dataset_sha256": hashlib.sha256(Path(eval_path).read_bytes()).hexdigest(),
        "topic": topic.model_dump(mode="json"),
        "system_prompt": system_prompt(topic.prompt_version or settings.classifier_prompt_version),
        "settings": {
            key: getattr(settings, key)
            for key in (
                "llm_name", "llm_base_url", "classifier_prompt_version",
                "classifier_policy_version", "keyword_rescue_enabled", "chunk_size",
                "chunk_overlap", "retrieval_top_k",
                "keyword_document_gate_enabled", "retrieval_pin_title",
                "llm_connection_reuse", "llm_requests_per_minute", "llm_batch_size",
            )
        },
        "implementation_sha256": {
            name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
            for name in source_files
        },
    }


def run_classifier(
    eval_path: str | Path,
    topic: TopicDefinition,
    out_path: str | Path,
    settings: Settings,
    workers: int = 8,
    limit: int | None = None,
    retry_failed: bool = True,
    topic_for: Callable[[Affair], TopicDefinition] | None = None,
) -> Path:
    """Classify every affair of the eval set; resumes by skipping affairs already in out_path.

    `topic_for` builds a per-affair topic (e.g. with retrieved few-shot examples).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = read_rows(out) if out.exists() else []
    manifest_path = out.with_suffix(out.suffix + ".manifest.json")
    manifest = _run_manifest(eval_path, topic, settings)
    if existing:
        if not manifest_path.exists():
            raise ValueError("Existing results have no provenance manifest; use a new output path")
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Run inputs changed; use a new output path to avoid mixing results")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if retry_failed:
        existing = [
            row for row in existing if row.get("status") != ClassificationStatus.FAILED.value
        ]
    done = {row["affair_id"] for row in existing}
    candidates = read_rows(eval_path)
    if limit is not None:
        candidates = candidates[:limit]
    todo = [row for row in candidates if row["affair_id"] not in done]
    if not todo and out.exists():
        return out
    service = ClassificationService(settings)
    affairs = [Affair.model_validate(row) for row in todo]
    with service, out.open("w", encoding="utf-8") as file, ThreadPoolExecutor(workers) as pool:
        for row in existing:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
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
    Every merged row carries the same model, prompt and classifier version (one run = one
    configuration, as scoring requires).
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

    from parltopic.classification.thinking import THINKING_MODEL

    second = {row["affair_id"]: row for row in read_rows(raw)}
    with out.open("w", encoding="utf-8") as file:
        for affair_id, row in base.items():
            merged = dict(row)
            again = second.get(affair_id)
            if again and again["status"] != ClassificationStatus.FAILED.value:
                merged = {
                    **again,
                    "input_tokens": (row.get("input_tokens") or 0) + (again["input_tokens"] or 0),
                    "output_tokens": (row.get("output_tokens") or 0)
                    + (again["output_tokens"] or 0),
                    "latency_ms": (row.get("latency_ms") or 0) + (again["latency_ms"] or 0),
                }
            merged["model"] = f"{row['model']} + {THINKING_MODEL}"
            merged["prompt_version"] = row.get("prompt_version")
            merged["classifier_version"] = f"{row.get('classifier_version')}+rethink"
            file.write(json.dumps(merged, ensure_ascii=False) + "\n")
    return out


def keyword_predictions(eval_path: str | Path, topic: TopicDefinition) -> dict[str, bool]:
    """Baseline B0, today's full-text search: any topic name or synonym occurs in the affair."""
    predictions = {}
    for row in read_rows(eval_path):
        affair = Affair.model_validate(row)
        segments = chunk_affair(affair, 10_000_000, 0)
        predictions[row["affair_id"]] = first_keyword_hit(segments, topic) is not None
    return predictions


def _metrics_row(
    pairs: list[tuple[bool, bool]], deployment_prevalence: float | None = None
) -> dict[str, Any]:
    expected, predicted = zip(*pairs, strict=True) if pairs else ((), ())
    m = binary_metrics(list(expected), list(predicted))
    row = {
        "n": m.count,
        "positives": sum(expected),
        "precision": round(m.precision, 3),
        "recall": round(m.recall, 3),
        "f1": round(m.f1, 3),
        "negative_f1": round(m.negative_f1, 3),
        "macro_precision": round(m.macro_precision, 3),
        "macro_recall": round(m.macro_recall, 3),
        "macro_f1": round(m.macro_f1, 3),
        "micro_f1": round(m.micro_f1, 3),
        "accuracy": round(m.accuracy, 3),
        "confusion": {
            "tp": m.true_positive,
            "fp": m.false_positive,
            "fn": m.false_negative,
            "tn": m.true_negative,
        },
    }
    if deployment_prevalence is not None:
        row["precision_at_deployment_prevalence"] = round(
            precision_at_prevalence(m, deployment_prevalence), 3
        )
        row["deployment_prevalence"] = deployment_prevalence
    return row


def _validated_results(
    eval_rows: list[dict[str, Any]], result_rows: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    eval_ids = {row["affair_id"] for row in eval_rows}
    result_ids = [row["affair_id"] for row in result_rows]
    duplicates = sorted(affair_id for affair_id, count in Counter(result_ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate result IDs: {duplicates[:10]}")
    unknown = sorted(set(result_ids) - eval_ids)
    if unknown:
        raise ValueError(f"Result IDs not present in evaluation set: {unknown[:10]}")
    models = {row.get("model") for row in result_rows}
    prompts = {row.get("prompt_version") for row in result_rows}
    classifiers = {row.get("classifier_version") for row in result_rows}
    if len(models) > 1 or len(prompts) > 1 or len(classifiers) > 1:
        raise ValueError(
            "A scored run must contain exactly one model, prompt, and classifier version"
        )
    results = {row["affair_id"]: row for row in result_rows}
    return results, eval_ids - set(results)


def score_binary(
    eval_path: str | Path,
    predictions: dict[str, bool],
    statuses: dict[str, str] | None = None,
    deployment_prevalence: float | None = None,
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
    report: dict[str, Any] = {
        key: _metrics_row(pairs, deployment_prevalence if key == "all" else None)
        for key, pairs in sorted(groups.items())
    }
    report["coverage"] = f"{len(groups['all'])}/{len(rows)}"
    if statuses:
        counts: dict[str, int] = defaultdict(int)
        for status in statuses.values():
            counts[status] += 1
        report["statuses"] = dict(counts)
    return report


def _deployment_prevalence(eval_path: str | Path) -> float | None:
    path = Path(eval_path)
    meta_path = path.parent / "meta.json"
    if not meta_path.exists():
        return None
    name = path.stem
    split = "test" if name.endswith("_test") else "dev" if name.endswith("_dev") else None
    if split is None or not name.startswith("e1_digitalisation_"):
        return None
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    prevalence = metadata.get(f"e1_{split}", {}).get("prevalence")
    return float(prevalence) if prevalence is not None else None


def score_results(eval_path: str | Path, results_path: str | Path) -> dict[str, Any]:
    eval_rows = read_rows(eval_path)
    result_rows = read_rows(results_path)
    results, missing = _validated_results(eval_rows, result_rows)
    statuses = {i: r["status"] for i, r in results.items()}
    covered = {
        i: s
        for i, s in statuses.items()
        if s
        in {
            ClassificationStatus.ASSIGNED.value,
            ClassificationStatus.NOT_ASSIGNED.value,
        }
    }
    deployment_prevalence = _deployment_prevalence(eval_path)
    tokens_in = sum(r.get("input_tokens") or 0 for r in results.values())
    tokens_out = sum(r.get("output_tokens") or 0 for r in results.values())
    latencies = sorted(r["latency_ms"] for r in results.values() if r.get("latency_ms"))
    return {
        "model": next(iter(results.values()), {}).get("model"),
        "prompt_version": next(iter(results.values()), {}).get("prompt_version"),
        "classifier_version": next(iter(results.values()), {}).get("classifier_version"),
        "result_integrity": {
            "expected": len(eval_rows),
            "received": len(results),
            "missing": len(missing),
            "coverage": round(len(covered) / len(eval_rows), 4) if eval_rows else 0.0,
        },
        "assigned": score_binary(
            eval_path,
            {i: s in POSITIVE for i, s in covered.items()},
            statuses,
            deployment_prevalence,
        ),
        "assigned_or_uncertain": score_binary(
            eval_path,
            {
                i: s in POSITIVE_OR_UNCERTAIN
                for i, s in statuses.items()
                if s in POSITIVE_OR_UNCERTAIN | {ClassificationStatus.NOT_ASSIGNED.value}
            },
        ),
        "usage_per_1000_affairs": {
            "input_tokens": round(tokens_in / len(results) * 1000) if results else 0,
            "output_tokens": round(tokens_out / len(results) * 1000) if results else 0,
        },
        "latency_ms_p50": latencies[len(latencies) // 2] if latencies else None,
        "label_warning": (
            "E1 untagged affairs are positive-unlabeled proxies, not adjudicated negatives."
        ),
    }
