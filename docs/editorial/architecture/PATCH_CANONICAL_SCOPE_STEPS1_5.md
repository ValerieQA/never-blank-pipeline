# Patch CANONICAL-SCOPE to Steps 1–5 (and Step 0)

*21 September 2026 · response to owner and GPT: "STOP BEFORE STEP 6. Architecture drift found in review" · binding principles A (one canonical Editorial Core) and B (six sibling destinations)*

## What went wrong

Two things leaked from **AS-IS** into **target** architecture:

1. **The current release scope.** `R1_PUBLISH_CHANNELS = Wix + LinkedIn` was used as an input that controls the target (S-07, S-14, AD-02). It is a fact about today's release, not a product constraint.
2. **The current weekday workflows.** Monday, Fri/Sun and Wednesday became the target cutover units in Step 5. They are an inventory of today's engine, not future paths.

Step 1 was already multi-destination (E-12 lists six destinations). The stage chain S-00…S-15, storage and the knowledge register are day-agnostic. **The drift was in scope wording and in the Step 5 migration model, not in the core architecture.**

## Binding principles now applied

- **A · One canonical Editorial Core.** `signal → evidence → interpretation → editorial unit → strategy → destination plan → text → validation → publication`. Weekday, rubric and lens are configuration inputs only. One canonical run is made to work end to end; the same engine is then reused by configuration.
- **B · Six sibling destinations:** Wix, LinkedIn, Facebook, Instagram, Threads, Telegram. `generate_only` is only a temporary rollout state.
- **New distinction** (AD-02, Step 2 S-07/S-14): **destination capability** (target; a destination is capable when it has publisher, package, preflight, idempotency authority and collector) versus **rollout scope** (a temporary deployment setting; its AS-IS value is `R1_PUBLISH_CHANNELS`).
- **Step 5 §3 rewritten:** migration by **capability** (C0 safety → C1 infrastructure → C2–C4 canonical chain in shadow for all six → C5 per-destination publication capability → C6 canonical run live as the only publisher → C7 reuse by configuration → C8 removal). Current workflows are **repointed or retired**, never migrated as paths.
- **The budget problem stays real and measured.** Normal about 61 calls for six destinations against 40 today. It is solved by measurement and optimization, never by shrinking scope.

## Current path → contribution → how it enters the one canonical engine

