"""Shared input validation for scoring; preserves unresolved outcomes explicitly."""

from parltopic.models import ClassificationStatus


def unique_rows(rows, name):
    indexed = {}
    for row in rows:
        identity = row.get("affair_id")
        if type(identity) is not str or not identity.strip() or identity != identity.strip():
            raise ValueError(f"{name}: affair_id must be a nonempty, unpadded string")
        if identity in indexed:
            raise ValueError(f"Duplicate {name} IDs: {identity}")
        indexed[identity] = row
    return indexed


def validate_gold(rows):
    indexed = unique_rows(rows, "gold")
    for identity, row in indexed.items():
        if type(row.get("label")) is not bool:
            raise ValueError(f"Gold label must be boolean for {identity}")
    return indexed


def validate_results(gold_rows, result_rows):
    gold = validate_gold(gold_rows)
    results = unique_rows(result_rows, "result")
    unknown = set(results) - set(gold)
    if unknown:
        raise ValueError(f"Result IDs not present in evaluation set: {sorted(unknown)[:10]}")
    allowed = {status.value for status in ClassificationStatus}
    for identity, row in results.items():
        if row.get("status") not in allowed:
            raise ValueError(f"Unknown result status for {identity}: {row.get('status')}")
        if "label" in row and (
            type(row["label"]) is not bool or row["label"] != gold[identity]["label"]
        ):
            raise ValueError(f"Prediction-embedded label differs from gold for {identity}")
    for field in ("model", "prompt_version", "classifier_version"):
        if len({row.get(field) for row in result_rows}) > 1:
            raise ValueError("A scored run must contain exactly one model, prompt, "
                             "and classifier version")
    return results, set(gold) - set(results)
