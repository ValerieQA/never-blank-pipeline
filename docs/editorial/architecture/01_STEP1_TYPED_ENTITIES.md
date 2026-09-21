# Step 1 · Typed entities and schemas E-01…E-19

*Implementation architecture, step 1 of 6 · 21 September 2026 · design authority: `CANONICAL_EDITORIAL_MAP_v1.md` · decisions: `02_ARCHITECTURE_DECISIONS.md` (AD-01…AD-10) · current-engine evidence: `00_STEP0_ARCHITECTURE_IMPACT_DELTA.md`*

This document defines **what each entity contains**: its fields, types, identity and validation rules. It also says which current-engine type it reuses, wraps or replaces.

It does **not** define:

- stage behaviour (Step 2, S-00…S-15 contracts);
- storage layout (Step 3);
- knowledge register format in detail (Step 4);
- migration order (Step 5).

It contains no implementation code. Schemas are written as field tables so that they can be implemented in the existing Pydantic contract style (`_ContractModel`: immutable, forbid extra fields, validated references).

---

## 0. Conventions shared by every entity

### 0.1 Envelope

Every entity carries these fields. They are not repeated in the tables below.

| Field | Type | Rule |
|---|---|---|
| `schema_version` | string | Required. One version per entity type |
| `id` | typed ID (§0.2) | Required. Unique within the run |
| `run_id` | UUID4 | The run that created this version. Taken from `RunContext` |
| `created_at` | UTC datetime | Required |
| `created_by` | StageAttribution (§0.4) | Required |
| `supersedes` | ID of the previous version, or empty | Set when a later stage produces a new version (e.g. the enrichment loop updates the core) |

**Immutability.** Every entity version is create-once. Change means a new version with `supersedes`. Nothing is edited in place. This is the rule the current engine already follows for `research.json` and `decision.json`.

### 0.2 Identifiers

- Typed prefix plus opaque unique part. Prefixes:

  | Prefix | Entity | Prefix | Entity |
  |---|---|---|---|
  | `sig` | signal | `unit` | Editorial Unit |
  | `obs` | source observation | `anc` | anchor |
  | `evc` | evidence claim | `dst` | destination decision |
  | `core` | Evidence Core | `str` | strategy |
  | `feat` | material features | `plan` | plan |
  | `ast` | asset | `txt` | text |
  | `gap` | gap | `fp` | fingerprint |
  | `int` | interpretation | `pob` | publication observation |
  | `bnd` | boundary | `lbl` | label record |

  Knowledge records keep their `K-*` and `V-*` IDs.
- Where the current engine already has an ID for the same thing, it is reused: `evidence_id` → `evidence_claim` ID; `source_id`; `signal_id`; `assignment_id`; `run_id`.
- A reference to an entity from another run is the pair (`run_id`, `id`).

### 0.3 Common value types

| Type | Definition |
|---|---|
| **Confidence** | `high` / `medium` / `low`, plus a short rationale. No numbers: numeric thresholds are OPEN-05 |
| **Strength** | A position on the run's strength ladder (AD-10): `ladder_id` plus an ordinal index. Higher index means a stronger assertion |
| **StrengthLadder** | An ordered list of wording levels. Source: the client contract (`claim_strength_ceiling` values, as today), otherwise the universal default. One ladder per run |
| **Ceiling** | A Strength that nothing below it may exceed |
| **KnowledgeRef** | `record_id`, `record_version`, tier, **file status**, **effective status** (e.g. `weak-candidate` after expiry), `reinforced_by` (a non-expired record, if any), all **as they were at the time of use** (patch S4-R1) |
| **OutcomeRecord** | ARP outcome: `RESOLVE` / `DEGRADE` / `REPLAN` / `SKIP`; `state_code` (one of the §6.2 states); `scope` (signal / unit / destination / publication); reason; knowledge references; precedence application, if any; attempt number and limit. Stored in E-19 and referenced from the entity it concerns |
| **PrecedenceApplication** | Conflict description; winning record, tier and effective status; losing record, tier and effective status; rule applied (map §5; weak-candidate rules, Step 4 §5.1) |
| **Justification** | Free text plus references (to evidence, interpretations, knowledge records) explaining why a field has its value |

### 0.4 Attribution

`StageAttribution` identifies what produced a record:

- stage ID (`S-00`…`S-15`);
- component name;
- decider kind: `model`, `rule` or `code`. This follows the current `EvaluatorKind`, **without** `human_review` in production (I-01, I-02);
- model or rule identity and version;
- request digest (from `stage_routing`).

Prompts and text are never stored in the attribution.

---

## 1. Entity overview

