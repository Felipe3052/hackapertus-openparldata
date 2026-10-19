import json
from pathlib import Path

import pytest

from parltopic.aps import ApsDecision, ApsRouter, ApsTaxonomy, build_aps_prompt, select_context
from parltopic.evaluation.aps import (
    benchmark_context,
    build_consensus_labels,
    check_disjoint_ids,
    evaluate_shadow,
    make_annotation_template,
    merge_annotation_templates,
    regression_gate,
)
from parltopic.models import Affair
from parltopic.retrieval.chunker import chunk_affair

ROOT = Path(__file__).parents[1]


def test_aps_taxonomy_is_hierarchical_and_complete() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    assert len(taxonomy.topics()) == 165
    assert len(taxonomy.chapters()) == 22
    assert len(taxonomy.domains()) == 8
    coverage = taxonomy.language_coverage()
    assert coverage["de"] == {"domain": 8, "chapter": 22, "topic": 165}
    assert coverage["fr"] == {"domain": 8, "chapter": 22, "topic": 165}
    assert coverage["it"] == {"domain": 0, "chapter": 0, "topic": 0}
    assert all(node.parent_code in {chapter.code for chapter in taxonomy.chapters()}
               for node in taxonomy.topics())


def test_aps_taxonomy_supports_versioned_multilingual_aliases(tmp_path: Path) -> None:
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps(
            {
                "taxonomy_version": "aps-2026-10-18",
                "aliases": {
                    "1.2": {"it": ["amministrazione"]},
                    "1.2.2": {"it": ["amministrazione", "servizi pubblici"]},
                },
            }
        )
    )
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json", aliases_path=aliases)
    assert taxonomy.node("1.2.2").labels["it"] == "amministrazione / servizi pubblici"
    route = ApsRouter(taxonomy).route(
        Affair(affair_id="it-1", title="Amministrazione", language="it")
    )
    assert "1.2.2" in {candidate.code for candidate in route.topic_candidates}


def test_aps_aliases_must_match_taxonomy_version(tmp_path: Path) -> None:
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"taxonomy_version": "old", "aliases": {}}))
    with pytest.raises(ValueError, match="does not match"):
        ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json", aliases_path=aliases)


def test_aps_aliases_must_reference_known_codes(tmp_path: Path) -> None:
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps({"taxonomy_version": "aps-2026-10-18", "aliases": {"99.9.9": {"it": "x"}}})
    )
    with pytest.raises(ValueError, match="unknown codes"):
        ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json", aliases_path=aliases)


def test_aps_router_is_deterministic_and_returns_candidates() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    affair = Affair(affair_id="a", title="Bundesrat und Parlament", text="Verwaltung und Kantone")
    router = ApsRouter(taxonomy)
    first = router.route(affair)
    second = router.route(affair)
    assert first == second
    assert first.chapter_candidates
    assert first.topic_candidates


def test_aps_router_closes_topic_candidates_to_parent_chapters() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    affair = Affair(affair_id="a", title="Eintritt in den Kindergarten")
    route = ApsRouter(taxonomy).route(affair)
    topic_codes = {candidate.code for candidate in route.topic_candidates}
    chapter_codes = {candidate.code for candidate in route.chapter_candidates}
    assert "4.1.6" in topic_codes
    assert "4.1" in chapter_codes


def test_aps_router_matches_longer_word_forms_conservatively() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    route = ApsRouter(taxonomy).route(
        Affair(affair_id="a", title="Verwaltungsrechtliche Anpassung")
    )
    assert route.topic_candidates
    assert any("verwaltungs" in term for term in route.topic_candidates[0].matched_terms)


def test_aps_router_uses_affair_language_for_label_matching() -> None:
    taxonomy = ApsTaxonomy.load(ROOT / "configs/taxonomies/aps_topics.json")
    german = ApsRouter(taxonomy).route(
        Affair(affair_id="de-1", title="Verwaltung", language="de")
    )
    italian = ApsRouter(taxonomy).route(
        Affair(affair_id="it-1", title="Amministrazione", language="it")
    )
    assert german.topic_candidates
    assert italian.fallback_reason == "no_taxonomy_term_match"


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
    assert report["chapter_precision_at_k"] is not None
    assert "de|federal" in report["groups"]
    assert "gold standard" in report["warning"]


