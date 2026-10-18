"""Offline independent evaluation audit. Never calls an inference client."""

import argparse
import csv
import gzip
import hashlib
import html
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from unittest.mock import patch

DECISIVE = {"assigned", "not_assigned"}
STATUSES = DECISIVE | {"failed", "uncertain", "not_evaluable"}


def read_rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_index(rows, name):
    result = {}
    for row in rows:
        identity = row.get("affair_id")
        if type(identity) is not str or not identity.strip() or identity != identity.strip():
            raise ValueError(f"{name}: affair_id must be a nonempty, unpadded string")
        if identity in result:
            raise ValueError(f"{name}: duplicate affair_id {identity}")
        result[identity] = row
    return result


def independent_metrics(pairs):
    """Calculate from four cells directly; do not call the project's metric implementation."""
    if any(type(y) is not bool or type(p) is not bool for y, p in pairs):
        raise ValueError("Metric inputs must be actual boolean labels and predictions")
    tp = len([1 for y, p in pairs if y and p])
    fp = len([1 for y, p in pairs if not y and p])
    fn = len([1 for y, p in pairs if y and not p])
    tn = len([1 for y, p in pairs if not y and not p])
    n = tp + fp + fn + tn

    def divide(numerator, denominator):
        return numerator / denominator if denominator else 0.0

    positive = {"precision": divide(tp, tp + fp), "recall": divide(tp, tp + fn),
                "f1": divide(2 * tp, 2 * tp + fp + fn), "support": tp + fn}
    negative = {"precision": divide(tn, tn + fn), "recall": divide(tn, tn + fp),
                "f1": divide(2 * tn, 2 * tn + fp + fn), "support": tn + fp}
    macro = {k: (positive[k] + negative[k]) / 2 for k in ("precision", "recall", "f1")}
    weighted = {k: divide(positive[k] * positive["support"]
                         + negative[k] * negative["support"], n)
                for k in ("precision", "recall", "f1")}
    accuracy = divide(tp + tn, n)
    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "matrix_actual_by_predicted_false_true": [[tn, fp], [fn, tp]],
        "classification_report": {"negative": negative, "positive": positive,
                                  "macro": {**macro, "support": n},
                                  "weighted": {**weighted, "support": n},
                                  "micro": {k: accuracy for k in ("precision", "recall", "f1")},
                                  "accuracy": accuracy},
        "zero_division_policy": "0 for undefined per-class divisions; both classes fixed",
        "undefined": [name for name, denominator in (
            ("positive_precision", tp + fp), ("positive_recall", tp + fn),
            ("negative_precision", tn + fn), ("negative_recall", tn + fp),
            ("accuracy", n),
        ) if denominator == 0],
    }


def audit_predictions(gold_rows, prediction_rows):
    gold, predictions = unique_index(gold_rows, "gold"), unique_index(prediction_rows, "prediction")
    for row in gold_rows:
        if type(row.get("label")) is not bool:
            raise ValueError(f"gold: missing/null/nonboolean label for {row['affair_id']}")
    unknown = set(predictions) - set(gold)
    if unknown:
        raise ValueError(f"Predictions have unknown IDs: {sorted(unknown)}")
    pairs, cases, statuses = [], [], Counter()
    for identity, row in gold.items():
        prediction = predictions.get(identity)
        status = "missing"
        if prediction is not None:
            result = prediction.get("result", prediction)
            if "affair_id" in result and result["affair_id"] != identity:
                raise ValueError(f"Nested result ID mismatch for {identity}")
            if "label" in prediction and (
                type(prediction["label"]) is not bool or prediction["label"] != row["label"]
            ):
                raise ValueError(f"Prediction-embedded label mismatch for {identity}")
            status = result.get("status")
            if status not in STATUSES:
                raise ValueError(f"Unknown prediction status for {identity}: {status}")
        statuses[status] += 1
        predicted = (status == "assigned") if status in DECISIVE else None
        cell = None
        if predicted is not None:
            pairs.append((row["label"], predicted))
            cell = ("TP" if predicted else "FN") if row["label"] else ("FP" if predicted else "TN")
        cases.append({"affair_id": identity, "label": row["label"], "status": status,
                      "prediction": predicted, "cell": cell})
    return {
        "expected": len(gold), "received": len(predictions), "decisive": len(pairs),
        "coverage": len(pairs) / len(gold) if gold else None,
        "status_counts": dict(statuses), "metrics": independent_metrics(pairs), "cases": cases,
    }


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def duplicates(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        value = normalize(key(row))
        if value:
            grouped[value].append(row["affair_id"])
    return [ids for ids in grouped.values() if len(ids) > 1]


def near_titles(left, right, within=False, threshold=.9):
    matches = []
    for i, a in enumerate(left):
        ta = normalize(a["title"])
        if len(ta) < 20 or len(re.findall(r"\w+", ta)) < 5:
            continue
        candidates = right[i + 1:] if within else right
        for b in candidates:
            tb = normalize(b["title"])
            if a["affair_id"] == b["affair_id"] or ta == tb or len(tb) < 20:
                continue
            if min(len(ta), len(tb)) / max(len(ta), len(tb)) < .8:
                continue
            ratio = SequenceMatcher(None, ta, tb, autojunk=False).ratio()
            if ratio >= threshold:
                matches.append({"left": a["affair_id"], "right": b["affair_id"],
                                "ratio": ratio, "left_title": a["title"],
                                "right_title": b["title"],
                                "left_date": a.get("date"), "right_date": b.get("date"),
                                "left_parliament": a.get("parliament"),
                                "right_parliament": b.get("parliament")})
    return matches


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    center = (p + z*z / (2*total)) / (1 + z*z / total)
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1 + z*z / total)
    return [max(0, center-radius), min(1, center+radius)]


