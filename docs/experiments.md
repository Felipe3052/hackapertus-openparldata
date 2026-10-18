# Experiment log

Two parts, one per line of work. Part A covers the eval sets, the ablations on the digitalisation topic, the frozen configuration and the checks across languages, levels, parliaments and topics. Part B covers the classifier-quality experiments run in isolation against `main` (title anchors, online spelling variants, document enrichment, supervised baseline, confirmation panel).

# Part A — evaluation and ablations

All runs use the frozen eval sets in `data/eval/` (seed 42, built by `parltopic build-eval`) and the
CSCS endpoint. Prompts and topic definitions are tuned on the **dev split only**; the test split is
run once per final configuration. Tables come from `parltopic compare`; raw results are in
`results/` (not committed).

## A · Eval sets

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

## A · E1 — digitalisation (dev, 450 affairs)

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

### E1.8 — document excerpt for title-only affairs (dev)

*Superseded:* this first implementation (`enrich-docs`, one best-matching document, first
1,500 characters) was removed after the merge in favour of `enrich-documents` (Part B), which
attaches all usable documents and gates the keyword rule inside them. Both lines reach the same
conclusion under the hybrid classifier (A · M and B · document enrichment): documents do not
significantly change the metrics.

Cantonal parliaments publish the content of an affair in attached documents. `parltopic
enrich-docs` fetches `/v1/affairs/{id}/docs` (extracted text, cached), keeps the document whose
opening shares most words with the title and uses its first 1,500 characters as the affair text.
Dev: 163 title-only affairs, 156 filled, 6.5 s for all API calls. Only those 156 are re-classified;
all other answers are reused, so the comparison is paired.

| Run | P | R | F1 | F1 lang=de | F1 lang=fr | F1 lang=it | F1 level=federal | F1 level=cantonal | tokens in/out per affair |
|---|---|---|---|---|---|---|---|---|---|
| E1.6 70B v3 | 0.955 | 0.700 | **0.808** | 0.847 | 0.766 | 0.720 | 0.733 | 0.859 | 849 / 84 |
| E1.8a 70B v3 + documents | 0.950 | 0.753 | **0.840** | 0.876 | 0.840 | 0.720 | 0.733 | 0.909 | 1,013 / 86 |
| E1.7 70B v3 + thinking | 0.909 | 0.800 | **0.851** | 0.852 | 0.889 | 0.814 | 0.810 | 0.883 | 1,462 / 658 |
| **E1.8b 70B v3 + documents + thinking** | 0.906 | 0.840 | **0.872** | 0.880 | 0.909 | 0.814 | 0.810 | 0.918 | 1,729 / 670 |

The document excerpt raises cantonal F1 by 0.035–0.05 at the same precision, for ~165 more input
tokens per affair. The excerpts often name authors and parties ("Postulat von … (FDP, Meilen)"),
which also makes a party bias check possible. Not yet run on the test split.

### E1.7 — final configuration (dev)

| Run | P | R | F1 | F1 lang=de | F1 lang=fr | F1 lang=it | F1 level=federal | F1 level=cantonal | tokens in/out per affair |
|---|---|---|---|---|---|---|---|---|---|
| E1.6 70B, topic v3 | 0.955 | 0.700 | **0.808** | 0.847 | 0.766 | 0.720 | 0.733 | 0.859 | 849 / 84 |
| **E1.7 70B v3 + thinking for `not_assigned`** | 0.909 | 0.800 | **0.851** | 0.852 | 0.889 | 0.814 | 0.810 | 0.883 | 1,462 / 658 |

8 of 338 re-checks returned no parseable answer (reasoning ran into the 4,000-token limit); these
keep the fast-pass label, so a failed re-check can never add a false positive.

## A · M — after merging main (hybrid-v3 classifier, prompt v2) — frozen configuration