def test_aps_shadow_evaluation_identifies_consensus_labels(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "affair_id": "156860",
                "consensus": {"chapter": "4.1", "topic": "4.1.6", "none": False},
                "josip": {"chapter": "4.1", "topic": "4.1.6", "none": False},
            }
        )
        + "\n"
    )
    report = evaluate_shadow(
        ROOT / "data/eval/e3_aps_sample.jsonl",
        labels,
        ROOT / "configs/taxonomies/aps_topics.json",
        annotator="consensus",
    )
    assert "unanimous double annotations" in report["warning"]
    assert report["topic_precision_at_k"] is not None
    assert "de|cantonal" in report["groups"]


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


def test_aps_regression_gate_accepts_identical_runs(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    gold.write_text(
        '{"affair_id":"1","label":true,"language":"de","level":"federal"}\n'
        '{"affair_id":"2","label":false,"language":"fr","level":"cantonal"}\n'
    )
    results = (
        '{"affair_id":"1","status":"assigned"}\n'
        '{"affair_id":"2","status":"not_assigned"}\n'
    )
    baseline.write_text(results)
    candidate.write_text(results)
    report = regression_gate(gold, baseline, candidate)
    assert report["passed"] is True
    assert all(report["checks"].values())


def test_aps_annotation_template_is_stratified_and_excludes_ids(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    excluded = tmp_path / "excluded.jsonl"
    output = tmp_path / "annotation.jsonl"
    rows = [
        {"affair_id": str(i), "language": language, "level": level, "title": f"Case {i}"}
        for i, (language, level) in enumerate(
            [("de", "federal"), ("fr", "federal"), ("it", "cantonal"), ("de", "cantonal")]
            * 3
        )
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    excluded.write_text('{"affair_id":"0"}\n')
    report = make_annotation_template(source, output, (excluded,), sample_size=6, seed=7)
    selected = [json.loads(line) for line in output.read_text().splitlines()]
    assert report["selected"] == 6
    assert "0" not in {row["affair_id"] for row in selected}
    assert all(row["aps_annotation"]["topic_codes"] == [] for row in selected)
    assert {row["language"] for row in selected} == {"de", "fr", "it"}


def test_aps_consensus_builder_excludes_disputes(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    output = tmp_path / "consensus.jsonl"
    labels.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "affair_id": "1",
                        "felipe": {"chapter": "1.1", "topic": "1.1.1", "none": False},
                        "josip": {"chapter": "1.1", "topic": "1.1.1", "none": False},
                    }
                ),
                json.dumps(
                    {
                        "affair_id": "2",
                        "felipe": {"chapter": "1.1", "topic": "1.1.1", "none": False},
                        "josip": {"chapter": "2.1", "topic": "2.1.1", "none": False},
                    }
                ),
            ]
        )
        + "\n"
    )
    report = build_consensus_labels(labels, output)
    assert report["consensus_labels"] == 1
    assert report["disputed_affair_ids"] == ["2"]
    row = json.loads(output.read_text().strip())
    assert row["consensus"]["topic"] == "1.1.1"


def test_aps_consensus_builder_validates_taxonomy(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "affair_id": "1",
                "felipe": {"chapter": "1.1", "topic": "2.1.1", "none": False},
                "josip": {"chapter": "1.1", "topic": "2.1.1", "none": False},
            }
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="requires chapter"):
        build_consensus_labels(
            labels, tmp_path / "consensus.jsonl", ROOT / "configs/taxonomies/aps_topics.json"
        )


def test_aps_template_merge_requires_complete_unanimous_annotations(tmp_path: Path) -> None:
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    output = tmp_path / "consensus.jsonl"
    base = {
        "affair_id": "1",
        "aps_annotation": {
            "chapter_code": "1.1",
            "topic_codes": ["1.1.1"],
            "not_classifiable": False,
        },
    }
    left.write_text(json.dumps(base) + "\n")
    right.write_text(json.dumps(base) + "\n")
    report = merge_annotation_templates(left, right, output)
    assert report["consensus_labels"] == 1
    assert json.loads(output.read_text())["consensus"]["topic"] == "1.1.1"


def test_aps_template_merge_rejects_invalid_hierarchy(tmp_path: Path) -> None:
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    invalid = {
        "affair_id": "1",
        "aps_annotation": {
            "chapter_code": "1.1",
            "topic_codes": ["2.1.1"],
            "not_classifiable": False,
        },
    }
    left.write_text(json.dumps(invalid) + "\n")
    right.write_text(json.dumps(invalid) + "\n")
    with pytest.raises(ValueError, match="requires chapter"):
        merge_annotation_templates(
            left,
            right,
            tmp_path / "consensus.jsonl",
            ROOT / "configs/taxonomies/aps_topics.json",
        )
