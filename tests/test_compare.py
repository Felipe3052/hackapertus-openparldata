import json
from pathlib import Path

from parltopic.evaluation.compare import compare_runs


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_compare_runs_uses_paired_examples_and_is_reproducible(tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    _write_jsonl(
        eval_path,
        [
            {"affair_id": "1", "label": True},
            {"affair_id": "2", "label": True},
            {"affair_id": "3", "label": False},
            {"affair_id": "4", "label": False},
        ],
    )
    _write_jsonl(
        baseline_path,
        [
            {"affair_id": "1", "status": "assigned", "prompt_version": "v1"},
            {"affair_id": "2", "status": "not_assigned", "prompt_version": "v1"},
            {"affair_id": "3", "status": "assigned", "prompt_version": "v1"},
            {"affair_id": "4", "status": "not_assigned", "prompt_version": "v1"},
        ],
    )
    _write_jsonl(
        candidate_path,
        [
            {"affair_id": str(index), "status": status, "prompt_version": "v2"}
            for index, status in enumerate(
                ["assigned", "assigned", "not_assigned", "not_assigned"], start=1
            )
        ],
    )

    first = compare_runs(eval_path, baseline_path, candidate_path, samples=100, seed=7)
    second = compare_runs(eval_path, baseline_path, candidate_path, samples=100, seed=7)

    assert first == second
    assert first["paired_examples"] == 4
    assert first["baseline"]["macro_f1"] == 0.5
    assert first["candidate"]["macro_f1"] == 1.0
    assert first["macro_f1_delta"] == 0.5
