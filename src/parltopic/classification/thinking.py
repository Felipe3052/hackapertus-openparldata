"""Second look with Apertus reasoning for affairs the fast pass rejected.

Apertus only reasons before answering when the assistant turn is prefilled with its reasoning
marker; the answer follows `<|inner_suffix|>`. Prompt instructions alone do not trigger it
(finding from the team's Fact Attack hackathon, confirmed on the CSCS endpoint).
"""

import json
import time

from parltopic.classification.apertus_client import ApertusClient
from parltopic.classification.prompts import build_user_prompt, system_prompt
from parltopic.config import Settings
from parltopic.models import (
    Affair,
    ClassificationResult,
    ClassificationStatus,
    Evidence,
    ModelDecision,
    TopicDefinition,
)
from parltopic.retrieval.bm25 import retrieve
from parltopic.retrieval.chunker import chunk_affair

THINKING_MODEL = "swiss-ai/Apertus-v1.5-70B-thinking"
PREFIX, SUFFIX = "<|inner_prefix|>", "<|inner_suffix|>"


def parse_answer(content: str) -> dict:
    """JSON answer after the reasoning; falls back to the last JSON object in the text."""
    answer = content.split(SUFFIX, 1)[1] if SUFFIX in content else content
    decoder = json.JSONDecoder()
    # First JSON object that decodes; text after it (a repeated answer, a note) is ignored.
    for start in (i for i, char in enumerate(answer) if char == "{"):
        try:
            payload, _ = decoder.raw_decode(answer, start)
        except ValueError:
            continue
        if isinstance(payload, dict) and "status" in payload:
            return payload
    raise ValueError("no JSON answer after reasoning")


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
        with ApertusClient(settings) as client:
            body = client.request({
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt(
                            topic.prompt_version or settings.classifier_prompt_version
                        ),
                    },
                    {"role": "user", "content": build_user_prompt(topic, [s for s, _ in ranked])},
                    {"role": "assistant", "content": PREFIX},
                ],
                "continue_final_message": True,
                "add_generation_prompt": False,
            }, timeout=max(settings.llm_timeout_seconds, 300))
        decision = ModelDecision.model_validate(parse_answer(
            body["choices"][0]["message"]["content"] or ""
        ))
        if set(decision.evidence_ids) - set(selected):
            raise ValueError("Thinking returned evidence outside the supplied passages")
        payload = decision.model_dump(mode="json")
        status = decision.status
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
            prompt_version=topic.prompt_version or settings.classifier_prompt_version,
            classifier_version="thinking-rethink",
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
            prompt_version=topic.prompt_version or settings.classifier_prompt_version,
            error=str(error),
        )
