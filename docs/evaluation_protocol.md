# Evaluation protocol

The checked-in E1 data is an **opened validation benchmark**, not a sealed test set.
PolitMonitor-tagged affairs are positive examples. Affairs without that tag are
positive-unlabeled proxies, not manually adjudicated negatives. Metrics therefore measure
agreement with the available tags and can understate precision when an apparently false
positive is actually relevant.

## Primary metrics

- Macro-F1 is the primary selection metric so both classes have equal weight.
- Positive-class precision and recall remain visible because topic search needs both.
- Coverage is reported separately; uncertain, failed, or missing classifications are not
  silently converted into negatives.
- Precision at the natural corpus prevalence is reported to expose false-positive risk that
  is hidden by the deliberately balanced validation sample.
- Prompt comparisons use identical affairs and a paired bootstrap confidence interval.

## Model-development policy

1. Tune prompts, retrieval, and thresholds only on `e1_digitalisation_dev.jsonl`.
2. Treat the current `e1_digitalisation_test.jsonl` as additional opened validation because
   its labels and aggregate results have already been inspected.
3. Before claiming final performance, create a new sealed, temporally later holdout.
4. Manually adjudicate a stratified sample, especially model false positives and uncertain
   cases, with two reviewers and an explicit topic rubric.
5. Report confidence intervals, language/level slices, model version, prompt version, and
   label provenance with every headline score.

Run a paired comparison with:

```bash
parltopic compare-runs \
  --eval-set data/eval/e1_digitalisation_dev.jsonl \
  --baseline-results results/prompt-v1.jsonl \
  --candidate-results results/prompt-v2.jsonl
```

The production candidate is a cascade: exact configured multilingual terms are assigned by a
deterministic rule, and only non-matches are sent through retrieval and Apertus. This rule must
be evaluated as part of the complete classifier policy, not as an isolated model score.
