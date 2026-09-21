# Step 3 · Storage and run trace

*Implementation architecture, step 3 of 6 · 21 September 2026 · entities: `01_STEP1_TYPED_ENTITIES.md` (patches R1, R2) · stage contracts: `03_STEP2_STAGE_CONTRACTS.md` (patch R2) · current-engine evidence read at `bdb8ac8`*

This document says **where every entity and trace record is stored, under which key, for how long, who may write it, and how a reader knows it is complete and untampered**. It consumes the rules fixed in Step 2, in particular the boundary commit (S-04). It does not invent new ones.

**Out of scope:** the knowledge register file format (Step 4); the migration order and cutover of current artifacts (Step 5). No implementation code.

---

## 0. What storage exists today (evidence)

| Store | Where | Durability | Written by |
|---|---|---|---|
| Run namespace: `research.json`, `decision.json`, `editorial_acceptance.json`, `generated.json`, `publication_results.json`, preflight | `reports/content_packages/<signal_id>/runs/<run_id>/` | **Ephemeral in production.** Uploaded as a GitHub Actions artifact: 90 days (`monday_publish.yml`), 30 days (`generate_and_publish.yml`). Not committed. The ~7 800 committed run files are test fixtures (`sig-test-001`, `sig-identity-test-001`) | `generate_and_publish.py` |
| Published index | `strategy/published_content_index.jsonl` (append-only, `PublishedEntry`) | Durable: committed by the workflow (`git pull --rebase`, commit `[skip ci]`, push) | S-14 equivalent |
| Published signal IDs | `data/research/published_signal_ids.txt` | Durable, committed | Workflow |
| Signal queue and research data | `data/research/*.jsonl` | Durable, committed | Research workflows |
| Legacy memory | `data/memory/*`, `src/internal/memory.py` files | Legacy path only | Legacy scripts |

**Properties worth keeping:**

- create-once, immutable artifacts per run;
- strict reload (`validate_json_for_research`, strict `DecisionPolicyRecord` reload);
- digests binding artifacts together (`research_artifact_digest`, `verify_run_provenance`);
- no prompts or secrets in artifacts (`stage_routing` stores request digests only).

**Two findings that shape this step:**

1. **Nothing the target needs across runs is durable today, except the published index.** Portfolio Memory (fingerprints), skip and degrade rates, deferred units, publication observations and the knowledge queue would all disappear with the 90-day artifact.
2. **Cross-run idempotency.** `find_prior_wix_publication` scans `reports/content_packages/<signal_id>/runs` in the checkout. Production run namespaces are not committed. From code reading, prior-run evidence is visible only if it happens to be in the checkout. **To verify in Step 5.** Publication idempotency is **not** delegated to the learning ledger: it has its own authority and invariant (§3.6, patch S3-R1).

---

## 1. Storage principles

| # | Principle | Source |
|---|---|---|
| P1 | **Create-once.** Every stored file is written once. A writer refuses to overwrite. Change = a new version file with `supersedes` | Step 1 §0.1; current practice |
| P2 | **The version is in the key.** File names carry the entity ID and version. A reader never guesses "the latest" by modification time | — |
| P3 | **Two tiers.** A run **workspace** (everything, ephemeral) and a durable **ledger** (only what later runs, indicators or learning need). The ledger is small and append-only | §0 finding 1 |
| P4 | **One file per durable record.** No shared append-only file in the ledger. Concurrent runs then never conflict on `git pull --rebase` | Current JSONL-append pattern conflicts at the file end under concurrency |
| P5 | **Derived indexes are disposable.** Any index over the ledger (e.g. fingerprints by client) is rebuilt by code from the records. It is never authoritative and never edited by hand | — |
| P6 | **Write ownership.** Each path pattern has exactly one writing stage (§2.3). That mirrors "one producer per version" (Step 2 §5.1) | Step 2 |
| P7 | **Strict reload.** Every reader validates schema version, run binding and digest before use, as `DecisionPolicyRecord` and the #58 artifact do today | Current practice |
| P8 | **No prompts, provider payloads or secrets anywhere.** Request digests only | `stage_routing` precedent |
| P9 | **The repository is public.** The ledger lives in the repository, so nothing goes into it that should not be public (§6) | Repository cloned without authentication |

