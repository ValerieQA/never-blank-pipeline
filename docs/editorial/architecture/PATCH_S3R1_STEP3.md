# Patch S3-R1 to Step 3 (and one line in Step 2)

*21 September 2026 · response to GPT review "R2 ACCEPT; Step 3 ACCEPT WITH ONE REQUIRED PATCH" · no redesign*

**Files changed:** `04_STEP3_STORAGE_AND_RUN_TRACE.md`, `03_STEP2_STAGE_CONTRACTS.md` (S-14 ARP, S-07 config, producer table).
**Total:** 14 exact replacements. The new §3.6 is shown in full. In the file it sits after §3.5 (the insertion anchor below is the §3.5 heading; the section was then placed after §3.5 so that the numbering stays in order).

**New invariant S3-I1:** a successful external publication has durable idempotency evidence that does not depend on the learning-ledger commit. The run is not publication-complete until either a durable PublicationMarker is written, or an authoritative lookup can find the publication. An intent without a marker counts as possibly published: **at most once**.

**New architectural contradictions exposed:** none. Stage contracts are unchanged except that S-14's ARP now names the publication transaction, and S-07 knows that a destination without an idempotency authority can only be `generate_only`.

---

## Required patch S3-R1 · publication idempotency independent of the learning ledger

**1 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
### 3.5 Existing durable stores during coexistence
```

*After:*

```text
### 3.6 Publication idempotency authority (patch S3-R1)

A published post cannot be un-published. The guarantee "never publish the same thing twice" therefore cannot depend on the learning ledger, whose commit may fail (§3.1).

**Invariant S3-I1.** A successful external publication must have durable idempotency evidence **independent of whether the rest of the editorial ledger was committed**. A publication transaction is not complete until one of these holds:

- a durable **PublicationMarker** for it has been written; or
- another **authoritative** durable or external lookup can find the publication before the next publish attempt.

**The idempotency authority is separate from the learning ledger.** Fingerprints, RunSummaries, observations and labels are learning records; losing one loses information. The authority is what S-14 consults before any irreversible call; losing it could cause a double publication. The two are never the same write.

**Contract for S-14:**

1. **Identity.** Every publication has a **publication identity key**. At minimum it covers client, destination and the set of source signal IDs. The exact key is derived in Step 5 from the existing `WixPublicationIdentity` / `LinkedInPublicationIdentity`.
2. **Lookup before publish.** Before any external publish call, S-14 queries the authority for the key.
   - Found → no publish (reuse or `SKIP`, per existing idempotency rules).
   - **Authority unavailable** → `SKIP` publication (reason `idempotency_authority_unavailable`). Fail closed; no wait.
3. **Intent before the irreversible step.** S-14 durably records a `publication_intent` for the key **before** the external call.
4. **Marker after success.** After a successful call, S-14 writes the PublicationMarker. It contains the key, platform, external ID, URL, time, `run_id` and content digest. It is written **first and alone**, with its own retries, before and independently of the learning-ledger commit.
5. **Unconfirmed state.** If the marker cannot be made durable, the run records `publication_unconfirmed` for that key in its trace and in the RunSummary. The run still ends normally; nothing waits.
6. **Next run.** An intent without a marker means **possibly published**.
   - The next run treats the key as published unless an authoritative external lookup confirms that the publication does not exist.
   - Without such a confirmation, the destination is `SKIP` (reason `publication_possibly_exists`).
   - Semantics are **at most once**: a lost post is preferred to a duplicate.
   - Clearing an unconfirmed key is offline maintenance (I-02) or an automatic external confirmation. It never happens inside a run by assumption.
7. **Per-destination eligibility.** A destination may have `mode = publish` only if at least one idempotency authority exists for it: a durable marker store, or an external lookup that can find its posts. Otherwise S-07 must give it `generate_only`. This is a rule, not a model judgment (AD-02).

**What Step 5 decides** (implementation, not architecture):

- where markers and intents live: a dedicated committed path such as `data/editorial/publication_markers/<client>/<key>.json`, the existing `published_signal_ids.txt` / `PublishedEntry` if they can meet S3-I1, or another durable store;
- which platforms offer an authoritative external lookup (e.g. Wix by canonical slug or post ID);
- how the existing `find_prior_*` functions, which today scan run directories in the checkout (§0, finding 2), are re-pointed to the authority.

