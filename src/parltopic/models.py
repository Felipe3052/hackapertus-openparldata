from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ClassificationStatus(StrEnum):
    ASSIGNED = "assigned"
    NOT_ASSIGNED = "not_assigned"
    UNCERTAIN = "uncertain"
    NOT_EVALUABLE = "not_evaluable"
    FAILED = "failed"


class ModelDecision(BaseModel):
    """Strict, source-grounded response expected from Apertus."""

    model_config = ConfigDict(extra="forbid")

    status: ClassificationStatus
    score: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("status")
    @classmethod
    def reject_internal_failure_status(cls, value: ClassificationStatus) -> ClassificationStatus:
        if value == ClassificationStatus.FAILED:
            raise ValueError("failed is application-owned and cannot be emitted by the model")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_ids must be unique")
        return values

    @model_validator(mode="after")
    def require_evidence_for_positive_or_uncertain(self) -> "ModelDecision":
        if self.status in {ClassificationStatus.ASSIGNED, ClassificationStatus.UNCERTAIN}:
            if not self.evidence_ids:
                raise ValueError(f"{self.status.value} requires at least one evidence ID")
        return self


class Document(BaseModel):
    document_id: str
    text: str = ""
    language: str | None = None
    source_url: HttpUrl | None = None


class Affair(BaseModel):
    affair_id: str
    title: str
    text: str = ""
    language: str = "de"
    parliament: str | None = None
    level: str | None = None
    date: str | None = None
    source_url: HttpUrl | None = None
    documents: list[Document] = Field(default_factory=list)

    def combined_text(self) -> str:
        parts = [self.title, self.text]
        parts.extend(document.text for document in self.documents if document.text)
        return "\n\n".join(part.strip() for part in parts if part and part.strip())


class TopicDefinition(BaseModel):
    topic_id: str
    name: str
    description: str
    synonyms: list[str] = Field(default_factory=list)
    title_synonyms: list[str] = Field(default_factory=list)
    normalize_online_variants: bool = False
    # Per-topic policy; None falls back to the settings. A curated topic with vetted terms can
    # use the term rule and prompt v2; a topic written in a minute should use topic-v1 without
    # the rule, because quickly chosen terms are too broad (see docs/experiments.md, A · M-A).
    prompt_version: str | None = None
    keyword_rule: bool | None = None
    positive_examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)


class TextSegment(BaseModel):
    segment_id: str
    affair_id: str
    document_id: str | None = None
    text: str
    language: str
    position: int
    source_url: HttpUrl | None = None


class Evidence(BaseModel):
    segment_id: str
    text: str
    document_id: str | None = None
    source_url: HttpUrl | None = None
    retrieval_score: float | None = None


class ClassificationResult(BaseModel):
    affair_id: str
    topic_id: str
    status: ClassificationStatus
    score: float | None = None
    explanation: str = ""
    language: str
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False
    model: str
    prompt_version: str = "topic-v1"
    classifier_version: str = "llm-only-v1"
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    error: str | None = None
