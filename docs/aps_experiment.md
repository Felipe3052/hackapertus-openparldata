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
multilingual label overlap, preserves the title and stable segment order, and reports approximate
token compression. It is wired into the existing classifier only as an opt-in experiment. The
default baseline therefore remains unchanged while recall, token reduction and latency can be
compared.

The classifier now exposes the same router as an opt-in experiment through
`APS_CONTEXT_ENABLED=true`. The default is `false`; with the flag enabled, the result records the
taxonomy version, context policy, segment counts and approximate token counts. If no APS candidate
is found, the full context is retained and the result records the fallback reason.

On the checked-in E1 digitalisation validation file (1,200 affairs), the shadow run with five
context segments routed 577 affairs and fell back for 623. The approximate token reduction was
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

The next experiment must add an independent, double-annotated APS holdout before using hard
routing. It must support multiple topic codes, `not_classifiable`, taxonomy versions and a
consensus rule. Any context-compression candidate must retain valid evidence IDs and pass the
existing digitalisation regression gates for macro-F1, positive recall, coverage and DE/FR/IT.
