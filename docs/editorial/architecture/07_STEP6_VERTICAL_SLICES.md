# Step 6 · Vertical slices

*Implementation architecture, step 6 of 6 · 21 September 2026 · **ACCEPTED** with clarifications C-1, C-2 · architecture: Steps 0–5 with patches R1, R2, S3-R1, S4-R1, CANONICAL-SCOPE · migration model: Step 5 §3 (capability cutover C0–C8)*

This document cuts the implementation into **vertical, provable slices**. Each slice:

- delivers one working capability through the canonical engine;
- ends with evidence that it works;
- never breaks current production.

There is **no monolithic PR** for the sixteen stages.

**Out of scope:** GitHub issues and orchestrator tasks. They come next, from these slices. No implementation code.

---

## 0. Binding rules for every slice

### 0.1 Canonical-engine invariant (CE-1)

> **Neither weekday nor destination may define a separate Editorial Core pipeline.** Weekday, rubric and lens are configuration and scheduling inputs. Destination affects strategy, adaptation, validation and publication capability. All of them execute through the same canonical S-00 → S-15 topology.

How CE-1 is made checkable (built in SL-1, enforced in every later slice):

| Mechanism | What it proves |
|---|---|
| **One stage-topology registry**: the ordered S-00…S-15 graph with its scopes, barriers and backward routes, defined once | There is one engine |
| **Topology digest** in every RunManifest | The digest identifies the canonical **allowed** S-00 → S-15 topology (stages, scopes, barriers, permitted backward routes), **not the literal executed path**. Legitimate `SKIP`, `REPLAN`, counter exhaustion and backward routes produce different execution traces with the **same** digest (clarification C-1, GPT acceptance). A run whose digest differs from the registry's fails CI |
| **Placement rule**, checked in CI: editorial-core modules (S-00…S-13) do not read the weekday or clock for decisions, and do not choose stages by destination. Destination-specific behaviour lives only in destination knowledge (`K-DST-*`), adaptation (S-10), check records and publishers | Days and destinations cannot grow their own pipelines |
| **Clone check** (SL-13) | A second configuration runs with zero editorial code change |

### 0.2 Other rules

| Rule | Source |
|---|---|
| **Six destinations from the start.** Every slice that touches destinations covers Wix, LinkedIn, Facebook, Instagram, Threads and Telegram. The rollout scope may keep some `generate_only`; the code, tests and traces never assume two | Principle B |
| **No production impact until SL-11.** Slices before go-live run in shadow jobs with their own call budget, or behind a flag that is off in production | Step 5 §3 invariants |
| **No human in the run.** Acceptance reviews by the owner are **offline** (I-02); they never gate an individual run | I-01, I-02 |
| **Evidence of done** is a trace, a test or a measured report, never "it looks right" | Step 3 §4.4 |
| **Budget: measure before optimizing.** No slice may reduce destinations or merge architectural responsibilities to fit the current 40-call ceiling. Optimization is only SL-10, after the SL-7 baseline | GPT review; Step 2 §6 |
| **Each slice is mergeable on its own:** one or a few PRs, each behind a flag or in a shadow path, each reversible | Owner constraint |

---

## 1. Slice map

```
SL-0 Publication safety ──────────────────────────────────────────────┐
SL-1 Canonical skeleton (topology, trace, ledger, ARP, CE-1) ─┐       │
SL-2 Knowledge register v0 ───────────────────────────────────┤       │
                                                              ▼       │
SL-3 Evidence Core (S-00…S-03) → SL-4 Boundary (S-04, S-05)          │
   → SL-5 Planning ×6 (S-06…S-11) → SL-6 Writing + checks ×6 (S-12, S-13)
                                                              │       │
            ┌─────────────────────────────────────────────────┤       │
            ▼                                                 ▼       │
SL-7 Six-destination canonical shadow run + BUDGET BASELINE   SL-8a…d, SL-9 Destination
            │                                                 publication capability ×6
            ▼                                                 │       │
SL-10 Call-boundary optimization (optional, measured)         │       │
            └──────────────────────┬──────────────────────────┘       │
                                   ▼                                  │
                     SL-11 Canonical run live (single publisher) ◄────┘
                                   │
                     SL-12 Observation (S-15) for all six
                                   │
                     SL-13 Clone check (product check)
                                   │
                     SL-14 Removal of unreachable code
```

