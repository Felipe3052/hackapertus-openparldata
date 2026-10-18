import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from parltopic.evaluation.execution import checkpointed_run, exclusive_lock
from parltopic.models import ClassificationResult


def dataset(tmp_path, count=8):
    path = tmp_path / "inputs.jsonl"
    path.write_text("\n".join(json.dumps({"affair_id": str(i), "title": "Synthetic fixture"})
                              for i in range(count)), encoding="utf-8")
    return path


def decision(affair):
    return ClassificationResult(affair_id=affair.affair_id, topic_id="fixture",
                                status="not_assigned", language="de", model="offline-fixture")


def test_short_resume_skips_committed_work_and_refuses_changed_manifest(tmp_path):
    source, out = dataset(tmp_path), tmp_path / "results.jsonl"
    calls = []

    def classify(affair):
        calls.append(affair.affair_id)
        return decision(affair)

    checkpointed_run(source, out, {"topic": "fixture"}, classify, workers=2, limit=3)
    assert len(calls) == 3
    checkpointed_run(source, out, {"topic": "fixture"}, classify, workers=2)
    assert len(calls) == len(set(calls)) == 8
    before = out.read_bytes()
    checkpointed_run(source, out, {"topic": "fixture"}, classify, workers=2)
    assert out.read_bytes() == before and len(calls) == 8
    with pytest.raises(ValueError, match="changed"):
        checkpointed_run(source, out, {"topic": "different"}, classify)
    assert out.read_bytes() == before


def test_interruption_keeps_committed_results_and_valid_snapshot(tmp_path):
    source, out = dataset(tmp_path), tmp_path / "results.jsonl"

    def fail_after_first(affair):
        if affair.affair_id == "2":
            raise RuntimeError("Simulated worker interruption")
        return decision(affair)

    with pytest.raises(RuntimeError, match="interruption"):
        checkpointed_run(source, out, {}, fail_after_first, workers=1)
    committed = {json.loads(line)["affair_id"] for line in out.read_text().splitlines()}
    assert "0" in committed
    calls = []

    def resume(affair):
        calls.append(affair.affair_id)
        return decision(affair)

    checkpointed_run(source, out, {}, resume, workers=1)
    assert not committed.intersection(calls)
    assert len(out.read_text().splitlines()) == 8


def test_exclusive_run_lock_rejects_second_writer(tmp_path):
    path = tmp_path / "run.lock"
    with exclusive_lock(path), pytest.raises(OSError), exclusive_lock(path):
        pass


def test_preflight_duplicate_ids_admits_no_work(tmp_path):
    path = dataset(tmp_path, count=1)
    path.write_text((path.read_text() + "\n") * 2)
    calls = []
    with pytest.raises(ValueError, match="duplicate"):
        checkpointed_run(path, tmp_path / "out", {}, lambda affair: calls.append(affair))
    assert not calls


def test_real_process_termination_preserves_journal_and_releases_lock(tmp_path):
    source, out = dataset(tmp_path), tmp_path / "killed.jsonl"
    program = """
import sys,time
from parltopic.evaluation.execution import checkpointed_run
from parltopic.models import ClassificationResult
def classify(affair):
    if affair.affair_id != '0':
        time.sleep(30)
    return ClassificationResult(affair_id=affair.affair_id, topic_id='fixture',
                                status='not_assigned', language='de', model='fixture')
checkpointed_run(sys.argv[1], sys.argv[2], {}, classify, workers=1)
"""
    child = subprocess.Popen([sys.executable, "-c", program, str(source), str(out)])
    journal = out.with_suffix(".jsonl.checkpoint.sqlite")
    try:
        deadline = time.monotonic() + 8
        committed = False
        while time.monotonic() < deadline and child.poll() is None:
            if journal.exists():
                try:
                    with sqlite3.connect(journal) as connection:
                        committed = connection.execute("SELECT count(*) FROM results").fetchone()[0]
                except sqlite3.OperationalError:
                    pass
            if committed:
                break
            time.sleep(.05)
        assert committed == 1
    finally:
        child.terminate()
        child.wait(timeout=5)
    calls = []

    def resume(affair):
        calls.append(affair.affair_id)
        return decision(affair)

    checkpointed_run(source, out, {}, resume, workers=1)
    assert "0" not in calls
    assert len(calls) == 7
    assert len(out.read_text().splitlines()) == 8


def test_interrupted_manifest_publish_preserves_previous_provenance(tmp_path, monkeypatch):
    source, out = dataset(tmp_path), tmp_path / "out.jsonl"
    checkpointed_run(source, out, {}, decision, workers=1, limit=1)
    manifest = out.with_suffix(".jsonl.manifest.json")
    before = manifest.read_bytes()
    original_replace = Path.replace

    def interrupt(path, target):
        if path.name.endswith(".manifest.json.part"):
            raise RuntimeError("Simulated manifest publication interruption")
        return original_replace(path, target)

    with monkeypatch.context() as context:
        context.setattr(Path, "replace", interrupt)
        with pytest.raises(RuntimeError, match="publication"):
            checkpointed_run(source, out, {}, decision, workers=1)
    assert manifest.read_bytes() == before
    checkpointed_run(source, out, {}, decision, workers=1)
    assert len(out.read_text().splitlines()) == 8
