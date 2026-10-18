# Technical Report — ParlTopic: Topic Classification for Swiss Parliaments with Apertus

- **Challenge:** 2 — OpenParlData: Topic classification for Swiss parliaments with Apertus
- **Event:** Hack Apertus Liebefeld, 18–19 October 2026
- **Team:** Token Tell — Felipe Wüthrich, Josip Jukic
- **Repository:** [GitHub](https://github.com/Felipe3052/hackapertus-openparldata) · **Experiment log:** [docs/experiments.md](docs/experiments.md) · **Benchmark notes:** [docs/benchmark.md](docs/benchmark.md)
- **Demo:** video link to add · Streamlit app (`make web`) · API (`make api`) · CLI (`parltopic classify`)

---

## 1. Summary

OpenParlData.ch holds more than 300,000 affairs from 90 Swiss parliaments in German, French,
Italian and some Romansh, but they can only be searched by full text. A question such as *"What
did Swiss parliaments decide on digitalisation?"* means guessing the wording in every language.
ParlTopic is an open classification service on **Apertus v1.5 70B**: a user defines a topic in a
short YAML file (name, description, terms, examples), and the service decides for each affair
whether it belongs to that topic, citing the passage that justifies the decision. New topics need
no training.

We validated it on the challenge's real use case: Digital Administration Switzerland (DVS)
identifies digitalisation affairs by hand, based on the PolitMonitor editorial tag (3,433 tagged
affairs from 35 parliaments). On the 1,200 affairs of 2024–2026 (one third tagged), **Apertus finds
88 % of the tagged affairs at 88 % precision (F1 0.876); keyword search over the same
multilingual terms finds 55 % (F1 0.674)**. F1 is 0.90 in German and 0.85 in French and
Italian, and 27 of the 30 affairs on the current DVS list are found. Three further topics written
once from their name only (migration, health, transport) reach F1 0.78–0.87 against the Federal
Assembly's official subject areas, where keyword search reaches 0.55–0.72. Because only 2.3 % of
all affairs are digitalisation affairs, about one in four suggestions over the full corpus is
PolitMonitor-tagged; keyword search has the same ratio at 63 % of our recall. ParlTopic is
therefore a suggestion list for the editors, not an automatic label.

Three findings shaped the system. **The topic definition is the cheapest lever:** an explicit
inclusion rule ("side aspects count, a precise title is enough") raised dev F1 from 0.72 to 0.81
without extra cost. **Apertus' own score is not a confidence:** 46 of 64 missed positives had a
score ≤ 0.1, so we route by a deterministic multilingual term rule instead of a score threshold
(78 of 450 affairs need no model call). **Two people agree on an Année Politique Suisse chapter
only 55 % of the time** (κ 0.51, 20 affairs), so a fixed scheme is hard even for humans; user-defined
topics are the stronger offer.

---

## 2. Architecture

```
 OpenParlData export / API (affairs, bodies, federal texts, documents)
        │
        ▼
 Normalise → Affair (title, text, language, parliament, level, documents)
        │      segments with provenance: title · affair text · document (ID + link)
        ▼
 Multilingual term rule ── a configured term occurs ──► assigned, cites that segment (no LLM call)
        │ no match
        ▼
 BM25 → top-5 passages ──► Apertus v1.5 70B (CSCS), prompt v2, JSON
        │                   {status, score, explanation, evidence_ids}
        ▼
 Validation: strict schema, only known passage IDs, 'failed' kept apart from 'not_assigned'
        │
        ▼
 Result: status · explanation · original evidence text and link · model · prompt · tokens · latency
        │
   CLI (JSONL) · FastAPI · Streamlit
```

1. **Ingestion.** `parltopic download-data` fetches the bulk exports (`affairs.ndjson.gz`, 326,396
   affairs; `bodies.ndjson.gz`) and the hackathon label files. Federal affairs get their submitted
   text and reasoning in the chosen language; the Federal Council's answer is left out so the
   executive's framing does not decide the topic. `parltopic enrich-documents` attaches the
   extracted text of an affair's documents from `/v1/affairs/{id}/docs` (cached).
2. **Segmentation.** Title, affair text and each document become separate segments with stable
   IDs, so evidence always points to its source field and document.
3. **Term rule.** If the topic name or a configured term occurs (prefix match for words such as
   *digital/digitale/digitalizzazione*, whole-token match for acronyms such as *NFT*), the affair is
   assigned with that segment as evidence. Terms inside attached documents can be excluded.
4. **Apertus.** All other affairs go to Apertus with the topic definition, in- and out-of-scope
   examples and the five passages that BM25 ranks highest against the topic's terms.
5. **Validation.** The answer must match a strict schema; `assigned` and `uncertain` must cite at
   least one passage; unknown passage IDs are rejected. Technical errors become `failed`, never
   a negative label. `uncertain` and `not_evaluable` are flagged for review.
6. **Topic policy.** Each topic file can set its prompt version and switch the term rule off.
   Curated topics with vetted terms (digitalisation) use the rule and prompt v2; topics written in
   a minute use the generic prompt v1 without the rule (5.3).
7. **Optional stages,** measured and off by default: a second look with Apertus reasoning for
   rejected affairs (`parltopic rethink`), retrieved few-shot examples, title-only rules.

---

## 3. Use of Apertus

- **Model:** `swiss-ai/Apertus-v1.5-70B`, temperature 0, on the CSCS inference endpoint
  (OpenAI-compatible, `response_format: json_object`), retries with exponential backoff. The
  model is set by `LLM_NAME`; nothing else is hard-wired.
- **Role:** Apertus is the semantic classifier and writes the explanation; it chooses the
  evidence passages by ID, so every cited text is original source text. It also translated the
  French and Italian cantonal titles into German for our human labelling page. No other model is
  used for classification or evaluation; no proprietary model is called at runtime.
- **8B vs. 70B (dev, same prompt):** 8B reaches F1 0.43 (recall 0.28) against 0.80 for 70B. It
  rejects most affairs whose digital aspect is not in the title, and in 169 of 450 answers it
  returned malformed evidence lists. 70B is the only viable size for this task.
- **Determinism:** two identical 70B runs change 0 of 450 labels, so paired differences measure
  the change, not noise.
- **Scores are not confidences:** 46 of the 64 missed positives of the first run had a score ≤ 0.1
  and only 16 of 450 answers lay between 0.1 and 0.9. A "send low-confidence cases to a second
  model" cascade cannot find these errors.
- **Reasoning:** Apertus only reasons before answering when the assistant turn is prefilled with
  `<|inner_prefix|>`; the answer follows `<|inner_suffix|>`. Re-checking rejected affairs this
  way raised dev F1 from 0.797 to 0.866 with the first prompt, but adds nothing once prompt v2 and
  the term rule are in place (macro-F1 −0.0015, 95 % CI [−0.015, +0.012]) at 3× the input tokens.
  It stays optional.

---

## 4. Data and evaluation protocol

- **Sources:** OpenParlData bulk exports and the hackathon label directory, snapshot of
  18 October 2026, CC BY 4.0.
- **E1 digitalisation (main benchmark):** PolitMonitor-tagged affairs are positives. Negatives are
  untagged affairs of the same parliaments, period and affair types, sampled per parliament in
  proportion to its positives so the parliament alone does not reveal the label. **Dev:**
  2018–2023, 150 + 300 affairs, used for all design decisions. **Test:** 2024–2026, 400 + 800
  affairs (DE 670, FR 325, IT 205; federal 585, cantonal 609, municipal 6). Federal affairs are
  assigned one of DE/FR/IT at random, so the official translations measure each language on
  comparable content. Seed 42; `parltopic build-eval` reproduces the files byte for byte.
- **Label caveat:** untagged affairs are positive-unlabelled proxies. Our error analysis found
  digitalisation affairs among the "false positives" (e.g. *Digital Services Act per la Svizzera*,
  the SIPAC IT system, the telecom surveillance ordinance), so precision is a lower bound.
- **Protocol:** prompts and topic definitions were tuned on dev only. The test split was first
  run once with predeclared expectations; since then it counts as opened validation, and the
  frozen configuration was run on it once more with expectations declared beforehand
  ([docs/experiments.md](docs/experiments.md)). Paired comparisons use a 10,000-sample bootstrap.
- **Further checks:** E2 — 500 federal affairs with the Federal Assembly's subject areas, used as
  ground truth for three ad-hoc topics; E3 — 20 affairs labelled blind by both team members with
  APS chapter and topic; E4 — the 30 affairs on the DVS list on 18 October 2026.

---

## 5. Results

### 5.1 Digitalisation, test split (1,200 affairs, 2024–2026)

| Configuration | Precision | Recall | F1 | Macro-F1 | F1 DE / FR / IT | Tokens in / out per affair |
|---|---:|---:|---:|---:|---|---:|
| Keyword search, same multilingual terms | 0.870 | 0.550 | 0.674 | 0.776 | 0.64 / 0.68 / 0.76 | 0 / 0 |
| Apertus 70B, topic v3, first prompt | 0.908 | 0.797 | 0.849 | 0.890 | 0.86 / 0.82 / 0.86 | 855 / 87 |
| … + reasoning re-check of rejections | 0.859 | 0.885 | 0.872 | 0.904 | 0.88 / 0.87 / 0.85 | 1,434 / 635 |
| **Frozen: term rule + Apertus 70B, prompt v2, topic v4** | **0.875** | **0.877** | **0.876** | **0.907** | 0.90 / 0.85 / 0.85 | 1,102 / 80 |

By level (frozen configuration): federal F1 0.854, cantonal 0.898. Municipal affairs are too
few to report (6). 30 affairs on the DVS list: 27 found (keyword search: 19). The frozen run met
two of its three predeclared expectations (F1 ≥ 0.84, DVS ≥ 27); the language spread of 0.051
narrowly misses the 0.05 bar. 6 of 1,200 affairs have no decision (4 failed calls, 2 without text).

**Precision at the real base rate.** The sample is one third positive; in the corpus 2.3 % of the
eligible affairs are tagged. Re-weighting the false-positive rate to that base rate gives the share
of suggestions that PolitMonitor tagged:

| Configuration | Recall | Precision at 2.3 % base rate |
|---|---:|---:|
| Keyword search | 0.55 | 0.24 |
| Apertus, topic v3, first prompt | 0.80 | 0.32 |
| Apertus + reasoning re-check | 0.89 | 0.22 |
| **Frozen** | **0.88** | **0.25** |

All variants, keyword search included, return about three untagged affairs per tagged one;
ParlTopic keeps that ratio at 1.6 times the recall. Part of the untagged suggestions are label gaps
(4.1), so the true share is higher, but the editors still have to review the list.

### 5.2 How we got there (dev split, 450 affairs)

| Step | P | R | F1 |
|---|---:|---:|---:|
| Keyword search | 0.936 | 0.487 | 0.640 |
| Apertus 70B, topic definition v1 | 0.966 | 0.573 | 0.720 |
| + inclusion rule in the definition (v2) | 0.952 | 0.685 | 0.797 |
| + side aspects count (v3) | 0.955 | 0.709 | 0.814 |
| + term rule and prompt v2 (hybrid-v3, main) | 0.932 | 0.820 | 0.872 |
| **+ topic v4 (frozen)** | **0.933** | **0.839** | **0.883** |
| Rejected: 8B instead of 70B | 0.951 | 0.275 | 0.426 |
| Rejected: 3 + 3 retrieved labelled examples | 0.952 | 0.673 | 0.789 |
| Not significant: document text for title-only affairs | 0.914 | 0.859 | 0.886 |
| Not significant: reasoning re-check on the frozen configuration | 0.908 | 0.859 | 0.883 |

The frozen configuration's dev macro-F1 is 0.915; the documents and reasoning variants differ by
+0.0009 and −0.0015 with 95 % intervals spanning zero. A title-only TF-IDF classifier trained on
2018–2021 reaches macro-F1 0.82–0.86, below Apertus (Part B of the experiment log).

### 5.3 Ad-hoc topics beyond digitalisation

Each topic was written once from its name (a two-line description and about 15 DE/FR/IT terms,
`configs/topics/adhoc/`) and scored against the Federal Assembly's subject area on 500 federal
affairs from 2024–2026.

| Topic | Positives | Keyword search | Frozen digitalisation policy | Same, term rule off | **Generic prompt v1, no term rule (final)** |
|---|---:|---:|---:|---:|---:|
| Migration | 63 | 0.717 | 0.762 | 0.757 | **0.874** |
| Health | 83 | 0.571 | 0.656 | 0.667 | **0.805** |
| Transport | 55 | 0.545 | 0.642 | 0.690 | **0.784** |

The policy tuned for digitalisation does not transfer. Prompt v2 names digital anchors
(software, ERP, online platforms) and makes Apertus strict on other topics (precision 0.94–1.00,
recall 0.52–0.62), and quickly chosen terms such as *Spital* or *Strasse* make the term rule fire
on unrelated affairs (health precision 0.61). Each topic file therefore sets its own policy
(`prompt_version`, `keyword_rule`): curated topics with vetted terms use the term rule and prompt
v2, topics written in a minute use the generic prompt without the rule. This was found after the
predeclared run (which expected F1 ≥ 0.80 and missed it with the frozen policy) and is reported as
a diagnosis, not a tuned result. Coverage is 97–98 %: in 34 of 1,500 answers the generic prompt cited the
affair ID instead of a passage ID, which the validator rejects rather than invent evidence.

### 5.4 Bias and neutrality

Frozen configuration, test split, decided affairs:

| Slice | Tagged affairs | Precision | Recall |
|---|---:|---:|---:|
| German / French / Italian (F1) | 670 / 325 / 205 affairs | | F1 0.90 / 0.85 / 0.85 |
| Federal Assembly | 195 | 0.84 | 0.87 |
| Bern / Zurich / Geneva / Valais / Basel-Stadt | 25 / 24 / 16 / 15 / 13 | 0.88 / 0.92 / 0.82 / 0.93 / 1.00 | 0.88 / 0.96 / 0.88 / 0.87 / 0.85 |
| Title and text / title only | 256 / 142 | 0.86 / 0.91 | 0.88 / 0.87 |
| Federal Council bills | 40 | 0.94 | 0.75 |

Title-only affairs, mostly cantonal, are now recalled as well as affairs with text; with the first
prompt they lost 13 recall points (0.78 vs. 0.91, Bern 0.73, Basel-Stadt 0.62). The term rule finds
German affairs slightly more often. Federal Council bills, with long legal titles where
digitalisation is one aspect among many, are recalled least. Author and party are not in the
affairs export; a party check is open. The prompt instructs Apertus to
classify subject matter only and never judge a position.

### 5.5 Standard topics: how hard is APS?

Both team members labelled 20 affairs (12 federal, 8 cantonal) blind with an APS chapter and topic,
reading French and Italian affairs in German. They agree on 11 of 20 chapters (55 %, κ 0.51) and
9 of 20 topics; most disagreements are multi-aspect affairs (*no transfer of tax data without
anonymisation*: data protection or taxes). A model scored against one human label would therefore
look worse than it is; standard topics should be multi-label and judged against this human
ceiling. The APS scheme (8 domains, 22 chapters, 165 topics) is exported to
`configs/taxonomies/aps_topics.json`.

### 5.6 Cost and runtime

The frozen configuration needs 1,102 / 80 tokens per affair on average; the term rule decides
21 % of the test affairs without a model call. Measured throughput on the shared CSCS endpoint
varied with load: the 1,200 test affairs took 379 s with 8 parallel requests at midday (about
150 answered requests per minute); a 500-affair probe with 16 parallel requests and no client
limit reached 64 per minute in the late afternoon (p95 latency 71 s) without a single rate-limit
error. Classifying every one of 325,000 affairs for one topic therefore takes about 28–67 hours
on one key; the client's default limit of 30 requests per minute (`LLM_REQUESTS_PER_MINUTE`,
an unverified quota assumption, see `docs/performance.md`) would stretch this to about 140 hours
and can be raised or disabled. At the Public AI list price for Apertus 70B (USD 0.82 / 2.92 per
million input / output tokens) one topic over the full corpus costs about USD 370; on CSCS or a
Swiss provider the price depends on the contract. Reading every affair for every new topic does
not scale; sending only candidate affairs to Apertus is the next step.

