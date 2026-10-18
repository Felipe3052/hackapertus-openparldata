"""Deterministic high-precision topic rule used by the hybrid classifier."""

import re

from parltopic.models import TextSegment, TopicDefinition


def _contains_term(text: str, term: str) -> bool:
    folded_text, folded_term = text.casefold(), term.casefold()
    # Short acronyms must be complete tokens: matching "nft" inside "Entwurf" would create
    # systematic false positives. Longer configured terms intentionally support morphology
    # such as digital/digitale/digitalizzazione through prefix matching.
    if folded_term.isalnum() and len(folded_term) <= 3:
        return re.search(rf"(?<!\w){re.escape(folded_term)}(?!\w)", folded_text) is not None
    return folded_term in folded_text


def first_keyword_hit(
    segments: list[TextSegment], topic: TopicDefinition
) -> tuple[TextSegment, str] | None:
    """Return the first segment and configured term with a case-insensitive match."""
    terms = [topic.name, *topic.synonyms]
    for segment in segments:
        for term in terms:
            if _contains_term(segment.text, term):
                return segment, term
    return None
