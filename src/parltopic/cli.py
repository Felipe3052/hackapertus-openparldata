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


if __name__ == "__main__":
    app()

