import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
import pytest

from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.evaluation.performance import Probe, distribution, execute_phase, select_panel
from parltopic.models import Affair, TopicDefinition


def test_hard_smoke_budget_counts_every_http_attempt(tmp_path):
    probe = Probe(tmp_path, rpm=60, smoke=True)
    probe.interval = 0
    calls = []

    def fake(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 5}})

    probe.original_post = fake

    def send(i):
        probe.local.state = {"affair_id": str(i), "phase": "smoke",
                             "limiter_ms": 0, "http_ms": 0}
        try:
            probe.post("https://example.test", json={"messages": []})
        except RuntimeError:
            pass

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(send, range(15)))
    assert len(calls) == 10
    assert len((tmp_path / "attempts.jsonl").read_text("utf-8").splitlines()) == 10
    resumed = Probe(tmp_path, rpm=60)
    assert resumed.count == 10


def test_persistent_total_budget_survives_new_process_probe(tmp_path):
    (tmp_path / "attempts.jsonl").write_text("{}\n" * 99)
    probe = Probe(tmp_path, rpm=60)
    probe.original_post = lambda *a, **k: httpx.Response(200, json={"usage": {}})
    probe.local.state = {"affair_id": "test", "phase": "parallel",
                         "limiter_ms": 0, "http_ms": 0}
    probe.post("https://example.test", json={"messages": []})
    with pytest.raises(RuntimeError):
        probe.post("https://example.test", json={"messages": []})
    assert len((tmp_path / "attempts.jsonl").read_text("utf-8").splitlines()) == 100


def test_provider_rate_limit_stops_further_calls(tmp_path):
    probe = Probe(tmp_path, rpm=60)
    probe.original_post = lambda *a, **k: httpx.Response(429, headers={"retry-after": "60"})
    probe.local.state = {"affair_id": "real-id-not-sent", "phase": "smoke",
                         "limiter_ms": 0, "http_ms": 0}
    assert probe.post("https://example.test", json={"messages": []}).status_code == 429
    with pytest.raises(RuntimeError):
        probe.post("https://example.test", json={"messages": []})
    assert probe.count == 1
    assert json.loads((tmp_path / "responses.jsonl").read_text("utf-8"))["limit_headers"]


def test_response_logging_never_waits_for_admission_lock(tmp_path):
    probe = Probe(tmp_path, rpm=60)
    started, release = threading.Event(), threading.Event()

    def fake(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return httpx.Response(200, json={"usage": {}})

    probe.original_post = fake

    def send():
        probe.local.state = {"affair_id": "test", "phase": "parallel",
                             "limiter_ms": 0, "http_ms": 0}
        return probe.post("https://example.test", json={"messages": []})

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(send)
        assert started.wait(2)
        with probe.lock:
            release.set()
            assert future.result(timeout=1).status_code == 200


def test_panel_is_reproducible_unique_and_balances_arms():
    rows = [{"affair_id": str(i), "title": "digital" if i % 5 == 0 else f"Health {i}",
             "text": "x" * i, "language": ("de", "fr", "it")[i % 3],
             "label": i % 3 == 0} for i in range(450)]
    settings = Settings(llm_api_key="", _env_file=None)
    topic = TopicDefinition(topic_id="topic", name="Digital", description="digital",
                            synonyms=["digital"])
    first = select_panel(rows, settings, topic)
    assert first == select_panel(rows, settings, topic)
    assert len({r["affair_id"] for r in first}) == 100
    assert sum(r["benchmark_arm"] == "sequential" for r in first) == 50
    assert distribution([1, 2, 3, 4])["p95"] == pytest.approx(3.85)


def test_instrumentation_preserves_live_payload_and_additive_times(tmp_path):
    settings = Settings(llm_api_key="offline-test", llm_name="test", _env_file=None,
                        llm_connection_reuse=False, llm_requests_per_minute=0)
    topic = TopicDefinition(topic_id="topic", name="Digital", description="digital")
    probe = Probe(tmp_path, rpm=60, smoke=True)
    request_seen = []

    def fake(*args, **kwargs):
        request_seen.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "status": "not_assigned", "score": .9, "explanation": "Health policy.",
            "evidence_ids": [],
        })}}], "usage": {"prompt_tokens": 5, "completion_tokens": 10}},
            request=httpx.Request("POST", "https://example.test"))

    probe.original_post = fake
    row = {"affair_id": "synthetic-test", "title": "Health", "text": "Hospital",
           "language": "de", "label": False, "benchmark_arm": "sequential"}
    with patch("parltopic.classification.apertus_client.httpx.post", probe.post):
        execute_phase(tmp_path, "smoke", [row], 1, settings, topic, probe)
    measured = json.loads((tmp_path / "smoke.jsonl").read_text("utf-8"))
    assert measured["pre_ms"] + measured["client_ms"] + measured["post_ms"] == pytest.approx(
        measured["total_ms"]
    )
    assert measured["result"]["status"] == "not_assigned"
    assert request_seen[0]["temperature"] == 0
    assert request_seen[0]["response_format"] == {"type": "json_object"}
    with patch("parltopic.classification.apertus_client.httpx.post", fake):
        original = ClassificationService(settings).classify(Affair.model_validate(row), topic)
    assert request_seen[0] == request_seen[1]
    observed_result = dict(measured["result"])
    original_result = original.model_dump(mode="json")
    observed_result.pop("latency_ms")
    original_result.pop("latency_ms")
    assert observed_result == original_result
