# Canonical Editorial Map v1

*Final Claude version · 21 September 2026 · for #283 · RESEARCH / DESIGN — HOLD · no code*

## Corrections before canonization

GPT found five internal contradictions in the specification. All five were confirmed. While checking, I found eight more defects of the same kind. All are corrected below.

| # | Defect | Real? | Correction |
|---|---|---|---|
| 1 | A bare generic term remained where a schema entity name was required (see the rule in section 2): in the English version V-T03 read "thesis → interpretation → [bare term] → observation", section 6 said "weaker [bare term]", and the feature was named `contested_claim` | **Yes** | The schema uses only entity names: `source_observation`, `evidence_claim`, `interpretation`, `editorial_thesis`, `angle`, `client_position`. The chain in I-04 and V-T03: `editorial_thesis → interpretation → evidence_claim → source_observation`. The feature is renamed `contested_assertion` (a third-party assertion in the world that the evidence contests). "Weaker [bare term]" in the protocol is replaced with "lower-strength interpretation" |
| 2 | `K-OPN-03` at tier 0a mixes an invented scene passed off as real with a hypothetical reader scene | **Yes** | Split: `K-OPN-03a` — a scene passed off as real without a source violates I-03 (invariant, 0a). `K-OPN-03b` — a hypothetical reader scene ("Suppose you…", "Imagine…") — a strong AI pattern in the current engine, candidate, tier 3. The client may forbid it with a tier 2 rule. `K-MAT-07` and V-S01 are aligned |
| 3 | Destination records with two tiers: `K-DST-LI-02` (1/3), `K-DST-FB-01` (1/4) | **Yes** | One record — one tier. Split: LI-02 (descriptive, 3) and LI-03 (platform rule, 1); FB-01 (ranking, 4) and FB-02 (platform rule, 1) |
| 4 | V-P01 checks by label: "'Teardown' requires a documented case" | **Yes** | Checks refer only to strategy fields: "if the reader path makes a case the subject of a move, `documented_case` is mandatory and confirmed in the Evidence Core". The labels in `K-MAT-*` are names of descriptions and are not used in checks |
| 5 | I-05 is an invariant, but V-T02 is a candidate | **Yes** | V-T02 inherits invariant status from I-05. The detection method may be probabilistic (a model against an explicit criterion); the rule may not. A separate "Method" column is added to the checks table |
| 6 | Same defect as 5: V-T03 (the chain) is a candidate while I-04 is an invariant | Found during checking | V-T03 → invariant |
| 7 | Same defect: V-T04 (invented links) is a candidate, although it is a violation of I-03 | Found | V-T04 → invariant |
| 8 | Same defect as 3: `K-DIV-02a` (5 / 1) and `K-DIV-02b` ("1 if matching") | Found | Split: republishing a near-exact text → `K-DIV-06` (platform rule, 1); structural repetitiveness → `K-DIV-02a`, `K-DIV-02b`, `K-DIV-02c` (5) |
| 9 | Same defect: `K-DST-WIX-01` (3–4) | Found | WIX-01 (editorial, 3) + WIX-02 (search ranking, 4) + WIX-03 (Google policy against scaled unoriginal content, 1) |
| 10 | `K-DST-META-02` mixes the disclosure obligation (a rule) and the label mechanism (a fact) | Found | META-02 (disclosure rule, 1) + META-03 (C2PA label mechanism, descriptive, no tier) |
| 11 | `K-EVD-03` is a "candidate" at tier 0a | Found | Storing tempting interpretations is a design technique (A, candidate). The ban on expressing them is I-05 |
| 12 | `K-AST-04` is a "candidate for invariant" at tier 0a | Found | Attributing to the client a position that is not in the contract is invented attribution, i.e. a violation of I-03. Record → invariant, 0a |
| 13 | Walkthrough A writes "Path 'Teardown'" as if it were a choice | Found | Marked as a label assigned after the choice |

**The rule introduced by these corrections.** Every knowledge record and every check has exactly one status and exactly one tier. The check method is stated separately from the rule status.

**What this is.** A specification of the editorial system, not a discussion. Sections are ordered as follows: entities → decisions → knowledge records → order → fallback outcomes → checks → memory → observability. There is no code and no work plan here. Open questions stay open (section 14).

**What it is assembled from:**

- knowledge map v0.1;
- flow diagram v2;
- four rounds of cross-review with GPT;
- the owner's requirement of autonomy after client setup.

---

## 0. How to read

**Numbering:**

| Prefix | What it denotes |
|---|---|
| `I-` | Invariants |
| `E-` | Entities |
| `S-` | Flow stages |
| `K-` | Knowledge records |
| `V-` | Checks |
| `R-` | Autonomous resolution outcomes |
| `OPEN-` | Open questions |

**Evidence classes:**

| Code | Class |
|---|---|
| `REPO` | Repository review at `87ea0f4` |
| `RES` | Scientific research |
| `PLAT` | Official platform data |
| `VEND` | Vendor data and surveys |
| `OBS` | Our teardown of 13 long-form texts and posts |
| `CLIENT` | Client document |
| `OWNER` | Owner decision or Sveta's methodology |
| `NBX-engine` | Controlled production runs of the current engine: Invisalign, the rerun after #279/#280, the 11-item run, `stage_routing.json`. Claude has not seen the primary artifacts |
| `NBX-map` | Experiments with this map. None so far |
| `INF` | Inference |

**Knowledge record statuses:** descriptive / candidate / client rule / invariant.

**Precedence tiers:** 0–6 (section 5). `A` — architectural invariant: a rule of how the system is built, not of text content.

**Confidence:** H — high, M — medium, L — low.

---

## 1. System invariants