Same 450 dev affairs, merged code (`4d3372e`), Apertus v1.5 70B, topic v4 (side-aspect rule +
main's scope examples and online/NFT terms). Paired bootstrap with 10,000 samples (`compare-runs`).

| Run | P | R | F1 | Macro-F1 | F1 de / fr / it | tokens in/out per affair |
|---|---|---|---|---|---|---|
| main hybrid-v3 with its own topic v3 (Josip, `docs/benchmark.md`) | 0.932 | 0.820 | 0.872 | 0.907 | | |
| **M-A hybrid-v3 + topic v4 (frozen)** | 0.933 | 0.839 | **0.883** | **0.915** | 0.882 / 0.889 / 0.881 | 1,153 / 83 |
| M-B M-A + document excerpt for title-only affairs | 0.914 | 0.859 | 0.886 | 0.916 | 0.880 / 0.909 / 0.881 | 1,245 / 86 |
| M-C M-A + thinking for `not_assigned` | 0.908 | 0.859 | 0.883 | 0.913 | 0.884 / 0.893 / 0.871 | 2,108 / 703 |

- M-B vs. M-A: macro-F1 +0.0009, 95 % interval [−0.013, +0.016]. M-C vs. M-A: −0.0015,
  [−0.015, +0.012]. Neither documents nor thinking improve the merged classifier; the keyword
  rule and prompt v2 already recover the recall that thinking bought before (E1.4). Thinking
  would triple input and multiply output tokens by 8.
- **Decision: freeze M-A.** Documents and thinking stay optional switches; documents remain
  useful as evidence for title-only affairs. No further prompt or rule tuning on this dev split.
- 78 of 450 affairs are assigned by the keyword rule without a model call.

### M-A on the test split, DVS list and ad-hoc topics — predeclared

Run once on 2026-10-18 (~16:30) with the frozen M-A configuration, nothing tuned afterwards. The
test split is opened validation (B · protocol), not a sealed holdout. Expected: test F1 ≥ 0.84
(the pre-merge fast pass E1.6), per-language F1 within 0.05 of each other, DVS ≥ 27 of 30, each
ad-hoc topic F1 ≥ 0.80.

### M-A on the test split, DVS list and ad-hoc topics — results

| Set | P | R | F1 | Notes |
|---|---:|---:|---:|---|
| E1 test (1,200) | 0.875 | 0.877 | **0.876** | macro-F1 0.907; F1 DE 0.897 / FR 0.849 / IT 0.846; federal 0.854, cantonal 0.898; 1,102 / 80 tokens per affair; 253 of 1,200 decided by the term rule; 379 s wall clock with 8 workers |
| E4 DVS list (30) | | | | 27 assigned, 1 uncertain, 2 not assigned |
| E2 migration | 0.762 | 0.762 | 0.762 | frozen digitalisation policy |
| E2 health | 0.608 | 0.711 | 0.656 | frozen digitalisation policy |
| E2 transport | 0.667 | 0.618 | 0.642 | frozen digitalisation policy |

Against the predeclared expectations: test F1 ≥ 0.84 met; DVS ≥ 27 met; language spread 0.051
narrowly misses 0.05; ad-hoc F1 ≥ 0.80 **missed** for all three topics.

Precision at the test-period base rate (2.29 %): keyword search 0.24 (recall 0.55), E1.6 0.32
(0.80), E1.7 0.22 (0.89), M-A 0.25 (0.88).

**Post-hoc diagnosis of the ad-hoc drop (not tuning):** with the term rule off and prompt v2 the
three topics reach P 0.975 / 0.935 / 1.00 but R 0.62 / 0.52 / 0.53 (F1 0.757 / 0.667 / 0.690).
Prompt v2 names digital anchors and makes Apertus strict on other topics; quickly chosen terms
(*Spital*, *Strasse*) make the term rule fire on unrelated affairs. Topic files now carry their own
policy (`prompt_version`, `keyword_rule`); the ad-hoc topics use `topic-v1` without the rule:

| Topic | P | R | F1 | Coverage |
|---|---:|---:|---:|---:|
| Migration | 0.929 | 0.825 | **0.874** | 489 / 500 |
| Health | 0.849 | 0.765 | **0.805** | 487 / 500 |
| Transport | 0.905 | 0.691 | **0.784** | 490 / 500 |

The 34 failed answers cite the affair ID instead of a passage ID; the validator rejects them.

## A · E3 — human agreement on APS topics (20 affairs, blind)

Felipe and Josip labelled the first 20 affairs of `data/eval/e3_aps_sample.jsonl` independently
(main topic, optional second topic, or "not classifiable"; FR/IT shown in German: official federal
version or Apertus translation). Labels: `data/eval/e3_aps_labels.jsonl`.

| Level | Agreement | Cohen's κ |
|---|---:|---:|
| APS chapter (22) | 11 / 20 = 55 % | 0.51 |
| APS topic (165), main topic | 9 / 20 = 45 % | |
| APS topic, main or second topic overlaps | 8 / 20 + 1 both "not classifiable" | |

- **Two people agree on the APS chapter only about half the time**, far below the ~80 % the
  parliamentary services report for their own scheme. n = 20 is small (±11 points), but the pattern
  is clear: 4 of the 11 topic disagreements stay within one chapter (army basics vs. army
  organisation, land law vs. housing), the others are multi-aspect affairs (*no transfer of tax data
  without anonymisation*: data protection vs. taxes; *SBB procurement abroad*: competition vs.
  labour market).
- Consequences for the APS evaluation: score the model **multi-label and at chapter level first**,
  and report it next to this human ceiling rather than against a single "gold" label. It also
  supports presenting topics as suggestions a person confirms.

## A · E1 — test split (1,200 affairs, 2024–2026, run once)

| Run | P | R | F1 | F1 lang=de | F1 lang=fr | F1 lang=it | F1 level=federal | F1 level=cantonal | tokens in/out per affair |
|---|---|---|---|---|---|---|---|---|---|
| B0 keyword search (DE/FR/IT synonyms) | 0.864 | 0.510 | **0.642** | 0.595 | 0.677 | 0.719 | 0.690 | 0.581 | 0 / 0 |
| E1.6 70B, topic v3 | 0.908 | 0.785 | **0.842** | 0.850 | 0.817 | 0.857 | 0.848 | 0.836 | 855 / 87 |
| **E1.7 70B v3 + thinking for `not_assigned`** | 0.859 | 0.868 | **0.863** | 0.868 | 0.861 | 0.851 | 0.856 | 0.871 | 1,434 / 635 |

All three predeclared expectations hold: E1.7 beats B0 by +0.221 F1 (bar ≥ 0.15) and E1.6 by
+0.021 (bar ≥ 0.02, met narrowly); FR (0.861) and IT (0.851) are within 0.02 of DE (0.868).

- **Apertus finds 87 % of the editorially tagged affairs; keyword search finds 51 %.** The gap is
  largest on cantonal affairs (F1 0.581 → 0.871), which usually have only a title.
- The fast pass alone is already strong on the test split (0.842, vs. 0.808 on dev); thinking adds
  less here than on dev (+0.021 vs. +0.043) and trades precision for recall (P 0.908 → 0.859,
  R 0.785 → 0.868). For DVS, whose editors review the list anyway, recall is the scarcer quantity.
- Thinking re-checked 846 rejections (p50 11.6 s): 58 flipped to `assigned`, 33 of them tagged by
  PolitMonitor. Of the other 25, at least 8 have a clear digital aspect in our reading (propaganda
  on the Swisscom network, websites run from Switzerland, driverless vehicles, the agricultural
  data system, police data collection, the RUAG ransom payment, the telecom-surveillance ordinance
  VÜPF, the SIPAC IT system), so the reported precision is a lower bound. 16 re-checks gave no
  parseable answer and kept the fast-pass label.
- 400 of 404 `assigned` results carry at least one evidence passage.
- Municipal affairs are too few to report (6 in the test split).

### Bias check (test split, E1.7, no extra API calls)

| Group | Positives | Precision | Recall |
|---|---:|---:|---:|
| Federal (CHE) | 195 | 0.81 | 0.90 |
| Bern (BE) | 26 | 0.90 | 0.73 |
| Zurich (ZH) | 24 | 0.88 | 0.96 |
| Geneva (GE) | 16 | 0.83 | 0.94 |
| Valais (VS) | 15 | 0.93 | 0.87 |
| Basel-Stadt (BS) | 13 | 1.00 | 0.62 |
| Title and text available | 256 | 0.84 | 0.91 |
| Title only | 144 | 0.91 | 0.78 |
| Government affairs (Federal Council bills) | 40 | 0.97 | 0.72 |

- No language gap (F1 DE 0.87, FR 0.86, IT 0.85). Parliaments differ mainly through how much text
  they publish: **title-only affairs lose 13 recall points**. The cantonal content sits in the PDF
  documents (`/v1/affairs/{id}/docs`), which this run does not use; adding their first page is the
  most promising next step for BE and BS.
- Federal Council bills are recalled least (0.72): long legal titles where digitalisation is one
  aspect among many.
- Author and party are not part of the affairs export, so a party bias check is still open.

### E4 — the 30 affairs on the current DVS list

Apertus (E1.7) finds 27 of 30, keyword search 19 of 30. The 3 misses have uninformative titles and
no text (*Wie weiter mit NFFS?*, *Wer trägt die Verantwortung für die «Sicherheitslücke»?*, a
cantonal structure-plan update on landfills).

**Predeclared before the single test run (2026-10-18, ~13:30):** the test split (1,200 affairs,
2024–2026) is run once with B0, E1.6 and E1.7, nothing is tuned afterwards. Expected: E1.7 beats B0
by ≥ 0.15 F1 and E1.6 by ≥ 0.02 F1; per-language F1 of FR and IT within 0.10 of DE.


# Part B — classifier-quality experiments against main

Status: this experiment round is concluded. E02 is the best primary-validation candidate and
remains explicitly selectable; main-compatible defaults and E01 are preserved. The secondary
panel found identical predictions, so independent superiority is not established. Inspectable
aggregate metrics, usage totals and artifact hashes are in [results/E02-summary.json](results/E02-summary.json).

All experiment changes stay on `experiment/classifier-quality`. The pinned main commit is
`1266c7ebfc1819c3c6c8d134699ebdfb138b204c`. No checkout, commit or merge changes main.

## B · Fixed evaluation and acceptance

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

## B · Iteration table

| Baseline | Experiment | Macro-F1 | Macro-Precision | Macro-Recall | Micro-F1 | Delta to main |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| main 1266c7e, Apertus 70B | Verified original main run | 0.9070 | 0.923 | 0.895 | 0.920 | 0 |
| same main, same 450 affairs | E01: title-only disinformation/automated-trading anchors | 0.9098 | 0.925 | 0.898 | 0.922 | +0.0028 |
| same main, same 450 affairs | E02: E01 + online spelling variants | 0.9125 | 0.927 | 0.902 | 0.924 | +0.0055 |

Main confusion matrix: TP=123, FP=9, FN=27, TN=291. E01: TP=124, FP=9, FN=26, TN=291.
The only changed decision is the French title “Importance du négoce à haute fréquence en Suisse”.
French macro-F1 moves from 0.881 to 0.896; German (0.920) and Italian (0.893) are unchanged.
Remaining proxy errors by language are DE: 15 FN / 4 FP; FR: 5 FN / 3 FP; IT: 6 FN / 2 FP.
Several missing positives have insufficient title-only inputs; broad document enrichment previously
reduced precision through incidental mentions. These are the largest observed failure sources.

The paired 5,000-sample bootstrap interval for delta is [0.0000, 0.0087]. This small, validation-
selected gain is not independently significant; no production or multi-topic quality claim follows.

## B · Baseline verification, runtime and costs

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

## B · Reproduce and use the optional candidate

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

## B · E02: opt-in online spelling normalization

Only the configured `online` keyword gains additional spellings: `on line`, `on-line` and
typographic dash variants, case-insensitively. Existing matches are preserved. Extra variants
require token boundaries so `on linear systems` and `on-linearity` do not match. Source text,
evidence quotations, retrieval query and Apertus prompts remain byte-for-byte unchanged.

The feature defaults off. E01 remains available with its original overlay; E02 uses
`configs/experiments/digitalisation-title-online-candidate.yaml` with
`normalize_online_variants: true`. Using that overlay via `--title-rules` records policy
`hybrid-title-online-v2` in live classification results.

E02 changes one additional decision beyond E01: the Italian package-travel consumer-protection
affair contains “prenotate on line”. Its existing positive tag is recovered without changing
any negative decision. Against main: TP=125, FP=9, FN=25, TN=291. German macro-F1 remains
0.920, French remains at E01's 0.896, Italian improves from main's 0.893 to 0.907. On the fixed
validation set all acceptance metrics improve. No final-test prediction or label was used.

Against main, the 5,000-sample paired bootstrap delta interval is [0.0000, 0.0140]. This is still
a small gain selected on the development set, not an independent generalization claim.

The controlled replay took 0.265 seconds excluding bootstrap and reused 369 validated model
decisions. It issued zero new API calls. Required/reused token counts fall to 501,537 input and
36,517 output; summed recorded request latency is 1,374.791 seconds. Those are reused baseline
measurements, not fresh live endpoint timings or concurrent wall-clock duration. Currency cost
of an equivalent live run still requires provider rates; this replay incurred no API cost.

```bash
python -m parltopic.evaluation.title_experiment \
  --eval-set data/eval/e1_digitalisation_dev.jsonl \
  --baseline results/hybrid_v3_actual_dev450.jsonl \
  --overlay configs/experiments/digitalisation-title-online-candidate.yaml \
  --experiment-id hybrid-title-online-v2 \
  --output results/title_online_variants_controlled_vs_main_dev450.jsonl
```

The earlier uncontrolled local trial is superseded by this explicit opt-in configuration and
is not an additional independent experiment. The E02 report and predictions live alongside the
preserved main/E01 artifacts under `results/`; choose a fresh output filename to rerun.

## B · Secondary validation and final selection

A deterministic 2023 panel was frozen before running any inference: 90 distinct affairs,
10 tagged positives and 20 untagged proxies per language (DE/FR/IT), seed 20261018. Dataset hash:
`e6b039bba4dcb7c00adae91fc8c836db02e2913acf6d4a144b15975b36da6f7c`.
All primary-validation IDs, supervised-baseline training/calibration IDs and their exact title
duplicates were excluded. Near-duplicates can remain. Some 2023 labels were previously used
only in a different model's aggregate validation report. This is secondary validation, not a
sealed or manually adjudicated final test; it is not used to tune further rules.

The baseline executed the actual `main` source from a temporary git archive, with package-path
verification and all seven source hashes recorded. No branch checkout or main modification
was performed. The fresh live baseline finished in 47.480 seconds with four workers and complete
90/90 coverage. E02 then reused 78 exact validated model requests, requiring no new API calls;
its replay took 0.104 seconds excluding bootstrap. Currency costs remain unknown without a tariff.

| Panel | Baseline | Experiment | Macro-F1 | Macro-Precision | Macro-Recall | Micro-F1 | Delta to main |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Secondary 90 | main 1266c7e | Original | 0.9222 | 0.942 | 0.908 | 0.933 | 0 |
| Secondary 90 | same main | Frozen E02 | 0.9222 | 0.942 | 0.908 | 0.933 | 0.0000 |

Both confusion matrices are TP=25, FP=1, FN=5, TN=59. No decision changed; the panel neither
shows a regression nor confirms the primary-panel improvement. E02 therefore remains optional
and its primary score is not presented as a general production-quality guarantee. No new rule
or prompt was selected from this secondary panel.

Reproduce the completed sequence with fresh output names:

```bash
python -m parltopic.evaluation.confirmation build \
  --dataset data/processed/confirmation/validation2023_90.jsonl
python -m parltopic.evaluation.confirmation run-main \
  --dataset data/processed/confirmation/validation2023_90.jsonl \
  --output results/confirmation2023_main90.jsonl
python -m parltopic.evaluation.title_experiment \
  --eval-set data/processed/confirmation/validation2023_90.jsonl \
  --baseline results/confirmation2023_main90.jsonl \
  --overlay configs/experiments/digitalisation-title-online-candidate.yaml \
  --experiment-id confirmation-hybrid-title-online-v2 \
  --output results/confirmation2023_E02_90.jsonl
```

Panel creation refuses to overwrite an existing file. Its metadata captures exclusions and input
hashes. Only the `run-main` step makes live inference requests. The API-free archive integration
test uses a clearly synthetic keyword-only case and does not contribute to any reported metric.
