# Technical report — ParlTopic, Token Tell

- **Challenge:** 2 — OpenParlData: Topic classification for Swiss parliaments with Apertus
- **Event:** Hack Apertus Liebefeld 2026
- **Team:** Token Tell — team member list to complete
- **Demo:** video link to add
- **Repository:** https://github.com/Felipe3052/hackapertus-openparldata

## 1. Summary

ParlTopic is a multilingual annotation service that assigns standard or user-defined topics to Swiss parliamentary affairs. A deterministic multilingual term gate handles explicit cases; the remaining affairs use field-aware segmentation, BM25 retrieval, and Apertus v1.5. Every decision is tied back to original evidence. The first development benchmark covers 450 German, French, and Italian digitalisation affairs from OpenParlData.

## 2. Architecture

The application is split into adapters, a reusable classification core, and delivery surfaces:

1. **Ingestion** reads OpenParlData API responses or export files and normalises them into stable `Affair`, `Document`, and `TextSegment` records.
2. **Deterministic gate** assigns explicit configured multilingual terms and cites the matching segment without an LLM call.
3. **Retrieval and classification** use field-aware segments and BM25 for all remaining affairs, then ask Apertus for a constrained JSON decision and passage IDs.
4. **Validation and evidence** reject unknown IDs, clamp invalid scores, preserve technical failures separately, and return original source text.
5. **Delivery** exposes one service through JSONL CLI, FastAPI, and Streamlit.
6. **Evaluation** measures precision, recall, F1, latency, tokens, review rate, language, and parliamentary level.

The implementation diagram and trust boundaries are documented in `docs/architecture.md`.

### Target architecture

The target is deployable in two of the event's required environments:

- **On-premise:** the Python service, indexes, cache, and Apertus serving endpoint can run inside the organisation's infrastructure.
- **Sovereign Swiss cloud:** the same container can use a Swiss-hosted Apertus endpoint and Swiss-resident storage.

An air-gapped runtime becomes possible when Apertus weights and all required OpenParlData exports are prepared before deployment. Runtime application code has no required proprietary AI dependency.

Build-time dependencies are Python packages and the container base image. Runtime dependencies are an Apertus-compatible endpoint and either cached OpenParlData data or permitted API access. Credentials enter through environment variables and are excluded from images and Git.

## 3. Use of Apertus

- **Model:** `swiss-ai/Apertus-v1.5-8B` by default; 70B is a measured quality-mode candidate.
- **Use:** zero-/few-shot structured topic classification.
- **Serving:** OpenAI-compatible CSCS endpoint during the hackathon; local or sovereign hosting remains possible.
- **Prompt:** a versioned topic definition, positive/negative examples, and a maximum of `RETRIEVAL_TOP_K` original passages.
- **Output:** `status`, model assessment, short explanation, and evidence passage IDs.

Temperature is zero. Complete documents are not sent blindly: the earlier Fact Attack project showed that selecting relevant context can improve quality while reducing latency and tokens. Model scores are not treated as calibrated probabilities.

## 4. Data

Primary data comes from the public OpenParlData REST API or data export. The internal schema preserves upstream identifiers, language, parliamentary level, dates, document identifiers, and source URLs. Source hashes and retrieval timestamps will be added when the first real API fixture is pinned.

The repository includes frozen E1 development and opened-validation data derived from PolitMonitor tags, plus Curia and DVS evaluation resources. Untagged E1 affairs are positive-unlabeled proxies rather than adjudicated negatives. Results therefore measure agreement with available tags and are not a final production-quality claim.

## 5. Evaluation

The current development result for hybrid-v3 with Apertus 70B is precision `0.931`, recall
`0.813`, positive F1 `0.868`, and macro-F1 `0.904` on 450 examples. The keyword-only baseline
has macro-F1 `0.733`. These are development figures; `docs/benchmark.md` records paired
comparisons and uncertainty. Evaluation includes:

- binary digitalisation precision, recall, F1, and accuracy;
- review/abstention rate for `uncertain` and `not_evaluable`;
- quality split by German, French, Italian, and where possible Romansh;
- quality split by federal, cantonal, and municipal level;
- inference latency, token use, and throughput;
- evidence validity: every returned ID exists in the supplied context;
- comparison against keyword-only and BM25-only baselines.

The next defensible quality milestone is a newly sealed, manually adjudicated holdout because
the existing nominal test labels have already been inspected.

## 6. Limitations

- OpenParlData field mapping is not final until exact API fixtures are committed.
- BM25 depends on surface terms and may underperform across languages.
- Model assessments can be overconfident and require labelled calibration work.
- Short source texts may not contain enough evidence for a reliable decision.
- Topic definitions can encode hidden scope choices; they must be versioned and reviewed.
- Performance on one topic cannot be generalised to the complete APS taxonomy.
- Romansh data is expected to be sparse.

## 7. Reproducibility

Create a Python 3.11+ environment, install `.[dev]`, copy `.env.example` to `.env`, and run `make test`. `make demo` validates the demo records without an API call. Live classification requires `LLM_API_KEY`; `make web` and `make api` expose the two interactive surfaces.

Final benchmark runs must record:

- exact Git commit;
- model identifier and endpoint type;
- prompt and topic configuration versions;
- dataset hash and split definition;
- Python and dependency versions;
- machine/serving configuration;
- full output JSONL and aggregate report.

## Licence

Code: Apache-2.0. Report and documentation: CC-BY-4.0.

## References

1. OpenParlData Challenge, Hack Apertus Liebefeld 2026.
2. Swiss AI, Apertus v1.5 model family.
3. OpenParlData API and data export documentation.
