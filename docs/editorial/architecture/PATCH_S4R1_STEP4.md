# Patch S4-R1 to Step 4 (propagated to Steps 1–3)

*21 September 2026 · response to GPT review "S3-R1 ACCEPTED; STEP 3 CLOSED; STEP 4 ACCEPTED WITH PATCH S4-R1" · no redesign*

**Files changed:** `05_STEP4_KNOWLEDGE_REGISTER.md`, `01_STEP1_TYPED_ENTITIES.md` (KnowledgeRef, PrecedenceApplication, KnowledgeQueueItem), `03_STEP2_STAGE_CONTRACTS.md` (S-09 config, S-15 outputs, producer table), `04_STEP3_STORAGE_AND_RUN_TRACE.md` (queue producers).
**Total:** 14 exact replacements.

**New contradictions exposed:** none.
- A weak-candidate that cannot exclude or route is compatible with every ARP route in Step 2: those routes are triggered by checks and hard records, never by candidates alone.
- The fail-closed rule for oversized mandatory knowledge is a new `SKIP` reason at the stage's scope, within the existing ARP.

Step 5 therefore follows directly.

---

## Correction 1 · executable `weak-candidate` demotion

**1 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
| `weak-candidate` | **Set only by the loader** when a candidate or descriptive record is past `review_by` (§5). Never written in a file | as the file's tier | Loader (automatic) |
```

*After:*

```text
| `weak-candidate` | **Set only by the loader** when a candidate or descriptive record is past `review_by` (§5). Never written in a file. Demotion semantics in §5.1 | as the file's tier | Loader (automatic) |
```

**2 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
**Every expiry** creates one KnowledgeQueueItem for the keeper, written by the S-15 / post-run job (Step 3 §3.2 producer rule), once per record per expiry, not once per run.
```

*After:*

```text
### 5.1 What `weak-candidate` may and may not do (patch S4-R1)

A `weak-candidate` does **not** behave like its unexpired source status. It keeps its tier, but it has these executable limits:

1. **It cannot by itself cause an exclusion, a `REPLAN` or a `SKIP`.**
   - At S-09, a candidate strategy is never excluded solely because it conflicts with a weak-candidate.
   - At S-11 and S-13, no route is triggered solely by a weak-candidate.
   - If a weak-candidate is the only record behind an exclusion or route, that exclusion or route is not taken. The conflict is recorded as a hint instead.
2. **It loses to any non-expired record of the same tier,** whatever the confidences. Within tier 3, the order is therefore: non-expired by confidence, then weak-candidates by confidence.
3. **It is usable only as supporting soft input or as a late tie-breaker.** In S-09 it can act only after the §7.3 tie-breakers that rest on evidence, destination and interpretation risk. That is, at the portfolio/cost end, as a soft preference.
   - **Exception:** it counts at its original weight when a non-expired record of the same or a higher tier points the same way ("reinforced"). The reinforcing record is cited in the KnowledgeRef.
4. **Recording.** Every KnowledgeRef records both the **file status** and the **effective status** (`weak-candidate`), and whether the record was reinforced. Every PrecedenceApplication that involves a weak-candidate records its effective status, so the trace shows that demoted knowledge could not win a conflict.

### 5.2 Expiry review items

**Expiry and review queue items are produced by the Knowledge Maintenance job, not by a run** (patch S4-R1).

- The job is **offline and scheduled**, for example daily. It scans the register and client rule files for records past `review_by`, or within a warning window before it. It writes one KnowledgeQueueItem per record per expiry, never one per run.
- It does **not** depend on a publication or a run happening, so expiry review continues even when nothing is published.
- It runs outside every production run and **never blocks one**. If it fails, the next scheduled run retries. Production runs still apply §5 demotion at load time, independently of the job.
- **The run's loader does not write queue items.** It only computes effective status.
```

