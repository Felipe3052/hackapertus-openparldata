"""Rejected batch-3/5 research variants, isolated from the production classifier.

The paired trial lost coverage. Do not use this module for production inference.
It is retained only to reproduce the comparison; size one preserves the single prompt.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, ConfigDict, Field

from parltopic.classification.apertus_client import ApertusResponse
from parltopic.classification.prompts import build_user_prompt, system_prompt
from parltopic.classification.service import ClassificationService, PreparedAffair
from parltopic.models import Affair, ClassificationResult, ClassificationStatus, ModelDecision


class BatchItem(ModelDecision):
    affair_id: str


class BatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[BatchItem] = Field(min_length=1, max_length=5)


def batch_prompts(service, prepared):
    topic = prepared[0].topic
    if any(item.topic != topic for item in prepared):
        raise ValueError("All batch members must use the same topic definition")
    system = system_prompt(service.settings.classifier_prompt_version) + """

MULTI-AFFAIR OUTPUT CONTRACT (replaces only the single-object output shape above)
Evaluate EACH supplied affair independently with the same decision policy.
Do not transfer subject matter or evidence between affairs. Return one JSON object:
{"results": [{"affair_id": "exact input ID", "status": "...", "score": 0.0,
"explanation": "one concise sentence", "evidence_ids": ["own passage IDs"]}]}
Return exactly one result per supplied affair, no duplicates or additional IDs.
Each result has exactly the five keys shown. Only cite passages from that same affair.
"""
    user = build_user_prompt(topic, []) + "\n\nINDEPENDENT AFFAIRS\n"
    for item in prepared:
        user += f"\nBEGIN AFFAIR {item.affair.affair_id}\n"
        user += "\n\n".join(f"[{s.segment_id}] {s.text}" for s in item.selected)
        user += f"\nEND AFFAIR {item.affair.affair_id}\n"
    return system, user


def classify_prepared(service: ClassificationService, prepared: list[PreparedAffair]):
    if not prepared or len(prepared) > 5:
        raise ValueError("A request must contain between one and five prepared affairs")
    started = time.perf_counter()
    try:
        if len(prepared) == 1:
            item = prepared[0]
            response = service.client.classify(
                system_prompt(service.settings.classifier_prompt_version),
                build_user_prompt(item.topic, item.selected),
            )
            return [service.finish(item, response)]
        system, user = batch_prompts(service, prepared)
        body = service.client.complete(system, user)
        parsed = BatchDecision.model_validate_json(body["choices"][0]["message"]["content"])
        ids = [item.affair_id for item in parsed.results]
        if len(ids) != len(set(ids)) or set(ids) != {p.affair.affair_id for p in prepared}:
            raise ValueError("Batch results must match requested affair IDs exactly")
        decisions = {item.affair_id: ModelDecision.model_validate(
            item.model_dump(exclude={"affair_id"})
        ) for item in parsed.results}
        # Validate ALL members before publishing any. Each result can cite only its own passages.
        results = [service.finish(item, ApertusResponse(
            payload=decisions[item.affair.affair_id], input_tokens=None, output_tokens=None,
            latency_ms=(time.perf_counter() - started) * 1000,
        )).model_copy(update={
            "classifier_version": service.settings.classifier_policy_version + "-batch-v1"
        }) for item in prepared]
        # Batch usage is counted once from HTTP usage, never duplicated across member results.
        return results
    except Exception as error:
        return [service._result(item.affair, item.topic, ClassificationStatus.FAILED, str(error))
                for item in prepared]


def classify_many(service: ClassificationService, affairs: list[Affair], topic,
                  batch_size: int | None = None, workers: int = 1):
    size = 1 if batch_size is None else batch_size
    if size not in {1, 3, 5} or workers < 1:
        raise ValueError("Batch size must be 1, 3 or 5; workers must be positive")
    if len({a.affair_id for a in affairs}) != len(affairs):
        raise ValueError("Affair IDs must be unique")
    results, pending = {}, []
    for affair in affairs:
        item = service.prepare(affair, topic)
        if isinstance(item, ClassificationResult):
            results[affair.affair_id] = item
        else:
            pending.append(item)
    groups = [pending[i:i + size] for i in range(0, len(pending), size)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for group_results in pool.map(lambda group: classify_prepared(service, group), groups):
            results.update({r.affair_id: r for r in group_results})
    return [results[a.affair_id] for a in affairs]
