# Step 2 · Stage contracts S-00…S-15

*Implementation architecture, step 2 of 6 · 21 September 2026 · design authority: `CANONICAL_EDITORIAL_MAP_v1.md` · entities: `01_STEP1_TYPED_ENTITIES.md` (with patch R1) · decisions: `02_ARCHITECTURE_DECISIONS.md` (AD-01…AD-10) · current-engine evidence: `00_STEP0_ARCHITECTURE_IMPACT_DELTA.md`*

This document defines what each stage of the target Editorial Core must do. For each stage it says what goes in, what comes out, who decides, what can go wrong, and where each failure is routed.

It resolves U-1, U-2 and U-3 (§4), checks the stages as one system (§5), gives the model-call cost (§6), and lists refinements to earlier documents (§7).

**Out of scope:** storage layout (Step 3), the knowledge register format (Step 4), migration order (Step 5), slices (Step 6). No implementation code.

**Accepted decisions preserved** (verified in §5.6):

- S-07 is deterministic.
- Labels never enter S-00…S-13.
- Destination openings stay independent.
- Split execution is OFF at cap = 1.
- No stage waits for a human.
- Failures route to the layer that made the wrong decision, not to the Writer.

---

## 0. Conventions and global rules

### 0.1 How each contract is written

Every stage in §1–§3 has the same fields:

| Field | Meaning |
|---|---|
| **Purpose / authority** | What the stage decides, and what it is forbidden to decide |
| **Inputs** | Typed entities (E-*) and persistent inputs, each marked *required* or *optional* |
| **Outputs** | Entities this stage is the **only** producer of (see §5.1) |
| **Pre / post** | Conditions that must hold before the stage runs and after it finishes |
| **Invariants** | *Enforces*: the stage is where the invariant is checked. *Depends on*: the stage assumes an earlier stage enforced it |
| **Knowledge / config** | Knowledge record families, contract sections, configuration |
| **Decider** | `code` (deterministic logic), `rule` (declared contract or policy rule applied by code), `model` |
| **Calls** | Model-call structure. Counted in §6 |
| **ARP outcomes and routes** | Every unresolved state → outcome → exact target |
| **Limits** | Which attempt counter the stage consumes, and what happens when it runs out |
| **Trace (E-19)** | What the stage writes to the run trace |
| **Seam** | Current-engine component reused, wrapped or replaced. Provisional: final verdicts in Step 5 |
| **Publication** | Effect on what is published or only generated, where relevant |

### 0.2 Execution scopes and barriers

Stages run at five scopes:

| Scope | Stages | Runs once per… |
|---|---|---|
| Signal | S-00, S-01, S-02, S-03, S-04, S-05 | run |
| Unit | S-06, S-07, and the unit-level part of S-11 (V-P03) | Editorial Unit. With cap = 1: once per run |
| Destination | S-08, S-09, S-10, S-11 (per-destination checks), S-12, S-13 | eligible destination of the unit |
| Publication | S-14 | accepted text |
| After the run | S-15, the label job | publication, asynchronously |

**Barrier B1 (plan barrier).** V-P03 compares the plans of all destinations of a unit. It runs only when every destination that has not been skipped holds a plan that has passed its per-destination checks. No text is written before B1 passes for that destination's unit. Plans are cheap; prose is not.

**Destination order.** Destinations are processed in this order, wherever order matters (budget exhaustion, publication):

1. the order of `publication_dependencies`: a destination that others link to goes first (with the default Client Contract, Wix, because the social posts may link to the article);
2. otherwise the Client Contract's listed order;
3. during migration only: `publish` destinations before `generate_only` ones, so that under a tight budget the destinations that are actually published are protected first.

### 0.3 Attempt counters and limits

Every backward route consumes a named counter. The values below are **initial defaults**. The numbers are tunable implementation parameters (OPEN-22); the counters and what happens at exhaustion are part of this contract.

| Counter | Scope | Default | Consumed by | On exhaustion |
|---|---|---|---|---|
| `L_enrich` | signal | 2 rounds | S-03 enrichment rounds | Stop enrichment. S-04 runs on the current core. If there is no admissible interpretation there → `SKIP` signal |
| `L_boundary` | unit | 1 | Re-entry into S-04 from S-13 (a new inadmissible interpretation found in a text) | The destination whose text caused it → `SKIP` destination (reason `boundary_reentry_exhausted`) |
| `L_anchor` | unit | 1 | Re-entry into S-06 (all destinations failed planning, or the anchor was invalidated at S-04 re-entry) | `SKIP` unit |
| `L_strategy` | destination | 2 | Every return to S-08 for that destination, whatever the cause (S-11 plan failure, V-P03 deviation, writer "plan does not hold", structural text failure, boundary re-entry) | `SKIP` destination |
| `L_edit` | text | 1 per approved plan | S-13 → S-12 edits (phrasing, facts) | `SKIP` publication for that destination |
| `RunCallBudget` | run | Sized for the six-destination canonical run from shadow measurements (§6). AS-IS: the current engine's ceiling is 40 | Every model call | See §0.4 |

The counters are recorded in each OutcomeRecord (`attempt`, `limit`).

### 0.4 Budget exhaustion

The current engine raises `RunCallBudgetExceededError` before the refused call and fails the run closed. The target keeps the "refuse before paying" property but turns the stop into ARP outcomes, so that finished work is not thrown away:

1. The call that would exceed the budget is not made.
2. The unit of work that needed it ends in `SKIP` with reason `budget_exhausted`: the destination if the call was destination-scoped, otherwise the unit or the signal.
3. Destinations not yet started end in `SKIP` (`budget_exhausted`), in reverse destination order (§0.2).
4. Texts already accepted at S-13 continue to S-14. S-14 makes no model calls.

This is a deliberate behaviour change from the current engine. It is recorded as refinement **R-3** in §7.

### 0.5 No human in the run

- No stage has a `human` decider.
- No outcome waits.
- Every non-pass result ends in one of the four ARP outcomes with a recorded reason.
- Preflight `BLOCK` and gate stops are `SKIP` outcomes.

### 0.6 Routing principle (I-09)

| Failure | Returns to |
|---|---|
| Phrasing or a fact misquoted from the core | S-12 edit, same approved plan |
| An unsupported fact that can be removed without breaking the plan; an ending that recaps although its approved intention is valid | S-12 edit, same approved plan |
| An unsupported fact the plan cannot do without; an ending intention that is itself a recap | S-08 (the approved strategy or plan owns the fault) |
| Structure, plan execution, promise, consistency across destinations | S-08, new strategy for that destination |
| Interpretation not admissible or not in the boundary | S-04 re-entry, then S-06 if the anchor fell, otherwise S-08 |
| Lack of material | S-03 enrichment, or `SKIP` |

**The Writer is never asked to repair a decision it did not make.**

### 0.7 Trace duties common to every stage

Every stage writes a **StageRecord** to E-19:

- stage ID and scope key (signal / unit / destination / text);
- input entity references with versions;
- output entity references;
- `StageAttribution`;
- routing evidence from `stage_routing`: which records and contract material were routed, and whether each request contained them;
- model calls and tokens;
- duration;
- every OutcomeRecord and PrecedenceApplication produced.

Stage entries below list only what is **specific** to the stage.

**Routing prohibition.** For S-00…S-13, `stage_routing` also declares label records as *forbidden*. A request containing label vocabulary from the label record is recorded as a violation (AD-07).

---

## 1. Evidence and interpretation stages (signal scope)

### S-00 · Signal selection

