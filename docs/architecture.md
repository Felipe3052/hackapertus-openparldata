# ParlTopic architecture

## Scope

ParlTopic is an annotation service over OpenParlData entities. OpenParlData remains the source of truth; ParlTopic stores reproducible topic suggestions and their provenance. It is not a political recommendation or truth-scoring system.

## Component boundaries

```text
┌───────────────────────────────┐
│ OpenParlData API / export     │
└──────────────┬────────────────┘
               │ public source data
               ▼
┌───────────────────────────────┐
│ Ingestion adapter             │
│ mapping, validation, hashing  │
└──────────────┬────────────────┘
               │ Affair + Document
               ▼
┌───────────────────────────────┐
│ Segmentation                  │
│ field-aware stable IDs        │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ Hybrid classification policy  │
│ term gate; else BM25 + Apertus│
└──────────────┬────────────────┘
               │ status + evidence IDs
               ▼
┌───────────────────────────────┐
│ Validation and provenance     │
│ reject unknown IDs/errors     │
└──────────────┬────────────────┘
               │ ClassificationResult
        ┌──────┼────────┐
        ▼      ▼        ▼
       CLI    API   Streamlit demo
```

## Trusted data

Only source text held by the application is returned as evidence. The deterministic gate cites
the segment containing its configured term. Apertus may select evidence IDs but cannot create
evidence text or source URLs. Unknown evidence IDs invalidate the model response.

## Failure semantics

`not_assigned` is a model decision. `not_evaluable` means the supplied text is insufficient. `uncertain` requests review. `failed` represents infrastructure, parsing, validation, or endpoint failure. These states must never be collapsed into one negative class.

## Evolution path

1. Manually adjudicate a stratified multilingual sample and create a new sealed holdout.
2. Calibrate the uncertain/review policy against adjudicated examples.
3. Add multilingual embeddings only if paired evaluation improves macro-F1.
4. Add SQLite/DuckDB persistence with upstream IDs and source hashes.
5. Add two-level APS taxonomy support using the same topic contract.
6. Add incremental jobs for newly published or changed affairs.

