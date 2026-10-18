import json

from parltopic.config import Settings
from parltopic.evaluation import run
from parltopic.models import ClassificationResult, TopicDefinition


def test_runner_retains_per_affair_topics_and_closes_shared_service(tmp_path, monkeypatch):
    events = []

    class StubService:
        def __init__(self, settings):
            events.append("created")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("closed")

        def classify(self, affair, topic):
            events.append((affair.affair_id, topic.topic_id))
            return ClassificationResult(
                affair_id=affair.affair_id, topic_id=topic.topic_id, status="not_assigned",
                language=affair.language, model="offline-stub",
            )

    dataset = tmp_path / "input.jsonl"
    dataset.write_text(json.dumps({"affair_id": "1", "title": "Hospital", "label": False})
                       + "\n", encoding="utf-8")
    output = tmp_path / "output.jsonl"
    topic = TopicDefinition(topic_id="base", name="Base", description="Base topic")
    monkeypatch.setattr(run, "ClassificationService", StubService)
    run.run_classifier(
        dataset, topic, output, Settings(_env_file=None), workers=1,
        topic_for=lambda affair: topic.model_copy(update={"topic_id": "per-affair"}),
    )
    assert events == ["created", ("1", "per-affair"), "closed"]
    assert json.loads(output.read_text("utf-8"))["topic_id"] == "per-affair"
