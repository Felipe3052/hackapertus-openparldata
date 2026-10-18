import pytest

from parltopic.classification.thinking import parse_answer


def test_answer_after_reasoning_marker_wins():
    content = 'I compare {"status": "assigned"} ... <|inner_suffix|>{"status": "not_assigned"}'
    assert parse_answer(content) == {"status": "not_assigned"}


def test_trailing_text_after_answer_is_ignored():
    assert parse_answer('{"status": "assigned", "score": 0.9}\nNote: {done}') == {
        "status": "assigned",
        "score": 0.9,
    }


def test_missing_answer_raises():
    with pytest.raises(ValueError):
        parse_answer("reasoning only, the token limit was reached")
