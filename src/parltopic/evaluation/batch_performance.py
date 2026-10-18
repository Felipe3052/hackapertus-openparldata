"""Paired live batch-size comparison, <=50 actual HTTP inference attempts including retries."""

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from parltopic.classification.apertus_client import ApertusClient, ApertusResponse
from parltopic.classification.rate_limit import StartLimiter
from parltopic.classification.service import ClassificationService, PreparedAffair
from parltopic.config import Settings, get_settings
from parltopic.evaluation.experimental_batching import classify_prepared
from parltopic.evaluation.metrics import binary_metrics
from parltopic.evaluation.performance import branch, digest, distribution, run_lock, save
from parltopic.evaluation.run import _run_manifest, read_rows
from parltopic.models import Affair, ModelDecision
from parltopic.topics import load_topic


def paired_panel(rows, n=30, seed=20261019):
    strata = defaultdict(list)
    for row in rows:
        strata[(row["language"], row["label"], row["expected_gate"])].append(row)
    exact = {k: n * len(v) / len(rows) for k, v in strata.items()}
    quotas = {k: math.floor(v) for k, v in exact.items()}
    for key in sorted(strata, key=lambda k: (-(exact[k] - quotas[k]), k))[
        :n - sum(quotas.values())
    ]:
        quotas[key] += 1
    rng = random.Random(seed)
    selected = []
    for key in sorted(strata):
        ordered = sorted(strata[key], key=lambda r: (
            len(Affair.model_validate(r).combined_text()), str(r["affair_id"])
        ))
        count = quotas[key]
        offset = rng.random()
        selected.extend(ordered[int((i + offset) * len(ordered) / count)] for i in range(count))
    rng.shuffle(selected)
    if len({r["affair_id"] for r in selected}) != n:
        raise ValueError("Invalid paired sample")
    return selected


class AttemptController:
    def __init__(self, root, expected_single, rpm=30, cap=50):
        self.root, self.expected_single, self.cap = root, expected_single, cap
        self.limiter = StartLimiter(rpm)
        self.lock = threading.Lock()
        self.local = threading.local()
        self.stopped = threading.Event()
        path = root / "attempts.jsonl"
        self.count = len(read_rows(path)) if path.exists() else 0

    def append(self, filename, row):
        with (self.root / filename).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def before(self, request):
        if self.stopped.is_set():
            raise RuntimeError("Benchmark stopped after provider rejection")
        self.limiter.wait()
        context = self.local.context
        payload = json.loads(request.content)
        sha = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if context["variant"] == 1 and sha != self.expected_single[context["ids"][0]]:
            raise RuntimeError("Single-affair request differs from original baseline")
        with self.lock:
            if self.stopped.is_set() or self.count >= self.cap:
                raise RuntimeError("Hard 50-attempt budget reached")
            self.count += 1
            record = {
                "attempt": self.count, "variant": context["variant"],
                "ids": context["ids"], "started_utc": datetime.now(UTC).isoformat(),
                "started_monotonic": time.monotonic(), "request_sha256": sha,
            }
            self.append("attempts.jsonl", record)
        request.extensions["benchmark_record"] = record
        request.extensions["benchmark_http_start"] = time.perf_counter()
        request.extensions["benchmark_connections"] = []

        def trace(name, info):
            if name in {"connection.connect_tcp.complete", "connection.start_tls.complete"}:
                request.extensions["benchmark_connections"].append(name)
        request.extensions["trace"] = trace

    def after(self, response):
        response.read()
        request = response.request
        elapsed = (time.perf_counter() - request.extensions["benchmark_http_start"]) * 1000
        if response.status_code >= 400:
            self.stopped.set()
        try:
            usage = response.json().get("usage", {})
        except ValueError:
            usage = {}
        row = {**request.extensions["benchmark_record"], "http_ms": elapsed,
               "status_code": response.status_code, "usage": usage,
               "connection_events": request.extensions["benchmark_connections"],
               "limit_headers": {k: v for k, v in response.headers.items()
                                 if k.lower().startswith(("x-ratelimit", "ratelimit"))
                                 or k.lower() == "retry-after"}}
        with self.lock:
            self.append("responses.jsonl", row)


def quality(rows):
    decisive = [r for r in rows if r["result"]["status"] in {"assigned", "not_assigned"}]
    return {"coverage": len(decisive) / len(rows), **asdict(binary_metrics(
        [r["label"] for r in decisive],
        [r["result"]["status"] == "assigned" for r in decisive],
    ))}


