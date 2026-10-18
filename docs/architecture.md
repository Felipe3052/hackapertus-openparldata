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
│ Segmentation and retrieval    │
│ stable IDs, BM25 baseline     │
└──────────────┬────────────────┘
               │ selected original passages
               ▼
┌───────────────────────────────┐
│ Apertus classifier            │
│ structured topic decision     │
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

Only source text held by the application is returned as evidence. Apertus may select evidence IDs but cannot create evidence text or source URLs. Unknown evidence IDs are ignored and must be counted during evaluation.

## Failure semantics

`not_assigned` is a model decision. `not_evaluable` means the supplied text is insufficient. `uncertain` requests review. `failed` represents infrastructure, parsing, validation, or endpoint failure. These states must never be collapsed into one negative class.

## Evolution path

1. Pin real OpenParlData fixtures and implement their normaliser.
2. Add SQLite/DuckDB persistence with upstream IDs and source hashes.
3. Evaluate the DVS digitalisation topic with BM25 retrieval.
4. Add multilingual embeddings only if they improve the frozen holdout.
5. Add two-level APS taxonomy support using the same topic contract.
6. Add incremental jobs for newly published or changed affairs.

