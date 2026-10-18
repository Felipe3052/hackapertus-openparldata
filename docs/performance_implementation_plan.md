# Performance implementation plan

Update, 18 October 2026: connection pooling and a shared process-local 30-RPM limiter have
been implemented and checked. Paired batch sizes 3/5 failed coverage checks and were rejected;
production keeps size 1. See the current results in [performance.md](performance.md).
The sections below retain the original plan; caching and prompt/filter experiments remain future work.

This plan follows the live benchmark in [performance.md](performance.md). Only benchmark
instrumentation and reporting were implemented in the initial change. The remaining optimizations
require their own paired checks.

## P1: Reuse HTTP connections

Give `ApertusClient` a reusable `httpx.Client` with explicit connection limits, timeouts and
close/lifespan handling. Reuse the classification service in the FastAPI application lifecycle;
constructing a new pooled client inside every request would defeat reuse. Keep the request
JSON, prompts, retry semantics and evidence validation identical. For CLI batch jobs, close
the client after the run. Exercise payload equivalence, cleanup and concurrent requests with
offline transport fixtures before a separately budgeted live comparison.

Acceptance: identical outgoing inference payloads and no change in deterministic rule outputs;
no loss of decisive coverage; measure API response distributions and process wall time on the
same frozen cases. A pooled client removes connection setup but cannot remove model generation.

## P2: Make parallel work bounded and quota-aware

Reuse the existing worker-based runner first. Add configurable request/token admission limits,
an in-flight semaphore, persisted resume state, Retry-After handling and jittered backoff for
retryable failures. Read authoritative project/key quotas before increasing admission rates.
Keep interactive requests separate from a long background backlog so throughput jobs do not
consume all concurrency. Treat 429s, timeouts, coverage and P95 as first-class outcomes.

An async client can later share the same rate limiter and bounded queue. It reduces blocked
threads at larger concurrency; at four workers with a binding request-start cap it does not
by itself remove the cap or speed up generation. Do not issue unbounded `asyncio.gather` calls.

Acceptance: maintain the existing prediction policy, never convert failures into negatives,
and demonstrate sustained throughput under the real request/token quotas. Concurrency sweeps
need a new explicit budget; this benchmark does not authorize additional inference calls.

## P3: Cache validated predictions for repeated work

Persist successful, validated outputs with a key containing full source-content hash, affair ID,
topic definition hash, selected prompt hash, model/version and relevant policy/retrieval settings.
Invalidate on source, model, taxonomy or implementation changes. Do not cache transport failures
as completed classification. Preserve original evidence IDs and URLs; cross-affair reuse needs
explicit evidence remapping and is outside the first version. Record hit rate and cache-read
latency separately from live endpoint latency. Existing eval resume and upstream document
response caching are useful, but are not a general inference result cache.

Acceptance: cached output matches the validated original and points at the current source;
measure warm and cold workloads separately. A first pass over unique new affairs can have
zero result-cache hits, so do not promise first-pass speedup or savings from repeat-use data.

## P4: Reduce prompt and passage tokens in controlled variants

First shorten repeated taxonomy/system wording while keeping inclusion and exclusion policy,
language coverage, concise explanation and evidence-ID requirements. Keep stable text first
to preserve provider prefix-cache eligibility. Next inspect redundant overlapping passages and
test smaller context budgets while preserving a precise title and decision-bearing passages.
The current sample mostly has <=3 selected passages, so lowering top-k from five to three alone
will affect few cases. Do not remove negations or critical qualifying context to meet a budget.

For a 20% input-token reduction scenario, full-rate input charges fall by 20%; output charges
remain. Runtime improvement depends on uncached prefill versus generation and cannot be
inferred from the token ratio alone. Server prefix caching already reduces some repeated work.

Acceptance: paired full validation evaluation, reporting macro-F1, macro-precision, macro-recall,
positive precision/recall and per-language results. Use the existing criterion: macro-F1 improves
and neither macro precision nor macro recall falls by more than 0.01 absolute before promoting
a quality-changing candidate; also inspect decisive coverage and positive recall. Any deliberate
speed/quality tradeoff needs an explicit decision, not automatic promotion.

## P5: Evaluate a high-recall embedding cascade

Prepare embeddings once per source version, retrieve topic candidates and send all candidates
and uncertain cases to Apertus. Freeze the threshold using training/calibration data before
paired validation. Price embedding creation, index storage and updates alongside saved model
requests. Existing BM25 selects passages *within* one affair; it is not a dataset-wide negative
prefilter. Embeddings would add a new decision stage with a real false-negative risk.

If fraction `q` of previously model-required cases reaches Apertus, LLM tokens/requests fall
approximately to `q` of baseline for unchanged downstream prompts. Total cost adds embedding
and retrieval work. Overall positive recall is filter recall times conditional downstream recall;
a filtered-out positive cannot be recovered by Apertus. Do not threshold the current model score
as though it were a calibrated probability. Start with shadow routing that still classifies all
validation cases; only enable skipping once multilingual false negatives are understood.

## Batching assessment

Batching jobs for orchestration can reduce scheduling/I/O overhead, but local processing is
already very small and the model still receives one request per affair. The documented CSCS
API does not establish a supported asynchronous Batch API or its price for this project.
Check actual provider support before planning around a batch discount.

Putting several affairs in a single chat request would change the inference contract. It can
amortize the repeated taxonomy but risks cross-affair reasoning, evidence-ID confusion, longer
generation, partial batch failures and harder retries. It is lower priority than pooled HTTP,
quota-aware concurrency and exact-result caching. Evaluate it as a separate model/prompt
experiment, with quality and coverage checks and no assumed discount.
