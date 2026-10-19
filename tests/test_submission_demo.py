import hashlib
import importlib
import json
from pathlib import Path

from parltopic.models import Affair, ClassificationResult

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_original_examples_and_predictions_are_self_contained():
    manifest = json.loads((ROOT / "data/demo/jury/manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    affairs = [Affair.model_validate_json(line) for line in
               (ROOT / "data/demo/jury/affairs.jsonl").read_text().splitlines()]
    results = [ClassificationResult.model_validate_json(line) for line in
               (ROOT / "data/demo/jury/predictions.jsonl").read_text().splitlines()]
    assert {(a.language, a.level) for a in affairs} == {
        (language, level) for language in ("de", "fr", "it")
        for level in ("federal", "cantonal")
    }
    assert {a.affair_id for a in affairs} == {r.affair_id for r in results}
    assert len(affairs) == 9
    assert sum(result.status == "assigned" for result in results) == 6
    for result in results:
        assert result.status != "failed"


def test_search_respects_budget_retains_errors_and_invalidates_changed_topic(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from parltopic.compiler import CompiledTopic

    demo = AppTest.from_file(ROOT / "app/streamlit_app.py", default_timeout=10).run()
    demo.radio[0].set_value("Thema über Parlamente suchen").run()
    page = importlib.import_module("search_page")
    monkeypatch.setattr(page, "compile_topic", lambda topic, settings, **kwargs: CompiledTopic(
        topic_id=topic.topic_id, terms={"de": ["ChatGPT"]}, model="offline-fixture"
    ))
    monkeypatch.setattr(page, "newest_matches", lambda *args: [
        {"id": i, "score": 1, "date": "2026-01-01"} for i in range(20)
    ])
    fetched = []

    def fetch(identity, **kwargs):
        fetched.append(identity)
        raise RuntimeError("offline source failure")

    monkeypatch.setattr(page, "fetch_affair", fetch)
    next(b for b in demo.button if b.label.startswith("1 ·")).click().run()
    demo.slider[0].set_value(5).run()
    next(b for b in demo.button if b.label.startswith("2 ·")).click().run()
    assert not demo.exception
    assert len(fetched) == 5
    assert len(demo.session_state["s_hits"]) == 5
    assert all(r["status"] == "failed" for _, r in demo.session_state["s_hits"])
    assert demo.get("download_button")
    next(t for t in demo.text_input if t.label == "Thema").set_value("Anderes Thema").run()
    assert "s_compiled" not in demo.session_state
    assert "s_hits" not in demo.session_state


def test_offline_demo_replay_survives_without_network(monkeypatch):
    import httpx
    from streamlit.testing.v1 import AppTest

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline replay must not use the network")

    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    demo = AppTest.from_file(ROOT / "app/streamlit_app.py").run()
    next(b for b in demo.button if b.label.startswith("Historisches Ergebnis")).click().run()
    assert not demo.exception
    result = ClassificationResult.model_validate(demo.session_state["classification"])
    assert result.affair_id
    assert demo.get("download_button")


def test_review_preserves_exact_prediction_and_can_be_downloaded(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from parltopic import integration

    record = integration.record_review
    target = tmp_path / "reviews.jsonl"
    monkeypatch.setattr(integration, "record_review", lambda entry, path: record(entry, target))
    demo = AppTest.from_file(ROOT / "app/streamlit_app.py").run()
    next(b for b in demo.button if b.label.startswith("Historisches Ergebnis")).click().run()
    before = demo.session_state["classification"]
    next(w for w in demo.text_input if w.label.startswith("Kürzel")).set_value("fixture").run()
    next(w for w in demo.selectbox if w.label.startswith("Korrigierter Status")).select(
        "not_assigned"
    ).run()
    next(b for b in demo.button if b.label == "Vorschlag ablehnen").click().run()
    assert not demo.exception
    saved = json.loads(target.read_text())
    assert saved["prediction"] == before
    assert saved["prediction_id"] == integration.content_id(before)
    assert saved["corrected_status"] == "not_assigned"
    assert saved["context"]["historical_snapshot_id"]
    assert demo.session_state["classification"] == before
    assert any(b.label == "Prüfung als JSON sichern" for b in demo.get("download_button"))
