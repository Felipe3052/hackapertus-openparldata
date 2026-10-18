# Apertus performance: API time and request admission dominate

## Paired update: keep connection reuse, reject multi-affair batching

The follow-up experiment used **the same 30 real affairs and labels for batch sizes 1, 3 and 5**,
on `experiment/classifier-quality`, with Apertus v1.5 70B, four workers and a common 30-start/min
admission controller. Five affairs were decided by existing rules in every variant. The remaining
25 required 25 single requests, nine batches of up to three, and five batches of five: **39 actual
additional API calls total**, all HTTP 200, zero retries. Eleven authorized calls remain unused.

**Recommendation: batch size 1 with pooled HTTP connections.** It preserves all 30 previous
decisions, macro-F1 **0.9206**, positive precision **1.0000**, positive recall **0.8000**, and full
coverage. Larger batches produce more attempted affairs/minute but fail the required quality
guard: size 3 has three invalid results and two non-evaluable affairs; size 5 has five invalid
results and one non-evaluable affair. These candidates are rejected, not promoted.

### Why 36 affairs/minute does not violate a 30-request/minute limit

The original parallel run processed **50 affairs**, with nine local rule decisions and only
**41 API requests**, in 83.1218 seconds:

- Affairs/minute: `50 / 83.1218 × 60 = 36.0916`.
- API requests/minute: `41 / 83.1218 × 60 = 29.5951`.

Calling the first number "requests/minute" mixes units. The raw start ledger contains at most
**30 request admissions in any half-open 60-second window**, including overlapping workers.
The original limiter serialized admissions with two-second spacing but recreated its state for
each CLI phase/process. It was benchmark-only, not a limit in the original production client.
Its previously corrected response-log contention affected worker latency, not this unit mismatch.

The new production limiter is shared by endpoint/key/RPM within a process, uses monotonic
time, checks both start spacing and a rolling 60-second window, and admits **each HTTP attempt,
including retries**. Logging has a separate lock. The paired runner shares one controller across
all three variants and persists the 50-attempt budget before transmission. It admits at most
30 requests in a measured rolling window across the entire follow-up trial. Limits in other
processes or other users' project keys need separate quota coordination; no global token quota
has been verified or raised.

The new single-affair microbenchmark reports `25 / 49.5821 × 60 = 30.2528` requests/minute
when normalized from a run shorter than 60 seconds. This also does not mean a quota breach:
there were only 25 starts in that interval; the first request can start immediately and the final
response arrives shortly after start 25. The actual rolling-window count remains <=30. For
large-volume projections use the sustained admission ceiling, not this finite-window artifact.

### Quality comparison on identical inputs

Sampling was frozen before inference: 19 DE / 6 FR / 5 IT, ten tagged positives / 20 proxy
negatives, selected proportionally by language, label and rule outcome with systematic
length coverage from the earlier 100-case panel. Seed `20261019` is an arbitrary fixed integer,
not a measurement date. Each variant sees the exact same IDs, order, labels and original texts.
No final-test cases or synthetic examples enter these measurements. Thirty cases are a budgeted
paired slice, not a new evaluation of the full 450-case set.

| Batch size | Decisive coverage | Macro-F1 † | Macro precision † | Macro recall † | Positive precision † | Positive recall † | Keep in production? |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1, pooled | **30/30** | **0.9206** | **0.9545** | **0.9000** | **1.0000** | **0.8000** | **Yes** |
| 3, experimental | 25/30 | 0.9554 | 0.9706 | 0.9444 | 1.0000 | 0.8889 | No: coverage loss |
| 5, experimental | 24/30 | 0.9515 | 0.9706 | 0.9375 | 1.0000 | 0.8750 | No: coverage loss |

† For incomplete variants, these are **selective metrics on the decisive subset**, not a
fair full-panel quality improvement. The higher values exclude unresolved cases. Failures and
abstentions are never silently converted into negative predictions. Acceptance requires coverage,
macro-F1, macro precision/recall and positive precision/recall all at least baseline, with no 0.01
tolerance. Sizes 3/5 fail coverage and therefore cannot pass even if their selective F1 is higher.