| ID | Entity | Created at | Current-engine basis | Provisional verdict (final in Step 5) |
|---|---|---|---|---|
| E-01 | Source signal | Intake + S-00 | `ContentAssignment`, JSONL signal | **Reuse** + selection record |
| E-02 | Source observation | S-01, S-03 | `SupportReference` + `NormalizedSource` | **Wrap** |
| E-03 | Evidence claim | S-01, S-03 | `ExtractedEvidence` | **Wrap** (AD-05) |
| E-04 | Evidence Core | S-01, versioned in S-03 | `NormalizedResearchArtifact` | **Wrap** |
| E-05 | Material features | S-02, S-03 | none | **New** |
| E-06 | Asset | S-02, S-03 | none (`reader_verifiable_artifact` is a plan slot, not an asset) | **New** |
| E-07 | Gap | S-03 | none | **New** |
| E-08 | Interpretation | S-04 | `ModelInterpretation` (no producer) | **New** (AD-06) |
| E-09 | Interpretation Boundary | S-04 | fragments in #58 gate and in `EditorialPlan` | **New** |
| E-10 | Editorial Unit | S-05 | none | **New** |
| E-11 | Anchor interpretation | S-06 | `central_claim` (copied from CORE_FACT, a bug class) | **Rebuild** |
| E-12 | Destination decision | S-07 | Publishers and packages (AS-IS: packages exist only for Wix, LinkedIn) | **New**. Target: all six destinations. The current `release_scope` is used only as the migration-time rollout scope |
| E-13 | Editorial Strategy | S-08, S-09 | scattered over the Monday stages and `_BLOCK_TABLE` | **Rebuild** |
| E-14 | Executable Destination Plan | S-10, S-11 | `EditorialPlan` (partial) | **Rebuild**, reuse `EditorialPlan.check` ideas |
| E-15 | Text | S-12, S-13 | `generated.json`, publication packages | **Wrap** |
| E-16 | Fingerprint (+ optional label record, post-decision, asynchronous) | S-14 | `PublishedEntry` (hook, echo, topic, cta) | **Rebuild** |
| E-17 | Publication observation | S-15 | `src/analytics/*`, `analytics_score` | **Examine in Step 5** |
| E-18 | Knowledge record (+ check record) | Offline | none (client lenses are rules, not records) | **New** |
| E-19 | Run trace | All | `RunContext`, `stage_routing`, `provenance`, `RunCallBudget` | **Wrap and extend** |

---

## 2. Evidence layer

### E-01 · Source signal

A signal from the queue. It is not evidence: it is the reason research starts.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `signal_id` | string | yes | Existing signal ID |
| `assignment_ref` | `assignment_id` | yes | The `ContentAssignment` it came in as |
| `origin` | string | yes | As today (`is_research_derived` distinguishes research-generated signals) |
| `headline` | string | no | Signal title |
| `source_locators` | list of URL / locator | yes, ≥1 | Feeds `SourceDirective`s |
| `source_published_at` | datetime or `unknown` | yes | Input to freshness |
| `submitted_at` | datetime | yes | |
| `strategy_ref`, `strategy_version` | string | yes | Client configuration identity |
| `selection` | SignalSelection | set by S-00 | See below |

**SignalSelection** (written by S-00):

| Field | Type | Rule |
|---|---|---|
| `candidate_kind` | `signal` / `deferred_unit` | AD-03: deferred units compete with new signals. While split is disabled (cap = 1), only `signal` occurs in production |
| `fit` | `fits` / `outside_contract` / `outside_topics` / `outside_risk_level` | Anything other than `fits` → `SKIP` |
| `relevance` | direct / indirect / irrelevant, plus relevance bases | Reuses the #58 `BusinessAudienceRelevance` and `AudienceRelevanceBasisType` |
| `portfolio_pressure` | list of (fingerprint reference, similarity kind) | Soft (I-12) |
| `selected` | bool + OutcomeRecord | |

### E-02 · Source observation (`source_observation`)

What a source records, attributed to that source. It is never a statement about the world.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `observation_id` | `obs` ID | yes | |
| `signal_id` | string | yes | AD-04: kept per observation |
| `source_ref` | `source_id` → `NormalizedSource` | yes | Must exist in the core |
| `kind` | quote / figure / event / stated_position / document_fact / other | yes | |
| `excerpt` | text ≤ 4000 | yes | Verbatim. Same bound as `SupportReference` |
| `location` | string | no | Section or offset |
| `attribution` | text | yes | The "source X reports Y" form. Code-generated from source and excerpt, not model-written |
| `figure` | Figure | if kind = figure | Value, unit, as-of date, `figure_provenance` (`own` / `third_party`) |
| `is_third_party_assertion` | bool | yes | True when the source reports someone else's claim about the world. Input to feature `contested_assertion` |

**Current mapping.** `SupportReference(source_id, excerpt, location)` plus its `NormalizedSource`. `kind`, `attribution`, `figure` and `is_third_party_assertion` are new fields. They are populated in S-01 alongside the existing extraction.

