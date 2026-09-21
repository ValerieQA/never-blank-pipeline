# Patch R1 to Steps 0–1: four required corrections

*21 September 2026 · response to GPT review verdict "Steps 0–1 accepted with four required corrections before Step 2" · no redesign · Step 2 not started*

**Files changed:** `01_STEP1_TYPED_ENTITIES.md`, `02_ARCHITECTURE_DECISIONS.md`, `CHECKPOINT_STEPS_0_1.md`. **Unchanged:** `00_STEP0_ARCHITECTURE_IMPACT_DELTA.md` (none of the four points touches Step 0).

**Total:** 27 passages replaced. Every replacement below is exact: the *Before* text appeared once in its file and was replaced in full by the *After* text. Russian-summary lines changed for consistency are included.

---

## Correction 1 · E-09 completeness: bounded, testable requirement

**1.1 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| `inadmissible` | list of E-08 | yes | Every tempting inadmissible interpretation considered is recorded, not only the ones that were close |
```

*After:*

```text
| `inadmissible` | list of E-08 | yes | Every inadmissible interpretation generated or explicitly tested by S-04 is recorded. S-04 must deliberately probe for likely tempting interpretations; completeness is not assumed. The list is evidence of what was tested, not a claim that every tempting interpretation was found |
```

**1.2 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| `temptation_note` | text | if inadmissible | Why a writer would reach for it. The detection material for V-T02 |
```

*After:*

```text
| `temptation_note` | text | if inadmissible | Why a writer would reach for it. Detection material for V-T02. V-T02 also checks the text for inadmissible interpretations that are not on the list: the list strengthens detection but does not bound it |
```

**1.3 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| U-1 | Who produces the tempting inadmissible interpretations: the same S-04 call as the admissible ones, or a separate adversarial pass? This affects detection quality and cost | Step 2 (S-04 contract) |
```

*After:*

```text
| U-1 | How S-04 deliberately probes for likely tempting inadmissible interpretations: in the same call as the admissible ones, or in a separate adversarial pass. The requirement is bounded: everything generated or tested is recorded; completeness is not assumed. The choice affects detection quality and cost | Step 2 (S-04 contract) |
```

---

## Correction 2 · AD-01: leading material is the primary evidentiary carrier, not the opening

**2.1 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
- **Link between the two:** each destination strategy must lead with a member of the unit's leading-material set.
```

*After:*

```text
- **Link between the two:** each destination strategy must foreground and use at least one member of the unit's leading-material set as its **primary evidentiary carrier**. It does not have to appear in the first line or the opening move. Opening and reveal mechanics stay independent per destination (`opening` and `leading_material_ref` are separate fields of E-13).
```

