from pathlib import Path

import pytest

from parltopic.classification.prompts import build_user_prompt
from parltopic.models import Affair
from parltopic.retrieval.chunker import chunk_affair
from parltopic.topics import load_topic


def test_title_overlay_preserves_model_prompt_and_original_topic(tmp_path: Path):
    topic = tmp_path / "topic.yaml"
    overlay = tmp_path / "rules.yaml"
    topic.write_text("topic_id: digital\nname: Digitalisierung\ndescription: Digital affairs\n")
    overlay.write_text("title_synonyms: ['fake news']\n")
    baseline = load_topic(topic)
    candidate = load_topic(topic, overlay)
    assert baseline.title_synonyms == []
    assert candidate.title_synonyms == ["fake news"]
    segments = chunk_affair(Affair(affair_id="a", title="Example"))
    assert build_user_prompt(baseline, segments) == build_user_prompt(candidate, segments)
    overlay.write_text("title_synonyms: []\ndescription: Changed prompt\n")
    with pytest.raises(ValueError, match="only title_synonyms"):
        load_topic(topic, overlay)
