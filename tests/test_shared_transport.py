import json

import httpx
import pytest

from parltopic import compiler
from parltopic.classification import thinking
from parltopic.classification.apertus_client import ApertusClient
from parltopic.config import Settings
from parltopic.models import Affair, TopicDefinition


def test_classifier_compiler_and_thinking_share_admission_and_strict_evidence(monkeypatch):
    requests = []

    class Admission:
        calls = 0

        def wait(self):
            self.calls += 1

    admission = Admission()

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("max_tokens") == 6000:
            content = {lang: ["fixture"] for lang in compiler.LANGUAGES}
            content["excluded"] = []
        elif payload.get("continue_final_message"):
            content = {"status": "assigned", "score": 1, "explanation": "Synthetic",
                       "evidence_ids": ["foreign-id"]}
        else:
            content = {"status": "not_assigned", "score": 0, "explanation": "Synthetic",
                       "evidence_ids": []}
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(content),
        }}]})

    settings = Settings(_env_file=None, llm_api_key="offline", llm_requests_per_minute=0)
    topic = TopicDefinition(topic_id="fixture", name="Fixture", description="Synthetic",
                            prompt_version="topic-v1", keyword_rule=False)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        def factory(configuration):
            return ApertusClient(configuration, http_client=http, limiter=admission)

        monkeypatch.setattr(compiler, "ApertusClient", factory)
        monkeypatch.setattr(thinking, "ApertusClient", factory)
        compiler.compile_topic(topic, settings)
        with factory(settings) as client:
            assert client.classify("system", "user").payload.status == "not_assigned"
        result = thinking.rethink(Affair(affair_id="1", title="Synthetic"), topic, settings)
        assert result.status == "failed"
        assert "evidence" in result.error
        assert result.prompt_version == "topic-v1"
    assert admission.calls == len(requests) == 3
    assert requests[2]["messages"][0]["content"].startswith("You classify Swiss")


def test_retry_after_is_observed_with_no_network_or_actual_wait(monkeypatch):
    waits, attempts = [], []

    def respond(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("parltopic.classification.apertus_client.time.sleep", waits.append)
    settings = Settings(_env_file=None, llm_api_key="offline", llm_requests_per_minute=0)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with ApertusClient(settings, http_client=http) as client:
            assert client.request({"model": "fixture"}) == {"ok": True}
    assert waits == [7]
    assert len(attempts) == 2


def test_forbidden_provider_response_is_not_retried():
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(403, json={"error": "forbidden"})

    settings = Settings(_env_file=None, llm_api_key="offline", llm_requests_per_minute=0)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with ApertusClient(settings, http_client=http) as client:
            with pytest.raises(httpx.HTTPStatusError) as error:
                client.request({"model": "fixture"})
    assert error.value.response.status_code == 403
    assert len(attempts) == 1