| Field | Contract |
|---|---|
| **Purpose / authority** | Decide whether this signal (or a deferred unit) is worth a run for this client. It decides fit and relevance only. It must not decide an angle, a story or a destination |
| **Modes** | *Assigned* (the run starts with one signal; S-00 accepts or skips it. This is also how the current engine starts runs). *Queue* (future: S-00 picks one candidate from signals and non-expired deferred units, per U-2) |
| **Inputs** | E-01 (required; from intake via `ContentAssignment`); Client Contract: topics, risk level, fit rules (required); Portfolio Memory, i.e. prior E-16 (optional); deferred E-10 (queue mode only; none exist while cap = 1) |
| **Outputs** | `E-01.selection` (SignalSelection) |
| **Pre** | `RunContext` exists (immutable `run_id`); configuration identity resolved |
| **Post** | Either `selected = true` with relevance recorded, or an OutcomeRecord `SKIP` |
| **Invariants** | *Enforces:* I-01 (a non-fit signal is a `SKIP`, never a hold). *Depends on:* none |
| **Knowledge / config** | Contract fit rules (tier 2); hard legal/ethics exclusions (tiers 0b, 0c); portfolio pressure (tier 5, soft); U-2 selection rule |
| **Decider** | `rule` for contract, topic and risk fit. `model` for source eligibility. `code` for portfolio pressure (similarity against fingerprints) |
| **Calls** | 1: source eligibility. Reuses `judge_source_eligibility` |
| **ARP** | Outside contract, topics or risk level → `SKIP` signal (terminal). Source not eligible → `SKIP` signal (terminal). Portfolio pressure never skips on its own in assigned mode; it is recorded |
| **Limits** | None (single pass) |
| **Trace** | Fit rule results with rule IDs; eligibility verdict; the portfolio pressure computed; in queue mode, the candidate list and ranking |
| **Seam** | **Wrap:** `source_eligibility.judge_source_eligibility`, `ContentAssignment`, `RunContext`. **New:** contract fit rules as data. **Not reused:** legacy `topic_prioritizer` and `internal/memory` (verdict in Step 5). **Alternate authority:** `DecisionPolicyRecord` (U-3) |
| **Publication** | A skipped signal produces nothing |

### S-01 · Evidence Core (initial) and relevance screen

