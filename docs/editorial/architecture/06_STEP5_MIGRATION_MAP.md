# Step 5 · Current → target migration map

*Implementation architecture, step 5 of 6 · 21 September 2026 · repository `main` @ `bdb8ac8` · architecture: Steps 1–4 with patches R1, R2, S3-R1, S4-R1*

This document:

- verifies the current code on the six points the review asked for;
- classifies every current component as **reuse / wrap / disable / rebuild**;
- fixes how **one canonical engine** replaces the current engine: capability by capability, with the current workflows repointed or retired.

**Two binding target principles (owner, patch CANONICAL-SCOPE):**

- **A · One canonical Editorial Core.** `signal → evidence → interpretation → editorial unit → strategy → destination plan → text → validation → publication`.
  - It is not a Monday, Wednesday or Friday engine.
  - Weekday, rubric or lens are **configuration inputs** to that same engine, when a client needs them.
  - One canonical run is made to work end to end first. The same engine is then reused, by configuration, for every other day, schedule and client. That reuse is the product check.
- **B · Six sibling destinations.**
  - Wix, LinkedIn, Facebook, Instagram, Threads, Telegram, each with its own strategy, plan and text from the shared core, boundary and anchor.
  - `R1_PUBLISH_CHANNELS` (Wix + LinkedIn) is a fact about today's release, not a target constraint.
  - A destination may be `generate_only` only temporarily, during rollout.

**Reading guide.** §0–§1 are **AS-IS evidence**: they describe the current engine, including its weekday workflows. §2 classifies current components. §3 is the **target migration**, which is day-agnostic and multi-destination.

It contains no implementation code, no issues and no orchestrator tasks. Slicing is Step 6.

**Evidence labels:**

- **VERIFIED**: read in code or workflow at `bdb8ac8`, with file and line.
- **INFERRED**: follows from verified facts, not executed.
- **TO TEST**: must be confirmed by a run before it is relied on.

---

## 0. What actually runs in production today

| Path | Trigger (VERIFIED) | Entrypoint and editorial code | Decision authority | Publishes to | Run namespace |
|---|---|---|---|---|---|
| **Monday** | `monday_publish.yml`: **dispatch only**; cron commented out (L20-37) | `generate_and_publish.py` → Monday pipeline (`src/editorial/pipeline.py`, L2169) | `decision_policy.json` (`role_bounded_r1`) | Wix + LinkedIn | `reports/content_packages/<sid>/runs/<run_id>/`, artifact 90 d |
| **Wednesday** | `wednesday_golden.yml`: cron Wed 08:17/09:17 UTC | Same entrypoint → frozen July modules (`src/never_blank/wednesday_july/*`, L2160-2162) | `decision_policy.json` (`role_bounded_r1`) | Wix + LinkedIn | Same, 90 d |
| **Research Fri/Sun** | `research_generate_and_publish.yml`: cron `0 7 * * 5,0` | Same entrypoint, **no role** → Monday pipeline without role rules | **#58 Decision Lens** (`evaluate_and_persist_decision`, L1562; `require_proceed`, L1578) | Wix + LinkedIn | Same, 90 d |
| **Visibility Tue/Thu** | `visibility_publish.yml`: cron Tue, Thu 07:00 | `generate_and_publish_visibility.py` → `src/editorial/vi_pipeline.py` | Own | Wix + LinkedIn (`restrict_to_release_scope`) | `reports/content_packages/<item>_generated.json`, **committed to git** |
| **Scheduled Friday (legacy)** | `scheduled_publish.yml`: cron Fri 08:17/09:17 UTC; "legacy until #144" (L9) | `scheduled_publish.py` → `generate.py` (`src/content/generator.py`, legacy memory) → `publish.py --live` per channel | None of the canonical gates | **Wix, LinkedIn, Facebook, Instagram, Threads, Telegram** (`scheduled_publish.py` L232-240; `publish.py` `ALL_CHANNELS` L50) | None; `data/drafts/…`, not committed |
| Daily research Stage 11 | `daily_signal_research.yml`: daily cron; publishing only if secret `NB_RESEARCH_PUBLISH_ENABLED=true`, never on Wednesdays | `run_daily_research.py` → `publish_packages.py` | Own | Wix + LinkedIn if enabled (max 1) | Flat files, committed |

