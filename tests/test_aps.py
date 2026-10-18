import json
from pathlib import Path

import pytest

from parltopic.aps import ApsDecision, ApsRouter, ApsTaxonomy, build_aps_prompt, select_context
from parltopic.evaluation.aps import benchmark_context, check_disjoint_ids, evaluate_shadow
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


def test_aps_decision_requires_hierarchically_valid_codes() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    decision = ApsDecision(
        status="assigned",
        score=0.8,
        topic_codes=["1.2.2"],
        chapter_codes=["1.2"],
        explanation="Verwaltung ist Gegenstand des Geschäfts.",
        evidence_ids=["a-title"],
    )
    assert taxonomy.validate_decision(decision) == decision
    with pytest.raises(ValueError, match="requires chapter"):
        taxonomy.validate_decision(decision.model_copy(update={"chapter_codes": []}))


def test_aps_prompt_is_bounded_to_router_candidates_and_evidence() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    affair = Affair(affair_id="a", title="Verwaltung und Parlament", text="Kantone")
    router = ApsRouter(taxonomy)
    route = router.route(affair)
    selected = chunk_affair(affair)
    system, user = build_aps_prompt(route, taxonomy, selected)
    assert "topic_codes" in system
    assert all(candidate.code in user for candidate in route.topic_candidates)
    assert selected[0].segment_id in user


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


def test_aps_leakage_checker_detects_overlap_and_duplicates(tmp_path: Path) -> None:
    left = tmp_path / "dev.jsonl"
    right = tmp_path / "holdout.jsonl"
    left.write_text('{"affair_id":"1"}\n{"affair_id":"1"}\n')
    right.write_text('{"affair_id":"1"}\n{"affair_id":"2"}\n')
    report = check_disjoint_ids({"dev": left, "holdout": right})
    assert report["disjoint"] is False
    assert report["duplicates"]["dev"] == ["1"]
    assert report["overlaps"]["dev∩holdout"] == ["1"]


def test_aps_context_benchmark_compares_identical_affairs() -> None:
    report = benchmark_context(
        ROOT / "data/eval/e1_digitalisation_test.jsonl",
        ROOT / "configs/topics/digitalisation.yaml",
        ROOT / "configs/taxonomies/aps_topics.json",
        max_segments=2,
    )
    assert report["affairs"] == 1200
    assert report["aps_context"]["tokens_approx"] <= report["baseline"]["tokens_approx"]
    assert "No Apertus calls" in report["warning"]
