"""Strict offline jury evaluation; never imports or invokes an inference client."""

import argparse
import json
from collections import Counter
from pathlib import Path

from parltopic.evaluation.audit import audit_predictions, read_rows, sha, unique_index
from parltopic.models import ClassificationResult


def evaluate(gold_rows, prediction_rows):
    """Include unresolved cases in every subgroup's coverage denominator."""
    unique_index(gold_rows, "gold")
    for row in prediction_rows:
        result = ClassificationResult.model_validate(row)
        if result.status in {"assigned", "uncertain"} and not result.evidence:
            raise ValueError(f"Missing evidence for {result.affair_id}")
    overall = audit_predictions(gold_rows, prediction_rows)
    indexed = unique_index(prediction_rows, "predictions")
    groups = {}
    for field, values in (
        ("language", sorted({"de", "fr", "it"}
                            | {r.get("language") or "unknown" for r in gold_rows})),
        ("level", sorted({"federal", "cantonal", "municipal"}
                         | {r.get("level") or "unknown" for r in gold_rows})),
    ):
        for value in values:
            rows = [r for r in gold_rows if (r.get(field) or "unknown") == value]
            groups[f"{field}={value}"] = audit_predictions(
                rows, [indexed[r["affair_id"]] for r in rows if r["affair_id"] in indexed]
            )
    for summary in [overall, *groups.values()]:
        summary.pop("cases")
        # With only one gold class, do not advertise two-class discrimination metrics.
        summary["binary_quality_evaluable"] = (
            summary["metrics"]["tp"] + summary["metrics"]["fn"] > 0
            and summary["metrics"]["tn"] + summary["metrics"]["fp"] > 0
        )
        if not summary["binary_quality_evaluable"]:
            summary["metrics"]["classification_report"]["macro"] = None
    usage_complete = bool(prediction_rows) and all(
        r.get("input_tokens") is not None and r.get("output_tokens") is not None
        for r in prediction_rows
    )
    return {
        "overall": overall, "groups": groups,
        "tokens": {
            "complete": usage_complete,
            "input": sum(r.get("input_tokens") or 0 for r in prediction_rows),
            "output": sum(r.get("output_tokens") or 0 for r in prediction_rows),
        },
        "api_attempts": None, "retries": None, "wall_seconds": None,
        "cost": None,
        "measurement_note": (
            "Tokens are recorded usage; attempts, retries and wall time need a ledger."
        ),
    }


def references(root):
    data = root / "data/eval"
    inventory = {}
    for name in ("e4_dvs.jsonl", "e3_aps_sample.jsonl", "e3_aps_labels.jsonl"):
        path = data / name
        if not path.exists():
            inventory[name] = {"available": False}
            continue
        rows = read_rows(path)
        unique_index(rows, name)
        inventory[name] = {
            "available": True, "rows": len(rows), "sha256": sha(path),
            "languages": dict(Counter(r.get("language", "unspecified") for r in rows)),
            "levels": dict(Counter(r.get("level", "unspecified") for r in rows)),
        }
    labels = data / "e3_aps_labels.jsonl"
    if labels.exists():
        rows = read_rows(labels)
        inventory["aps_chapter_agreement"] = {
            "same_chapter": sum(r["felipe"]["chapter"] == r["josip"]["chapter"] for r in rows),
            "total": len(rows),
            "consensus_gold_available": False,
        }
    taxonomy = root / "configs/taxonomies/aps_topics.json"
    inventory["aps_taxonomy"] = {"available": taxonomy.exists()}
    if taxonomy.exists():
        topics = json.loads(taxonomy.read_text("utf-8"))
        inventory["aps_taxonomy"].update(
            topics=len(topics), chapters=len({t["chapter_code"] for t in topics}),
            sha256=sha(taxonomy),
        )
    inventory["warning"] = (
        "DVS is positive-only: precision and binary macro-F1 are not established. "
        "APS annotators disagree; no adjudicated consensus or APS model predictions supplied. "
        "Curia Vista subject labels are not APS labels."
    )
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    report = evaluate(read_rows(args.eval_set), read_rows(args.results))
    manifest = args.results.with_suffix(args.results.suffix + ".manifest.json")
    report.update(
        schema_version=1,
        provenance={"dataset": str(args.eval_set), "dataset_sha256": sha(args.eval_set),
                    "predictions": str(args.results), "predictions_sha256": sha(args.results),
                    "evaluator_sha256": sha(__file__),
                    "manifest": (json.loads(manifest.read_text("utf-8"))
                                 if manifest.exists() else None)},
        references=references(args.root),
        limitations=["Metrics are selective on decisive cases; inspect subgroup coverage.",
                     "E1 labels contain untagged proxy negatives and an opened validation split.",
                     "Rescoring historical outputs is not a measurement of current code quality."],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