### E-03 · Evidence claim (`evidence_claim`)

A statement about the world, grounded in one or more source observations, with a verdict.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `evidence_claim_id` | = existing `evidence_id` | yes | |
| `statement` | text | yes | Maps from `ExtractedEvidence.claim` (AD-05) |
| `observation_refs` | list of `obs` IDs | yes, ≥1 | Break = fabrication (I-04) |
| `source_refs` | list of `source_id` | yes, ≥1 | Consistent with the observations |
| `verdict` | accepted / qualified / conflicting / rejected / not_assessed | yes | Existing `EvidenceDisposition` |
| `verdict_rationale` | text ≤ 600 | yes | Existing field |
| `caveats` | list of text | if qualified | `qualified` without caveats is invalid |
| `scope` | who / where / when it holds | yes | Needed for transfer checks (E-08 `audience_transfer`) |
| `strength` | Strength | yes | How strongly the evidence supports it |
| `ceiling` | Ceiling | yes | The lower of the client ceiling and the evidence-derived strength |

**Usability rule.** Only `accepted` and `qualified` claims may be referenced downstream of S-04. This replaces `_USABLE_DISPOSITIONS` with the same meaning.

### E-04 · Evidence Core

Everything known about the signal, with provenance. It is the only source of facts for every later stage (I-03).

| Field | Type | Req. | Rule |
|---|---|---|---|
| `core_id` | `core` ID | yes | |
| `version` | integer | yes | 1 after S-01, +1 per enrichment round |
| `signal_ids` | list | yes, ≥1 | AD-04. Exactly one in current behaviour |
| `research_artifact_refs` | list of (artifact_id, digest) | yes | The `NormalizedResearchArtifact`(s) it wraps. The digest uses the existing `research_artifact_digest` |
| `sources` | list of `NormalizedSource` | yes | |
| `observations` | list of E-02 | yes | |
| `evidence_claims` | list of E-03 | yes | |
| `uncertainties` | list of `UncertaintyAssessment` | no | Existing type, now populated (Step 2) |
| `contradictions` | list of `Contradiction` | no | Existing type, now populated |
| `readiness` | `EvidenceReadiness` | yes | Existing enum |
| `closed_gaps` | list of `gap` IDs | no | Gaps whose closure produced this version |

**Validation.**

- Referential integrity across all lists. The existing artifact already enforces this for its own contents.
- A new version may add items or change verdicts. It may not silently drop an item. Removing an item requires a verdict change to `rejected` with a rationale.

### E-05 · Material features

The feature vector that later knowledge conditions refer to. **No label lives here** (AD-07).

| Field | Type | Req. | Rule |
|---|---|---|---|
| `features_id` | `feat` ID | yes | |
| `core_ref` | (`core_id`, version) | yes | Features are recomputed per core version |
| `values` | list of FeatureValue | yes | Exactly one entry per feature in the map §8.3 list |

**FeatureValue:**

- `feature` is one of: `documented_case`, `named_company`, `figure_provenance`, `method_known`, `freshness`, `mechanism_present`, `real_scene`, `first_person`, `failure_cost`, `contested_assertion`, `parallel_structure`, `open_question`;
- `value`: bool, or an enum for `figure_provenance` (own / third_party / none) and `freshness` (high / medium / low);
- `confidence`;
- `evidence_refs`: required when the value is positive. A positive feature with no reference is invalid. This is the "reference check" of S-02.

### E-06 · Asset

What gives a text something the reader could not get elsewhere.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `asset_id` | `ast` ID | yes | |
| `asset_class` | `evidentiary` / `positional` | yes | |
| `kind` | evidentiary: figure / calculation / document / second_source / first_to_report / other. Positional: `client_position` | yes | |
| `refs` | evidence claim IDs (evidentiary) **or** a contract position ID (positional) | yes, ≥1 | An asset without a reference is invalid |
| `derivation` | inputs (evidence claim IDs) + method | if kind = calculation | Every input must be in the core. A calculation is a derived evidence claim with its own ceiling |
| `strength` | Confidence | yes | |

**Rule.** A positional asset comes only from an **approved** position in the Client Contract. A model cannot create one. If the needed position is missing, the ARP state "client position needed" applies: `DEGRADE` without it, or `SKIP`.

### E-07 · Gap