| ID | Invariant | Basis |
|---|---|---|
| **I-01** | **A production run never waits for a human.** Every unresolved state ends in one of four outcomes: `RESOLVE`, `DEGRADE`, `REPLAN`, `SKIP` (section 6) | `OWNER` |
| **I-02** | Humans act only during client setup and in offline system maintenance (section 12), not during a production run | `OWNER` |
| **I-03** | No text contains a source observation, evidence claim, name, figure or causal link outside the Evidence Core. No text asserts more strongly than the ceiling | `REPO` + `CLIENT` |
| **I-04** | The chain `editorial_thesis → interpretation → evidence_claim → source_observation` is never broken. A break means fabrication | `INF` (round 3) |
| **I-05** | Texts do not express interpretations marked inadmissible in the Interpretation Boundary | round 4 |
| **I-06** | Destinations are siblings. No text is the source of another. All rely on the Evidence Core and the Interpretation Boundary | #283 |
| **I-07** | The texts of one Editorial Unit carry one anchor interpretation and do not contradict each other | rounds 3–4 |
| **I-08** | Editorial decisions are made before prose and recorded. The Writer executes the plan | `RES` + #283 |
| **I-09** | A failure returns to the layer where the wrong decision was made: phrasing → Writer, structure → strategy, interpretation → boundary, lack of material → enrichment or `SKIP` | round 4 |
| **I-10** | Labels (material type, strategy type, form) are assigned **after** the decision, for observability. They do not serve as a route | round 4 |
| **I-11** | Knowledge in the map is not a routing table. A strong candidate is not mandatory. Every deviation and every choice is recorded | #283 |
| **I-12** | Soft signals (section 9) do not become thresholds without an owner decision | `RES` (Goodhart) |
| **I-13** | Research findings do not become hard checks without approval | #283 |

---

## 2. Entities

| ID | Entity | What it contains | Who creates it | Who uses it |
|---|---|---|---|---|
| **E-01** | Source signal | Material from the queue: article, source, date | Signal collection | S-00 |
| **E-02** | Source observation (`source_observation`) | What is recorded in the source: a quote, number, event, with attribution ("source X reports Y") | S-01, S-03 | E-03 |
| **E-03** | Evidence claim (`evidence_claim`) | A statement about the world grounded in source observations, with a verdict (accepted / with caveat / rejected), strength and ceiling | S-01, S-03 | E-06, checks |
| **E-04** | Evidence Core | All E-02 and E-03 for the signal, with provenance | S-01, updated in S-03 | All subsequent stages |
| **E-05** | Material features | Feature vector with confidence (section 8.3) and a derived label `material_label` | S-02, updated in S-03 | S-03, S-04, S-08 |
| **E-06** | Asset | Evidentiary (figure, calculation, document, second source, being first) or positional (client position from the contract). With a reference | S-02, S-03 | S-05, S-08 |
| **E-07** | Gap | What is missing: evidence, reader connection, counter-evidence, asset | S-03 | S-03 |
| **E-08** | Interpretation (`interpretation`) | What the evidence claims mean: cause, generalization, comparison, consequence for the reader, forecast. Supports, ceiling, limitations, what contradicts it | S-04 | E-09 |
| **E-09** | Interpretation Boundary | Admissible interpretations + **explicitly inadmissible tempting ones** + limitations (concession candidates) | S-04 | S-05 … S-13 |
| **E-10** | Editorial Unit | A part of the material with one anchor interpretation. By default one per signal | S-05 | S-06 onward |
| **E-11** | Anchor interpretation | One admissible interpretation from E-09, shared by all destinations of the unit | S-06 | S-07 … S-13 |
| **E-12** | Destination | Wix, LinkedIn, Facebook, Instagram, Threads, Telegram | S-07 | S-08 … S-13 |
| **E-13** | Editorial Strategy | A composite configuration (section 7): editorial job, angle, thesis, focal subject, leading material, reader path and evidence order, opening, reveal logic, concession (present or not, and where), ending intention, second interpretation (optional) | S-08, S-09 | S-10 |
| **E-14** | Executable Destination Plan | Strategy plus adaptation: length, format, first-line mechanics, subheadings, hashtags, link to another destination, references, voice brief | S-10, S-11 | S-12 |
| **E-15** | Text | The Writer's output | S-12 | S-13, S-14 |
| **E-16** | Fingerprint | Features, labels, strategy fields, adaptation, text profile, link to the text | S-14 | Portfolio Memory |
| **E-17** | Post-publication observation | Platform metrics, confounders, link to the fingerprint | S-15 | Knowledge queue |
| **E-18** | Knowledge record | Section 8 | Knowledge keeper (offline) | S-00 … S-13 |
| **E-19** | Run trace | Section 11 | All stages | Observability |

**Concepts inside the strategy** (from the round 3 ontology):

| Concept | Definition |
|---|---|
| **Thesis** (`editorial_thesis`) | The idea the text commits to proving. Formulated from admissible interpretations and inherits the ceiling of the weakest one |
| **Angle** | The question or tension the thesis answers, from the reader's point of view |
| **Editorial job** | What the text does for the reader. An open description plus an optional label |
| **Client position** | The authorial point of view from the Client Contract. A positional asset, not evidence |

**Names in the schema:** `source_observation` (E-02), `evidence_claim` (E-03), `interpretation` (E-08), `editorial_thesis`, `angle`, `editorial_job`, `client_position`. The bare word `claim` is not used anywhere as a schema concept. A third-party assertion in the world that we examine (for example, a market assertion) is a `source_observation` with attribution, and the feature of such material is called `contested_assertion`.

---

## 3. Persistent inputs

These inputs are set during setup or updated offline. During a production run they are read-only.

| Input | Content | Who sets it | Where it enters |
|---|---|---|---|
| **Client Contract** | Business and stance; **approved client positions** (positional assets); internal data cleared for use; evidence policy and ceiling; prohibitions (phrases and construction types); allowed and forbidden topics; **risk level**; rules for resolving its own contradictions; AI image policy; skip-or-soften mode (`OPEN-P1`) | Client setup | S-00, S-03, S-08, S-09, S-11, S-13 |
| **Audience Profile** | Who reads, what resonates, English level, cultural context | Setup | S-04 (reader connection), S-08 |
| **Editorial Lens** | How the client looks at the signal on a given day or in a given column. Participates in choosing the editorial job but does not set it | Setup (a separate part of the product) | S-08 |
| **Platform Knowledge** | `K-DST-*` records with a verification date and a review deadline | Knowledge keeper | S-07, S-08, S-10, S-11 |
| **Portfolio Memory** | Fingerprints of this client's texts and, as a candidate, other clients' texts | Code (S-14) | S-00, S-05, S-08, S-09, V-S05 |
| **Reference Library** | 3–5 references per form and destination, annotated "take / do not copy" | Setup + keeper | S-11 |
| **Knowledge map** | Section 8 | Keeper | All planning stages |

---

## 4. Flow

For each stage: what comes in, what decision is made, who makes it, what knowledge it relies on, what comes out, and which outcomes are possible in an unresolved state.

