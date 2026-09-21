# Patch R2 to Step 2 (and Step 1 schema fixes)

*21 September 2026 · response to GPT review "Step 2: ACCEPT WITH R2 PATCH" · U-1/U-2/U-3, F-1…F-6 and R-1…R-5 kept · no redesign*

**Files changed:** `03_STEP2_STAGE_CONTRACTS.md`, `01_STEP1_TYPED_ENTITIES.md`. **Unchanged:** Step 0, AD-01…AD-10.

**Total:** 22 exact replacements. Each *Before* passage occurred exactly once in its file. Items tagged `C1+C2` serve both corrections and are listed under Correction 1.

**Call budget:** unchanged. The new edit branches consume `L_edit`, and the new replan branch consumes `L_strategy`. Both were already bounded in §6.

**New architectural contradictions exposed:** none. Therefore this patch proceeds directly to Step 3, as instructed.

---

## Correction 1 · V-T08 routing split by ownership

**1 · `03_STEP2_STAGE_CONTRACTS.md`** (C1+C2)

*Before:*

```text
| Phrasing or a fact misquoted from the core | S-12 edit, same approved plan |
```

*After:*

```text
| Phrasing or a fact misquoted from the core | S-12 edit, same approved plan |
| An unsupported fact that can be removed without breaking the plan; an ending that recaps although its approved intention is valid | S-12 edit, same approved plan |
| An unsupported fact the plan cannot do without; an ending intention that is itself a recap | S-08 (the approved strategy or plan owns the fault) |
```

**2 · `03_STEP2_STAGE_CONTRACTS.md`** (C1)

*Before:*

```text
| V-T03 chain broken; V-T07 plan not executed; V-T08 Echo recaps | S-08 | `L_strategy` | `SKIP` destination |
```

*After:*

```text
| V-T03 chain broken; V-T07 plan not executed | S-08 | `L_strategy` | `SKIP` destination |
| V-T08 Echo recaps, branch **strategy**: the approved `ending_intention`, executed faithfully, would itself recap the opening | S-08 | `L_strategy` | `SKIP` destination |
| V-T08 Echo recaps, branch **execution**: the approved `ending_intention` is a valid reframe and the Writer executed it as a recap | S-12 edit, same plan | `L_edit` | `SKIP` publication |
```

**3 · `03_STEP2_STAGE_CONTRACTS.md`** (C1+C2)

*Before:*

```text
A text with both an edit-class and a replan-class finding follows the replan route: a decision error outranks phrasing.
```

*After:*

```text
A text with both an edit-class and a replan-class finding follows the replan route: a decision error outranks phrasing.

**Branch decisions (V-T01, V-T08).** The branch is decided per finding and **recorded** in the CheckResult (`fault_owner`: `writer` / `plan`, plus the branch name and the criterion applied).

- **V-T01 `removable` vs `load-bearing`.** Code locates the unsupported item and the plan elements (thesis, promise, move, opening) that reference the text span. The truth call answers one explicit question: can each of those elements still be executed with only core material? Yes → `removable`. No → `load-bearing`.
- **V-T08 `strategy` vs `execution`.** The execution call judges the approved `ending_intention` on its own, against the V-T08 criterion (reframe, not recap), before judging the text. Intention fails → `strategy`. Intention passes and the text fails → `execution`.
- **When uncertain,** the route defaults to the **plan** branch (S-08). A decision error is never charged to the Writer by default.
```

**4 · `03_STEP2_STAGE_CONTRACTS.md`** (C1+C2)

*Before:*

```text
| S-13 | Phrasing, facts, links | S-12 (same plan) | `L_edit` | `SKIP` publication |
| S-13 | Structure, chain, execution, Echo | S-08 | `L_strategy` | `SKIP` destination |
```

*After:*

```text
| S-13 | Phrasing, misquoted facts, links; V-T01 `removable`; V-T08 `execution` | S-12 (same plan) | `L_edit` | `SKIP` publication |
| S-13 | Structure, chain, plan execution; V-T01 `load-bearing`; V-T08 `strategy` | S-08 | `L_strategy` | `SKIP` destination |
```

**5 · `03_STEP2_STAGE_CONTRACTS.md`** (C1+C2)

*Before:*