For sensitivity on the **same full 30-label denominator**, assign every unresolved label its
worst possible completion. This produces conservative mathematical bounds, not new observed
model predictions:

| Batch size | Full-panel Macro-F1 lower bound | Positive precision lower bound | Positive recall lower bound |
| --- | ---: | ---: | ---: |
| 1 | 0.9206 | 1.0000 | 0.8000 |
| 3 | 0.7847 | 0.6667 | 0.8000 |
| 5 | 0.7436 | 0.6364 | 0.7000 |

### Speed, latency, usage and reliability

| Batch size | Actual calls | Wall time | Attempted affairs/min | Worker P50 / P95 | Input / output tokens per affair | Invalid results | Retries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1, pooled | 25 | 49.582 s | 36.30 | 7.580 / 8.472 s | 1123.90 / 80.20 | **0/30 (0%)** | 0 |
| 3 | 9 | 18.449 s | 97.57 | 7.339 / 11.467 s | 566.70 / 80.37 | 3/30 (10%) | 0 |
| 5 | 5 | 17.756 s | 101.38 | 9.483 / 14.137 s | 400.40 / 75.00 | 5/30 (16.7%) | 0 |

Worker latency is measured from group processing start through validation, including quota
waiting, and excludes time queued for a worker. All members share the group's elapsed latency;
rule-only cases have zero assigned inference latency. Response logging does not wait behind
the admission limiter in this runner. Model-only HTTP P50/P95 are **1.619/2.246 s** for size 1,
**4.974/6.015 s** for size 3 and **7.540/9.226 s** for size 5. Bigger batches improve attempted
throughput, not individual response latency. There are too few batches for stable tail claims.

All 39 HTTP responses were successful at the transport level. "Invalid results" above means
model schema/ID validation failure. In addition, two cases in size 3 and one in size 5 return
`not_evaluable`, so total missing-decision rates are **16.7% / 20%**. Decisive throughput is
81.30 / 81.10 affairs/min respectively, but still does not complete the entire workload.

Size 3 returned an invalid requested-ID mapping for one three-member batch. Size 5 returned
an `assigned` member without the required evidence IDs, invalidating that five-member batch.
Validation remains strict and atomic. No IDs were guessed, no evidence checks were relaxed,
and no additional single-call fallback hid failures or consumed unreported API requests.

HTTPX traces confirm connection reuse: **four TCP/TLS connections for 25 single requests**.
Without pooling the old client created a connection per request. On the same 25 model-required
affairs the historical mean HTTP time was 2.087 s; the new pooled mean is 1.697 s. This is an
observed difference of 18.7%, **not an isolated causal estimate** of pooling: server load,
generation and prefix-cache state also differ, and no new unpooled A/B arm was purchased.
All 25 single request payload hashes match the historical prompts/settings exactly, and all
30 final statuses match. Reusing connections is therefore retained without changing taxonomy,
decision prompts, retrieval, evidence validation or model parameters.

An additional **API-free 450-case control-flow replay** compared the feature's pre-change service
at commit `bddc796` with the refactored service, injecting the same recorded model decisions into
both. All **450/450 prompts, routing choices and validated results match**. This checks the local
refactor over the full existing development set; it is not a fresh 450-case inference benchmark
or an accuracy/speed estimate from replay. Evidence and source/data hashes are saved in
[results/pooling-refactor-equivalence450.json](results/pooling-refactor-equivalence450.json).

Usage is taken once per HTTP response, including invalid batches: size 1 uses 33,717 input /
2,406 output tokens, size 3 uses 17,001 / 2,411, and size 5 uses 12,012 / 2,250. Total paid
response usage is **62,730 input + 7,067 output tokens**. Per-affair averages divide by all 30
attempted affairs, including the five rule-only cases. Smaller nominal token bills for rejected
batches do not include recovery and are not a quality-neutral saving. Exact monetary tariffs
remain unverified; no price or batch discount is assumed.

### Updated projection to 300,000 affairs

