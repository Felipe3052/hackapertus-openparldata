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


def content_id(value: Any) -> str:
    """Stable identity for an exact JSON snapshot; never include credentials."""
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def record_review(entry: dict, path: str | Path) -> dict:
    """Append an exact review event under a writer lock; keep prediction data unchanged."""
    from parltopic.evaluation.execution import exclusive_lock

    record = {**entry, "review_id": content_id(entry)}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(target.with_suffix(target.suffix + ".lock")):
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


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
    results: list[ClassificationResult], version: str, run_id: str = "legacy-unverified"
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
            "run_id": run_id,
            "prediction_id": content_id(result.model_dump(mode="json")),
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
            "evidence": [item.model_dump(mode="json") for item in result.evidence],
        })
    return rows


def export(
    results_path: str | Path,
    topic: TopicDefinition,
    output: str | Path,
    compiled: CompiledTopic | None = None,
    allow_unverified: bool = False,
) -> dict[str, int]:
    """Write `<output>` (affair_topics rows, NDJSON) and `<output>.topic.json` (topics row)."""
    results_path = Path(results_path)
    out = Path(output)
    if out.resolve() == results_path.resolve():
        raise ValueError("Export must not overwrite its input")
    targets = [out, Path(str(out) + ".topic.json"), Path(str(out) + ".run.json")]
    if any(path.exists() for path in targets):
        raise FileExistsError("Export target already exists; choose a new output path")
    manifest_path = results_path.with_suffix(results_path.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else None
    if manifest is None and not allow_unverified:
        raise ValueError("No run manifest; use --allow-unverified only for historical outputs")
    if manifest is not None:
        if TopicDefinition.model_validate(manifest.get("topic")) != topic:
            raise ValueError("Export topic differs from the classification run manifest")
    if compiled is not None and compiled.topic_id != topic.topic_id:
        raise ValueError("Compiled query belongs to another topic")
    results = []
    unstructured = 0
    for line in Path(results_path).read_text("utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            if "model" in data:  # rows from `find` for affairs the API could not serve lack it
                results.append(ClassificationResult.model_validate(data))
            else:
                if data.get("status") != "failed":
                    raise ValueError("Only explicitly failed source fetches may omit model fields")
                unstructured += 1
    if any(result.topic_id != topic.topic_id for result in results):
        raise ValueError("Prediction topic IDs do not match the export topic")
    ids = [result.affair_id for result in results]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate affair IDs in export input")
    for result in results:
        if result.status in {ClassificationStatus.ASSIGNED, ClassificationStatus.UNCERTAIN}:
            if not result.evidence:
                raise ValueError(f"Missing evidence for {result.affair_id}")
    provenance = {"manifest": manifest, "manifest_verified": manifest is not None,
                  "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest()}
    run_id = content_id(provenance)
    version = topic_version(topic, compiled)
    rows = affair_topic_rows(results, version, run_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    Path(str(out) + ".topic.json").write_text(
        json.dumps(topic_row(topic, compiled), ensure_ascii=False, indent=2), "utf-8")
    Path(str(out) + ".run.json").write_text(
        json.dumps({"run_id": run_id, **provenance}, ensure_ascii=False, indent=2), "utf-8")
    return {"rows": len(rows), "skipped_failed": len(results) - len(rows) + unstructured}
