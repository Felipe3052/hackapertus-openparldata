"""Offline APS shadow-router evaluation.

This reports candidate recall against one annotator and disagreement with the second annotator.
It is an exploratory diagnostic, not a model-quality score or a consensus gold standard.
"""

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from parltopic.aps import ApsRouter, ApsTaxonomy, select_context
from parltopic.models import Affair
from parltopic.retrieval.chunker import chunk_affair


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _codes(annotation: dict[str, Any], field: str) -> set[str]:
    if annotation.get("none"):
        return set()
    return {value for key, value in annotation.items() if key.startswith(field) and value}


def check_disjoint_ids(paths: dict[str, Path]) -> dict[str, Any]:
    """Check that named JSONL splits contain unique and disjoint affair IDs."""
    ids_by_name: dict[str, set[str]] = {}
    duplicates: dict[str, list[str]] = {}
    for name, path in paths.items():
        ids: list[str] = []
        for row in _load_jsonl(path):
            identifier = row.get("affair_id", row.get("id"))
            if identifier is None:
                raise ValueError(f"{name} contains a row without affair_id or id")
            ids.append(str(identifier))
        ids_by_name[name] = set(ids)
        duplicates[name] = sorted({identifier for identifier in ids if ids.count(identifier) > 1})

    overlaps: dict[str, list[str]] = {}
    names = list(ids_by_name)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            shared = sorted(ids_by_name[left] & ids_by_name[right])
            if shared:
                overlaps[f"{left}∩{right}"] = shared
    return {
        "datasets": {name: len(ids) for name, ids in ids_by_name.items()},
        "duplicates": {name: values for name, values in duplicates.items() if values},
        "overlaps": overlaps,
        "disjoint": not any(duplicates.values()) and not overlaps,
    }


