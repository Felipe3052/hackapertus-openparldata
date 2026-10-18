import math
import re
from collections import Counter

from parltopic.models import TextSegment, TopicDefinition

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text)]


def retrieve(
    segments: list[TextSegment], topic: TopicDefinition, top_k: int = 5
) -> list[tuple[TextSegment, float]]:
    if not segments:
        return []
    query = " ".join([topic.name, topic.description, *topic.synonyms])
    query_terms = set(_tokens(query))
    documents = [_tokens(segment.text) for segment in segments]
    document_frequency = Counter(term for doc in documents for term in set(doc))
    average_length = sum(map(len, documents)) / len(documents) or 1

    ranked: list[tuple[TextSegment, float]] = []
    for segment, document in zip(segments, documents, strict=True):
        frequencies = Counter(document)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            numerator = len(documents) - document_frequency[term] + 0.5
            inverse_frequency = math.log(
                1 + numerator / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(document) / average_length)
            score += inverse_frequency * frequency * 2.5 / denominator
        ranked.append((segment, score))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:top_k]

