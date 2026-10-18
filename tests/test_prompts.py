import pytest

from parltopic.classification.prompts import system_prompt


def test_topic_v2_prompt_has_recall_and_evidence_guards() -> None:
    prompt = system_prompt("topic-v2")
    assert "Do not require the literal words" in prompt
    assert "assigned and uncertain require at least one evidence ID" in prompt
    assert "not_evaluable" in prompt


def test_unknown_prompt_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown prompt version"):
        system_prompt("unknown")