---

## 2. Slices

### SL-0 · Publication safety (C0)

| | |
|---|---|
| **Goal** | Make double publication impossible for whatever publishes, before any target code runs |
| **Builds** | Marker authority (Step 3 §3.6; Step 5 §1.1): intent before each destination's publish call; marker immediately after its success, committed in its own step, independent of job success; identity key (client, destination, signal set); `find_prior_*` re-pointed to markers; selection and dispatched signal IDs checked against markers; explicit 90-day retention on run uploads |
| **Proof** | Fault-injection tests with fake publishers: (a) destination 1 succeeds, destination 2 fails → the next run does not republish destination 1; (b) crash between intent and marker → the next run treats the key as possibly published and skips. Tests cover **all six** destination names. One real run's trace shows intent and marker files committed |
| **Production safety** | Additive to the current publishing path; it can only prevent a publication, never cause one |
| **Non-goals** | Any editorial change |
| **Depends on** | — |

### SL-1 · Canonical skeleton: topology, trace, ledger, ARP (C1)

| | |
|---|---|
| **Goal** | A walking skeleton of the one canonical engine: every stage S-00…S-15 exists as a typed pass-through, run end to end on a fixture signal with fake providers |
| **Builds** | Topology registry and digest (CE-1); workspace writer with create-once and write ownership; StageRecord trace; manifest-last completeness; RunSummary (public-safe) to the ledger; OutcomeRecord and PrecedenceLog plumbing; attempt counters and `RunCallBudget` exhaustion as ARP `SKIP` (Step 2 §0.3–0.4); boundary-commit writer semantics (Step 3 §2.4); destination loop over all six |
| **Proof** | (1) A fixture run produces a manifest that `verify_run_provenance` (extended) accepts. (2) Two runs with different configurations (e.g. two lens settings) have the **same topology digest**. (3) Forced exhaustion of each counter produces the specified `SKIP` in the trace. (4) The CE-1 placement rule runs in CI and fails on a planted weekday branch. (5) The six destination folders exist in the workspace |
| **Production safety** | Shadow only; no model calls; no publishing |
| **Non-goals** | Real stage logic |
| **Depends on** | — |

### SL-2 · Knowledge register v0 (C1)

| | |
|---|---|
| **Goal** | Knowledge reaches stages by the Step 4 rules, and hand edits cannot break a run |
| **Builds** | `knowledge/` files in the Step 4 format; validator in CI and at run start; loader with effective status and weak-candidate limits; eligibility × applicability selection; mandatory-knowledge containment and fail-closed; Knowledge Maintenance job (scheduled, offline). **Seed set:** default strength ladder; the V-P/V-T/V-S check records with Step 2 routes; the seven `K-TEMPT` probe families; at least one `K-DST` record **per destination for all six**; Never Blank client rules migrated into the client folder with front matter |
| **Proof** | A corpus of broken files is rejected, one per validator rule. A loader trace shows effective statuses and containment for a fixture stage. An expired candidate cannot exclude a strategy (unit test). An oversized mandatory set fails before the call |
| **Production safety** | Files and a job only; production does not read them yet |
| **Non-goals** | Full migration of all K-* records from the map (incremental, later) |
| **Depends on** | SL-1 |

### SL-3 · Evidence Core on real signals (S-00…S-03; C2)

| | |
|---|---|
| **Goal** | Real Evidence Cores with references, from real signals, in shadow |
| **Builds** | S-00 with source eligibility and contract fit rules; S-01 wrapping research plus the extended assessment (observation kind, figure, third-party flag, claim scope and strength) plus the **#58 relevance screen with a reconciled profile** (Step 5 §1.2); S-02 features, assets and MaterialNotes with the code reference check; S-03 enrichment loop with gaps and stop reasons |
| **Proof** | On a fixed set of real signals (reusing saved research artifacts where possible): every core is referentially valid; every positive feature has references; every enrichment stops with a recorded reason; relevance `revise`/`hold` routes to enrichment rather than stopping. Calls per stage are recorded |
| **Production safety** | Shadow job, own budget |
| **Non-goals** | Interpretations |
| **Depends on** | SL-1, SL-2 |

