"""Evaluate the topic compiler on the full E1 population, not only on the balanced sample.

Population: every affair of the PolitMonitor parliaments and affair types in the test period
(2024-2026), the same eligibility as E1 (`meta.json`: 37,258 affairs, 853 tagged). Stage 1 is the
compiled query on OpenParlData's search; stage 2 is the frozen classifier on the candidates.
"""

import json
from collections import Counter
from pathlib import Path

from parltopic.evaluation.datasets import MIN_TYPE_POSITIVES, _in_split
from parltopic.evaluation.run import read_rows
from parltopic.ingestion.opendata_export import available_languages, read_csv, read_ndjson


def population(raw_dir: str | Path, split: str = "test") -> tuple[set[int], set[int]]:
    """(eligible IDs, tagged IDs among them), as `build_eval_sets` (historical eligibility)."""
    raw = Path(raw_dir)
    tagged = {int(r["openparldata_id"]) for r in read_csv(raw / "politmonitor_digitalisierung.csv")}
    affairs = {r["id"]: r for r in read_ndjson(raw / "affairs.ndjson.gz")}
    positives = [affairs[i] for i in tagged if i in affairs]
    bodies = Counter(r["body_key"] for r in positives)
    types = Counter(r["type_harmonized_en"] for r in positives)
    keep_types = {t for t, n in types.items() if n >= MIN_TYPE_POSITIVES}
    eligible = {
        r["id"]
        for r in affairs.values()
        if r["body_key"] in bodies
        and r["type_harmonized_en"] in keep_types
        and _in_split(r.get("begin_date"), split)
        and available_languages(r)
    }
    return eligible, eligible & tagged


def evaluate(
    raw_dir: str | Path,
    candidates_path: str | Path,
    sample_eval: str | Path,
    sample_results: str | Path,
    scope: str = "all",
) -> dict:
    eligible, tagged = population(raw_dir)
    found = json.loads(Path(candidates_path).read_text("utf-8"))[scope]
    candidates = set().union(*map(set, found["ids"].values())) & eligible
    per_language = {lang: len(set(ids) & eligible) for lang, ids in found["ids"].items()}

    sample = {row["affair_id"]: bool(row["label"]) for row in read_rows(sample_eval)}
    decided = {
        row["affair_id"]: row["status"] == "assigned"
        for row in read_rows(sample_results)
        if row["status"] in ("assigned", "not_assigned")
    }

    def scores(predicted: dict[str, bool]) -> dict:
        tp = sum(predicted[i] and sample[i] for i in predicted)
        fp = sum(predicted[i] and not sample[i] for i in predicted)
        fn = sum(not predicted[i] and sample[i] for i in predicted)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"n": len(predicted), "tp": tp, "fp": fp, "fn": fn, "precision": round(p, 3),
                "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}

    staged = {i: decided[i] and int(i) in candidates for i in decided}
    return {
        "population": {"affairs": len(eligible), "tagged": len(tagged)},
        "stage1": {
            "scope": scope,
            "search_seconds": found["seconds"],
            "candidates": len(candidates),
            "share_of_population": round(len(candidates) / len(eligible), 4),
            "tagged_found": len(candidates & tagged),
            "candidate_recall": round(len(candidates & tagged) / len(tagged), 3),
            "per_language_candidates": per_language,
        },
        "sample": {
            "frozen_classifier_only": scores(decided),
            "compiled_query_then_classifier": scores(staged),
            "candidate_recall_on_sample_positives": round(
                sum(int(i) in candidates for i, y in sample.items() if y)
                / sum(sample.values()), 3),
        },
    }


def build_population_set(
    raw_dir: str | Path, ids: set[int], out_path: str | Path, split: str = "test"
) -> dict:
    """Affair rows (title, federal text, language, level, PolitMonitor label) for the given IDs.

    Federal affairs are read in German here; the balanced sample used a random DE/FR/IT version.
    """
    from parltopic.ingestion.opendata_export import load_bodies, load_che_texts, to_affair

    raw = Path(raw_dir)
    _, tagged = population(raw, split)
    bodies = load_bodies(raw)
    records = [r for r in read_ndjson(raw / "affairs.ndjson.gz") if r["id"] in ids]
    texts = load_che_texts(raw, {r["id"] for r in records if r["body_key"] == "CHE"})
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as file:
        for record in records:
            language = "de" if record["body_key"] == "CHE" else None
            text = texts.get(record["id"], {}).get("de", "")
            affair = to_affair(record, bodies.get(record["body_key"]), language=language, text=text)
            if affair:
                row = {**affair.model_dump(mode="json"), "label": record["id"] in tagged}
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
    return {"affairs": written, "tagged": sum(1 for i in ids if i in tagged)}