**3 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| **KnowledgeRef** | `record_id`, `record_version`, tier and status **as they were at the time of use** |
```

*After:*

```text
| **KnowledgeRef** | `record_id`, `record_version`, tier, **file status**, **effective status** (e.g. `weak-candidate` after expiry), `reinforced_by` (a non-expired record, if any), all **as they were at the time of use** (patch S4-R1) |
```

**4 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
| **PrecedenceApplication** | Conflict description; winning record and tier; losing record and tier; rule applied (map §5) |
```

*After:*

```text
| **PrecedenceApplication** | Conflict description; winning record, tier and effective status; losing record, tier and effective status; rule applied (map §5; weak-candidate rules, Step 4 §5.1) |
```

**5 · `03_STEP2_STAGE_CONTRACTS.md`**

*Before:*

```text
| **Knowledge / config** | Map §5 tiers; §7.3 tie-breakers |
```

*After:*

```text
| **Knowledge / config** | Map §5 tiers; §7.3 tie-breakers; weak-candidate limits (Step 4 §5.1): a weak-candidate alone never excludes a candidate, and acts only at the soft end of the tie-breakers unless reinforced |
```

---

## Correction 2 · KnowledgeQueueItem producers split; offline Knowledge Maintenance job

**1 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
| **KnowledgeQueueItem** | `data/editorial/knowledge_queue/<item_id>.json` | S-15 only (the sole producer, Step 2 §5.1). Sources: E-17 observations, and V-T02 findings that matched no recorded interpretation (U-1 feedback), read from the run's TextVerdicts while the workspace is still retained | Keeper's offline queue | Until the keeper closes it; then kept with the decision |
```

*After:*

```text
| **KnowledgeQueueItem** | `data/editorial/knowledge_queue/<item_id>.json` | **Two producers, split by item kind** (patch S4-R1). **S-15**: `observation` items (from E-17) and `vt02_feedback` items (V-T02 findings that matched no recorded interpretation, U-1, read from the run's TextVerdicts while the workspace is still retained). **Knowledge Maintenance job** (offline, scheduled, outside every run): `expiry_review` items. Each kind has exactly one producer | Keeper's offline queue | Until the keeper closes it; then kept with the decision |
```

**2 · `03_STEP2_STAGE_CONTRACTS.md`**

*Before:*

```text
| **Outputs** | `E-17` (sole producer); KnowledgeQueueItem (sole producer) |
```

*After:*

```text
| **Outputs** | `E-17` (sole producer); KnowledgeQueueItem of kinds `observation` and `vt02_feedback` (sole producer of those kinds). `expiry_review` items come from the offline Knowledge Maintenance job (Step 4 §5.2), not from S-15 |
```

**3 · `03_STEP2_STAGE_CONTRACTS.md`**

*Before:*

```text
| E-17, KnowledgeQueueItem | S-15 | Keeper (offline) | n/a |
```

*After:*

```text
| E-17; KnowledgeQueueItem kinds `observation`, `vt02_feedback` | S-15 | Keeper (offline) | n/a |
| KnowledgeQueueItem kind `expiry_review` | Knowledge Maintenance job (offline, scheduled; outside every run) | Keeper (offline) | n/a |
```

**4 · `01_STEP1_TYPED_ENTITIES.md`**

*Before:*

```text
**KnowledgeQueueItem** (proposal to the keeper): referenced observations; target `K-*` record; proposed status change; evidence summary.
```

*After:*

```text
**KnowledgeQueueItem** (proposal to the keeper): `kind` (`observation` / `vt02_feedback` / `expiry_review`); referenced observations or findings; target `K-*` record; proposed status change; evidence summary. Producers by kind: S-15 (`observation`, `vt02_feedback`); the offline Knowledge Maintenance job (`expiry_review`), patch S4-R1.
```

---

## Correction 3 · hard knowledge is never truncated

**1 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
6. **Size discipline.** If the applicable set for a model stage is too large for the call, records are included in tier order, then by confidence. The excluded remainder is recorded. The stage is never silently given a subset.
```

*After:*

```text
6. **Size discipline** (patch S4-R1).
   - **Mandatory knowledge is never truncated.** When applicable, these always reach the stage in full: every tier `0a`, `0b`, `0c` and `A` record; every tier `1` and tier `2` rule (including the client's approved rules); every hard (`class: H`) check record the stage applies.
   - **Only** `descriptive`, `candidate` and `weak-candidate` records may be reduced for context size. They are cut in tier order, then by confidence, weak-candidates first. The excluded remainder is recorded in the StageRecord.
   - **If the mandatory set alone exceeds the request capacity,** the stage fails closed **before** the model call. The call is not made, and the StageRecord records `mandatory_knowledge_exceeds_capacity` with the sizes. The outcome is `SKIP` at the stage's scope (destination for S-08…S-13; signal or unit for earlier stages). No incomplete hard-policy surface is ever sent.
   - `stage_routing` containment proves, per request, that every mandatory record was present.
```

---

## Correction 4 · client ladders constrained; universal Level 4 tightened

**1 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
| 4 | **Established**: "across … , …" | Systematic evidence: data over many cases, official statistics, a study with a method |
```

*After:*

```text
| 4 | **Established**: "across … , …" | **Either** authoritative statistics that directly measure the thing claimed (e.g. an official statistical series on exactly that quantity), **or** convergent or systematic evidence across multiple cases: several independent studies agreeing, a systematic review, data spanning many cases. **One individual study, however well-designed, reaches level 3 at most** (patch S4-R1) |
```

**2 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
- A client ladder (declared in the contract, as `claim_strength_ceiling` today) replaces this one for that client's runs (AD-10). A client ladder must be ordered from weakest to strongest; the validator checks that it has at least two levels.
```

*After:*

```text
- **A client ladder** (declared in the contract, as `claim_strength_ceiling` today) is used for that client's runs (AD-10), under constraints (patch S4-R1):
  - It may **rename** the universal levels, e.g. "observed on one shop floor" for level 2.
  - It may **restrict further**, e.g. merge levels 3 and 4, or declare a lower top level.
  - It may **never permit a stronger assertion than the universal ceiling for the same evidence pattern.**
  - To make that checkable, every client level must declare which universal level it **maps to**. Its effective ceiling is the minimum of the client level and the universal level reached by the evidence. A client level can never lift a claim above what the universal ladder allows for that evidence.
  - The client ladder must be ordered from weakest to strongest and have at least two levels.
  - The validator rejects a client ladder that lacks mappings, is not monotonic, or maps a level to a stronger universal level than its position allows.
```

**3 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
8. `K-DST-*` lacks `verified_on`;
```

*After:*

```text
8. `K-DST-*` lacks `verified_on`;
9. a client ladder lacks a universal-level mapping for every level, is not monotonic, or could permit a stronger assertion than the universal ladder for the same evidence (§7);
```

**4 · `05_STEP4_KNOWLEDGE_REGISTER.md`**

*Before:*

```text
9. a file contains text matching credential patterns (Q8).
```

*After:*

```text
10. a file contains text matching credential patterns (Q8).
```

---

## Кратко по-русски (для Светы)

- **Устаревшее знание** теперь действительно слабее. Оно не может само по себе отбросить вариант, вернуть план на доработку или отменить публикацию. Оно всегда проигрывает свежему знанию того же уровня и работает только как мягкая подсказка. Если его подтверждает свежее знание, вес возвращается.
- **Напоминания о перепроверке знаний** создаёт отдельная плановая задача вне прогонов. Они приходят, даже если ничего не публиковалось.
- **Жёсткие правила** (закон, этика, правила площадок, правила клиента, обязательные проверки) никогда не урезаются ради длины запроса. Если они не влезают в запрос, стадия не запускается, и причина записывается.
- **Шкала клиента** может переименовать ступени или сделать их строже, но не может разрешить более сильное утверждение, чем общая шкала. Одно исследование, даже хорошее, теперь даёт максимум «подтверждено несколькими источниками», но не «установлено».