What is missing, and what the enrichment loop did about it. **Sole producer: S-03** (fix F-3). S-02 does not create gaps; it emits MaterialNotes (free-text missing-material notes with references), which S-03 turns into E-07 only when a note blocks a decision.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `gap_id` | `gap` ID | yes | |
| `kind` | evidence / reader_connection / counter_evidence / asset / figure_provenance / other | yes | |
| `description` | text | yes | |
| `blocks` | what decision it blocks (stage ID + what) | yes | Only gaps that block a decision are opened. This prevents endless enrichment |
| `search_directives` | list of `SourceDirective` | if searched | Reuses the existing provider request type |
| `attempts` | integer | yes | Against the loop limit (OPEN-22) |
| `status` | open / closed / abandoned | yes | |
| `closure` | resulting `core` version | if closed | |
| `stop_reason` | limit_reached / budget_exhausted / nothing_found / not_needed | if abandoned | |

---

## 3. Interpretation layer

### E-08 · Interpretation (`interpretation`)

What the evidence means. The layer where most AI-shaped errors live (map walkthroughs A–C).

| Field | Type | Req. | Rule |
|---|---|---|---|
| `interpretation_id` | `int` ID | yes | |
| `statement` | text | yes | |
| `kind` | cause / generalization / comparison / consequence_for_reader / forecast / mechanism / other | yes | |
| `support_refs` | evidence claim IDs | yes, ≥1 | Only usable claims (E-03) |
| `counter_refs` | evidence claim IDs | no | What argues against it |
| `depends_on` | interpretation IDs | no | Premise relation. AD-03 uses it to test independence |
| `audience_transfer` | `direct_audience` / `bounded_external_case` | yes | AD-08. `direct_audience` requires support whose scope covers the configured audience |
| `strength` | Strength | yes | |
| `ceiling` | Ceiling | yes | ≤ the lowest ceiling among the supporting claims |
| `limits` | list of Limitation | no | Text + refs. Concession candidates |
| `admissibility` | `admissible` / `inadmissible` | yes | |
| `inadmissible_reason` | unsupported / exceeds_ceiling / transfer_not_supported / invented_scene / contradicted / other | if inadmissible | |
| `temptation_note` | text | if inadmissible | Why a writer would reach for it. Detection material for V-T02. V-T02 also checks the text for inadmissible interpretations that are not on the list: the list strengthens detection but does not bound it |
| `rationale` | Justification | yes | |

**Validation.**

- `strength` ≤ `ceiling`, otherwise the interpretation is inadmissible with reason `exceeds_ceiling`.
- An interpretation of kind `consequence_for_reader` with `audience_transfer = direct_audience` requires at least one supporting claim scoped to the configured audience. Otherwise it is inadmissible with reason `transfer_not_supported`.

### E-09 · Interpretation Boundary

What the texts of this signal may and may not mean.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `boundary_id` | `bnd` ID | yes | |
| `core_ref` | (`core_id`, version) | yes | The final core version after enrichment |
| `relevance_ref` | RelevanceAssessment (`decision.json`) ID and digest | yes | Fix F-6: the relevance evidence the reader connection and `audience_transfer` defaults came from |
| `version` | integer | yes | 1 at the first S-04 run; +1 per boundary commit (Step 2, S-04) |
| `admissible` | list of (`interpretation_id`, `version`) | yes | Exact E-08 versions. Empty → `SKIP` with state "no admissible interpretation" |
| `inadmissible` | list of (`interpretation_id`, `version`) | yes | Every inadmissible interpretation generated or explicitly tested by S-04 is recorded. S-04 must deliberately probe for likely tempting interpretations; completeness is not assumed. The list is evidence of what was tested, not a claim that every tempting interpretation was found |
| `limits` | list of Limitation | no | Boundary-level limits: e.g. "single case", "no second source" |
| `ambiguities` | list of Ambiguity | no | Which interpretations a contradiction affects. Whether it touches the anchor is decided at S-06 |
| `reader_connection` | text + refs | yes | How the material connects to the Audience Profile. Empty is allowed only together with a `SKIP` |
| `outcome` | OutcomeRecord ref | yes | `RESOLVE` / `DEGRADE` / `SKIP` |

**Validation.** No interpretation is in both lists. Every interpretation in `admissible` passes the E-08 rules.

**Versioning (patch R2).** Every E-09 version is a complete snapshot of exact E-08 versions. A newly discovered interpretation is a new E-08 record. A reclassified one is a new version of the existing E-08. An E-08 version and the E-09 version that first references it are written together (the boundary commit, Step 2 S-04).

**Where context does not enter.** Client rights to speak, lens and portfolio do **not** enter the boundary (round 4, §5.3). The boundary answers "what is true", not "what suits us". Only the Audience Profile enters, for the reader connection.

---

## 4. Unit and destination layer

### E-10 · Editorial Unit

One story with one anchor. It can outlive its run (AD-03).