### 5.7 Can a compiled query replace reading every affair? (negative result)

Idea: Apertus reads the topic once and writes search terms per language (`parltopic
compile-topic`: 18–26 s, about 1,900 tokens, 40–56 terms per language; editable JSON); a cheap
search returns candidates, and Apertus verifies only those (`parltopic find`). Measured on the
full population behind E1, not on the balanced sample: every affair of the 35 PolitMonitor
parliaments and the same affair types.

| Period | Affairs | Tagged | Pre-filter | Candidates (share) | Tagged among candidates |
|---|---:|---:|---|---:|---:|
| 2018–2023 (dev) | 72,741 | 2,487 | local, word-prefix, terms v1 | 4,703 (6.5 %) | 61.0 % |
| 2018–2023 (dev) | 72,741 | 2,487 | local, word-prefix, terms v2 (stems) | 2,932 (4.0 %) | 59.5 % |
| 2024–2026 (test) | 37,258 | 853 | OpenParlData search, titles | 6,073 (16.3 %) | 59.1 % |
| 2024–2026 (test) | 37,258 | 853 | local, word-prefix, terms v1 | 2,982 (8.0 %) | 67.6 % |

On the test sample, the frozen classifier restricted to the local candidates reaches F1
0.749 (precision 0.873, recall 0.656) against 0.876 when every affair is read. We set the bar
before measuring (≥ 85 % of the tagged affairs among the candidates) and stopped: about 40 % of
the tagged affairs contain no predictable search term ("Nevo/Rialto – Wie weiter?", "Handyfreie
Schulen?!", smart glasses, robotaxis, a pension affair with a digital side aspect). High recall
needs Apertus to read every affair, which is what the main configuration does. The compiler is
still useful as a fast first pass — 60–68 % of the hits sit in 4–8 % of the affairs and arrive
in minutes, the complete pass follows — and its terms are a readable, editable description of a
topic. OpenParlData's own search would serve it if it supported prefixes (`digital:*` returns
nothing, so compounds such as "Digitalisierungsstrategie" are missed) and date filters
(`date_from`/`date_to` are ignored; deep offsets take about 60 s per page).

