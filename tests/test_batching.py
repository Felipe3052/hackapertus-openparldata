import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
import pytest

from parltopic.classification.apertus_client import ApertusClient
from parltopic.classification.rate_limit import StartLimiter, shared_limiter
from parltopic.classification.service import ClassificationService
from parltopic.config import Settings
from parltopic.evaluation.batch_performance import AttemptController, not_worse, paired_panel
from parltopic.evaluation.experimental_batching import classify_many, classify_prepared
from parltopic.models import Affair, TopicDefinition


def settings():
    return Settings(_env_file=None, llm_api_key="offline", llm_requests_per_minute=0)


def test_connection_reuse_lifecycle_and_identical_single_payload():
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "status": "not_assigned", "score": .9, "explanation": "Outside topic",
            "evidence_ids": [],
        })}}]})

    http = httpx.Client(transport=httpx.MockTransport(respond))
    factory_path = "parltopic.classification.apertus_client.httpx.Client"
    with patch(factory_path, return_value=http) as factory:
        with ApertusClient(settings()) as client:
            client.classify("system", "user")
            client.classify("system", "user")
            assert not http.is_closed
        assert http.is_closed
        assert factory.call_count == 1
    assert sent[0] == sent[1]
    assert sent[0]["messages"] == [{"role": "system", "content": "system"},
                                   {"role": "user", "content": "user"}]


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_shared_limiter_strict_rolling_30_starts_including_retry():
    clock = Clock()
    limiter = StartLimiter(30, clock.time, clock.sleep)
    starts = []
    for _ in range(75):
        limiter.wait()
        starts.append(clock.time())
    assert starts[:3] == [0, 2, 4]
    assert max(sum(t <= u < t + 60 for u in starts) for t in starts) == 30
    assert starts[30] == 60


def test_clients_share_one_limiter_during_concurrent_initialization():
    with ThreadPoolExecutor(8) as pool:
        limiters = list(pool.map(
            lambda _: shared_limiter("https://offline.test/concurrent", "test-key", 30),
            range(32),
        ))
    assert all(limiter is limiters[0] for limiter in limiters)


def test_real_client_retry_is_rate_limited_and_uses_same_pool():
    clock, starts = Clock(), []

    def respond(request):
        starts.append(clock.time())
        if len(starts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "status": "not_assigned", "score": .9, "explanation": "Outside topic",
            "evidence_ids": [],
        })}}]})

    configured = settings().model_copy(update={"llm_retry_backoff_seconds": 0})
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with ApertusClient(configured, http_client=http,
                           limiter=StartLimiter(30, clock.time, clock.sleep)) as client:
            assert client.classify("system", "user").payload.status == "not_assigned"
        assert not http.is_closed  # The injected client remains its caller's responsibility.
    assert starts == [0, 2]


