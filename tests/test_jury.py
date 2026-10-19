from pathlib import Path

import pytest

from parltopic.config import Settings
from parltopic.evaluation.jury import evaluate
from parltopic.evaluation.run import _run_manifest
from parltopic.models import TopicDefinition


def prediction(identity, status):
    return {"affair_id": identity, "topic_id": "test", "status": status,
            "language": "de", "model": "offline-test"}


def test_subgroup_coverage_includes_failures_and_missing():
    gold = [
        {"affair_id": "a", "label": True, "language": "de", "level": "federal"},
        {"affair_id": "b", "label": False, "language": "fr", "level": "cantonal"},
        {"affair_id": "c", "label": True, "language": "fr", "level": "cantonal"},
    ]
    report = evaluate(gold, [prediction("a", "not_assigned"), prediction("b", "failed")])
    assert report["overall"]["coverage"] == 1 / 3
    assert report["overall"]["metrics"]["fn"] == 1
    assert report["groups"]["language=fr"]["status_counts"] == {"failed": 1, "missing": 1}
    assert report["groups"]["language=it"]["coverage"] is None
    assert report["overall"]["metrics"]["classification_report"]["macro"] is None
    assert report["api_attempts"] is None
    assert report["tokens"]["complete"] is False


@pytest.mark.parametrize("label", [None, "false", 1])
def test_no_label_coercion(label):
    with pytest.raises(ValueError):
        evaluate([{"affair_id": "a", "label": label}], [])


def test_invalid_integration_output_fails():
    with pytest.raises(ValueError, match="Missing evidence"):
        evaluate([{"affair_id": "a", "label": True}], [prediction("a", "assigned")])


def test_manifest_records_effective_topic_prompt(tmp_path):
    dataset = tmp_path / "panel.jsonl"
    dataset.write_text("")
    topic = TopicDefinition(topic_id="test", name="test", description="test",
                            prompt_version="topic-v1", keyword_rule=False)
    manifest = _run_manifest(dataset, topic, Settings(_env_file=None))
    assert manifest["system_prompt"].startswith("You classify Swiss parliamentary")


def test_real_demo_loads_without_api(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from parltopic.classification.service import ClassificationService
    from parltopic.models import ClassificationResult

    seen = []

    def offline_classify(self, affair, topic):
        seen.append(topic)
        return ClassificationResult(
            affair_id=affair.affair_id, topic_id=topic.topic_id, language=affair.language,
            status="not_assigned", explanation="Offline transport fixture", model="fixture",
        )

    monkeypatch.setattr(ClassificationService, "classify", offline_classify)
    demo = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/streamlit_app.py").run()
    assert not demo.exception
    assert next(w for w in demo.text_input if w.label.startswith("Title")).value
    for language in ["fr", "it"]:
        next(w for w in demo.selectbox if w.label == "Example language").select(language).run()
        assert not demo.exception
        assert next(w for w in demo.selectbox if w.label == "Language").value == language
    demo.sidebar.selectbox[0].select("Custom topic").run()
    assert not demo.exception
    next(w for w in demo.button if w.label == "Classify with Apertus").click().run()
    assert not demo.exception
    assert seen[0].prompt_version == "topic-v1"
    assert seen[0].keyword_rule is False
    assert ClassificationResult.model_validate(demo.session_state["classification"])
    assert demo.get("download_button")


def test_search_mode_renders_without_api():
    from streamlit.testing.v1 import AppTest

    demo = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/streamlit_app.py",
                             default_timeout=10)
    demo.run()
    demo.radio[0].set_value("Search a topic across parliaments").run()
    assert not demo.exception
    assert any("search terms" in button.label for button in demo.button)