---

## 2. Run workspace (tier 1)

### 2.1 Root and key

**Root:** `reports/editorial_runs/<run_id>/`

- The key is `run_id` (AD-04). Signal IDs are attributes in the manifest, not the directory key.
- The legacy root `reports/content_packages/<signal_id>/runs/<run_id>/` keeps holding the artifacts the existing lifecycle writes there: `research.json`, `decision.json` and the publication artifacts. The new manifest references them **by path and digest**. It does not copy them. This is the wrap relationship from Step 0. Moving them is a Step 5 decision.

**Retention:** uploaded as one Actions artifact per run, **90 days (target contract)**, the same as `monday_publish.yml` today. `generate_and_publish.yml` keeps 30 days today; aligning it is a Step 5 migration delta, not an architecture question. Everything that must outlive 90 days is also written to the ledger (§3).

### 2.2 Layout

```
reports/editorial_runs/<run_id>/
  manifest.json                          RunManifest (written last, §4.3)
  trace/
    <seq>_<stage>_<scope-key>.json       StageRecord, one per stage execution (§4.2)
  signal/
    selection.json                       E-01.selection (S-00)
    core/core.v<n>.json                  E-04 incl. E-02, E-03 (v1: S-01; v≥2: S-03)
    relevance.ref.json                   path + digest of legacy decision.json (S-01)
    features/features.v<n>.json          E-05 (v1: S-02; v≥2: S-03)
    assets/assets.v<n>.json              E-06 set (v1: S-02; v≥2: S-03)
    notes/material_notes.json            MaterialNotes (S-02)
    gaps/<gap_id>.json                   E-07 (S-03)
    boundary/
      interpretations/<int_id>.v<n>.json E-08 (S-04)
      boundary.v<n>.json                 E-09 (S-04) — the commit marker (§2.4)
  units/<unit_id>/
    unit.json                            E-10 (S-05)
    anchor/anchor.v<n>.json              E-11 (S-06)
    destinations/<destination>/
      decision.json                      E-12 (S-07)
      strategies/<candidate_set_id>/<str_id>.json   E-13 (S-08)
      strategies/<candidate_set_id>/selection.json  StrategySelection (S-09)
      plans/<plan_id>.v<n>.json          E-14 draft (S-10) / approved (S-11)
      verdicts/plan_<plan_id>.v<n>.json  PlanVerdict (S-11)
      texts/<txt_id>.v<n>.json           E-15 (S-12)
      verdicts/text_<txt_id>.v<n>.json   TextVerdict (S-13)
      publication.json                   package digests, preflight, result refs (S-14)
    b1/round_<k>.json                    V-P03 results per barrier round (S-11)
  fingerprints/<fp_id>.json              E-16, run copy (S-14)
```

*The tree is a layout specification, not code.*

### 2.3 Write ownership

| Path pattern | Only writer | Readers |
|---|---|---|
| `signal/selection.json` | S-00 | S-01, manifest |
| `signal/core/core.v1.json`, `relevance.ref.json` | S-01 | S-02 … S-14 |
| `signal/core/core.v≥2.json`, `features.v≥2`, `assets.v≥2`, `gaps/*` | S-03 | S-04 … S-14 |
| `features.v1`, `assets.v1`, `notes/*` | S-02 | S-03 |
| `signal/boundary/**` | S-04 | S-05 … S-13 |
| `units/*/unit.json` | S-05 | S-06, S-07 |
| `units/*/anchor/*` | S-06 | S-07 … S-13 |
| `destinations/*/decision.json` | S-07 | S-08 … S-14 |
| `strategies/*/<str_id>.json` | S-08 | S-09 |
| `strategies/*/selection.json` | S-09 | S-10, S-14 |
| `plans/*` with `stage_of_version = draft` | S-10 | S-11 |
| `plans/*` with `stage_of_version = approved`; `verdicts/plan_*`; `b1/*` | S-11 | S-12, S-13, S-14 |
| `texts/*` | S-12 | S-13, S-14 |
| `verdicts/text_*` | S-13 | S-12 (edit), S-14 |
| `publication.json`, `fingerprints/*` | S-14 | Ledger writer, S-15 |
| `trace/*` | The stage named in the file | Manifest, audits |
| `manifest.json` | Run harness, at the end | Everyone after the run |

