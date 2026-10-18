import csv
import gzip
import json
import subprocess
from pathlib import Path

import pytest

from parltopic.evaluation.confirmation import MAIN_RUNNER, build_panel, run_main


def test_panel_is_immutable_and_excludes_development_training_and_duplicate_titles(tmp_path: Path):
    rows = []
    positives = []
    for index, language in enumerate(("de", "fr", "it")):
        for label in (True, False):
            affair_id = 100 + index * 10 + int(label)
            rows.append({"id": affair_id, "body_key": "CHE", "begin_date": "2023-04-01",
                         f"title_{language}": f"Title {language} {label}"})
            if label:
                positives.append(affair_id)
    rows.extend([
        {"id": 900, "body_key": "CHE", "begin_date": "2023-01-01", "title_de": "Training"},
        {"id": 901, "body_key": "CHE", "begin_date": "2023-01-01", "title_de": "Calibration"},
        {"id": 902, "body_key": "CHE", "begin_date": "2023-01-01", "title_de": "Training"},
        {"id": 999, "body_key": "CHE", "begin_date": "2023-01-01", "title_de": "Development"},
    ])
    for name, values in [("affairs.ndjson.gz", rows), ("texts_CHE.ndjson.gz", []),
                         ("bodies.ndjson.gz", [{"body_key": "CHE", "type": "country"}])]:
        with gzip.open(tmp_path / name, "wt", encoding="utf-8") as file:
            file.write("".join(json.dumps(row) + "\n" for row in values))
    with (tmp_path / "politmonitor_digitalisierung.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["openparldata_id"])
        writer.writerows([[affair_id] for affair_id in positives])
    dev = tmp_path / "dev.jsonl"
    dev.write_text('{"affair_id":"999"}\n')
    training = tmp_path / "training.json"
    training.write_text(json.dumps({"split_ids": {"train": [900], "calibration": [901]}}))
    output = tmp_path / "panel.jsonl"
    metadata = build_panel(tmp_path, dev, training, output, 1, 1)
    selected = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(selected) == metadata["count"] == 6
    assert not {"900", "901", "902", "999"} & {row["affair_id"] for row in selected}
    assert sum(row["label"] for row in selected) == 3
    with pytest.raises(ValueError, match="immutable"):
        build_panel(tmp_path, dev, training, output, 1, 1)


def test_isolated_main_runner_source_compiles():
    compile(MAIN_RUNNER, "isolated_main", "exec")


def test_archived_main_import_and_zero_api_smoke(tmp_path: Path):
    try:
        before = subprocess.check_output(["git", "rev-parse", "main"], text=True).strip()
        branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    except subprocess.CalledProcessError:
        pytest.skip("An available main ref is required for the isolated integration check")
    if branch in ("", "main"):
        pytest.skip("The isolated runner is restricted to a feature branch")
    dataset = tmp_path / "synthetic-smoke.jsonl"
    dataset.write_text('{"affair_id":"smoke","title":"Digitalisierung","language":"de"}\n')
    output = tmp_path / "smoke-results.jsonl"
    run_main(dataset, output, "unused-rule-only")
    result = json.loads(output.read_text())
    assert result["status"] == "assigned"
    assert result["input_tokens"] == 0
    manifest = json.loads(output.with_suffix(".jsonl.main.manifest.json").read_text())
    assert manifest["main_commit"] == before
    assert subprocess.check_output(["git", "rev-parse", "main"], text=True).strip() == before
