# Experiments against main

All experiment changes stay on `experiment/classifier-quality`. The pinned main commit is
`1266c7ebfc1819c3c6c8d134699ebdfb138b204c`. No checkout, commit or merge changes main.

## Fixed evaluation and acceptance

The current validation set is `data/eval/e1_digitalisation_dev.jsonl`: 450 affairs, 150 tagged
positives and 300 untagged proxy negatives, DE/FR/IT. SHA-256:
`5fb54735bc2d51045dbde3209004172987081e64870e81322118c853d682237b`.
It is not a final test. Apertus has no task-specific training here. The separate linear baseline
excluded all these IDs and exact matching titles from training. Proxy-label noise, previous
validation tuning and one-topic scope limit all performance claims below.

Accept a candidate only when macro-F1 increases and neither macro-precision nor macro-recall
drops by more than 0.01 absolute. An eligible development candidate remains optional until
confirmed independently. Preserve baseline predictions, topic definition and original behavior.
The final-test file is not used to select this change; the previously running test-file inference
was terminated and its partial results are excluded from the table.

Macro precision/recall below average the positive and negative classes of **one binary topic**.
Micro-F1 includes both mutually exclusive classes and therefore equals accuracy. These results
are not macro averages across the complete APS or Curia topic taxonomy.

## Iteration table

| Baseline | Experiment | Macro-F1 | Macro-Precision | Macro-Recall | Micro-F1 | Delta to main |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| main 1266c7e, Apertus 70B | Verified original main run | 0.9070 | 0.923 | 0.895 | 0.920 | 0 |
| same main, same 450 affairs | E01: title-only disinformation/automated-trading anchors | 0.9098 | 0.925 | 0.898 | 0.922 | +0.0028 |

Main confusion matrix: TP=123, FP=9, FN=27, TN=291. E01: TP=124, FP=9, FN=26, TN=291.
The only changed decision is the French title “Importance du négoce à haute fréquence en Suisse”.
French macro-F1 moves from 0.881 to 0.896; German (0.920) and Italian (0.893) are unchanged.
Remaining proxy errors by language are DE: 15 FN / 4 FP; FR: 5 FN / 3 FP; IT: 6 FN / 2 FP.
Several missing positives have insufficient title-only inputs; broad document enrichment previously
reduced precision through incidental mentions. These are the largest observed failure sources.

The paired 5,000-sample bootstrap interval for delta is [0.0000, 0.0087]. This small, validation-
selected gain is not independently significant; no production or multi-topic quality claim follows.

## Baseline verification, runtime and costs

The original main run is `results/hybrid_v3_actual_dev450.jsonl`. Its manifest contains the full
topic, settings, dataset hash and hashes of seven classification/retrieval/model source files.
`title_experiment` verifies every source hash against the pinned main content and compares the
baseline topic against main. This verifies an actual historical main run rather than attributing
an earlier weaker prompt to the current baseline.

E01 does not change the system/user prompt or retrieval query. For every required model call,
the replay compares its exact prompt with the saved baseline request before returning that
case's stored completion. Rule outputs cannot substitute for missing model completions.
Additional deterministic title rules run through the real classification service. This is a
prediction replay, not a new live model measurement or a model-accuracy estimate from invented
completions. Apertus remains the central semantic classifier.

| Measurement | main | E01 |
| --- | ---: | ---: |
| Recorded/required input tokens | 506,252 | 503,409 |
| Recorded/required output tokens | 36,846 | 36,642 |
| Sum of recorded request latencies, seconds | 1,387.185 | 1,379.545 |
| Recorded per-case latency median, ms | 3,357.949 | 3,353.733 |
| New API calls for this replay | 0 | 0 |

Replay processing took 0.292 seconds on the local machine, excluding bootstrap comparison.
Summed request latencies are not concurrent wall-clock runtime. No historical wall-clock run
duration was captured. Currency cost of the original model calls is unknown without provider
rates; actual incremental API cost of this replay is zero. Token totals provide an auditable cost
basis without inventing a tariff. Retries and billed provider-side work may not be fully reflected.

## Reproduce and use the optional candidate

```bash
python -m parltopic.evaluation.title_experiment \
  --eval-set data/eval/e1_digitalisation_dev.jsonl \
  --baseline results/hybrid_v3_actual_dev450.jsonl \
  --overlay configs/experiments/digitalisation-title-candidate.yaml \
  --output results/title_anchors_vs_main_dev450.jsonl
```

The command requires the original baseline results plus manifest, refuses an existing output,
and writes a full report including per-language metrics, usage and acceptance outcome. Choose
a new output filename when repeating. Raw prediction artifacts remain ignored by Git.

To run live inference with the candidate, add
`--title-rules configs/experiments/digitalisation-title-candidate.yaml` to `parltopic classify`
or `parltopic run-eval`. The base topic remains `configs/topics/digitalisation.yaml`. The
overlay changes only title matching, not taxonomy wording, prompt examples or generic body terms.