def not_worse(candidate, baseline):
    keys = ("coverage", "macro_f1", "macro_precision", "macro_recall", "precision", "recall")
    return all(candidate[k] + 1e-12 >= baseline[k] for k in keys)


def prepare(args):
    current_branch = branch()
    parent = args.parent
    settings = get_settings()
    topic = load_topic("configs/topics/digitalisation.yaml")
    rows = paired_panel(read_rows(parent / "panel.jsonl"))
    baseline = {}
    for phase in ("smoke", "sequential", "parallel"):
        baseline.update({r["affair_id"]: r for r in read_rows(parent / f"{phase}.jsonl")})
    signatures = {r["affair_id"]: r["request_sha256"]
                  for r in read_rows(parent / "attempts.jsonl") if r["phase"] != "calibration"}
    # Count baseline model routing, not predictions, before selecting any candidate.
    required = sum(baseline[r["affair_id"]]["used_model"] for r in rows)
    planned = required + math.ceil(required / 3) + math.ceil(required / 5)
    if planned > 50:
        raise ValueError("Planned comparison exceeds 50-call budget")
    root = args.run_dir
    root.mkdir(parents=True, exist_ok=False)
    with (root / "panel.jsonl").open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    saved_baseline = [{"affair_id": r["affair_id"], "label": r["label"],
                       "result": baseline[r["affair_id"]]["result"]} for r in rows]
    save(root / "baseline.json", {"rows": saved_baseline, "quality": quality(saved_baseline),
                                  "single_signatures": signatures})
    manifest = _run_manifest(parent / "panel.jsonl", topic, settings)
    manifest.update({
        "branch": current_branch, "created_utc": datetime.now(UTC).isoformat(),
        "parent": str(parent), "panel_sha256": digest(root / "panel.jsonl"),
        "baseline_sha256": digest(root / "baseline.json"), "planned_calls": planned,
        "model_required": required, "seed": 20261019, "workers": 4, "rpm": 30,
        "attempt_cap": 50,
        "benchmark_source_sha256": digest(__file__),
        "batching_sha256": digest(Path(__file__).with_name("experimental_batching.py")),
    })
    save(root / "manifest.json", manifest)
    print(json.dumps({"sample": 30, "model_required": required, "planned_calls": planned,
                      "historic_quality": quality(saved_baseline)}, indent=2))


def run(args):
    root = args.run_dir
    with run_lock(root):
        manifest = json.loads((root / "manifest.json").read_text())
        baseline = json.loads((root / "baseline.json").read_text())
        settings = get_settings()
        topic = load_topic("configs/topics/digitalisation.yaml")
        expected = _run_manifest(Path(manifest["parent"]) / "panel.jsonl", topic, settings)
        if branch() != manifest["branch"] or any(expected[k] != manifest[k] for k in expected):
            raise ValueError("Code, branch, data or configuration changed")
        if digest(root / "panel.jsonl") != manifest["panel_sha256"]:
            raise ValueError("Panel changed")
        if digest(root / "baseline.json") != manifest["baseline_sha256"]:
            raise ValueError("Baseline changed")
        if digest(__file__) != manifest["benchmark_source_sha256"]:
            raise ValueError("Benchmark changed")
        if digest(Path(__file__).with_name("experimental_batching.py")) != manifest[
            "batching_sha256"
        ]:
            raise ValueError("Batch contract changed")
        controller = AttemptController(root, baseline["single_signatures"])
        if controller.count:
            raise ValueError("Live experiment has started; do not silently rerun paid calls")
        panel = read_rows(root / "panel.jsonl")
        # Each variant starts a new pool, avoiding inherited connections; limiter is shared.
        for size in (1, 3, 5):
            if controller.stopped.is_set():
                break
            output = root / f"batch{size}.jsonl"
            with output.open("x", encoding="utf-8") as stream, httpx.Client(
                event_hooks={"request": [controller.before], "response": [controller.after]},
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            ) as http:
                client = ApertusClient(settings.model_copy(update={"llm_connection_reuse": True}),
                                       http_client=http, limiter=StartLimiter(0))
                service = ClassificationService(settings, client=client)
                started = time.perf_counter()
                pending, results = [], {}
                by_id = {r["affair_id"]: r for r in panel}
                for row in panel:
                    item = service.prepare(Affair.model_validate(row), topic)
                    if isinstance(item, PreparedAffair):
                        pending.append(item)
                    else:
                        results[item.affair_id] = {
                            "affair_id": item.affair_id, "label": row["label"],
                            "language": row["language"], "result": item.model_dump(mode="json"),
                            "latency_ms": 0.0,
                        }
                groups = [pending[i:i + size] for i in range(0, len(pending), size)]

                def one(group, size=size, service=service, by_id=by_id):
                    controller.local.context = {"variant": size,
                                                "ids": [p.affair.affair_id for p in group]}
                    start = time.perf_counter()
                    batch_results = classify_prepared(service, group)
                    elapsed = (time.perf_counter() - start) * 1000
                    return [{"affair_id": r.affair_id, "label": by_id[r.affair_id]["label"],
                             "language": by_id[r.affair_id]["language"],
                             "result": r.model_dump(mode="json"), "latency_ms": elapsed}
                            for r in batch_results]

                with ThreadPoolExecutor(max_workers=4) as pool:
                    for future in as_completed([pool.submit(one, g) for g in groups]):
                        for row in future.result():
                            results[row["affair_id"]] = row
                for row in panel:
                    stream.write(json.dumps(results[row["affair_id"]], ensure_ascii=False) + "\n")
                elapsed = time.perf_counter() - started
                save(root / f"batch{size}.runtime.json", {"wall_seconds": elapsed})
                print(json.dumps({"batch_size": size, "wall_seconds": elapsed,
                                  "quality": quality(list(results.values())),
                                  "cumulative_attempts": controller.count}), flush=True)


