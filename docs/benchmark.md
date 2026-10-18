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