**Note on the inventory (AS-IS only).** The current engine is split into separate weekday paths with different editorial code. Most publish only to Wix and LinkedIn; one legacy path posts to all six. **None of these splits is a target path or a cutover unit.** Each current path is repointed to or retired into the one canonical engine (§3.3).

---

## 1. Verification results

### 1.1 Publication idempotency authority and `find_prior_*`

| Finding | Status |
|---|---|
| `find_prior_wix_publication` / `find_prior_linkedin_publication` scan only the local `packages_dir/<signal_id>/runs/*/publication_results.json` (`idempotency.py:434, 534`). With no `runs/` directory they return "no prior publication" (`:435-436, 535-536`). The module says it covers sequential retries only (`:30-34`) | VERIFIED |
| Production workflows only **upload** run namespaces as artifacts. None downloads prior artifacts. The "Mark signal" steps commit only `published_signal_ids.txt` and `published_content_index.jsonl` (`monday_publish.yml:337-343`, `wednesday_golden.yml:230-234`, `research_generate_and_publish.yml:182-188`) | VERIFIED |
| Therefore `find_prior_*` finds nothing in a fresh CI checkout | INFERRED (strong) |
| The Wix identity key includes the article digest (`idempotency.py:61-75`). A **new** article for the same signal counts as a different publication even when evidence is present | VERIFIED |
| **LinkedIn scan probably never matches.** The identity digest is taken from the package after `bind_canonical_article_url` has added the link (`generate_and_publish.py:3459`, before the scan at `:3556`). The prior digest comes from `linkedin_composition.json` without the link (`idempotency.py:364-371`) | INFERRED from code order; **TO TEST** |
| **The real authority today is `data/research/published_signal_ids.txt`,** by signal ID. It is read by `select_eligible_signal.py:66-80`, the research workflow's inline selector (L66-78), Wednesday (`generate_and_publish.py:1186`) and `from-package` retries | VERIFIED |
| **Hole: partial success.** The signal is marked only when the whole job succeeds (`success()`, `monday:329`, `wednesday:230`). The entrypoint exits 1 if any channel failed (`generate_and_publish.py:3753-3757`). Wix published + LinkedIn failed ⇒ the signal is not marked ⇒ the next run can publish a **second Wix post** for the same signal | VERIFIED chain; the double post itself INFERRED |
| An explicitly dispatched `signal_id` in `research_generate_and_publish.yml` bypasses the list | VERIFIED |
| **External lookup:** `WixPublisher` reads only by post ID (`wix.py:134, 353, 490`); no lookup by slug or title exists in code. LinkedIn via Zernio is POST only; Zernio returns 409 for identical content within 24 h (`linkedin.py:166-176`), which is not proof of a post | VERIFIED (code); Wix slug lookup API availability **TO TEST** |

**Verdict for S3-I1** (Step 3 §3.6). The architecture decision stays. The concrete choice:

| Element | Target |
|---|---|
| **Authority store** | Committed `data/editorial/publication_markers/<client>/<destination>/<key>.json`: one file per publication, plus `…/<key>.intent.json`. It is shared by legacy and target paths during coexistence |
| **Identity key** | (client, destination, sorted source signal IDs). **No article digest.** One publication per signal set per destination, the same semantics as `published_signal_ids.txt`, and stricter than the current digest-based Wix key |
| **When written** | Intent before each channel's publish call. Marker **immediately after that channel succeeds**, committed in its own step with `if: always()` semantics, before and independent of any other commit |
| **External lookup** | Wix: by post ID from a marker (exists). Lookup by slug: **TO TEST** (if confirmed, it becomes the recovery path for an intent without a marker). LinkedIn/Zernio: none, so markers are its only authority, which satisfies S-07 rule 7 |
| **`published_signal_ids.txt`** | Kept and still written, as a signal-level summary. Selection keeps reading it. It is no longer the only authority |
| **`find_prior_*`** | **Rebuild**: re-point to the marker store; keep its reuse behaviour (`REUSED` + canonical URL lookup) |

### 1.2 #58 Decision Lens and `DecisionPolicyRecord`

