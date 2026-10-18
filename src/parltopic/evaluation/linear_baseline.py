"""Optional, title-only character TF-IDF baseline with chronological model selection."""

import argparse
import hashlib
import json
import random
from dataclasses import asdict
from pathlib import Path

from parltopic.evaluation.metrics import binary_metrics
from parltopic.evaluation.run import read_rows, score_binary
from parltopic.ingestion.opendata_export import read_csv, read_ndjson, strip_html


def titles(record: dict) -> list[str]:
    return list(dict.fromkeys(
        text for lang in ("de", "fr", "it", "rm")
        if (text := strip_html(record.get(f"title_{lang}")))
    ))


def fit_baseline(raw_dir: Path, eval_path: Path, output_dir: Path, seed: int = 42) -> dict:
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    eval_rows = read_rows(eval_path)
    excluded_ids = {int(row["affair_id"]) for row in eval_rows}
    excluded_titles = {row["title"].strip().casefold() for row in eval_rows}
    positive_ids = {
        int(row["openparldata_id"])
        for row in read_csv(raw_dir / "politmonitor_digitalisierung.csv")
    }
    records = [
        row for row in read_ndjson(raw_dir / "affairs.ndjson.gz")
        if "2018" <= (row.get("begin_date") or "")[:4] <= "2023"
        and row["id"] not in excluded_ids and titles(row)
        and not any(t.casefold() in excluded_titles for t in titles(row))
    ]
    training_bodies = {
        row["body_key"] for row in records
        if row["id"] in positive_ids and row["begin_date"][:4] <= "2021"
    }
    groups = {"train": [], "calibration": [], "validation": []}
    seen_titles: set[str] = set()
    # Exact title duplicates are assigned only to their earliest eligible affair.
    for row in sorted(records, key=lambda r: (r["begin_date"], r["id"])):
        if row["body_key"] not in training_bodies:
            continue
        names = {t.casefold() for t in titles(row)}
        if names & seen_titles:
            continue
        seen_titles.update(names)
        year = row["begin_date"][:4]
        split = "train" if year <= "2021" else "calibration" if year == "2022" else "validation"
        groups[split].append(row)

    rng = random.Random(seed)
    sampled = {}
    for split, rows in groups.items():
        positives = [r for r in rows if r["id"] in positive_ids]
        negatives = [r for r in rows if r["id"] not in positive_ids]
        if not positives or not negatives:
            raise ValueError(f"Both proxy classes are required in {split}")
        sampled[split] = positives + rng.sample(negatives, min(len(negatives), 3 * len(positives)))
        rng.shuffle(sampled[split])

    train_text, train_labels, weights = [], [], []
    for row in sampled["train"]:
        names = titles(row)
        train_text.extend(names)
        train_labels.extend([row["id"] in positive_ids] * len(names))
        weights.extend([1 / len(names)] * len(names))
    vectorizer = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=2,
        max_features=120_000, sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(train_text)
    model = LogisticRegression(C=4, class_weight="balanced", max_iter=500, random_state=seed)
    model.fit(matrix, train_labels, sample_weight=weights)

    def probabilities(rows):
        # One language per held-out affair, selected without reference to its label.
        text = [titles(row)[int(row["id"]) % len(titles(row))] for row in rows]
        return model.predict_proba(vectorizer.transform(text))[:, 1].tolist()

    calibration = sampled["calibration"]
    calibration_labels = [r["id"] in positive_ids for r in calibration]
    scores = probabilities(calibration)
    thresholds = [i / 100 for i in range(10, 91, 5)]
    threshold = max(thresholds, key=lambda t: (
        binary_metrics(calibration_labels, [p >= t for p in scores]).macro_f1, t
    ))
    validation = sampled["validation"]
    validation_metrics = binary_metrics(
        [r["id"] in positive_ids for r in validation],
        [p >= threshold for p in probabilities(validation)],
    )
    eval_scores = model.predict_proba(vectorizer.transform([r["title"] for r in eval_rows]))[:, 1]
    predictions = {r["affair_id"]: bool(p >= threshold)
                   for r, p in zip(eval_rows, eval_scores, strict=True)}
    report = {
        "model": "char-tfidf-logistic-v1", "seed": seed, "sklearn_version": sklearn.__version__,
        "input_fields": ["title"], "threshold_selected_on_2022": threshold,
        "sampled_affairs": {split: len(rows) for split, rows in sampled.items()},
        "training_language_rows": len(train_text),
        "excluded_eval_ids": len(excluded_ids), "exact_title_deduplication": True,
        "validation_2023": asdict(validation_metrics),
        "opened_dev_diagnostic": score_binary(eval_path, predictions),
        "label_warning": (
            "Positive-unlabeled proxies; 1:3 sampled class ratio; no calibrated probabilities"
        ),
        "source_hashes": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (eval_path, raw_dir / "affairs.ndjson.gz",
                         raw_dir / "politmonitor_digitalisierung.csv")
        },
        "split_ids": {split: [r["id"] for r in rows] for split, rows in sampled.items()},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (output_dir / "predictions.jsonl").open("w", encoding="utf-8") as file:
        for row, probability in zip(eval_rows, eval_scores, strict=True):
            file.write(json.dumps({
                "affair_id": row["affair_id"], "model": "char-tfidf-logistic-v1",
                "prompt_version": "none", "classifier_version": "char-tfidf-logistic-v1",
                "status": "assigned" if predictions[row["affair_id"]] else "not_assigned",
                "score": float(probability),
            }) + "\n")
    return {k: v for k, v in report.items() if k != "split_ids"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(fit_baseline(args.raw_dir, args.eval_set, args.output_dir), indent=2))
