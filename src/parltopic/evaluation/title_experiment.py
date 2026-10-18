"""Verify a main baseline and replay identical Apertus requests for lexical rule experiments."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import yaml

from parltopic.classification.apertus_client import ApertusResponse
from parltopic.classification.prompts import build_user_prompt
from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.evaluation.compare import compare_runs
from parltopic.evaluation.run import _validated_results, read_rows, score_results
from parltopic.models import Affair, ModelDecision, TopicDefinition
from parltopic.retrieval.bm25 import retrieve
from parltopic.retrieval.chunker import chunk_affair


def run_experiment(
    eval_path: Path, baseline_path: Path, overlay: Path, output: Path,
    experiment_id: str = "hybrid-title-v1",
) -> dict:
    started = time.perf_counter()
    manifest = json.loads(baseline_path.with_suffix(".jsonl.manifest.json").read_text("utf-8"))
    main_ref = subprocess.check_output(["git", "rev-parse", "main"], text=True).strip()
    for name, expected in manifest["implementation_sha256"].items():
        content = subprocess.check_output(["git", "show", f"{main_ref}:src/parltopic/{name}"])
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Historical baseline does not match main: {name}")
    topic_content = subprocess.check_output([
        "git", "show", f"{main_ref}:configs/topics/digitalisation.yaml",
    ], text=True)
    base_topic = TopicDefinition.model_validate(yaml.safe_load(topic_content))
    original_topic = base_topic.model_dump(exclude={"title_synonyms", "normalize_online_variants"})
    if original_topic != manifest["topic"]:
        raise ValueError("Baseline topic differs from main")
    if hashlib.sha256(eval_path.read_bytes()).hexdigest() != manifest["dataset_sha256"]:
        raise ValueError("Baseline dataset hash differs")
    # Request builders must match the original source; runtime request equality is checked too.
    for name in ("classification/prompts.py", "retrieval/bm25.py", "retrieval/chunker.py"):
        source = Path(__file__).resolve().parents[1] / name
        expected_hash = manifest["implementation_sha256"][name]
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f"Replay cannot prove request equivalence for {name}")
    rows = read_rows(eval_path)
    baseline, missing = _validated_results(rows, read_rows(baseline_path))
    if missing or any(row["status"] not in {"assigned", "not_assigned"}
                      for row in baseline.values()):
        raise ValueError("A complete, decisive baseline is required")
    overlay_data = yaml.safe_load(overlay.read_text("utf-8"))
    allowed = {"title_synonyms", "normalize_online_variants"}
    if not isinstance(overlay_data, dict) or set(overlay_data) - allowed:
        raise ValueError("Unsupported experiment overlay fields")
    title_terms = overlay_data["title_synonyms"]
    candidate = TopicDefinition.model_validate({**base_topic.model_dump(), **overlay_data})
    settings = Settings(_env_file=None, **{
        **manifest["settings"], "classifier_policy_version": experiment_id,
        "keyword_document_gate_enabled": True, "retrieval_pin_title": False,
    })

    class ReplayClient:
        saved = None
        expected_user = None
        calls = 0

        def classify(self, system, user):
            if system != manifest["system_prompt"] or user != self.expected_user:
                raise ValueError("Replay refused a changed Apertus request")
            self.calls += 1
            row = self.saved
            if not row.get("input_tokens"):
                raise ValueError("Baseline rule output cannot stand in for a model completion")
            return ApertusResponse(
                payload=ModelDecision(
                    status=row["status"], score=row["score"], explanation=row["explanation"],
                    evidence_ids=[e["segment_id"] for e in row["evidence"]],
                ),
                input_tokens=row["input_tokens"], output_tokens=row["output_tokens"],
                latency_ms=row["latency_ms"],
            )

    client = ReplayClient()
    service = ClassificationService(settings, client=client)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        for row in rows:
            affair = Affair.model_validate(row)
            segments = chunk_affair(affair, settings.chunk_size, settings.chunk_overlap)
            ranked = retrieve(segments, base_topic, settings.retrieval_top_k)
            client.expected_user = build_user_prompt(base_topic, [segment for segment, _ in ranked])
            client.saved = baseline[affair.affair_id]
            result = service.classify(affair, candidate)
            if result.status.value == "failed":
                raise ValueError(result.error)
            file.write(result.model_dump_json() + "\n")
    base_score = score_results(eval_path, baseline_path)
    candidate_score = score_results(eval_path, output)
    report = {
        "experiment_id": experiment_id,
        "main_commit": main_ref, "dataset_sha256": manifest["dataset_sha256"],
        "baseline_source_verified": True, "mode": "exact-request replay, no new inference",
        "topic_scope": "digitalisation binary proxy labels only",
        "candidate_title_terms": title_terms, "replayed_model_calls": client.calls,
        "normalize_online_variants": candidate.normalize_online_variants,
        "new_api_calls": 0, "incremental_api_cost": 0,
        "replay_wall_seconds": round(time.perf_counter() - started, 3),
        "baseline": base_score, "experiment": candidate_score,
        "comparison": compare_runs(eval_path, baseline_path, output, samples=5000),
        "acceptance": {
            "macro_precision_recall_max_drop": 0.01,
            "eligible": (
                candidate_score["assigned"]["all"]["macro_f1"]
                > base_score["assigned"]["all"]["macro_f1"]
                and all(candidate_score["assigned"]["all"][key]
                        >= base_score["assigned"]["all"][key] - 0.01
                        for key in ("macro_precision", "macro_recall"))
            ),
        },
        "cost_note": (
            "Token counts and latency are measured baseline-call records reused by replay. "
            "Currency costs require a provider tariff; replay time is not live API time."
        ),
    }
    output.with_suffix(".report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment-id", default="hybrid-title-v1")
    args = parser.parse_args()
    report = run_experiment(args.eval_set, args.baseline, args.overlay, args.output,
                            args.experiment_id)
    print(json.dumps({
        "main": report["main_commit"],
        "baseline": report["baseline"]["assigned"]["all"],
        "experiment": report["experiment"]["assigned"]["all"],
        "acceptance": report["acceptance"], "comparison": report["comparison"],
    }, indent=2))