**Relation to the learning ledger.** The fingerprint of a published text still goes to the learning ledger (§3.2). If that commit fails, portfolio memory is incomplete; publication safety is not affected.

### 3.5 Existing durable stores during coexistence
```

**2 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
2. **Cross-run idempotency.** `find_prior_wix_publication` scans `reports/content_packages/<signal_id>/runs` in the checkout. Production run namespaces are not committed. From code reading, prior-run evidence is visible only if it happens to be in the checkout. **To verify in Step 5.** The durable ledger (§3) gives V-T05 and idempotency a durable source either way.
```

*After:*

```text
2. **Cross-run idempotency.** `find_prior_wix_publication` scans `reports/content_packages/<signal_id>/runs` in the checkout. Production run namespaces are not committed. From code reading, prior-run evidence is visible only if it happens to be in the checkout. **To verify in Step 5.** Publication idempotency is **not** delegated to the learning ledger: it has its own authority and invariant (§3.6, patch S3-R1).
```

**3 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
- A push failure after retries is recorded in the RunSummary as `ledger_commit: failed`. It does **not** undo publication, and it does not wait for a human. The run's workspace artifact still holds the records, and the next successful run's ledger step does **not** try to recover them. Recovery is an offline maintenance task (I-02).
```

*After:*

```text
- A push failure after retries is recorded in the RunSummary as `ledger_commit: failed`. It does **not** undo publication, and it does not wait for a human. The run's workspace artifact still holds the records, and the next successful run's ledger step does **not** try to recover them. Recovery is an offline maintenance task (I-02).
- **This applies to learning records only.** Publication idempotency never depends on this commit. It has its own authority, written first and alone (§3.6, invariant S3-I1).
```

**4 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
- **Runs are not resumable.** A crashed run is not continued. A new run gets a new `run_id`. Idempotency (V-T05, existing `idempotency.py`, fed from the ledger) prevents double publication.
```

*After:*

```text
- **Runs are not resumable.** A crashed run is not continued. A new run gets a new `run_id`. Double publication is prevented by the publication idempotency authority (§3.6): an intent without a marker counts as "possibly published" (at most once).
```

**5 · `03_STEP2_STAGE_CONTRACTS.md`**

*Before:*

```text
| **ARP** | Preflight `BLOCK` → `SKIP` publication (reason = blocking reason). Link target failed or skipped → omit the link (`DEGRADE`, recorded); the text is complete without it by construction. Prior identical publication found → reuse or `SKIP` per existing idempotency rules. Publisher error → `SKIP` publication with the error; no editorial retry |
```

*After:*

```text
| **ARP** | Preflight `BLOCK` → `SKIP` publication (reason = blocking reason). Link target failed or skipped → omit the link (`DEGRADE`, recorded); the text is complete without it by construction. Prior publication found by the **idempotency authority** → reuse or `SKIP` per existing idempotency rules. Authority unavailable → `SKIP` (`idempotency_authority_unavailable`). An intent without a marker from an earlier run → `SKIP` (`publication_possibly_exists`) unless an external lookup confirms no publication exists. Publisher error → `SKIP` publication with the error; no editorial retry. **Publication transaction** (Step 3 §3.6, invariant S3-I1): lookup → durable intent → external call → durable marker written first and alone, independent of the learning-ledger commit |
```

**6 · `03_STEP2_STAGE_CONTRACTS.md`**

*Before:*

```text
| E-16 | S-14 | S-00, S-07, S-08, S-09, S-13 (V-T05, V-S05) **of later runs**, S-15, label job | Yes (prior runs) |
```

*After:*

```text
| E-16 | S-14 | S-00, S-07, S-08, S-09, S-13 (V-T05, V-S05) **of later runs**, S-15, label job | Yes (prior runs) |
| Publication intent, PublicationMarker | S-14 (sole producer; Step 3 §3.6) | S-14 of later runs (lookup before publish); S-07 (publish-mode eligibility) | Yes (prior runs) |
```

**7 · `03_STEP2_STAGE_CONTRACTS.md`**

*Before:*

```text
| **Knowledge / config** | Tier 2 contract rules; tier 1 hard platform policy; release scope; cadence |
```

*After:*

```text
| **Knowledge / config** | Tier 2 contract rules; tier 1 hard platform policy; release scope; cadence; whether an idempotency authority exists for the destination (a destination without one can only be `generate_only`, Step 3 §3.6 rule 7) |
```