### SL-4 · Interpretation Boundary (S-04, S-05; C2)

| | |
|---|---|
| **Goal** | Admissible and probed inadmissible interpretations, committed as a versioned boundary |
| **Builds** | S-04 generate and probe calls (U-1); code rules (ceiling, transfer, references); boundary commit; re-entry path; S-05 with cap = 1, rules 1–2 and the `split_candidate` trace |
| **Proof** | The map walkthroughs as regression cases: uranium → `SKIP` "no admissible interpretation"; Ramp → "business has more money" recorded as inadmissible (benefit inflation); breakfast founder → "you, the reader, bake at night" recorded as inadmissible (transfer / invented scene). A simulated re-entry produces a coordinated E-08/E-09 commit |
| **Production safety** | Shadow |
| **Non-goals** | Anchor and strategies |
| **Depends on** | SL-3 |

### SL-5 · Planning for six destinations (S-06…S-11; C3)

| | |
|---|---|
| **Goal** | For one unit: an anchor, deterministic destination decisions, and an approved plan for **each of the six destinations** |
| **Builds** | S-06 anchor and leading-material set; S-07 deterministic, with capability × contract × rollout scope; S-08 candidates per destination (independent calls); S-09 selection with precedence and weak-candidate limits; S-10 adaptation using `K-DST-*` per destination, with the conditional link; S-11 plan checks, barrier B1 and exemplars |
| **Proof** | On the SL-3/SL-4 signal set: each non-skipped destination has an approved plan with a resolvable chain (I-04); V-P02 excludes over-promising candidates (the Ramp "3 things" case); V-P03 re-plans only the deviating destination; S-07 exclusions each cite a rule and tier; openings differ by destination while each uses the leading-material set as its evidentiary carrier (AD-01) |
| **Production safety** | Shadow |
| **Non-goals** | Prose |
| **Depends on** | SL-4, SL-2 |

### SL-6 · Writing and text checks for six destinations (S-12, S-13; C4)

| | |
|---|---|
| **Goal** | A text per approved plan, verified and routed by ownership |
| **Builds** | S-12 Writer from the approved plan only; S-13 truth and execution calls plus code checks; routes including the V-T01 and V-T08 branches with `fault_owner`; the boundary-drift re-check (F-4) |
| **Proof** | Accepted texts for all six destinations on the signal set. Planted-fault tests: a misquoted figure → S-12 edit; a load-bearing unsupported fact → S-08; an inadmissible interpretation → S-04 re-entry → S-08. No accepted text contains an interpretation listed as inadmissible (V-T02) |
| **Production safety** | Shadow |
| **Non-goals** | Publication |
| **Depends on** | SL-5 |

### SL-7 · Six-destination canonical shadow run and budget baseline (C4)

**The explicit baseline slice the review asked for.**

| | |
|---|---|
| **Goal** | Run the complete canonical chain S-00 → S-14 (no external publish call) for **all six destinations** on real signals, and measure what it really costs **before** any optimization |
| **Builds** | A scheduled shadow workflow for the canonical engine with its own ceiling, set high enough not to truncate the measurement; S-14 in shadow mode (packages where they exist, fingerprints, markers not written); a **baseline report** generated from the traces |
| **Baseline report contents** | Model calls and tokens **per stage and per destination**: minimum / median / maximum across runs. Counter usage (`L_enrich`, `L_boundary`, `L_anchor`, `L_strategy`, `L_edit`). Skip and degrade rates by state code and destination. First-pass rates (plan approved at attempt 1; text accepted at version 1). Comparison with the Step 2 §6 estimate (min 44 / normal 61 / worst 211) |
| **Proof** | The report exists for a fixed sample of real signals covering different material types. Its numbers are reproducible from the stored traces |
| **Decision it enables** | The canonical run's `RunCallBudget` ceiling, set from measured data. Whether SL-10 is needed at all |
| **Hard rule** | **No optimization in this slice.** Destinations are not reduced and stages are not merged to fit 40 calls |
| **Depends on** | SL-6 |

### SL-8a…SL-8d · Publication capability: Facebook, Instagram, Threads, Telegram (C5)

One slice per destination, same shape.