---

## 6. Limitations

- **Labels:** PolitMonitor tags are positives only; precision against them is a lower bound. One
  topic is evaluated in depth; three more against official subject areas.
- **Test split:** opened validation, not a sealed holdout; a later, manually adjudicated holdout is
  needed for an independent quality claim.
- **Coverage:** municipal affairs are too few in the labels (6 in the test split); Romansh is
  supported by the schema but not evaluated.
- **Title-only affairs** are recalled worse; document text did not help significantly yet because
  long reports bring incidental mentions.
- **Standard topics:** the APS scheme is available, but a multi-label APS mode is not evaluated.
- **Full-corpus runtime:** high recall needs every affair read (28–67 h per topic over 325,000
  affairs on one key); a lexical pre-filter keeps only about 60 % of the hits (5.7).
- **Party bias** is not checked yet.
- **Topic policy:** the term rule and prompt v2 suit curated topics only; quickly written topics
  need the generic prompt (5.3), which in 2 % of answers cites an affair ID instead of a passage.

---

## 7. Reproducibility

```bash
python -m pip install -e '.[dev]'          # Python 3.11+; copy .env.example to .env, add LLM_API_KEY
make test                                  # unit tests, no API calls
parltopic fetch-results && parltopic claims # recompute every number in this report, no API calls
parltopic download-data                    # exports and label files to data/raw (~350 MB)
parltopic build-eval                       # rebuilds data/eval byte for byte (seed 42)
parltopic baseline --eval-set data/eval/e1_digitalisation_test.jsonl --topic configs/topics/digitalisation.yaml
parltopic run-eval --eval-set data/eval/e1_digitalisation_test.jsonl \
  --topic configs/topics/digitalisation.yaml --output results/test.jsonl --workers 8
parltopic compare-runs --eval-set … --baseline-results … --candidate-results …   # paired bootstrap
```

Every `run-eval` output has a manifest with the dataset hash, topic, system prompt, settings and
source-file hashes; resuming with changed inputs is refused. All settings are in `.env.example`.

---

## 8. Next steps

1. A semantic pre-filter (multilingual embeddings, e.g. bge-m3 hosted in Switzerland) measured
   against the 85 % recall bar that the lexical one missed; nightly runs only for new affairs.
2. Feed reviewer decisions (the demo stores confirm / reject; `affair_topics.review_decision`)
   back as labels and as in-scope / out-of-scope examples of the topic.
3. Multi-label APS chapters, evaluated against the human agreement in 5.5.
4. Party bias check; a sealed, adjudicated holdout including municipal affairs.

**License:** code Apache-2.0 ([LICENSE](LICENSE)); report and documentation CC BY 4.0. Data: OpenParlData.ch, CC BY 4.0.
