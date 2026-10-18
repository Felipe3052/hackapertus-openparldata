# Development benchmark

All numbers below use the 450-example E1 development split. The labels are
positive-unlabeled proxies, so this is model-selection evidence rather than a final quality
claim. The existing test split has already been opened and is not used for prompt selection.

| Classifier | Precision | Recall | Positive F1 | Macro-F1 |
| --- | ---: | ---: | ---: | ---: |
| Multilingual keyword baseline | 0.930 | 0.440 | 0.597 | 0.733 |
| Hybrid keyword + Apertus, prompt v1 | 0.927 | 0.767 | 0.839 | 0.885 |
| Hybrid keyword + Apertus, prompt v2 | 0.929 | 0.780 | 0.848 | 0.890 |
| Candidate v3 policy, adds `online` and token-safe `NFT` gates | 0.931 | 0.813 | 0.868 | 0.904 |
| Hybrid v3, fresh end-to-end inference with current topic examples | 0.932 | 0.820 | 0.872 | 0.907 |

Prompt v2 versus v1 was compared on all 450 paired examples with 10,000 bootstrap samples:
macro-F1 delta `+0.0057`, 95% interval `[-0.0055, +0.0179]`, and bootstrap probability of a
positive delta `0.7818`. It is a small directional gain, not yet conclusive.

The v3 policy was replayed deterministically over the complete v2 result set. `online` occurred
in eight development examples; all four previously missed examples were positive and no new
false positive was introduced. A token-safe `NFT` rule adds one further true positive and avoids
substring errors such as matching `Entwurf`. Against v2, the paired macro-F1 delta is `+0.0140`;
a 10,000-sample bootstrap gives a 95% interval of `[+0.0028, +0.0273]` and probability of
improvement `0.9943`. This is still a development-set result and requires confirmation on a
newly sealed, manually adjudicated holdout.

The strongest remaining slice gap is Italian: prompt v2 reaches macro-F1 `0.849`, precision
`0.917`, and recall `0.710` before the v3 online gate.

## Verified full v3 run (2026-10-18)

`results/hybrid_v3_actual_dev450.jsonl` contains fresh predictions from the current topic YAML,
prompt v2, hybrid-v3 policy and Apertus 70B. All 450 examples have decisive results; the confusion
matrix is TP=123, FP=9, FN=27, TN=291. Its sibling provenance manifest records the dataset,
configuration and implementation hashes. This replaces the replay estimate as the current
end-to-end development result.

| Language | N | Precision | Recall | Macro-F1 |
| --- | ---: | ---: | ---: | ---: |
| German | 276 | 0.950 | 0.835 | 0.920 |
| French | 93 | 0.880 | 0.786 | 0.881 |
| Italian | 81 | 0.926 | 0.806 | 0.893 |

Against the historical hybrid-v2 run, 10,000 paired bootstrap samples give macro-F1 delta
`+0.0168`, percentile interval `[+0.0027, +0.0333]` and a positive-delta resampling fraction
`0.9833`. These intervals do not account for choosing the rules after inspecting development
labels. They also include differences in topic examples and inference variability.

Data completeness remains a substantial limit: 173/450 inputs contain only a title, including
61 positive examples. Original documents and full source texts are the next data improvement
to evaluate. A new adjudicated holdout is still required for an independent quality estimate.

## Document enrichment experiment

The label-independent `enrich-documents` command added 423 documents to 149 of the 173
title-only affairs. Twenty-four affairs had no usable document text; there were no API failures.
Existing source rows, labels and ordering were preserved in a separate processed dataset.

On these same 450 IDs, unrestricted hybrid-v3 document matching produced precision `0.828`,
recall `0.867`, positive F1 `0.847` and macro-F1 `0.884` (TP=130, FP=27, FN=20, TN=273).
This is worse than the original-input run's macro-F1 `0.907`. Many newly positive predictions
were automatic matches in lengthy reports; two model explanations cited JavaScript browser
requirements from retrieved source text. This variant is retained as an experiment.

The next candidate disables deterministic keyword assignment inside attached documents and
pins the affair title in the model context. Document mentions then require model verification.

That candidate (`hybrid-v4-candidate`) was evaluated on all 450 enriched inputs with full
coverage: precision `0.919`, recall `0.833`, positive F1 `0.874`, macro-F1 `0.908`
(TP=125, FP=11, FN=25, TN=289). Compared with the unrestricted document policy it restores
most precision. Compared with the original-input v3 run, macro-F1 delta is only `+0.0007`,
with a 10,000-sample paired bootstrap interval `[-0.0151, +0.0174]`. This is not a demonstrated
overall improvement; v3 defaults are retained while document controls remain configurable.

Reproduce the candidate with:

```bash
KEYWORD_DOCUMENT_GATE_ENABLED=false RETRIEVAL_PIN_TITLE=true \
CLASSIFIER_POLICY_VERSION=hybrid-v4-candidate \
parltopic run-eval \
  --eval-set data/processed/enriched/e1_digitalisation_dev.jsonl \
  --topic configs/topics/digitalisation.yaml \
  --output results/hybrid_v4_documents_dev450.jsonl --workers 8
```

Ongoing quality experiments are developed on branch `experiment/classifier-quality`.
