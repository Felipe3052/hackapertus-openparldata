"""Bounded live benchmark; instruments the existing service without changing its policy.

prepare -> smoke (<=10 HTTP attempts) -> complete (<=100 cumulative attempts).
Artifacts are immutable by phase. No automatic reruns or paid warmups.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from parltopic.classification.apertus_client import ApertusClient
from parltopic.classification.keyword import first_keyword_hit
from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.evaluation.metrics import binary_metrics
from parltopic.evaluation.run import _run_manifest, read_rows
from parltopic.models import Affair
from parltopic.retrieval.chunker import chunk_affair
from parltopic.topics import load_topic


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def branch():
    value = subprocess.check_output(
        ["git", "branch", "--show-current"], text=True
    ).strip()
    if not value or value in {"main", "master"}:
        raise RuntimeError("A feature branch is required")
    return value


def historical_settings():
    """Keep the original unpooled control explicit after production enables connection reuse."""
    return get_settings().model_copy(update={
        "llm_connection_reuse": False, "llm_requests_per_minute": 0, "llm_batch_size": 1,
    })


def gate(row, settings, topic):
    affair = Affair.model_validate(row)
    segments = chunk_affair(affair, settings.chunk_size, settings.chunk_overlap)
    eligible = segments if settings.keyword_document_gate_enabled else [
        s for s in segments if s.document_id is None
    ]
    return bool(settings.keyword_rescue_enabled and (
        first_keyword_hit(eligible, topic)
        or (affair.title.strip() and first_keyword_hit(
            [segments[0]], topic, terms=topic.title_synonyms
        ))
    ))


def select_panel(rows, settings, topic, seed=20261018):
    """Proportional language/label/gate quotas; systematic length sampling within strata."""
    if len(rows) < 100 or len({r["affair_id"] for r in rows}) != len(rows):
        raise ValueError("Need >=100 unique real affairs")
    strata = defaultdict(list)
    for row in rows:
        strata[(row["language"], bool(row["label"]), gate(row, settings, topic))].append(row)
    keys = sorted(strata)
    exact = {k: 100 * len(strata[k]) / len(rows) for k in keys}
    quotas = {k: math.floor(exact[k]) for k in keys}
    for key in sorted(keys, key=lambda k: (-(exact[k] - quotas[k]), k))[
        :100 - sum(quotas.values())
    ]:
        quotas[key] += 1
    rng = random.Random(seed)
    panel, counts = [], Counter()
    for key in keys:
        ordered = sorted(strata[key], key=lambda r: (
            len(Affair.model_validate(r).combined_text()), str(r["affair_id"])
        ))
        count = quotas[key]
        if not count:
            continue
        offset = rng.random()
        chosen = [ordered[int((i + offset) * len(ordered) / count)] for i in range(count)]
        for i in range(0, count, 2):
            pair = chosen[i:i + 2]
            rng.shuffle(pair)
            for row in pair:
                arm = min(("sequential", "parallel"), key=lambda a: counts[a])
                panel.append({**row, "benchmark_arm": arm, "expected_gate": key[2]})
                counts[arm] += 1
    assert counts == {"sequential": 50, "parallel": 50}
    return panel


def prepare(args):
    current_branch = branch()
    settings = historical_settings()
    topic = load_topic(args.topic)
    panel = select_panel(read_rows(args.dataset), settings, topic)
    root = args.run_dir
    root.mkdir(parents=True, exist_ok=False)
    with (root / "panel.jsonl").open("x", encoding="utf-8") as stream:
        for row in panel:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = _run_manifest(args.dataset, topic, settings)
    manifest.update({
        "branch": current_branch,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "created_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "httpx": httpx.__version__, "seed": 20261018,
        "source_path": str(args.dataset), "topic_path": str(args.topic),
        "panel_sha256": digest(root / "panel.jsonl"),
        "instrumentation_sha256": digest(__file__),
        "requests_per_minute_cap": args.rpm, "parallel_workers": args.workers,
        "http_attempt_cap": 100, "smoke_http_attempt_cap": 10,
        "transport_settings": {
            "timeout": settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
            "retry_backoff": settings.llm_retry_backoff_seconds,
        },
    })
    save(root / "manifest.json", manifest)
    print(json.dumps({"prepared": 100, "strata": dict(Counter(
        f"{r['benchmark_arm']}/{r['language']}/{r['label']}/{r['expected_gate']}"
        for r in panel
    ))}))


@contextmanager
def run_lock(root):
    with (root / "run.lock").open("a") as stream:
        try:
            import fcntl  # POSIX only; imported here so the module also loads on Windows
        except ImportError:
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Probe:
    def __init__(self, root, rpm, smoke=False):
        self.root, self.interval = root, 60 / rpm
        self.cap = 10 if smoke else 100
        self.lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.local = threading.local()
        self.stopped = threading.Event()
        self.next_start = 0.0
        self.original_post = httpx.post
        self.ledger = root / "attempts.jsonl"
        self.count = len(read_rows(self.ledger)) if self.ledger.exists() else 0
        self.initial = self.count

    def append(self, path, value):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def post(self, *args, **kwargs):
        state = self.local.state
        waiting = time.perf_counter()
        # Serialize admissions, not network calls. Count BEFORE sending, including failures.
        with self.lock:
            if self.stopped.is_set() or self.count >= self.cap:
                raise RuntimeError("Benchmark HTTP budget or safety stop reached")
            time.sleep(max(0, self.next_start - time.perf_counter()))
            if self.stopped.is_set():
                raise RuntimeError("Provider safety stop reached while waiting")
            self.next_start = time.perf_counter() + self.interval
            self.count += 1
            request = kwargs["json"]
            reservation = {
                "attempt": self.count, "affair_id": state["affair_id"],
                "phase": state["phase"], "started_utc": datetime.now(UTC).isoformat(),
                "request_sha256": hashlib.sha256(
                    json.dumps(request, sort_keys=True).encode()
                ).hexdigest(),
                "prompt_chars": sum(len(m["content"]) for m in request["messages"]),
            }
            with self.log_lock:
                self.append(self.ledger, reservation)
        state["limiter_ms"] += (time.perf_counter() - waiting) * 1000
        started = time.perf_counter()
        response = None
        try:
            response = self.original_post(*args, **kwargs)
            if response.status_code >= 400:
                self.stopped.set()  # No repeated paid probes after provider rejection.
            return response
        except Exception:
            self.stopped.set()
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            state["http_ms"] += elapsed
            record = {**reservation, "http_ms": elapsed,
                      "status_code": response.status_code if response is not None else None}
            if response is not None:
                record["limit_headers"] = {
                    k: v for k, v in response.headers.items()
                    if k.lower().startswith(("x-ratelimit", "ratelimit"))
                    or k.lower() == "retry-after"
                }
                try:
                    record["usage"] = response.json().get("usage", {})
                except ValueError:
                    record["usage"] = {}
            with self.log_lock:
                self.append(self.root / "responses.jsonl", record)


class TimedClient(ApertusClient):
    def __init__(self, settings, probe):
        # This is explicitly the historical, unpooled benchmark adapter. Probe owns admission.
        super().__init__(settings.model_copy(update={
            "llm_connection_reuse": False, "llm_requests_per_minute": 0
        }))
        self.probe = probe

    def classify(self, system_prompt, user_prompt):
        state = self.probe.local.state
        state["client_start"] = time.perf_counter()
        try:
            return super().classify(system_prompt, user_prompt)
        finally:
            state["client_end"] = time.perf_counter()


def execute_phase(root, name, rows, workers, settings, topic, probe):
    path = root / f"{name}.jsonl"
    # Refuse repeats even after a crash: never silently spend the budget again.
    stream = path.open("x", encoding="utf-8")
    service = ClassificationService(settings, client=TimedClient(settings, probe))

    def one(row):
        started = time.perf_counter()
        state = {"affair_id": row["affair_id"], "phase": name,
                 "http_ms": 0.0, "limiter_ms": 0.0}
        probe.local.state = state
        affair = Affair.model_validate(row)
        result = service.classify(affair, topic)
        finished = time.perf_counter()
        entered, exited = state.get("client_start", finished), state.get("client_end", finished)
        if result.status.value == "failed":
            probe.stopped.set()
        return {
            "affair_id": row["affair_id"], "language": row["language"],
            "label": row["label"], "arm": row["benchmark_arm"], "phase": name,
            "chars": len(affair.combined_text()), "has_body": bool(affair.text.strip()),
            "has_documents": bool(affair.documents),
            "total_ms": (finished - started) * 1000,
            "pre_ms": (entered - started) * 1000,
            "client_ms": (exited - entered) * 1000,
            "post_ms": (finished - exited) * 1000,
            "http_ms": state["http_ms"], "limiter_ms": state["limiter_ms"],
            "used_model": "client_start" in state,
            "result": result.model_dump(mode="json"),
        }

    started = time.perf_counter()
    completed = 0
    with stream, ThreadPoolExecutor(max_workers=workers) as pool:
        pending_rows = iter(rows)
        futures = {pool.submit(one, row) for row in list(rows)[:workers]}
        for _ in range(min(workers, len(rows))):
            next(pending_rows)
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                value = future.result()
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")
                stream.flush()
                completed += 1
                row = next(pending_rows, None)
                if row is not None and not probe.stopped.is_set():
                    futures.add(pool.submit(one, row))
    elapsed = time.perf_counter() - started
    save(root / f"{name}.runtime.json", {
        "phase": name, "workers": workers, "wall_seconds": elapsed,
        "completed": completed, "expected": len(rows),
        "stopped": probe.stopped.is_set(), "http_attempts_total": probe.count,
    })
    print(json.dumps({"phase": name, "completed": completed,
                      "wall_seconds": elapsed, "attempts_total": probe.count}), flush=True)


def run(args):
    root = args.run_dir
    with run_lock(root):
        manifest = json.loads((root / "manifest.json").read_text("utf-8"))
        settings = historical_settings()
        topic = load_topic(manifest["topic_path"])
        current = _run_manifest(manifest["source_path"], topic, settings)
        if branch() != manifest["branch"] or any(current[k] != manifest[k] for k in current):
            raise ValueError("Branch, data, policy, settings or source changed")
        if digest(root / "panel.jsonl") != manifest["panel_sha256"]:
            raise ValueError("Panel changed")
        if digest(__file__) != manifest["instrumentation_sha256"]:
            raise ValueError("Instrumentation changed")
        if manifest["transport_settings"] != {
            "timeout": settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
            "retry_backoff": settings.llm_retry_backoff_seconds,
        }:
            raise ValueError("Transport settings changed")
        if not settings.llm_api_key:
            raise ValueError("No API credential configured")
        panel = read_rows(root / "panel.jsonl")
        sequential = [r for r in panel if r["benchmark_arm"] == "sequential"]
        smoke = [r for r in sequential if not r["expected_gate"]][:10]
        smoke_ids = {r["affair_id"] for r in smoke}
        probe = Probe(root, manifest["requests_per_minute_cap"], args.phase == "smoke")
        if args.phase == "complete":
            status = json.loads((root / "smoke.runtime.json").read_text("utf-8"))
            if status["stopped"] or status["completed"] != len(smoke):
                raise ValueError("Smoke test did not pass; do not spend more calls")
        with patch("parltopic.classification.apertus_client.httpx.post", probe.post):
            if args.phase == "smoke":
                execute_phase(root, "smoke", smoke, 1, settings, topic, probe)
            else:
                execute_phase(root, "sequential", [r for r in sequential
                              if r["affair_id"] not in smoke_ids], 1, settings, topic, probe)
                if not probe.stopped.is_set():
                    execute_phase(root, "parallel", [r for r in panel
                                  if r["benchmark_arm"] == "parallel"],
                                  manifest["parallel_workers"], settings, topic, probe)


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)

    def quantile(q):
        index = (len(ordered) - 1) * q
        lower = math.floor(index)
        return ordered[lower] + (ordered[math.ceil(index)] - ordered[lower]) * (index - lower)

    return {"n": len(values), "mean": statistics.mean(values),
            "p50": quantile(.5), "p95": quantile(.95), "p99": quantile(.99),
            "max": max(values)}


def calibrate(args):
    """Small live check of corrected observer, sharing the original <=100-call ledger."""
    root = args.run_dir
    with run_lock(root):
        manifest = json.loads((root / "manifest.json").read_text("utf-8"))
        if digest(root / "instrumentation-v1.py") != manifest["instrumentation_sha256"]:
            raise ValueError("Original instrumentation archive is required")
        settings = historical_settings()
        topic = load_topic(manifest["topic_path"])
        current = _run_manifest(manifest["source_path"], topic, settings)
        if branch() != manifest["branch"] or any(current[k] != manifest[k] for k in current):
            raise ValueError("Production code, branch, data or inference settings changed")
        if digest(root / "panel.jsonl") != manifest["panel_sha256"]:
            raise ValueError("Original panel changed")
        for phase in ("smoke", "sequential", "parallel"):
            status = json.loads((root / f"{phase}.runtime.json").read_text("utf-8"))
            if status["stopped"] or status["completed"] != status["expected"]:
                raise ValueError("Original measurement is incomplete")
        eligible = sorted([r for r in read_rows(root / "panel.jsonl")
                           if not r["expected_gate"]], key=lambda r: (
                               r["language"], len(Affair.model_validate(r).combined_text()),
                               str(r["affair_id"])
                           ))
        selected = [eligible[int((i + .5) * len(eligible) / 8)] for i in range(8)]
        probe = Probe(root, manifest["requests_per_minute_cap"])
        if probe.count + 8 > 100:
            raise ValueError("Not enough remaining HTTP budget for calibration")
        save(root / "calibration.manifest.json", {
            "reason": "Separate response logging lock from admission wait lock",
            "parent_manifest_sha256": digest(root / "manifest.json"),
            "original_instrumentation_sha256": manifest["instrumentation_sha256"],
            "corrected_instrumentation_sha256": digest(__file__),
            "selected_ids": [r["affair_id"] for r in selected],
            "workers": 4, "additional_attempt_cap": 8,
        })
        # Per-phase cap also counts retries; the persistent total remains <=100.
        probe.cap = min(100, probe.count + 8)
        with patch("parltopic.classification.apertus_client.httpx.post", probe.post):
            execute_phase(root, "calibration", selected, 4, settings, topic, probe)


def summarize(args):
    root = args.run_dir
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    rows, runtimes = [], []
    for phase in ("smoke", "sequential", "parallel"):
        if (root / f"{phase}.runtime.json").exists():
            rows.extend(read_rows(root / f"{phase}.jsonl"))
            runtimes.append(json.loads((root / f"{phase}.runtime.json").read_text("utf-8")))
    if len({r["affair_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate measurements")
    responses = read_rows(root / "responses.jsonl")
    attempts = read_rows(root / "attempts.jsonl")
    result = {"manifest": manifest, "artifacts_sha256": {
        p.name: digest(p) for p in sorted(root.glob("*.jsonl"))
    }, "unique_affairs": len(rows), "http_attempts": len(attempts),
        "http_responses": len(responses), "arms": {}}
    for arm in ("sequential", "parallel", "all"):
        selected = [r for r in rows if arm == "all" or r["arm"] == arm]
        phases = {r["phase"] for r in selected}
        wall = sum(t["wall_seconds"] for t in runtimes if t["phase"] in phases)
        successful = [r for r in selected if r["result"]["status"] != "failed"]
        decisive = [r for r in selected if r["result"]["status"]
                    in {"assigned", "not_assigned"}]
        usage_rows = [r for r in responses if r["phase"] in phases]
        tokens = {key: sum(r.get("usage", {}).get(key, 0) or 0 for r in usage_rows)
                  for key in ("prompt_tokens", "completion_tokens")}
        known_usage = sum("prompt_tokens" in r.get("usage", {}) for r in usage_rows)
        priced = args.input_price is not None and args.output_price is not None
        cost = ((tokens["prompt_tokens"] * args.input_price
                 + tokens["completion_tokens"] * args.output_price) / 1e6) if priced else None
        result["arms"][arm] = {
            "n": len(selected), "successful": len(successful), "decisive": len(decisive),
            "model_cases": sum(r["used_model"] for r in selected),
            "strata": dict(Counter(f"{r['language']}/{r['label']}" for r in selected)),
            "chars": distribution([r["chars"] for r in selected]),
            "title_only": sum(not r["has_body"] and not r["has_documents"] for r in selected),
            "wall_seconds": wall,
            "throughput_affairs_s": len(selected) / wall if wall else None,
            "successful_throughput_s": len(successful) / wall if wall else None,
            "timings_ms": {key: distribution([r[key] for r in selected]) for key in (
                "total_ms", "pre_ms", "post_ms", "client_ms", "http_ms", "limiter_ms"
            )},
            "model_http_ms": distribution([r["http_ms"] for r in selected if r["used_model"]]),
            "tokens": tokens, "http_usage_rows": known_usage,
            "estimated_cost": cost, "currency": args.currency if priced else None,
            "projection_300k_hours": wall / len(selected) * 300000 / 3600
            if selected else None,
            "projection_300k_tokens": {k: v / len(selected) * 300000
                                      for k, v in tokens.items()} if selected else None,
            "quality_decisive_only": asdict(binary_metrics(
                [r["label"] for r in decisive],
                [r["result"]["status"] == "assigned" for r in decisive]
            )) if decisive else None,
        }
    result["cost_basis"] = {"input_per_million": args.input_price,
                            "output_per_million": args.output_price,
                            "source": args.price_source,
                            "unknown_without_verified_tariff": args.input_price is None}
    result["http_statuses"] = dict(Counter(str(r["status_code"]) for r in responses))
    if (root / "calibration.runtime.json").exists():
        calibration = read_rows(root / "calibration.jsonl")
        calibration_runtime = json.loads((root / "calibration.runtime.json").read_text("utf-8"))
        result["calibration"] = {
            "manifest": json.loads((root / "calibration.manifest.json").read_text("utf-8")),
            "runtime": calibration_runtime,
            "n": len(calibration),
            "status_counts": dict(Counter(r["result"]["status"] for r in calibration)),
            "timings_ms": {key: distribution([r[key] for r in calibration]) for key in (
                "total_ms", "pre_ms", "post_ms", "client_ms", "http_ms", "limiter_ms"
            )},
            "client_residual_ms": distribution([
                r["client_ms"] - r["http_ms"] - r["limiter_ms"] for r in calibration
            ]),
            "throughput_affairs_s": len(calibration) / calibration_runtime["wall_seconds"],
        }
    result["primary_http_attempts"] = sum(r["phase"] != "calibration" for r in attempts)
    result["all_billed_usage_tokens"] = {
        key: sum(r.get("usage", {}).get(key, 0) or 0 for r in responses)
        for key in ("prompt_tokens", "completion_tokens")
    }
    result["reported_cached_input_tokens"] = sum(
        (r.get("usage", {}).get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        for r in responses if r["phase"] != "calibration"
    )
    result["primary_timing_limitation"] = (
        "v1 response logging contended with admission lock; parallel total/client latencies "
        "include observer waiting. HTTP timings are uncontaminated. Eight-call v2 calibration "
        "checks a separate response logging lock; it does not replace 50-case percentiles."
        if "calibration" in result else None
    )
    save(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {
        "manifest", "artifacts_sha256"
    }}, indent=2))


def main():
    parser = argparse.ArgumentParser(__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--dataset", type=Path, default=Path("data/eval/e1_digitalisation_dev.jsonl"))
    prep.add_argument("--topic", type=Path, default=Path("configs/topics/digitalisation.yaml"))
    prep.add_argument("--rpm", type=float, default=30)
    prep.add_argument("--workers", type=int, default=4)
    prep.add_argument("--run-dir", type=Path, required=True)
    live = sub.add_parser("run")
    live.add_argument("--run-dir", type=Path, required=True)
    live.add_argument("--phase", choices=("smoke", "complete"), required=True)
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--run-dir", type=Path, required=True)
    summary = sub.add_parser("summarize")
    summary.add_argument("--run-dir", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    summary.add_argument("--input-price", type=float)
    summary.add_argument("--output-price", type=float)
    summary.add_argument("--currency")
    summary.add_argument("--price-source")
    args = parser.parse_args()
    if args.command == "prepare" and (not 0 < args.rpm <= 60 or not 1 <= args.workers <= 4):
        parser.error("Use 0<RPM<=60 and 1<=workers<=4 for the initial bounded benchmark")
    if args.command == "summarize" and (
        (args.input_price is None) != (args.output_price is None)
        or (args.input_price is not None and (
            args.input_price < 0 or args.output_price < 0
            or not args.currency or not args.price_source
        ))
    ):
        parser.error("Pricing requires nonnegative input/output rates, currency and source")
    {"prepare": prepare, "run": run, "summarize": summarize,
     "calibrate": calibrate}[args.command](args)


if __name__ == "__main__":
    main()
