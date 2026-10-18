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


@app.command("run-eval")
def run_eval(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    topic: Annotated[Path, typer.Option(exists=True, readable=True)],
    output: Annotated[Path, typer.Option()],
    model: Annotated[str | None, typer.Option(help="Override LLM_NAME.")] = None,
    workers: int = 8,
    limit: int | None = None,
    fewshot_pool: Annotated[
        Path | None, typer.Option(help="Add the k most similar labelled affairs as examples.")
    ] = None,
    fewshot_k: int = 3,
) -> None:
    """Classify an eval set with Apertus (resumable), then print the scores."""
    from parltopic.evaluation.run import run_classifier, score_results

    settings = get_settings()
    if model:
        settings = settings.model_copy(update={"llm_name": model})
    definition = load_topic(topic)
    topic_for = None
    if fewshot_pool:
        from parltopic.evaluation.fewshot import FewShotIndex

        index = FewShotIndex(fewshot_pool)
        topic_for = lambda affair: index.topic_for(definition, affair, fewshot_k)  # noqa: E731
    run_classifier(eval_set, definition, output, settings, workers, limit, topic_for)
    typer.echo(json.dumps(score_results(eval_set, output), indent=2))


@app.command()
def rethink(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    topic: Annotated[Path, typer.Option(exists=True, readable=True)],
    base: Annotated[Path, typer.Option(exists=True, readable=True, help="Fast-pass results.")],
    output: Annotated[Path, typer.Option()],
    workers: int = 8,
) -> None:
    """Re-check not_assigned answers with Apertus reasoning (thinking), then print the scores."""
    from parltopic.evaluation.run import run_rethink, score_results

    run_rethink(eval_set, load_topic(topic), base, output, get_settings(), workers)
    typer.echo(json.dumps(score_results(eval_set, output), indent=2))


@app.command()
def compare(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    results: Annotated[list[Path], typer.Argument(exists=True, readable=True)],
) -> None:
    """Markdown table of several results files on one eval set (for docs/experiments.md)."""
    from parltopic.evaluation.run import score_results

    groups = ["all", "lang=de", "lang=fr", "lang=it", "level=federal", "level=cantonal"]
    header = " | ".join(f"F1 {g}" for g in groups[1:])
    typer.echo(f"| Run | P | R | F1 | {header} | tokens in/out per affair |")
    typer.echo("|---" * (len(groups) + 4) + "|")
    for path in results:
        report = score_results(eval_set, path)
        assigned, usage = report["assigned"], report["usage_per_1000_affairs"]
        cells = [
            f"{assigned['all']['precision']:.3f}",
            f"{assigned['all']['recall']:.3f}",
            f"**{assigned['all']['f1']:.3f}**",
            *(f"{assigned[g]['f1']:.3f}" if g in assigned else "-" for g in groups[1:]),
            f"{usage['input_tokens'] // 1000} / {usage['output_tokens'] // 1000}",
        ]
        typer.echo(f"| {path.stem} | " + " | ".join(cells) + " |")


@app.command()
def score(
    eval_set: Annotated[Path, typer.Option(exists=True, readable=True)],
    results: Annotated[Path, typer.Option(exists=True, readable=True)],
) -> None:
    """Score an existing results file against an eval set."""
    from parltopic.evaluation.run import score_results

    typer.echo(json.dumps(score_results(eval_set, results), indent=2))


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

