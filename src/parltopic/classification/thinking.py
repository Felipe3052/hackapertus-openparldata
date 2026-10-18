"""Second look with Apertus reasoning for affairs the fast pass rejected.

Apertus only reasons before answering when the assistant turn is prefilled with its reasoning
marker; the answer follows `<|inner_suffix|>`. Prompt instructions alone do not trigger it
(finding from the team's Fact Attack hackathon, confirmed on the CSCS endpoint).
"""

import json
import re
import time

import httpx

from parltopic.classification.prompts import SYSTEM_PROMPT, build_user_prompt
from parltopic.config import Settings
from parltopic.models import (
    Affair,
    ClassificationResult,
    ClassificationStatus,
    Evidence,
    TopicDefinition,
)
from parltopic.retrieval.bm25 import retrieve
from parltopic.retrieval.chunker import chunk_affair

THINKING_MODEL = "swiss-ai/Apertus-v1.5-70B-thinking"
PREFIX, SUFFIX = "<|inner_prefix|>", "<|inner_suffix|>"
JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_answer(content: str) -> dict:
    """JSON answer after the reasoning; falls back to the last JSON object in the text."""
    answer = content.split(SUFFIX, 1)[1] if SUFFIX in content else content
    match = JSON_RE.search(answer)
    if not match:
        raise ValueError("no JSON answer after reasoning")
    return json.loads(match.group(0))


def rethink(
    affair: Affair,
    topic: TopicDefinition,
    settings: Settings,
    model: str = THINKING_MODEL,
    max_tokens: int = 4000,
) -> ClassificationResult:
    segments = chunk_affair(affair, settings.chunk_size, settings.chunk_overlap)
    ranked = retrieve(segments, topic, settings.retrieval_top_k)
    selected = {segment.segment_id: (segment, score) for segment, score in ranked}
    started = time.perf_counter()
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(topic, [s for s, _ in ranked])},
                    {"role": "assistant", "content": PREFIX},
                ],
                "continue_final_message": True,
                "add_generation_prompt": False,
            },
            timeout=max(settings.llm_timeout_seconds, 300),
        )
        response.raise_for_status()
        body = response.json()
        payload = parse_answer(body["choices"][0]["message"]["content"] or "")
        status = ClassificationStatus(payload["status"])
        usage = body.get("usage", {})
        return ClassificationResult(
            affair_id=affair.affair_id,
            topic_id=topic.topic_id,
            status=status,
            score=max(0.0, min(1.0, float(payload.get("score", 0)))),
            explanation=str(payload.get("explanation", "")),
            language=affair.language,
            evidence=[
                Evidence(
                    segment_id=i,
                    text=selected[i][0].text,
                    source_url=selected[i][0].source_url,
                    retrieval_score=selected[i][1],
                )
                for i in payload.get("evidence_ids", [])
                if i in selected
            ],
            needs_review=status
            in {ClassificationStatus.UNCERTAIN, ClassificationStatus.NOT_EVALUABLE},
            model=model,
            prompt_version="topic-v1-thinking",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as error:
        return ClassificationResult(
            affair_id=affair.affair_id,
            topic_id=topic.topic_id,
            status=ClassificationStatus.FAILED,
            language=affair.language,
            needs_review=True,
            model=model,
            error=str(error),
        )
