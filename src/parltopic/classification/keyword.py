"""Deterministic high-precision topic rule used by the hybrid classifier."""

import re

from parltopic.models import TextSegment, TopicDefinition


def _contains_term(text: str, term: str, online_variants: bool = False) -> bool:
    folded_text, folded_term = text.casefold(), term.casefold()
    if online_variants and folded_term == "online":
        # Recognize orthographic equivalents without altering source evidence or LLM input.
        # Keep historical compound matches (e.g. Onlinehandel); add separated variants only
        # at token boundaries so prose such as "on linear systems" is not a match.
        return folded_term in folded_text or re.search(
            r"(?<!\w)on[\s\u2010-\u2015-]+line(?!\w)", folded_text
        ) is not None
    # Short acronyms must be complete tokens: matching "nft" inside "Entwurf" would create
    # systematic false positives. Longer configured terms intentionally support morphology
    # such as digital/digitale/digitalizzazione through prefix matching.
    if folded_term.isalnum() and len(folded_term) <= 3:
        return re.search(rf"(?<!\w){re.escape(folded_term)}(?!\w)", folded_text) is not None
    return folded_term in folded_text


def first_keyword_hit(
    segments: list[TextSegment], topic: TopicDefinition, terms: list[str] | None = None
) -> tuple[TextSegment, str] | None:
    """Return the first segment and configured term with a case-insensitive match."""
    terms = [topic.name, *topic.synonyms] if terms is None else terms
    for segment in segments:
        for term in terms:
            if term.strip() and _contains_term(
                segment.text, term, online_variants=topic.normalize_online_variants
            ):
                return segment, term
    return None