def summarize(args):
    root = args.run_dir
    manifest = json.loads((root / "manifest.json").read_text())
    baseline = json.loads((root / "baseline.json").read_text())
    responses, attempts = read_rows(root / "responses.jsonl"), read_rows(root / "attempts.jsonl")
    panel = read_rows(root / "panel.jsonl")
    report = {"manifest": manifest, "historical_quality": baseline["quality"],
              "total_api_attempts": len(attempts), "variants": {},
              "artifacts_sha256": {p.name: digest(p) for p in sorted(root.glob("*.jsonl"))}}
    for size in (1, 3, 5):
        path = root / f"batch{size}.jsonl"
        if not path.exists():
            continue
        rows = read_rows(path)
        if [r["affair_id"] for r in rows] != [r["affair_id"] for r in panel]:
            raise ValueError("Paired IDs/order differ")
        if [r["label"] for r in rows] != [r["label"] for r in panel]:
            raise ValueError("Paired labels differ")
        metrics = quality(rows)
        unresolved = [r for r in rows if r["result"]["status"]
                      not in {"assigned", "not_assigned"}]
        # Sensitivity bound, not fabricated predictions: score every unresolved label as wrong.
        full_panel_lower_bound = asdict(binary_metrics(
            [r["label"] for r in rows],
            [r["result"]["status"] == "assigned" if r not in unresolved else not r["label"]
             for r in rows],
        ))
        used = [r for r in responses if r["variant"] == size]
        tried = [r for r in attempts if r["variant"] == size]
        tokens = {key: sum(r.get("usage", {}).get(key, 0) or 0 for r in used)
                  for key in ("prompt_tokens", "completion_tokens")}
        elapsed = json.loads((root / f"batch{size}.runtime.json").read_text())["wall_seconds"]
        report["variants"][str(size)] = {
            "n": len(rows), "quality": metrics, "wall_seconds": elapsed,
            "quality_scope": "Decisive cases only; always assess with coverage on fixed panel",
            "status_counts": dict(Counter(r["result"]["status"] for r in rows)),
            "full_panel_worst_case_completion_bound": full_panel_lower_bound,
            "affairs_per_minute": len(rows) / elapsed * 60,
            "decisive_affairs_per_minute": (len(rows) - len(unresolved)) / elapsed * 60,
            "requests_per_minute": len(tried) / elapsed * 60,
            "latency_ms": distribution([r["latency_ms"] for r in rows]),
            "http_latency_ms": distribution([r["http_ms"] for r in used]),
            "tokens": tokens, "tokens_per_affair": {k: v / len(rows) for k, v in tokens.items()},
            "api_attempts": len(tried),
            "retries": len(tried) - len({tuple(r["ids"]) for r in tried}),
            "failed_affairs": sum(r["result"]["status"] == "failed" for r in rows),
            "affair_error_rate": sum(r["result"]["status"] == "failed" for r in rows) / len(rows),
            "http_error_rate": sum(r["status_code"] >= 400 for r in used) / len(used),
            "tcp_connections": sum(r["connection_events"].count("connection.connect_tcp.complete")
                                   for r in used),
            "projection_300k_hours": elapsed / len(rows) * 300000 / 3600,
            "projection_300k_admission_floor_hours":
                len({tuple(r["ids"]) for r in tried}) / len(rows) * 300000
                / manifest["rpm"] / 60,
            "not_worse_than_historical": not_worse(metrics, baseline["quality"]),
        "not_worse_than_live_single": not_worse(
                metrics, report["variants"].get("1", {"quality": metrics})["quality"]
            ),
        }
    eligible = {k: v for k, v in report["variants"].items()
                if v["not_worse_than_historical"] and v["not_worse_than_live_single"]
                and not v["failed_affairs"]}
    report["recommended_batch_size_on_panel"] = int(min(
        eligible, key=lambda k: eligible[k]["wall_seconds"]
    )) if eligible else None
    times = sorted(r["started_monotonic"] for r in attempts)
    report["max_starts_in_halfopen_60s"] = max(sum(t <= u < t + 60 for u in times) for t in times)
    report["minimum_start_gap_seconds"] = min(
        b-a for a, b in zip(times, times[1:], strict=False)
    )
    report["quality_rejected_batch_sizes"] = [
        int(k) for k in report["variants"] if k not in eligible
    ]
    report["production_enabled_batch_sizes"] = [1]
    report["decision"] = (
        f"Fastest candidate meeting all paired quality/coverage criteria: "
        f"{report['recommended_batch_size_on_panel']}. "
        "Production permits only single-affair inference with connection reuse; "
        "multi-affair implementation remains research-only pending separate promotion."
    )
    report["historical_matching_http_ms"] = distribution([
        r["http_ms"] for r in read_rows(Path(manifest["parent"]) / "responses.jsonl")
        if r["phase"] != "calibration" and r["affair_id"] in {p["affair_id"] for p in panel}
    ])
    report["live_single_status_matches_historical"] = sum(
        old["result"]["status"] == new["result"]["status"]
        for old, new in zip(baseline["rows"], read_rows(root / "batch1.jsonl"), strict=True)
    )
    save(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}, indent=2))