| Batch size | Direct sample extrapolation | Quality-preserving completed-work projection |
| --- | ---: | --- |
| **1, pooled** | **137.73 h** | **Approximately 139 h minimum** at the same 25/30 model-call mix and sustained 30 RPM; allow extra time for endpoint variability/retries |
| 3 | 51.25 h for attempts only | Not supported: 5/30 decisions missing; recovery not measured |
| 5 | 49.32 h for attempts only | Not supported: 6/30 decisions missing; recovery not measured |

For size 1 the admission floor is `(300000 × 25/30) / 30 / 60 = 138.89 hours`; it corrects
the optimistic finite-window normalization of the 49.6-second sample. This is a **single-topic
scenario with the same source-length/rule-hit mix**, excluding ingestion, downloads and review.
The measured 36.30 affairs/min is already near that sustained 36 affairs/min ceiling. Connection
reuse reduces network overhead, but cannot create a large bulk speedup while that quota binds.
At the measured single-case mix, projected usage is 337.17M input + 24.06M output tokens.

The task did not demonstrate a large quality-neutral reduction in total processing time. The
safe retained change is connection reuse; batching's apparent 2.7–2.8× attempted throughput
comes with unacceptable coverage loss. A larger verified project quota could improve sustained
throughput with the same inference contract, but no quota increase is assumed or executed.

### Retained implementation and reproducibility

- `ApertusClient` owns a lazy persistent `httpx.Client`, with injection for tests, bounded pools,
  an explicit close/context manager and rate admission before every retry.
- FastAPI shares the service for the application lifespan and closes it on shutdown. CLI and
  evaluation jobs reuse a service within the job and close its pool afterward. Streamlit closes
  its per-action service; it does not claim a persistent cache or cross-click connection reuse.
- Production settings accept only `LLM_BATCH_SIZE=1`. Rejected implementations are isolated
  in `evaluation/experimental_batching.py`, used only by the research runner for configurable
  sizes 1/3/5; they are not exposed by the production API or CLI.
- The acceptance rule and raw outcomes are retained in
  [results/batching-20261018-summary.json](results/batching-20261018-summary.json).
  Local ignored artifacts are in `results/batching-20261018/`: panel and baseline hashes,
  pre-send budget ledger, response usage/connection traces, per-case outcomes and phase times.
  `measured-source/` preserves the exact source used for the experiment before rejected batching
  was moved out of production. The recorded manifest hashes refer to those measured sources.

The reproducible comparison driver is `python -m parltopic.evaluation.batch_performance` with
`prepare`, `run` and `summarize` modes. Prepare freezes 30 IDs/labels and plans 39 calls for this
panel; run refuses changed source/data and any already-started experiment. A new directory
means a new paid experiment, not continuation of the current authorization. Offline tests cover
pool ownership, request equivalence, strict rolling admission, the hard HTTP attempt cap,
cross-affair evidence rejection, missing/duplicate IDs, production batch rejection and lifespan
cleanup. Re-running the comparison is not necessary for this decision.
The `verify-refactor` mode repeats the 450-case offline equivalence check without any API calls.

## Initial 100-affair benchmark, before connection reuse

The following initial results were measured on 18 October 2026 on branch `experiment/classifier-quality`, using the configured
`swiss-ai/Apertus-v1.5-70B` endpoint and existing `hybrid-v3` topic policy. Production classifier
code and topic configuration were not changed during that initial measurement. E02 was not enabled.

## Findings

- **100 real affairs, 83 inference calls:** 17 affairs were classified by existing keyword
  rules. All 100 returned decisive, valid results. A separate eight-call instrumentation check
  brings the total to **91 HTTP inference attempts**, all HTTP 200, without retries.
- A model-required HTTP response took **2.132 s on average**, median **2.019 s**, P95
  **2.824 s**, P99 **3.875 s**, across 83 primary requests. Local preprocessing averaged
  **0.860 ms**, postprocessing **0.176 ms** per affair.
- Sequential operation processed 50 affairs in **98.538 s** (**0.507 affairs/s**). Four-worker
  operation processed a different, matched 50-affair group in **83.122 s** (**0.602 affairs/s**).
  Both used an intentionally conservative **30 request-starts/minute** cap. The throughput
  ratio is **1.185**, a descriptive comparison, not a paired causal speedup estimate.