| Field | Type | Req. | Rule |
|---|---|---|---|
| `unit_id` | `unit` ID | yes | |
| `signal_ids` | list | yes, ≥1 | AD-04 |
| `core_ref`, `boundary_ref` | refs | yes | |
| `interpretation_scope` | admissible interpretation IDs | yes, ≥1 | The part of the boundary this unit may use |
| `anchor_ref` | `anc` ID | after S-06 | |
| `status` | active / deferred / skipped / completed / expired | yes | |
| `expires_at` | datetime | if deferred | Derived from evidence freshness |
| `split` | SplitRecord | if the unit came from a split, or a split was evaluated | Sibling unit IDs; the result of rules 1–3 of AD-03; `split_candidate` flag when the cap prevented the split. With cap = 1 (current), only the flag and the rule results are written; no sibling unit exists |

### E-11 · Anchor interpretation

| Field | Type | Req. | Rule |
|---|---|---|---|
| `anchor_id` | `anc` ID | yes | |
| `unit_id` | ref | yes | |
| `interpretation_ref` | admissible (`interpretation_id`, `version`) in the unit's scope | yes | |
| `boundary_ref` | E-09 version the anchor was chosen against | yes | Patch R2: the anchor is invalid when a newer E-09 version lists its interpretation as inadmissible |
| `strength_used` | Strength | yes | ≤ interpretation ceiling. `DEGRADE` may lower it, never raise it |
| `leading_material` | 1–2 refs to evidence claims or assets | yes | AD-01. A second item is allowed only if both support the anchor |
| `candidates` | list of (interpretation ID, reason chosen or not) | yes | |
| `ambiguity_touches_anchor` | bool | yes | Drives the ARP row "evidence conflicts in the anchor" |
| `outcome` | OutcomeRecord ref | yes | |

**Replaces** `central_claim`, which is currently copied from CORE_FACT rather than chosen (REPO_TRACK A4).

### E-12 · Destination decision

The destination itself is an enumeration: `wix`, `linkedin`, `facebook`, `instagram`, `threads`, `telegram`. Static destination knowledge (length norms, policy, ranking) is **not** part of this entity. It lives in `K-DST-*` records (E-18).

The entity is the per-unit **decision** made at S-07 (AD-02):

| Field | Type | Req. | Rule |
|---|---|---|---|
| `destination_decision_id` | `dst` ID | yes | |
| `unit_id` | ref | yes | |
| `destination` | enum | yes | |
| `eligibility` | eligible / excluded | yes | |
| `exclusion_rule` | contract_disabled / contract_topic / contract_risk / hard_platform_policy / cadence | if excluded | Always a rule with a tier, never "model judged" |
| `exclusion_ref` | contract rule ID or KnowledgeRef | if excluded | |
| `mode` | publish / generate_only | if eligible | `publish` when the contract enables the destination, it is capable, and the rollout scope includes it (AD-02). Target: all six publish. `generate_only` is a temporary migration state, or a contract choice |
| `publication_dependencies` | list of (target destination, kind = `link`) | no | Publication order only. Never content derivation (I-06) |
| `outcome` | OutcomeRecord ref | yes | |

### E-13 · Editorial Strategy

A composite configuration for one destination of one unit. Candidates and the chosen strategy share one schema.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `strategy_id` | `str` ID | yes | |
| `unit_id`, `destination` | refs | yes | |
| `candidate_set_id` | ID | yes | Groups the 2–4 candidates of one S-08 call |
| `anchor_ref` | `anc` ID | yes | Must equal the unit's anchor (I-07) |
| `boundary_ref` | E-09 version the strategy was built against | yes | Patch R2 |
| `second_interpretation_ref` | `int` ID | no | Must be admissible and in the unit's scope |
| `editorial_job` | text | yes | Open description. No enum (I-10) |
| `angle` | text | yes | The reader's question |
| `editorial_thesis` | text + interpretation refs | yes | Its ceiling is the minimum over the referenced interpretations |
| `focal_subject` | kind (company / owner_reader / client / person_in_story) + text + refs | yes | `person_in_story` requires a documented case in the core |
| `leading_material_ref` | ref | yes | Must be a member of the anchor's `leading_material` (AD-01). It is the strategy's **primary evidentiary carrier**: at least one move of the reader path references it. It does **not** have to be in the opening or the first line; the opening is decided independently below |
| `reader_path` | ordered list of Move | yes, ≥2 | Move = text, purpose, refs (interpretation / evidence claim / asset). Each move has at least one reference |
| `opening` | what comes first + refs + `held_back` (which variable is withheld) | yes | |
| `reveal` | immediate / gradual / delayed + `until_move` index | yes | `delayed` requires `until_move` |
| `concession` | present: bool; limitation ref; move index | yes | If present, the limitation must be in the boundary |
| `ending_intention` | text | yes | Recorded after the opening (map §7.1). Any per-client fixed `ending_mode` becomes a tier-2 constraint on it, not a value (Step 0 §4.6) |
| `client_position_ref` | positional asset ID | no | Only from the contract (E-06) |
| `justifications` | map from field name to Justification | yes | Every field above has one |
| `knowledge_used` | list of KnowledgeRef | yes | Which records shaped the candidate |