| Finding | Status |
|---|---|
| Switch at `generate_and_publish.py:1493-1549`: a role with `decision_policy == "role_bounded_r1"` → `decision_policy.json`; otherwise the #58 Lens | VERIFIED |
| Both existing roles (`never-blank-monday-documented-case`, `never-blank-wednesday-golden`) are `role_bounded_r1` (`strategy/current/business_strategy.json:361` and the Wednesday entry) | VERIFIED |
| **Only research Fri/Sun uses #58 in production** (no `--editorial-role`) | VERIFIED |
| Reason for the bypass: the Lens's audience-transfer rules predate the corrected Monday strategy (`generate_and_publish.py:1478-1479`). A live Wednesday run was stopped with `revise` (`:1480-1486`). Debt against #151, whose reconciliation is not specified (`MONDAY_TARGET_ARCHITECTURE.md:464`, D9) | VERIFIED |
| `supported_editorial_angle` and `defensible_perspective` are **not consumed anywhere downstream** | VERIFIED. AD-09 is already true in practice |

**Verdicts**

- **#58 evaluator → WRAP** as the S-01 relevance screen for **all** target paths (Step 2 R-1).
  - `revise` / `hold` become an enrichment REPLAN, not a stop.
  - `reject` / `irrelevant` / `insufficient_evidence` → `SKIP`.
  - Angle fields: recorded as hints only.
  - **Precondition for cutover:** the #58 profile for the Never Blank roles (`config/prompts/decision_lens/never_blank.yaml`) must be brought in line with the target's `audience_transfer` / `bounded_external_case` semantics, which is what #151 was waiting for. This is the reconciliation #151 deferred, now defined: relevance plus claim mode feed the boundary. The Lens no longer decides the story.
- **`DecisionPolicyRecord` → migration compatibility only.** It stays for current paths until they are repointed; canonical runs never use it (they carry a RelevanceAssessment). It is removed when the last current path using it is repointed or retired. The provenance rule "`decision.json` XOR `decision_policy.json`" (`provenance.py:196-203`) stays valid throughout, because target runs have `decision.json`.

### 1.3 Legacy memory

| Finding | Status |
|---|---|
| `src/internal/memory.py`, `strategy.py`, `topic_prioritizer.py`, `src/content/differentiation.py`, `src/quality/duplication.py` (via `gate.py`) are reached only from `scripts/generate.py` and `scripts/dry_run.py`. `generate_and_publish.py` imports none of them | VERIFIED |
| **`generate.py` is live every Friday** through `scheduled_publish.py` (L229-241), besides the dispatch-only workflows | VERIFIED. This corrects the Step 0 note "legacy only" |
| `data/memory/{published,embeddings,portfolio,theme_registry,…}.json` do not exist in the repository; the workflows running `generate.py` never commit them. The Friday de-duplication and theme memory therefore start empty every run | VERIFIED (files absent, no commit); effect INFERRED |
| `echo_memory.py` reads `published_content_index.jsonl` but is reached only from unused or compile-only code | VERIFIED |

**Verdict: DISABLE** when the legacy scheduled-Friday trigger is retired or repointed to the canonical engine (§3.3). **Not reused** for Portfolio Memory: fingerprints replace it (Step 3). `data/memory/visual_registry.json` belongs to the image pipeline and is out of scope.

### 1.4 Analytics collectors

| Finding | Status |
|---|---|
| Effective path: `run_analytics_pipeline([BlogCollector(), LinkedInCollector()])` runs **inline at the end of every non-dry canonical run** (`generate_and_publish.py:3733`). Its writes reach git only through the Mark step's commit of `published_content_index.jsonl` | VERIFIED |
| `run_analytics.yml` and `smoke_test_full_cycle.yml` are dispatch-only and **commit nothing**; their updates are lost | VERIFIED |
| Collected: Wix views, likes, comments (`blog.py:46, 162-164`); Zernio impressions, reach, likes, comments, shares, saves, clicks, views (`linkedin.py:63, 209-216`) | VERIFIED |
| **Only a blended score is persisted** (`scorer.py:103-145`, `SCORER_VERSION = "v1"`), the highest per `content_id`. Raw metrics exist only in logs | VERIFIED |
| **Nothing reads `analytics_score`** (the orchestrator docstring claiming Echo Memory uses it is false) | VERIFIED |

