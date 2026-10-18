"""Deterministic APS routing and context selection for experiments.

The router is deliberately a shadow component. It produces candidates and a compact context
without changing the existing Apertus classification policy. A later experiment can compare the
shadow output with the full-context baseline before enabling hard routing.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parltopic.models import Affair, TextSegment

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
TAXONOMY_VERSION = "aps-2026-10-18"


def _tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return {token for token in TOKEN_RE.findall(normalized) if len(token) > 2}


def _with_aliases(labels: dict[str, str], code: str, aliases: dict[str, object]) -> dict[str, str]:
    merged = dict(labels)
    values_by_language = aliases.get(code, {})
    if not isinstance(values_by_language, dict):
        raise ValueError(f"APS aliases for {code} must be an object keyed by language")
    for language, values in values_by_language.items():
        if not isinstance(language, str) or not language:
            raise ValueError(f"APS aliases for {code} must use non-empty language codes")
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ValueError(f"APS aliases for {code}/{language} must be non-empty strings")
        merged[language] = " / ".join(value.strip() for value in values)
    return merged


@dataclass(frozen=True)
class ApsNode:
    code: str
    parent_code: str | None
    level: str
    labels: dict[str, str]
    url_de: str | None = None

    @property
    def label_terms(self) -> set[str]:
        return _tokens(" ".join(self.labels.values()))


@dataclass(frozen=True)
class ApsCandidate:
    code: str
    level: str
    score: float
    matched_terms: tuple[str, ...]


class ApsDecision(BaseModel):
    """Strict multi-label response contract for a future APS Apertus call."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["assigned", "not_assigned", "uncertain", "not_evaluable"]
    score: float = Field(ge=0.0, le=1.0)
    topic_codes: list[str] = Field(default_factory=list, max_length=8)
    chapter_codes: list[str] = Field(default_factory=list, max_length=4)
    explanation: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("topic_codes", "chapter_codes", "evidence_ids")
    @classmethod
    def unique_codes(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("APS response lists must contain unique values")
        return values

    @model_validator(mode="after")
    def require_evidence_for_decision(self) -> "ApsDecision":
        if self.status in {"assigned", "uncertain"} and not self.evidence_ids:
            raise ValueError(f"{self.status} APS decisions require evidence IDs")
        return self


@dataclass(frozen=True)
class ApsRoute:
    taxonomy_version: str
    domain_candidates: tuple[ApsCandidate, ...]
    chapter_candidates: tuple[ApsCandidate, ...]
    topic_candidates: tuple[ApsCandidate, ...]
    fallback_reason: str | None = None

    def model_dump(self) -> dict:
        return {
            "taxonomy_version": self.taxonomy_version,
            "domain_candidates": [candidate.__dict__ for candidate in self.domain_candidates],
            "chapter_candidates": [candidate.__dict__ for candidate in self.chapter_candidates],
            "topic_candidates": [candidate.__dict__ for candidate in self.topic_candidates],
            "fallback_reason": self.fallback_reason,
        }


class ApsTaxonomy:
    def __init__(self, nodes: tuple[ApsNode, ...], version: str = TAXONOMY_VERSION):
        self.nodes = nodes
        self.version = version
        self._by_code = {node.code: node for node in nodes}
        self._validate()

    @classmethod
    def load(
        cls,
        path: Path,
        version: str = TAXONOMY_VERSION,
        aliases_path: Path | None = None,
    ) -> "ApsTaxonomy":
        raw = json.loads(path.read_text(encoding="utf-8"))
        aliases = {}
        if aliases_path is not None:
            aliases_data = json.loads(aliases_path.read_text(encoding="utf-8"))
            if not isinstance(aliases_data, dict):
                raise ValueError("APS alias file must contain a JSON object")
            if aliases_data.get("taxonomy_version") not in {None, version}:
                raise ValueError("APS alias taxonomy version does not match the base taxonomy")
            aliases = aliases_data.get("aliases", {})
            if not isinstance(aliases, dict):
                raise ValueError("APS aliases must be an object keyed by taxonomy code")
        nodes: list[ApsNode] = []
        chapter_labels: dict[str, dict[str, str]] = {}
        domain_labels: dict[str, dict[str, str]] = {}
        for item in raw:
            code = str(item["code"])
            parts = code.split(".")
            level = "topic" if len(parts) == 3 else "chapter"
            parent_code = str(item.get("chapter_code")) if level == "topic" else None
            labels = {
                key[6:]: str(value)
                for key, value in item.items()
                if key.startswith("topic_")
            }
            if level == "chapter":
                labels = {
                    key[8:]: str(value)
                    for key, value in item.items()
                    if key.startswith("chapter_")
                }
            labels = {key: value for key, value in labels.items() if value}
            labels = _with_aliases(labels, code, aliases)
            nodes.append(ApsNode(code, parent_code, level, labels, item.get("url_de")))
            if parent_code:
                chapter_labels[parent_code] = {
                    key[8:]: str(value)
                    for key, value in item.items()
                    if key.startswith("chapter_") and value
                }
                domain_labels[parts[0]] = {
                    key[7:]: str(value)
                    for key, value in item.items()
                    if key.startswith("domain_") and value
                }

        # The source file contains topic rows and derives chapter/domain names from them.
        chapter_codes = {node.parent_code for node in nodes if node.parent_code}
        for code in sorted(chapter_codes):
            labels = _with_aliases(chapter_labels.get(code, {}), code, aliases)
            nodes.append(ApsNode(code, code.split(".")[0], "chapter", labels))
        for code in sorted(domain_labels):
            labels = _with_aliases(domain_labels[code], code, aliases)
            nodes.append(ApsNode(code, None, "domain", labels))
        known_codes = {node.code for node in nodes}
        unknown_codes = sorted(set(aliases) - known_codes)
        if unknown_codes:
            raise ValueError(f"APS aliases reference unknown codes: {unknown_codes[:3]}")
        return cls(tuple(nodes), version)

    def _validate(self) -> None:
        if len(self._by_code) != len(self.nodes):
            raise ValueError("APS taxonomy contains duplicate codes")
        for node in self.nodes:
            if node.parent_code and node.parent_code not in self._by_code:
                raise ValueError(
                    f"APS {node.level} {node.code} has unknown parent {node.parent_code}"
                )

    def node(self, code: str) -> ApsNode:
        return self._by_code[code]

    def validate_decision(self, decision: ApsDecision) -> ApsDecision:
        for topic_code in decision.topic_codes:
            node = self._by_code.get(topic_code)
            if node is None or node.level != "topic":
                raise ValueError(f"Unknown APS topic code: {topic_code}")
            if node.parent_code not in decision.chapter_codes:
                raise ValueError(
                    f"APS topic {topic_code} requires chapter {node.parent_code} in the response"
                )
        for chapter_code in decision.chapter_codes:
            node = self._by_code.get(chapter_code)
            if node is None or node.level != "chapter":
                raise ValueError(f"Unknown APS chapter code: {chapter_code}")
        if decision.status == "assigned" and not decision.topic_codes:
            raise ValueError("Assigned APS decision requires at least one topic code")
        return decision

    def chapters(self) -> tuple[ApsNode, ...]:
        return tuple(node for node in self.nodes if node.level == "chapter")

    def domains(self) -> tuple[ApsNode, ...]:
        return tuple(node for node in self.nodes if node.level == "domain")

    def topics(self) -> tuple[ApsNode, ...]:
        return tuple(node for node in self.nodes if node.level == "topic")


class ApsRouter:
    def __init__(self, taxonomy: ApsTaxonomy):
        self.taxonomy = taxonomy

    def route(self, affair: Affair, max_chapters: int = 4, max_topics: int = 8) -> ApsRoute:
        text_terms = _tokens(affair.combined_text())
        if not text_terms:
            return ApsRoute(self.taxonomy.version, (), (), (), "no_text")

        topic_candidates = self._rank(self.taxonomy.topics(), text_terms, max_topics)
        chapter_candidates = self._rank(self.taxonomy.chapters(), text_terms, max_chapters)
        domain_candidates = self._rank(
            self.taxonomy.domains(), text_terms, len(self.taxonomy.domains())
        )
        if not chapter_candidates:
            return ApsRoute(
                self.taxonomy.version, domain_candidates, (), (), "no_taxonomy_term_match"
            )
        return ApsRoute(
            self.taxonomy.version, domain_candidates, chapter_candidates, topic_candidates
        )

    @staticmethod
    def _rank(
        nodes: tuple[ApsNode, ...], text_terms: set[str], limit: int
    ) -> tuple[ApsCandidate, ...]:
        ranked = []
        for node in nodes:
            matched = tuple(sorted(node.label_terms & text_terms))
            if matched:
                # Phrase labels receive a small bonus through the number of matched tokens;
                # this remains deterministic and language agnostic.
                score = len(matched) / max(len(node.label_terms), 1)
                ranked.append(ApsCandidate(node.code, node.level, round(score, 6), matched))
        ranked.sort(key=lambda item: (-item.score, item.code))
        return tuple(ranked[:limit])


def select_context(
    segments: list[TextSegment],
    route: ApsRoute,
    taxonomy: ApsTaxonomy,
    max_segments: int = 5,
) -> tuple[list[TextSegment], dict]:
    """Select a bounded, evidence-preserving context for a shadow experiment."""
    if max_segments < 1:
        raise ValueError("max_segments must be positive")
    candidate_codes = {
        candidate.code
        for candidate in (
            *route.domain_candidates,
            *route.chapter_candidates,
            *route.topic_candidates,
        )
    }
    candidate_terms = set()
    for code in candidate_codes:
        candidate_terms.update(taxonomy.node(code).label_terms)
    ranked: list[tuple[float, int, TextSegment]] = []
    title_segments = [segment for segment in segments if "-title-" in segment.segment_id]
    for segment in segments:
        overlap = _tokens(segment.text) & candidate_terms
        title_bonus = 1.0 if "-title-" in segment.segment_id else 0.0
        ranked.append((len(overlap) + title_bonus, -segment.position, segment))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = title_segments[:1]
    selected.extend(item[2] for item in ranked if item[2] not in selected)
    selected = selected[:max_segments]
    selected.sort(key=lambda segment: segment.position)
    before = sum(len(_tokens(segment.text)) for segment in segments)
    after = sum(len(_tokens(segment.text)) for segment in selected)
    return selected, {
        "input_segments": len(segments),
        "selected_segments": len(selected),
        "input_tokens_approx": before,
        "selected_tokens_approx": after,
        "compression_ratio": round(after / before, 6) if before else 1.0,
        "fallback_reason": route.fallback_reason,
    }


def build_aps_prompt(
    route: ApsRoute, taxonomy: ApsTaxonomy, segments: list[TextSegment]
) -> tuple[str, str]:
    """Build a bounded, evidence-grounded prompt for a future APS multi-label call."""
    candidates = [
        taxonomy.node(candidate.code)
        for candidate in (*route.chapter_candidates, *route.topic_candidates)
    ]
    candidate_lines = "\n".join(
        f"- {node.code}: "
        + " / ".join(f"{language}={label}" for language, label in node.labels.items())
        for node in candidates
    ) or "- none; return not_evaluable if the passages are insufficient"
    passage_lines = "\n\n".join(f"[{segment.segment_id}] {segment.text}" for segment in segments)
    system = (
        "You assign Swiss parliamentary affairs to the supplied APS hierarchy. "
        "Return JSON with exactly status, score, topic_codes, chapter_codes, explanation, "
        "and evidence_ids. Use only candidate codes and passage IDs. An affair may have "
        "multiple topics; every topic's parent chapter must be included."
    )
    user = f"""APS CANDIDATES\n{candidate_lines}\n\nAFFAIR PASSAGES\n{passage_lines}\n\n"""
    user += "Choose all materially supported APS topics and cite the supporting passage IDs."
    return system, user
