"""Freeze a secondary validation panel and execute main without changing the main branch."""

import argparse
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from parltopic.evaluation.run import read_rows
from parltopic.ingestion.opendata_export import (
    available_languages,
    load_bodies,
    load_che_texts,
    read_csv,
    read_ndjson,
    strip_html,
    to_affair,
)


def build_panel(
    raw: Path, opened_dev: Path, training_report: Path, output: Path,
    positives_per_language: int = 10, negatives_per_language: int = 20, seed: int = 20261018,
) -> dict:
    if output.exists():
        raise ValueError("Use a new output path; confirmation panels are immutable")
    if min(positives_per_language, negatives_per_language) < 1:
        raise ValueError("Both class quotas must be positive")
    excluded = {int(row["affair_id"]) for row in read_rows(opened_dev)}
    split_ids = json.loads(training_report.read_text("utf-8"))["split_ids"]
    excluded.update(split_ids["train"])
    excluded.update(split_ids["calibration"])
    positive_ids = {int(row["openparldata_id"])
                    for row in read_csv(raw / "politmonitor_digitalisierung.csv")}

    def names(row):
        return {strip_html(row.get(f"title_{lang}")).casefold()
                for lang in available_languages(row)}

    blocked_titles = set()
    candidates = []
    for row in read_ndjson(raw / "affairs.ndjson.gz"):
        if row["id"] in excluded:
            blocked_titles.update(names(row))
        elif (row.get("begin_date") or "")[:4] == "2023":
            candidates.append(row)
    pools = {(lang, label): [] for lang in ("de", "fr", "it") for label in (True, False)}
    for row in candidates:
        languages = [lang for lang in available_languages(row) if lang in ("de", "fr", "it")]
        if not languages or names(row) & blocked_titles:
            continue
        digest = hashlib.sha256(str(row["id"]).encode()).hexdigest()
        language = languages[int(digest[:8], 16) % len(languages)]
        pools[(language, row["id"] in positive_ids)].append(row)
    rng = random.Random(seed)
    selected = []
    seen = set(blocked_titles)
    for (language, label), rows in pools.items():
        rows.sort(key=lambda row: row["id"])
        rng.shuffle(rows)
        quota = positives_per_language if label else negatives_per_language
        chosen = 0
        for row in rows:
            if names(row) & seen:
                continue
            selected.append((row, language, label))
            seen.update(names(row))
            chosen += 1
            if chosen == quota:
                break
        if chosen != quota:
            raise ValueError(f"Insufficient eligible {language}/{label} examples")
    bodies = load_bodies(raw)
    texts = load_che_texts(raw, [r["id"] for r, _, _ in selected if r["body_key"] == "CHE"])
    rows = []
    for row, language, label in selected:
        affair = to_affair(row, bodies.get(row["body_key"]), language,
                           texts.get(row["id"], {}).get(language, ""))
        if affair is None:
            raise ValueError(f"Selected affair {row['id']} cannot be normalized")
        rows.append({**affair.model_dump(mode="json"), "label": label,
                     "split": "secondary_validation_2023"})
    rng.shuffle(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                      encoding="utf-8")
    metadata = {
        "seed": seed, "year": 2023, "count": len(rows),
        "positive_quota_per_language": positives_per_language,
        "negative_quota_per_language": negatives_per_language,
        "excluded_affair_ids": sorted(excluded),
        "dataset_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "label_semantics": "positive-unlabeled proxy; not manually adjudicated",
        "purpose": "secondary validation of frozen E02; not for further rule tuning",
        "limitations": (
            "Exact-title filtering only; near-duplicates may remain. "
            "Some 2023 labels contributed to a different model's aggregate report."
        ),
        "input_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (opened_dev, training_report, raw / "affairs.ndjson.gz",
                                   raw / "politmonitor_digitalisierung.csv")},
    }
    output.with_suffix(".meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {key: value for key, value in metadata.items() if key != "excluded_affair_ids"}


MAIN_RUNNER = r'''
import hashlib, json, sys, time
from pathlib import Path
import parltopic
from parltopic.config import Settings
from parltopic.topics import load_topic
from parltopic.evaluation.run import run_classifier
eval_path, output, model, main_commit = sys.argv[1:5]
root = Path(parltopic.__file__).resolve().parent
if not root.is_relative_to(Path(sys.argv[5]).resolve()):
    raise RuntimeError("Refusing to load a package outside the isolated main snapshot")
settings = Settings(llm_name=model)
topic = load_topic(root.parents[1] / "configs/topics/digitalisation.yaml")
files = ["classification/service.py", "classification/keyword.py", "classification/prompts.py",
         "classification/apertus_client.py", "retrieval/chunker.py", "retrieval/bm25.py",
         "models.py"]
manifest = {
    "schema_version": 1, "main_commit": main_commit,
    "dataset_sha256": hashlib.sha256(Path(eval_path).read_bytes()).hexdigest(),
    "topic": topic.model_dump(mode="json"),
    "system_prompt": __import__("parltopic.classification.prompts", fromlist=["system_prompt"])
                     .system_prompt(settings.classifier_prompt_version),
    "settings": {k:getattr(settings,k) for k in (
        "llm_name", "llm_base_url", "classifier_prompt_version", "classifier_policy_version",
        "keyword_rescue_enabled", "chunk_size", "chunk_overlap", "retrieval_top_k")},
    "implementation_sha256": {name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                              for name in files},
}
# Own file: run_classifier (main since PR #1) writes its manifest to output + ".manifest.json".
path = Path(output + ".main.manifest.json")
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists() and json.loads(path.read_text("utf-8")) != manifest:
    raise ValueError("Run inputs changed; use a new output path")
if Path(output).exists() and not path.exists():
    raise ValueError("Existing results have no verified main manifest")
path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
started = time.perf_counter()
run_classifier(eval_path, topic, output, settings, workers=4)
Path(output + ".runtime.json").write_text(json.dumps({
    "wall_seconds_this_invocation": time.perf_counter()-started,
    "main_commit": main_commit, "workers": 4,
}), encoding="utf-8")
'''


def run_main(eval_path: Path, output: Path, model: str) -> None:
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    if branch in ("main", ""):
        raise ValueError("Run confirmation from the feature branch")
    main_ref = subprocess.check_output(["git", "rev-parse", "main"], text=True).strip()
    archive = subprocess.check_output(["git", "archive", main_ref, "src", "configs"])
    with tempfile.TemporaryDirectory(prefix="parltopic-main-") as directory:
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(directory, filter="data")
        environment = {**os.environ, "PYTHONPATH": str(Path(directory) / "src")}
        subprocess.run([sys.executable, "-c", MAIN_RUNNER, str(eval_path.resolve()),
                        str(output.resolve()), model, main_ref, directory],
                       env=environment, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "run-main"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="swiss-ai/Apertus-v1.5-70B")
    args = parser.parse_args()
    if args.mode == "build":
        report = build_panel(
            Path("data/raw"), Path("data/eval/e1_digitalisation_dev.jsonl"),
            Path("results/linear_baseline_v1/report.json"), args.dataset,
        )
        print(json.dumps(report, indent=2))
    elif args.output is None:
        parser.error("--output is required for run-main")
    else:
        run_main(args.dataset, args.output, args.model)