**2.2 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
| **C with exactly one leading item** (the map's literal wording) | Over-constrains short forms. On Ramp (walkthrough B), the article leads with the payment timeline while a Threads post may lead with the one figure. Forcing the same item on every destination reintroduces a soft parent |
```

*After:*

```text
| **C with exactly one leading item** (the map's literal wording) | Over-constrains short forms. On Ramp (walkthrough B), the article carries its argument on the payment timeline while a Threads post may carry it on the one figure. Forcing the same item on every destination reintroduces a soft parent |
| **Leading material must be the opening** | Merges two separate strategy fields and makes every destination open the same way. That is a hidden template, the failure the destination-strategy research was meant to remove |
```

**2.3 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| `leading_material_ref` | ref | yes | Must be a member of the anchor's `leading_material` (AD-01) |
```

*After:*

```text
| `leading_material_ref` | ref | yes | Must be a member of the anchor's `leading_material` (AD-01). It is the strategy's **primary evidentiary carrier**: at least one move of the reader path references it. It does **not** have to be in the opening or the first line; the opening is decided independently below |
```

**2.4 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
Each destination has its own full strategy and must lead with an item from that set | OPEN-19 |
```

*After:*

```text
Each destination has its own full strategy and uses at least one item from that set as its primary evidentiary carrier, not necessarily in the opening or first line | OPEN-19 |
```

**2.5 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| M-2 | §7.4 | Shared leading material is a **set of 1–2 items**, and each destination leads with one of them | AD-01 |
```

*After:*

```text
| M-2 | §7.4 | Shared leading material is a **set of 1–2 items**. Each destination uses at least one of them as its primary evidentiary carrier. It is not an opening constraint: opening and reveal stay per destination | AD-01 |
```

**2.6 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
якорь и один-два «ведущих материала». Всё остальное каждая площадка выбирает сама.
```

*After:*

```text
якорь и один-два «ведущих материала». Ведущий материал — главная опора текста, но не обязательно его начало: с чего начать, каждая площадка решает сама. Всё остальное площадка тоже выбирает сама.
```

---

## Correction 3 · E-16 labels: post-decision observability, never a required call or publication dependency

**3.1 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
| **AD-07** | Labels (`material_label`, strategy label, form label) live in a separate **label record**, written after the decision by a separate classifier. It is never routed to a planning stage. `stage_routing` proves this per run |
```

*After:*

```text
| **AD-07** | Labels (`material_label`, strategy label, form label) live in a separate **label record**, written after the decision. It is never routed to S-00…S-13; `stage_routing` proves this per run. Label generation is **post-decision observability only**: it is not required for successful generation or publication, is not a synchronous step of the run, and may be code-based, batched, asynchronous, or absent when unavailable. A missing label never fails a run |
```

**3.2 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
**There is no label field.** Labels are written afterwards (label record, E-16) and are never inputs to S-08…S-13 (AD-07).
```

*After:*

```text
**There is no label field.** Labels are written afterwards (label record, E-16) and are never inputs to S-00…S-13 (AD-07).
```

**3.3 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| `label_ref` | `lbl` ID | yes | |
```

*After:*

```text
| `label_ref` | `lbl` ID | no | Filled in when a label record exists. A fingerprint without labels is valid |
```

**3.4 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
**Label record.** Written after the decision (AD-07).
```

*After:*

```text
**Label record.** Written after the decision (AD-07). **Label generation is post-decision observability.** It must not be required for successful generation or publication, and it is not a synchronous step of the run. It may be code-based, batched, asynchronous (e.g. a periodic job over fingerprints), or omitted when unavailable. A run with no label record is complete. Consumers of labels (V-S06, V-S07, portfolio reports) treat missing labels as missing data, not as failure.
```

**3.5 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| `classifier` | StageAttribution | Separate from the planner |
```

*After:*

```text
| `classifier` | StageAttribution | Separate from the planner. `decider_kind` may be `code`, `rule` or `model`; no model call is required |
```

**3.6 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| E-16 | Fingerprint (+ label record) | S-14 | `PublishedEntry` (hook, echo, topic, cta) | **Rebuild** |
```

*After:*

```text
| E-16 | Fingerprint (+ optional label record, post-decision, asynchronous) | S-14 | `PublishedEntry` (hook, echo, topic, cta) | **Rebuild** |
```

**3.7 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| AD-07 | Labels live in a separate post-decision record that is never routed to planners | I-10 made structural |
```

*After:*

```text
| AD-07 | Labels live in a separate post-decision record that is never routed to S-00…S-13. Label generation is observability only: optional, may be code-based, batched or asynchronous, never a publication dependency | I-10 made structural |
```

**3.8 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| M-3 | §2, E-05 | `material_label` leaves E-05 and goes to a separate label record written after the decision | AD-07 |
```

*After:*

```text
| M-3 | §2, E-05 | `material_label` leaves E-05 and goes to a separate, optional label record written after the decision, outside the production critical path | AD-07 |
```

---

## Correction 4 · AD-03 / OPEN-18 status: architecture resolved; production behavior disabled pending observation

**4.1 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
## AD-03 · OPEN-18: when a signal is split into units, and how the calendar absorbs it

```

*After:*

```text
## AD-03 · OPEN-18: when a signal is split into units, and how the calendar absorbs it

**Status: architecture resolved; production behavior disabled pending observation.** Until the cap is raised by an explicit decision, no second unit is created or deferred in production. Implementers must not build split execution as live behaviour on the strength of this record.

```

**4.2 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
**Initial configuration.** The maximum starts at **1**. S-05 still evaluates rules 1–3 and records a `split_candidate` in the run trace. Splitting is observed before it is enabled. Enabling it later is a configuration change, not an architecture change.
```

*After:*

```text
**Initial configuration.** The maximum starts at **1**. With cap = 1, S-05 evaluates rules 1–3 and records a `split_candidate` in the run trace, and nothing else: **no additional unit is created, stored or deferred**, and no deferred unit re-enters S-00. Splitting is observed before it is enabled. Enabling it later is a configuration change plus an explicit decision based on the traced split-candidate rate, not an architecture change.
```

**4.3 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
One unit per signal per slot; the others are deferred with an expiry and re-enter S-00. **Initial cap = 1**: split candidates are traced, not acted on | OPEN-18 |
```

*After:*

```text
One unit per signal per slot; the others are deferred with an expiry and re-enter S-00. **Status: architecture resolved; production behavior disabled pending observation.** Initial cap = 1: split candidates are traced, but no additional unit is created or deferred in production | OPEN-18 |
```

**4.4 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| M-8 | §14 | OPEN-15, OPEN-18, OPEN-19 and OPEN-21 move from open to decided, with references to AD-01…AD-04 | — |
```

*After:*

```text
| M-8 | §14 | OPEN-15 and OPEN-19 move to decided. OPEN-18 moves to "architecture resolved; production behavior disabled pending observation". OPEN-21 moves to "schema ready; behaviour deferred". References AD-01…AD-04 | — |
```

**4.5 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| `candidate_kind` | `signal` / `deferred_unit` | AD-03: deferred units compete with new signals |
```

*After:*

```text
| `candidate_kind` | `signal` / `deferred_unit` | AD-03: deferred units compete with new signals. While split is disabled (cap = 1), only `signal` occurs in production |
```

**4.6 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
`split_candidate` flag when the cap prevented the split |
```

*After:*

```text
`split_candidate` flag when the cap prevented the split. With cap = 1 (current), only the flag and the rule results are written; no sibling unit exists |
```

**4.7 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
**Сначала деление выключено**: система только записывает, где могла бы делить. Включим, когда увидим цифры.
```

*After:*

```text
**Статус: архитектура решена, в продакшене деление выключено до наблюдений.** Система только записывает, где могла бы делить; вторая единица не создаётся и не откладывается. Включим отдельным решением, когда увидим цифры.
```

**4.8 · `02_ARCHITECTURE_DECISIONS.md`**

*Before:*

```text
**Status of every decision below: ACCEPTED for architecture.** Its thresholds and limits are implementation parameters (OPEN-22, OPEN-25), not part of the decision.
```

*After:*

```text
**Status of every decision below: ACCEPTED for architecture.** Its thresholds and limits are implementation parameters (OPEN-22, OPEN-25), not part of the decision. Two decisions accept the architecture without enabling production behaviour: **AD-03** (architecture resolved; production behavior disabled pending observation) and **AD-04** (schema ready; behaviour deferred).
```

**4.9 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| M-6 | §2, E-10; §4, S-00 | A unit can be deferred and outlive its run. S-00 selects among new signals **and** deferred units | AD-03 |
```

*After:*

```text
| M-6 | §2, E-10; §4, S-00 | A unit can be deferred and outlive its run. S-00 selects among new signals **and** deferred units. Dormant in production while the split cap is 1 | AD-03 |
```

**4.10 · `CHECKPOINT_STEPS_0_1.md`**

*Before:*

```text
| Деление сигнала | Строгие условия, на старте выключено, только наблюдаем |
```

*After:*

```text
| Деление сигнала | Архитектура решена, в продакшене выключено до наблюдений: только записываем кандидатов |
```

---

## Кратко по-русски (для Светы)

Внесены все четыре правки GPT, архитектура не переделывалась.

1. **Соблазнительные ложные выводы.** Больше не требуем «записать все». Требуем записать всё, что система проверила, и обязательно целенаправленно искать типичные ловушки. Полнота не предполагается.
2. **Ведущий материал.** Это главная опора текста, а не его начало. С чего начинать, каждая площадка решает сама.
3. **Метки.** Это только аналитика после решения. Отдельный обязательный вызов модели не нужен: метки можно ставить кодом, пачкой, потом или не ставить вовсе. Без меток прогон не падает.
4. **Деление сигнала.** Теперь везде написано точно: «архитектура решена, в продакшене выключено до наблюдений». Разработчик не сможет прочитать это как «можно делать».

Шаг 2 не начат, жду проверки GPT.