- The first observer version added lock waiting to parallel total/client latency. The HTTP
  timings remain clean. The observer was corrected and checked with eight additional calls;
  the main parallel total-latency percentiles must **not** be interpreted as production tails.

The most useful next work is connection reuse and quota-aware scheduling, followed by exact
result caching for repeated requests. Shorter prompts are a separate quality-sensitive experiment.

## Scope and architecture

The sample contains 61 German, 21 French and 18 Italian affairs from 2018–2023, with 33 tagged
positives and 67 untagged proxy negatives, spanning federal and 24 cantonal parliament codes.
It is proportionally sampled from the existing 450-affair development set, with 50 cases per
arm, balanced by language, label, rule outcome and approximate text length. Thirty-seven affairs
have title-only input. The largest supplied affair is 4,112 characters including field separators;
long PDF collections and a full production-volume mix are not represented.

The measured path is schema validation -> chunking -> keyword gate -> BM25 passage ranking
-> prompt construction -> Apertus HTTP request -> output schema/evidence validation -> result.
The API, CLI and Streamlit interface share the same classification service. The normal classify
CLI processes cases sequentially; `run-eval` already supports a thread pool. BM25 runs within
each affair, not across all 300,000 affairs. No embedding prefilter or general inference-result
cache exists. The API constructs a service per request; `ApertusClient` uses top-level
`httpx.post` and therefore creates a fresh connection per call.

The sample uses `configs/topics/digitalisation.yaml` and current environment settings, without
changing prompt wording, context, model parameters, retrieval or decision rules. The benchmark
injects timers around the existing client and observes the original HTTP function.

## Observed timings

HTTP response time includes connection setup, transfer, provider queueing and generation. It
does not isolate GPU generation or time to first token. Model-only distributions exclude the
17 local rule cases; otherwise zeros would make API latency look artificially low.

| Model-required HTTP time | Sequential, n=42 | Parallel, n=41 | All, n=83 |
| --- | ---: | ---: | ---: |
| Mean | 2.252 s | 2.010 s | 2.132 s |
| Median | 2.090 s | 1.933 s | 2.019 s |
| P95 | 3.369 s | 2.784 s | 2.824 s |
| P99 | 4.723 s | 2.882 s | 3.875 s |

The following are raw worker-to-result measurements across all affairs, including local rules,
admission waiting and observer overhead. They exclude time queued for an executor worker.

| Per-affair measurement | Sequential, n=50 | Parallel, n=50 |
| --- | ---: | ---: |
| Mean total | 1.970 s | 6.494 s † |
| Median total | 2.059 s | 6.427 s † |
| P95 total | 3.213 s | 12.023 s † |
| P99 total | 4.568 s | 12.110 s † |
| Mean preprocessing | 1.030 ms | 0.690 ms |
| Mean postprocessing | 0.099 ms | 0.253 ms |
| Mean measured admission wait | 0.076 s | 2.891 s |
| Phase wall time | 98.538 s | 83.122 s |
| Throughput | 0.507 affairs/s | 0.602 affairs/s |

† The initial response logger acquired the admission lock, which other workers held while
waiting for the next allowed request start. Parallel client time minus HTTP and measured
admission time averaged **1.953 s** per affair, predominantly observer contention. This is an
instrumentation bottleneck, not evidence that production postprocessing takes seconds.

The corrected observer separates logging and admission locks. An offline concurrency test
proves responses can finish while the admission lock is held. Eight extra live calls with four
workers finished in **15.909 s**; mean HTTP time was **1.983 s**, and client time minus HTTP and
admission averaged **2.347 ms**. Mean worker-to-result time was **6.491 s**, P95 **8.106 s** and
P99 **8.153 s**, mostly because four workers share two-second start spacing. These eight
cases all required the model and are too few to replace the primary 50-case tail distributions.
We did not rerun the 100-case experiment, preserving the requested API budget.

Parallel throughput was already close to this configuration's admission ceiling: 41 model
requests / 50 affairs at 0.5 allowed starts/s gives approximately **0.610 affairs/s**. Actual
throughput was 0.602. Thus the controlled rate cap explains the bulk processing ceiling even
though the original logger materially inflated per-worker latency. A faster bulk job and lower
per-request latency are different objectives; four workers cannot bypass the admission cap.

