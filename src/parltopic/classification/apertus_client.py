import time
from dataclasses import dataclass

import httpx

from parltopic.config import Settings
from parltopic.models import ModelDecision


@dataclass
class ApertusResponse:
    payload: ModelDecision
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float


class ApertusClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def classify(self, system_prompt: str, user_prompt: str) -> ApertusResponse:
        if not self.settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is not configured")
        started = time.perf_counter()
        response = self._post_with_retry(system_prompt, user_prompt)
        body = response.json()
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
                response = httpx.post(
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