```
S-00 Signal selection → S-01 Evidence Core → S-02 Material features
→ S-03 Enrichment loop (updates S-01, S-02, assets) → S-04 Interpretation Boundary
→ S-05 Editorial Units → S-06 Anchor → S-07 Destinations
→ S-08 Candidate strategies → S-09 Strategy choice → S-10 Executable plan
→ S-11 Plan check + references → S-12 Writer → S-13 Text check
→ S-14 Publication and fingerprint → S-15 Observation
```

| Stage | Decision | Who | Knowledge | Output | Outcomes |
|---|---|---|---|---|---|
| **S-00 Signal selection** | Whether the signal suits the client; which of the suitable ones to take given the portfolio | Model against the contract + code | Contract, `K-DIV-*`, memory | Selected signal | `SKIP` unsuitable ones |
| **S-01 Evidence Core** | Which source observations and evidence claims exist, with which verdicts | Model + code | Evidence policy | E-04 (initial) | — |
| **S-02 Material features** | Feature vector, initial assets | Model + code (reference check) | `K-MAT-*` (section 8.3) | E-05, E-06 | — |
| **S-03 Enrichment loop** | Which gaps to close and with which search; when to stop | Model + code | `K-AST-*`, `K-PRC-08` | Updated E-04, E-05, E-06 | `RESOLVE` (gap closed) / `SKIP` (stop condition with no admissible interpretation) |
| **S-04 Interpretation Boundary** | Which meanings are admissible, which inadmissible, which limitations apply | Model + code (supports, ceiling) | `K-EVD-*`, `K-TEN-*`, `K-CON-*`, `K-RDR-*` | E-09 | `DEGRADE` (weaken) / `SKIP` (not a single admissible one) |
| **S-05 Editorial Units** | Whether to split the signal into independent units | Model + code | `K-UNIT-01` | E-10 | Each unit passes S-06 on its own |
| **S-06 Anchor** | Which admissible interpretation is the unit's anchor | Model | `K-PRC-03`, `K-RDR-*` | E-11 | `DEGRADE` (weaker anchor) / `SKIP` (no provable anchor) |
| **S-07 Destinations** | Which destinations need a text for this unit | Model + contract | `K-DST-*`, `OPEN-15` | Set of E-12 | Excluding a destination = its `SKIP` |
| **S-08 Candidate strategies** | 2–4 internally consistent strategies per destination | Model | `K-MAT-*`, `K-OPN-*`, `K-REV-*`, `K-END-*`, `K-JOB-*`, `K-FOC-*`, lens, reader, portfolio | E-13 candidates | `REPLAN` if none is admissible, → S-06 |
| **S-09 Strategy choice** | Which candidate is chosen and why | Model + code (precedence) | Section 5, `K-PRC-06` | E-13 with a record: admissible / excluded + reason / chosen / what decided the choice | `DEGRADE` (safest admissible) |
| **S-10 Executable plan** | Adaptation to the destination without changing meaning | Code + model | `K-DST-*` | E-14 | — |
| **S-11 Plan check** | Whether the plan passes the `V-P*` checks before writing; reference selection | Code + model | Section 9, `K-EXM-*` | Approved E-14 | `REPLAN` → S-08 (on repeated failure → S-06); `SKIP` of the destination after the limit |
| **S-12 Writer** | Execute the plan. If the plan does not hold, do not improvise | Model | Plan, references, brief | E-15 | "Plan does not hold" signal → `REPLAN` |
| **S-13 Text check** | Whether the text passes `V-T*` | Code + model | Section 9 | Accepted E-15 | Route per I-09; after the limit — `SKIP` of the publication |
| **S-14 Publication** | Publish; record the fingerprint | Code | — | E-16 | — |
| **S-15 Observation** | Collect metrics, link them to the fingerprint, queue them for knowledge | Code | `K-PRC-10` | E-17 | Knowledge statuses are changed only by the keeper, offline |

**Decision or adaptation** (criterion from round 3). If a change alters what the reader should believe or do, it is a decision (S-06 … S-09). If it alters only delivery, it is an adaptation (S-10).

---

## 5. Precedence model

Confidence and authority are different dimensions. In a conflict, the higher tier wins. Within tier 3, the record with higher confidence wins.

| Tier | What | Note |
|---|---|---|
| **0a** | Facts and evidence (I-03, I-04, I-05) | Absolute. Implemented separately from 0b and 0c |
| **0b** | Law | Absolute |
| **0c** | Ethics and safety | Absolute |
| **1** | Hard platform policy: what gets a post removed or an account penalized | The client cannot override |
| **2** | Approved client rule | Cannot require violating tiers 0–1 |
| **3** | Editorial knowledge: descriptive and candidates | By confidence |
| **4** | Platform ranking knowledge (vendor correlations) | Weaker than editorial |
| **5** | Portfolio preference | Soft pressure, decides ties |
| **6** | Stylistic preference | — |

**Rules:**

1. A candidate client rule, until approved, sits at tier 3.
2. A contradiction within tier 2 is resolved by the resolution rule from the contract. If there is no such rule, the stricter one is taken, low confidence is recorded, and the conflict goes into the report for settings reconciliation.
3. Every application of precedence is recorded in the run trace: which tier won and over what.

---

## 6. Autonomous Resolution Protocol

### 6.1. Four outcomes

| Outcome | What it means |
|---|---|
| **`RESOLVE`** | The state is resolved on evidence: enrichment closed the gap or a candidate is unambiguously best |
| **`DEGRADE`** | Proceed with a safer option: a lower-strength interpretation, a stricter rule, no positional asset, no second interpretation. Low confidence is recorded |
| **`REPLAN`** | Return to the nearest layer where the wrong decision was made (I-09), with a limited number of attempts |
| **`SKIP`** | The unit, destination or publication is not released. The reason is recorded |

**The safest admissible option** means: the lowest-strength of the admissible interpretations, the strictest of the conflicting rules, no positional asset that is not confirmed by the contract, with low confidence recorded.

### 6.2. Unresolved states and outcomes

