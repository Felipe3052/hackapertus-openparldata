# ParlTopic — topic classification for Swiss parliaments with Apertus

**Hack Apertus Liebefeld 2026 · Challenge 2: OpenParlData · Team Token Tell (Felipe Wüthrich, Josip Jukic)**

ParlTopic tells you which Swiss parliamentary affairs belong to a topic, in German, French and
Italian, across federal, cantonal and municipal parliaments. You describe a topic in a short YAML
file; Apertus v1.5 decides for each affair and cites the passage that justifies the decision. New
topics need no training.

- **Challenge:** [Topic classification for Swiss parliaments with Apertus](https://app.sprintd.org/events/hack-apertus-liebefeld/cases/topic-classification-for-swiss-parliaments-with-apertus)
- **Technical report:** [technical_report.md](technical_report.md) · **Experiment log:** [docs/experiments.md](docs/experiments.md) · **Benchmark notes:** [docs/benchmark.md](docs/benchmark.md)
- **Demo video:** link to add

> Topic labels are suggestions about subject matter. They do not judge political positions, and a
> person should confirm them before they are published.

---

## Results

Use case of the challenge: Digital Administration Switzerland (DVS) lists digitalisation affairs
by hand, based on the PolitMonitor editorial tag. Model: `swiss-ai/Apertus-v1.5-70B` on CSCS.

| Evaluation set | Keyword search | **ParlTopic** | Notes |
|---|---:|---:|---|
| Digitalisation, 1,200 affairs 2024–2026, F1 | 0.642 | **0.876** | precision 0.875, recall 0.877 |
| … F1 German / French / Italian | 0.60 / 0.68 / 0.72 | **0.90 / 0.85 / 0.85** | official translations of federal affairs |
| Current DVS list (30 affairs), found | 19 | **27** | federal and cantonal |
| Ad-hoc topic *migration*, F1 | 0.717 | **0.874** | topic written once, no tuning; |
| Ad-hoc topic *health*, F1 | 0.571 | **0.805** | scored against the Federal Assembly's |
| Ad-hoc topic *transport*, F1 | 0.540 | **0.784** | official subject areas (500 affairs) |

Keyword search uses the same multilingual terms as the topic file. The digitalisation labels are
editorial tags without checked negatives, so precision is a lower bound. The sample is one third
positive; in the whole corpus only 2.3 % of the affairs are tagged, so about one in four
suggestions is a tagged affair (keyword search: the same ratio at 63 % of our recall). ParlTopic is
a suggestion list for editors to review. Configuration and prompts were chosen on a separate
2018–2023 split; see the [technical report](technical_report.md) for the protocol, the ablations,
the bias check and costs.
Further documentation: [performance and scale measurements](docs/performance.md) ([methodology](docs/performance_methodology.md)),
the [independent evaluation audit](docs/evaluation_audit.md) and the [evaluation protocol](docs/evaluation_protocol.md).

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

Requires Python 3.11 or newer.

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

User interface and API:

```bash
make web                      # Streamlit
make api                      # FastAPI, then: curl http://localhost:8000/health
docker compose up --build     # both in containers
```

---

## Reproduce the evaluation

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
docs/                   Architecture, evaluation protocol, benchmark notes, experiment log
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
- Each topic is classified affair by affair; a pre-filter for a fast pass over all 325,000 affairs
  and a stored, searchable result per topic are next.
- The UI has no correction button yet; the APS scheme is exported but no multi-label APS mode is
  evaluated; party bias is not checked; Romansh is not evaluated.
- Apertus 8B is not suitable for this task (dev F1 0.41 vs. 0.78 for 70B).

## Licence

Code: [Apache License 2.0](LICENSE). Documentation: CC BY 4.0. Data: OpenParlData.ch, CC BY 4.0.