---

## RunSummary public-safe by construction

**1 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
| **RunSummary** | `data/editorial/runs/<client>/<yyyy-mm>/<run_id>.json` | Run harness, after S-14 | Indicators (skip/degrade rate by reason, replans, first-pass rate, cost per text) must outlive the 90-day workspace | Indefinite |
```

*After:*

```text
| **RunSummary** | `data/editorial/runs/<client>/<yyyy-mm>/<run_id>.json` | Run harness, after S-14 | Indicators (skip/degrade rate by state code and category, replans, first-pass rate, calls and tokens per text) must outlive the 90-day workspace. Public-safe by construction (§3.3) | Indefinite |
```

**2 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
- final state per scope (signal / unit / destination / publication): the ARP outcome, state code and reason;
```

*After:*

```text
- final state per scope (signal / unit / destination / publication): the ARP outcome, the machine **state code** and a **reason category** from a closed vocabulary. **No free-text reason**;
```

**3 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
- `ledger_commit` status.

It contains no text, excerpts or interpretations.
```

*After:*

```text
- `ledger_commit` status; `publication_unconfirmed` keys, if any (§3.6).

**Public-safe by construction** (patch S3-R1). A RunSummary never contains:

- text, excerpts or interpretations;
- money amounts or prices (only call and token counts);
- raw provider or publisher error messages (only an error category);
- free-text reasons;
- client-internal or risk-specific reasons beyond a closed category (e.g. `contract_risk`, not the risk itself).

Free-text reasons, raw errors and client-specific detail stay in the 90-day workspace trace. The RunSummary is therefore safe whether the repository stays public or the ledger later moves to private storage.
```

**4 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
| RunSummaries (outcomes, reasons, counts, costs); fingerprints
```

*After:*

```text
| RunSummaries (state codes, reason categories, call and token counts; no money, no free text, no raw errors); publication markers (key, platform, public URL / ID, time); fingerprints
```

**5 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
**Open for review (not an owner question unless it turns into one).** RunSummaries expose per-run cost and skip reasons publicly. If that is unacceptable, the ledger moves to private storage. The ledger's interface (one file per record, rebuildable indexes) does not change with the location. Only the commit mechanism does.
```

*After:*

```text
**Resolved by construction (patch S3-R1).** RunSummaries are public-safe (§3.3), so the public repository is not a blocker. If the ledger later moves to private storage, its interface (one file per record, rebuildable indexes) does not change; only the commit mechanism does.
```

---

## Rebase wording

**1 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
- Because every record is its own file (P4), a rebase never conflicts.
```

*After:*

```text
- Because every record is its own file (P4), concurrent runs normally avoid record-level content conflicts. `git rebase` / `push` can still fail for other reasons; that case is handled below.
```

---

## Retention: 90 days as target contract

**1 · `04_STEP3_STORAGE_AND_RUN_TRACE.md`**

*Before:*

```text
**Retention:** uploaded as one Actions artifact per run, 90 days, the same as `monday_publish.yml` today. Everything that must outlive 90 days is also written to the ledger (§3).
```

*After:*

```text
**Retention:** uploaded as one Actions artifact per run, **90 days (target contract)**, the same as `monday_publish.yml` today. `generate_and_publish.yml` keeps 30 days today; aligning it is a Step 5 migration delta, not an architecture question. Everything that must outlive 90 days is also written to the ledger (§3).
```

---

## Кратко по-русски (для Светы)

- **Закрыта дыра, которую нашёл GPT.** Раньше защита от двойной публикации опиралась на постоянный журнал, а его запись могла не пройти уже после публикации. Теперь это отдельная запись-метка «опубликовано». Она пишется первой и сама по себе, а перед публикацией ставится отметка о намерении. Если метка не записалась, следующий прогон считает, что пост, возможно, уже вышел, и не публикует его снова: лучше потерять пост, чем выпустить дубль.
- **Итоги прогонов в публичном журнале теперь безопасны по устройству.** В них нет денег, свободного текста причин и сырых ошибок, только коды и счётчики.
- **Мелочи.** Смягчена фраза про конфликты при слиянии. Срок хранения 90 дней закреплён как целевой, а выравнивание процессов отложено на шаг 5.
