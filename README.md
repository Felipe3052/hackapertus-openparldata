# ParlTopic — topic classification for Swiss parliaments with Apertus

**Hack Apertus Liebefeld 2026 · Challenge 2: OpenParlData · Team Token Tell (Felipe Wüthrich, Josip Jukic)**

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Apertus v1.5 70B](https://img.shields.io/badge/Apertus-v1.5_70B-DC2626?style=for-the-badge)
![PostgreSQL integration](https://img.shields.io/badge/PostgreSQL-Integration-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)

ParlTopic tells you which Swiss parliamentary affairs belong to a topic, in German, French and
Italian, across federal, cantonal and municipal parliaments. You describe a topic in a short YAML
file; Apertus v1.5 decides for each affair and cites the passage that justifies the decision. New
topics need no training.

- **Challenge:** [Topic classification for Swiss parliaments with Apertus](https://app.sprintd.org/events/hack-apertus-liebefeld/cases/topic-classification-for-swiss-parliaments-with-apertus)
- **Technical report:** [technical_report.md](technical_report.md) · **Experiment log:** [docs/experiments.md](docs/experiments.md) · **Benchmark notes:** [docs/benchmark.md](docs/benchmark.md)
- **Demo:** `make run` starts the bundled historical replay without an API key.

> Topic labels are suggestions about subject matter. They do not judge political positions, and a
> person should confirm them before they are published.

---

## Results

Use case of the challenge: Digital Administration Switzerland (DVS) lists digitalisation affairs
by hand, based on the PolitMonitor editorial tag. Model: `swiss-ai/Apertus-v1.5-70B` on CSCS.

| Evaluation set | Keyword search | **ParlTopic** | Notes |
|---|---:|---:|---|
| Digitalisation, 1,200 affairs 2024–2026, positive-class F1 | 0.674 | **0.876** | positive-class precision 0.875, recall 0.877; Macro-F1 0.907 |
| … F1 German / French / Italian | 0.64 / 0.68 / 0.76 | **0.90 / 0.85 / 0.85** | official translations of federal affairs |
| Current DVS list (30 affairs), found | 19 | **27** | federal and cantonal |
| Ad-hoc topic *migration*, F1 | 0.717 | **0.874** | exploratory; scored against Curia Vista subject labels |
| Ad-hoc topic *health*, F1 | 0.571 | **0.805** | exploratory; scored against Curia Vista subject labels |
| Ad-hoc topic *transport*, F1 | 0.545 | **0.784** | exploratory; scored against Curia Vista subject labels |

Keyword search uses the same multilingual terms as the topic file. The digitalisation labels are
editorial tags without checked negatives, so precision is a proxy estimate that may miss label gaps.
The sample is one third positive; in the whole corpus only 2.3 % of the affairs are tagged. At
that base rate, the measured recall and the observed false-positive rate imply an estimated
precision of about one in four suggestions; this is a base-rate projection, not a directly
adjudicated production precision. ParlTopic is a suggestion list for editors to review.
Configuration and prompts were chosen on a separate 2018–2023 split; see the
[technical report](technical_report.md) for the protocol, the ablations, the bias check and costs.
Further documentation: [performance and scale measurements](docs/performance.md) ([methodology](docs/performance_methodology.md)),
the [independent evaluation audit](docs/evaluation_audit.md) and the [evaluation protocol](docs/evaluation_protocol.md).

The 1,200-affair set is an opened validation benchmark rather than a sealed final holdout.
DVS contains positive editorial tags but no fully adjudicated negative set, so its 27/30 result
is a discovery rate, not a precision estimate. The ad-hoc topic results use Curia Vista labels
and are not APS model evaluations. The 300,000-affair runtime is documented as a projection;
no full-corpus run was executed.

---

## How it works

```text
OpenParlData export / API ─► normalise affair (title, text, documents, language, level)
        │
        ▼
 multilingual term rule ── term found ──► assigned, cites the segment (no model call)
        │ no match
        ▼
 BM25 → 5 passages ─► Apertus v1.5 70B → {status, score, explanation, evidence_ids}
        │
        ▼
 strict validation → result with original evidence text and link
        │
   CLI · FastAPI · Streamlit
```

- **Topics as YAML** (`configs/topics/`): name, description with an inclusion rule, DE/FR/IT terms,
  in- and out-of-scope examples, and the topic's own policy. `digitalisation.yaml` is the curated,
  validated topic (term rule on, prompt v2); `adhoc/` has three topics written without tuning
  (`prompt_version: topic-v1`, `keyword_rule: false`, because quickly chosen terms are too broad).
- **Evidence first:** Apertus returns passage IDs, the service returns the original text, its
  document ID and link.
- **Explicit states:** `assigned`, `not_assigned`, `uncertain` and `not_evaluable` are model
  decisions; `failed` is a technical error and never counts as a negative.
- **Every result** carries model, prompt and policy version, tokens and latency; every evaluation
  run has a manifest with dataset, topic, prompt and source hashes.

---

## Quick start

Jury walkthrough with real DE/FR/IT affairs, historical replay, custom topics and JSON export:
[docs/jury_demo.md](docs/jury_demo.md). It includes independently recalculated local results,
subgroup coverage, missing APS references and the limits of the 300k projection.

Requires Python 3.11 or newer.

For a short jury walkthrough without a key, local datasets or inference charges, run
`make run` (Docker, port 8501). Six original DE/FR/IT examples and historical predictions are
bundled. Select **Historisches Ergebnis (ohne API)** for offline replay. Live searches are bounded
candidate lists, not complete corpus classifications. The current submission scope uses short
functional checks; 300k runtimes remain projections, not a completed full-corpus run.

For live classification with an existing `parltopic-jury` image and a configured `.env`, use
`make run-live` after installing the Python dependencies below. Stop the offline container
first to free port 8501. This command parses quoted dotenv values correctly and passes secrets
through environment variables. Docker's raw `--env-file .env` preserves surrounding quotes,
which can cause authentication failures when keys or model names are quoted.

```bash
cp .env.example .env          # add LLM_API_KEY for the CSCS endpoint
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
make test                     # unit tests, no API calls
make demo                     # validates the demo records offline
```

Classify affairs:

```bash
parltopic classify --input data/demo/affairs.jsonl \
  --topic configs/topics/digitalisation.yaml --output results/digitalisation.jsonl
```

Classify one affair live from the OpenParlData API (title, federal texts, first documents):

```bash
parltopic classify-affair 303044 --topic configs/topics/digitalisation.yaml
```

Rows for OpenParlData's `affair_topics` table (schema, review fields and Apache Hop pipeline:
[docs/integration.md](docs/integration.md)):

```bash
parltopic export-opd --results results/digitalisation.jsonl   --topic configs/topics/digitalisation.yaml --output out/affair_topics.ndjson
```

User interface and API. The demo has two modes: *Einzelnes Geschäft* loads an affair by its
OpenParlData ID, classifies it and stores a reviewer's confirm / reject decision; *Thema über
Parlamente suchen* turns one sentence into search terms in four languages (Apertus), takes the
newest matches from OpenParlData's search per parliament and lets Apertus check them, with the
original passage for every hit. Pitch and demo script: [docs/pitch.md](docs/pitch.md).

```bash
make web                      # Streamlit
make api                      # FastAPI, then: curl http://localhost:8000/health
docker compose up --build     # both in containers
```

---

## Reproduce the evaluation

Every number above can be recomputed from the published prediction files, without API calls:

```bash
parltopic fetch-results      # prediction files + manifests from the release results-2026-10-19
parltopic claims             # recomputes each stated number; exits 1 on any mismatch
```

To rerun the experiments themselves:

```bash
parltopic download-data                       # OpenParlData exports + hackathon labels, ~350 MB
parltopic build-eval --out-dir data/processed/eval   # same files as data/eval, byte for byte
parltopic baseline --eval-set data/eval/e1_digitalisation_test.jsonl \
  --topic configs/topics/digitalisation.yaml  # keyword search
parltopic run-eval --eval-set data/eval/e1_digitalisation_test.jsonl \
  --topic configs/topics/digitalisation.yaml --output results/test.jsonl --workers 8
parltopic score --eval-set data/eval/e1_digitalisation_test.jsonl --results results/test.jsonl
parltopic compare-runs --eval-set data/eval/e1_digitalisation_dev.jsonl \
  --baseline-results results/a.jsonl --candidate-results results/b.jsonl   # paired bootstrap
```

The frozen eval sets are in `data/eval/` (`meta.json` describes them). `build-eval
--eligibility dev` uses a stricter sampling rule for a new sealed holdout and produces different
files. Optional experiments: `parltopic rethink` (second look with Apertus reasoning),
`--fewshot-pool`, `--title-rules`, `parltopic enrich-documents`, and a title-only TF-IDF baseline
(`pip install -e '.[experiments]'`, `python -m parltopic.evaluation.linear_baseline --help`).

---

## Data

Source: [OpenParlData](https://openparldata.ch) bulk exports ([files.openparldata.ch](https://files.openparldata.ch/))
and the [hackathon label directory](https://files.openparldata.ch/hackapertus/), CC BY 4.0. The
REST API ([documentation](https://api.openparldata.ch/documentation)) serves document text.

- **Affairs:** 326,396 records; join key `id` in the exports, `openparldata_id` in the label files.
- **Federal texts:** submitted text, reasoning and lead in DE/FR/IT (`texts_CHE.ndjson.gz` if
  present, else the hackathon file), in a stable order. The Federal Council's answer is not used.
- **Labels:** PolitMonitor and DVS digitalisation lists (positives only), Curia Vista subject areas
  for federal affairs, the APS scheme (no affair has an APS label).
- **Documents:** `parltopic enrich-documents --input … --output …` attaches the extracted text of
  an affair's documents from `/v1/affairs/{id}/docs`, cached under `data/cache/documents`. Documents
  can postdate the affair.

Raw data, caches and results are excluded from Git.

---

## Repository structure

```text
app/                    Streamlit demo
configs/topics/         Topic definitions (digitalisation, adhoc/, experiments/)
configs/taxonomies/     APS scheme as JSON (22 chapters, 165 topics)
data/eval/              Frozen eval sets and the human APS labels
data/demo/              Small synthetic demo inputs
docs/                   Architecture, integration, evaluation protocol, benchmark notes, log
integration/opd/        SQL schema for OpenParlData's affair_topics table
src/parltopic/          Ingestion, classification, retrieval, evaluation, CLI, API
tests/                  Offline unit tests
technical_report.md     Hackathon technical report
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `LLM_NAME` | Apertus model, default `swiss-ai/Apertus-v1.5-70B` |
| `LLM_BASE_URL` | OpenAI-compatible endpoint, default CSCS |
| `LLM_API_KEY` | API key; never committed |
| `RETRIEVAL_TOP_K` | Passages sent to Apertus (5) |
| `CLASSIFIER_PROMPT_VERSION` | Prompt version (`topic-v2`) |
| `KEYWORD_RESCUE_ENABLED` | Multilingual term rule on or off |
| `KEYWORD_DOCUMENT_GATE_ENABLED` | Term rule also inside attached documents |
| `LLM_REQUESTS_PER_MINUTE` | Process-local request limit (default 30; 0 disables) |
| `LLM_CONNECTION_REUSE` | Reuse pooled HTTP connections (default on) |

All settings and defaults are listed in [.env.example](.env.example).

## Sovereign deployment

The service is a Python package and container with no proprietary AI dependency. It runs against
any OpenAI-compatible Apertus endpoint: CSCS during the hackathon, a Swiss provider, or a local
vLLM server with the open weights. With the exports cached, it runs without internet access.

## Current limitations

- The digitalisation labels have no checked negatives; the test split has been opened and is not a
  sealed holdout.
- High recall needs every affair read (28–67 h per topic over 325,000 affairs on one key). A
  compiled-query pre-filter (`parltopic compile-topic`, `find`) finds about 60 % of the hits in
  4–8 % of the affairs; it is a fast first pass, not a replacement (report 5.7).
- The APS scheme is exported but no multi-label APS mode is
  evaluated; party bias is not checked; Romansh is not evaluated.
- Apertus 8B is not suitable for this task (dev F1 0.43 vs. 0.80 for 70B).

## Licence

Code: [Apache License 2.0](LICENSE). Documentation: CC BY 4.0. Data: OpenParlData.ch, CC BY 4.0.