**Roles are not stored on E-13** (fix F-1). E-13 is immutable. Whether a candidate was chosen or excluded is recorded only in StrategySelection.

**StrategySelection** (one per `candidate_set_id`, written by S-09):

- `admissible`: strategy IDs;
- `excluded`: list of (strategy ID, reason, KnowledgeRef, tier);
- `chosen`: strategy ID;
- `deciding_tiebreaker`: one of the map §7.3 criteria, in order (evidence_fit, destination_fit, interpretation_risk, asset_strength, client_preference, portfolio, cost);
- `precedence_applications`: list;
- `outcome`: OutcomeRecord ref.

**There is no label field.** Labels are written afterwards (label record, E-16) and are never inputs to S-00…S-13 (AD-07).

### E-14 · Executable Destination Plan

The chosen strategy plus adaptation. By the decision-vs-adaptation criterion, adaptation may not change any E-13 field.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `plan_id` | `plan` ID | yes | |
| `strategy_ref` | chosen `str` ID | yes | |
| `destination`, `mode` | from E-12 | yes | |
| `format` | article / post / carousel / thread / channel_post / other | yes | |
| `length_target` | range, unit (words / characters / slides) | yes | |
| `first_line_mechanics` | text | yes | e.g. preview cut-off, first slide |
| `segments` | ordered list of (segment, the moves it carries) | yes | Every move of the reader path is carried by at least one segment |
| `subheadings` | yes / no + plan | article formats | Subject to client rule OPEN-03 during setup |
| `hashtags` | policy + list | no | |
| `cross_destination_link` | target destination + the interpretation the link promises | no | Always **conditional** (Step 2 R-2). The text must deliver its promise without the link. The link is bound at S-14 only if the target was published; otherwise it is omitted (`DEGRADE`) |
| `citations` | source IDs to cite | yes | Only from the core |
| `voice_brief_ref` | ref to the client voice document version | yes | |
| `exemplars` | list of (reference library item ID, "take" note, "do not copy" note) | no | Empty in the draft (S-10). Filled in the approved version (S-11) |
| `forbidden` | phrases and construction types in force | yes | Resolved from the contract (tier 2) and hard policy (tier 1) |
| `stage_of_version` | `draft` (produced by S-10) / `approved` (produced by S-11) | yes | An approved version `supersedes` its draft. Only an approved version goes to S-12 |
| `attempt` | integer | yes | Against the replan limit |

**PlanVerdict** (fix F-2; one per plan draft, sole producer S-11): `plan_ref` (draft ID and version); `boundary_ref` (the E-09 version checked against); CheckResults V-P01…V-P05; result `pass` / `fail`; route and counter; `approved_plan_ref` when it passed. Check results and pass/fail are **not** stored on E-14.

**Current mapping.** `EditorialPlan` holds some of these as run-wide slots (`claim_strength_ceiling`, `ending_mode`, `factual_restrictions`, `acknowledged_limits`, `banned`, `reader_verifiable_artifact`). In the target they split three ways:

- the ceiling goes to E-03/E-08;
- limits go to E-09;
- restrictions and bans go to `forbidden` here.

`EditorialPlan.check()` and `forbidden_in()` are candidates to reuse as V-T01/V-T06 mechanics (Step 5).

---

## 5. Text, publication and learning layer

### E-15 · Text

| Field | Type | Req. | Rule |
|---|---|---|---|
| `text_id` | `txt` ID | yes | |
| `plan_ref` | approved `plan` ID | yes | |
| `destination` | enum | yes | |
| `title`, `dek` | text | article formats | |
| `body` | text | yes | |
| `segments` | ordered text parts | multi-part formats | Aligned to the plan's segments |
| `links` | list of URLs | no | Each is a source in the core or a canonical URL of a sibling destination |
| `writer_signal` | `plan_holds` bool + reason | yes | `false` → `REPLAN` → S-08, not improvisation |
| `version` | integer | yes | +1 per edit. Edits route by I-09 |
| `content_digest` | sha256 | yes | Used by idempotency and V-T05 |

**Current mapping.** `generated.json`, and the frozen `WixPublicationPackage` / `LinkedInPublicationPackage` are built from an accepted E-15. The packaging and preflight code stays downstream (Step 0 §4.5).

**TextVerdict** (fix F-2; one per text version, sole producer S-13): `text_ref` (ID and version); `plan_ref`; `boundary_ref`; CheckResults V-T01…V-T08 and V-S01…V-S10; result `accepted` / `edit` / `replan` / `skip`; route and counter. Status and check results are **not** stored on E-15.

