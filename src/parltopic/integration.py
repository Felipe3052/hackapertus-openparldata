"""Export classification results as rows for OpenParlData's `affair_topics` table.

Schema: integration/opd/001_affair_topics.sql. One row per affair, topic and topic version;
failed calls are not exported (they are a technical state, not a topic decision).
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from parltopic.compiler import CompiledTopic
from parltopic.models import ClassificationResult, ClassificationStatus, TopicDefinition


def topic_version(topic: TopicDefinition, compiled: CompiledTopic | None = None) -> str:
    payload = {"topic": topic.model_dump(mode="json"),
               "terms": compiled.terms if compiled else None}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())
    return digest.hexdigest()[:16]


def topic_row(topic: TopicDefinition, compiled: CompiledTopic | None = None) -> dict[str, Any]:
    return {
        "topic_id": topic.topic_id,
        "name": topic.name,
        "definition": topic.model_dump(mode="json"),
        "compiled_query": compiled.terms if compiled else None,
        "topic_version": topic_version(topic, compiled),
    }


def affair_topic_rows(
    results: list[ClassificationResult], version: str
) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        if result.status == ClassificationStatus.FAILED:
            continue
        evidence = result.evidence[0] if result.evidence else None
        rows.append({
            "affair_id": int(result.affair_id),
            "topic_id": result.topic_id,
            "topic_version": version,
            "status": result.status.value,
            "explanation": result.explanation or None,
            "evidence_text": evidence.text if evidence else None,
            "evidence_document_id": evidence.document_id if evidence else None,
            "evidence_url": str(evidence.source_url) if evidence and evidence.source_url else None,
            "language": result.language,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "classifier_version": result.classifier_version,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        })
    return rows


def export(
    results_path: str | Path,
    topic: TopicDefinition,
    output: str | Path,
    compiled: CompiledTopic | None = None,
) -> dict[str, int]:
    """Write `<output>` (affair_topics rows, NDJSON) and `<output>.topic.json` (topics row)."""
    results = []
    for line in Path(results_path).read_text("utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            if "model" in data:  # rows from `find` for affairs the API could not serve lack it
                results.append(ClassificationResult.model_validate(data))
    version = topic_version(topic, compiled)
    rows = affair_topic_rows(results, version)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    Path(str(out) + ".topic.json").write_text(
        json.dumps(topic_row(topic, compiled), ensure_ascii=False, indent=2), "utf-8")
    return {"rows": len(rows), "skipped_failed": len(results) - len(rows)}
