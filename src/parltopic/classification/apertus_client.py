import time
from dataclasses import dataclass
from threading import Lock

import httpx

from parltopic.classification.rate_limit import StartLimiter, shared_limiter
from parltopic.config import Settings
from parltopic.models import ModelDecision


@dataclass
class ApertusResponse:
    payload: ModelDecision
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float


class ApertusClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None,
                 limiter: StartLimiter | None = None):
        self.settings = settings
        self._http_client = http_client
        self._owns_client = http_client is None
        self._client_lock = Lock()
        self._closed = False
        self.limiter = limiter or shared_limiter(
            settings.llm_base_url, settings.llm_api_key, settings.llm_requests_per_minute
        )

    def close(self):
        with self._client_lock:
            if self._owns_client and self._http_client is not None:
                self._http_client.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is not configured")
        return self._post_with_retry(system_prompt, user_prompt).json()

    def classify(self, system_prompt: str, user_prompt: str) -> ApertusResponse:
        started = time.perf_counter()
        body = self.complete(system_prompt, user_prompt)
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return ApertusResponse(
            payload=ModelDecision.model_validate_json(content),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _post_with_retry(self, system_prompt: str, user_prompt: str) -> httpx.Response:
        endpoint = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        request = {
            "model": self.settings.llm_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                if self._closed:
                    raise RuntimeError("ApertusClient is closed")
                self.limiter.wait()
                if self.settings.llm_connection_reuse:
                    with self._client_lock:
                        if self._http_client is None:
                            self._http_client = httpx.Client(
                                limits=httpx.Limits(max_connections=8, max_keepalive_connections=8)
                            )
                    post = self._http_client.post
                else:
                    post = httpx.post
                response = post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json=request,
                    timeout=self.settings.llm_timeout_seconds,
                )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as error:
                retryable = error.response.status_code == 429 or error.response.status_code >= 500
                if not retryable or attempt >= self.settings.llm_max_retries:
                    raise
            except httpx.TimeoutException:
                if attempt >= self.settings.llm_max_retries:
                    raise
            time.sleep(self.settings.llm_retry_backoff_seconds * 2**attempt)
        raise RuntimeError("Apertus retry loop ended unexpectedly")

