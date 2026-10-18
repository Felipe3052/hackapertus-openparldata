from parltopic.classification.apertus_client import ApertusClient
from parltopic.classification.keyword import first_keyword_hit
from parltopic.classification.prompts import build_user_prompt, system_prompt
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
        if self.settings.keyword_rescue_enabled:
            gate_segments = segments if self.settings.keyword_document_gate_enabled else [
                segment for segment in segments if segment.document_id is None
            ]
            hit = first_keyword_hit(gate_segments, topic)
            if hit:
                segment, term = hit
                return ClassificationResult(
                    affair_id=affair.affair_id,
                    topic_id=topic.topic_id,
                    status=ClassificationStatus.ASSIGNED,
                    score=1.0,
                    explanation=f"Configured topic term {term!r} occurs in the affair.",
                    language=affair.language,
                    evidence=[
                        Evidence(
                            segment_id=segment.segment_id,
                            text=segment.text,
                            document_id=segment.document_id,
                            source_url=segment.source_url,
                        )
                    ],
                    needs_review=False,
                    model=self.settings.llm_name,
                    prompt_version=self.settings.classifier_prompt_version,
                    classifier_version=self.settings.classifier_policy_version,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                )
        ranked = retrieve(segments, topic, self.settings.retrieval_top_k)
        if self.settings.retrieval_pin_title and affair.title.strip():
            title = segments[0]
            title_rank = next((item for item in ranked if item[0] == title), (title, 0.0))
            ranked = [title_rank, *(item for item in ranked if item[0] != title)][
                :self.settings.retrieval_top_k
            ]
        selected = [segment for segment, _ in ranked]
        score_by_id = {segment.segment_id: score for segment, score in ranked}
        try:
            prompt_version = self.settings.classifier_prompt_version
            response = self.client.classify(
                system_prompt(prompt_version), build_user_prompt(topic, selected)
            )
            status = response.payload.status
            selected_by_id = {segment.segment_id: segment for segment in selected}
            evidence_ids = self._resolve_evidence_ids(
                response.payload.evidence_ids, selected_by_id
            )
            evidence = [
                Evidence(
                    segment_id=segment_id,
                    text=selected_by_id[segment_id].text,
                    document_id=selected_by_id[segment_id].document_id,
                    source_url=selected_by_id[segment_id].source_url,
                    retrieval_score=score_by_id[segment_id],
                )
                for segment_id in evidence_ids
            ]
            model_score = response.payload.score
            return ClassificationResult(
                affair_id=affair.affair_id,
                topic_id=topic.topic_id,
                status=status,
                score=max(0.0, min(1.0, model_score)),
                explanation=response.payload.explanation,
                language=affair.language,
                evidence=evidence,
                needs_review=status
                in {ClassificationStatus.UNCERTAIN, ClassificationStatus.NOT_EVALUABLE},
                model=self.settings.llm_name,
                prompt_version=prompt_version,
                classifier_version=self.settings.classifier_policy_version,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
            )
        except Exception as error:
            return self._result(affair, topic, ClassificationStatus.FAILED, str(error))

    @staticmethod
    def _resolve_evidence_ids(
        requested: list[str], selected_by_id: dict[str, object]
    ) -> list[str]:
        """Repair only unambiguous prefix typos when the content hash still matches exactly."""
        resolved = []
        for segment_id in requested:
            if segment_id in selected_by_id:
                resolved.append(segment_id)
                continue
            content_hash = segment_id.rsplit("-", 1)[-1]
            matches = [
                candidate
                for candidate in selected_by_id
                if candidate.rsplit("-", 1)[-1] == content_hash
            ]
            if len(matches) != 1:
                raise ValueError(f"Model returned unknown evidence ID: {segment_id}")
            resolved.append(matches[0])
        if len(resolved) != len(set(resolved)):
            raise ValueError("Resolved evidence IDs must be unique")
        return resolved

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
            prompt_version=self.settings.classifier_prompt_version,
            classifier_version=self.settings.classifier_policy_version,
            error=error,
        )

