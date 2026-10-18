# Experiment log

All runs use the frozen eval sets in `data/eval/` (seed 42, built by `parltopic build-eval`) and the
CSCS endpoint. Prompts and topic definitions are tuned on the **dev split only**; the test split is
run once per final configuration. Tables come from `parltopic compare`; raw results are in
`results/` (not committed).

## Eval sets

| Set | Content | Size | Notes |
|---|---|---|---|
| E1 dev | PolitMonitor "Digitalisierung" positives vs. untagged affairs, 2018–2023 | 150 + 300 | for tuning |
| E1 test | same, 2024–2026, frozen | 400 + 800 | DE 670, FR 325, IT 205; federal 585, cantonal 609, municipal 6 |
| E1 few-shot pool | labelled 2018–2023 affairs not in the dev sample | 2,337 + 9,348 | titles only |
| E2 test | Curia Vista subject areas (28, multi-label), 2024–2026 | 500 | DE/FR/IT ~1/3 each, 2.5 labels per affair |
| E4 | DVS list of digitalisation affairs | 30 | positives only, cross-level check |

Negatives come from the same parliaments, period and affair types as the positives, sampled per
parliament in proportion to its positives (the parliament alone does not reveal the label).
Prevalence in the eligible population: 3.4 % (dev period), 2.3 % (test period). PolitMonitor tags
are incomplete, so precision against them is a lower bound: all 3 "false positives" of run E1.2
(e.g. *Digital Services Act per la Svizzera*) are in fact digitalisation affairs.

Federal affairs are randomly assigned one of DE/FR/IT (title and submitted text in that language),
so the same pipeline is measured per language on official translations.

## E1 — digitalisation (dev, 450 affairs)

| Run | P | R | F1 | F1 lang=de | F1 lang=fr | F1 lang=it | F1 level=federal | F1 level=cantonal | tokens in/out per affair |
|---|---|---|---|---|---|---|---|---|---|
| B0 keyword search (DE/FR/IT synonyms) | 0.930 | 0.440 | **0.597** | | | | | | 0 / 0 |
| E1.1 70B, topic v1 | 0.966 | 0.573 | **0.720** | 0.773 | 0.682 | 0.578 | 0.660 | 0.755 | 630 / 76 |
| E1.2 70B, topic v2 (inclusion rule) | 0.952 | 0.667 | **0.784** | 0.840 | 0.711 | 0.667 | 0.680 | 0.852 | 815 / 86 |
| E1.2 repeated | 0.952 | 0.667 | **0.784** | 0.840 | 0.711 | 0.667 | 0.680 | 0.852 | 815 / 87 |
| E1.3 8B, topic v2 | 0.951 | 0.260 | **0.408** | 0.404 | 0.389 | 0.439 | 0.463 | 0.355 | 815 / 82 |

Findings:

- **Topic definition matters more than anything else so far.** v1 → v2 adds an explicit inclusion
  rule ("assign as soon as digital technology, IT, data, online services or telecoms are an
  essential aspect, even if only the title is available") and examples from the PolitMonitor scope
  (IT/ERP credits, ChatGPT in schools, 5G, data-protection reports): recall 0.57 → 0.67 at the same
  precision.
- **70B is deterministic at temperature 0:** the repeated run changes 0 of 450 labels, so paired
  differences are not run-to-run noise (unlike Fact Attack, where 3 of 1,488 changed).
- **8B is not an option for this task:** recall 0.26 vs. 0.67. It rejects most affairs where the
  digital aspect is not in the title. It also returned `evidence_ids` as nested lists in 169 of 450
  answers, which crashed the service (fixed: unknown or non-string IDs are dropped).
- **Apertus' score is not a usable confidence:** 46 of the 64 missed positives (E1.1) carry a
  score ≤ 0.1, and only 16 of 450 answers lie between 0.1 and 0.9. A cascade on the score cannot
  find the misses (same finding as in Fact Attack).
- **Errors are mostly a scope mismatch:** in many misses the model names the digital aspect itself
  (online booking platforms, anonymous online applications, surveillance technology, ERP systems)
  and still answers `not_assigned` because it is not the core topic. PolitMonitor also tags side
  aspects. A smaller part of the misses looks like label noise (pension, rail, CO₂ affairs).
- Federal and Italian affairs are the weak spots (F1 0.68 / 0.67 vs. cantonal 0.85).

Cost reference: E1.2 needs 815 input and 86 output tokens per affair. At the Public AI list price for
Apertus 70B (USD 0.82 / 2.92 per million tokens) that is about USD 0.92 per 1,000 affairs, i.e.
~USD 300 for all 325,000 affairs and one topic without a pre-filter. Throughput: 450 affairs in
168 s with 8 parallel requests (p50 latency 2.9 s).

## Open experiments

- E1.4 thinking only for `not_assigned` answers (reasoning prefill `<|inner_prefix|>`)
- E1.5 retrieved few-shot examples (3 most similar tagged + 3 untagged affairs from the pool)
- E1.6 topic v3: side aspects count
