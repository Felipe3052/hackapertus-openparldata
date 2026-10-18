# APS experiment branch

Branch: `experiment/aps-context-pipeline`

## Current finding

The repository contains a clean APS taxonomy with 165 topics, 22 chapters and 8 domains.
The existing classifier is a binary, user-defined-topic pipeline; it does not yet perform APS
multi-label classification. The 50-affair APS sample covers German, French and Italian affairs
at federal and cantonal level. Only 20 affairs have two human annotations. Chapter agreement is
11/20 (55 %) and main-topic agreement is 9/20 (45 %), so these labels are useful for an experiment
but are not a model-quality gold standard.

## Shadow architecture

```text
Domain → Chapter → Topic
                    ↑
Affair → APS candidate router → bounded context selector → existing Apertus classifier
                         ↘ route manifest and token/compression measurements
```

The router is deterministic and does not call Apertus. It ranks chapter and topic candidates by
available taxonomy-label overlap, preserves the title and stable segment order, and reports
approximate token compression. The checked-in APS taxonomy has German and French labels; it does
not yet contain an official Italian label set. Italian input is therefore supported by the
pipeline interface but its APS routing recall is not established. The router is wired into the
existing classifier only as an opt-in experiment. The default baseline therefore remains
unchanged while recall, token reduction and latency can be compared.

An optional, version-matched alias file can be supplied with `APS_ALIASES_PATH` or the CLI
`--aliases` option. It is intended for reviewed Italian or domain-specific synonyms. Such aliases
are project additions, not official APS translations, and must be evaluated before use.

The classifier now exposes the same router as an opt-in experiment through
`APS_CONTEXT_ENABLED=true`. The default is `false`; with the flag enabled, the result records the
taxonomy version, context policy, segment counts and approximate token counts. If no APS candidate
is found, the full context is retained and the result records the fallback reason.

On the checked-in E1 digitalisation validation file (1,200 affairs), the shadow run with five
context segments routed 1,131 affairs and fell back for 69. The approximate token reduction was
0 % because the available affairs are short enough to fit within five selected segments. This is
an observed offline result without Apertus calls, not evidence of a latency improvement. Use
`--max-segments 2` or a long-text export for a controlled compression experiment, then compare
quality and latency on identical IDs before enabling it for production.

Run the shadow router offline:

```bash
parltopic aps-route \
  --input data/eval/e3_aps_sample.jsonl \
  --output results/aps-shadow.jsonl
```

Run the diagnostic against the existing double annotations:

```bash
parltopic aps-evaluate \
  --sample data/eval/e3_aps_sample.jsonl \
  --labels data/eval/e3_aps_labels.jsonl
```

The output reports candidate recall and annotator disagreement. It is intentionally labelled a
diagnostic because 20 double annotations with 55 % chapter agreement do not establish an APS gold
standard.

Before creating a holdout, check all split IDs:

```bash
parltopic aps-check-leakage \
  data/eval/aps_dev.jsonl data/eval/aps_tuning.jsonl data/eval/aps_holdout.jsonl
```

The command exits with status 1 for duplicate IDs within a split or overlaps between splits.
As a current audit example, E1 digitalisation validation and E2 Curia Vista share 24 affair IDs;
they must therefore not be presented as independent APS holdout evidence.

Create a leakage-safe annotation template from a larger source export:

```bash
parltopic aps-annotation-template \
  --input data/raw/affairs.jsonl \
  --output data/eval/aps_holdout_annotations.jsonl \
  --exclude data/eval/e1_digitalisation_test.jsonl \
  --exclude data/eval/e2_curia_test.jsonl \
  --sample-size 100 \
  --seed 42
```

The command stratifies by language and parliament level, leaves APS labels blank, records the
source hash and refuses duplicate source IDs. Two independent annotations and a documented
consensus step are required before the file can be used as a quality benchmark.

Build the evaluator-compatible unanimous subset after double annotation:

```bash
parltopic aps-consensus \
  --labels data/eval/e3_aps_labels.jsonl \
  --output data/eval/e3_aps_consensus.jsonl
```

Only exact agreement on chapter, topic, secondary topic and `none` is retained. The command
reports and excludes disputed affairs instead of silently choosing one annotator.

On the checked-in 20 double annotations, this produced 9 unanimous labels and excluded 11
disputes. After hierarchical parent closure and conservative word-prefix matching, the offline
router diagnostic on those 9 labels reached 42.9 % chapter recall and 42.9 % topic recall at the
configured candidate limits (previously 14.3 % and 28.6 %). This small diagnostic is not a
generalizable quality metric: the deterministic router is still not suitable as a hard APS
classifier and remains a candidate/context pre-filter until it is validated on a larger holdout.

Compare the actual retrieval context sent to a future prompt:

```bash
parltopic aps-benchmark \
  --input data/eval/e1_digitalisation_test.jsonl \
  --topic configs/topics/digitalisation.yaml \
  --max-segments 2
```

This compares identical Affairs with the same topic and retrieval implementation. It measures
whitespace token approximations offline. On the checked-in E1 file with `max-segments 2`, the
baseline context is approximately 152,141 tokens and the APS context approximately 90,604
tokens, a 40.4 % reduction. This does not claim an Apertus latency or quality gain.

A controlled live smoke test used one German, one French and one Italian affair, each with a
baseline and APS-context call to the same Apertus endpoint. All three paired statuses were
unchanged. Across the six calls, measured latency was 21.0 % lower and input tokens were 33.0 %
lower. The Italian pair was slower with APS context despite using 34.7 % fewer input tokens,
showing that endpoint variance is material. The full record is
[`docs/results/aps-live-smoke-20261018.json`](results/aps-live-smoke-20261018.json). This is
one paired example per language and must not be generalized to all topics or parliament levels.

After producing a candidate result file with the same evaluation IDs, run the regression gate:

```bash
parltopic aps-regression-gate \
  --eval-set data/eval/e1_digitalisation_test.jsonl \
  --baseline results/baseline.jsonl \
  --candidate results/aps-context.jsonl
```

The default gate allows at most one percentage point loss in overall Macro-F1 or positive Recall,
three percentage points per sufficiently large language/level group, and no coverage loss.

The next experiment must add an independent, double-annotated APS holdout before using hard
routing. It must support multiple topic codes, `not_classifiable`, taxonomy versions and a
consensus rule. Any context-compression candidate must retain valid evidence IDs and pass the
existing digitalisation regression gates for macro-F1, positive recall, coverage and DE/FR/IT.
