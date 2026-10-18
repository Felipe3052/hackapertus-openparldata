from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class ClassificationStatus(StrEnum):
    ASSIGNED = "assigned"
    NOT_ASSIGNED = "not_assigned"
    UNCERTAIN = "uncertain"
    NOT_EVALUABLE = "not_evaluable"
    FAILED = "failed"


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
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    error: str | None = None