```text
**Validity.** Every target is upstream of its source and owns the failed decision: S-03 owns material, S-04 truth, S-06 the anchor, S-08 structure, S-12 phrasing. **No route targets the Writer for a decision failure.**
```

*After:*

```text
**Validity.** Every target is upstream of its source and owns the failed decision: S-03 owns material, S-04 truth, S-06 the anchor, S-08 structure, S-12 phrasing and faithful execution of a valid plan. **No route targets the Writer for a decision failure.** Where ownership is split (V-T01, V-T08), the branch is decided per finding, recorded, and defaults to the plan branch when uncertain.
```

---

## Correction 2 · V-T01 `fact not in core` split

**1 · `03_STEP2_STAGE_CONTRACTS.md`** (C2)

*Before:*

```text
| V-T01 fact not in the core; V-T04 invented link or source | S-12 edit (remove it), same plan | `L_edit` | `SKIP` publication |
```

*After:*

```text
| V-T01 fact not in the core, branch **removable**: the plan's thesis, promise and every move can still be executed without it; V-T04 invented link or source | S-12 edit (remove it), same plan | `L_edit` | `SKIP` publication |
| V-T01 fact not in the core, branch **load-bearing**: removing it leaves the thesis, a promise or a move without support (the plan required material the core does not hold) | S-08 | `L_strategy` | `SKIP` destination |
```

---

## Correction 3 · S-04 re-entry version semantics (boundary commit)

**1 · `03_STEP2_STAGE_CONTRACTS.md`** (C3)

*Before:*

```text
| **Outputs** | `E-08` (sole producer); `E-09` (sole producer; a new version on re-entry) |
```

*After:*

```text
| **Outputs** | `E-08` (sole producer); `E-09` (sole producer; a new version on re-entry). Version semantics: see **Boundary commit** below |
```

**2 · `03_STEP2_STAGE_CONTRACTS.md`** (C3)

*Before:*

```text
| **Seam** | **New.** Consumes #58 claim mode as the default for `audience_transfer`; the code transfer rule can only make it stricter. `ModelInterpretation` is not used (AD-06) |
| **Publication** | — |

### S-05
```

*After:*

```text
| **Seam** | **New.** Consumes #58 claim mode as the default for `audience_transfer`; the code transfer rule can only make it stricter. `ModelInterpretation` is not used (AD-06) |
| **Publication** | — |

**Boundary commit (version semantics, binding for Step 3).** A re-entry produces a **coordinated** E-08/E-09 change, committed together as one boundary commit:

1. **The E-09 version is the unit of consistency.** Every E-09 version is a complete snapshot. It lists each member interpretation as an exact (`interpretation_id`, `version`) pair, in `admissible` or `inadmissible`.
2. **A newly discovered interpretation** (not previously recorded) gets a **new E-08 record** (new ID, version 1), marked `inadmissible` with its reason, and a new E-09 version includes it.
3. **A previously recorded interpretation that must be reclassified** (e.g. an admissible one now shown to be unsupported) gets a **new version of the same E-08** (`supersedes` the old version, admissibility changed), and the new E-09 version references the new version.
4. **Unchanged interpretations are not copied.** The new E-09 version references their existing (ID, version) pairs.
5. **No E-08 change exists without a new E-09 version,** and vice versa. Both are written in one S-04 execution. A reader never sees an E-08 version that no E-09 version references.
6. **Downstream references carry versions.** E-11 (anchor), E-13 and PlanVerdict record the E-09 version they were decided against. The anchor is invalidated when its interpretation's current version in the newest E-09 is inadmissible. Invalidation is detected by code comparing the pairs.

### S-05
```

**3 · `03_STEP2_STAGE_CONTRACTS.md`** (C3)

*Before:*

```text
| **Boundary version drift.** After an S-04 re-entry, plans approved against the older boundary version could reach S-12 |
```

*After:*

```text
| **Boundary version drift.** After an S-04 re-entry (a boundary commit, §1 S-04), plans approved against the older boundary version could reach S-12 |
```

**4 · `01_STEP1_TYPED_ENTITIES.md`** (C3)

*Before:*

```text
| `inadmissible` | list of E-08 | yes | Every inadmissible
```

*After:*

```text
| `inadmissible` | list of (`interpretation_id`, `version`) | yes | Every inadmissible
```

