# ParlTopic — OpenParlData topic classification with Apertus

ParlTopic is an open, multilingual topic-classification service for Swiss parliamentary affairs. It combines retrieval over OpenParlData texts with Apertus v1.5 and returns a topic decision together with verifiable source passages.

**Challenge:** [Topic classification for Swiss parliaments with Apertus](https://app.sprintd.org/events/hack-apertus-liebefeld/cases/topic-classification-for-swiss-parliaments-with-apertus)

**Team:** Token Tell

**Status:** Working hackathon MVP with OpenParlData ingestion, frozen validation data, a
hybrid classifier, and reproducible evaluation commands.

## What the MVP does

- accepts parliamentary affairs in a small, versioned JSONL contract;
- defines standard or ad-hoc topics as YAML, without retraining;
- splits long affairs into stable text segments;
- retrieves the most relevant passages before inference;
- assigns explicit multilingual topic terms with a deterministic evidence-backed rule;
- sends the remaining semantic cases to Apertus v1.5 for neutral topic classification;
- returns evidence IDs that are resolved to original source text;
- distinguishes `uncertain`, `not_evaluable`, and technical `failed` results;
- exposes the same core through a CLI, FastAPI endpoint, and Streamlit demo.

The first validation use case is **digitalisation**. The architecture is designed for German, French, Italian, and Romansh; the initial quality report must publish results separately by language.

## Architecture

```text
OpenParlData API / export
          │
          ▼
 ingestion + normalisation
          │
          ▼
 stable affairs and text segments
          │
          ▼
 deterministic keyword gate ── clear match ──┐
          │ no match                         │
          ▼                                  │
 BM25 retrieval → Apertus classifier         │
          │                                  │
          └──────────────────────────────────┘
          │
          ▼
 validated result + original evidence
          │
     ┌────┼────┐
     ▼    ▼    ▼
    CLI  API   Streamlit
```

See [docs/architecture.md](docs/architecture.md) and [technical_report.md](technical_report.md) for boundaries, decisions, and the production-oriented target design.
Current development metrics and their limitations are recorded in
[docs/benchmark.md](docs/benchmark.md).

## Quick start

Requires Python 3.11 or newer.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make test
make demo
```

Add the CSCS API key to `.env`, then start the user interface:

```bash
make web
```

Or run the API:

```bash
make api
curl http://localhost:8000/health
```

Docker:

```bash
cp .env.example .env
docker compose up --build
```

## CLI contract

Offline validation, without an Apertus request:

```bash
parltopic classify \
  --input data/demo/affairs.jsonl \
  --topic configs/topics/digitalisation.yaml \
  --offline
```

Live classification:

```bash
parltopic classify \
  --input data/demo/affairs.jsonl \
  --topic configs/topics/digitalisation.yaml \
  --output results/digitalisation.jsonl
```

## Repository structure

```text
app/                    Streamlit demo
configs/topics/         Ad-hoc and standard topic definitions
data/demo/              Small redistributable demo inputs
docs/                   Architecture and implementation decisions
src/parltopic/          Reusable application core
tests/                  Offline unit tests
technical_report.md     Hackathon technical report
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `LLM_NAME` | Apertus model identifier |
| `LLM_BASE_URL` | OpenAI-compatible inference endpoint |
| `LLM_API_KEY` | Runtime API credential; never committed |
| `OPENPARLDATA_BASE_URL` | OpenParlData API root |
| `RETRIEVAL_TOP_K` | Maximum passages sent to Apertus |
| `CHUNK_SIZE` | Approximate passage size in characters |
| `CLASSIFIER_PROMPT_VERSION` | Versioned Apertus decision prompt |
| `CLASSIFIER_POLICY_VERSION` | Versioned end-to-end classifier policy |
| `KEYWORD_RESCUE_ENABLED` | Enable the deterministic high-precision gate |

All settings and safe defaults are documented in [.env.example](.env.example).

## Design principles

- **Evidence first:** the model selects passage IDs; the application returns the original text.
- **Neutrality:** the service classifies subject matter, not political merit or truth.
- **Explicit failure states:** infrastructure failures never become negative topic labels.
- **Reproducibility:** model, prompt version, token usage, and latency belong to every result.
- **Sovereign deployment:** application code and data processing can run on-premise or in a Swiss cloud with Apertus.

## Evaluation

Evaluation reports positive-class precision/recall/F1, macro-F1, confusion counts, coverage,
language and parliamentary-level slices, latency, and token use. Paired prompt/policy comparisons
include a bootstrap confidence interval. See [docs/evaluation_protocol.md](docs/evaluation_protocol.md)
for the important positive-unlabeled label limitation.

## Current limitations

- The checked-in OpenParlData client is deliberately thin until the exact API response contract is pinned with fixtures.
- BM25 is the reproducible baseline; multilingual embeddings remain a measured follow-up experiment.
- The included demo data is synthetic and cannot be used as evidence of classification quality.
- Romansh support is part of the schema but requires a dedicated labelled evaluation sample.

## Licence

Code is released under the [Apache License 2.0](LICENSE). Documentation is intended for CC-BY-4.0 as required by the event template.