| Current path (AS-IS) | What it contributes | Retire or repoint |
|---|---|---|
| Monday (dispatch only) | Signal selection with role judgment; due check; the Monday stream contract as client configuration | Repoint the schedule (if wanted) to the canonical engine with that configuration; Monday stages disabled |
| Research Fri/Sun | #58 Lens → S-01 relevance screen; an automatic schedule | Repoint the schedule; the inline selector is replaced by S-00 |
| Wednesday | RSS signal supply → a signal source for S-00 | Repoint the schedule; July modules disabled |
| Visibility Tue/Thu | Curated item queue → a signal source | Repoint into S-00, or retire |
| Legacy scheduled Friday | Proof that the six-channel publishers work; nothing editorial | Retire (#144); six-channel reach becomes capability C5 with canonical gates |
| Daily research Stage 11 | Signal discovery and scoring → the S-00 source | Keep discovery; retire its publishing step |
| Manual legacy workflows | Tooling | Retire; the image step is reused inside the canonical run |

## Classification of every occurrence

Every line in Steps 0–5 (as they stood before this patch) that mentions a weekday, `R1_PUBLISH_CHANNELS` / release scope, Wix + LinkedIn-only publication, R1, or a legacy workflow or path.

- **1** = AS-IS evidence.
- **2** = migration compatibility (temporary).
- **3** = target architecture. **3 — LEAK** marks a line where category 1 or 2 had leaked into the target; every one of those is corrected.

Patch-name matches ("patch R1", "S3-R1") are excluded.

| Step | Line | Passage (before) | Category | Action |
|---|---|---|---|---|
| 00 | 7 | **Short answer.** `main` has not changed any code, configuration, client document or workflow since `87ea0f4`. | 1 AS-IS | unchanged |
| 00 | 32 | / `reports/research_2026-09-21.json` / **Irrelevant to the architecture.** It is a daily output of the legacy  | 1 AS-IS | unchanged |
| 00 | 42 | / A1 / The Monday path runs Pattern Extractor → Decision Lens Lite → Spine → Hook → Reader Context → Discovery | 1 AS-IS | unchanged |
| 00 | 48 | / A7 / "Differentiation: legacy path only" / **Valid, extended** / `src/internal/memory.py` (embeddings, theme | 1 AS-IS | unchanged |
| 00 | 50 | / A9 / The LinkedIn text is recomposed from the accepted article, with a fidelity judge / **Valid, incomplete* | 1 AS-IS | unchanged |
| 00 | 51 | / A10 / The run can be described as a single article-then-derivatives flow / **Incomplete** / R1 **publishes** | 1 AS-IS (annotated with Step 5 correction) | corrected |
| 00 | 85 | The REPO_TRACK names only Decision Lens **Lite**, a Monday pipeline stage. There is also a separate typed gate | 1 AS-IS | unchanged |
| 00 | 119 | / `release_scope.py`: `R1_PUBLISH_CHANNELS = (wix, linkedin)` / The **release scope** is an input to S-07 (see | 3 target — LEAK | corrected |
| 00 | 122 | / `package.py`: frozen Wix and LinkedIn packages; `bind_canonical_article_url` / **Reuse** for the publication | 1 AS-IS | unchanged |
| 00 | 138 | 5. R1 publishes only Wix and LinkedIn. Every slice must keep that true until the release scope is changed deli | 3 target — LEAK | corrected |
| 01 | 97 | / E-12 / Destination decision / S-07 / `release_scope`, packages / **New**, uses release scope / | 3 target — LEAK | corrected |
| 01 | 98 | / E-13 / Editorial Strategy / S-08, S-09 / scattered over the Monday stages and `_BLOCK_TABLE` / **Rebuild** / | 1 AS-IS | unchanged |
| 01 | 346 | / `mode` / publish / generate_only / if eligible / From the release scope. Today only `wix` and `linkedin` are | 3 target — LEAK | corrected |
| 01 | 561 | / Final reuse / wrap / disable / rebuild verdict per current component, including the #58 gate, legacy memory  | 2 migration | unchanged |
| 02 | 43 | 3. **Mode.** Each eligible destination gets a mode: `publish` or `generate_only`. The mode comes from the rele | 3 target — LEAK | corrected |
| 02 | 56 | **Change to Canonical Map v1.** In the S-07 row, the decider changes from "Model + contract" to "Code (contrac | 3 target — LEAK | corrected |
| 02 | 120 | / **AD-05** / E-02, E-03 and E-04 **wrap** the existing research contract (`SupportReference`, `ExtractedEvide | 1 AS-IS | unchanged |
| 02 | 125 | / **AD-10** / Strength is a position on **one ordered ladder per run**: the client's declared ladder (`claim_s | 1 AS-IS | unchanged |
| 03 | 77 | / `RunCallBudget` / run / existing ceiling (R1: 40) / Every model call / See §0.4 / | 3 target — LEAK | corrected |
| 03 | 138 | / **Modes** / *Assigned* (current R1: the run starts with one `--signal-id`; S-00 accepts or skips it). *Queue | 1 AS-IS (reworded day-agnostic) | corrected |
| 03 | 150 | / **Seam** / **Wrap:** `source_eligibility.judge_source_eligibility`, `ContentAssignment`, `RunContext`. **New | 2 migration | unchanged |
| 03 | 190 | / **Seam** / **New.** Replaces nothing directly. The Monday Pattern Extractor made a comparable judgment witho | 1 AS-IS | unchanged |
| 03 | 287 | / **Inputs** / `E-10`, `E-11` (required: the topic and risk facts come from the core and boundary); Client Con | 3 target — LEAK | corrected |
| 03 | 292 | / **Knowledge / config** / Tier 2 contract rules; tier 1 hard platform policy; release scope; cadence; whether | 3 target — LEAK | corrected |
| 03 | 298 | / **Seam** / **Reuse:** `release_scope.py` as the mode source / | 3 target — LEAK | corrected |
| 03 | 345 | / **Inputs** / Chosen `E-13` (required); `E-12` (mode, dependencies); `K-DST-*` (tiers 1 and 4); Client Contra | 3 target — LEAK | corrected |
| 03 | 458 | / **Seam** / **Reuse:** `package.py` (including `bind_canonical_article_url`), `preflight.py`, `idempotency.py | 3 target — LEAK | corrected |
| 03 | 459 | / **Publication** / Only `publish` mode reaches external platforms. Today only Wix and LinkedIn, in that order | 3 target — LEAK | corrected |
| 03 | 526 | 1. **Queue mode only.** In assigned mode (current R1), S-00 evaluates the one given signal. Deferred units are | 1 AS-IS (reworded day-agnostic) | corrected |
| 03 | 700 | / D / Min / Normal / Worst / Current R1 ceiling / | 1 AS-IS | unchanged |
| 03 | 702 | / 2 (Wix + LinkedIn only) / 20 / 27 / 79 / 40 / | 3 target — LEAK | corrected |
| 04 | 15 | / Run namespace: `research.json`, `decision.json`, `editorial_acceptance.json`, `generated.json`, `publication | 1 AS-IS | unchanged |
| 04 | 19 | / Legacy memory / `data/memory/*`, `src/internal/memory.py` files / Legacy path only / Legacy scripts / | 1 AS-IS | unchanged |
| 04 | 58 | - The legacy root `reports/content_packages/<signal_id>/runs/<run_id>/` keeps holding the artifacts the existi | 2 migration | unchanged |
| 04 | 60 | **Retention:** uploaded as one Actions artifact per run, **90 days (target contract)**, the same as `monday_pu | 1 AS-IS | unchanged |
| 04 | 72 | relevance.ref.json path + digest of legacy decision.json (S-01) | 2 migration | unchanged |
| 04 | 150 | **Commit.** The same mechanism as `monday_publish.yml` today: `git pull --rebase --autostash`, add the run's n | 1 AS-IS | unchanged |
| 04 | 209 | - **Legacy memory** (`data/memory/*`): not read or written by the target (verdict in Step 5). | 1 AS-IS | unchanged |
| 04 | 317 | / S-07 / Unit, anchor / Fingerprints (cadence per destination); release scope; contract / | 3 target — LEAK | corrected |
| 06 | 9 | - fixes the coexistence and cutover order that moves production to the target without breaking R1. | 3 target — LEAK | corrected |
| 06 | 25 | / **Monday** / `monday_publish.yml`: **dispatch only**; cron commented out (L20-37) / `generate_and_publish.py | 1 AS-IS | unchanged |
| 06 | 26 | / **Wednesday** / `wednesday_golden.yml`: cron Wed 08:17/09:17 UTC / Same entrypoint → frozen July modules (`s | 1 AS-IS | unchanged |
| 06 | 27 | / **Research Fri/Sun** / `research_generate_and_publish.yml`: cron `0 7 * * 5,0` / Same entrypoint, **no role* | 1 AS-IS | unchanged |
| 06 | 28 | / **Visibility Tue/Thu** / `visibility_publish.yml`: cron Tue, Thu 07:00 / `generate_and_publish_visibility.py | 1 AS-IS | unchanged |
| 06 | 29 | / **Scheduled Friday (legacy)** / `scheduled_publish.yml`: cron Fri 08:17/09:17 UTC; "legacy until #144" (L9)  | 1 AS-IS | unchanged |
| 06 | 30 | / Daily research Stage 11 / `daily_signal_research.yml`: daily cron; publishing only if secret `NB_RESEARCH_PU | 1 AS-IS | unchanged |
| 06 | 34 | 1. **Step 0, assumption A10** ("R1 publishes only Wix and LinkedIn") is **partly wrong**. The canonical entryp | 1 AS-IS | corrected |
| 06 | 35 | 2. **Two automatic publishers run on Friday** (research 07:00 UTC, scheduled 08:17/09:17 UTC), and `scheduled_ | 1 AS-IS | corrected |
| 06 | 46 | / Production workflows only **upload** run namespaces as artifacts. None downloads prior artifacts. The "Mark  | 1 AS-IS | unchanged |
| 06 | 50 | / **The real authority today is `data/research/published_signal_ids.txt`,** by signal ID. It is read by `selec | 1 AS-IS | unchanged |
| 06 | 51 | / **Hole: partial success.** The signal is marked only when the whole job succeeds (`success()`, `monday:329`, | 1 AS-IS | unchanged |
| 06 | 59 | / **Authority store** / Committed `data/editorial/publication_markers/<client>/<destination>/<key>.json`: one  | 1 AS-IS | unchanged |
| 06 | 71 | / Both existing roles (`never-blank-monday-documented-case`, `never-blank-wednesday-golden`) are `role_bounded | 1 AS-IS | unchanged |
| 06 | 72 | / **Only research Fri/Sun uses #58 in production** (no `--editorial-role`) / VERIFIED / | 1 AS-IS | unchanged |
| 06 | 73 | / Reason for the bypass: the Lens's audience-transfer rules predate the corrected Monday strategy (`generate_a | 1 AS-IS | unchanged |
| 06 | 83 | - **`DecisionPolicyRecord` → keep for legacy paths during coexistence; DISABLE for target runs.** A target run | 1 AS-IS | corrected |
| 06 | 85 | ### 1.3 Legacy memory | 1 AS-IS | unchanged |
| 06 | 90 | / **`generate.py` is live every Friday** through `scheduled_publish.py` (L229-241), besides the dispatch-only  | 1 AS-IS | unchanged |
| 06 | 91 | / `data/memory/{published,embeddings,portfolio,theme_registry,…}.json` do not exist in the repository; the wor | 1 AS-IS | unchanged |
| 06 | 94 | **Verdict: DISABLE with the legacy Friday path** (retired or moved per #144; §3 Phase 5). **Not reused** for P | 1 AS-IS | corrected |
| 06 | 117 | / The uploads that hold run namespaces are already **90 days**: Monday L375, Wednesday L247, research L217 / V | 1 AS-IS | unchanged |
| 06 | 118 | / `generated-<sid>` uploads (Monday L393-399, research L219-225) set **no** `retention-days`: the repository d | 1 AS-IS | unchanged |
| 06 | 119 | / Below 90: scheduled Friday report 7; daily research 7; smoke test 7; `generate_and_publish.yml`, `publish.ym | 1 AS-IS | unchanged |
| 06 | 121 | **Correction to Step 3 §0 / §2.1.** The 30-day workflow named there (`generate_and_publish.yml`) is a manual l | 1 AS-IS | unchanged |
| 06 | 134 | / `src/run/decision_policy.py` / **Keep (legacy) → Disable** / — / Legacy paths only; removed with the last on | 2 migration | unchanged |
| 06 | 136 | / `src/artifacts/__init__.py` (writers, `resolve_run_dir`) / **Wrap** / Workspace writer with create-once and  | 2 migration | unchanged |
| 06 | 146 | / **Monday editorial path** /// | 2 migration (reworded) | corrected |
| 06 | 147 | / `pattern_extractor.py`, `decision_lens_lite.py`, `narrative_spine.py`, `hook_engine.py`, `reader_context.py` | 2 migration | unchanged |
| 06 | 156 | / `editorial_role.py` / **Wrap** / Client/stream configuration / `decision_policy` field retired with legacy / | 2 migration | unchanged |
| 06 | 158 | / `src/never_blank/wednesday_*`, `wednesday_july/*` / **Disable** at Wednesday cutover / — / Frozen July modul | 2 migration (reworded) | corrected |
| 06 | 160 | / `src/content/generator.py`, `scripts/generate.py`, `scripts/scheduled_publish.py`, `scripts/publish.py` (leg | 2 migration (reworded) | corrected |
| 06 | 167 | / **Legacy memory and quality** /// | 2 migration | unchanged |
| 06 | 168 | / `src/internal/*`, `src/quality/*`, `src/content/differentiation.py`, `src/content/matrix.py` / **Disable** w | 2 migration (reworded) | corrected |
| 06 | 170 | / `package.py`, `preflight.py`, `result.py`, `canonical_url.py`, `formatting.py`, `hashtags.py`, `release_scop | 2 migration (reworded) | corrected |
| 06 | 179 | / `monday_publish.yml`, `wednesday_golden.yml`, `research_generate_and_publish.yml` / **Wrap** / Target run ha | 2 migration (reworded) | corrected |
| 06 | 180 | / `scheduled_publish.yml`, `generate_and_publish.yml`, `publish.yml`, `generate_content.yml` / **Disable** wit | 2 migration (reworded) | corrected |
| 06 | 190 | - R1 production keeps publishing throughout. | 2 migration (section rewritten) | corrected |
| 06 | 191 | - Each path switches independently behind a per-path engine flag (`legacy` / `target-shadow` / `target`). | 3 target | corrected |
| 06 | 202 | / 0.3 / Put `scheduled_publish.yml` in the shared publish concurrency group / Two Friday publishers today / | 3 target — LEAK | corrected |
| 06 | 203 | / 0.4 / **Legacy Friday six-channel publishing:** either restrict it to `R1_PUBLISH_CHANNELS` or retire the pa | 3 target — LEAK | corrected |
| 06 | 214 | R1 outputs are unchanged. | 2 migration (section rewritten) | corrected |
| 06 | 218 | - S-00 … S-05 run in a **separate shadow job** on the saved research artifact of real R1 runs: no new retrieva | 2 migration (section rewritten) | corrected |
| 06 | 224 | S-06 … S-11 in the shadow job for Wix and LinkedIn: plans and verdicts, no prose. | 3 target | corrected |
| 06 | 229 | - Target texts sit side by side with the R1 texts for the same signals. | 2 migration (section rewritten) | corrected |
| 06 | 236 | / 1 / **Monday** / Dispatch-only today (cron paused), so a cutover run is started deliberately and has the low | 3 target — LEAK | corrected |
| 06 | 237 | / 2 / **Research Fri/Sun** / Automatic twice weekly, same entrypoint and the same Monday pipeline; already on  | 3 target — LEAK | corrected |
| 06 | 238 | / 3 / **Wednesday** / Different editorial code (frozen July modules) and its own signal supply; the most disti | 3 target — LEAK | corrected |
| 06 | 239 | / 4 / **Legacy Friday** / Retired or re-pointed to a canonical path (#144). Legacy memory, the generator and t | 3 target — LEAK | corrected |
| 06 | 244 | 1. `legacy` → `target-shadow`: the target runs beside legacy in the same slot, `generate_only`. | 3 target | corrected |
| 06 | 245 | 2. `target-shadow` → `target`: the target publishes, legacy is off. | 3 target | corrected |
| 06 | 247 | The step from 1 to 2 needs the acceptance criteria that Step 6 defines per slice. During the switch, the marke | 3 target | corrected |
| 06 | 253 | - the Monday stages, `plan_decisions`, LinkedIn recomposition; | 2 migration (section rewritten) | corrected |
| 06 | 254 | - the Wednesday July modules; | 2 migration (section rewritten) | corrected |
| 06 | 258 | - the legacy generator and memory. | 3 target | corrected |
| 06 | 264 | 1. R1 publishes only through the canonical publishers, in Wix → LinkedIn order. | 3 target — LEAK | corrected |
| 06 | 267 | 4. No shadow job publishes or consumes R1's call budget. | 2 migration (section rewritten) | corrected |
| 06 | 275 | / Step 0, A10 / Corrected: legacy scheduled Friday publishes to six channels (§0) / | 1 AS-IS (moved into the patch record) | corrected |
| 06 | 276 | / Step 0 §4 / A7 / Legacy memory is live on Fridays through `scheduled_publish.py`, not "legacy only" / | 1 AS-IS (moved into the patch record) | corrected |
| 06 | 277 | / Step 3 §0 / §2.1 / The 30-day retention example referred to a manual legacy workflow; canonical run namespac | 3 target | corrected |
| 06 | 286 | 1. **Legacy Friday publishes to Facebook, Instagram, Threads and Telegram** every Friday it runs, against the  | 1 AS-IS (kept in §0/§1; removed from target review items) | corrected |

**Totals:** 100 occurrences; 23 classified as leaks, all corrected; the rest kept as AS-IS or migration context.

## Exact before → after changes

A unified diff per file, against the state before this correction. Lines starting with `-` are before, lines starting with `+` are after. This includes the earlier product-frame edits made in the same correction pass.

### 00_STEP0_ARCHITECTURE_IMPACT_DELTA.md

```diff
--- before/00_STEP0_ARCHITECTURE_IMPACT_DELTA.md
+++ after/00_STEP0_ARCHITECTURE_IMPACT_DELTA.md
@@ -51 +51 @@
-| A10 | The run can be described as a single article-then-derivatives flow | **Incomplete** | R1 **publishes** only Wix and LinkedIn. Facebook, Instagram, Threads and Telegram are generated and packaged, but not published (`R1_PUBLISH_CHANNELS`, #227) |
+| A10 | The run can be described as a single article-then-derivatives flow | **Incomplete** | *(AS-IS; later corrected in Step 5 §0: the legacy scheduled Friday path posts to all six channels.)* R1 **publishes** only Wix and LinkedIn. Facebook, Instagram, Threads and Telegram are generated and packaged, but not published (`R1_PUBLISH_CHANNELS`, #227) |
@@ -119 +119 @@
-| `release_scope.py`: `R1_PUBLISH_CHANNELS = (wix, linkedin)` | The **release scope** is an input to S-07 (see ADR OPEN-15). Generation for the other four destinations can run without publication |
+| `release_scope.py`: `R1_PUBLISH_CHANNELS = (wix, linkedin)` | **AS-IS fact** about the current production release, not a target constraint. In the target it survives only as the migration-time **rollout scope** (which destination capabilities are switched on in a deployment). Target destinations are all six (patch CANONICAL-SCOPE) |
@@ -138 +138 @@
-5. R1 publishes only Wix and LinkedIn. Every slice must keep that true until the release scope is changed deliberately.
+5. Current production (R1) publishes only through the canonical publishers for Wix and LinkedIn (one legacy path excepted, Step 5 §0). No slice may break current production while the canonical engine is built. The **target** is one canonical engine publishing to all six sibling destinations; destinations are enabled capability by capability (Step 5 §3), not by keeping Wix + LinkedIn as the product scope.
```

### 01_STEP1_TYPED_ENTITIES.md

```diff
--- before/01_STEP1_TYPED_ENTITIES.md
+++ after/01_STEP1_TYPED_ENTITIES.md
@@ -97 +97 @@
-| E-12 | Destination decision | S-07 | `release_scope`, packages | **New**, uses release scope |
+| E-12 | Destination decision | S-07 | Publishers and packages (AS-IS: packages exist only for Wix, LinkedIn) | **New**. Target: all six destinations. The current `release_scope` is used only as the migration-time rollout scope |
@@ -346 +346 @@
-| `mode` | publish / generate_only | if eligible | From the release scope. Today only `wix` and `linkedin` are `publish` |
+| `mode` | publish / generate_only | if eligible | `publish` when the contract enables the destination, it is capable, and the rollout scope includes it (AD-02). Target: all six publish. `generate_only` is a temporary migration state, or a contract choice |
```

### 02_ARCHITECTURE_DECISIONS.md

```diff
--- before/02_ARCHITECTURE_DECISIONS.md
+++ after/02_ARCHITECTURE_DECISIONS.md
@@ -43 +43,4 @@
-3. **Mode.** Each eligible destination gets a mode: `publish` or `generate_only`. The mode comes from the release scope; today only Wix and LinkedIn are `publish` (`R1_PUBLISH_CHANNELS`).
+3. **Mode: target capability versus rollout scope.** Two separate inputs decide the mode. They must never be confused.
+   - **Destination capability (target architecture).** The target supports six sibling destinations: Wix, LinkedIn, Facebook, Instagram, Threads, Telegram. A destination is **capable** when it has a publisher, package, preflight, an idempotency authority (Step 3 §3.6) and a metrics collector.
+   - **Rollout scope (migration compatibility, temporary).** A deployment setting listing which capable destinations are switched on for publishing. During migration and shadow it may be narrower. The current `R1_PUBLISH_CHANNELS` (Wix + LinkedIn) is an **AS-IS fact** about today's release, not a target constraint.
+   - A destination is `publish` when the client contract enables it, it is capable, and the rollout scope includes it. Otherwise it is `generate_only`, **as a temporary migration state**. The finished canonical run publishes to all six (owner product frame, patch CANONICAL-SCOPE).
@@ -56 +59 @@
-**Change to Canonical Map v1.** In the S-07 row, the decider changes from "Model + contract" to "Code (contract, platform policy, release scope, cadence)". `K-DST-*` knowledge moves from S-07 to S-08 and S-10, where it already acts.
+**Change to Canonical Map v1.** In the S-07 row, the decider changes from "Model + contract" to "Code (contract, platform policy, destination capability, rollout scope, cadence)". `K-DST-*` knowledge moves from S-07 to S-08 and S-10, where it already acts.
```

### 03_STEP2_STAGE_CONTRACTS.md

```diff
--- before/03_STEP2_STAGE_CONTRACTS.md
+++ after/03_STEP2_STAGE_CONTRACTS.md
@@ -60,5 +60,3 @@
-1. `publish` destinations before `generate_only` destinations;
-2. within `publish`, the order of `publication_dependencies`: today Wix before LinkedIn, because LinkedIn links to Wix;
-3. otherwise the Client Contract's listed order.
-
-Under a tight budget, the destinations that are actually published are protected first.
+1. the order of `publication_dependencies`: a destination that others link to goes first (with the default Client Contract, Wix, because the social posts may link to the article);
+2. otherwise the Client Contract's listed order;
+3. during migration only: `publish` destinations before `generate_only` ones, so that under a tight budget the destinations that are actually published are protected first.
@@ -77 +75 @@
-| `RunCallBudget` | run | existing ceiling (R1: 40) | Every model call | See §0.4 |
+| `RunCallBudget` | run | Sized for the six-destination canonical run from shadow measurements (§6). AS-IS: the current engine's ceiling is 40 | Every model call | See §0.4 |
@@ -138 +136 @@
-| **Modes** | *Assigned* (current R1: the run starts with one `--signal-id`; S-00 accepts or skips it). *Queue* (future: S-00 picks one candidate from signals and non-expired deferred units, per U-2) |
+| **Modes** | *Assigned* (the run starts with one signal; S-00 accepts or skips it. This is also how the current engine starts runs). *Queue* (future: S-00 picks one candidate from signals and non-expired deferred units, per U-2) |
@@ -287 +285 @@
-| **Inputs** | `E-10`, `E-11` (required: the topic and risk facts come from the core and boundary); Client Contract destination settings (required); hard platform policy records (`K-DST-*` at tier 1 only); release scope (`R1_PUBLISH_CHANNELS`); cadence state from prior E-16 |
+| **Inputs** | `E-10`, `E-11` (required: the topic and risk facts come from the core and boundary); Client Contract destination settings (required); hard platform policy records (`K-DST-*` at tier 1 only); **destination capability** (target: six destinations, AD-02); **rollout scope** (migration-time deployment setting; AS-IS value `R1_PUBLISH_CHANNELS` = Wix + LinkedIn); cadence state from prior E-16 |
@@ -292 +290 @@
-| **Knowledge / config** | Tier 2 contract rules; tier 1 hard platform policy; release scope; cadence; whether an idempotency authority exists for the destination (a destination without one can only be `generate_only`, Step 3 §3.6 rule 7) |
+| **Knowledge / config** | Tier 2 contract rules; tier 1 hard platform policy; destination capability; rollout scope (temporary); cadence; whether an idempotency authority exists for the destination (a destination without one can only be `generate_only`, Step 3 §3.6 rule 7) |
@@ -298 +296 @@
-| **Seam** | **Reuse:** `release_scope.py` as the mode source |
+| **Seam** | **Wrap:** `release_scope.py` becomes the rollout-scope setting during migration only. The target mode source is capability × contract × rollout scope (AD-02). When all six destinations are capable and enabled, the rollout scope equals the contract's destinations and can be removed |
@@ -345 +343 @@
-| **Inputs** | Chosen `E-13` (required); `E-12` (mode, dependencies); `K-DST-*` (tiers 1 and 4); Client Contract: voice document, forbidden phrases and constructions, fixed slots such as `ending_mode` treated as constraints; release scope |
+| **Inputs** | Chosen `E-13` (required); `E-12` (mode, dependencies); `K-DST-*` (tiers 1 and 4); Client Contract: voice document, forbidden phrases and constructions, fixed slots such as `ending_mode` treated as constraints; the destination's mode from E-12 |
@@ -458,2 +456,2 @@
-| **Seam** | **Reuse:** `package.py` (including `bind_canonical_article_url`), `preflight.py`, `idempotency.py`, the publishers, `release_scope.py`, `verify_run_provenance`. **New:** fingerprint writer. `PublishedEntry` stays as the publication index |
-| **Publication** | Only `publish` mode reaches external platforms. Today only Wix and LinkedIn, in that order |
+| **Seam** | **Reuse:** `package.py` (including `bind_canonical_article_url`), `preflight.py`, `idempotency.py`, the publishers for all six destinations, `verify_run_provenance`. **Extend:** packages and preflight exist today only for Wix and LinkedIn; they are extended to Facebook, Instagram, Threads, Telegram. **New:** fingerprint writer. `PublishedEntry` stays as the publication index |
+| **Publication** | `publish` mode reaches external platforms. **Target: all six destinations**; during migration, only those in the rollout scope (AD-02). Wix is published first, because the other destinations may link to it (conditional link, R-2). Instagram, and Facebook when it has an image, need an image from the existing image pipeline |
@@ -526 +524 @@
-1. **Queue mode only.** In assigned mode (current R1), S-00 evaluates the one given signal. Deferred units are not considered.
+1. **Queue mode only.** In assigned mode, S-00 evaluates the one given signal. Deferred units are not considered.
@@ -702,2 +700,2 @@
-| 2 (Wix + LinkedIn only) | 20 | 27 | 79 | 40 |
-| 6 (all destinations) | 44 | 61 | 211 | 40 |
+| 6 (**canonical run: all destinations**) | 44 | 61 | 211 | 40 (current engine) |
+| 2 (comparison only) | 20 | 27 | 79 | 40 |
@@ -707,2 +705,2 @@
-1. **Two destinations fit the current ceiling** in the minimum and normal cases. The worst case exceeds it. That is intended: budget exhaustion ends in `SKIP`, and `publish` destinations are protected by destination order (§0.4).
-2. **Six destinations do not fit.** Even the minimum case (44) exceeds 40. With today's ceiling, the four `generate_only` destinations would regularly end in `SKIP` (`budget_exhausted`). Before generation for all six is switched on, this needs a decision on the ceiling or on per-mode limits. **It is an engineering and budget decision, not an editorial one.** It is listed for the review.
+1. **The canonical run publishes to six destinations (patch CANONICAL-SCOPE),** so the 40-call ceiling of the current engine does not fit it: even the minimum case is 44. The canonical run needs its **own ceiling, sized for six destinations**. The answer to the cost is measurement and optimization, **never shrinking the target to Wix + LinkedIn**. The normal case is about 61 calls. The worst case (211) is still bounded, because exhaustion ends in destination `SKIP` in destination order (§0.4).
+2. The exact ceiling is set from the calls measured in the shadow phase (Step 5, capability C4), not guessed now.
```

### 04_STEP3_STORAGE_AND_RUN_TRACE.md

```diff
--- before/04_STEP3_STORAGE_AND_RUN_TRACE.md
+++ after/04_STEP3_STORAGE_AND_RUN_TRACE.md
@@ -317 +317 @@
-| S-07 | Unit, anchor | Fingerprints (cadence per destination); release scope; contract |
+| S-07 | Unit, anchor | Fingerprints (cadence per destination); destination capability; rollout scope (migration only); contract |
```

### 05_STEP4_KNOWLEDGE_REGISTER.md

No change.

### 06_STEP5_MIGRATION_MAP.md

```diff
--- before/06_STEP5_MIGRATION_MAP.md
+++ after/06_STEP5_MIGRATION_MAP.md
@@ -9 +9,14 @@
-- fixes the coexistence and cutover order that moves production to the target without breaking R1.
+- fixes how **one canonical engine** replaces the current engine: capability by capability, with the current workflows repointed or retired.
+
+**Two binding target principles (owner, patch CANONICAL-SCOPE):**
+
+- **A · One canonical Editorial Core.** `signal → evidence → interpretation → editorial unit → strategy → destination plan → text → validation → publication`.
+  - It is not a Monday, Wednesday or Friday engine.
+  - Weekday, rubric or lens are **configuration inputs** to that same engine, when a client needs them.
+  - One canonical run is made to work end to end first. The same engine is then reused, by configuration, for every other day, schedule and client. That reuse is the product check.
+- **B · Six sibling destinations.**
+  - Wix, LinkedIn, Facebook, Instagram, Threads, Telegram, each with its own strategy, plan and text from the shared core, boundary and anchor.
+  - `R1_PUBLISH_CHANNELS` (Wix + LinkedIn) is a fact about today's release, not a target constraint.
+  - A destination may be `generate_only` only temporarily, during rollout.
+
+**Reading guide.** §0–§1 are **AS-IS evidence**: they describe the current engine, including its weekday workflows. §2 classifies current components. §3 is the **target migration**, which is day-agnostic and multi-destination.
@@ -32,4 +45 @@
-**Two corrections to earlier steps**
-
-1. **Step 0, assumption A10** ("R1 publishes only Wix and LinkedIn") is **partly wrong**. The canonical entrypoint, visibility and daily research respect `R1_PUBLISH_CHANNELS`. The legacy **scheduled Friday** path does not, and posts to all six channels whenever it runs. **VERIFIED in code.** Whether each post succeeds depends on secrets and was not checked.
-2. **Two automatic publishers run on Friday** (research 07:00 UTC, scheduled 08:17/09:17 UTC), and `scheduled_publish.yml` is outside the `never-blank-publish` concurrency group. **VERIFIED.**
+**Note on the inventory (AS-IS only).** The current engine is split into separate weekday paths with different editorial code. Most publish only to Wix and LinkedIn; one legacy path posts to all six. **None of these splits is a target path or a cutover unit.** Each current path is repointed to or retired into the one canonical engine (§3.3).
@@ -83 +93 @@
-- **`DecisionPolicyRecord` → keep for legacy paths during coexistence; DISABLE for target runs.** A target run carries a RelevanceAssessment instead. It is removed together with the last legacy path that uses it. The provenance rule "`decision.json` XOR `decision_policy.json`" (`provenance.py:196-203`) stays valid throughout, because target runs have `decision.json`.
+- **`DecisionPolicyRecord` → migration compatibility only.** It stays for current paths until they are repointed; canonical runs never use it (they carry a RelevanceAssessment). It is removed when the last current path using it is repointed or retired. The provenance rule "`decision.json` XOR `decision_policy.json`" (`provenance.py:196-203`) stays valid throughout, because target runs have `decision.json`.
@@ -94 +104 @@
-**Verdict: DISABLE with the legacy Friday path** (retired or moved per #144; §3 Phase 5). **Not reused** for Portfolio Memory: fingerprints replace it (Step 3). `data/memory/visual_registry.json` belongs to the image pipeline and is out of scope.
+**Verdict: DISABLE** when the legacy scheduled-Friday trigger is retired or repointed to the canonical engine (§3.3). **Not reused** for Portfolio Memory: fingerprints replace it (Step 3). `data/memory/visual_registry.json` belongs to the image pipeline and is out of scope.
@@ -146 +156 @@
-| **Monday editorial path** |||
+| **Current editorial stages** (AS-IS; used today by the Monday and Fri/Sun paths) |||
@@ -158,3 +168,3 @@
-| `src/never_blank/wednesday_*`, `wednesday_july/*` | **Disable** at Wednesday cutover | — | Frozen July modules |
-| `src/editorial/vi_pipeline.py` (visibility) | **Disable** at visibility cutover, **or keep out of scope** | — | Visibility is a separate product line; its cutover is optional and last (§3) |
-| `src/content/generator.py`, `scripts/generate.py`, `scripts/scheduled_publish.py`, `scripts/publish.py` (legacy Friday) | **Disable** | — | With #144 |
+| `src/never_blank/wednesday_*`, `wednesday_july/*` | **Disable** when the Wednesday trigger is repointed to the canonical engine | — | Frozen July modules. Its RSS signal supply (`wednesday_supply.py`) may be kept as a **signal source** feeding S-00 |
+| `src/editorial/vi_pipeline.py` (visibility) | **Disable** when the visibility trigger is repointed | — | Its queue (`visibility_queue.jsonl`) may be kept as a **signal source** feeding S-00 |
+| `src/content/generator.py`, `scripts/generate.py`, `scripts/scheduled_publish.py`, `scripts/publish.py` (AS-IS: legacy Friday) | **Disable** when that trigger is retired or repointed | — | #144 |
@@ -168 +178 @@
-| `src/internal/*`, `src/quality/*`, `src/content/differentiation.py`, `src/content/matrix.py` | **Disable** with legacy Friday | — | §1.3 |
+| `src/internal/*`, `src/quality/*`, `src/content/differentiation.py`, `src/content/matrix.py` | **Disable** with the legacy generator | — | §1.3 |
@@ -170 +180 @@
-| `package.py`, `preflight.py`, `result.py`, `canonical_url.py`, `formatting.py`, `hashtags.py`, `release_scope.py`, publishers (`wix.py`, `linkedin.py`, …) | **Reuse** | S-14 | `bind_canonical_article_url` implements the conditional link (R-2) |
+| `package.py`, `preflight.py`, `result.py`, `canonical_url.py`, `formatting.py`, `hashtags.py`, publishers `wix.py`, `linkedin.py`, `facebook.py`, `instagram.py`, `threads.py`, `telegram.py` | **Reuse** | S-14 for all six destinations | `bind_canonical_article_url` implements the conditional link (R-2). Packages and preflight exist today only for Wix and LinkedIn; they are **extended** to the four Meta/Telegram destinations |
@@ -172 +182 @@
-| `image_pipeline.py`, `wix_media.py`, `src/visual/*` | **Reuse**, out of editorial scope | Visual branch (OPEN-P4) | |
+| `image_pipeline.py`, `wix_media.py`, `src/visual/*` | **Reuse** | Image for Wix cover, Instagram (required, `instagram.py:4, 44`) and Facebook (optional) in the canonical run | The image *policy* stays OPEN-P4; the existing pipeline is used as is |
@@ -179,2 +189,2 @@
-| `monday_publish.yml`, `wednesday_golden.yml`, `research_generate_and_publish.yml` | **Wrap** | Target run harness per path | Per-path engine flag; marker commit step; retention 90 explicit |
-| `scheduled_publish.yml`, `generate_and_publish.yml`, `publish.yml`, `generate_content.yml` | **Disable** with legacy Friday | — | |
+| `monday_publish.yml`, `wednesday_golden.yml`, `research_generate_and_publish.yml`, `visibility_publish.yml` | **Repoint or retire** (§3.3) | Schedules (triggers) of the one canonical engine, if kept | Each keeps at most its schedule, due check and signal source. Its editorial code path is dropped |
+| `scheduled_publish.yml`, `generate_and_publish.yml`, `publish.yml`, `generate_content.yml` | **Retire** (§3.3) | — | Legacy generator paths |
@@ -186,13 +196,29 @@
-## 3. Coexistence and cutover order
-
-**Rules during coexistence:**
-
-- R1 production keeps publishing throughout.
-- Each path switches independently behind a per-path engine flag (`legacy` / `target-shadow` / `target`).
-- Rollback = flip the flag back.
-
-### Phase 0 · Safety deltas on current production (before any target code runs)
-
-These fix verified holes that migration could otherwise make worse. They are **the first implementation of S3-I1**, not new architecture.
-
-| # | Delta | Why |
+## 3. Target migration: one canonical engine, capability cutover
+
+### 3.1 Principle
+
+- There is **one** target engine, the canonical Editorial Core. It is built beside the current engine, proven in shadow, and then becomes the only engine that generates and publishes.
+- **The migration unit is a capability, not a weekday.** The canonical engine takes over capability by capability.
+- **Current workflows are not migrated as paths.** Each is repointed (its schedule calls the canonical engine with its configuration) or retired (§3.3).
+
+### 3.2 Capabilities and cutover order
+
+| # | Capability | What "done" means | Order and gate |
+|---|---|---|---|
+| C0 | **Publication safety** | Marker authority (§1.1): intent before, marker immediately after, per destination; used by whatever publishes. Explicit 90-day retention on run uploads | First. Protects current production during the whole build |
+| C1 | **Shared infrastructure** | Ledger, workspace writer, manifest, write ownership; knowledge register, validator, Knowledge Maintenance job | No behaviour change |
+| C2 | **Canonical Evidence Core and boundary** | S-00 … S-05 on real signals. #58 profile reconciled (§1.2) | Shadow; own budget |
+| C3 | **Canonical planning** | S-06 … S-11 for **all six destinations** | Shadow |
+| C4 | **Canonical writing and checks** | S-12, S-13 for all six destinations | Shadow. Real calls per run measured, and the six-destination ceiling set from them (Step 2 §6) |
+| C5 | **Destination publication capability**, per destination | For each of the six: package, preflight, publisher, marker authority, metrics collector. **Wix and LinkedIn** exist (packages, preflight, collectors). **Facebook, Instagram, Threads, Telegram**: publishers exist; packages, preflight, markers and collectors are new. Instagram also needs the image from the existing pipeline | Each destination is proven in shadow (package + preflight without the publish call), then added to the rollout scope |
+| C6 | **Canonical run live** | The canonical engine is the only publisher. Its first live configuration is the default Never Blank contract with every destination whose C5 is done | Gate: Step 6 acceptance criteria. At the same moment every current publishing trigger is repointed or retired (§3.3). **The canonical run is complete when all six destinations publish;** until then the remaining destinations are `generate_only` (temporary) |
+| C7 | **Reuse by configuration** | Further schedules and clients run the same engine with a different client contract, lens and cadence. **No new editorial code** | The product check |
+| C8 | **Removal** | Code nothing reaches is deleted (§2 "Disable" rows) | Deletion, never a behaviour change |
+
+**Rollback at C6:** turn the canonical run's publishing off and restore the previous triggers. The shared marker authority prevents duplicates across the switch.
+
+**Budget.** The six-destination run costs about 61 model calls in the normal case, against the current engine's ceiling of 40 (Step 2 §6). This is measured in C4 and handled by setting the ceiling and, if needed, optimizing afterwards (the known levers in Step 2 §6). **It is never handled by shrinking the target to Wix + LinkedIn.**
+
+### 3.3 Current path → contribution → how it enters the one canonical engine
+
+| Current path (AS-IS) | What it contributes | Retire or repoint |
@@ -200,68 +226,14 @@
-| 0.1 | Write and commit the publication **marker per channel immediately after that channel succeeds**, independent of job success. Write an **intent** before each publish call | Closes the partial-success double-Wix hole (§1.1) |
-| 0.2 | Selection reads the marker store as well as `published_signal_ids.txt`. An explicitly dispatched `signal_id` is also checked | Closes the dispatch bypass |
-| 0.3 | Put `scheduled_publish.yml` in the shared publish concurrency group | Two Friday publishers today |
-| 0.4 | **Legacy Friday six-channel publishing:** either restrict it to `R1_PUBLISH_CHANNELS` or retire the path (#144) | Violates the documented R1 scope (§0). **See §5: this may be an owner decision** |
-| 0.5 | Explicit `retention-days: 90` on `generated-*` uploads | Repository default unknown |
-
-### Phase 1 · Shared infrastructure, no behaviour change
-
-- Ledger root `data/editorial/` and its commit step.
-- Workspace writer with manifest and ownership.
-- Knowledge register files, validator (CI + run start), Knowledge Maintenance job.
-- Marker store (from Phase 0) used by all paths.
-- S-15 scheduled collector writing raw E-17, **alongside** the existing inline analytics, which stays until cutover.
-
-R1 outputs are unchanged.
-
-### Phase 2 · Evidence and boundary in shadow
-
-- S-00 … S-05 run in a **separate shadow job** on the saved research artifact of real R1 runs: no new retrieval, and its own call budget, so it never consumes R1's.
-- Output: traces and boundaries only.
-- Precondition: the #58 profile reconciliation (§1.2), because S-01 uses the Lens.
-
-### Phase 3 · Planning in shadow
-
-S-06 … S-11 in the shadow job for Wix and LinkedIn: plans and verdicts, no prose.
-
-### Phase 4 · Full target in shadow, `generate_only`
-
-- S-12 and S-13 in the shadow job; S-14 writes fingerprints **without** publishing.
-- Target texts sit side by side with the R1 texts for the same signals.
-- The real call cost per run is measured against the Step 2 §6 estimate.
-
-### Phase 5 · Cutover, one path at a time
-
-| Order | Path | Why this position |
-|---|---|---|
-| 1 | **Monday** | Dispatch-only today (cron paused), so a cutover run is started deliberately and has the lowest production risk. It is already the reference path for the target |
-| 2 | **Research Fri/Sun** | Automatic twice weekly, same entrypoint and the same Monday pipeline; already on #58 |
-| 3 | **Wednesday** | Different editorial code (frozen July modules) and its own signal supply; the most distinct path, so it cuts over last among canonical paths |
-| 4 | **Legacy Friday** | Retired or re-pointed to a canonical path (#144). Legacy memory, the generator and the six-channel `publish.py` loop are disabled with it |
-| — | Visibility | Optional; a separate product line with its own queue. Decided after 1–3 |
-
-**Per path:**
-
-1. `legacy` → `target-shadow`: the target runs beside legacy in the same slot, `generate_only`.
-2. `target-shadow` → `target`: the target publishes, legacy is off.
-
-The step from 1 to 2 needs the acceptance criteria that Step 6 defines per slice. During the switch, the marker authority is shared, so legacy and target can never both publish the same signal.
-
-### Phase 6 · Removal
-
-After the last canonical path has run as `target` for an agreed period, disable:
-
-- the Monday stages, `plan_decisions`, LinkedIn recomposition;
-- the Wednesday July modules;
-- `decision_policy`;
-- the inline analytics and scorer;
-- `PublishedEntry` as a portfolio source;
-- the legacy generator and memory.
-
-Removal is a deletion of unreachable code, never a behaviour change.
-
-**Invariants held across all phases:**
-
-1. R1 publishes only through the canonical publishers, in Wix → LinkedIn order.
-2. One publisher per path per slot (concurrency group).
-3. One shared idempotency authority.
-4. No shadow job publishes or consumes R1's call budget.
+| **Monday** (`monday_publish.yml`, dispatch only; Monday pipeline; `decision_policy`) | Signal selection with role judgment (`select_eligible_signal.py`, `run_first_valid.py`); due-check window; the Never Blank Monday stream contract as **client configuration** (a lens/rubric input) | **Repoint:** if a Monday schedule is wanted, the trigger calls the canonical engine with the Monday configuration. The Monday editorial stages are disabled (§2) |
+| **Research Fri/Sun** (`research_generate_and_publish.yml`; Monday pipeline without role; #58) | The only production use of the #58 Lens → becomes S-01 relevance screen; an automatic schedule | **Repoint:** its schedule, if kept, calls the canonical engine. The inline selector is replaced by S-00 |
+| **Wednesday** (`wednesday_golden.yml`; frozen July modules; own RSS supply) | An RSS-based signal supply (`wednesday_supply.py`) usable as a **signal source** for S-00 | **Repoint:** the schedule, if kept, calls the canonical engine; the supply feeds S-00. The July modules are disabled |
+| **Visibility Tue/Thu** (`visibility_publish.yml`; `vi_pipeline`) | A curated item queue usable as a **signal source** | **Repoint** its schedule and queue into S-00, or retire |
+| **Legacy scheduled Friday** (`scheduled_publish.yml`; `generate.py`; six channels, no canonical gates) | Evidence that the six-channel publishers work end to end (`publish.py` loop). Nothing editorial is reused | **Retire** (#144). Its six-channel reach becomes the canonical engine's C5 capability, with the canonical gates |
+| **Daily research Stage 11** (`daily_signal_research.yml`, publishing behind a secret) | Signal discovery and scoring (`data/research/signals_active.jsonl`) → the signal source for S-00 | **Keep discovery; retire its publishing step** |
+| Manual workflows (`generate_and_publish.yml`, `publish.yml`, `generate_content.yml`, `generate_image.yml`) | Tooling only | **Retire** with the legacy generator; the image step is reused inside the canonical run |
+
+**Invariants in every phase:**
+
+1. One publisher at a time for any signal.
+2. One shared idempotency authority.
+3. No shadow job publishes or consumes the live budget.
+4. Current production is never broken while the canonical engine is built.
@@ -273,8 +245,7 @@
-| Document | Change |
-|---|---|
-| Step 0, A10 | Corrected: legacy scheduled Friday publishes to six channels (§0) |
-| Step 0 §4 / A7 | Legacy memory is live on Fridays through `scheduled_publish.py`, not "legacy only" |
-| Step 3 §0 / §2.1 | The 30-day retention example referred to a manual legacy workflow; canonical run namespaces are already 90 days (§1.5) |
-| Step 3 §3.6 | Concrete S3-I1 choice recorded here (§1.1). The architecture rule is unchanged |
-
-**No architecture decision (AD-01…AD-10, U-1…U-5, F-*, R-*, S3-*, S4-*) is reversed.**
+See `PATCH_CANONICAL_SCOPE_STEPS1_5.md` for every passage. In short:
+
+- AD-02, E-12 and Step 2 S-07/S-14/§0.2 now separate **destination capability** (target: six) from **rollout scope** (temporary).
+- Step 0 and Step 5 weekday material is labelled AS-IS.
+- Step 2 §6 treats six destinations as the reference cost case.
+
+**No architecture decision is reversed.**
@@ -286,4 +257,3 @@
-1. **Legacy Friday publishes to Facebook, Instagram, Threads and Telegram** every Friday it runs, against the documented R1 scope. Restricting it to Wix + LinkedIn, or retiring it, is a safety delta (0.4). **If the owner intends those Friday social posts, this becomes a product decision.** It is the only item in Step 5 that may need the owner.
-2. **The LinkedIn idempotency mismatch** (§1.1) is inferred from code order and must be tested. It does not change the plan: the marker authority replaces the digest-based scan.
-3. **Wix lookup by slug** is not in the code. Whether the API supports it is to be tested. Without it, an intent without a marker stays "possibly published" (at most once), as designed.
-4. **Budget exposure (Step 2 §6) still open:** six destinations do not fit the current 40-call ceiling. Phase 4 measures the real cost before any decision.
+1. **Six-destination cost:** normal about 61 calls, worst 211, against 40 today. It is measured in C4, then the ceiling is set or the pipeline optimized. The target scope is not reduced.
+2. **New work for six destinations (C5):** packages, preflight, markers and collectors for Facebook, Instagram, Threads, Telegram; the Instagram image.
+3. **To test:** the LinkedIn idempotency digest mismatch; Wix lookup by slug; the repository's default artifact retention.
@@ -295,15 +265,12 @@
-- **Проверила реальный код по всем шести пунктам GPT.** Главное из найденного:
-  - **От двойной публикации сейчас защищает только список уже опубликованных сигналов.** Есть дыра: если статья на Wix вышла, а пост в LinkedIn упал, сигнал не отмечается как опубликованный, и в следующий раз на Wix может выйти вторая статья. Закрываем это первым делом: отметка «опубликовано» ставится по каждой площадке сразу после успеха.
-  - **Старый пятничный процесс публикует на все шесть площадок,** хотя по правилам первого релиза должен только на Wix и LinkedIn. Вдобавок по пятницам работают два публикатора. **Это единственный вопрос к тебе:** нужны ли пятничные посты в Facebook, Instagram, Threads и Telegram. Если нет, их выключаем.
-  - **«Ворота решения» (#58) сейчас работают только в пятнично-воскресном потоке.** Понедельник и среда их обходят. Угол, который они выбирают, нигде не используется. В новой системе ворота остаются только как проверка уместности.
-  - **Статистика площадок собирается, но сохраняется только одна усреднённая оценка,** и её никто не читает. Сами цифры будем сохранять.
-  - **Сроки хранения рабочих файлов прогонов уже 90 дней;** 30 дней было только у старого ручного процесса.
-- **Каждая часть текущего кода получила вердикт:** оставить, обернуть, выключить или переписать.
-- **Порядок перехода без остановки публикаций:**
-  1. сначала исправления безопасности;
-  2. общая инфраструктура;
-  3. новая система работает «в тени» рядом со старой, ничего не публикуя;
-  4. переключение по одному потоку: понедельник (он сейчас запускается только вручную), потом пятница и воскресенье, потом среда; старый пятничный процесс уходит;
-  5. в конце удаляется неиспользуемый код.
-
-  Откат — переключение флага обратно.
+- **Строим один канонический движок:** сигнал → факты → интерпретации → редакционная единица → стратегия → план площадки → текст → проверка → публикация. Никаких «движков понедельника» или «пятницы». День, рубрика или линза — это просто настройка того же движка, если она клиенту нужна.
+- **Площадок шесть:** Wix, LinkedIn, Facebook, Instagram, Threads, Telegram. У каждой своя стратегия и свой текст из общего ядра. Нынешнее «только Wix и LinkedIn» — факт о сегодняшнем релизе, а не цель.
+- **Переход идёт по возможностям, а не по дням:**
+  1. защита от двойной публикации;
+  2. инфраструктура;
+  3. движок «в тени» на всех шести площадках, с замером стоимости;
+  4. готовность каждой площадки к публикации;
+  5. включение движка как единственного публикатора;
+  6. копии для других расписаний и клиентов без нового кода — это и есть продуктовая проверка;
+  7. удаление старого кода.
+- **Нынешние дневные процессы остаются только в описании «как есть».** Каждый либо перенаправляется на канонический движок (остаётся только расписание и источник сигналов), либо выключается.
+- **Стоимость шести площадок** (около 61 вызова модели) меряем в «теневом» режиме и потом оптимизируем. Площадки ради бюджета не урезаем.
```

## Кратко по-русски (для Светы)

- **Исправлено по двум принципам.** Один канонический движок: день и рубрика — просто его настройки. Шесть площадок-«сестёр» с публикацией во всех.
- **Пройдены все шаги с 0 по 5, а не только пятый.** Каждое упоминание дней недели, «только Wix и LinkedIn» и старых процессов помечено: «как есть сейчас», «временно на время перехода» или «целевая система». Всё, что протекло в целевую систему, исправлено.
- **План перехода переписан:** не по дням, а по возможностям. Старые дневные процессы либо перенаправляются на один движок, либо выключаются.
- **Стоимость шести площадок** меряем и оптимизируем, площадки не урезаем.
- К шагу 6 не иду, жду проверки GPT.
