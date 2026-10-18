import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from parltopic.config import Settings


@dataclass
class ApertusResponse:
    payload: dict[str, Any]
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
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json={
                "model": self.settings.llm_name,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return ApertusResponse(
            payload=json.loads(content),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

