"""Bounded execution with a local SQLite journal and atomic JSONL snapshots."""

import json
import os
import sqlite3
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from itertools import islice
from pathlib import Path

from parltopic.models import Affair, ClassificationResult


@contextmanager
def exclusive_lock(path):
    with Path(path).open("a+b") as stream:
        try:
            import fcntl
        except ImportError:
            import msvcrt

            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def iter_rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def checkpointed_run(dataset, output, manifest, classify, workers=8, limit=None, retry_failed=True):
    if workers < 1 or workers > 32:
        raise ValueError("workers must be between 1 and 32")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    out = Path(output)
    if out.resolve() == Path(dataset).resolve():
        raise ValueError("Results must not overwrite the input dataset")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = out.with_suffix(out.suffix + ".manifest.json")
    journal_path = out.with_suffix(out.suffix + ".checkpoint.sqlite")
    serialized_manifest = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    with exclusive_lock(out.with_suffix(out.suffix + ".lock")):
        if out.exists() and out.stat().st_size:
            if not manifest_path.exists():
                raise ValueError(
                    "Existing results have no provenance manifest; use a new output path"
                )
            if json.loads(manifest_path.read_text("utf-8")) != manifest:
                raise ValueError(
                    "Run inputs changed; use a new output path to avoid mixing results"
                )
        # Preflight all source IDs and records before admitting any inference work.
        identities = set()
        for row in iter_rows(dataset):
            affair = Affair.model_validate(row)
            if not affair.affair_id.strip() or affair.affair_id in identities:
                raise ValueError(f"Missing or duplicate input affair_id: {affair.affair_id}")
            identities.add(affair.affair_id)
        with sqlite3.connect(journal_path) as journal:
            journal.execute("PRAGMA synchronous=FULL")
            journal.execute("CREATE TABLE IF NOT EXISTS metadata (manifest TEXT NOT NULL)")
            journal.execute("CREATE TABLE IF NOT EXISTS results "
                            "(affair_id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                            "payload TEXT NOT NULL)")
            previous = journal.execute("SELECT manifest FROM metadata").fetchone()
            if previous and previous[0] != serialized_manifest:
                raise ValueError("Run inputs changed; checkpoint belongs to another configuration")
            if not previous:
                journal.execute("INSERT INTO metadata VALUES (?)", (serialized_manifest,))
                if out.exists():
                    imported = set()
                    for row in iter_rows(out):
                        result = ClassificationResult.model_validate(row)
                        if result.affair_id not in identities or result.affair_id in imported:
                            raise ValueError("Existing results have duplicate or foreign IDs")
                        imported.add(result.affair_id)
                        journal.execute("INSERT INTO results VALUES (?, ?, ?)",
                                        (result.affair_id, result.status.value,
                                         result.model_dump_json()))
                journal.commit()
            manifest_temporary = manifest_path.with_suffix(manifest_path.suffix + ".part")
            with manifest_temporary.open("w", encoding="utf-8") as stream:
                stream.write(serialized_manifest + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            manifest_temporary.replace(manifest_path)

            def todo():
                rows = iter_rows(dataset)
                if limit is not None:
                    rows = islice(rows, limit)
                for row in rows:
                    status = journal.execute("SELECT status FROM results WHERE affair_id=?",
                                             (row["affair_id"],)).fetchone()
                    if status is None or (retry_failed and status[0] == "failed"):
                        yield Affair.model_validate(row)

            try:
                iterator = iter(todo())
                with ThreadPoolExecutor(workers) as pool:
                    pending = {}
                    exhausted = False
                    while pending or not exhausted:
                        while not exhausted and len(pending) < workers * 2:
                            affair = next(iterator, None)
                            if affair is None:
                                exhausted = True
                            else:
                                pending[pool.submit(classify, affair)] = affair.affair_id
                        if not pending:
                            break
                        finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in finished:
                            identity = pending.pop(future)
                            result = future.result()
                            if result.affair_id != identity:
                                raise ValueError("Classifier returned the wrong affair_id")
                            journal.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?)",
                                            (identity, result.status.value,
                                             result.model_dump_json()))
                            journal.commit()  # Durable per result, including technical failures.
            finally:
                temporary = out.with_suffix(out.suffix + ".part")
                with temporary.open("w", encoding="utf-8") as stream:
                    for (payload,) in journal.execute("SELECT payload FROM results ORDER BY rowid"):
                        stream.write(payload + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(out)
    return out
