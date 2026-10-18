"""Short, isolated export/import check. Requires Docker; uses synthetic data, no inference."""

import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from parltopic.integration import export
from parltopic.models import ClassificationResult, Evidence, TopicDefinition

ROOT = Path(__file__).resolve().parents[1]


def main():
    name = f"parltopic-import-{uuid.uuid4().hex[:12]}"
    subprocess.run([
        "docker", "run", "--rm", "-d", "--network", "none", "--name", name,
        "-e", "POSTGRES_PASSWORD=offline-fixture", "postgres:16-alpine",
    ], check=True, stdout=subprocess.DEVNULL)
    try:
        for _ in range(75):
            ready = subprocess.run([
                "docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres",
            ], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError("PostgreSQL did not become ready within 15 seconds")

        def sql(statement):
            completed = subprocess.run([
                "docker", "exec", "-i", name, "psql", "-U", "postgres",
                "-v", "ON_ERROR_STOP=1", "-At",
            ], input=statement, text=True, capture_output=True, check=True)
            return completed.stdout.strip()

        sql((ROOT / "integration/opd/001_affair_topics.sql").read_text("utf-8"))

        def quoted(value):
            return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"

        with tempfile.TemporaryDirectory(prefix="parltopic-import-") as folder:
            root = Path(folder)
            for number in (1, 2):
                topic = TopicDefinition(topic_id="fixture", name="Offline fixture",
                                        description=f"Synthetic definition {number}")
                result = ClassificationResult(
                    affair_id="42", topic_id="fixture", status="assigned", language="fr",
                    model="offline-fixture", explanation="Synthetic transport result",
                    evidence=[Evidence(segment_id="a", text="First synthetic passage"),
                              Evidence(segment_id="b", text="Second synthetic passage")],
                )
                source = root / f"run{number}.jsonl"
                source.write_text(result.model_dump_json() + "\n", encoding="utf-8")
                source.with_suffix(".jsonl.manifest.json").write_text(json.dumps({
                    "topic": topic.model_dump(mode="json"), "dataset_sha256": "fixture",
                }), encoding="utf-8")
                out = root / f"export{number}.jsonl"
                export(source, topic, out)
                definition = json.loads(Path(str(out) + ".topic.json").read_text())
                rows = [json.loads(line) for line in out.read_text().splitlines()]
                d = quoted(definition)
                sql("INSERT INTO topics (topic_id, name) VALUES ('fixture', 'Offline fixture') "
                    "ON CONFLICT DO NOTHING;")
                sql("INSERT INTO topic_versions (topic_id, name, definition, compiled_query, "
                    f"topic_version) SELECT j->>'topic_id', j->>'name', j->'definition', "
                    f"j->'compiled_query', j->>'topic_version' FROM (SELECT {d} AS j) x;")
                columns = ", ".join(rows[0])
                insert = (f"INSERT INTO affair_topics ({columns}) SELECT {columns} FROM "
                          f"jsonb_populate_recordset(NULL::affair_topics, {quoted(rows)}) "
                          "ON CONFLICT DO NOTHING;")
                sql(insert)
                sql(insert)  # Repeat imports must not multiply the original suggestions.
            assert sql("SELECT count(*) FROM topic_versions;") == "2"
            assert sql("SELECT count(*) FROM affair_topics;") == "2"
            assert sql("SELECT min(jsonb_array_length(evidence)) FROM affair_topics;") == "2"
            sql("""DO $$ BEGIN
                BEGIN
                    INSERT INTO affair_topics
                        (affair_id, topic_id, topic_version, run_id, prediction_id, status, model)
                    VALUES (43, 'fixture', 'unknown', 'bad', 'bad', 'assigned', 'fixture');
                    RAISE EXCEPTION 'Missing topic-version foreign-key enforcement';
                EXCEPTION WHEN foreign_key_violation THEN NULL;
                END;
            END $$;""")
        print(json.dumps({"passed": True, "fixture": "synthetic, no inference",
                          "topic_versions": 2, "predictions_after_repeat_import": 2,
                          "evidence_per_prediction": 2, "foreign_key_enforced": True}))
    finally:
        subprocess.run(["docker", "stop", name], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