**CheckResult** (shared by PlanVerdict and TextVerdict): check ID; rule status and class at the time of the run; method (code / model against an explicit criterion); pass / fail; findings with references; route taken; for V-T01 and V-T08, `fault_owner` (`writer` / `plan`), the branch name and the criterion applied (patch R2).

### E-16 · Fingerprint and label record

**Fingerprint.** What Portfolio Memory remembers about a published or generated text.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `fingerprint_id` | `fp` ID | yes | |
| `client`, `destination`, `unit_id`, `text_ref`, `content_digest` | refs | yes | |
| `mode` | publish / generate_only | yes | Generated-only texts are remembered too, flagged |
| `features` | snapshot of E-05 values | yes | |
| `strategy` | snapshot of E-13 fields, normalized for comparison | yes | |
| `adaptation` | snapshot of E-14 adaptation fields | yes | |
| `text_profile` | position of the first evidence, paragraph and sentence length distribution, and other V-S02/V-S04 metrics | yes | |
| `deciding_tiebreaker` | from StrategySelection | yes | |
| `label_ref` | `lbl` ID | no | Filled in when a label record exists. A fingerprint without labels is valid |
| `publication` | platform, external ID, URL, published_at | if published | Reuses `PlatformPublication` |

**Label record.** Written after the decision (AD-07). **Label generation is post-decision observability.** It must not be required for successful generation or publication, and it is not a synchronous step of the run. It may be code-based, batched, asynchronous (e.g. a periodic job over fingerprints), or omitted when unavailable. A run with no label record is complete. Consumers of labels (V-S06, V-S07, portfolio reports) treat missing labels as missing data, not as failure.

| Field | Type | Rule |
|---|---|---|
| `label_id` | `lbl` ID | |
| `targets` | features ID, strategy ID | |
| `material_label`, `strategy_label`, `form_label` | text from a closed vocabulary kept in the knowledge register | |
| `classifier` | StageAttribution | Separate from the planner. `decider_kind` may be `code`, `rule` or `model`; no model call is required |
| `written_after` | timestamp of the StrategySelection | A label written before the selection is invalid |

**Access rule.** Label records are never routed to S-00…S-13. `stage_routing` records the absence, so I-10 can be checked per run.

**Current mapping.** `PublishedEntry` (hook, echo, topic, cta_mode, analytics_score) is superseded as a portfolio source. It stays as the publication index until migration (Step 5).

### E-17 · Publication observation

Named "publication observation" to avoid confusion with `source_observation`.

| Field | Type | Req. | Rule |
|---|---|---|---|
| `publication_observation_id` | `pob` ID | yes | |
| `fingerprint_ref` | ref | yes | |
| `destination` | enum | yes | |
| `metrics` | list of (name, value, window, collected_at, collector identity and version) | yes | Raw values. No blended score |
| `confounders` | topic, timing, author reach, news hook, paid promotion | yes | Unknown values are marked `unknown`, not omitted |

**KnowledgeQueueItem** (proposal to the keeper): `kind` (`observation` / `vt02_feedback` / `expiry_review`); referenced observations or findings; target `K-*` record; proposed status change; evidence summary. Producers by kind: S-15 (`observation`, `vt02_feedback`); the offline Knowledge Maintenance job (`expiry_review`), patch S4-R1. Only the keeper changes status, offline (I-02). **Metrics never change status or thresholds automatically** (I-12).

### E-18 · Knowledge record and check record

The field set is fixed by the map §8.1. The detailed format (conditions language, file layout, review workflow) is Step 4.

| Field | Type | Rule |
|---|---|---|
| `record_id` | `K-*` | Stable across versions |
| `version` | integer | |
| `statement` | text | |
| `source` | citation(s) | |
| `evidence_class` | REPO / RES / PLAT / VEND / OBS / CLIENT / OWNER / NBX-engine / NBX-map / INF | |
| `confidence` | Confidence | |
| `applies_when` | condition over **features, boundary facts, destination and strategy fields** | Never over labels (I-10). Enforced by the condition schema in Step 4 |
| `conflicts` | record IDs | |
| `status` | one status (invariant / client rule / descriptive / candidate / …) | Exactly one |
| `tier` | 0a / 0b / 0c / 1 / 2 / 3 / 4 / 5 / 6 / A | Exactly one |
| `influences` | stage IDs and entity fields it may shape | |
| `verified_at`, `review_by` | dates | Required for `K-DST-*`. After `review_by` the record is automatically demoted to a weak candidate (map §6.2) |

**Check record** (`V-P*`, `V-T*`, `V-S*`): check ID; statement; class (H / S); **rule status** (separate from method); **detection method**; route on failure; the knowledge records it enforces. A soft (S) check has no threshold unless the owner approves one (I-12).

### E-19 · Run trace

The complete record of one production run (map §11). Storage layout is Step 3.