def make_annotation_template(
    input_path: Path,
    output_path: Path,
    exclude_paths: tuple[Path, ...] = (),
    sample_size: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Create a deterministic, stratified APS annotation file without labels."""
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    source = _load_jsonl(input_path)
    source_ids = {str(row.get("affair_id")) for row in source}
    excluded_ids = set()
    for path in exclude_paths:
        excluded_ids.update(
            str(row.get("affair_id", row.get("id"))) for row in _load_jsonl(path)
        )
    eligible = [row for row in source if str(row.get("affair_id")) not in excluded_ids]
    if len({str(row.get("affair_id")) for row in source}) != len(source):
        raise ValueError("Annotation source contains duplicate affair IDs")
    if sample_size > len(eligible):
        raise ValueError(f"Requested {sample_size} affairs, only {len(eligible)} are eligible")

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        buckets[f"{row.get('language', 'unknown')}|{row.get('level', 'unknown')}"].append(row)
    rng = random.Random(seed)
    for rows in buckets.values():
        rng.shuffle(rows)
    selected: list[dict[str, Any]] = []
    bucket_names = sorted(buckets)
    while len(selected) < sample_size:
        added = False
        for bucket in bucket_names:
            if len(selected) >= sample_size:
                break
            rows = buckets[bucket]
            if rows:
                selected.append(rows.pop())
                added = True
        if not added:
            break
    selected.sort(key=lambda row: str(row["affair_id"]))
    output_rows = []
    for row in selected:
        output_rows.append({
            **row,
            "aps_annotation": {
                "chapter_code": None,
                "topic_codes": [],
                "not_classifiable": None,
                "annotator": "",
                "notes": "",
            },
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in output_rows) + "\n",
        encoding="utf-8",
    )
    return {
        "source": str(input_path),
        "source_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "excluded_ids": len(excluded_ids & source_ids),
        "eligible": len(eligible),
        "selected": len(selected),
        "strata": {bucket: sum(
            f"{row.get('language', 'unknown')}|{row.get('level', 'unknown')}" == bucket
            for row in selected
        ) for bucket in bucket_names},
        "seed": seed,
        "output": str(output_path),
        "labels": (
            "blank APS annotation template; requires two independent annotators and consensus"
        ),
    }


def build_consensus_labels(labels_path: Path, output_path: Path) -> dict[str, Any]:
    """Write only unanimous double annotations as an evaluator-compatible APS gold file."""
    rows = _load_jsonl(labels_path)
    if not rows:
        raise ValueError("APS labels file is empty")
    output_rows: list[dict[str, Any]] = []
    disputed: list[str] = []
    for row in rows:
        affair_id = str(row.get("affair_id", ""))
        if not affair_id or "felipe" not in row or "josip" not in row:
            raise ValueError("APS labels require affair_id, felipe, and josip fields")
        left = row["felipe"]
        right = row["josip"]
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise ValueError(f"APS annotations for {affair_id} must be objects")
        if _annotation_signature(left) != _annotation_signature(right):
            disputed.append(affair_id)
            continue
        consensus = _canonical_annotation(left)
        output_rows.append(
            {
                "affair_id": affair_id,
                "consensus": consensus,
                "felipe": consensus,
                "josip": consensus,
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output_rows),
        encoding="utf-8",
    )
    return {
        "input": str(labels_path),
        "output": str(output_path),
        "input_labels": len(rows),
        "consensus_labels": len(output_rows),
        "disputed_labels": len(disputed),
        "disputed_affair_ids": disputed,
        "warning": "Consensus contains only unanimous labels; disputed affairs are excluded.",
    }


def _canonical_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    return {
        "chapter": str(annotation.get("chapter", "")),
        "topic": str(annotation.get("topic", "")),
        "topic2": str(annotation.get("topic2", "")),
        "none": bool(annotation.get("none", False)),
    }


def _annotation_signature(annotation: dict[str, Any]) -> tuple[str, str, str, bool]:
    canonical = _canonical_annotation(annotation)
    return (
        canonical["chapter"],
        canonical["topic"],
        canonical["topic2"],
        canonical["none"],
    )


def benchmark_context(
    sample_path: Path,
    topic_path: Path,
    taxonomy_path: Path,
    max_segments: int = 2,
    aliases_path: Path | None = None,
) -> dict[str, Any]:
    """Compare actual prompt context sizes without making inference calls."""
    from parltopic.classification.service import ClassificationService, PreparedAffair
    from parltopic.config import Settings
    from parltopic.topics import load_topic

    affairs = [Affair.model_validate(row) for row in _load_jsonl(sample_path)]
    topic = load_topic(topic_path)
    baseline_settings = Settings(
        _env_file=None, llm_api_key="offline", keyword_rescue_enabled=False
    )
    aps_settings = baseline_settings.model_copy(
        update={
            "aps_context_enabled": True,
            "aps_taxonomy_path": taxonomy_path,
            "aps_aliases_path": aliases_path,
            "aps_context_max_segments": max_segments,
        }
    )

    def measure(settings: Settings) -> tuple[int, int, int]:
        affairs_used = segments = tokens = 0
        with ClassificationService(settings) as service:
            for affair in affairs:
                prepared = service.prepare(affair, topic)
                if not isinstance(prepared, PreparedAffair):
                    continue
                affairs_used += 1
                segments += len(prepared.selected)
                tokens += sum(len(segment.text.split()) for segment in prepared.selected)
        return affairs_used, segments, tokens

    baseline_n, baseline_segments, baseline_tokens = measure(baseline_settings)
    candidate_n, candidate_segments, candidate_tokens = measure(aps_settings)
    if baseline_n != candidate_n:
        raise ValueError("Baseline and APS context benchmark selected different affairs")
    reduction = (baseline_tokens - candidate_tokens) / baseline_tokens if baseline_tokens else 0.0
    return {
        "mode": "offline_context_benchmark",
        "affairs": baseline_n,
        "max_segments": max_segments,
        "baseline": {
            "segments": baseline_segments,
            "tokens_approx": baseline_tokens,
        },
        "aps_context": {
            "segments": candidate_segments,
            "tokens_approx": candidate_tokens,
        },
        "token_reduction_ratio": round(reduction, 6),
        "warning": "No Apertus calls; token counts use whitespace approximation.",
    }


def regression_gate(
    eval_path: Path,
    baseline_path: Path,
    candidate_path: Path,
    max_macro_f1_drop: float = 0.01,
    max_recall_drop: float = 0.01,
    max_group_drop: float = 0.03,
) -> dict[str, Any]:
    """Check that a candidate run does not materially regress the frozen baseline."""
    from parltopic.evaluation.run import score_results

    baseline = score_results(eval_path, baseline_path)
    candidate = score_results(eval_path, candidate_path)
    checks: dict[str, bool] = {}

    base_coverage = float(baseline["result_integrity"]["coverage"])
    candidate_coverage = float(candidate["result_integrity"]["coverage"])
    checks["coverage"] = candidate_coverage >= base_coverage
    base_all = baseline["assigned"]["all"]
    candidate_all = candidate["assigned"]["all"]
    checks["macro_f1"] = candidate_all["macro_f1"] >= base_all["macro_f1"] - max_macro_f1_drop
    checks["positive_recall"] = candidate_all["recall"] >= base_all["recall"] - max_recall_drop

    group_checks: dict[str, bool] = {}
    for group in ("lang=de", "lang=fr", "lang=it", "level=federal", "level=cantonal"):
        base_group = baseline["assigned"].get(group)
        candidate_group = candidate["assigned"].get(group)
        if not base_group or not candidate_group or base_group["n"] < 10:
            continue
        group_checks[group] = (
            candidate_group["macro_f1"] >= base_group["macro_f1"] - max_group_drop
            and candidate_group["recall"] >= base_group["recall"] - max_group_drop
        )
    checks["language_and_level_groups"] = all(group_checks.values())
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "group_checks": group_checks,
        "thresholds": {
            "max_macro_f1_drop": max_macro_f1_drop,
            "max_recall_drop": max_recall_drop,
            "max_group_drop": max_group_drop,
        },
        "baseline": {
            "coverage": base_coverage,
            "macro_f1": base_all["macro_f1"],
            "recall": base_all["recall"],
        },
        "candidate": {
            "coverage": candidate_coverage,
            "macro_f1": candidate_all["macro_f1"],
            "recall": candidate_all["recall"],
        },
    }


def evaluate_shadow(
    sample_path: Path,
    labels_path: Path,
    taxonomy_path: Path,
    annotator: str = "felipe",
    max_chapters: int = 4,
    max_topics: int = 8,
    aliases_path: Path | None = None,
) -> dict[str, Any]:
    sample = _load_jsonl(sample_path)
    labels = _load_jsonl(labels_path)
    affairs = {str(row["affair_id"]): Affair.model_validate(row) for row in sample}
    if len(affairs) != len(sample):
        raise ValueError("APS sample contains duplicate affair_id values")
    label_by_id = {str(row["affair_id"]): row for row in labels}
    if len(label_by_id) != len(labels):
        raise ValueError("APS labels contain duplicate affair_id values")
    missing = sorted(set(label_by_id) - set(affairs))
    if missing:
        raise ValueError(f"APS labels reference affairs absent from sample: {missing[:3]}")

    router = ApsRouter(ApsTaxonomy.load(taxonomy_path, aliases_path=aliases_path))
    chapter_hits = topic_hits = chapter_total = topic_total = 0
    chapter_candidates_total = topic_candidates_total = 0
    routed = no_text = 0
    disagreements = {"chapter": 0, "topic": 0}
    compression_ratios: list[float] = []
    tokens_before = tokens_after = 0
    for affair_id, row in label_by_id.items():
        affair = affairs[affair_id]
        route = router.route(affair, max_chapters, max_topics)
        segments = chunk_affair(affair)
        if route.fallback_reason:
            approximate_tokens = sum(len(segment.text.split()) for segment in segments)
            context_report = {
                "compression_ratio": 1.0,
                "input_tokens_approx": approximate_tokens,
                "selected_tokens_approx": approximate_tokens,
            }
        else:
            _, context_report = select_context(segments, route, router.taxonomy)
        compression_ratios.append(context_report["compression_ratio"])
        tokens_before += context_report["input_tokens_approx"]
        tokens_after += context_report["selected_tokens_approx"]
        if route.chapter_candidates:
            routed += 1
        if route.fallback_reason == "no_text":
            no_text += 1
        expected = row[annotator]
        chapters = _codes(expected, "chapter")
        topics = _codes(expected, "topic")
        predicted_chapters = {candidate.code for candidate in route.chapter_candidates}
        predicted_topics = {candidate.code for candidate in route.topic_candidates}
        chapter_total += len(chapters)
        topic_total += len(topics)
        chapter_hits += len(chapters & predicted_chapters)
        topic_hits += len(topics & predicted_topics)
        chapter_candidates_total += len(predicted_chapters)
        topic_candidates_total += len(predicted_topics)
        other = row.get("josip" if annotator == "felipe" else "felipe", expected)
        disagreements["chapter"] += bool(_codes(expected, "chapter") != _codes(other, "chapter"))
        disagreements["topic"] += bool(_codes(expected, "topic") != _codes(other, "topic"))

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    warning = (
        "Consensus labels are derived from unanimous double annotations; "
        "router recall is diagnostic only."
        if annotator == "consensus"
        else "No consensus APS gold standard; diagnostic only."
    )
    return {
        "mode": "shadow_router_diagnostic",
        "annotator": annotator,
        "sample_size": len(sample),
        "labelled_size": len(labels),
        "routed": routed,
        "no_text": no_text,
        "chapter_recall_at_k": ratio(chapter_hits, chapter_total),
        "topic_recall_at_k": ratio(topic_hits, topic_total),
        "chapter_precision_at_k": ratio(chapter_hits, chapter_candidates_total),
        "topic_precision_at_k": ratio(topic_hits, topic_candidates_total),
        "context": {
            "mean_compression_ratio": round(sum(compression_ratios) / len(compression_ratios), 6),
            "token_reduction_ratio": ratio(tokens_before - tokens_after, tokens_before),
            "tokens_before_approx": tokens_before,
            "tokens_after_approx": tokens_after,
        },
        "annotator_disagreement": {
            "chapter": ratio(disagreements["chapter"], len(labels)),
            "topic": ratio(disagreements["topic"], len(labels)),
        },
        "warning": warning,
    }
