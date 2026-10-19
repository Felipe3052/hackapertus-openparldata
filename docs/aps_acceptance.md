# APS-Experiment: Acceptance Matrix

Branch: `experiment/aps-context-pipeline`
Baseline: existing classifier with `APS_CONTEXT_ENABLED=false`

This matrix records what is proven on the current branch and what is still required before APS
can be promoted from an opt-in shadow/context component to a hard classifier.

| Requirement | Evidence | Status |
|---|---|---|
| Versioned APS hierarchy | 165 topics, 22 chapters, 8 domains; 195 loaded nodes | Proven |
| Hierarchy validation | Topic → chapter → domain parent checks and strict decision contract | Proven |
| DE/FR label coverage | `aps-coverage`: 165/165 topics in both languages | Proven |
| IT/RM coverage | `aps-coverage`: 0/165 topics until reviewed aliases are supplied | Explicitly missing; guarded |
| Parliament-level handling | Affairs retain federal/cantonal metadata; evaluation reports `language|level` groups | Proven structurally; quality evidence too small |
| Apertus integration | `APS_CONTEXT_ENABLED` is opt-in; result records policy, taxonomy and context sizes | Proven |
| Safe fallback | No text, no topic candidate or unsupported language retains full context | Proven by tests |
| Offline context reduction | E1: 152,141 → 112,450 whitespace tokens, 26.1 % reduction, no API calls | Proven for this dataset |
| Live latency/cost evidence | Six paired smoke calls across DE/FR/IT; not a general benchmark | Limited evidence |
| Existing classifier protection | Default disabled; regression gate and unchanged baseline path | Proven structurally |
| APS model quality | 9 unanimous labels only; 42.9 % recall, 11.1 % chapter precision, 5.8 % topic precision | Not sufficient |
| Independent APS gold standard | No larger adjudicated holdout exists in the repository | Required |

## Holdout preparation

On 2026-10-19, the existing 11,685-row `e1_fewshot_pool.jsonl` produced a 100-row blank
annotation template with seed 42. It contains 15 DE/cantonal, 15 DE/federal, 14 DE/municipal,
14 FR/cantonal, 14 FR/federal, 14 IT/cantonal and 14 IT/federal Affairs. The pool has no ID
overlap with E1 or E2; the existing E3 APS sample does overlap E1/E2 and is therefore not used as
an independent holdout. The reproducible command is documented in `docs/aps_experiment.md`.

## Current promotion decision

Do not enable APS as a hard filter or claim APS classification quality. It is suitable for a
shadow run and guarded context experiment. The low candidate precision means that an Apertus call
must remain responsible for the final semantic decision.

## Required next evidence

1. Export a larger source pool disjoint from E1/E2 and create a stratified DE/FR/IT,
   federal/cantonal annotation template.
2. Obtain two independent APS annotations and adjudicate disagreements.
3. Add reviewed, version-matched Italian aliases or an official Italian APS source; do not use
   generic Curia Vista labels as APS mappings.
4. Run `aps-evaluate` on the sealed consensus holdout and apply the existing regression gate to
   the final classifier outputs.
5. Repeat the latency/token comparison on the same holdout before changing the default flag.