**Verdicts**

- **Collectors → WRAP** into S-15. The API fetch code of `BlogCollector` and `LinkedInCollector` is reused. S-15 runs as its own **scheduled job after publication windows**, not inline in a run. It writes raw metrics with confounders as E-17 ledger records.
- **Scorer → DISABLE** as a knowledge input. A blend is not evidence (Step 2 S-15).
- **Inline call at the end of the run → DISABLE at cutover.** S-15 is outside the run's critical path.
- **`analytics_score` on `PublishedEntry`:** left as is during coexistence (unread, harmless), retired with `PublishedEntry` as a portfolio source.

### 1.5 Retention 30 → 90

| Finding | Status |
|---|---|
| The uploads that hold run namespaces are already **90 days**: Monday L375, Wednesday L247, research L217 | VERIFIED |
| `generated-<sid>` uploads (Monday L393-399, research L219-225) set **no** `retention-days`: the repository default applies, value unknown | VERIFIED; default **TO TEST** |
| Below 90: scheduled Friday report 7; daily research 7; smoke test 7; `generate_and_publish.yml`, `publish.yml`, `generate_*`, `connectivity_audit.yml` 30. **None of these holds a canonical run namespace** | VERIFIED |

**Correction to Step 3 §0 / §2.1.** The 30-day workflow named there (`generate_and_publish.yml`) is a manual legacy workflow, not a run-namespace holder. **Target:** every upload of `reports/editorial_runs/<run_id>/` and every `generated-*` upload sets `retention-days: 90` explicitly. The legacy 7/30-day workflows retire with their paths. Nothing needs to be raised from 30 to 90 for the canonical paths today.

---

## 2. Component classification

