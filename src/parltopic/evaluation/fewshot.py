"""Retrieved few-shot examples: the most similar labelled affairs become the topic's examples.

The pool holds labelled affairs from 2018-2023 that are not in the dev sample
(data/eval/e1_fewshot_pool.jsonl), so no evaluated affair sees its own label.
"""

import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from parltopic.evaluation.run import read_rows
from parltopic.models import Affair, TopicDefinition

TOKEN_RE = re.compile(r"\w{3,}", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text)]


class FewShotIndex:
    def __init__(self, pool_path: str | Path, k1: float = 1.5, b: float = 0.75):
        self.rows = read_rows(pool_path)
        docs = [_tokens(f"{row['title']} {row['text'][:300]}") for row in self.rows]
        self.lengths = [len(doc) for doc in docs]
        self.avg = sum(self.lengths) / len(docs)
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, doc in enumerate(docs):
            for term, count in Counter(doc).items():
                self.postings[term].append((index, count))
        self.idf = {
            term: math.log(1 + (len(docs) - len(p) + 0.5) / (len(p) + 0.5))
            for term, p in self.postings.items()
        }

    def similar(self, affair: Affair, label: bool, k: int) -> list[dict]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(_tokens(f"{affair.title} {affair.text[:300]}")):
            for index, count in self.postings.get(term, ()):
                if bool(self.rows[index]["label"]) != label:
                    continue
                norm = count + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.avg)
                scores[index] += self.idf[term] * count * (self.k1 + 1) / norm
        best = sorted(scores, key=scores.get, reverse=True)[:k]
        return [
            self.rows[index] for index in best if self.rows[index]["affair_id"] != affair.affair_id
        ]

    def topic_for(self, topic: TopicDefinition, affair: Affair, k: int = 3) -> TopicDefinition:
        """Topic with the k most similar tagged and untagged affairs added as examples."""
        positives = [row["title"] for row in self.similar(affair, True, k)]
        negatives = [row["title"] for row in self.similar(affair, False, k)]
        return topic.model_copy(
            update={
                "positive_examples": [*topic.positive_examples, *positives],
                "negative_examples": [*topic.negative_examples, *negatives],
            }
        )
