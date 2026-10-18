import json
from collections.abc import Iterator
from pathlib import Path

from parltopic.models import Affair


def read_affairs(path: str | Path) -> Iterator[Affair]:
    with Path(path).open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if line.strip():
                try:
                    yield Affair.model_validate_json(line)
                except ValueError as error:
                    raise ValueError(f"Invalid affair on line {line_number}: {error}") from error


def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