**5 · `01_STEP1_TYPED_ENTITIES.md`** (C3)

*Before:*

```text
**Validation.** No interpretation is in both lists. Every interpretation in `admissible` passes the E-08 rules.
```

*After:*

```text
**Validation.** No interpretation is in both lists. Every interpretation in `admissible` passes the E-08 rules.

**Versioning (patch R2).** Every E-09 version is a complete snapshot of exact E-08 versions. A newly discovered interpretation is a new E-08 record. A reclassified one is a new version of the existing E-08. An E-08 version and the E-09 version that first references it are written together (the boundary commit, Step 2 S-04).
```

**6 · `01_STEP1_TYPED_ENTITIES.md`** (C3)

*Before:*

```text
| `interpretation_ref` | admissible `int` ID in the unit's scope | yes | |
```

*After:*

```text
| `interpretation_ref` | admissible (`interpretation_id`, `version`) in the unit's scope | yes | |
| `boundary_ref` | E-09 version the anchor was chosen against | yes | Patch R2: the anchor is invalid when a newer E-09 version lists its interpretation as inadmissible |
```

**7 · `01_STEP1_TYPED_ENTITIES.md`** (C3)

*Before:*

```text
| `anchor_ref` | `anc` ID | yes | Must equal the unit's anchor (I-07) |
```

*After:*

```text
| `anchor_ref` | `anc` ID | yes | Must equal the unit's anchor (I-07) |
| `boundary_ref` | E-09 version the strategy was built against | yes | Patch R2 |
```

---

## Step 1 schema fixes F-1, F-2, F-3, F-6 (and R-2, R-5 carried into the schema)

**1 · `01_STEP1_TYPED_ENTITIES.md`** (F-1)

*Before:*

```text
| `role` | candidate / chosen / excluded | yes | |

```

*After:*

```text
(removed)
```

**2 · `01_STEP1_TYPED_ENTITIES.md`** (F-1)

*Before:*

```text
**StrategySelection** (one per `candidate_set_id`, written by S-09):
```

*After:*

```text
**Roles are not stored on E-13** (fix F-1). E-13 is immutable. Whether a candidate was chosen or excluded is recorded only in StrategySelection.

**StrategySelection** (one per `candidate_set_id`, written by S-09):
```

**3 · `01_STEP1_TYPED_ENTITIES.md`** (F-2)

*Before:*

```text
| `exemplars` | list of (reference library item ID, "take" note, "do not copy" note) | no | Selected at S-11 |
| `forbidden` | phrases and construction types in force | yes | Resolved from the contract (tier 2) and hard policy (tier 1) |
| `plan_checks` | list of CheckResult (V-P01…V-P05) | after S-11 | |
| `status` | draft / approved / rejected | yes | Only `approved` goes to S-12 |
| `attempt` | integer | yes | Against the replan limit |
```

*After:*

```text
| `exemplars` | list of (reference library item ID, "take" note, "do not copy" note) | no | Empty in the draft (S-10). Filled in the approved version (S-11) |
| `forbidden` | phrases and construction types in force | yes | Resolved from the contract (tier 2) and hard policy (tier 1) |
| `stage_of_version` | `draft` (produced by S-10) / `approved` (produced by S-11) | yes | An approved version `supersedes` its draft. Only an approved version goes to S-12 |
| `attempt` | integer | yes | Against the replan limit |

**PlanVerdict** (fix F-2; one per plan draft, sole producer S-11): `plan_ref` (draft ID and version); `boundary_ref` (the E-09 version checked against); CheckResults V-P01…V-P05; result `pass` / `fail`; route and counter; `approved_plan_ref` when it passed. Check results and pass/fail are **not** stored on E-14.
```

**4 · `01_STEP1_TYPED_ENTITIES.md`** (F-2)

*Before:*

```text
| `writer_signal` | `plan_holds` bool + reason | yes | `false` → `REPLAN` → S-08, not improvisation |
| `text_checks` | list of CheckResult (V-T01…V-T08, V-S01…V-S10) | after S-13 | |
| `version` | integer | yes | +1 per edit. Edits route by I-09 |
| `status` | candidate / accepted / rejected / skipped | yes | |
```

*After:*

```text
| `writer_signal` | `plan_holds` bool + reason | yes | `false` → `REPLAN` → S-08, not improvisation |
| `version` | integer | yes | +1 per edit. Edits route by I-09 |
```