| State | Outcome |
|---|---|
| The signal does not fit the contract, topics or risk level | `SKIP` |
| No asset or admissible interpretation | Enrichment (S-03) → `RESOLVE`; on a stop condition → `SKIP` |
| A client position is needed that is not in the contract | Write without it (`DEGRADE`) if the anchor holds; otherwise `SKIP`. Do not invent the position |
| Evidence conflicts, the ambiguity is **not** in the anchor | `DEGRADE`: a lower-strength interpretation or an explicitly named ambiguity |
| Evidence conflicts **in the anchor** | Enrichment → weaken the anchor (`DEGRADE`) → if there is no provable anchor, `SKIP` the unit |
| High stakes outside the contract's risk level | `SKIP` |
| Client rules contradict each other | Resolution rule from the contract, otherwise the stricter one (`DEGRADE`) + report |
| Several equal strategies | `RESOLVE` via "what decided the choice" by precedence (section 7.3) |
| No admissible strategy | `REPLAN` → S-06; on repeat → `SKIP` the unit |
| The plan's promise is wider than the boundary (e.g. "3 things" with two interpretations) | `REPLAN` → S-08 |
| The unit's destinations contradict each other | `REPLAN` of the destination that deviated from the anchor |
| The Writer signals "plan does not hold" | `REPLAN` → S-08 |
| Structural failure in the text | `REPLAN` → S-08; after the limit `SKIP` the publication |
| The text contains an invented or inadmissible interpretation | `REPLAN` → S-04 or S-08 (not to the Writer) |
| Failure of facts or phrasing | Text edit; after the limit `SKIP` |
| Platform knowledge is expired | Automatically downgraded to a weak candidate; entry in the keeper's queue |

### 6.3. Limits and accounting

- Every loop (enrichment, replan, edit) has an attempt limit and a budget. The specific numbers are an implementation decision, not the map's.
- **The skip rate is the main indicator of autonomous operation.** It is counted by client, destination and reason. If there are many skips, the calendar empties. If there are few with weak material, the system has probably become too permissive.
- The reason for every `SKIP` and every `DEGRADE` is recorded. From this it is visible offline what the Client Contract is missing.

---

## 7. Strategy

### 7.1. Strategy fields

A strategy is a composite configuration, not a choice from a list.

| Field | What is recorded |
|---|---|
| Anchor | Reference to E-11 |
| Second interpretation | Optional, only from the boundary |
| Editorial job | Open description |
| Angle | Reader's question |
| Thesis | One sentence, supported by interpretations |
| Focal subject | Company, owner-reader, client, person from the story |
| Leading material | Which fact or case carries the entry |
| Reader path and evidence order | Sequence of moves, each with a reference to the registry |
| Opening | What comes first and which variable is held back |
| Reveal logic | Immediate / gradual / delayed until which point |
| Concession | Present or not; which; where |
| Ending intention | Decided after the opening |
| Justifications | Why each field follows from the others |

### 7.2. How it is generated and checked

1. **Generated as a batch.** The planner creates 2–4 whole strategies, each internally consistent. Fields are not chosen one at a time.
2. **Stored by fields**, with a justification for each field.
3. **Checked by the links between fields** (`V-P01`).
4. **Labels are assigned after** the choice, by a separate classifier (I-10).
5. **Anti-template test.** The label must not predict the rest. Computed over the portfolio as signal `V-S06`.

### 7.3. What decides between equals

Tie-breakers are applied in order:

1. Fit with the evidence.
2. Fit with the destination.
3. Lower interpretation risk (lower strength relative to the ceiling).
4. Asset strength.
5. Client preference from the contract.
6. Portfolio (soft penalty, not rotation).
7. Cost.

The distribution of triggered tie-breakers is itself a portfolio signal (`V-S07`).

### 7.4. Shared level versus destination level

| Shared across the unit | Specific to the destination |
|---|---|
| Evidence Core, Interpretation Boundary, anchor | Editorial job, angle, thesis (within the anchor), focal subject, path, opening, reveal, concession placement, ending |
| Leading material — **under model C** (`OPEN-19`) | All adaptation |

---

## 8. Knowledge registry

### 8.1. Record schema

Each record contains:

1. ID;
2. statement;
3. source;
4. evidence class;
5. confidence;
6. when it applies;
7. conflicts;
8. status;
9. affects;
10. **precedence tier**;
11. **verification date and review deadline** (mandatory for destination records).

Below, the fields are compressed into tables. Full source wording is in knowledge map v0.1. Corrections from rounds 2–4 are applied.

### 8.2. Process, evidence, assets

| ID | Statement | Class | Conf. | Status | Tier | Affects |
|---|---|---|---|---|---|---|
| K-PRC-01 | Structure is decided before prose | `RES` + practice | H (coherence) / L (interestingness) | Invariant | A | The whole plan |
| K-PRC-02 | Editing by the same model does not fix structure and erases the voice | `RES` + `NBX-engine` (indirectly) | M | Descriptive | 3 | I-09 routing |
| K-PRC-03 | Choosing among several whole variants is better than rewriting one | `RES` | M | Candidate | 3 | S-06, S-08 |
| K-PRC-04 | An AI judge of taste does not agree with experts; a model checks explicit criteria well | `RES` | M–H | Descriptive | 3 | Check classes |
| K-PRC-05 | Diversity is built into the plan; quality and diversity conflict | `RES` | M | Descriptive | 3 | S-08, S-09 |
| K-PRC-06 | Choice record: admissible / excluded + reason / chosen / what decided the choice | `OWNER` | — | Candidate for invariant | A | S-09 |
| K-PRC-07 | The Writer does not improvise when the plan is broken but signals `REPLAN` | `RES` + `INF` | M | Candidate | A | S-12 |
| K-PRC-08 | An asset can be created at the enrichment stage. What is created enters the core with provenance; a calculation is reproducible. A loop with a stop condition | `RES` (STORM) + `VEND` + `INF` | M | Candidate | 3 | S-03 |
| K-PRC-09 | Delivering a client document to a stage ≠ executing it | `REPO` + `NBX-engine` | M | Descriptive | 3 | Plan execution check |
| K-PRC-10 | A result is an observation, not evidence. Status changes after a minimum number of observations, accounting for confounders, by the keeper's decision | `INF` + `RES` (Goodhart) | — | Candidate | A | S-15 |
| K-EVD-01 | Facts only from the core, within the ceiling | `REPO` + `CLIENT` | H | Invariant | 0a | Everything |
| K-EVD-02 | Rejected evidence is not used | `REPO` | H | Invariant | 0a | S-04 |
| K-EVD-03 | The boundary stores tempting inadmissible interpretations (a design technique; the ban on expressing them is I-05) | round 4 + `OBS` (uranium and Ramp outputs) | M | Candidate | A | S-04, V-T02 |
| K-AST-01 | Strong texts have an irreplaceable asset | `OBS` + `VEND` + `PLAT` | M | Descriptive | 3 | S-00, S-06 |
| K-AST-02 | No asset after enrichment → flag; outcome per section 6 | `INF` | L | Candidate | 3 | S-03 |
| K-AST-03 | Never Blank assets: Sveta's case, Lera's case, the stance on automation | `OWNER` | — | Candidate client rule | 3 | Contract |
| K-AST-04 | Evidentiary asset ≠ positional asset. A positional asset is taken only from the contract: attributing to the client a position that is not there is invented attribution (I-03) | round 2 + I-03 | H | Invariant | 0a | S-03, S-08 |
| K-UNIT-01 | A signal is split into units if two interpretations are independent and lead to different editorial jobs. Each unit passes the checks on its own; splitting accounts for the calendar | rounds 3–4 | — | Candidate | 3 | S-05 |