| Component | Verdict | Target role | Notes |
|---|---|---|---|
| **Run spine** |||
| `src/run/run_context.py` (`RunContext`) | **Reuse** | E-19 header | |
| `src/run/code_identity.py` | **Reuse** | E-19 header, live-acceptance gate | |
| `src/run/call_budget.py` | **Wrap** | `RunCallBudget` | Exhaustion becomes ARP `SKIP` (R-3), still refused before paying |
| `src/run/stage_routing.py` | **Wrap** | Routing evidence, mandatory-knowledge containment, label prohibition | Extended as in Step 3 §4.2 |
| `src/run/decision_policy.py` | **Keep (legacy) → Disable** | — | Legacy paths only; removed with the last one |
| `src/intake/*` (`ContentAssignment`, adapters, audience routing) | **Reuse** | E-01 intake | |
| `src/artifacts/__init__.py` (writers, `resolve_run_dir`) | **Wrap** | Workspace writer with create-once and ownership | New root `reports/editorial_runs/`; legacy root kept for research/decision |
| `src/artifacts/provenance.py` | **Wrap** | Manifest verification | Extended to manifest digests and write ownership |
| `src/lifecycle/signal_lifecycle.py` (`ResearchContext`, `EditorialContext`) | **Wrap** | Context passing into S-01 / S-06 | Editorial context replaced by entity references |
| **Research and evidence** |||
| `src/research/provider.py`, `lifecycle.py`, `adapters/{exa,direct_url,fake}.py` | **Reuse** | S-01, S-03 retrieval | |
| `src/research/evidence.py` | **Wrap** | E-02/E-03/E-04 (AD-05) | `claim` → `evidence_claim.statement` by mapping |
| `src/research/assessment.py` (`assess_artifact`) | **Wrap** | S-01, S-03 extended assessment | Returns observation kind, figure, third-party flag, claim scope and strength |
| `src/editorial/source_eligibility.py` | **Wrap** | S-00 eligibility | |
| `src/editorial/decision_contract.py`, `decision_lens_evaluator.py`, `decision_lifecycle.py` (#58) | **Wrap** | S-01 relevance screen | Profile reconciliation precondition (§1.2); `require_proceed` becomes ARP |
| `src/editorial/sources_of_record.py`, `source_transparency.py` | **Wrap** | S-13 code checks (V-T04) | |
| **Current editorial stages** (AS-IS; used today by the Monday and Fri/Sun paths) |||
| `pattern_extractor.py`, `decision_lens_lite.py`, `narrative_spine.py`, `hook_engine.py`, `reader_context.py`, `discovery_builder.py`, `story_assembly.py`, `never_blank_voice.py`, `pipeline.py` | **Disable** at cutover | Replaced by S-02, S-06, S-08 … S-10 | Kept running for legacy paths until each cuts over |
| `plan_decisions.py` | **Disable** | Replaced by S-08/S-09 | |
| `editorial_plan.py` (`EditorialPlan`, `evidence_package_from_artifact`) | **Rebuild** | E-14; reuse `check()` / `forbidden_in()` ideas in S-11/S-13 | `evidence_package_from_artifact` drops interpretation layers; not used by target |
| `platform_composer.py` | **Rebuild** | S-12 Writer | Fixed `_BLOCK_TABLE` removed |
| `linkedin_composition.py` (recomposition from the accepted article) | **Disable** | — | Content derivation conflicts with I-06; LinkedIn gets its own strategy |
| `derivation_fidelity.py` | **Disable** (as a derivation judge) | — | No derivations in the target. Parts may be reused as V-T01 code checks |
| `factual_review.py` | **Wrap** | S-13 truth call | |
| `editorial_acceptance.py` | **Wrap** | S-13 execution call | Rubric replaced by V-T criteria; "one revision" becomes `L_edit` |
| `machine_tells.py`, `src/content/output_guard.py` | **Wrap** | S-13 code checks, V-S hints | |
| `editorial_role.py` | **Wrap** | Client/stream configuration | `decision_policy` field retired with legacy |
| **Other editorial paths** |||
| `src/never_blank/wednesday_*`, `wednesday_july/*` | **Disable** when the Wednesday trigger is repointed to the canonical engine | — | Frozen July modules. Its RSS signal supply (`wednesday_supply.py`) may be kept as a **signal source** feeding S-00 |
| `src/editorial/vi_pipeline.py` (visibility) | **Disable** when the visibility trigger is repointed | — | Its queue (`visibility_queue.jsonl`) may be kept as a **signal source** feeding S-00 |
| `src/content/generator.py`, `scripts/generate.py`, `scripts/scheduled_publish.py`, `scripts/publish.py` (AS-IS: legacy Friday) | **Disable** when that trigger is retired or repointed | — | #144 |
| **Strategy and configuration** |||
| `src/strategy/client_contracts.py` | **Wrap** | Client Contract loading, tier-2 rules, forbidden, ladder | Gains the Step 4 front-matter fields and ladder mapping |
| `src/strategy/business_config.py`, `loader.py`, `execution_context.py` | **Reuse** | Configuration identity | |
| `src/strategy/history.py`, `models.py` (`PublishedEntry`) | **Keep → Retire as portfolio source** | Publication index during coexistence | Fingerprints are the portfolio source |
| `src/strategy/validators.py` (`validate_article_for_publish`) | **Wrap** | Pre-package validation in S-14 | |
| `src/strategy/echo_memory.py`, `content_planner.py`, `decision_engine.py`, `market_analyzer.py`, `pattern_extractor.py` (strategy) | **Disable** | — | Unused or compile-only |
| **Legacy memory and quality** |||
| `src/internal/*`, `src/quality/*`, `src/content/differentiation.py`, `src/content/matrix.py` | **Disable** with the legacy generator | — | §1.3 |
| **Publishing** |||
| `package.py`, `preflight.py`, `result.py`, `canonical_url.py`, `formatting.py`, `hashtags.py`, publishers `wix.py`, `linkedin.py`, `facebook.py`, `instagram.py`, `threads.py`, `telegram.py` | **Reuse** | S-14 for all six destinations | `bind_canonical_article_url` implements the conditional link (R-2). Packages and preflight exist today only for Wix and LinkedIn; they are **extended** to the four Meta/Telegram destinations |
| `idempotency.py` (`find_prior_*`) | **Rebuild** | S-14 idempotency lookup against the marker authority (§1.1) | |
| `image_pipeline.py`, `wix_media.py`, `src/visual/*` | **Reuse** | Image for Wix cover, Instagram (required, `instagram.py:4, 44`) and Facebook (optional) in the canonical run | The image *policy* stays OPEN-P4; the existing pipeline is used as is |
| **Analytics** |||
| `src/analytics/blog.py`, `linkedin.py`, `collector_protocol.py`, `base.py` | **Wrap** | S-15 scheduled collector | |
| `src/analytics/scorer.py`, `orchestrator.py` (score write-back) | **Disable** as knowledge input | — | |
| **Reporting** |||
| `src/reporting/run_report.py` (`R1RunReport`) | **Wrap** | RunSummary projection | Public-safe fields only (S3-R1) |
| **Workflows** |||
| `monday_publish.yml`, `wednesday_golden.yml`, `research_generate_and_publish.yml`, `visibility_publish.yml` | **Repoint or retire** (§3.3) | Schedules (triggers) of the one canonical engine, if kept | Each keeps at most its schedule, due check and signal source. Its editorial code path is dropped |
| `scheduled_publish.yml`, `generate_and_publish.yml`, `publish.yml`, `generate_content.yml` | **Retire** (§3.3) | — | Legacy generator paths |
| `run_analytics.yml` | **Rebuild** as the S-15 scheduled job | — | With a ledger commit |
| New: Knowledge Maintenance job | **New** | Step 4 §5.2 | Scheduled, offline |

---

## 3. Target migration: one canonical engine, capability cutover

### 3.1 Principle

- There is **one** target engine, the canonical Editorial Core. It is built beside the current engine, proven in shadow, and then becomes the only engine that generates and publishes.
- **The migration unit is a capability, not a weekday.** The canonical engine takes over capability by capability.
- **Current workflows are not migrated as paths.** Each is repointed (its schedule calls the canonical engine with its configuration) or retired (§3.3).

### 3.2 Capabilities and cutover order

| # | Capability | What "done" means | Order and gate |
|---|---|---|---|
| C0 | **Publication safety** | Marker authority (§1.1): intent before, marker immediately after, per destination; used by whatever publishes. Explicit 90-day retention on run uploads | First. Protects current production during the whole build |
| C1 | **Shared infrastructure** | Ledger, workspace writer, manifest, write ownership; knowledge register, validator, Knowledge Maintenance job | No behaviour change |
| C2 | **Canonical Evidence Core and boundary** | S-00 … S-05 on real signals. #58 profile reconciled (§1.2) | Shadow; own budget |
| C3 | **Canonical planning** | S-06 … S-11 for **all six destinations** | Shadow |
| C4 | **Canonical writing and checks** | S-12, S-13 for all six destinations | Shadow. Real calls per run measured, and the six-destination ceiling set from them (Step 2 §6) |
| C5 | **Destination publication capability**, per destination | For each of the six: package, preflight, publisher, marker authority, metrics collector. **Wix and LinkedIn** exist (packages, preflight, collectors). **Facebook, Instagram, Threads, Telegram**: publishers exist; packages, preflight, markers and collectors are new. Instagram also needs the image from the existing pipeline | Each destination is proven in shadow (package + preflight without the publish call), then added to the rollout scope |
| C6 | **Canonical run live** | The canonical engine is the only publisher. Its first live configuration is the default Never Blank contract with every destination whose C5 is done | Gate: Step 6 acceptance criteria. At the same moment every current publishing trigger is repointed or retired (§3.3). **The canonical run is complete when all six destinations publish;** until then the remaining destinations are `generate_only` (temporary) |
| C7 | **Reuse by configuration** | Further schedules and clients run the same engine with a different client contract, lens and cadence. **No new editorial code** | The product check |
| C8 | **Removal** | Code nothing reaches is deleted (§2 "Disable" rows) | Deletion, never a behaviour change |

**Rollback at C6:** turn the canonical run's publishing off and restore the previous triggers. The shared marker authority prevents duplicates across the switch.

**Budget.** The six-destination run costs about 61 model calls in the normal case, against the current engine's ceiling of 40 (Step 2 §6). This is measured in C4 and handled by setting the ceiling and, if needed, optimizing afterwards (the known levers in Step 2 §6). **It is never handled by shrinking the target to Wix + LinkedIn.**

### 3.3 Current path → contribution → how it enters the one canonical engine

| Current path (AS-IS) | What it contributes | Retire or repoint |
|---|---|---|
| **Monday** (`monday_publish.yml`, dispatch only; Monday pipeline; `decision_policy`) | Signal selection with role judgment (`select_eligible_signal.py`, `run_first_valid.py`); due-check window; the Never Blank Monday stream contract as **client configuration** (a lens/rubric input) | **Repoint:** if a Monday schedule is wanted, the trigger calls the canonical engine with the Monday configuration. The Monday editorial stages are disabled (§2) |
| **Research Fri/Sun** (`research_generate_and_publish.yml`; Monday pipeline without role; #58) | The only production use of the #58 Lens → becomes S-01 relevance screen; an automatic schedule | **Repoint:** its schedule, if kept, calls the canonical engine. The inline selector is replaced by S-00 |
| **Wednesday** (`wednesday_golden.yml`; frozen July modules; own RSS supply) | An RSS-based signal supply (`wednesday_supply.py`) usable as a **signal source** for S-00 | **Repoint:** the schedule, if kept, calls the canonical engine; the supply feeds S-00. The July modules are disabled |
| **Visibility Tue/Thu** (`visibility_publish.yml`; `vi_pipeline`) | A curated item queue usable as a **signal source** | **Repoint** its schedule and queue into S-00, or retire |
| **Legacy scheduled Friday** (`scheduled_publish.yml`; `generate.py`; six channels, no canonical gates) | Evidence that the six-channel publishers work end to end (`publish.py` loop). Nothing editorial is reused | **Retire** (#144). Its six-channel reach becomes the canonical engine's C5 capability, with the canonical gates |
| **Daily research Stage 11** (`daily_signal_research.yml`, publishing behind a secret) | Signal discovery and scoring (`data/research/signals_active.jsonl`) → the signal source for S-00 | **Keep discovery; retire its publishing step** |
| Manual workflows (`generate_and_publish.yml`, `publish.yml`, `generate_content.yml`, `generate_image.yml`) | Tooling only | **Retire** with the legacy generator; the image step is reused inside the canonical run |

**Invariants in every phase:**

1. One publisher at a time for any signal.
2. One shared idempotency authority.
3. No shadow job publishes or consumes the live budget.
4. Current production is never broken while the canonical engine is built.

---

## 4. What changes in earlier documents

See `PATCH_CANONICAL_SCOPE_STEPS1_5.md` for every passage. In short:

- AD-02, E-12 and Step 2 S-07/S-14/§0.2 now separate **destination capability** (target: six) from **rollout scope** (temporary).
- Step 0 and Step 5 weekday material is labelled AS-IS.
- Step 2 §6 treats six destinations as the reference cost case.

**No architecture decision is reversed.**

---

## 5. Items for review

1. **Six-destination cost:** normal about 61 calls, worst 211, against 40 today. It is measured in C4, then the ceiling is set or the pipeline optimized. The target scope is not reduced.
2. **New work for six destinations (C5):** packages, preflight, markers and collectors for Facebook, Instagram, Threads, Telegram; the Instagram image.
3. **To test:** the LinkedIn idempotency digest mismatch; Wix lookup by slug; the repository's default artifact retention.

---

## Кратко по-русски (для Светы)

- **Строим один канонический движок:** сигнал → факты → интерпретации → редакционная единица → стратегия → план площадки → текст → проверка → публикация. Никаких «движков понедельника» или «пятницы». День, рубрика или линза — это просто настройка того же движка, если она клиенту нужна.
- **Площадок шесть:** Wix, LinkedIn, Facebook, Instagram, Threads, Telegram. У каждой своя стратегия и свой текст из общего ядра. Нынешнее «только Wix и LinkedIn» — факт о сегодняшнем релизе, а не цель.
- **Переход идёт по возможностям, а не по дням:**
  1. защита от двойной публикации;
  2. инфраструктура;
  3. движок «в тени» на всех шести площадках, с замером стоимости;
  4. готовность каждой площадки к публикации;
  5. включение движка как единственного публикатора;
  6. копии для других расписаний и клиентов без нового кода — это и есть продуктовая проверка;
  7. удаление старого кода.
- **Нынешние дневные процессы остаются только в описании «как есть».** Каждый либо перенаправляется на канонический движок (остаётся только расписание и источник сигналов), либо выключается.
- **Стоимость шести площадок** (около 61 вызова модели) меряем в «теневом» режиме и потом оптимизируем. Площадки ради бюджета не урезаем.