A write outside a stage's patterns is a contract violation. It is detectable by comparing the StageRecord's `created_by.stage` with the path.

### 2.4 Boundary commit on disk (consumes Step 2, S-04)

The rule is fixed in Step 2. Storage implements it this way:

1. S-04 writes every **new** E-08 file first: a new record as `<int_id>.v1.json`, a reclassification as `<int_id>.v<n+1>.json` with `supersedes`.
2. S-04 writes `boundary.v<m+1>.json` **last**. It lists every member as an exact (`interpretation_id`, `version`) pair and carries the digest of each E-08 file it references.
3. **The E-09 file is the commit marker.** An E-08 version that no E-09 version references is invisible to every reader. If the process dies between steps 1 and 2, the orphan E-08 files are ignored, and the trace records an incomplete S-04 execution.
4. "The current boundary" = the highest `boundary.v<m>.json` whose referenced digests all verify.
5. Readers that decided against a boundary (E-11, E-13, PlanVerdict, TextVerdict) store `boundary_ref = m`. Invalidation after a commit is a code comparison of `boundary_ref` with the current `m`, and of the anchor's interpretation pair with its entry in `boundary.v<current>` (Step 2 §5.4 F-4).

### 2.5 Other version rules

| Entity | Version rule |
|---|---|
| E-04 core, E-05 features, E-06 assets | `v1` at S-01/S-02; `+1` per enrichment round at S-03. The core's `closed_gaps` lists the gaps whose closure produced the version |
| E-11 anchor | `+1` per S-06 re-entry. The old version is kept |
| E-14 plan | One ID per strategy attempt. `v1` = draft (S-10); `v2` = approved (S-11), `supersedes` v1. A rejected draft has no v2; its PlanVerdict records `fail` |
| E-15 text | One ID per approved plan. `+1` per edit (S-12). Every version has its own TextVerdict |
| E-13 strategies, StrategySelection, E-12, E-10 | Written once. A new S-08 attempt is a new `candidate_set_id`, not a new version |

---

## 3. Durable ledger (tier 2)

### 3.1 Root and commit mechanism

**Root:** `data/editorial/`, next to the existing durable `data/research/` and `data/strategy/`.

**Commit.** The same mechanism as `monday_publish.yml` today: `git pull --rebase --autostash`, add the run's new ledger files, commit `[skip ci]`, push, retry on a push race.

- Because every record is its own file (P4), concurrent runs normally avoid record-level content conflicts. `git rebase` / `push` can still fail for other reasons; that case is handled below.
- A push failure after retries is recorded in the RunSummary as `ledger_commit: failed`. It does **not** undo publication, and it does not wait for a human. The run's workspace artifact still holds the records, and the next successful run's ledger step does **not** try to recover them. Recovery is an offline maintenance task (I-02).
- **This applies to learning records only.** Publication idempotency never depends on this commit. It has its own authority, written first and alone (§3.6, invariant S3-I1).

### 3.2 Ledger records

