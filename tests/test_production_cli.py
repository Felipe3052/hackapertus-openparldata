import json

from typer.testing import CliRunner

from parltopic import cli
from parltopic.config import Settings


def test_short_unlabelled_job_runs_and_resumes_without_scoring_or_inference(tmp_path, monkeypatch):
    source = tmp_path / "unlabelled.jsonl"
    source.write_text("\n".join(json.dumps({"affair_id": str(i), "title": "Digitalisierung"})
                                for i in range(3)), encoding="utf-8")
    topic = tmp_path / "topic.yaml"
    topic.write_text("topic_id: fixture\nname: Digitalisierung\ndescription: Digital topics\n")
    output = tmp_path / "results.jsonl"
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    args = ["run-eval", "--eval-set", str(source), "--topic", str(topic),
            "--output", str(output), "--workers", "1", "--limit", "2", "--no-score"]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 2
    assert all(row["input_tokens"] == 0 and row["status"] == "assigned" for row in rows)
    before = output.read_bytes()
    assert CliRunner().invoke(cli.app, args).exit_code == 0
    assert output.read_bytes() == before
