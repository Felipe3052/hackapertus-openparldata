"""Offline APS shadow-router evaluation.

This reports candidate recall against one annotator and disagreement with the second annotator.
It is an exploratory diagnostic, not a model-quality score or a consensus gold standard.
"""

import json
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


def evaluate_shadow(
    sample_path: Path,
    labels_path: Path,
    taxonomy_path: Path,
    annotator: str = "felipe",
    max_chapters: int = 4,
    max_topics: int = 8,
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

    router = ApsRouter(ApsTaxonomy.load(taxonomy_path))
    chapter_hits = topic_hits = chapter_total = topic_total = 0
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
        chapter_total += bool(chapters)
        topic_total += bool(topics)
        chapter_hits += bool(chapters & predicted_chapters)
        topic_hits += bool(topics & predicted_topics)
        other = row["josip" if annotator == "felipe" else "felipe"]
        disagreements["chapter"] += bool(_codes(expected, "chapter") != _codes(other, "chapter"))
        disagreements["topic"] += bool(_codes(expected, "topic") != _codes(other, "topic"))

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    return {
        "mode": "shadow_router_diagnostic",
        "annotator": annotator,
        "sample_size": len(sample),
        "labelled_size": len(labels),
        "routed": routed,
        "no_text": no_text,
        "chapter_recall_at_k": ratio(chapter_hits, chapter_total),
        "topic_recall_at_k": ratio(topic_hits, topic_total),
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
        "warning": "No consensus APS gold standard; diagnostic only.",
    }
