# Live inference benchmark methodology

This document describes the initial 100-case / 100-call-budget experiment. The subsequent
**paired batch-1/3/5 comparison with a separate 50-additional-call budget** and its stricter
no-quality-loss decision are documented in [performance.md](performance.md). It used 39 calls;
batch sizes 3/5 were rejected and are available only in the research runner.

This benchmark measures the existing `hybrid-v3` classifier and configured Apertus endpoint.
It adds an external timing client and transport observer. It does not change production
prompts, retrieval, topic rules, response validation, model parameters or connection handling.
All development and measurements run on the current feature branch.

## Sample and scope

The input is `data/eval/e1_digitalisation_dev.jsonl`, the existing real OpenParlData development
set: 450 affairs, German/French/Italian, one binary digitalisation topic. The final test set is
not accessed. Select exactly 100 unique affairs deterministically with seed `20261018`.
Allocate proportional quotas by language, proxy label and existing keyword gate outcome,
using largest remainders. Within each stratum, sort by text length and systematically sample
across its length range with a seeded offset. Assign nearby selected lengths in shuffled pairs
to sequential and parallel groups, balancing total arm sizes at 50 each.

The resulting sample is representative of this development set, not a probability sample of
all 300,000 OpenParlData affairs. The source overrepresents tagged digitalisation positives;
untagged examples are proxy negatives. Other topics, cantonal document availability, source
languages, long attachments and production prevalence may change throughput and quality.

Each affair is processed once. Sequential and parallel arms contain different affairs. This
saves paid calls but prevents a paired causal speedup or quality comparison. Their language,
label, gate and length compositions are recorded. The sequential arm runs before the parallel
arm, so shared endpoint load and prefix-cache warmup can confound differences.

## Invocation budget and safety

1. `prepare` freezes panel, branch, commit, data/source hashes, settings and topic.
2. `run --phase smoke` processes ten model-required sequential-arm affairs, with at most ten
   actual HTTP inference attempts, including retries. These cases count toward the final 100.
3. Inspect smoke status, latency, token usage and any rate-limit headers before proceeding.
4. `run --phase complete` processes the other 40 sequential and 50 parallel cases. Existing
   rules can avoid API calls. Total attempted HTTP inference calls cannot exceed 100.

The initial operating cap is **30 request starts/minute**, with evenly spaced admissions,
and at most four in-flight requests. This cap is an experiment setting, not a verified provider
quota. The CSCS public documentation says resource/key limits apply but does not publish one
universal RPM/TPM quota. No authenticated quota was available. The observer stores only
rate-limit/retry headers, status, usage and request hashes, never credentials. It stops admitting
requests after any HTTP error or network exception. Already in-flight requests can finish.
The original retry code remains in place, but the observer blocks further HTTP attempts after
such failures. A response-validation failure also stops new work. There is no paid retry of an
incomplete phase, no additional warmup and no sweep of concurrency settings.

A process-wide file lock prevents concurrent runs in the same run directory. The persistent
attempt ledger is fsynced before sending; a crashed request consumes budget conservatively.
Each phase refuses to overwrite existing results. Use the same run directory for smoke and
completion; creating a new run is a new paid experiment and needs its own budget.

## Timing definitions

- **Total latency:** worker start through final validated `ClassificationResult`, including
  Affair schema validation, all local processing, HTTP work and admission waiting. It excludes
  time waiting for an available executor worker and disk serialization of the final row.
- **Preprocessing:** Affair validation, chunking, keyword rules, BM25 retrieval and prompt
  construction, ending at entry to `ApertusClient.classify`. For rule-only cases, the entire
  service duration is counted as local preprocessing; separate postprocessing is zero.
- **HTTP/API response time:** `httpx.post` start to complete buffered response/exception.
  Includes fresh connection establishment, network transfer, server queueing and generation.
  It excludes the benchmark admission wait. It is not pure GPU inference time or time to first
  token; this endpoint run provides no reliable decomposition of those components.
- **Client time:** admission, ledger recording, HTTP, retry/backoff if applicable, response
  decoding and model-output schema validation. Admission waiting is also reported separately.
- **Postprocessing:** evidence-ID resolution, source-text lookup and final result construction
  after `ApertusClient.classify` returns.
- **Throughput:** completed affairs / phase wall seconds, including local rules, executor,
  rate limiter and result I/O. The combined sequential wall time sums smoke and subsequent
  sequential time; human inspection and time between invocations are excluded.