def verify_refactor(args):
    """API-free equivalence of original and refactored flow, using recorded model decisions."""
    reference = json.loads((args.parent / "manifest.json").read_text())["commit"]
    source = subprocess.check_output(
        ["git", "show", f"{reference}:src/parltopic/classification/service.py"], text=True
    )
    namespace = {}
    exec(compile(source, "frozen_feature_service.py", "exec"), namespace)
    original_service = namespace["ClassificationService"]
    dataset = Path("data/eval/e1_digitalisation_dev.jsonl")
    recorded = Path("results/hybrid_v3_actual_dev450.jsonl")
    decisions = {r["affair_id"]: r for r in read_rows(recorded)}
    manifest = json.loads(recorded.with_suffix(".jsonl.manifest.json").read_text())
    settings = Settings(_env_file=None, **manifest["settings"])
    topic = load_topic("configs/topics/digitalisation.yaml")

    class Replay:
        def __init__(self, row):
            self.row, self.prompts = row, []

        def classify(self, system, user):
            self.prompts.append((system, user))
            row = self.row
            return ApertusResponse(
                ModelDecision(status=row["status"], score=row["score"],
                              explanation=row["explanation"],
                              evidence_ids=[e["segment_id"] for e in row["evidence"]]),
                row.get("input_tokens"), row.get("output_tokens"), row.get("latency_ms") or 0,
            )

    count = 0
    for row in read_rows(dataset):
        affair = Affair.model_validate(row)
        old_client = Replay(decisions[affair.affair_id])
        new_client = Replay(decisions[affair.affair_id])
        old = original_service(settings, client=old_client).classify(affair, topic)
        new = ClassificationService(settings, client=new_client).classify(affair, topic)
        if old_client.prompts != new_client.prompts or old.model_dump() != new.model_dump():
            raise ValueError(f"Refactor changes prompt/routing/result for {affair.affair_id}")
        count += 1
    report = {
        "purpose": "Control-flow/prompt/result equivalence, not fresh inference quality or timing",
        "matched": count, "api_calls": 0, "reference_commit": reference,
        "original_service_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "current_service_sha256": digest(Path(__file__).parents[1] / "classification/service.py"),
        "dataset_sha256": digest(dataset), "recorded_decisions_sha256": digest(recorded),
    }
    if args.output:
        save(args.output, report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "summarize", "verify-refactor"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--parent", type=Path, default=Path("results/performance-20261018"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "summarize": summarize,
     "verify-refactor": verify_refactor}[args.mode](args)


if __name__ == "__main__":
    main()
