# Step 0 · Architecture-impact delta: `87ea0f4` → `bdb8ac8`

*Implementation architecture, step 0 of 6 · 21 September 2026 · read-only · design authority: `docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`*

This document answers one question: can the target Editorial Core be designed on the evidence in `REPO_TRACK_87ea0f4.md`, or has current `main` moved in a way that changes that?

**Short answer.** `main` has not changed any code, configuration, client document or workflow since `87ea0f4`. Every code-level fact in the REPO_TRACK is still true. But the REPO_TRACK is **incomplete for architecture work**. It studied the editorial Monday path and covered research and the decision gate in one line. This step examined those seams. Several of them are typed, tested contracts that the target should **reuse or wrap**, not replace.

---

## 1. What changed on `main` since `87ea0f4`

Five commits. Method: `git log 87ea0f4..origin/main`, then a scoped diff.

| Commit | Change | Type |
|---|---|---|
| `3ca0341` | `reports/research_2026-09-21.json` (daily research output) | Data |
| `156d5f7` | `docs/editorial/RESEARCH_PROVENANCE.md` | Documentation |
| `6acf6ec` | `docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` | Documentation |
| `21907ac` | `docs/editorial/research/REPO_TRACK_87ea0f4.md` | Documentation |
| `bdb8ac8` | `docs/editorial/research/EDITORIAL_KNOWLEDGE_MAP_v0.1_superseded.md` (#284) | Documentation |

**Verified no change** in `src/`, `scripts/`, `config/`, `clients/`, `strategy/` or `.github/`: `git diff --quiet 87ea0f4 origin/main -- <those paths>` returns clean.

**Unmerged remote branches.** `task/279`, `orch/269`, `task/268`, `task/263`, `orch/267`, `orch/240-2`, `orch/237` and `evidence/234` are pre-squash histories of PRs that are already merged. They differ from `main` only because `main` moved later. None carries unmerged architecture-relevant work.

## 2. Which changes affect the target architecture

| Change | Effect on the Canonical Map / Editorial Core |
|---|---|
| Canonical Map v1, provenance, REPO_TRACK and v0.1 now in the repository | **Affects governance, not design.** The map is now citable by path. The IDs E-*, S-*, I-*, K-*, V-* are stable references for the next steps |
| `reports/research_2026-09-21.json` | **Irrelevant to the architecture.** It is a daily output of the legacy research generator. It is useful later as sample signal input for slices, nothing more |

**Nothing on `main` since `87ea0f4` changes the design.**

## 3. REPO_TRACK assumptions: still valid, partially stale, or stale

**Stale** means code changed. **Incomplete** means the code is the same, but the REPO_TRACK did not look at a seam that matters now.

| # | REPO_TRACK assumption | Status | Note |
|---|---|---|---|
| A1 | The Monday path runs Pattern Extractor → Decision Lens Lite → Spine → Hook → Reader Context → Discovery → Story → Voice → Platform Composer. The composer is the only prose writer and uses `_BLOCK_TABLE` | **Valid** | Unchanged |
| A2 | Five stages that fix argument content and order receive no plan and no lens (`pipeline.py:60-62, 175-193`) | **Valid** | Unchanged. Now observable per run through `stage_routing` (see §4.4) |
| A3 | Blocks are mandatory only because `discovery_builder._validate` requires them | **Valid** | Unchanged |
| A4 | `central_claim` is copied from CORE_FACT, a semantic bug class | **Valid** | Unchanged |
| A5 | Structure is explicitly not enforced by reviewers | **Valid** | Unchanged |
| A6 | Portfolio signals are counted and never used; `analytics_score` is written back and read by nothing | **Valid** | Confirmed: `PublishedEntry` has only `hook`, `echo`, `topic`, `cta_mode` and one derived `analytics_score`. There is no strategy fingerprint |
| A7 | "Differentiation: legacy path only" | **Valid, extended** | `src/internal/memory.py` (embeddings, theme registry, diversity adjustment) is reached only from `scripts/generate.py`, `scripts/dry_run.py` and `src/quality/duplication.py`. It is not on the R1 path |
| A8 | Stages before drafting: "eligibility (model) → research + evidence verdicts (model) → plan decider" | **Incomplete** | The line hides a typed research contract and a typed pre-editorial decision gate. See §4.1–4.2 |
| A9 | The LinkedIn text is recomposed from the accepted article, with a fidelity judge | **Valid, incomplete** | It also has a **publication-order dependency**: the LinkedIn post carries the canonical Wix URL, so Wix must publish first (`release_scope.py`). That is a separate concern from content derivation. See §4.5 |
| A10 | The run can be described as a single article-then-derivatives flow | **Incomplete** | *(AS-IS; later corrected in Step 5 §0: the legacy scheduled Friday path posts to all six channels.)* R1 **publishes** only Wix and LinkedIn. Facebook, Instagram, Threads and Telegram are generated and packaged, but not published (`R1_PUBLISH_CHANNELS`, #227) |
| A11 | Evidence layer is the most mature part | **Valid, strengthened** | The contract is richer than the REPO_TRACK described (§4.1) |

**Nothing is stale. A8, A9 and A10 are incomplete.** The gaps are filled below.

## 4. Current-engine seams to reuse rather than replace

The classification here is **provisional**. The final reuse / wrap / disable / rebuild verdict belongs to step 5, based on the stage contracts. No component is kept merely because it exists.

### 4.1 Research contract: `src/research/evidence.py`

Immutable Pydantic models with referential integrity, produced by three adapters (`exa`, `direct_url`, `fake`), assessed by `assess_artifact` and persisted create-once as `research.json`.

| Current type | What it holds | Target entity | Fit |
|---|---|---|---|
| `NormalizedSource` | Source identity, locator, publisher, publication time, retrieval time | Provenance of E-02 | Direct |
| `SupportReference` | Source ID, excerpt ≤ 4000, location | **E-02 `source_observation`** | Direct. It lacks an attribution form ("X reports Y") and an observation kind (quote, figure, event) |
| `ExtractedEvidence` | Evidence ID, statement (field `claim`), sources, support, disposition, rationale; docstring "never model interpretation" | **E-03 `evidence_claim`** | Strong. Missing: strength and ceiling. The field name `claim` conflicts with the ontology and is handled by mapping, not by renaming in place |
| `EvidenceDisposition` | accepted, qualified, conflicting, rejected, not_assessed | E-03 verdict | Direct. `qualified` = "with caveat" |
| `ModelInterpretation` | Interpretation ID, statement, ≥1 evidence IDs | Seed of **E-08** | Partial: no kind, strength, ceiling, admissibility, limits or counter-evidence |
| `UncertaintyAssessment` | Level, materiality, resolution, description, references | Limits in E-09 (concession candidates); gaps (E-07) | Partial |
| `Contradiction` | ≥2 records, resolution | Tension/conflict input to S-04; the "evidence conflicts" state in ARP §6.2 | Partial |
| `NormalizedResearchArtifact` | Run, assignment, signal, configuration identity, all of the above, assessor, readiness | Initial **E-04 Evidence Core** | Strong |

**Key finding.** The contract already separates observation, evidence and interpretation, as the Canonical Map requires. But in production the upper layers are empty:

- none of the three adapters populates `interpretations`, `uncertainties` or `contradictions`;
- `assess_artifact` reads contradictions and uncertainties to derive readiness, so it depends on inputs no producer supplies;
- `evidence_package_from_artifact` (`editorial_plan.py`) maps only `artifact.evidence` into the editorial plan. Everything else is dropped at the editorial boundary.

**Provisional verdict: wrap and extend.** E-02, E-03 and E-04 are built on this contract. E-08 and E-09 are new entities that reference it by ID; they do not overload `ModelInterpretation`.

### 4.2 Pre-editorial decision gate (#58): `src/editorial/decision_contract.py`, `decision_lifecycle.py`

The REPO_TRACK names only Decision Lens **Lite**, a Monday pipeline stage. There is also a separate typed gate that runs after research and before any editorial work. It writes `decision.json` once. `require_proceed()` stops the run on any disposition other than `PROCEED`.

| Field in `DecisionLensDecisionArtifact` / judgment | Target overlap |
|---|---|
| `disposition`: proceed / revise / hold / reject / insufficient_evidence | S-00 fit and the S-03/S-04 `SKIP` outcomes. Every non-proceed disposition **stops**; none waits for a human. **Compatible with I-01** |
| `relevance`, `relevance_bases` (direct audience evidence … analogy only), `evidence_sufficiency` | S-00 fit and the reader-connection part of S-04 |
| `claim_mode`: `direct_audience_claim` / `bounded_external_case` | **A seed of the Interpretation Boundary.** It encodes whether an interpretation may transfer to the configured audience or must stay attributed to the external case |
| `research_condition_handling`: acknowledged / bounded / resolved / excluded_from_angle, per uncertainty or contradiction | Limits and concession candidates in E-09 |
| `defensible_perspective`, `supported_editorial_angle` | **Conflict.** An angle chosen here, before the boundary and per signal, contradicts the map: the angle is a destination strategy field (S-08) |
| `criterion_results` (profile-defined, evidence-cited) | Lens participation (Persistent inputs §3), not strategy selection |

**Provisional verdict: split.** The fit, relevance and claim-mode parts are reused as inputs to S-00 and S-04. The angle and perspective fields are disabled as decisions: at most they can be recorded as a hint.

### 4.3 Run spine: `src/run/*`, `src/intake/*`, `src/artifacts/provenance.py`

| Seam | What it gives | Target use |
|---|---|---|
| `RunContext` | Immutable UUID4 `run_id`, assignment, strategy reference and version, execution mode, configuration identity | E-19 run trace header. **Reuse** |
| `ContentAssignment`, `CorrelationMetadata` | Typed intake of one signal | E-01 source signal. **Reuse**, with one addition (§5, OPEN-21) |
| Artifact layout `reports/content_packages/<signal_id>/runs/<run_id>/*.json` | Create-once, immutable artifacts per run | Basis for step 3 storage. **Needs a unit dimension** (see ADR in `02_ARCHITECTURE_DECISIONS.md`) |
| `verify_run_provenance`, `CodeIdentity` | Proof that a run's artifacts belong together and came from clean tracked code | Trace integrity. **Reuse** |
| `RunCallBudget` | A per-run model-call ceiling by editorial role | The budget part of ARP §6.3 limits (OPEN-22). **Reuse** |
| `DecisionPolicyRecord` | Records the policy under which decisions were made | Precedence recording candidate. **Examine in step 2** |

### 4.4 Stage observability: `src/run/stage_routing.py` (#279)

It records per stage what client material was routed, and hashes each model request to prove whether it actually carried that material (`contained` / `missing`). It stores no prompts or text.

**Provisional verdict: reuse** as the mechanism behind trace item 1 (input versions) and the precedence record. Its "was the rule present" check is exactly what the target needs to prove that a stage decided with the knowledge it claims.

### 4.5 Publication boundary: `src/publishing/*`

| Seam | Target use |
|---|---|
| `release_scope.py`: `R1_PUBLISH_CHANNELS = (wix, linkedin)` | **AS-IS fact** about the current production release, not a target constraint. In the target it survives only as the migration-time **rollout scope** (which destination capabilities are switched on in a deployment). Target destinations are all six (patch CANONICAL-SCOPE) |
| `preflight.py`: per-channel ALLOW/BLOCK before any external call | Downstream of S-13. **Reuse** unchanged |
| `idempotency.py`: prior-publication detection by digest | Part of V-T05 (no near-exact republication). **Reuse** |
| `package.py`: frozen Wix and LinkedIn packages; `bind_canonical_article_url` | **Reuse** for the publication-order dependency. The target must separate *content derivation* (forbidden by I-06) from *publication dependency* (allowed: a post may link to the article) |

### 4.6 Plan and contract seams: `editorial_plan.py`, `plan_decisions.py`, `client_contracts.py`

The REPO_TRACK covers these in detail. One point matters for Step 1: the client contract declares `ending_mode` and `claim_strength_ceiling` as **scalar slots for every run** (`PLAN_SCALAR_SLOTS`), and forbids contracts from stating run-derived slots (`PLAN_RUN_SLOTS`).

- The ceiling as a client setting fits tier 2.
- A fixed `ending_mode` per client conflicts with the map, where the ending intention is a strategy field chosen per destination.
- The run-slot refusal is a good existing guard. The target keeps the principle: **a contract cannot pre-state what only the run can find**.

## 5. What this means for the next steps

1. The REPO_TRACK stays the reference for the editorial path. It is **not superseded**, only supplemented by §3–4 of this document.
2. Step 1 builds E-02…E-04 on the existing research contract, and E-01 and E-19 on the run spine.
3. The biggest single gap confirmed in code: **interpretation, uncertainty and contradiction exist as types but have no producer and are dropped at the editorial boundary.** That is where S-04 attaches.
4. The Decision Lens (#58) gate overlaps S-00 and S-04. Its angle field conflicts with S-08. Step 5 must settle this seam explicitly. Otherwise two components will decide the angle.
5. Current production (R1) publishes only through the canonical publishers for Wix and LinkedIn (one legacy path excepted, Step 5 §0). No slice may break current production while the canonical engine is built. The **target** is one canonical engine publishing to all six sibling destinations; destinations are enabled capability by capability (Step 5 §3), not by keeping Wix + LinkedIn as the product scope.

---

## Кратко по-русски (для Светы)

- С момента прошлого исследования (`87ea0f4`) в коде **ничего не менялось**. Добавились только наши документы и один файл с дневными данными. Всё, что мы писали о текущем движке, по-прежнему верно.
- Прошлое исследование было **неполным**. Оно смотрело на то, как пишется статья, а сбор фактов и «ворота» перед редакцией описало одной строкой. Сейчас я посмотрела их подробно.
- **Главная находка.** В коде уже есть аккуратная типизированная схема: источник → наблюдение → доказательство → интерпретация → неопределённость → противоречие. Это почти ровно наше «ядро доказательств». Но верхние слои (интерпретации, неопределённости, противоречия) **никто не заполняет**, а при переходе к редакции они и вовсе выбрасываются. Именно сюда встанет наша «граница интерпретаций».
- Есть ещё отдельные «ворота решения» (#58). Они уже умеют сказать «не публиковать» без участия человека и различают «утверждаем про нашего читателя» и «это чужой кейс, переносить нельзя». Это полезно. Но там же выбирается угол, а по нашей карте угол выбирается позже и отдельно для каждой площадки. Этот конфликт надо будет развести.
- Сейчас движок **публикует** только Wix и LinkedIn. Остальные четыре площадки готовятся, но не публикуются. При переделке это сохраняется.