## Tokens, prefix caching and estimated costs

| Usage | Sequential 50 | Parallel 50 | Primary 100 |
| --- | ---: | ---: | ---: |
| Inference requests | 42 | 41 | 83 |
| Input tokens | 57,371 | 55,347 | 112,718 |
| Output tokens | 4,228 | 3,997 | 8,225 |

All 83 primary responses supplied usage. They reported **91,840 cached input tokens**, or
**81.5%** of input tokens; 82 responses reported 1,120 cached tokens each. This is provider
prefix caching, not reuse of a previous classification result. It can influence latency. There
was no isolated cold-cache comparison, and the cached-token billing discount is unverified.

The eight-call check used another 11,140 input and 800 output tokens. Total actual benchmark
usage is **123,858 input + 9,025 output tokens across 91 calls**. Remaining call budget was not
spent. No credentials or authorization headers are written to artifacts.

CSCS directs users to its Inference UI for model prices and applies project/key resource limits.
The project-specific tariff and quota could not be verified from the public documentation.
Therefore monetary estimates are explicitly `null`, not zero. For verified prices `Pi` and `Po`
per million full-rate input/output tokens in the same currency:

- Primary 100 affairs: **`0.112718 × Pi + 0.008225 × Po`**.
- Entire paid measurement including observer check: **`0.123858 × Pi + 0.009025 × Po`**.
- 300,000 affairs at the pooled primary sample mix: **`338.154 × Pi + 24.675 × Po`**.

These formulas assume all input is charged at the full rate; use verified cached-token billing
rules before replacing them with a discounted estimate. This is not a provider invoice.

## Projection to 300,000 affairs

| Scenario | Measured basis | Projected continuous time |
| --- | --- | ---: |
| Sequential | 50 affairs / 98.538 s | **164.23 hours / 6.84 days** |
| Four workers, benchmark cap 30 starts/min | 50 affairs / 83.122 s | **138.54 hours / 5.77 days** |

These are **single-topic, sample-mix scenarios**, not a production SLA. They assume stable
endpoint load, similar title/body lengths, rule hits, cache behavior and zero outages/retries.
Downloads, ingestion, enrichment, manual review and indexing are excluded. The primary parallel
measurement includes the observer issue described above. Extrapolating tails or many topics
from this sample is unsupported. The pooled token projection is **338.154M input + 24.675M
output tokens**; each arm's distinct token projection is also available in the aggregate JSON.

At the pooled 83% model-call fraction, the 30-start/min cap alone implies about 138.3 hours.
If the actual project quota permits **60 starts/minute**, the admission-only scenario falls to
about **69.2 hours**, provided model capacity and token quotas also permit that rate. This is
an unmeasured scenario, not a demonstrated optimization. More threads at the existing 30/min
cap cannot deliver this reduction.

## Bottlenecks and five prioritized optimizations

Local preprocessing plus postprocessing is about **0.06%** of sequential worker time. CPU
micro-optimization, more elaborate local batching or changing BM25 is unlikely to improve this
workload materially. The dominant observed costs are the remote response and admission wait.
Connection setup is included in remote time but was not separately measured. Every outgoing
model request repeats **5,109 fixed prompt/taxonomy characters** before adding the passages.

Expected effects below are engineering hypotheses or explicit formulas. No optimization was
implemented or measured against baseline in this task.

