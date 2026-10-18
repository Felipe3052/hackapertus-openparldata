import json
from pathlib import Path

from parltopic.aps import ApsRouter, ApsTaxonomy, select_context
from parltopic.evaluation.aps import evaluate_shadow
from parltopic.models import Affair
from parltopic.retrieval.chunker import chunk_affair

ROOT = Path(__file__).parents[1]


def test_aps_taxonomy_is_hierarchical_and_complete() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    assert len(taxonomy.topics()) == 165
    assert len(taxonomy.chapters()) == 22
    assert len(taxonomy.domains()) == 8
    assert all(node.parent_code in {chapter.code for chapter in taxonomy.chapters()}
               for node in taxonomy.topics())


def test_aps_router_is_deterministic_and_returns_candidates() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    affair = Affair(affair_id="a", title="Bundesrat und Parlament", text="Verwaltung und Kantone")
    router = ApsRouter(taxonomy)
    first = router.route(affair)
    second = router.route(affair)
    assert first == second
    assert first.chapter_candidates
    assert first.topic_candidates


def test_aps_context_selection_preserves_title_and_reports_compression() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    affair = Affair(
        affair_id="a",
        title="Digitale Verwaltung",
        text="Langer Kontext über Verwaltung und Kantone. " * 100,
    )
    route = ApsRouter(taxonomy).route(affair)
    selected, report = select_context(chunk_affair(affair, size=100, overlap=10), route, taxonomy)
    assert selected
    assert selected[0].text == affair.title
    assert report["selected_segments"] <= 5
    assert report["input_tokens_approx"] >= report["selected_tokens_approx"]


def test_aps_sample_has_expected_shape() -> None:
    sample = ROOT / "data/eval/e3_aps_sample.jsonl"
    rows = [json.loads(line) for line in sample.read_text().splitlines()]
    assert len(rows) == 50
    assert {row["language"] for row in rows} == {"de", "fr", "it"}
    assert {row["level"] for row in rows} == {"federal", "cantonal"}


def test_aps_shadow_evaluation_reports_diagnostic_warning() -> None:
    report = evaluate_shadow(
        ROOT / "data/eval/e3_aps_sample.jsonl",
        ROOT / "data/eval/e3_aps_labels.jsonl",
        ROOT / "configs/taxonomies/aps_topics.json",
    )
    assert report["sample_size"] == 50
    assert report["labelled_size"] == 20
    assert report["chapter_recall_at_k"] is not None
    assert "gold standard" in report["warning"]
