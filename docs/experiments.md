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
| E1.4 70B v2 + thinking for `not_assigned` | 0.935 | 0.773 | **0.847** | 0.861 | 0.846 | 0.807 | 0.814 | 0.873 | 1,430 / 644 |
| E1.5 70B v2 + 3+3 retrieved few-shot examples | 0.952 | 0.660 | **0.780** | 0.810 | 0.739 | 0.720 | 0.701 | 0.831 | 953 / 88 |
| E1.6 70B, topic v3 (side aspects count) | 0.955 | 0.700 | **0.808** | 0.847 | 0.766 | 0.720 | 0.733 | 0.859 | 849 / 84 |

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

- **Thinking for the rejections is the largest gain so far (E1.4, +0.063 F1).** Apertus only reasons
  when the assistant turn is prefilled with `<|inner_prefix|>` (a prompt instruction or the
  `-thinking` model alone does not trigger it); the answer is parsed after `<|inner_suffix|>`. Of
  340 re-checked rejections, 19 flip to `assigned`, 16 of them correctly; the 3 others
  (*Frais de surveillance téléphonique*, *Punir enfin le pédopiégeage en ligne*, *analfabetismo
  visivo*) are arguably digital, i.e. label gaps. It lifts exactly the weak spots: FR 0.71 → 0.85,
  IT 0.67 → 0.81, federal 0.68 → 0.81. Cost: median 669 output tokens and 11.6 s per re-check,
  on 76 % of the affairs; 2 of 340 answers had no parseable JSON (parser hardened since).
- **Retrieved few-shot examples do not help (E1.5, rejected):** 6 fixed, 7 broken, +17 % input
  tokens. The BM25 neighbours are lexically, not topically similar.
- **Counting side aspects helps (E1.6, adopted as topic v3):** 6 fixed, 1 broken, precision
  unchanged, no new false positives.

Cost reference: E1.2 needs 815 input and 86 output tokens per affair. At the Public AI list price for
Apertus 70B (USD 0.82 / 2.92 per million tokens) that is about USD 0.92 per 1,000 affairs, i.e.
~USD 300 for all 325,000 affairs and one topic without a pre-filter. Throughput: 450 affairs in
168 s with 8 parallel requests (p50 latency 2.9 s).

### E1.7 — final configuration (dev)

| Run | P | R | F1 | F1 lang=de | F1 lang=fr | F1 lang=it | F1 level=federal | F1 level=cantonal | tokens in/out per affair |
|---|---|---|---|---|---|---|---|---|---|
| E1.6 70B, topic v3 | 0.955 | 0.700 | **0.808** | 0.847 | 0.766 | 0.720 | 0.733 | 0.859 | 849 / 84 |
| **E1.7 70B v3 + thinking for `not_assigned`** | 0.909 | 0.800 | **0.851** | 0.852 | 0.889 | 0.814 | 0.810 | 0.883 | 1,462 / 658 |

8 of 338 re-checks returned no parseable answer (reasoning ran into the 4,000-token limit); these
keep the fast-pass label, so a failed re-check can never add a false positive.

**Predeclared before the single test run (2026-10-18, ~13:30):** the test split (1,200 affairs,
2024–2026) is run once with B0, E1.6 and E1.7, nothing is tuned afterwards. Expected: E1.7 beats B0
by ≥ 0.15 F1 and E1.6 by ≥ 0.02 F1; per-language F1 of FR and IT within 0.10 of DE.