| Priority / change | Expected speed effect | Effort | Macro-F1, precision and recall | API cost effect |
| --- | --- | --- | --- | --- |
| 1. Persistent HTTP client | Removes repeated connection setup; exact gain unmeasured. If setup were 100 ms, a 2.132 s model call would improve by about 4.7%; this is a scenario. The rate cap can mask bulk gains. | Small | No intended decision change; verify payload/output equivalence and coverage. | Same requests/tokens. |
| 2. Quota-aware concurrency; async when useful | Already near the current cap. Higher verified admission rate can help: 30 -> 60/min gives an admission-only ceiling up to 2× higher. Async at unchanged quota has no demonstrated gain over four threads. | Medium; async lifecycle adds work | No intended metric change; timeouts, dropped work and retries must not reduce coverage. | Similar tokens; better backoff can prevent wasted retries. |
| 3. Exact validated-result cache | At cache-hit fraction `h`, paid calls fall to about `1-h`; first-pass unique work can have `h=0`. Cache hits avoid model latency, but cache-read latency is unmeasured. | Small–medium | Same valid output if keys/invalidation include source, taxonomy, model, policy and evidence identity. Stale entries can harm all metrics. | About `h` of repeat-request token charges avoided; small local storage cost. |
| 4. Shorter prompts and less redundant context | Target a separately tested 20% input reduction first. This does not imply 20% lower latency, particularly with existing prefix-cache hits. Lowering top-k 5 -> 3 affects only six primary cases. | Medium | Can change all metrics; missing definition details, negations or context can reduce precision/recall. Require paired validation. | 20% lower full-rate input charges in that scenario; output charges unchanged. Cache pricing may alter savings. |
| 5. Embedding candidate filter | If `q` of current model cases remain, LLM work becomes roughly `q` of baseline, plus embedding/retrieval work. Example `q=0.5` halves LLM requests, not necessarily total latency. | High | False negatives at the filter cannot be recovered; recall is the main risk, and macro-F1/precision may also change. Start in shadow mode. | Fewer LLM tokens, offset by embedding/index/update costs. |

Batching has two meanings. Grouping background jobs for scheduling preserves one LLM request
per affair and offers little benefit when local overhead is already tiny. Sending multiple affairs
in one chat prompt could amortize the taxonomy but changes the model contract and risks mixed
evidence, decision contamination and partial failures. Provider-side Batch API support and batch
pricing were not established by the documentation inspected. Multi-affair prompting is therefore
a later quality experiment, with no claimed speedup or discount.

## Quality guardrail and implementation sequence

This 100-case run has TP=28, FP=2, FN=5, TN=65: **macro-F1 0.9189**, macro-precision **0.9310**,
macro-recall **0.9093**, positive precision **0.9333**, positive recall **0.8485**, decisive coverage
**100%**. These describe a selected, proxy-labeled performance sample, not a new quality win.
The arm-specific metrics cannot establish a concurrency effect because the cases differ.

Implement connection reuse first, then verify project quota and improve bounded scheduling.
Add exact-result caching for the demo/repeated workflows. Evaluate compact prompts on the full
fixed validation set before changing defaults. Keep embedding filtering and multi-affair batching
behind separate experiments. For changes to classification behavior, preserve the existing
acceptance criterion: macro-F1 increases and macro precision/recall each decline by at most
0.01 absolute; also inspect positive/per-language recall, errors and decisive coverage.

The [implementation plan](performance_implementation_plan.md) gives acceptance checks and
component changes for each priority. No further live calls are included in that plan's execution.

## Reproducibility and validation

- Script: [`src/parltopic/evaluation/performance.py`](../src/parltopic/evaluation/performance.py).
- Full procedure and timing definitions: [performance_methodology.md](performance_methodology.md).
- Checked-in aggregate evidence: [results/performance-20261018-summary.json](results/performance-20261018-summary.json).
- Local raw evidence: `results/performance-20261018/` (ignored): fixed panel, original source
  manifest, per-affair outputs, pre-send attempt ledger, per-response usage/headers and phase
  runtimes. `instrumentation-v1.py` preserves the initial observer byte-for-byte; the separate
  calibration manifest records both observer hashes and the eight repeated IDs.
- Instrumentation checks cover concurrent smoke/total budget limits, provider rejection,
  deterministic sampling, additive timer boundaries, original request/output equivalence and
  separation of response logging from the admission lock. Test fixtures never enter metrics.

Sources: [CSCS inference API, pricing and access](https://docs.cscs.ch/services/inference/api/)
and [HTTPX connection pooling](https://www.python-httpx.org/advanced/clients/), consulted
18 October 2026. The exact project tariff, token quota and connection-handshake cost remain
unverified; they are not replaced with invented measurements.