### 8.3. Material features and reader paths

**Features** (each with its own confidence):

- `documented_case`
- `named_company`
- `figure_provenance` (own / third-party / none)
- `method_known`
- `freshness`
- `mechanism_present`
- `real_scene` (with a source)
- `first_person`
- `failure_cost`
- `contested_assertion` (a third-party assertion that the evidence contests)
- `parallel_structure`
- `open_question`

The `material_label` is derived from the features after analysis (I-10).

The paths below are descriptions of reader paths, not routes. The condition is on features and the boundary. Path names ("Finding", "Teardown", etc.) are labels for description and observability. Checks do not use them (I-10): they check strategy fields.

| ID | Path (label) | Strong candidate if… | Excluded if… | Class, conf., status |
|---|---|---|---|---|
| K-MAT-01 | Finding: how it was measured → what came out → how it works → what it costs | `figure_provenance = own` and `method_known` | The figure is third-party | `OBS` + `CLIENT`, M, descriptive, tier 3 |
| K-MAT-02 | Teardown: case → what is wrong → how to do it right → what transfers | `documented_case` and `named_company`; transfer in the ending is almost always needed | Nothing to say beyond a retelling | same |
| K-MAT-03 | Post-mortem: what broke → why → the cost → what was changed | `failure_cost` | Failure without details | same |
| K-MAT-04 | Argument: third-party assertion → where it does not add up → how it really is → turn | `contested_assertion` and counter-evidence in the boundary | Nothing to argue with | same |
| K-MAT-05 | Explainer: how it works → where it breaks → what to do | `mechanism_present`, mechanism in the boundary | The mechanism is a guess | same |
| K-MAT-06 | Reader questions | High `freshness` and several open questions in the boundary | The news is simple | same |
| K-MAT-07 | Scene: scene → thesis → evidence → return | `real_scene` with a source | There is no real scene. A scene passed off as real without a source violates I-03 (`K-OPN-03a`); for a hypothetical scene see `K-OPN-03b` | same |
| K-MAT-08 | Frame and points | `parallel_structure` and enough admissible interpretations for the points | More points than interpretations (I-05) | same |
| K-MAT-09 | Inquiry; a final question is appropriate | A genuine `open_question` | There is an answer | same |
| K-MAT-10 | The path follows from the material, not from the client's niche | — | — | `OBS` + practice, M, descriptive, tier 3 |
| K-MAT-11 | With two paths — the one where the price we paid is visible | — | — | `CLIENT`, NB client rule, tier 2 |
| K-MAT-12 | If no path fits, write what the material is, with a note. A forced path is worse | — | — | `CLIENT`, client rule, tier 2 |

### 8.4. Opening, reveal, tension, concession, ending, focal subject, editorial job

