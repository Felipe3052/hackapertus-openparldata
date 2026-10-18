from parltopic.classification.apertus_client import ApertusClient
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


class ClassificationService:
    def __init__(self, settings: Settings, client: ApertusClient | None = None):
        self.settings = settings
        self.client = client or ApertusClient(settings)

    def classify(self, affair: Affair, topic: TopicDefinition) -> ClassificationResult:
        segments = chunk_affair(affair, self.settings.chunk_size, self.settings.chunk_overlap)
        if not segments:
            return self._result(affair, topic, ClassificationStatus.NOT_EVALUABLE)
        ranked = retrieve(segments, topic, self.settings.retrieval_top_k)
        selected = [segment for segment, _ in ranked]
        score_by_id = {segment.segment_id: score for segment, score in ranked}
        try:
            response = self.client.classify(SYSTEM_PROMPT, build_user_prompt(topic, selected))
            status = ClassificationStatus(response.payload["status"])
            selected_by_id = {segment.segment_id: segment for segment in selected}
            evidence = [
                Evidence(
                    segment_id=segment_id,
                    text=selected_by_id[segment_id].text,
                    source_url=selected_by_id[segment_id].source_url,
                    retrieval_score=score_by_id[segment_id],
                )
                for segment_id in response.payload.get("evidence_ids") or []
                # Smaller models sometimes return nested lists or numbers; keep only known IDs.
                if isinstance(segment_id, str) and segment_id in selected_by_id
            ]
            model_score = float(response.payload.get("score", 0))
            return ClassificationResult(
                affair_id=affair.affair_id,
                topic_id=topic.topic_id,
                status=status,
                score=max(0.0, min(1.0, model_score)),
                explanation=str(response.payload.get("explanation", "")),
                language=affair.language,
                evidence=evidence,
                needs_review=status
                in {ClassificationStatus.UNCERTAIN, ClassificationStatus.NOT_EVALUABLE},
                model=self.settings.llm_name,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
            )
        except Exception as error:
            return self._result(affair, topic, ClassificationStatus.FAILED, str(error))

    def _result(
        self,
        affair: Affair,
        topic: TopicDefinition,
        status: ClassificationStatus,
        error: str | None = None,
    ) -> ClassificationResult:
        return ClassificationResult(
            affair_id=affair.affair_id,
            topic_id=topic.topic_id,
            status=status,
            language=affair.language,
            needs_review=True,
            model=self.settings.llm_name,
            error=error,
        )

