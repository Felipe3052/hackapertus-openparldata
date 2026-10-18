import csv
import gzip
import json
from pathlib import Path

import pytest

from parltopic.evaluation.linear_baseline import fit_baseline


def test_training_excludes_eval_ids_and_titles_and_uses_chronological_splits(tmp_path: Path):
    pytest.importorskip("sklearn")
    records = []
    positives = []
    for year in (2019, 2022, 2023):
        for index in range(12):
            affair_id = year * 100 + index
            positive = index < 3
            if positive:
                positives.append(affair_id)
            records.append({
                "id": affair_id, "begin_date": f"{year}-01-01", "body_key": "CHE",
                "title_de": f"{'Digital online' if positive else 'Strassenbau'} {year} {index}",
            })
    held_out = records[0]
    duplicate = {**held_out, "id": 999}
    records.append(duplicate)
    with gzip.open(tmp_path / "affairs.ndjson.gz", "wt", encoding="utf-8") as file:
        for row in records:
            file.write(json.dumps(row) + "\n")
    with (tmp_path / "politmonitor_digitalisierung.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["openparldata_id"])
        writer.writerows([[i] for i in positives])
    evaluation = tmp_path / "eval.jsonl"
    evaluation.write_text(json.dumps({
        "affair_id": str(held_out["id"]), "title": held_out["title_de"],
        "label": True, "language": "de", "level": "federal",
    }) + "\n", encoding="utf-8")
    output = tmp_path / "results"
    fit_baseline(tmp_path, evaluation, output)
    report = json.loads((output / "report.json").read_text("utf-8"))
    split_ids = report["split_ids"]
    assert not ({held_out["id"], 999} & set(sum(split_ids.values(), [])))
    assert all(i // 100 == 2019 for i in split_ids["train"])
    assert all(i // 100 == 2022 for i in split_ids["calibration"])
    assert all(i // 100 == 2023 for i in split_ids["validation"])
    assert report["validation_2023"]["count"] > 0
    assert len((output / "predictions.jsonl").read_text("utf-8").splitlines()) == 1