| ID | Statement | Class | Conf. | Status | Tier |
|---|---|---|---|---|---|
| K-OPN-01 | Tension in sentences 1–2 in all 13 strong texts | `OBS` | M | Descriptive | 3 |
| K-OPN-02 | Specifics in the first sentence — in 9 of 13, not always | `OBS` | M | Descriptive | 3 |
| K-OPN-03a | A scene passed off as real without a source is a violation of I-03 | I-03 | H | Invariant | 0a |
| K-OPN-03b | A hypothetical reader scene ("Suppose you…", "Imagine…", "picture this: you're a business owner…") is a strong AI pattern: in the current engine it is produced by the `aha_setup` and `founder_scenario` fields, and the opening recurred across runs. A hypothesis explicitly presented as a hypothesis is not a fact. The reader's stake is better recorded as a fact (`reader_stake`). The client may forbid the pattern with a tier 2 rule | `REPO` + `OBS` + `NBX-engine` | H (for the current engine) | Candidate | 3 |
| K-OPN-04 | NB hook: a number, a named company or a contradiction | `CLIENT` (doc 12) | — | Client rule | 2 |
| K-OPN-05 | Keep one variable in reserve; excessive specifics in the opening reduce response | `CLIENT` + `RES` (Upworthy) | M | Descriptive | 3 |
| K-OPN-06 | A question opening is the worst on LinkedIn, a story opening the best | `VEND` | L–M | Descriptive | 4 |
| K-OPN-07 | A question works if there is a real puzzle behind it | `OBS` + `INF` | M | Descriptive | 3 |
| K-REV-01 | By default reveal immediately; delay if the material justifies it | `CLIENT` | — | Client rule | 2 |
| K-REV-02 | A delayed thesis in journalism — no later than the 5th paragraph | `OBS` | M | Descriptive | 3 |
| K-REV-03 | Resolve a delayed puzzle within about 4 sentences | `CLIENT` / `OWNER` (#277) | — | Candidate | 3 |
| K-REV-04 | Short form reveals immediately; detail in lines 1–2 | `OBS` + `PLAT` | M | Descriptive | 3 |
| K-TEN-01 | Tension only from the material | practice + `INF` | M | Candidate | 3 |
| K-TEN-02 | Contradiction between the source and our data → Evidence Tension lens | `CLIENT` + `REPO` | — | Client rule | 2 |
| K-CON-01 | A genuine concession in 12 of 13 texts; placement is free | `OBS` | M | Descriptive | 3 |
| K-CON-02 | Concession only genuine, with a reference; do not invent | `CLIENT` | — | Client rule | 2 |
| K-CON-03 | In a short post an admitted mistake plays the role of the concession | `OBS` + `INF` | L | Descriptive | 3 |
| K-END-01 | The ending does not recap | `OBS` | M | Descriptive | 3 |
| K-END-02 | NB: the last line is the Echo; after it only sources | `CLIENT` + `REPO` | — | Client rule | 2 |
| K-END-03 | The return to the opening is decided after the opening and reframes it | `CLIENT` | — | Client rule | 2 |
| K-END-04 | A question at the end of a post gives almost nothing | `VEND` | L | Descriptive | 4 |
| K-FOC-01 | The focal subject is a strategy variable, derived from features, evidence and path | `CLIENT` + `OWNER` + `INF` | — | Candidate | 3 |
| K-JOB-01 | The editorial job is a strategy decision, separate from angle and path. The lens participates in the choice but does not set it | rounds 2–4, practice | M | Candidate | 3 |

### 8.5. Reader

| ID | Statement | Class | Conf. | Status | Tier |
|---|---|---|---|---|---|
| K-RDR-01 | The US business reader values proprietary data, problem framing, cases, a fresh perspective, a human tone; considers 15% of texts "very good" | `VEND` (Edelman–LinkedIn; 2025 geography not confirmed) | M | Descriptive | 3 |
| K-RDR-02 | US small business: money and time (overdue invoices 39%, taxes 77%, less than an hour on marketing for 42%) | `VEND` | M | Descriptive | 3 |
| K-RDR-03 | The B2B buyer verifies AI answers (94%) | `VEND` | M | Descriptive | 3 |
| K-RDR-04 | Visible sources remove the penalty for an "AI" label | `RES` | M | Descriptive | 3 |
| K-RDR-05 | For a reader with English as a second language, simplify the form, not the thought | practice + `RES` | M | Candidate | 3 |
| K-RDR-06 | Models Americanize text and erase cultural details | `RES` | M | Descriptive | 3 |
| K-RDR-07 | Detectors misfire on writers with English as a second language; the defense is specifics, not "unpredictable" words | `RES` (from memory) + `INF` | L–M | Descriptive | 3 |

### 8.6. Destinations

For all records: verification date 2026-09-21, review by 2026-12-21. After the deadline the record is automatically downgraded (section 6).

| ID | Statement | Class | Status | Tier |
|---|---|---|---|---|
| K-DST-WIX-01 | Subheadings that state a conclusion, the main point first, visible sources (readers scan the text) | practice | Descriptive | 3 |
| K-DST-WIX-02 | For citation in AI search — adjacent questions as separate sections (Google splits a query into sub-questions) | `VEND` | Descriptive | 4 |
| K-DST-WIX-03 | Google sanctions scaled unoriginal content regardless of how it was created | `PLAT` | Platform rule | 1 |
| K-DST-LI-01 | ~250–400 words; document carousel ×1.39 reach; first line ≤40 characters; one idea | `VEND` + `PLAT` | Descriptive | 4 |
| K-DST-LI-02 | "AI slop" filter: complaints + classifiers, about −40% out-of-network views, a private notice to the author. The criteria are not disclosed, so no checkable rule follows from this; what follows is an editorial conclusion — avoid overused patterns, specifics in lines 1–2 | `PLAT` | Descriptive | 3 |
| K-DST-LI-03 | Automated comments and automated engagement are blocked | `PLAT` | Platform rule | 1 |
| K-DST-META-01 | Duplicates, "minor edits" and an account's unoriginal stream lead to demotion and loss of recommendation eligibility (Instagram assesses the stream over a month) | `PLAT` | Platform rule | 1 |
| K-DST-META-02 | Photorealistic AI media (video, audio) require disclosure | `PLAT` | Platform rule | 1 |
| K-DST-META-03 | The "AI info" label is applied automatically from C2PA/IPTC image metadata; text gets no label | `PLAT` | Descriptive (mechanism) | — |
| K-DST-FB-01 | Text status holds among the top formats; posts with links perform worse | `VEND` | Descriptive | 4 |
| K-DST-FB-02 | Engagement bait and long hashtag captions unrelated to the image are demoted and demonetized | `PLAT` | Platform rule | 1 |
| K-DST-IG-01 | Carousel — engagement and saves, Reels — reach; one idea per slide; keywords after the first line; 0–3 hashtags | `VEND` + `PLAT` | Descriptive | 4 |
| K-DST-TH-01 | Plain text is half as strong as video; text + image; feed leans to follows | `VEND` + `PLAT` | Descriptive | 4 |
| K-DST-TH-02 | Live author replies give +42%. **Unavailable in an autonomous system** — this is knowledge for the Client Contract, not for the production run | `VEND` | Descriptive | 4 |
| K-DST-TG-01 | No feed; the reader punishes; growth through forwards; AI summaries of long posts — thesis in the first line and paragraph | `PLAT` + `INF` | Descriptive | 3 |
| K-DST-ALL-01 | Platforms do not report "AI or not"; demotion is visible in non-follower reach and account statuses | `PLAT` | Descriptive | — (measurements) |

### 8.7. Voice, references, diversity

| ID | Statement | Class | Conf. | Status | Tier |
|---|---|---|---|---|---|
| K-VOI-01 | A long "don't" list barely works; voice — a short positive brief, the long style guide — into checks | `RES` | M–H | Descriptive | 3 |
| K-VOI-02 | Sveta's method: no negations and no "not this, but that", no unnecessary em dashes, clipped sentences, enumerations where fitting, the text has a purpose | `OWNER` | — | Candidate NB client rule | 3 (until approved) |
| K-VOI-03 | Typical AI patterns are born from structure, not words | `REPO` + `OBS` + `NBX-engine` | H | Descriptive | 3 |
| K-EXM-01 | References beat abstract rules for register and form; ceiling at 2–5 examples; selection by text type, not by topic | `RES` | M | Descriptive | 3 |
| K-EXM-02 | Only fine-tuning on a large corpus gives an exact voice | `RES` | M | Descriptive | 3 |
| K-EXM-03 | 1–4 references annotated "take / do not copy", with a copying check | `REPO` + `INF` | — | Candidate | 3 |
| K-EXM-04 | In `research/angles.yaml` the hook example contradicts the client's prohibition | `REPO` | H | Descriptive (engine debt, #281) | — |
| K-DIV-01 | AI improves an individual text but makes the set similar; switching models does not help | `RES` | M | Descriptive | 3 |
| K-DIV-02a | Structural repetitiveness in one client's portfolio — soft pressure | `PLAT` + `RES` | M | Candidate | 5 |
| K-DIV-02b | Near-verbatim texts across different clients probably fall under duplicate rules (not directly confirmed) — soft pressure with high weight | `PLAT` (plausible) | L–M | Candidate | 5 |
| K-DIV-02c | A recognizable "factory" structure across different clients | `OWNER` | — | Candidate product policy (`OPEN-P2`) | 5 |
| K-DIV-03 | Soft pressure instead of quotas | `RES` + `INF` | M | Candidate | 5 |
| K-DIV-04 | Text fingerprint (E-16) | `INF` | — | Candidate | A |
| K-DIV-05 | Audit: change the path for the same material; if nothing is lost, the choice was arbitrary | `INF` | — | Audit method | — |
| K-DIV-06 | Republishing a near-exact text on the same destination is a duplicate under platform rules | `PLAT` | H | Platform rule | 1 |

---

## 9. Checks

All checks run without a human. Taste judgments are moved to offline review by the owner (section 12).

### 9.1. Plan checks (S-11, before writing)

| ID | Check | Type | On failure |
|---|---|---|---|
| V-P01 | Strategy fields are consistent with each other. Examples: a delayed reveal is incompatible with short-form length; an opening built on a figure requires that figure in the core; if the reader path makes a case the subject of a move, `documented_case` is mandatory and confirmed in the core; the second interpretation is in the boundary. Path labels are not used in the check (I-10) | Code + model against an explicit criterion | `REPLAN` → S-08 |
| V-P02 | The plan's promise ⊆ the boundary: the number of points is no greater than the number of admissible interpretations, no inadmissible interpretations | Code | `REPLAN` → S-08 |
| V-P03 | The unit's destinations do not contradict each other and carry the anchor | Model against an explicit criterion | `REPLAN` of the deviating destination |
| V-P04 | Compliance with the Client Contract (tier 2) and hard platform policy (tier 1) | Code + model | `REPLAN` / `SKIP` of the destination |
| V-P05 | Portfolio pressure is taken into account | Code | Soft signal |

### 9.2. Text checks (S-13)

Status refers to the rule. Method refers to the means of detection: it may be probabilistic even if the rule is an invariant.

| ID | Check | Class | Rule status | Method | Route |
|---|---|---|---|---|---|
| V-T01 | Source observations, evidence claims, figures, names only from the core; strength within the ceiling (I-03) | H | Invariant | Code (reconciliation with the core) + model against an explicit criterion | Edit → `SKIP` |
| V-T02 | No interpretations marked inadmissible in the boundary (I-05) | H | Invariant | Model against an explicit criterion + reconciliation with the list of tempting inadmissible ones | `REPLAN` → S-04 / S-08 |
| V-T03 | The chain `editorial_thesis → interpretation → evidence_claim → source_observation` without a break (I-04) | H | Invariant | Code (links in the plan) + model against an explicit criterion (text matches the plan) | `REPLAN` → S-08 |
| V-T04 | No invented links or sources (I-03) | H | Invariant | Code | Edit → `SKIP` |
| V-T05 | No republication of a near-exact text (`K-DIV-06`) | H | Platform rule | Code | `SKIP` |
| V-T06 | No forbidden client phrases and constructions | H | Client rule | Code (phrases) + model (construction types) | Edit |
| V-T07 | The text executed the plan: opening, path, concession in place | H | Candidate | Model against an explicit criterion | `REPLAN` → S-08 |
| V-T08 | The Echo reframes the opening rather than recapping it | H | Candidate | Model against an explicit criterion | Edit → `REPLAN` |
| V-S01 | Construction types: hypothetical reader scene (`K-OPN-03b`), "not X but Y", question in the ending | S | Candidate | Code + model | Hint for editing |
| V-S02 | Words before the first specific, position of the first evidence, abstraction before evidence | S | Candidate (not validated) | Code | Hint |
| V-S03 | Repetition of an idea within the text | S | Candidate | Model / embeddings | Hint |
| V-S04 | Uniformity of paragraph and sentence length | S | Candidate (not validated) | Code | Hint |
| V-S05 | Similarity to the portfolio: path, opening, ending, n-grams | S | Candidate | Code | Memory, S-09 |
| V-S06 | Predictability of fields from the label (anti-template test) | S | Candidate | Code on fingerprints | Report |
| V-S07 | Distribution of tie-breakers | S | Candidate | Code on fingerprints | Report |
| V-S08 | Ending with no progression relative to the thesis (formerly H02) | S | Candidate | Model | Hint |
| V-S09 | Global English rules: idioms, American terms without explanation | S | Candidate | Code + model | Hint |
| V-S10 | Platform ranking knowledge: link in the body of a Facebook post, hashtags | S | Candidate | Code | Hint |

---

## 10. Portfolio Memory and the observation loop

**The fingerprint (E-16)** contains:

- client and destination;
- features and `material_label`;
- strategy fields: editorial job, focal subject, path, opening, reveal, concession, ending;
- adaptation;
- text profile: position of the first evidence, paragraph lengths;
- the chosen tie-breaker;
- the text itself.

**Memory affects:**

- signal selection (S-00);
- splitting into units (S-05);
- strategies and choice (S-08, S-09);
- signal V-S05.

The influence is always soft pressure, not a quota.

**Observation loop:**

1. Plan → text → publication.
2. Platform metrics: saves and shares on Instagram, read time on LinkedIn, mutes and forwards on Telegram, non-follower reach on Meta.
3. Observation E-17, linked to the fingerprint. Confounders are recorded: topic, timing, author reach, news hook.
4. Knowledge keeper's queue: a proposal to change a record's status.
5. The keeper decides offline (I-02).

A metric is evidence, not a target (`K-PRC-10`). The path to `NBX-map` runs not only through passive measurement but also through comparing two plans on similar signals and blind evaluation "with the map versus without the map".

---

## 11. Observability: the trace of every production run

Every production run records:

1. Input versions: Client Contract, Audience Profile, lens, knowledge map, Platform Knowledge (with dates), Reference Library.
2. Evidence Core, features, gaps and enrichment loops: what was searched for, what was found, why it stopped.
3. The Interpretation Boundary, including inadmissible interpretations.
4. The decision on units and anchor.
5. Destinations and reasons for exclusion.
6. For each destination: strategy candidates, those excluded with knowledge record IDs and precedence tier, the chosen strategy, the tie-breaker.
7. Every `RESOLVE`, `DEGRADE`, `REPLAN`, `SKIP` outcome with its reason.
8. Plan and text check results.
9. Cost: calls and tokens per stage.
10. The fingerprint.

**Indicators:**

- skip and soften rates by reason;
- number of replans;
- share of texts passing on the first try;
- cost per published text;
- portfolio similarity signals;
- predictability of fields from the label.

---

## 12. Where humans participate

| When | Who | What |
|---|---|---|
| **Client setup** | Client + Never Blank | Contract: positions, data, topics, risk level, prohibitions, voice, contradiction resolution, AI image policy, skip-or-soften mode. Audience Profile. References. Lenses |
| **Offline: knowledge keeper** | Sveta, Lera | Record statuses, deadline-driven verification of Platform Knowledge, NBX records, approval of candidates for invariants |
| **Offline: client settings reconciliation** | Client + Never Blank | Based on the report on skips, softenings and rule conflicts |
| **Offline: quality review** | Owner | Sampled: "this is Never Blank" or "AI garbage again". The result goes into observations |

**During a production run — no one** (I-01).

---

## 13. Manual walkthroughs on v1

### A · "This Dad Lost His Job and Started Making a Breakfast Staple at Home… $85,000"

| Stage | What happens |
|---|---|
| Features | `documented_case`, `named_company` (a person), `figure_provenance = third-party`, `real_scene = none`, low `freshness` |
| Enrichment | No second source, a kitchen capacity calculation is impossible → weak asset |
| Boundary | Admissible: "growth hit the founder's capacity" (a single case — limitation). Inadmissible: "hiring would have solved the problem" (not in the evidence); "you, the reader, bake at night" (invented scene) |
| Anchor | Founder capacity, softened: a single case |
| Wix | Path case → what is wrong → how to do it right → what transfers (the "Teardown" label is assigned afterwards), opening — a figure and a person, immediate reveal, ending — Echo to "the kitchen", concession "a single case" |
| LinkedIn | "Before/after", first line with a figure |
| Outcome | `DEGRADE` (low confidence due to a weak asset). "Scene" excluded: no real scene (I-03) |

### B · "Ramp Launches Instant Stablecoin Payments with Stripe's New Technology"

| Stage | What happens |
|---|---|
| Boundary | Admissible: "the time it takes to receive money changes". Limitation: "there is not more money". Inadmissible: "the business has more money"; "the compliance checklist doubles" (this conclusion appeared in the real output) |
| Anchor | Time to receive money + limitation |
| Wix | Job — help with a decision; path "Reader questions"; gradual reveal |
| LinkedIn | Job — challenge an assumption. The "X is not Y" realization is excluded by tier 2 (client prohibition) → the same idea via "before/after" |
| Instagram | The "3 things" candidate is excluded by V-P02: the boundary has two interpretations → `REPLAN` → "one thing changes, one does not" |
| Outcome | `RESOLVE` across three destinations |

### C · "U.S. Uranium Production Hits Record High in 2025, Triples from 2024"

| Stage | What happens |
|---|---|
| Enrichment | Searched for a link to small business (contractors, suppliers); stop condition reached |
| Boundary | No admissible interpretation for small business. Inadmissible: "owners were buried in inspections" (appeared in the real output) |
| Outcome | **`SKIP`**, reason "no admissible interpretation for the reader". No human needed during the production run |

### D · Hypothetical signal with two stories: "a company cut costs by 40% and simultaneously took on a regulatory risk"

| Stage | What happens |
|---|---|
| Units | Two independent interpretations, different editorial jobs → split into two units (`K-UNIT-01`) |
| Unit checks | Each passes S-06 on its own. The second unit is deferred by calendar pressure |
| Destinations | The regulatory unit — Wix and LinkedIn only |
| Outcome | Two units with separate anchors, no core with multiple anchors |

**What the walkthroughs showed:**

- all four outcomes occur on real signals;
- no walkthrough required a human;
- the tempting inadmissible interpretations matched real engine errors in two cases out of three.

---

## 14. Open questions

All questions stay open. They are grouped by who decides them and when.

**Architecture** — decided by us with GPT before slicing tasks:

| ID | Question |
|---|---|
| OPEN-15 | Destination selection for a unit: always all, or by material |
| OPEN-18 | Rules for splitting a signal into units and accounting for the calendar |
| OPEN-19 | Model A / B / C. This map leans toward C |
| OPEN-21 | Combining several signals into one unit |

**Implementation** — decided during code design, does not affect the map:

| ID | Question |
|---|---|
| OPEN-06 | Model call structure and cost. Six logical plans ≠ six calls |
| OPEN-05 | Which H candidates are approved and which thresholds (if any) the S signals get |
| OPEN-22 | Loop limits (enrichment, replan, edit) and budgets |
| OPEN-23 | Expiry periods by knowledge class |
| OPEN-24 | Minimum observations and the method of accounting for confounders before a record's status changes |
| OPEN-25 | Portfolio soft-pressure weights and the "near-verbatim" match threshold |

**Product** — candidate forks for the owner. Bring to the owner only those that actually change the result for the client:

| ID | Question | Current assessment |
|---|---|---|
| OPEN-P1 | Weak material: skip more often or release a cautious text more often | Test on real signals first. A rule "soften down to the evidence boundary, below that — skip" may suffice, and a global choice by the owner will not be needed |
| OPEN-P2 | Cross-client memory versus a "factory" signature | Candidate product policy, not blocking |
| OPEN-P3 | Sveta's method as a Never Blank client rule | Test piece by piece with experiments rather than approving as a bundle |
| OPEN-P4 | AI images | A separate policy branch, does not block the editorial map |

**Never Blank client setup** — contradictions in its documents, resolved during contract setup:

| ID | Question |
|---|---|
| OPEN-02 | Final question |
| OPEN-03 | Subheadings |
| OPEN-12 | CTA on LinkedIn |
| OPEN-13 | Delayed reveal limit |

**Deliberately deferred:**

- visuals as a plan;
- the publication stream as a coherent line;
- people in stories;
- global English — the level of simplification (`OPEN-14`);
- client trust mode (`OPEN-20`): partly removed by the autonomy requirement.

---

## 15. What is not confirmed

- Links from GPT's research have not been rechecked.
- Claude has not seen the `NBX-engine` artifacts; records citing them rest on the descriptions in #277 and #283.
- The "material → reader path" path rests on 13 texts without a second annotator.
- Platform data are vendor correlations with small effects and an expiry date.
- All walkthroughs are manual.
- There are no controlled experiments on business texts. `NBX-map` is empty.