| | |
|---|---|
| **Goal** | Make the destination **capable** (AD-02): publisher, canonical package, preflight, marker authority, metrics collector |
| **Builds** | Canonical package and preflight for the destination (today they exist only for Wix and LinkedIn); the existing publisher (`facebook.py`, `instagram.py`, `threads.py`, `telegram.py`) wired to the package; markers; a raw-metrics collector for S-15. **Instagram:** image from the existing image pipeline (required); Facebook uses it when available |
| **Proof** | On SL-7 texts: package built and preflight `ALLOW` without the publish call. Publisher contract test against the provider's validation or sandbox where one exists. Collector returns raw metrics for a known existing post. Capability recorded as available, so S-07 can mark it `publish` once the rollout scope includes it |
| **Production safety** | No live publication until the destination is added to the rollout scope in SL-11 |
| **Depends on** | SL-6 (texts), SL-0 (markers) |

### SL-9 · Publication capability: Wix and LinkedIn on canonical texts (C5)

| | |
|---|---|
| **Goal** | The existing Wix and LinkedIn capability works on canonical texts **without** LinkedIn recomposition |
| **Builds** | Packages from canonical E-15 texts; conditional link binding at S-14 (R-2); LinkedIn has its own strategy and text, never derived from the article; markers; the existing collectors wrapped for S-15 |
| **Proof** | Preflight `ALLOW` on SL-7 texts. The LinkedIn text in the trace has its own plan and strategy IDs. Link omission when the Wix target is skipped is shown in a test |
| **Depends on** | SL-6, SL-0 |

### SL-10 · Call-boundary optimization (optional; after SL-7)

| | |
|---|---|
| **Goal** | Reduce cost **only if** the SL-7 baseline shows it is needed, without changing responsibilities or scope |
| **Allowed levers** (Step 2 §6) | Merge S-09 ranking into the S-08 call; merge S-10 segmenting into S-08; one S-11 call per unit; one S-13 call for short formats. Each is a separate, measured change |
| **Proof per lever** | Against the SL-7 baseline on the same signal sample: calls reduced; **no regression** in hard-check failures, skip rate, first-pass rate or trace completeness; responsibilities stay separate in the trace (the stage records still exist) |
| **Forbidden** | Removing destinations; skipping S-04 probing; dropping plan checks; letting the Writer decide |
| **Depends on** | SL-7 |

### SL-11 · Canonical run live: the single publisher (C6)

| | |
|---|---|
| **Goal** | The canonical engine becomes the only engine that publishes |
| **Builds** | The live canonical workflow with the ceiling set from SL-7 (or SL-10); a rollout scope that includes every destination whose SL-8/SL-9 is done; all current publishing triggers repointed or retired per Step 5 §3.3, in the same change; a rollback switch |
| **Go-live acceptance** (release gate, measured on a fixed number of consecutive shadow runs; the number is set at planning) | (1) Zero accepted texts with a hard-check failure (V-T01…V-T04). (2) 100 % manifest verification. (3) Zero label-routing violations. (4) Zero duplicate publications in the SL-0 fault-injection suite, re-run on the live workflow. (5) Cost per run within the set ceiling. (6) **Offline owner quality review** of a sample of shadow texts across all six destinations ("this is Never Blank" versus "AI garbage again"). This is the owner's call, offline, never a per-run gate |
| **Cutover vs completion** (clarification C-2, GPT acceptance) | Two separate milestones. **Canonical publisher cutover:** the canonical engine becomes the only publisher, for the destinations in the current rollout scope. **Product rollout completion:** reached only when Wix, LinkedIn, Facebook, Instagram, Threads **and** Telegram all have publication capability enabled and publish through the same canonical engine. Partial destination rollout between the two is temporary; the remaining destinations run `generate_only` inside the same run, never in a different pipeline |
| **Rollback** | Turn canonical publishing off and restore the previous triggers; the shared marker authority prevents duplicates |
| **Depends on** | SL-7 (or SL-10), SL-9 and at least the SL-8 slices included in the first rollout scope |

### SL-12 · Observation for six destinations (S-15)

