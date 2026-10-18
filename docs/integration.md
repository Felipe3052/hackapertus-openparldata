# Integration into OpenParlData

ParlTopic adds topic suggestions next to OpenParlData's affairs; it never changes source data.

## Table

[`integration/opd/001_affair_topics.sql`](../integration/opd/001_affair_topics.sql) creates two
PostgreSQL tables:

- `topics`: one row per topic with its YAML definition, the compiled search terms and a
  `topic_version` hash. Editing a topic creates a new version; old suggestions stay attributable.
- `affair_topics`: one row per affair, topic and topic version with status, explanation, the
  original evidence text, its document ID and link, model, prompt and classifier version and
  tokens. `review_decision`, `reviewed_by` and `reviewed_at` hold the human check (confirmed /
  rejected); a review never deletes the suggestion.

Failed calls are not exported: they are a technical state, not a topic decision.

## Commands

```bash
# one affair, live from api.openparldata.ch
parltopic classify-affair 303044 --topic configs/topics/digitalisation.yaml

# batch over an eval set or any Affair JSONL, then rows for affair_topics
parltopic run-eval --eval-set data/eval/e1_digitalisation_test.jsonl \
  --topic configs/topics/digitalisation.yaml --output results/run.jsonl
parltopic export-opd --results results/run.jsonl \
  --topic configs/topics/digitalisation.yaml --output out/affair_topics.ndjson
# -> out/affair_topics.ndjson (rows) and out/affair_topics.ndjson.topic.json (topics row)

# ad-hoc topic: Apertus writes the search terms once, a person can edit them
parltopic compile-topic --topic configs/topics/adhoc/health.yaml --output topics/health.json
parltopic find --topic configs/topics/adhoc/health.yaml --compiled topics/health.json \
  --bodies CHE,BE,ZH --from 2026-01-01 --output results/health_2026.jsonl
```

## Apache Hop

OpenParlData's ETL runs on Apache Hop. A nightly pipeline needs three transforms:

1. **Table input** — affairs updated since the last run (`updated_at > :last_run`).
2. **Execute process / Shell** — `parltopic run-eval` (or `classify-affair` per ID) on those
   affairs, one call per active topic; output NDJSON via `parltopic export-opd`.
3. **JSON input → Table output** — load the NDJSON into `affair_topics` (insert only; the
   primary key `(affair_id, topic_id, topic_version)` makes reruns idempotent).

The FastAPI service (`make api`, `POST /classify`) is the alternative for a REST client
transform. All calls go to an OpenAI-compatible Apertus endpoint (`LLM_BASE_URL`): CSCS, a Swiss
provider or a local vLLM server.

## Search: one change on OpenParlData's side would help

OpenParlData's boolean full-text search is fast for the first pages, but it has no prefix
matching (`digital:*` returns no result), so German compounds such as
"Digitalisierungsstrategie" are missed, and it ignores `date_from`/`date_to` and slows down at
deep offsets (about 60 s per page at offset 5,000). Supporting `:*` prefixes and date filters in
the search endpoint would let any topic query run as a cheap first pass over all affairs.