| Record | Path | Written by | Why durable | Retention |
|---|---|---|---|---|
| **RunSummary** | `data/editorial/runs/<client>/<yyyy-mm>/<run_id>.json` | Run harness, after S-14 | Indicators (skip/degrade rate by state code and category, replans, first-pass rate, calls and tokens per text) must outlive the 90-day workspace. Public-safe by construction (§3.3) | Indefinite |
| **Fingerprint** (E-16) | `data/editorial/fingerprints/<client>/<yyyy-mm>/<fp_id>.json` | S-14 (ledger copy) | Portfolio Memory: S-00, S-07 cadence, S-08/S-09 pressure, V-T05, V-S05 | Indefinite |
| **Publication observation** (E-17) | `data/editorial/observations/<client>/<fp_id>/<pob_id>.json` | S-15 | Learning loop | Indefinite |
| **KnowledgeQueueItem** | `data/editorial/knowledge_queue/<item_id>.json` | **Two producers, split by item kind** (patch S4-R1). **S-15**: `observation` items (from E-17) and `vt02_feedback` items (V-T02 findings that matched no recorded interpretation, U-1, read from the run's TextVerdicts while the workspace is still retained). **Knowledge Maintenance job** (offline, scheduled, outside every run): `expiry_review` items. Each kind has exactly one producer | Keeper's offline queue | Until the keeper closes it; then kept with the decision |
| **Label record** | `data/editorial/labels/<client>/<lbl_id>.json` | Label job (asynchronous) | V-S06, V-S07 | Indefinite; optional |
| **Deferred unit** | `data/editorial/units/<client>/<unit_id>.json` | S-05 | Must survive until its expiry | Until expiry, then kept with the `expired` outcome. **No writer is enabled while cap = 1** |

**Deferred unit snapshot rule** (for when the cap is raised). The record embeds its own copies of the core and boundary versions it needs, because the originating workspace expires in 90 days. Before this writer is enabled, the public-repository rule (§6) must be re-checked, since a snapshot contains source excerpts.

### 3.3 RunSummary contents

A small record, enough to compute every indicator in map §11 without the workspace:

- `run_id`, client, signal IDs, unit IDs, code identity, configuration identity;
- final state per scope (signal / unit / destination / publication): the ARP outcome, the machine **state code** and a **reason category** from a closed vocabulary. **No free-text reason**;
- counters used versus limits (`L_enrich`, `L_boundary`, `L_anchor`, `L_strategy`, `L_edit`);
- model calls and tokens per stage; total against `RunCallBudget`;
- first-pass flags per destination (plan approved on attempt 1; text accepted on version 1);
- fingerprint IDs; publication results (platform, URL, external ID);
- `split_candidate` flag (for the AD-03 observation);
- count of V-T02 findings that matched no recorded interpretation (the U-1 feedback signal; the findings themselves go to the knowledge queue via S-15);
- workspace reference: Actions artifact name, expiry date, manifest digest;
- `ledger_commit` status; `publication_unconfirmed` keys, if any (§3.6).

**Public-safe by construction** (patch S3-R1). A RunSummary never contains:

- text, excerpts or interpretations;
- money amounts or prices (only call and token counts);
- raw provider or publisher error messages (only an error category);
- free-text reasons;
- client-internal or risk-specific reasons beyond a closed category (e.g. `contract_risk`, not the risk itself).

Free-text reasons, raw errors and client-specific detail stay in the 90-day workspace trace. The RunSummary is therefore safe whether the repository stays public or the ledger later moves to private storage.

### 3.4 Fingerprint storage rule

| Fingerprint of | Stored in the ledger |
|---|---|
| A **published** text | Full snapshot: features, strategy fields, adaptation, text profile, tie-breaker, publication reference, **and the text body**. The text is already public |
| A **`generate_only`** text | Everything **except the body**: features, strategy fields, adaptation, text profile, content digest, and a similarity sketch (a MinHash-style n-gram signature) that supports V-S05 without the text. The body stays only in the 90-day workspace |

This follows from P9: committing a `generate_only` body to a public repository would publish it by another route.

**Derived index.** `data/editorial/indexes/fingerprints_<client>.jsonl` may be rebuilt by code from the records for fast S-00 / S-07 / S-08 queries. It is not authoritative (P5) and is not committed if it can be rebuilt at run start in acceptable time. That choice is left to implementation.

### 3.5 Existing durable stores during coexistence

- `strategy/published_content_index.jsonl` (`PublishedEntry`): S-14 keeps appending it until Step 5 decides its fate. It is not the Portfolio Memory source; fingerprints are.
- `data/research/published_signal_ids.txt`: unchanged.
- **Legacy memory** (`data/memory/*`): not read or written by the target (verdict in Step 5).

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

---

## 4. Run trace (E-19)

### 4.1 Composition

E-19 is not one file. It is:

- the set of StageRecords (`trace/`);
- the entity files they reference;
- the manifest that binds them;
- the RunSummary in the ledger.

| E-19 part (Step 1) | Stored as |
|---|---|
| Header | `manifest.json` → `header`, copied from `RunContext` and `CodeIdentity` |
| Input versions | `manifest.json` → `inputs`: contract, Audience Profile, lens, knowledge register version (git commit of the register files), platform knowledge verification dates, reference library version, strength ladder ID. Each with a digest |
| Stage records | `trace/<seq>_<stage>_<scope-key>.json` |
| Outcome log | Inside each StageRecord (`outcomes[]`). The manifest holds the ordered index |
| Precedence log (U-3) | Inside each StageRecord (`precedence[]`). The manifest holds the ordered index |
| Check log | PlanVerdict and TextVerdict files. StageRecords reference them |
| Entity index | `manifest.json` → `entities[]`: type, ID, version, path, digest, writer stage |
| Integrity | `manifest.json` → `run_digest` over the sorted entity and trace digests |

### 4.2 StageRecord

One file per stage **execution**. A stage that runs again (a re-entry, a new attempt) writes a new StageRecord with a higher `seq`.

| Field | Content |
|---|---|
| `seq` | Monotonic within the run |
| `stage`, `scope_key` | e.g. `S-08`, `unit_…/linkedin/attempt_2` |
| `started_at`, `ended_at` | |
| `created_by` | StageAttribution |
| `inputs[]` | (entity type, ID, version, digest) |
| `outputs[]` | (entity type, ID, version, digest) |
| `routing` | The existing `stage_routing` evidence: routed record IDs and digests, request digests, contained / missing, **plus the label prohibition check** (AD-07) |
| `calls` | Count, tokens in and out, model identity; the `RunCallBudget` value before and after |
| `outcomes[]` | OutcomeRecords (scope, outcome, state code, reason, knowledge references, attempt / limit, route target) |
| `precedence[]` | PrecedenceApplications |
| `status` | `completed` / `failed_infrastructure` (the process error, recorded; the ARP outcome is in `outcomes`) |

### 4.3 Manifest and completeness

- The manifest is written **last**, by the run harness, after S-14 (or after the terminal `SKIP` of the signal or unit).
- A run directory **without** a manifest is `incomplete`. It is never read as a source by another run. Its partial files remain in the artifact for forensics.
- **Runs are not resumable.** A crashed run is not continued. A new run gets a new `run_id`. Double publication is prevented by the publication idempotency authority (§3.6): an intent without a marker counts as "possibly published" (at most once).

  *Rationale:* resumption would need mutable run state, which conflicts with P1. The cost of re-running is bounded by `RunCallBudget`.
- `verify_run_provenance` is extended to verify a manifest: every file digest matches, every StageRecord's outputs match the entity index, and the write ownership table (§2.3) holds.

### 4.4 What the trace proves

| Question | Answered from |
|---|---|
| Did a stage decide with the knowledge it claims? | StageRecord `routing` (contained / missing) + `inputs` |
| Was a label ever routed to S-00…S-13? | `routing.label_prohibition` |
| Why was this destination skipped? | `outcomes[]` in the stage that skipped it; mirrored in the RunSummary |
| Which rule won a conflict? | `precedence[]` |
| Was the text written against the current boundary? | TextVerdict `boundary_ref` against the latest committed `boundary.v<m>` |
| Did any stage write outside its paths? | Manifest entity index `writer stage` against §2.3 |
| What did the run cost, and where? | StageRecord `calls`; RunSummary totals |

---

## 5. How stages read what they need

| Stage | Reads from workspace | Reads from ledger / repo |
|---|---|---|
| S-00 | — | Fingerprints (portfolio pressure); deferred units (queue mode only, dormant) |
| S-01 … S-06 | Own run's earlier versions | Knowledge register (Step 4) |
| S-07 | Unit, anchor | Fingerprints (cadence per destination); destination capability; rollout scope (migration only); contract |
| S-08, S-09 | Unit, anchor, boundary, features, assets | Fingerprints (soft pressure); knowledge register |
| S-11 | Plans, boundary | Reference Library; fingerprints (V-P05) |
| S-13 | Text, plan, core, boundary | Fingerprints and published records (V-T05, V-S05) |
| S-14 | Accepted texts and verdicts | Fingerprints / publication records (idempotency) |
| S-15 | — | Published fingerprints |

A deferred unit re-entering (U-2, dormant) reads its **own snapshot** from the ledger, never an expired workspace.

---

## 6. Public repository rule

The repository is public. The ledger is committed to it. Therefore:

| Allowed in the ledger | Not allowed in the ledger |
|---|---|
| RunSummaries (state codes, reason categories, call and token counts; no money, no free text, no raw errors); publication markers (key, platform, public URL / ID, time); fingerprints of published texts including their bodies; fingerprints of `generate_only` texts **without** bodies; observations; knowledge queue items; labels | Unpublished text bodies; source excerpts (except deferred-unit snapshots, which stay disabled until re-checked); prompts; provider payloads; credentials; the client's internal data cleared for use but not for publication |

**Resolved by construction (patch S3-R1).** RunSummaries are public-safe (§3.3), so the public repository is not a blocker. If the ledger later moves to private storage, its interface (one file per record, rebuildable indexes) does not change; only the commit mechanism does.

---

## 7. Budget and performance notes

- Storage adds **no model calls**.
- The ledger grows by one RunSummary per run plus one fingerprint per accepted text: a few KB each, except published bodies.
- Portfolio queries scan the client's fingerprints within a window. The derived index (§3.4) makes that fast. Its rebuild cost is linear in the number of fingerprints.

---

## Кратко по-русски (для Светы)

- **Как сейчас.** Всё, что движок делает за прогон, хранится 90 дней как вложение к запуску на GitHub, а потом исчезает. Надолго сохраняется только список опубликованного. Новой системе этого мало: память портфеля, доля пропусков и отзывы площадок должны жить дольше.
- **Решение: два уровня.**
  - **Рабочая папка прогона.** Хранит всё, 90 дней, как сейчас.
  - **Небольшой постоянный журнал в репозитории.** Итог каждого прогона, «отпечатки» текстов, наблюдения за публикациями, очередь для хранителя знаний. Каждая запись — отдельный файл, чтобы параллельные прогоны не мешали друг другу.
- **Каждый файл пишется один раз и больше не меняется.** За каждое место в папке отвечает ровно одна стадия. В конце прогона собирается опись с контрольными суммами, так что подмену или пропуск видно.
- **Важно: репозиторий публичный.** Поэтому в постоянный журнал не попадают неопубликованные тексты и цитаты из источников. Отпечатки текстов для четырёх площадок, которые готовятся, но не публикуются, хранятся без самого текста. Если публичность итогов прогона (стоимость, причины пропусков) нежелательна, журнал можно перенести в закрытое хранилище, устройство от этого не меняется.
- **Попутная находка для шага 5.** Судя по коду, защита от повторной публикации смотрит только на прогоны, лежащие в текущей копии репозитория, а рабочие прогоны туда не попадают. Это надо проверить.