def service_with_response(transform=None):
    topic = TopicDefinition(topic_id="d", name="Digital", description="Digital policy")
    affairs = [Affair(affair_id=str(i), title=f"Hospital {i}") for i in range(5)]
    service = ClassificationService(settings())
    prepared = [service.prepare(a, topic) for a in affairs]

    def fake(system, user):
        rows = [{"affair_id": p.affair.affair_id, "status": "assigned", "score": .9,
                 "explanation": "Evidence", "evidence_ids": [p.selected[0].segment_id]}
                for p in prepared]
        rows = transform(rows) if transform else list(reversed(rows))
        return {"choices": [{"message": {"content": json.dumps({"results": rows})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30}}

    service.client.complete = fake
    return service, prepared


def test_batch_preserves_ids_order_and_counts_usage_only_once():
    service, prepared = service_with_response()
    results = classify_prepared(service, prepared)
    assert [r.affair_id for r in results] == [str(i) for i in range(5)]
    assert all(r.status == "assigned" for r in results)
    assert all(r.input_tokens is None and r.output_tokens is None for r in results)
    for result, item in zip(results, prepared, strict=True):
        assert result.evidence[0].segment_id == item.selected[0].segment_id


@pytest.mark.parametrize("problem", ["duplicate", "missing", "foreign-evidence"])
def test_batch_rejects_invalid_member_or_cross_affair_evidence_atomically(problem):
    def corrupt(rows):
        if problem == "duplicate":
            rows[-1] = rows[0]
        elif problem == "missing":
            rows.pop()
        else:
            rows[0]["evidence_ids"] = rows[1]["evidence_ids"]
        return rows

    service, prepared = service_with_response(corrupt)
    assert all(r.status == "failed" for r in classify_prepared(service, prepared))


def test_rule_only_batches_never_call_model():
    topic = TopicDefinition(topic_id="d", name="Digital", description="Digital policy")
    affairs = [Affair(affair_id=str(i), title="Digital") for i in range(6)]
    service = ClassificationService(settings())
    service.client.complete = lambda *a: pytest.fail("No paid model calls for rule hits")
    for size in (1, 3, 5):
        results = classify_many(service, affairs, topic, batch_size=size)
        assert [r.affair_id for r in results] == [str(i) for i in range(6)]
        assert all(r.input_tokens == 0 for r in results)


def test_paid_attempt_cap_and_strict_quality_guard(tmp_path):
    controller = AttemptController(tmp_path, {}, cap=2)
    controller.limiter = StartLimiter(0)
    controller.local.context = {"variant": 3, "ids": ["a", "b", "c"]}
    for _ in range(2):
        controller.before(httpx.Request("POST", "https://example.test", json={"messages": []}))
    with pytest.raises(RuntimeError, match="budget"):
        controller.before(httpx.Request("POST", "https://example.test", json={"messages": []}))
    assert len((tmp_path / "attempts.jsonl").read_text("utf-8").splitlines()) == 2
    baseline = dict.fromkeys(["coverage", "macro_f1", "macro_precision", "macro_recall",
                              "precision", "recall"], .9)
    assert not_worse(baseline, baseline)
    assert not not_worse({**baseline, "recall": .89}, baseline)


def test_new_benchmark_budget_is_global_across_workers_and_persistent(tmp_path):
    controller = AttemptController(tmp_path, {}, cap=50)
    controller.limiter = StartLimiter(0)

    def attempt(i):
        controller.local.context = {"variant": 3, "ids": [str(i)]}
        try:
            controller.before(httpx.Request("POST", "https://example.test", json={}))
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(attempt, range(60))) == 50
    assert len((tmp_path / "attempts.jsonl").read_text("utf-8").splitlines()) == 50
    resumed = AttemptController(tmp_path, {}, cap=50)
    resumed.limiter = StartLimiter(0)
    resumed.local.context = {"variant": 3, "ids": ["never-sent"]}
    with pytest.raises(RuntimeError):
        resumed.before(httpx.Request("POST", "https://example.test", json={}))


def test_paired_sample_is_deterministic_and_not_selected_on_predictions():
    rows = [{"affair_id": str(i), "title": f"Hospital {i}", "text": "x" * i,
             "language": ("de", "fr", "it")[i % 3], "label": bool(i % 2),
             "expected_gate": i % 5 == 0} for i in range(100)]
    chosen = paired_panel(rows)
    assert chosen == paired_panel(rows)
    assert len({r["affair_id"] for r in chosen}) == 30


def test_rejected_batch_sizes_cannot_be_enabled_in_production_settings():
    from pydantic import ValidationError

    for size in (3, 5):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, llm_batch_size=size)


def test_api_reuses_service_for_lifespan_and_closes_pool(monkeypatch):
    from fastapi.testclient import TestClient

    from parltopic import api

    monkeypatch.setattr(api, "get_settings", settings)
    with TestClient(api.app) as http:
        service = api.app.state.classifier
        body = {"affair_id": "1", "title": "Digital", "topic": {
            "topic_id": "digital", "name": "Digital", "description": "Digital policy",
        }}
        assert http.post("/classify", json=body).json()["status"] == "assigned"
        assert http.post("/classify", json=body).json()["status"] == "assigned"
        assert api.app.state.classifier is service
        assert service.client._http_client is None  # Rule-only traffic opens no connections.
    assert service.client._closed
