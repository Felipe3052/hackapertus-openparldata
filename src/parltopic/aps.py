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

from parltopic.models import Affair, TextSegment

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
TAXONOMY_VERSION = "aps-2026-10-18"


def _tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return {token for token in TOKEN_RE.findall(normalized) if len(token) > 2}


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


@dataclass(frozen=True)
class ApsRoute:
    taxonomy_version: str
    chapter_candidates: tuple[ApsCandidate, ...]
    topic_candidates: tuple[ApsCandidate, ...]
    fallback_reason: str | None = None

    def model_dump(self) -> dict:
        return {
            "taxonomy_version": self.taxonomy_version,
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
    def load(cls, path: Path, version: str = TAXONOMY_VERSION) -> "ApsTaxonomy":
        raw = json.loads(path.read_text(encoding="utf-8"))
        nodes: list[ApsNode] = []
        chapter_labels: dict[str, dict[str, str]] = {}
        for item in raw:
            code = str(item["code"])
            parts = code.split(".")
            level = "topic" if len(parts) == 3 else "chapter"
            parent_code = str(item.get("chapter_code")) if level == "topic" else None
            labels = {
                key[7:]: str(value)
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
            nodes.append(ApsNode(code, parent_code, level, labels, item.get("url_de")))
            if parent_code:
                chapter_labels[parent_code] = {
                    key[8:]: str(value)
                    for key, value in item.items()
                    if key.startswith("chapter_") and value
                }

        # The source file contains topic rows and derives chapter/domain names from them.
        chapter_codes = {node.parent_code for node in nodes if node.parent_code}
        for code in sorted(chapter_codes):
            nodes.append(ApsNode(code, None, "chapter", chapter_labels.get(code, {})))
        return cls(tuple(nodes), version)

    def _validate(self) -> None:
        if len(self._by_code) != len(self.nodes):
            raise ValueError("APS taxonomy contains duplicate codes")
        for node in self.nodes:
            if node.level == "topic" and node.parent_code not in self._by_code:
                raise ValueError(f"APS topic {node.code} has unknown chapter {node.parent_code}")

    def node(self, code: str) -> ApsNode:
        return self._by_code[code]

    def chapters(self) -> tuple[ApsNode, ...]:
        return tuple(node for node in self.nodes if node.level == "chapter")

    def topics(self) -> tuple[ApsNode, ...]:
        return tuple(node for node in self.nodes if node.level == "topic")


class ApsRouter:
    def __init__(self, taxonomy: ApsTaxonomy):
        self.taxonomy = taxonomy

    def route(self, affair: Affair, max_chapters: int = 4, max_topics: int = 8) -> ApsRoute:
        text_terms = _tokens(affair.combined_text())
        if not text_terms:
            return ApsRoute(self.taxonomy.version, (), (), "no_text")

        topic_candidates = self._rank(self.taxonomy.topics(), text_terms, max_topics)
        chapter_candidates = self._rank(self.taxonomy.chapters(), text_terms, max_chapters)
        if not chapter_candidates:
            return ApsRoute(self.taxonomy.version, (), (), "no_taxonomy_term_match")
        return ApsRoute(self.taxonomy.version, chapter_candidates, topic_candidates)

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
    candidate_codes = {candidate.code for candidate in route.topic_candidates}
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