| Field | Contract |
|---|---|
| **Purpose / authority** | Retrieve the sources and build Evidence Core v1: source observations, evidence claims with verdicts, uncertainties, contradictions. Then confirm, on the evidence, that the material is relevant to the configured audience. It must not interpret, and it must not pick an angle |
| **Inputs** | `E-01` with `selected = true` (required); Client Contract evidence policy and strength ladder (required); lens profile for relevance criteria (as today in #58) |
| **Outputs** | `E-04` v1, containing E-02 and E-03 (producer of v1 only). **RelevanceAssessment**: the existing `decision.json`, restricted per AD-09 |
| **Pre** | Signal selected |
| **Post** | Core v1 is referentially valid. Every evidence claim has a verdict, strength and ceiling. Every observation has an attribution (built by code). The relevance assessment exists with a disposition |
| **Invariants** | *Enforces:* I-03 at source (nothing enters the core without an observation). I-04, lower half: `evidence_claim → source_observation`. *Depends on:* none |
| **Knowledge / config** | `K-EVD-*` evidence rules; contract ceiling and ladder (tier 2); AD-10 |
| **Decider** | `code` for retrieval (existing adapters; the providers are not text-model calls). `model` for assessment and relevance |
| **Calls** | 2. (a) **Evidence assessment**, extended: the existing `assess_artifact` call, which also returns for each observation `kind`, `figure` and `is_third_party_assertion`, and for each claim `scope` and `strength`. (b) **Relevance screen**: the existing #58 evaluator, whose `supported_editorial_angle` and `defensible_perspective` are recorded as hints and not consumed downstream (AD-09) |
| **ARP** | Retrieval failure (`FailedResearchResult`) → `SKIP` signal, reason `research_failed`. No usable evidence claim → `SKIP` signal. Relevance disposition `reject`, `irrelevant` or `insufficient_evidence` → `SKIP` signal. Disposition `revise` or `hold` → **not** a wait: `REPLAN` into S-03 with a `reader_connection` or `evidence` gap, if `L_enrich` allows; otherwise `SKIP` |
| **Limits** | None of its own. The `revise`/`hold` route spends `L_enrich` |
| **Trace** | Research artifact ID and digest; assessor identity; readiness; relevance disposition, bases and claim mode; hints recorded as hints |
| **Seam** | **Reuse:** `execute_and_persist_research`, the adapters, `ResearchResultEnvelope`. **Wrap:** `assess_artifact` (extended output), `evaluate_and_persist_decision` (angle fields demoted). **Replace:** `require_proceed` raising an error becomes ARP outcomes |
| **Publication** | — |

*Placement note.* AD-09 said the #58 outputs "feed S-00 and S-04". The #58 evaluator needs the research artifact, so it cannot run before research. It runs at the end of S-01 as an early screen, before any money is spent on enrichment. Its relevance output is consumed by S-04. This is recorded as refinement **R-1** (§7).

### S-02 · Material features and initial assets

| Field | Contract |
|---|---|
| **Purpose / authority** | Describe the material: the 12 features, initial assets, and what is missing. It must not choose a reader path, a label or a story |
| **Inputs** | `E-04` (current version, required) |
| **Outputs** | `E-05` v1 and `E-06` v1 (producer of the first versions). **MaterialNotes**: missing-material notes. These are not gaps; S-03 turns them into E-07 |
| **Pre** | Core has at least one usable evidence claim |
| **Post** | Every feature has a value and a confidence. Every positive feature has evidence references. Every asset has references. Calculations have inputs that are all in the core |
| **Invariants** | *Enforces:* I-10 (no label is produced here); I-03 for assets. *Depends on:* I-03, I-04 from S-01 |
| **Knowledge / config** | `K-MAT-*` feature definitions (not paths); `K-AST-*`; contract approved positions for positional assets |
| **Decider** | `model` for features, asset candidates and notes. `code` for the reference check and for calculations (arithmetic is never left to the model) |
| **Calls** | 1 |
| **ARP** | A feature or asset failing the reference check is dropped and recorded (`DEGRADE`, low confidence), not retried |
| **Limits** | — |
| **Trace** | Features with references; dropped items with reason; asset list |
| **Seam** | **New.** Replaces nothing directly. The Monday Pattern Extractor made a comparable judgment without references (disable at cutover, Step 5) |
| **Publication** | — |

### S-03 · Enrichment loop

| Field | Contract |
|---|---|
| **Purpose / authority** | Close gaps that **block a decision**, and decide when to stop. It must not collect "interesting extras" |
| **Inputs** | `E-04`, `E-05`, `E-06` (current versions); MaterialNotes; gaps routed back from S-01 (relevance `revise`/`hold`) |
| **Outputs** | `E-07` (sole producer). `E-04`, `E-05`, `E-06` versions ≥ 2 (producer of later versions) |
| **Pre** | Core v1 exists |
| **Post** | Every opened gap is `closed` or `abandoned` with a stop reason. The core, features and assets are at their final versions for S-04 |
| **Invariants** | *Enforces:* I-03 (new material enters only as observations and claims with verdicts); core append-only rule (E-04). *Depends on:* S-01 |
| **Knowledge / config** | `K-AST-*`, `K-PRC-08` (stop conditions); `L_enrich` |
| **Decider** | `code` opens gaps from notes, keeping only those with a `blocks` target. `code` searches (existing providers). `model` re-assesses and recomputes features |
| **Calls** | Per round: 1 extended assessment + 1 features recomputation = **2**. Rounds: 0 to `L_enrich` |
| **ARP** | Gap closed → `RESOLVE`. Stop with the gap open → gap `abandoned`, continue to S-04; S-04 decides between `DEGRADE` and `SKIP`. No blocking gap → zero rounds |
| **Limits** | `L_enrich` exhausted → stop; the same as a stop condition |
| **Trace** | For every gap: what it blocks, directives, what was found, rounds, stop reason; core version lineage |
| **Seam** | **Reuse:** `SourceDirective`, `ResearchProviderRequest`, the providers. **Wrap:** `assess_artifact` |
| **Publication** | — |

### S-04 · Interpretation Boundary

| Field | Contract |
|---|---|
| **Purpose / authority** | Decide what the material may mean for this audience: admissible interpretations, probed inadmissible ones, limits. It must not consider client positions, lens or portfolio ("what is true", not "what suits us") |
| **Inputs** | `E-04`, `E-05`, `E-06` (final versions); RelevanceAssessment (claim mode and relevance bases); Audience Profile (required, for the reader connection); `K-TEMPT-*` probe families (Step 4); on re-entry, the detected interpretation from S-13 |
| **Outputs** | `E-08` (sole producer); `E-09` (sole producer; a new version on re-entry). Version semantics: see **Boundary commit** below |
| **Pre** | Final core. At least one usable evidence claim |
| **Post** | Every interpretation passes the E-08 rules (support, ceiling, transfer). No interpretation sits in both lists. Every inadmissible one has a reason. The reader connection is present, or the outcome is `SKIP` |
| **Invariants** | *Enforces:* I-05 at source; I-04, middle link `interpretation → evidence_claim`; E-09 bounded completeness (patch R1: record what was generated or tested; completeness is not assumed). *Depends on:* I-03 |
| **Knowledge / config** | `K-EVD-*`, `K-TEN-*`, `K-CON-*`, `K-RDR-*`; strength ladder; `K-TEMPT-*` (U-1) |
| **Decider** | `model` for generation and probing (two separate calls, U-1). `code` for ceilings, the transfer rule, references and dual-listing |
| **Calls** | 2: (a) **generate**; (b) **probe** (U-1). On re-entry from S-13: 1 (**test** the detected interpretation) |
| **ARP** | No admissible interpretation → `SKIP` signal (terminal; walkthrough C). Only low-strength interpretations → `DEGRADE` (proceed with low confidence). Re-entry: detected interpretation recorded as inadmissible, new boundary version; if the anchor stays admissible → `REPLAN` → S-08 for the causing destination; if the anchor was invalidated → `REPLAN` → S-06 (consumes `L_anchor`) |
| **Limits** | Re-entry consumes `L_boundary`. When exhausted, the causing destination → `SKIP` |
| **Trace** | All interpretations with lists and reasons; the probe families applied and each result; boundary version lineage; which S-13 finding triggered a re-entry |
| **Seam** | **New.** Consumes #58 claim mode as the default for `audience_transfer`; the code transfer rule can only make it stricter. `ModelInterpretation` is not used (AD-06) |
| **Publication** | — |

**Boundary commit (version semantics, binding for Step 3).** A re-entry produces a **coordinated** E-08/E-09 change, committed together as one boundary commit:

1. **The E-09 version is the unit of consistency.** Every E-09 version is a complete snapshot. It lists each member interpretation as an exact (`interpretation_id`, `version`) pair, in `admissible` or `inadmissible`.
2. **A newly discovered interpretation** (not previously recorded) gets a **new E-08 record** (new ID, version 1), marked `inadmissible` with its reason, and a new E-09 version includes it.
3. **A previously recorded interpretation that must be reclassified** (e.g. an admissible one now shown to be unsupported) gets a **new version of the same E-08** (`supersedes` the old version, admissibility changed), and the new E-09 version references the new version.
4. **Unchanged interpretations are not copied.** The new E-09 version references their existing (ID, version) pairs.
5. **No E-08 change exists without a new E-09 version,** and vice versa. Both are written in one S-04 execution. A reader never sees an E-08 version that no E-09 version references.
6. **Downstream references carry versions.** E-11 (anchor), E-13 and PlanVerdict record the E-09 version they were decided against. The anchor is invalidated when its interpretation's current version in the newest E-09 is inadmissible. Invalidation is detected by code comparing the pairs.

### S-05 · Editorial Units

| Field | Contract |
|---|---|
| **Purpose / authority** | Decide how many units the signal becomes. **With cap = 1 it creates exactly one unit** and records whether a split would have qualified |
| **Inputs** | `E-09` (required); `E-08` admissible set with `depends_on` and supports; split cap (configuration) |
| **Outputs** | `E-10` (sole producer) |
| **Pre** | Boundary has at least one admissible interpretation |
| **Post** | Exactly one active unit whose `interpretation_scope` is the full admissible set. A `split` record with rule 1 and 2 results; `split_candidate` flag |
| **Invariants** | *Enforces:* AD-03 status (no second unit is created, stored or deferred at cap = 1). *Depends on:* I-05 |
| **Knowledge / config** | `K-UNIT-01`; cap = 1 |
| **Decider** | `code`: independence from `depends_on` and disjoint support sets. Rule 3 (standalone viability) is **not evaluated** at cap = 1, because it needs anchor calls; the trace records `rule_3: not_evaluated` |
| **Calls** | 0 |
| **ARP** | — (cannot fail once S-04 passed) |
| **Limits** | — |
| **Trace** | Rule results; `split_candidate`; which interpretation pairs qualified |
| **Seam** | **New** |
| **Publication** | — |

---

## 2. Unit and destination stages

### S-06 · Anchor

| Field | Contract |
|---|---|
| **Purpose / authority** | Choose the unit's one anchor interpretation, the strength it will be stated at, and the leading-material set (1–2 items). It must not choose openings or destinations |
| **Inputs** | `E-10`, `E-09`, `E-08`, `E-06` (required); on re-entry, the previous anchor and why it failed |
| **Outputs** | `E-11` (sole producer; a new anchor on re-entry) |
| **Pre** | Unit active; interpretation scope not empty |
| **Post** | Anchor is admissible and in scope; `strength_used` ≤ ceiling; the leading-material set supports the anchor; `ambiguity_touches_anchor` computed by code from the boundary's ambiguities |
| **Invariants** | *Enforces:* I-07 source (one anchor); AD-01 leading-material set. *Depends on:* I-05 |
| **Knowledge / config** | `K-PRC-03`, `K-RDR-*` |
| **Decider** | `model` chooses. `code` validates and computes the ambiguity flag |
| **Calls** | 1 (+1 on re-entry) |
| **ARP** | Ambiguity touches the anchor → `REPLAN` into S-03 once if `L_enrich` remains, otherwise weaken (`DEGRADE`); no provable anchor → `SKIP` unit. Re-entry from S-04 or S-08: exclude the failed anchor and choose again, or weaken it |
| **Limits** | Re-entry consumes `L_anchor`. When exhausted → `SKIP` unit |
| **Trace** | Candidates with reasons; strength used versus ceiling; leading material; ambiguity flag; re-entry cause |
| **Seam** | **Replaces** the copying of `central_claim` from CORE_FACT |
| **Publication** | — |

### S-07 · Destinations (deterministic)

| Field | Contract |
|---|---|
| **Purpose / authority** | Decide which destinations this unit is attempted on, with which mode and dependencies (AD-02). **No model.** It must not judge material fit |
| **Inputs** | `E-10`, `E-11` (required: the topic and risk facts come from the core and boundary); Client Contract destination settings (required); hard platform policy records (`K-DST-*` at tier 1 only); **destination capability** (target: six destinations, AD-02); **rollout scope** (migration-time deployment setting; AS-IS value `R1_PUBLISH_CHANNELS` = Wix + LinkedIn); cadence state from prior E-16 |
| **Outputs** | `E-12` DestinationDecision per destination (sole producer) |
| **Pre** | Anchor exists |
| **Post** | Every destination known to the contract has exactly one decision, eligible or excluded, each with a rule and tier |
| **Invariants** | *Enforces:* I-06 structure (dependencies are publication order only); AD-02. *Depends on:* — |
| **Knowledge / config** | Tier 2 contract rules; tier 1 hard platform policy; destination capability; rollout scope (temporary); cadence; whether an idempotency authority exists for the destination (a destination without one can only be `generate_only`, Step 3 §3.6 rule 7) |
| **Decider** | `rule` / `code` only |
| **Calls** | 0 |
| **ARP** | Excluded → `SKIP` destination with its rule. Zero eligible destinations → `SKIP` unit, reason `no_eligible_destination` |
| **Limits** | — |
| **Trace** | Per destination: decision, rule, tier, mode, dependencies |
| **Seam** | **Wrap:** `release_scope.py` becomes the rollout-scope setting during migration only. The target mode source is capability × contract × rollout scope (AD-02). When all six destinations are capable and enabled, the rollout scope equals the contract's destinations and can be removed |
| **Publication** | Sets `publish` / `generate_only` for each destination |

### S-08 · Candidate strategies (per destination)

| Field | Contract |
|---|---|
| **Purpose / authority** | Produce 2–4 whole, internally consistent strategies for one destination. It decides editorial job, angle, thesis, focal subject, reader path, opening, reveal, concession and ending intention. It must not choose among them, and must not produce labels |
| **Inputs** | `E-11`, `E-09`, `E-08` admissible set, `E-06`, `E-05` (required); `E-12` for this destination (required); Client Contract: positions, prohibitions, preferences (required); Audience Profile; Editorial Lens; Portfolio Memory (prior E-16, as soft pressure); `K-DST-*` for this destination; `K-MAT-*`, `K-OPN-*`, `K-REV-*`, `K-END-*`, `K-JOB-*`, `K-FOC-*`; on re-entry, the failure record that sent the destination back |
| **Not an input** | Sibling destinations' strategies or texts (I-06, AD-01: independence); label records (AD-07) |
| **Outputs** | `E-13` candidates (sole producer), grouped by `candidate_set_id` |
| **Pre** | Destination eligible; anchor valid; `L_strategy` not exhausted |
| **Post** | Every candidate meets the E-13 schema: anchor matches the unit; the second interpretation is admissible; every move has references; `leading_material_ref` is in the anchor's set and used as the primary evidentiary carrier (at least one move references it); opening chosen independently; justification for every field; `knowledge_used` listed |
| **Invariants** | *Enforces:* I-08 (decisions before prose); I-11 (knowledge recorded, not routed); AD-01. *Depends on:* I-05, I-07 |
| **Knowledge / config** | As listed. The tier of every record used is carried in `knowledge_used` |
| **Decider** | `model` |
| **Calls** | 1 per destination per attempt. Calls for different destinations are independent and may run in parallel |
| **ARP** | Zero candidates pass schema validation → counts as "no admissible strategy" for this destination (see S-09) |
| **Limits** | Each entry after the first consumes `L_strategy` |
| **Trace** | Candidate set; schema validation failures; routed knowledge (with `stage_routing` containment); the re-entry cause, if any |
| **Seam** | **Replaces** Pattern Extractor, Decision Lens Lite, Narrative Spine, Hook Engine, Reader Context, Discovery Builder, Story Assembly, the plan decider (`plan_decisions.py`) and the fixed `_BLOCK_TABLE` order. All of them are disabled only at cutover (Step 5) |
| **Publication** | — |

### S-09 · Strategy selection (per destination)

| Field | Contract |
|---|---|
| **Purpose / authority** | Exclude inadmissible candidates with a recorded reason, then choose one by the tie-breaker order (map §7.3). It must not edit candidates |
| **Inputs** | `E-13` candidate set (required); Client Contract; precedence model (map §5); Portfolio Memory (tier 5 tie-breaker) |
| **Outputs** | **StrategySelection** (sole producer): admissible, excluded with reason / record / tier, chosen, deciding tie-breaker, precedence applications |
| **Pre** | Candidate set exists |
| **Post** | Exactly one chosen strategy, or an outcome |
| **Invariants** | *Enforces:* precedence (every conflict resolved by tier, recorded); I-10 (the choice uses fields, never labels). *Depends on:* S-08 schema validity |
| **Knowledge / config** | Map §5 tiers; §7.3 tie-breakers; weak-candidate limits (Step 4 §5.1): a weak-candidate alone never excludes a candidate, and acts only at the soft end of the tie-breakers unless reinforced |
| **Decider** | `code` first: deterministic exclusions (V-P02 promise versus boundary, tier 0–2 conflicts, the code part of V-P01). If one admissible candidate remains, it is chosen. If several remain, `model` ranks them against the tie-breakers as explicit criteria. Portfolio and cost tie-breakers are computed by `code` |
| **Calls** | 0 if at most one candidate remains after code exclusion; 1 otherwise |
| **ARP** | Several admissible → `RESOLVE` by tie-breaker. The model cannot separate the leaders → `DEGRADE`: choose the safest admissible (lowest strength relative to the ceiling, no positional asset). No admissible candidate → `REPLAN` → S-08 for this destination (consumes `L_strategy`). **Unit rule:** if no destination of the unit has an admissible candidate in the same round, that points at the anchor → `REPLAN` → S-06 (consumes `L_anchor`) |
| **Limits** | `L_strategy` exhausted → `SKIP` destination (reason `no_admissible_strategy`). `L_anchor` exhausted → `SKIP` unit |
| **Trace** | The full StrategySelection |
| **Seam** | **New** |
| **Publication** | — |

### S-10 · Executable plan (per destination)

| Field | Contract |
|---|---|
| **Purpose / authority** | Adapt the chosen strategy to the destination without changing what the reader should believe or do (decision-vs-adaptation criterion). It sets format, length, segments, first-line mechanics, subheadings, hashtags, citations, voice brief and the conditional cross-destination link. It must not change any E-13 field |
| **Inputs** | Chosen `E-13` (required); `E-12` (mode, dependencies); `K-DST-*` (tiers 1 and 4); Client Contract: voice document, forbidden phrases and constructions, fixed slots such as `ending_mode` treated as constraints; the destination's mode from E-12 |
| **Outputs** | `E-14` draft (sole producer of drafts) |
| **Pre** | StrategySelection has a chosen strategy |
| **Post** | Every move is carried by at least one segment. Citations come only from the core. `forbidden` is resolved. A cross-destination link is **always conditional**: the plan must deliver its promise without the link (refinement R-2) |
| **Invariants** | *Enforces:* the adaptation boundary; I-06 (a link is not a content source). *Depends on:* I-08 |
| **Knowledge / config** | `K-DST-*`; contract rules (tier 2) |
| **Decider** | `code` for length ranges, hashtag policy, citations, the forbidden list and the link. `model` for segmenting and first-line mechanics |
| **Calls** | 1 per destination per strategy attempt |
| **ARP** | An adaptation that cannot fit a hard constraint (e.g. the reader path does not fit the format's length) is a structural failure → `REPLAN` → S-08 (consumes `L_strategy`) |
| **Limits** | Via `L_strategy` |
| **Trace** | The plan; which constraints were applied from which tier |
| **Seam** | **Rebuild.** Reuses contract resolution from `client_contracts.py` (plan slots, lens resolution) for `forbidden` and constraints |
| **Publication** | Sets the format each publisher or package will need |

### S-11 · Plan check and exemplars

| Field | Contract |
|---|---|
| **Purpose / authority** | Check each plan before any prose (V-P01, V-P02, V-P04, V-P05), then check the unit's plans together (V-P03, barrier B1). Select exemplars. It must not repair plans |
| **Inputs** | `E-14` drafts (required); `E-09`; `E-11`; Client Contract; hard platform policy; Reference Library; Portfolio Memory |
| **Outputs** | **PlanVerdict** per plan version (sole producer): check results, pass/fail, route. `E-14` approved version, with exemplars attached (sole producer of approved plans) |
| **Pre** | Per-destination checks: a plan draft exists. V-P03: all non-skipped destinations of the unit have passed their per-destination checks (B1) |
| **Post** | Each destination has an approved plan or an outcome. B1 passed for the unit |
| **Invariants** | *Enforces:* I-04 in the plan (thesis → interpretations → evidence claims → observations, all references resolvable: code); I-05 (V-P02); I-07 (V-P03); tier 1–2 compliance (V-P04). *Depends on:* all upstream |
| **Knowledge / config** | Check records V-P01…V-P05 (E-18); `K-EXM-*` |
| **Decider** | `code`: V-P02, the code parts of V-P01 and V-P04, V-P05, the chain check, exemplar lookup. `model`: the semantic part of V-P01 and construction types in V-P04, both against explicit criteria (one call per destination), and V-P03 (one call per unit per round) |
| **Calls** | 1 per destination per plan version, plus 1 per unit per B1 round |
| **ARP** | V-P01, V-P02 or V-P04 failure → `REPLAN` → S-08 for that destination. V-P04 violation of a tier-1 hard platform rule with no compliant variant → `SKIP` destination. V-P03 failure → `REPLAN` → S-08 **only for the destination(s) that deviated** from the anchor; the others keep their approval. V-P05 → soft signal only, recorded, never blocks (I-12) |
| **Limits** | Via `L_strategy` → `SKIP` destination. If B1 can never pass (the deviating destination is skipped), B1 re-evaluates without it |
| **Trace** | Every CheckResult with method and rule status; B1 rounds; exemplars chosen with take / do-not-copy notes |
| **Seam** | **New.** Reuses ideas from `EditorialPlan.check()` for the chain and forbidden checks |
| **Publication** | — |

### S-12 · Writer (per destination)

| Field | Contract |
|---|---|
| **Purpose / authority** | Execute the approved plan in prose. **Decides nothing editorial.** If the plan cannot be executed honestly, it says so instead of improvising |
| **Inputs** | Approved `E-14` (required, and **the only planning input**); the core items the plan references (resolved by code); exemplars; voice brief; `forbidden`; on edit, the text version and the S-13 findings |
| **Not an input** | The boundary's full lists beyond what the plan references; sibling texts; labels; the raw research |
| **Outputs** | `E-15` (sole producer; new version per edit) |
| **Pre** | The plan is approved and B1 passed for its unit |
| **Post** | Text with `writer_signal`. On `plan_holds = false`, no text is accepted |
| **Invariants** | *Depends on:* I-03, I-04, I-05, I-08 (the plan is the gate). *Enforces:* nothing by itself; S-13 verifies |
| **Knowledge / config** | None directly: knowledge reaches the Writer only through the plan (I-11) |
| **Decider** | `model` |
| **Calls** | 1 per write or edit |
| **ARP** | `plan_holds = false` → `REPLAN` → S-08 (consumes `L_strategy`). The Writer does not retry itself |
| **Limits** | Edits consume `L_edit` (counted at S-13) |
| **Trace** | Text digest; writer signal; edit lineage |
| **Seam** | **Replaces** `platform_composer` (prose), `never_blank_voice` and LinkedIn recomposition from the accepted article (content derivation, a conflict with I-06). Reuses the provider transport and `RunCallBudget` |
| **Publication** | — |

### S-13 · Text check (per text version)

| Field | Contract |
|---|---|
| **Purpose / authority** | Verify the text against the core, the boundary, the plan and the contract. Route each failure to the layer that made the decision. It must not rewrite |
| **Inputs** | `E-15` (required); its approved `E-14`; `E-09`; `E-04`; Client Contract; prior E-16 and publication index (for V-T05, V-S05) |
| **Outputs** | **TextVerdict** per text version (sole producer): CheckResults, accepted / rejected / edit / replan, route |
| **Pre** | Text exists with `plan_holds = true` |
| **Post** | Accepted, or routed |
| **Invariants** | *Enforces:* I-03 (V-T01, V-T04), I-04 (V-T03), I-05 (V-T02, **not bounded by the recorded inadmissible list**, patch R1), V-T05 (duplicate), V-T06 (client prohibitions), V-T07 (plan executed), V-T08 (Echo). *Depends on:* the approved plan |
| **Knowledge / config** | Check records V-T*, V-S*; the recorded inadmissible list as detection aid |
| **Decider** | `code`: figures, names and links reconciled with the core (V-T01 code part, V-T04), V-T05 digest and near-duplicate, V-T06 phrases, the code parts of V-S*. `model`, **two calls against explicit criteria**: (a) **truth**: V-T01 model part, V-T02, V-T03; (b) **execution**: V-T07, V-T08, V-T06 construction types, and the model parts of V-S01, V-S03, V-S08 and V-S09 |
| **Calls** | 2 per text version |
| **ARP routes** | See the table below |
| **Limits** | `L_edit`, `L_strategy`, `L_boundary` as routed |
| **Trace** | Every CheckResult with route; S-signal values (hints only) |
| **Seam** | **Wrap:** `factual_review` (becomes the truth call), `editorial_acceptance` (becomes the execution call; its rubric is replaced by the V-T criteria; its "one controlled revision" becomes `L_edit`), `machine_tells`, `output_guard`, `source_transparency`, `derivation_fidelity` as code checks where applicable |
| **Publication** | Only accepted texts reach S-14 |

**S-13 routes:**

| Finding | Route | Counter | On exhaustion |
|---|---|---|---|
| V-T01 fact misquoted from the core; V-T06 forbidden phrase | S-12 edit, same plan | `L_edit` | `SKIP` publication |
| V-T01 fact not in the core, branch **removable**: the plan's thesis, promise and every move can still be executed without it; V-T04 invented link or source | S-12 edit (remove it), same plan | `L_edit` | `SKIP` publication |
| V-T01 fact not in the core, branch **load-bearing**: removing it leaves the thesis, a promise or a move without support (the plan required material the core does not hold) | S-08 | `L_strategy` | `SKIP` destination |
| V-T02 interpretation inadmissible, or not in the boundary | S-04 re-entry (test and record), then S-06 if the anchor fell, otherwise S-08 | `L_boundary`, then `L_anchor` or `L_strategy` | `SKIP` destination, or unit |
| V-T03 chain broken; V-T07 plan not executed | S-08 | `L_strategy` | `SKIP` destination |
| V-T08 Echo recaps, branch **strategy**: the approved `ending_intention`, executed faithfully, would itself recap the opening | S-08 | `L_strategy` | `SKIP` destination |
| V-T08 Echo recaps, branch **execution**: the approved `ending_intention` is a valid reframe and the Writer executed it as a recap | S-12 edit, same plan | `L_edit` | `SKIP` publication |
| V-T05 near-exact republication | `SKIP` publication (terminal) | — | — |
| V-S* soft signals | Recorded as hints; never block (I-12) | — | — |

A text with both an edit-class and a replan-class finding follows the replan route: a decision error outranks phrasing.

**Branch decisions (V-T01, V-T08).** The branch is decided per finding and **recorded** in the CheckResult (`fault_owner`: `writer` / `plan`, plus the branch name and the criterion applied).

- **V-T01 `removable` vs `load-bearing`.** Code locates the unsupported item and the plan elements (thesis, promise, move, opening) that reference the text span. The truth call answers one explicit question: can each of those elements still be executed with only core material? Yes → `removable`. No → `load-bearing`.
- **V-T08 `strategy` vs `execution`.** The execution call judges the approved `ending_intention` on its own, against the V-T08 criterion (reframe, not recap), before judging the text. Intention fails → `strategy`. Intention passes and the text fails → `execution`.
- **When uncertain,** the route defaults to the **plan** branch (S-08). A decision error is never charged to the Writer by default.

---

## 3. Publication and learning

### S-14 · Publication and fingerprint

| Field | Contract |
|---|---|
| **Purpose / authority** | Package, preflight, publish `publish`-mode texts in dependency order, store `generate_only` texts, and write fingerprints. **No model and no editorial decision** |
| **Inputs** | Accepted `E-15` with its TextVerdict (required); `E-12` mode and dependencies; `E-14`, `E-13`, `E-05` (for the fingerprint snapshot); publication targets and credentials (existing configuration) |
| **Outputs** | Publication results (existing `PublishResult`, normalized to the run); `E-16` fingerprint (sole producer); publication index entry (existing `PublishedEntry`, kept until migration) |
| **Pre** | Text accepted |
| **Post** | Every accepted text has a fingerprint, flagged `publish` or `generate_only`. Every `publish` text is published, or has a recorded `SKIP` |
| **Invariants** | *Enforces:* I-06 at the boundary (the link is bound only if its target was published; otherwise it is omitted, refinement R-2); V-T05 is re-confirmed by idempotency. *Depends on:* S-13 |
| **Decider** | `code` |
| **Calls** | 0 |
| **ARP** | Preflight `BLOCK` → `SKIP` publication (reason = blocking reason). Link target failed or skipped → omit the link (`DEGRADE`, recorded); the text is complete without it by construction. Prior publication found by the **idempotency authority** → reuse or `SKIP` per existing idempotency rules. Authority unavailable → `SKIP` (`idempotency_authority_unavailable`). An intent without a marker from an earlier run → `SKIP` (`publication_possibly_exists`) unless an external lookup confirms no publication exists. Publisher error → `SKIP` publication with the error; no editorial retry. **Publication transaction** (Step 3 §3.6, invariant S3-I1): lookup → durable intent → external call → durable marker written first and alone, independent of the learning-ledger commit |
| **Limits** | — |
| **Trace** | Package digests; preflight verdicts; publish results; fingerprint IDs |
| **Seam** | **Reuse:** `package.py` (including `bind_canonical_article_url`), `preflight.py`, `idempotency.py`, the publishers for all six destinations, `verify_run_provenance`. **Extend:** packages and preflight exist today only for Wix and LinkedIn; they are extended to Facebook, Instagram, Threads, Telegram. **New:** fingerprint writer. `PublishedEntry` stays as the publication index |
| **Publication** | `publish` mode reaches external platforms. **Target: all six destinations**; during migration, only those in the rollout scope (AD-02). Wix is published first, because the other destinations may link to it (conditional link, R-2). Instagram, and Facebook when it has an image, need an image from the existing image pipeline |

### S-15 · Observation (after the run)

| Field | Contract |
|---|---|
| **Purpose / authority** | Collect platform metrics, link them to fingerprints with confounders, and queue knowledge proposals. It must not change knowledge status, thresholds or anything in production |
| **Inputs** | `E-16` (published only); platform collectors |
| **Outputs** | `E-17` (sole producer); KnowledgeQueueItem of kinds `observation` and `vt02_feedback` (sole producer of those kinds). `expiry_review` items come from the offline Knowledge Maintenance job (Step 4 §5.2), not from S-15 |
| **Pre** | Publication exists and its observation window has elapsed |
| **Post** | Metrics stored raw, with confounders (`unknown` allowed) |
| **Invariants** | *Enforces:* I-02, I-12, I-13 (proposals only; the keeper decides offline) |
| **Decider** | `code` |
| **Calls** | 0 |
| **ARP** | Collector failure → retried by schedule. It never affects a production run |
| **Trace** | Its own job trace, linked to the run by fingerprint |
| **Seam** | Examine `src/analytics/*` in Step 5. `analytics_score` is not used as a knowledge input (it is a blend) |

### Label job (after the run; not a stage of S-00…S-15)

- Writes label records for fingerprints: code-based, batched, asynchronous, or not at all (patch R1).
- Never runs inside a production run's critical path.
- Its calls are **outside** `RunCallBudget`.
- Consumers (V-S06, V-S07, portfolio reports) treat missing labels as missing data.

---

## 4. Resolved questions U-1, U-2, U-3

### U-1 · How S-04 probes for tempting inadmissible interpretations

**Decision.** Two separate model calls at S-04, plus code rules.

1. **Generate.** One call proposes interpretations with kind, supports, counter-evidence, dependencies, audience transfer and limits.
2. **Probe.** A second, separate call receives the core, the Audience Profile and the generated list. It works through an explicit checklist of **probe families** (`K-TEMPT-*`, a Step 4 knowledge family). For each family it states the most likely tempting interpretation, if any. It then tests that interpretation, and every generated one, against the evidence as an explicit criterion: admissible, or inadmissible with a reason.
3. **Code** applies the hard rules: strength ≤ ceiling, the transfer rule, resolvable references, no dual listing.

**Initial probe families**, taken from the real errors in the sample pack and walkthroughs A–C:

| Family | Example |
|---|---|
| transfer to the reader | "you, the reader, bake at night" |
| benefit inflation | "the business has more money" |
| invented scene | — |
| causal overreach | — |
| generalization from a single case | — |
| forecast stated as fact | — |
| burden inflation | "the compliance checklist doubles"; "owners were buried in inspections" |

**The requirement stays bounded** (patch R1). The boundary records what was generated and tested, and which families were applied. It does not claim to be complete. S-13 V-T02 is not limited to that list.

**Feedback loop.** A V-T02 finding that matches no recorded interpretation becomes a KnowledgeQueueItem proposing a new family or example. The keeper decides offline.

**Alternatives considered**

| Option | Why rejected |
|---|---|
| Generate and probe in the same call | A model that has just produced a reading is weak at flagging its own overreach (`K-PRC-02`: same-model self-editing does not fix structure). Explicit-criteria checks work better as separate calls (`K-PRC-04`). The saving is one call per signal |
| Probe per destination | The boundary is signal-level truth. Probing per destination multiplies cost by D and mixes "what is true" with "what suits this platform" |
| No probing; rely on S-13 detection | Finds errors only after prose is paid for, and routes the most expensive way. It also loses the planner-side protection (strategies cannot reference what is recorded as inadmissible) |

**Cost:** +1 model call per signal (§6).

### U-2 · S-00 when candidates include deferred units

Dormant while cap = 1. In production, only `signal` candidates occur. The contract is fixed now so that raising the cap needs no redesign.

1. **Queue mode only.** In assigned mode, S-00 evaluates the one given signal. Deferred units are not considered.
2. **Expiry is a hard boundary, not a score.** A deferred unit past `expires_at` ends in `SKIP` (`expired`) before ranking. There is no freshness decay curve to tune.
3. **Fit is re-checked.** A deferred unit goes through the same contract, topic and risk rules as a new signal, because the contract may have changed since it was deferred.
4. **Ranking, in order:**
   1. relevance (from eligibility for signals; the stored relevance for deferred units);
   2. portfolio pressure as a soft penalty (tier 5). A deferred unit's topic key is compared with recent fingerprints, including its sibling unit's, so it naturally waits after its sibling is published;
   3. candidate age (older first) as the last tie-breaker.
5. **No starvation boost and no quota** (I-12). A deferred unit that keeps losing simply expires. That outcome is recorded and counted.
6. **Re-entry.** A selected deferred unit reuses its stored core and boundary if they are within their expiry. The run then starts at S-06. Otherwise the unit is treated as a new signal from S-01.

**Alternative rejected:** a priority score blending freshness, relevance and portfolio pressure. It creates a threshold-tuning problem with no data behind it, and it hides why a candidate won.

### U-3 · Where the precedence log lives

**Decision.** A new **PrecedenceLog** in E-19: an ordered list of PrecedenceApplication, each with stage, scope key, conflict, winner and tier, loser and tier, and the rule applied.

`DecisionPolicyRecord` is **not** extended. It stays what it is: a narrow, create-once authority record for the `role_bounded_r1` path, which runs without a #58 decision. It is recorded as debt against #151. In the target it is treated as an alternate S-00/S-01 authority for that role, and its fate is decided in Step 5.

**Alternatives considered**

| Option | Why rejected |
|---|---|
| Extend `DecisionPolicyRecord` | Its contract states it "proves five things and nothing else", with `Literal` fields and create-once semantics. Precedence applications are produced throughout the run, by many stages. Extending it would break both properties |
| Record precedence in `stage_routing` | `stage_routing` proves what material **reached** a stage, not what the stage **decided**. Mixing them weakens both proofs |

---

## 5. End-to-end contract consistency pass (S-00 → S-15)

### 5.1 Every output has exactly one producer

Rule for versioned entities: every **version** has exactly one producer. Where the first version and later versions come from different stages, both are listed and they never produce the same version.

| Artifact | Producer | Consumers | Available before its first consumer? |
|---|---|---|---|
| E-01 (intake part) | Intake (`ContentAssignment`), before S-00 | S-00, S-01 | Yes |
| `E-01.selection` | S-00 | S-01, E-19 | Yes |
| E-04 v1 (with E-02, E-03) | S-01 | S-02, S-03 | Yes |
| E-04 v≥2 | S-03 | S-04, S-06, S-10, S-12, S-13, S-14 | Yes: S-04 waits for the loop to end |
| RelevanceAssessment | S-01 | S-04 | Yes |
| E-05 v1, E-06 v1, MaterialNotes | S-02 | S-03 | Yes |
| E-05 v≥2, E-06 v≥2 | S-03 | S-04, S-06, S-08, S-14 | Yes |
| E-07 | S-03 (sole; see fix F-3) | S-03, E-19 | Yes |
| E-08, E-09 | S-04 (including re-entries) | S-05, S-06, S-08, S-09, S-11, S-12 (referenced items only), S-13 | Yes |
| E-10 | S-05 | S-06, S-07 | Yes |
| E-11 | S-06 | S-07, S-08, S-11 | Yes |
| E-12 | S-07 | S-08, S-10, S-11, S-14 | Yes |
| E-13 candidates | S-08 | S-09 | Yes |
| StrategySelection | S-09 | S-10, S-14 (fingerprint), E-19 | Yes |
| E-14 draft | S-10 | S-11 | Yes |
| PlanVerdict, E-14 approved | S-11 | S-12, S-13, S-14 | Yes |
| E-15 | S-12 | S-13, S-14 | Yes |
| TextVerdict | S-13 | S-12 (edit), S-14 | Yes |
| E-16 | S-14 | S-00, S-07, S-08, S-09, S-13 (V-T05, V-S05) **of later runs**, S-15, label job | Yes (prior runs) |
| Publication intent, PublicationMarker | S-14 (sole producer; Step 3 §3.6) | S-14 of later runs (lookup before publish); S-07 (publish-mode eligibility) | Yes (prior runs) |
| Label record | Label job, after the run | V-S06, V-S07, reports; **never S-00…S-13** | n/a (optional) |
| E-17; KnowledgeQueueItem kinds `observation`, `vt02_feedback` | S-15 | Keeper (offline) | n/a |
| KnowledgeQueueItem kind `expiry_review` | Knowledge Maintenance job (offline, scheduled; outside every run) | Keeper (offline) | n/a |
| E-18 | Keeper (offline) | S-00…S-13 as routed knowledge; S-11, S-13 as check records | Yes (persistent) |
| E-19 | Every stage appends; the run harness owns it | Indicators, audits | Yes |

**Result:** no artifact has two producers for the same version. Three defects were found and fixed along the way (§5.7: F-1, F-2, F-3).

### 5.2 Every required input exists before it is consumed

Checked stage by stage against §5.1. Two ordering constraints needed explicit rules:

- **V-P03 needs every plan of the unit** → barrier B1 (§0.2).
- **S-14 publishes after the unit's destinations reach a terminal state** (accepted or skipped). Two reasons:
  - a boundary re-entry triggered by one destination's text can invalidate a sibling's accepted text (§5.4);
  - the Wix outcome must be known before the LinkedIn link is bound.

This costs latency, not quality. The existing Wix-before-LinkedIn order is preserved inside S-14.

### 5.3 Every REPLAN route has a valid target and terminates

| From | Cause | Target | Counter | Terminal outcome at exhaustion |
|---|---|---|---|---|
| S-01 | Relevance `revise` / `hold` | S-03 (with a gap) | `L_enrich` | `SKIP` signal |
| S-06 | Ambiguity touches the anchor | S-03 | `L_enrich` | `DEGRADE` (weaker anchor) or `SKIP` unit |
| S-09 | No admissible candidate (one destination) | S-08 | `L_strategy` | `SKIP` destination |
| S-09 | No admissible candidate on any destination in the same round | S-06 | `L_anchor` | `SKIP` unit |
| S-10 | Adaptation cannot meet a hard constraint | S-08 | `L_strategy` | `SKIP` destination |
| S-11 | V-P01 / V-P02 / V-P04 | S-08 | `L_strategy` | `SKIP` destination |
| S-11 | V-P03 deviation | S-08 (deviating destination only) | `L_strategy` | `SKIP` destination; B1 re-evaluates without it |
| S-12 | Plan does not hold | S-08 | `L_strategy` | `SKIP` destination |
| S-13 | Phrasing, misquoted facts, links; V-T01 `removable`; V-T08 `execution` | S-12 (same plan) | `L_edit` | `SKIP` publication |
| S-13 | Structure, chain, plan execution; V-T01 `load-bearing`; V-T08 `strategy` | S-08 | `L_strategy` | `SKIP` destination |
| S-13 | Inadmissible or unlisted interpretation | S-04 → S-06 or S-08 | `L_boundary` → `L_anchor` / `L_strategy` | `SKIP` destination or unit |

**Termination.** Every backward edge consumes a finite counter, and no counter is ever reset during a run. `RunCallBudget` bounds everything globally. So the route graph with counters is finite, and every path ends in S-14 or in a `SKIP`.

**Validity.** Every target is upstream of its source and owns the failed decision: S-03 owns material, S-04 truth, S-06 the anchor, S-08 structure, S-12 phrasing and faithful execution of a valid plan. **No route targets the Writer for a decision failure.** Where ownership is split (V-T01, V-T08), the branch is decided per finding, recorded, and defaults to the plan branch when uncertain.

### 5.4 No route bypasses Evidence Core → Interpretation Boundary → approved plan

| Check | Result |
|---|---|
| The only edge into S-12 comes from S-11 (approved plan, B1 passed) or from S-13 (edit on the **same** approved plan) | Holds |
| Every S-08 entry reads the **current** anchor and boundary versions | Holds |
| **Boundary version drift.** After an S-04 re-entry (a boundary commit, §1 S-04), plans approved against the older boundary version could reach S-12 | **Defect F-4, fixed.** PlanVerdict records the boundary version. The S-12 precondition requires it to equal the current version. On a new boundary version, S-11's code checks (V-P02, chain) re-run on every approved plan of the unit (0 model calls). Texts already accepted for sibling destinations get a targeted re-run of the S-13 **truth** call (1 call each) before S-14 |
| S-10 may add citations only from the core, and may not add moves | Holds (post-condition) |
| S-14 cannot change text except binding or omitting a conditional link | Holds |
| Knowledge reaches the Writer only through the plan | Holds (S-12 inputs) |
| Labels never reach S-00…S-13 | Holds (routing prohibition §0.7, label job after the run) |

### 5.5 ARP coverage

Every state in map §6.2 maps to a stage and an outcome above.

- **Map row "No admissible strategy → REPLAN S-06"** conflicted with AD-02 (a destination without an admissible strategy is a destination `SKIP`). **Reconciled** by the unit rule in S-09: one destination failing → that destination's `SKIP`; all destinations failing in the same round → the anchor is suspect → S-06. This is fix F-5.
- **"Several equal strategies"** → S-09 `RESOLVE` or `DEGRADE`.
- **"Platform knowledge expired"** → handled when knowledge is loaded: automatic demotion to a weak candidate (Step 4). No stage outcome is needed.

### 5.6 Accepted decisions preserved

| Decision | Where it holds |
|---|---|
| AD-01 Model C; leading material is the carrier, not the opening | S-06 output; S-08 post-condition; V-P01 checks the carrier, not the opening |
| AD-02 S-07 deterministic | S-07 decider is `rule`/`code`, 0 calls; material fit appears as an S-09 destination `SKIP` |
| AD-03 split OFF at cap = 1 | S-05 creates exactly one unit; rule 3 not evaluated; U-2 dormant |
| AD-04 many-to-many schema | E-04 and E-10 carry lists; S-00 assigned mode uses one signal |
| AD-05 / AD-06 | S-01 wraps the research contract; S-04 produces new E-08/E-09 |
| AD-07 labels | Label job after the run; routing prohibition; no stage consumes labels |
| AD-08 audience transfer | S-04 default from #58 claim mode; the code rule can only make it stricter |
| AD-09 #58 demoted | S-01 relevance screen; angle fields are hints and not consumed |
| AD-10 ladder | S-01 assigns strength and ceiling on one ladder; S-04/S-06 compare on it |
| No human wait | §0.5; no `human` decider anywhere |
| Failures route to their layer | §0.6, §5.3 |

### 5.7 Defects found by this pass and fixed

| ID | Defect | Fix | Touches |
|---|---|---|---|
| F-1 | `E-13.role` would be changed by S-09 on an immutable entity | Remove `role` from E-13. Roles live only in StrategySelection | Step 1 schema |
| F-2 | `E-14.status`/`plan_checks` and `E-15.status`/`text_checks` would be changed by S-11 and S-13 | Move them into **PlanVerdict** and **TextVerdict** records. S-11 also produces the approved E-14 version, with exemplars | Step 1 schema |
| F-3 | E-07 had two potential producers (S-02 proposing gaps, S-03 managing them) | S-02 emits MaterialNotes. S-03 is the sole producer of E-07 | Step 1 note |
| F-4 | Boundary version drift after an S-04 re-entry | PlanVerdict records the boundary version; S-12 precondition; code re-check; sibling truth re-check | This document |
| F-5 | Map ARP row versus AD-02 on "no admissible strategy" | Unit rule in S-09 | Map §6.2 wording (v1.1) |
| F-6 | E-09 had no reference to the relevance evidence it uses | Add `relevance_ref` to E-09 | Step 1 schema |

---

## 6. Stage-call budget

**Model calls only.** Retrieval providers, publishers and the label job are not counted. D is the number of eligible destinations of the unit. Today D ≤ 6, of which 2 are `publish`.

| Case | Assumptions |
|---|---|
| **Minimum** | No enrichment; one admissible candidate per destination after code exclusion; no replans; no edits |
| **Normal** | One enrichment round; S-09 needs a model ranking; about half the texts need one edit (e = ⌈D/2⌉) |
| **Worst** | Every counter exhausted at its default (`L_enrich` = 2, `L_boundary` = 1, `L_anchor` = 1, `L_strategy` = 2, `L_edit` = 1) |

| Stage | Min | Normal | Worst | Notes |
|---|---|---|---|---|
| S-00 | 1 | 1 | 1 | Source eligibility |
| S-01 | 2 | 2 | 2 | Extended assessment + relevance screen |
| S-02 | 1 | 1 | 1 | |
| S-03 | 0 | 2 | 4 | 2 per round |
| S-04 | 2 | 2 | 3 | Generate + probe; +1 re-entry test |
| S-05 | 0 | 0 | 0 | Code at cap = 1 |
| S-06 | 1 | 1 | 2 | +1 re-entry |
| S-07 | 0 | 0 | 0 | Deterministic |
| S-08 | D | D | 3D | 1 per destination per attempt |
| S-09 | 0 | D | 3D | 0 when one candidate survives code |
| S-10 | D | D | 3D | |
| S-11 | D + 1 | D + 1 | 5D + 1 | Per plan version + V-P03 rounds (≤ 1 + 2D) |
| S-12 | D | D + e | 6D | Up to 3 plans × (write + 1 edit) |
| S-13 | 2D | 2D + 2e | 13D − 1 | 2 per text version + sibling truth re-checks after a boundary re-entry |
| S-14, S-15 | 0 | 0 | 0 | |
| **Total** | **8 + 6D** | **10 + 7D + 3e** | **13 + 33D** | |

**At the current destination counts:**

| D | Min | Normal | Worst | Current R1 ceiling |
|---|---|---|---|---|
| 6 (**canonical run: all destinations**) | 44 | 61 | 211 | 40 (current engine) |
| 2 (comparison only) | 20 | 27 | 79 | 40 |

**What the numbers show.** They are exposed, not optimized.

1. **The canonical run publishes to six destinations (patch CANONICAL-SCOPE),** so the 40-call ceiling of the current engine does not fit it: even the minimum case is 44. The canonical run needs its **own ceiling, sized for six destinations**. The answer to the cost is measurement and optimization, **never shrinking the target to Wix + LinkedIn**. The normal case is about 61 calls. The worst case (211) is still bounded, because exhaustion ends in destination `SKIP` in destination order (§0.4).
2. The exact ceiling is set from the calls measured in the shadow phase (Step 5, capability C4), not guessed now.
3. **The per-destination chain dominates.** S-08 → S-13 accounts for about 6–7 calls per destination in the normal case. The signal-level stages cost 7–9 calls, however many destinations there are.
4. **Known levers, not applied now:**
   - merge S-09 ranking into S-08;
   - merge S-10 segmenting into S-08;
   - one S-11 call per unit instead of per destination;
   - lower `L_strategy` for `generate_only`;
   - one S-13 call for short formats.

   Each of them trades separation against cost. Deciding them is OPEN-06, after real runs.

---

## 7. Refinements to earlier documents

None changes an invariant or an accepted decision's intent. They make the accepted decisions executable.

| ID | Refinement | Affects |
|---|---|---|
| R-1 | The #58 relevance evaluation runs at the end of S-01, not in S-00, because it needs the research artifact. Its output feeds S-04 | AD-09 wording ("feeds S-00 and S-04" → "runs at S-01, feeds S-04") |
| R-2 | A cross-destination link is always conditional. The linking text must deliver its promise without it. The link is bound at S-14 only if the target was published, otherwise omitted (`DEGRADE`). This replaces "drop the link in adaptation", which is impossible when the target is skipped after writing | AD-02 point 5; E-14 `cross_destination_link` |
| R-3 | Budget exhaustion ends in `SKIP` outcomes with accepted texts preserved, instead of raising and failing the whole run | Behaviour change to the `RunCallBudget` seam (wrap) |
| R-4 | S-14 publishes after all destinations of the unit reach a terminal state | Publication timing |
| R-5 | Schema fixes F-1, F-2, F-3, F-6 | `01_STEP1_TYPED_ENTITIES.md`: **applied in patch R2** |

---

## Кратко по-русски (для Светы)

- **Расписаны все 16 стадий**: что входит, что выходит, кто решает (код, правило или модель), что может пойти не так и куда возвращается ошибка.
- **Человек нигде не ждётся.** Любой сбой заканчивается одним из четырёх исходов, причина записывается.
- **Ошибка возвращается туда, где было принято неверное решение.** Автора (Writer) никогда не просят чинить чужую ошибку: он исправляет только формулировки и неточно процитированные факты.
- **Все петли ограничены счётчиками**, поэтому система не может зациклиться.
- **Систему проверила целиком, а не по стадиям.** Нашлись и исправлены шесть нестыковок. Главная: если по ходу обнаружилась новая недопустимая интерпретация, уже одобренные планы других площадок перепроверяются, чтобы они не опирались на устаревшую границу.
- **Три вопроса закрыты.**
  - Ловушки ищет отдельный проход модели по списку типичных ошибок, взятых из реальных текстов движка.
  - Правила выбора отложенных единиц записаны, но пока спят, потому что деление выключено.
  - Журнал приоритетов правил — новая запись в журнале прогона, старую запись не трогаем.
- **Стоимость.** Для Wix и LinkedIn: 20–27 вызовов модели в обычном случае при нынешнем потолке 40. Для всех шести площадок нужно 44–61, в текущий потолок это не влезает. Это решение о бюджете, а не о текстах. Я его не оптимизировала, а показала.