**5 · `01_STEP1_TYPED_ENTITIES.md`** (F-2)

*Before:*

```text
**CheckResult** (shared by E-14 and E-15): check ID; rule status and class at the time of the run; method (code / model against an explicit criterion); pass / fail; findings with references; route taken.
```

*After:*

```text
**TextVerdict** (fix F-2; one per text version, sole producer S-13): `text_ref` (ID and version); `plan_ref`; `boundary_ref`; CheckResults V-T01…V-T08 and V-S01…V-S10; result `accepted` / `edit` / `replan` / `skip`; route and counter. Status and check results are **not** stored on E-15.

**CheckResult** (shared by PlanVerdict and TextVerdict): check ID; rule status and class at the time of the run; method (code / model against an explicit criterion); pass / fail; findings with references; route taken; for V-T01 and V-T08, `fault_owner` (`writer` / `plan`), the branch name and the criterion applied (patch R2).
```

**6 · `01_STEP1_TYPED_ENTITIES.md`** (F-3)

*Before:*

```text
### E-07 · Gap

What is missing, and what the enrichment loop did about it.
```

*After:*

```text
### E-07 · Gap

What is missing, and what the enrichment loop did about it. **Sole producer: S-03** (fix F-3). S-02 does not create gaps; it emits MaterialNotes (free-text missing-material notes with references), which S-03 turns into E-07 only when a note blocks a decision.
```

**7 · `01_STEP1_TYPED_ENTITIES.md`** (F-6+C3)

*Before:*

```text
| `core_ref` | (`core_id`, version) | yes | The final core version after enrichment |
| `admissible` | list of E-08 | yes | Empty → `SKIP` with state "no admissible interpretation" |
```

*After:*

```text
| `core_ref` | (`core_id`, version) | yes | The final core version after enrichment |
| `relevance_ref` | RelevanceAssessment (`decision.json`) ID and digest | yes | Fix F-6: the relevance evidence the reader connection and `audience_transfer` defaults came from |
| `version` | integer | yes | 1 at the first S-04 run; +1 per boundary commit (Step 2, S-04) |
| `admissible` | list of (`interpretation_id`, `version`) | yes | Exact E-08 versions. Empty → `SKIP` with state "no admissible interpretation" |
```

**8 · `01_STEP1_TYPED_ENTITIES.md`** (R-2)

*Before:*

```text
| `cross_destination_link` | target destination + the interpretation the link promises | no | The target must be eligible. If it is skipped, the link is removed (`DEGRADE`) |
```

*After:*

```text
| `cross_destination_link` | target destination + the interpretation the link promises | no | Always **conditional** (Step 2 R-2). The text must deliver its promise without the link. The link is bound at S-14 only if the target was published; otherwise it is omitted (`DEGRADE`) |
```

**9 · `03_STEP2_STAGE_CONTRACTS.md`** (R-5)

*Before:*

```text
| R-5 | Schema fixes F-1, F-2, F-3, F-6 | `01_STEP1_TYPED_ENTITIES.md` (to apply in the next revision after review) |
```

*After:*

```text
| R-5 | Schema fixes F-1, F-2, F-3, F-6 | `01_STEP1_TYPED_ENTITIES.md`: **applied in patch R2** |
```

---

## Кратко по-русски (для Светы)

- **Концовка-пересказ.** Если неудачна сама задумка концовки в стратегии, возвращаемся к стратегии. Если задумка хорошая, а автор просто пересказал начало, автор правит текст сам.
- **Факт, которого нет в доказательствах.** Если его можно убрать и план не рассыпется, автор убирает его сам. Если без этого факта тезис или обещание текста не держатся, значит, ошибся план: возвращаемся к стратегии. Какая ветка выбрана, записывается. При сомнении ошибку считаем ошибкой плана, а не автора.
- **Новая ловушка, найденная в тексте.** Теперь точно описано, как это хранится: граница интерпретаций получает новую полную версию, а сама интерпретация — новую запись или новую версию. Шаг 3 (хранение) берёт это правило как есть.
- **В схемы шага 1 внесены четыре ранее записанные поправки.**

Новых противоречий правка не выявила, поэтому сразу перехожу к шагу 3.