Per-case `pre + client + post = total`. HTTP and admission are nested within client time, not
additional terms. Rule-only HTTP latency is zero; model-only HTTP distributions are reported
separately. Mean, median, P95 and P99 use exact samples with linear interpolation at `(n-1)*q`.
With 50 cases/arm and fewer model calls, P99 is near the maximum and is descriptive only.
There are no repeated trials or stable production tail-latency guarantees.

## Tokens, cost, quality and scale projections

Token totals come from actual HTTP response `usage`, including completions that might later
fail schema validation. Attempts without usage are counted separately and prevent a complete
billing reconciliation. A provider reporting prefix-cache hits does not establish a cached-token
discount. Token cost stays `null` unless explicit, sourced input/output rates and currency are
supplied. With full-rate input price `Pi` and output price `Po` per million tokens:

`estimated_cost = (prompt_tokens * Pi + completion_tokens * Po) / 1,000,000`.

No zero-price inference is implied by a missing tariff. Provider key billing remains authoritative.
The optional summarizer price arguments calculate an all-input full-rate estimate; a cache
discount requires separate verified billing rules.

Quality metrics score only decisive results and separately report coverage. `uncertain`,
`not_evaluable` and `failed` never become negative labels. Macro-F1, macro-precision and
macro-recall average the two classes of this one topic. Quality on different 50-case arms is
not a model-change comparison. Future optimizations need paired evaluation on a larger
fixed validation set, preserving primary quality criteria and multilingual recall.

The 300,000-affair projection is `measured_wall_seconds / measured_affairs * 300000`,
separately for sequential and four-worker operation at the measured admission cap. Project
tokens with the same sample-to-volume factor. These are single-topic scenarios assuming the
same text-length, rule-hit, label, caching and endpoint-load mix, continuous operation and no
additional retries. They exclude download, parsing of raw exports, ingestion, enrichment,
index construction, outages and review. Applying many topics multiplies model work unless a
separately evaluated joint approach replaces per-topic inference.

## Reproduce

From the repository root, using the same source/configuration hashes and installed environment:

```bash
.venv/bin/python -m parltopic.evaluation.performance prepare \
  --run-dir results/performance-NEW --rpm 30 --workers 4
.venv/bin/python -m parltopic.evaluation.performance run \
  --run-dir results/performance-NEW --phase smoke
# Inspect smoke.runtime.json, responses.jsonl and the ten validated outputs first.
.venv/bin/python -m parltopic.evaluation.performance run \
  --run-dir results/performance-NEW --phase complete
.venv/bin/python -m parltopic.evaluation.performance summarize \
  --run-dir results/performance-NEW --output results/performance-NEW/summary.json
```

Raw evidence and results stay under ignored `results/`. A checked-in aggregate summary and
report document the completed run. Synthetic fixtures are used only for offline instrumentation
tests and never contribute to reported performance.

## Observer correction in the completed 18 October run

The first observer held one admission lock during rate-limit waits and reused it for response
logging. This added contention after HTTP completion, inflating parallel total/client latency
without changing the already-recorded HTTP time. The original code is archived byte-for-byte
as `results/performance-20261018/instrumentation-v1.py`, matching the initial manifest hash.
The corrected implementation uses a separate response-log lock. New runs use that correction.

For the existing completed run only, `calibrate --run-dir results/performance-20261018` selected
eight model-required affairs deterministically across language/length from the same panel and
repeated them with four workers. This is a separate diagnostic, not eight extra unique primary
cases or a replacement for 50-case latency percentiles. It shares the original persistent attempt
ledger and cannot exceed eight additional attempts or 100 cumulative attempts. It refuses any
changed production-code/data/policy manifest and requires the original observer archive. The
diagnostic manifest records both instrumentation hashes and the selected IDs; repeats refuse
existing outputs. The final run used 83 primary + 8 diagnostic = 91 actual inference attempts.

The checked-in JSON identifies primary versus cumulative calls, all paid tokens, the original
parallel timing limitation and the eight-call diagnostic. Primary per-arm metrics and token
projections exclude diagnostic usage. The separate `all_billed_usage_tokens` total includes it.
Parallel worker-to-result percentiles from the first run are explicitly marked as affected by
the observer in the report. Full-buffer HTTP times remain the usable model response measurement.

## Sources

- [CSCS Inference API: access, pricing and resource limits](https://docs.cscs.ch/services/inference/api/),
  consulted 18 October 2026. Exact project token prices and quota remain unverified.
- [HTTPX clients and connection reuse](https://www.python-httpx.org/advanced/clients/): top-level
  requests create connections per request; a persistent client can reuse them.