def legacy_validation_probes():
    """Synthetic malformed inputs diagnose validators; never contribute to real metrics."""
    from parltopic.evaluation.run import _validated_results, score_binary

    def score(rows, predictions):
        with patch("parltopic.evaluation.run.read_rows", return_value=rows):
            result = score_binary("not-a-file", predictions)
        return {"coverage": result["coverage"], "all": result.get("all")}

    row = {"affair_id": "synthetic", "label": True, "language": "de", "level": "federal"}
    return {
        "purpose": "Malformed-fixture diagnostics only; no real labels or predictions changed",
        "null_label_treated_as_negative": score([{**row, "label": None}], {"synthetic": False}),
        "string_false_treated_as_positive": score([{**row, "label": "false"}], {"synthetic": True}),
        "duplicate_gold_counted_twice": score([row, row], {"synthetic": True}),
        "foreign_prediction_silently_ignored": score([row], {"foreign": False}),
        "unknown_status_accepted_by_validator": bool(_validated_results(
            [row], [{"affair_id": "synthetic", "status": "invalid-status"}]
        )[0]),
    }


def run_audit(root):
    dataset = Path("data/eval/e1_digitalisation_dev.jsonl")
    test_path = Path("data/eval/e1_digitalisation_test.jsonl")
    source_csv = Path("data/raw/politmonitor_digitalisierung.csv")
    panel = read_rows(root / "panel.jsonl")
    dev, temporal = read_rows(dataset), read_rows(test_path)
    # Do not score or tune on later-split labels. Only ID/title/date overlap is examined.
    dev_index, test_index = unique_index(dev, "dev"), unique_index(temporal, "temporal")
    panel_index = unique_index(panel, "panel")
    for identity, row in panel_index.items():
        if identity not in dev_index or any(row[k] != dev_index[identity][k] for k in (
            "title", "text", "documents", "language", "date", "label"
        )):
            raise ValueError(f"Panel differs from frozen dev source for {identity}")
    with source_csv.open(encoding="utf-8-sig", newline="") as stream:
        tag_rows = list(csv.DictReader(stream))
    positive_ids = {str(r["openparldata_id"]) for r in tag_rows}
    variants = {str(size): audit_predictions(panel, read_rows(root / f"batch{size}.jsonl"))
                for size in (1, 3, 5)}
    cases = variants["1"]["cases"]
    predictions = unique_index(read_rows(root / "batch1.jsonl"), "single")
    for case in cases:
        row = panel_index[case["affair_id"]]
        case.update({"language": row["language"], "title": row["title"], "date": row["date"],
                     "source_has_positive_tag": case["affair_id"] in positive_ids,
                     "route": "rule" if predictions[case["affair_id"]]["result"].get(
                         "input_tokens") == 0 else "llm",
                     "body_chars": len(row["text"]), "document_count": len(row["documents"])})
    other_dev = [r for r in dev if r["affair_id"] not in panel_index]
    normalized_titles = {normalize(r["title"]) for r in panel}
    def cross(rows):
        return [{"panel_id": p["affair_id"], "other_id": q["affair_id"], "title": p["title"]}
                for p in panel for q in rows if normalize(p["title"]) == normalize(q["title"])]

    temporal_titles = defaultdict(list)
    for row in temporal:
        temporal_titles[normalize(row["title"])].append(row["affair_id"])
    exact_dev_temporal = [{"dev_id": r["affair_id"], "later_ids": temporal_titles[
        normalize(r["title"])], "title": r["title"]} for r in dev
        if normalize(r["title"]) and normalize(r["title"]) in temporal_titles]
    linear_path = Path("results/linear_baseline_v1/report.json")
    linear = json.loads(linear_path.read_text("utf-8"))
    split_ids = {k: {str(i) for i in ids} for k, ids in linear["split_ids"].items()}
    wanted = set().union(*split_ids.values())
    linear_title_matches = []
    with gzip.open("data/raw/affairs.ndjson.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if str(record["id"]) not in wanted:
                continue
            for language in ("de", "fr", "it", "rm"):
                # Equivalent simple HTML cleanup for title-overlap diagnostics only.
                text = html.unescape(re.sub(
                    r"<[^>]+>", "", record.get(f"title_{language}") or ""
                ))
                if normalize(text) in normalized_titles:
                    linear_title_matches.append({"id": str(record["id"]), "title": text})
    m = variants["1"]["metrics"]
    sliced = {}
    for field, values in (("language", sorted({r["language"] for r in cases})),
                          ("route", ["rule", "llm"])):
        for value in values:
            selected = [r for r in cases if r[field] == value]
            sliced[f"{field}={value}"] = independent_metrics([
                (r["label"], r["prediction"]) for r in selected if r["prediction"] is not None
            ])
    published = json.loads(Path("docs/results/batching-20261018-summary.json").read_text("utf-8"))
    published_checks = {}
    for size, variant in variants.items():
        actual = variant["metrics"]["classification_report"]
        old = published["variants"][size]["quality"]
        published_checks[size] = {
            "macro_f1": math.isclose(actual["macro"]["f1"], old["macro_f1"], abs_tol=1e-12),
            "positive_precision": math.isclose(actual["positive"]["precision"], old["precision"],
                                                abs_tol=1e-12),
            "positive_recall": math.isclose(actual["positive"]["recall"], old["recall"],
                                             abs_tol=1e-12),
            "coverage": math.isclose(variant["coverage"], old["coverage"], abs_tol=1e-12),
        }
    report = {
        "api_calls": 0, "variants": variants, "slices": sliced,
        "legacy_input_validation_probes": legacy_validation_probes(),
        "published_score_checks": published_checks,
        "source_label_check": {
            "tag_rows": len(tag_rows), "unique_tagged_ids": len(positive_ids),
            "positive_labels": sum(r["label"] for r in panel),
            "negative_proxy_labels": sum(not r["label"] for r in panel),
            "panel_label_membership_mismatches": [r["affair_id"] for r in panel
                if r["label"] != (r["affair_id"] in positive_ids)],
        },
        "overlap": {
            "nested_parent100": len(set(panel_index) & set(unique_index(
                read_rows(Path("results/performance-20261018/panel.jsonl")), "parent100"))),
            "nested_dev450": len(set(panel_index) & set(dev_index)),
            "panel_vs_temporal1200_ids": sorted(set(panel_index) & set(test_index)),
            "dev450_vs_temporal1200_ids": sorted(set(dev_index) & set(test_index)),
            "exact_titles_dev450_vs_temporal1200": exact_dev_temporal,
            "exact_titles_within_dev450": duplicates(dev, lambda r: r["title"]),
            "exact_titles_within_temporal1200": duplicates(temporal, lambda r: r["title"]),
            "linear_split_ids": {k: sorted(set(panel_index) & ids) for k, ids in split_ids.items()},
            "linear_split_translated_title_matches": linear_title_matches,
            "exact_title_within30": duplicates(panel, lambda r: r["title"]),
            "exact_fulltext_within30": duplicates(panel, lambda r: r["title"] + "\n" + r["text"]
                + "\n" + "\n".join(d["text"] for d in r["documents"])),
            "exact_body_within30": duplicates(panel, lambda r: r["text"]),
            "exact_titles_panel_vs_other_dev": cross(other_dev),
            "exact_titles_panel_vs_temporal": cross(temporal),
            "near_titles_within30": near_titles(panel, panel, within=True),
            "near_titles_panel_vs_other_dev": near_titles(panel, other_dev),
            "near_titles_panel_vs_temporal": near_titles(panel, temporal),
        },
        "wilson95_conditional_on_proxy_labels": {
            "positive_precision": wilson(m["tp"], m["tp"] + m["fp"]),
            "positive_recall": wilson(m["tp"], m["tp"] + m["fn"]),
            "accuracy": wilson(m["tp"] + m["tn"], m["n"]),
        },
        "source_sha256": {str(p): sha(p) for p in [dataset, test_path, source_csv, linear_path,
            Path("data/eval/meta.json"), Path(__file__),
            root / "panel.jsonl", root / "batch1.jsonl", root / "batch3.jsonl",
            root / "batch5.jsonl",
            root / "manifest.json", Path("docs/results/batching-20261018-summary.json"),
            Path("data/raw/affairs.ndjson.gz")]},
    }
    return report


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("results/batching-20261018"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_audit(args.run_dir)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"metrics": report["variants"]["1"]["metrics"],
                      "overlap": report["overlap"],
                      "source_label_check": report["source_label_check"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