| | |
|---|---|
| **Goal** | Raw metrics with confounders for every published destination, feeding the knowledge queue |
| **Builds** | Scheduled S-15 job using the six collectors; E-17 ledger records; `observation` and `vt02_feedback` queue items; removal of the inline analytics call and the blended score as a knowledge input |
| **Proof** | Ledger records for real publications on every published destination. Queue items appear. Nothing changes knowledge status automatically |
| **Depends on** | SL-11 |

### SL-13 · Clone check: the product check (C7)

| | |
|---|---|
| **Goal** | Prove that other days, schedules and clients are configuration, not code |
| **Builds** | A second configuration of the same engine, for example another schedule with a different lens, or a second client contract fixture |
| **Proof** | (1) The change set contains **configuration only**: no files in editorial-core modules change. (2) The topology digest is identical to the reference run's. (3) The clone completes a shadow run end to end on all six destinations |
| **Depends on** | SL-11 |

### SL-14 · Removal (C8)

| | |
|---|---|
| **Goal** | Delete code nothing reaches any more |
| **Scope** | The Step 5 §2 "Disable" rows: current editorial stages and `plan_decisions`, LinkedIn recomposition, the Wednesday July modules, `vi_pipeline`, `decision_policy`, the legacy generator and memory, the blended scorer, `PublishedEntry` as a portfolio source |
| **Proof** | A reachability check shows the removed modules have no callers. The full test suite and one canonical run pass unchanged |
| **Depends on** | SL-13 |

---

## 3. Coverage check

| Architecture element | Slice |
|---|---|
| E-01…E-19 | E-01, E-19: SL-1. E-02…E-07: SL-3. E-08, E-09: SL-4. E-10…E-14: SL-4, SL-5. E-15: SL-6. E-16: SL-7, SL-9. E-17: SL-12. E-18: SL-2 |
| S-00…S-15 | S-00…S-03: SL-3. S-04, S-05: SL-4. S-06…S-11: SL-5. S-12, S-13: SL-6. S-14: SL-7 (shadow), SL-8/9 (capability), SL-11 (live). S-15: SL-12 |
| Invariants I-01…I-13, CE-1 | Traces and tests in SL-1 (ARP, no human, topology), SL-4 (I-05), SL-5 (I-04, I-07), SL-6 (I-03, I-09), SL-2 (I-10 to I-13), SL-13 (CE-1) |
| Publication safety S3-I1 | SL-0; re-verified in SL-11 |
| Six destinations | SL-1, SL-5, SL-6, SL-7 (all six in shadow), SL-8a–d and SL-9 (capability), SL-11 (completion = all six publish) |
| Budget | SL-7 baseline, then SL-10 if needed; SL-11 uses the measured ceiling |
| Current paths retired or repointed | SL-11 (triggers), SL-14 (code) |

**Nothing in Steps 1–5 is left without a slice.** No slice introduces a weekday-specific or destination-specific pipeline.

---

## Кратко по-русски (для Светы)

- **Работа нарезана на 15 кусков.** Каждый доводит до рабочего состояния одну возможность единого движка, заканчивается доказательством (записью прогона, тестом или отчётом с цифрами) и не трогает текущие публикации до момента включения.
- **Правило «один движок» теперь проверяется автоматически.** Порядок стадий описан в одном месте, у каждого прогона записывается его отпечаток. Если прогоны с разными настройками прошли разными путями, проверка падает. Код, который выбирает стадии по дню недели или по площадке, тоже не пройдёт проверку.
- **Все шесть площадок — с самого начала,** во всех тестах и прогонах.
- **Отдельный кусок SL-7:** полный прогон на шести площадках «в тени», где сначала честно меряется стоимость по каждой стадии и площадке. Оптимизация — только после этого (SL-10), и без урезания площадок.
- **Подготовка к публикации:** для Facebook, Instagram, Threads и Telegram — по отдельному куску на каждую, Wix и LinkedIn — один общий. LinkedIn больше не пересказывает статью.
- **Включение (SL-11).** Единый движок становится единственным публикатором, а старые процессы перенаправляются или выключаются одним изменением. Прогон считается завершённым, когда публикуются все шесть площадок. Перед включением ты выборочно оцениваешь тексты: «это Never Blank» или «опять ИИ-мусор». Это вне прогона, прогон никого не ждёт.
- **Продуктовая проверка (SL-13):** копия движка с другими настройками должна заработать без единой правки кода.
