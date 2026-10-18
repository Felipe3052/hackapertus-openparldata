import json
from pathlib import Path
from typing import Annotated

import typer

from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.ingestion.jsonl import read_affairs
from parltopic.topics import load_topic

app = typer.Typer(help="ParlTopic command line interface")


@app.callback()
def main() -> None:
    """Run ParlTopic ingestion, classification, and evaluation commands."""


@app.command()
def classify(
    input: Annotated[Path, typer.Option(exists=True, readable=True)],
    topic: Annotated[Path, typer.Option(exists=True, readable=True)],
    output: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[
        bool, typer.Option(help="Validate and retrieve without calling Apertus.")
    ] = False,
) -> None:
    settings = get_settings()
    definition = load_topic(topic)
    service = ClassificationService(settings)
    rows = []
    for affair in read_affairs(input):
        if offline:
            row = {
                "affair_id": affair.affair_id,
                "topic_id": definition.topic_id,
                "status": "not_evaluable",
                "note": "Offline validation succeeded; no model call was made.",
            }
        else:
            row = service.classify(affair, definition).model_dump(mode="json")
        rows.append(row)
    rendered = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered, nl=False)


@app.command("download-data")
def download_data(
    raw_dir: Annotated[Path, typer.Option()] = Path("data/raw"),
    overwrite: bool = False,
) -> None:
    """Download OpenParlData exports and the hackathon label files (~350 MB)."""
    from parltopic.ingestion.opendata_export import download_raw

    for path in download_raw(raw_dir, overwrite):
        typer.echo(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")


@app.command("build-eval")
def build_eval(
    raw_dir: Annotated[Path, typer.Option(exists=True)] = Path("data/raw"),
    out_dir: Annotated[Path, typer.Option()] = Path("data/eval"),
    seed: int = 42,
) -> None:
    """Build the frozen eval sets E1 (digitalisation), E2 (Curia subject areas), E4 (DVS)."""
    from parltopic.evaluation.datasets import build_eval_sets

    typer.echo(json.dumps(build_eval_sets(raw_dir, out_dir, seed), indent=2))


@app.command("enrich-documents")
def enrich_documents(
    input: Annotated[Path, typer.Option(exists=True, readable=True)],
    output: Annotated[Path, typer.Option()],
    cache_dir: Path = Path("data/cache/documents"),
    workers: Annotated[int, typer.Option(min=1, max=8)] = 4,
) -> None:
    """Add original documents to title-only inputs, preserving labels and row order."""
    from parltopic.ingestion.enrich import enrich_dataset
    from parltopic.ingestion.openparldata_client import OpenParlDataClient

    report = enrich_dataset(input, output, OpenParlDataClient(get_settings()), cache_dir, workers)
    typer.echo(json.dumps(report, indent=2))


@app.command("run-eval")
def run_eval(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    topic: Annotated[Path, typer.Option(exists=True, readable=True)],
    output: Annotated[Path, typer.Option()],
    model: Annotated[str | None, typer.Option(help="Override LLM_NAME.")] = None,
    workers: int = 8,
    limit: int | None = None,
) -> None:
    """Classify an eval set with Apertus (resumable), then print the scores."""
    from parltopic.evaluation.run import run_classifier, score_results

    settings = get_settings()
    if model:
        settings = settings.model_copy(update={"llm_name": model})
    run_classifier(eval_set, load_topic(topic), output, settings, workers, limit)
    typer.echo(json.dumps(score_results(eval_set, output), indent=2))


@app.command()
def score(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    results: Annotated[Path, typer.Option(exists=True, readable=True)],
) -> None:
    """Score an existing results file against an eval set."""
    from parltopic.evaluation.run import score_results

    typer.echo(json.dumps(score_results(eval_set, results), indent=2))


@app.command("compare-runs")
def compare_run_outputs(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    baseline_results: Annotated[Path, typer.Option(exists=True, readable=True)],
    candidate_results: Annotated[Path, typer.Option(exists=True, readable=True)],
    samples: Annotated[int, typer.Option(min=1)] = 2_000,
    seed: int = 42,
) -> None:
    """Paired bootstrap comparison of macro-F1 for two runs on the same examples."""
    from parltopic.evaluation.compare import compare_runs

    report = compare_runs(
        eval_set, baseline_results, candidate_results, samples=samples, seed=seed
    )
    typer.echo(json.dumps(report, indent=2))


@app.command("score-confidence")
def score_confidence(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    results: Annotated[Path, typer.Option(exists=True, readable=True)],
    samples: Annotated[int, typer.Option(min=1)] = 2000,
    seed: int = 42,
) -> None:
    """Report class-stratified bootstrap intervals for precision, recall and F1."""
    from parltopic.evaluation.uncertainty import bootstrap_metrics

    typer.echo(json.dumps(bootstrap_metrics(eval_set, results, samples, seed), indent=2))


@app.command()
def baseline(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    topic: Annotated[Path, typer.Option(exists=True, readable=True)],
) -> None:
    """Baseline B0: multilingual keyword match on name + synonyms (full-text search), no LLM."""
    from parltopic.evaluation.run import keyword_predictions, score_binary

    predictions = keyword_predictions(eval_set, load_topic(topic))
    typer.echo(json.dumps(score_binary(eval_set, predictions), indent=2))


if __name__ == "__main__":
    app()

