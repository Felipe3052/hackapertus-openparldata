from dataclasses import dataclass

from parltopic.aps import ApsRouter, ApsTaxonomy, select_context
from parltopic.classification.apertus_client import ApertusClient, ApertusResponse
from parltopic.classification.keyword import first_keyword_hit
from parltopic.classification.prompts import build_user_prompt, system_prompt
from parltopic.config import Settings
from parltopic.models import (
    Affair,
    ClassificationResult,
    ClassificationStatus,
    Evidence,
    TextSegment,
    TopicDefinition,
)
from parltopic.retrieval.bm25 import retrieve
from parltopic.retrieval.chunker import chunk_affair


@dataclass
class PreparedAffair:
    affair: Affair
    topic: TopicDefinition
    selected: list[TextSegment]
    score_by_id: dict[str, float]
    context_policy: str = "full"
    aps_taxonomy_version: str | None = None
    context_segments_before: int | None = None
    context_segments_after: int | None = None
    context_tokens_approx_before: int | None = None
    context_tokens_approx_after: int | None = None


class ClassificationService:
    def __init__(self, settings: Settings, client: ApertusClient | None = None):
        self.settings = settings
        self.client = client or ApertusClient(settings)
        self.aps_router = None
        if settings.aps_context_enabled:
            self.aps_router = ApsRouter(ApsTaxonomy.load(settings.aps_taxonomy_path))

    def classify(self, affair: Affair, topic: TopicDefinition) -> ClassificationResult:
        prepared = self.prepare(affair, topic)
        if isinstance(prepared, ClassificationResult):
            return prepared
        try:
            response = self.client.classify(
                system_prompt(self._prompt_version(topic)),
                build_user_prompt(topic, prepared.selected),
            )
            return self.finish(prepared, response)
        except Exception as error:
            return self._result(affair, topic, ClassificationStatus.FAILED, str(error))

    def _prompt_version(self, topic: TopicDefinition) -> str:
        """A topic file may set its own prompt; otherwise the configured default applies."""
        return topic.prompt_version or self.settings.classifier_prompt_version

    def _keyword_rule(self, topic: TopicDefinition) -> bool:
        if topic.keyword_rule is None:
            return self.settings.keyword_rescue_enabled
        return topic.keyword_rule

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def prepare(
        self, affair: Affair, topic: TopicDefinition
    ) -> PreparedAffair | ClassificationResult:
        segments = chunk_affair(affair, self.settings.chunk_size, self.settings.chunk_overlap)
        if not segments:
            return self._result(affair, topic, ClassificationStatus.NOT_EVALUABLE)
        if self._keyword_rule(topic):
            gate_segments = (
                segments
                if self.settings.keyword_document_gate_enabled
                else [segment for segment in segments if segment.document_id is None]
            )
            hit = first_keyword_hit(gate_segments, topic)
            if hit is None and affair.title.strip():
                hit = first_keyword_hit([segments[0]], topic, terms=topic.title_synonyms)
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
                    prompt_version=self._prompt_version(topic),
                    classifier_version=self.settings.classifier_policy_version,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                )
        context = self._select_context(affair, segments)
        ranked = retrieve(context["segments"], topic, self.settings.retrieval_top_k)
        if self.settings.retrieval_pin_title and affair.title.strip():
            title = segments[0]
            title_rank = next((item for item in ranked if item[0] == title), (title, 0.0))
            ranked = [title_rank, *(item for item in ranked if item[0] != title)][
                : self.settings.retrieval_top_k
            ]
        selected = [segment for segment, _ in ranked]
        score_by_id = {segment.segment_id: score for segment, score in ranked}
        return PreparedAffair(
            affair, topic, selected, score_by_id,
            context_policy=context["policy"],
            aps_taxonomy_version=context["taxonomy_version"],
            context_segments_before=context["segments_before"],
            context_segments_after=context["segments_after"],
            context_tokens_approx_before=context["tokens_before"],
            context_tokens_approx_after=context["tokens_after"],
        )

    def _select_context(self, affair: Affair, segments: list[TextSegment]) -> dict:
        if self.aps_router is None:
            return {
                "segments": segments,
                "policy": "full",
                "taxonomy_version": None,
                "segments_before": len(segments),
                "segments_after": len(segments),
                "tokens_before": None,
                "tokens_after": None,
            }
        route = self.aps_router.route(
            affair,
            max_chapters=self.settings.aps_max_chapters,
            max_topics=self.settings.aps_max_topics,
        )
        if route.fallback_reason:
            return {
                "segments": segments,
                "policy": f"aps-fallback:{route.fallback_reason}",
                "taxonomy_version": route.taxonomy_version,
                "segments_before": len(segments),
                "segments_after": len(segments),
                "tokens_before": None,
                "tokens_after": None,
            }
        selected, report = select_context(
            segments,
            route,
            self.aps_router.taxonomy,
            max_segments=self.settings.aps_context_max_segments,
        )
        return {
            "segments": selected,
            "policy": "aps-shadow-context",
            "taxonomy_version": route.taxonomy_version,
            "segments_before": report["input_segments"],
            "segments_after": report["selected_segments"],
            "tokens_before": report["input_tokens_approx"],
            "tokens_after": report["selected_tokens_approx"],
        }

    def finish(self, prepared: PreparedAffair, response: ApertusResponse) -> ClassificationResult:
        affair, topic = prepared.affair, prepared.topic
        status = response.payload.status
        selected_by_id = {segment.segment_id: segment for segment in prepared.selected}
        evidence_ids = self._resolve_evidence_ids(response.payload.evidence_ids, selected_by_id)
        evidence = [
            Evidence(
                segment_id=segment_id,
                text=selected_by_id[segment_id].text,
                document_id=selected_by_id[segment_id].document_id,
                source_url=selected_by_id[segment_id].source_url,
                retrieval_score=prepared.score_by_id[segment_id],
            )
            for segment_id in evidence_ids
        ]
        return ClassificationResult(
            affair_id=affair.affair_id,
            topic_id=topic.topic_id,
            status=status,
            score=max(0.0, min(1.0, response.payload.score)),
            explanation=response.payload.explanation,
            language=affair.language,
            evidence=evidence,
            needs_review=status
            in {ClassificationStatus.UNCERTAIN, ClassificationStatus.NOT_EVALUABLE},
            model=self.settings.llm_name,
            prompt_version=self._prompt_version(topic),
            classifier_version=self.settings.classifier_policy_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            context_policy=prepared.context_policy,
            aps_taxonomy_version=prepared.aps_taxonomy_version,
            context_segments_before=prepared.context_segments_before,
            context_segments_after=prepared.context_segments_after,
            context_tokens_approx_before=prepared.context_tokens_approx_before,
            context_tokens_approx_after=prepared.context_tokens_approx_after,
        )

    @staticmethod
    def _resolve_evidence_ids(requested: list[str], selected_by_id: dict[str, object]) -> list[str]:
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
            prompt_version=self._prompt_version(topic),
            classifier_version=self.settings.classifier_policy_version,
            error=error,
        )