| Part | Content | Current basis |
|---|---|---|
| Header | `run_id`, assignment, strategy reference and version, execution mode, configuration identity, code identity | `RunContext`, `CodeIdentity` — **reuse** |
| Input versions | Client Contract, Audience Profile, lens, knowledge register version, platform knowledge with dates, reference library — each with a digest | `ConfigurationIdentity`, lens digests in `stage_routing` — **extend** |
| Stage records | Per stage: input refs, output refs, attribution, routing evidence (routed / contained / missing), calls and tokens, duration | `stage_routing`, `RunCallBudget` — **extend** |
| Outcome log | Every OutcomeRecord in order | **New** |
| Precedence log | Every PrecedenceApplication | **New**. `DecisionPolicyRecord` to be examined in Step 2 |
| Check log | Every CheckResult | Partly in `editorial_acceptance.json` — **extend** |
| Entity index | Every entity ID created in the run, by type and version | **New** |
| Integrity | Digests linking the parts; provenance verification | `verify_run_provenance` — **extend** |

**Indicators** (map §11) are computed from traces, not stored in them.

---

## 6. Cross-entity invariants: where each is enforced

| Invariant | Enforced by schema | Checked at |
|---|---|---|
| I-01 no human wait | `StageAttribution.decider_kind` has no human value. Every unresolved state writes an OutcomeRecord | Every stage; trace audit |
| I-02 humans only at setup and offline | Knowledge status changes only through KnowledgeQueueItem → keeper | E-17/E-18 |
| I-03 facts only from the core, within the ceiling | E-13 moves, E-14 citations and E-15 links reference core IDs; ceilings on E-03/E-08 | V-T01, V-T04 |
| I-04 unbroken chain | thesis → interpretation IDs → evidence claim IDs → observation IDs, all required, non-empty | V-T03, and schema validation at S-10 |
| I-05 no inadmissible interpretation | Strategy may reference only `admissible` IDs. `inadmissible` list with `temptation_note` feeds detection | V-P02, V-T02 |
| I-06 siblings | No entity has a field pointing to another destination's **text** as input. `publication_dependencies` carry order only | Schema; V-P03 |
| I-07 one anchor per unit | `E-13.anchor_ref` must equal `E-10.anchor_ref` | Schema; V-P03 |
| I-08 decisions before prose | E-15 requires an `approved` E-14 | S-12 precondition |
| I-09 failure routes to its layer | CheckResult records the route. The route table is in the check record | S-11, S-13 |
| I-10 labels after the decision | Label record separate, `written_after` rule, never routed to planners | Trace (`stage_routing`) |
| I-11 knowledge is not a routing table | `knowledge_used` and exclusions with KnowledgeRef on every strategy | Trace |
| I-12 soft signals do not become thresholds | S-check records carry no threshold without owner approval | E-18 |
| I-13 research findings do not become hard checks | Check record status changes only through the keeper | E-18 |

---

## 7. What Step 1 leaves to later steps

| Item | Step |
|---|---|
| Which stage produces E-08 inadmissible interpretations, and whether in the same call as admissible ones | 2 |
| Exact S-00 contract for choosing between new signals and deferred units | 2 |
| Keys, paths and retention for run artifacts, units that outlive runs, fingerprints | 3 |
| Wording of the universal default strength ladder (AD-10) | 4 |
| Condition language for `applies_when` | 4 |
| Final reuse / wrap / disable / rebuild verdict per current component, including the #58 gate, legacy memory and the analytics collectors | 5 |

---

## Кратко по-русски (для Светы)

- Описаны все 19 сущностей системы: из каких полей состоит каждая, что обязательно, какие правила проверяются и из какой части текущего кода она строится.
- **Строим на существующем, где это оправдано.** Источники, наблюдения, доказательства и ядро фактов оборачивают уже работающий код сбора фактов. Паспорт прогона (идентификатор, версии, учёт вызовов, запись того, какие правила дошли до какой стадии) тоже уже есть, его расширяем.
- **Новое:** признаки материала, активы, пробелы, интерпретации, граница интерпретаций, редакционная единица, решение по площадкам, стратегия, отпечаток текста, записи знания.
- **Переделываем:** «центральный тезис». Сейчас он просто копируется из главного факта; в новой системе это выбранная якорная интерпретация. Стратегию текста, которая сейчас размазана по восьми стадиям и жёсткому порядку блоков, тоже собираем заново.
- **У каждого инварианта карты есть место, где он держится в схеме.** Например, у стратегии физически нет поля «метка». Метки пишутся отдельно, после решения, и планировщику их не передают, а журнал прогона это доказывает.
- В интерпретацию добавлено важное поле: можно ли переносить вывод на нашего читателя или это чужой кейс. Ровно на этом движок ошибался в реальных текстах.
