# Editorial Knowledge Map

*Version 0.1 · 21 September 2026 · for issue #283 · RESEARCH / DESIGN — HOLD, no code*

---

## 0. What this is and how to read it

This is the **knowledge map** the Planner uses to assemble a plan for a specific text for a specific destination. The map does not write the text and does not choose values on the Planner's behalf. It stores what we know:

- which material properties make a form suitable or unsuitable;
- which opening rests on the available evidence;
- when the reveal can be delayed;
- what requires a concession;
- what the destination constrains;
- what diversity must be maintained across texts and clients.

The architecture around the map is described in the document "Map: from signal to texts for each destination", version 2. This document covers only the knowledge itself and how to use it.

### 0.1. Knowledge entry format

Each knowledge entry has a number and eight fields. These are the eight questions from #283.

| Field | Question |
|---|---|
| **Statement** | What is the rule or conclusion? |
| **Source** | Where did it come from? |
| **Evidence class** | What supports it? (codes below) |
| **Confidence** | High / medium / low |
| **Applies when** | Under what conditions? |
| **Conflicts** | What does it conflict with? |
| **Status** | Descriptive evidence / policy candidate / client rule / invariant |
| **Influences** | Which plan decisions? |

**Evidence class codes**

| Code | Class |
|---|---|
| `REPO` | Review of the `never-blank-pipeline` repository at `87ea0f4` |
| `RES` | External scientific research |
| `PLAT` | Official platform documentation or statements |
| `VEND` | Vendor data and industry surveys |
| `OBS` | Our observation: review of 13 long-form texts and LinkedIn posts |
| `CLIENT` | Client document (`clients/never_blank/…`, doc 12) |
| `OWNER` | Owner decision or Sveta's methodology |
| `NBX` | Never Blank controlled experiment. **None yet** |
| `INF` | Inference from sources |

**Statuses**

| Status | What it means for the system |
|---|---|
| **Descriptive** | This is how strong texts are built or how the platform behaves. The Planner takes it into account, but it is not a rule |
| **Candidate** | Proposed policy. Works as a signal or flag; the decision belongs to a human until it is approved |
| **Client rule** | The client approved it in their document. Applies to that client |
| **Invariant** | Applies always and to everyone, enforced by code |

**Important.** In this version almost all entries are descriptive or candidates. There are few invariants, and this is deliberate. Entries will be approved after a cross-review.

---

## 1. Inputs: signal beads

The Analyzer extracts beads **from the signal and the evidence found**. A bead is a property of the material, not a decision. The schema is not yet approved: what is recorded here is an idea, not a final interface.

| Bead | What it is | Values | Who extracts | In the engine today |
|---|---|---|---|---|
| `material_type` | Material type: one primary, sometimes a secondary | `own_figure`, `company_case`, `failure`, `market_claim`, `mechanism`, `fresh_news`, `human_story`, `parallel_points`, `open_question` | Model | ❌ |
| `asset` | Irreplaceable asset that not everyone writing on this topic has | Type (own figure / case with details / document / calculation / being first / client's position / first person) + evidence reference, or `none` | Model; code verifies the reference | ❌ |
| `evidence` | Evidence package with verdicts "accepted / with caveat / rejected" | Ledger entries | Model + code | ✅ |
| `evidence_strength` | How strong a claim the material can bear | Claim-strength ceiling | Code + client document | ✅ |
| `named_entities` | Named companies, people, places | List with evidence references | Model | 🟡 (present in the signal, not as a bead) |
| `figures` | Figures in the material | List with references | Code + model | 🟡 (figure reconciliation exists) |
| `tension` | What doesn't add up in the material itself | Contradiction / puzzle / threatening figure / competing explanations / cost / none | Model | 🟡 (only "source vs. our data") |
| `failure_cost` | Failure or cost, if any | Text + reference, or `none` | Model | ❌ |
| `first_person` | First-person material: from the client, the author, a person in the story | Yes / no + reference | Model | ❌ |
| `reader_stake` | Why this concerns the reader. Recorded as a fact, not as a scene | Short statement tied to the reader profile | Model | 🟡 (currently the scene "the owner recognizes themselves") |
| `timeliness` | What makes the topic relevant now | Short statement or `none` | Model | ❌ |
| `angle_candidates` | 2–3 ideas the material is capable of proving | List | Model | ❌ |
| `authority` | By what right we claim this | Own data / access / client expertise / only someone else's source | Model + client document | ❌ |
| `restrictions` | What must not be claimed: facts, ethics, law | List | Client document + model | ✅ (`factual_restrictions`, `acknowledged_limits`) |

### 1.1. External context (not beads)

This does **not come from the signal**, so it is not mixed with the beads. The Analyzer does not extract it. The Planner receives it ready-made.

| Context | What it is | Where from | Today |
|---|---|---|---|
| Client profile | Business, position, what we say and what we don't | Client document | ✅ |
| **Reader profile** | Who reads, what hits home, English level | Client document | 🟡 |
| Voice | Short brief in positive form | Client document | 🟡 |
| Bans | Phrases and construction types | Client document | 🟡 (exact phrases only) |
| Allowed forms | List of forms the client permits, with per-destination adjustments | Client document | ❌ |
| Lens of the day or of the rubric | How the client looks at the signal today | Client document, a separate part of the product | 🟡 |
| Destination set | Where a text is needed for this signal | Client document + Planner | 🟡 |
| **Portfolio memory** | Fingerprints of recent texts by this client and other clients | Code | ❌ |
| **Exemplar library** | Exemplars by form and destination, annotated | A human selects, code retrieves | ❌ |
| Knowledge map | This document | Us | — |

---

## 2. Boundary: Editorial Core and destination plan

One core per signal. One plan per destination.

| Decision | Where | Why |
|---|---|---|
| Evidence ledger | **Core** | Facts are shared. No destination adds a fact or figure outside the ledger (`K-EVD-01`) |
| Chosen angle | **Core** | Otherwise different destinations talk about different things, and the client has no single idea per signal |
| Thesis (one sentence) | **Core** | Anchor for checking fidelity across all destinations |
| Main tension | **Core** | Follows from the material, not from the destination |
| Concession (yes / no, which one) | **Core** | Follows from the evidence. A destination may shorten the concession, but may not remove a real limitation if without it the claim becomes stronger than the ceiling |
| Claim-strength ceiling | **Core** | Evidence policy |
| Portable noun | **Core** | Otherwise different destinations will use different names for the same phenomenon |
| Focal subject (`focal_subject`) | **Core by default.** Open question whether a destination may narrow it | For example, in Telegram the focus is the company itself, in LinkedIn the takeaway for the reader. Decision `OPEN-04` |
| Form | **Destination plan** | The same material can carry a different form on the website and in a post |
| Opening (`opening_commitment`) | **Destination plan** | The first line works differently: 40 characters in LinkedIn, the preview in Telegram, the first slide in Instagram |
| Order of moves and evidence | **Destination plan** | Depends on form and length |
| Reveal | **Destination plan** | A short form almost always reveals immediately |
| Ending | **Destination plan** | Platform mechanics differ |
| Format, length, subheadings, hashtags | **Destination plan** | Destination knowledge |
| Link to another destination (post leads to article) | **Destination plan** | This is a destination choice, not an architectural dependency |

---

## 3. Knowledge entries

### 3.1. Process: how to make decisions

**K-PRC-01 · Structure is decided before prose**
- Statement: decisions about angle, form, order, reveal and ending are made before text generation and are recorded. The Writer executes them.
- Source: STORM, DOME, DPWriter, editorial practice (McPhee, Hart, Blundell); GPT research.
- Evidence class: `RES` + practice.
- Confidence: high for coherence and organization of the text; low for "interestingness".
- Applies when: always.
- Conflicts: today some decisions are made by the text assembler (`REPO`).
- Status: architecture invariant (decision #283).
- Influences: the whole plan.

**K-PRC-02 · Revision by the same model does not fix structure**
- Statement: the "critique → revise" loop improves phrasing. It does not fix a weak angle or a wrong form, and it erases voice and position.
- Source: Xu et al. (ACL 2024): the model overrates its own revisions. A 2026 preprint: during revision, three models shift all 13 style markers in the same direction; asking to "preserve the voice" removes only 32%.
- Evidence class: `RES`. There is no direct "weak structure → revision" experiment.
- Confidence: medium.
- Applies when: always.
- Conflicts: today, after one free revision, structure is not re-checked (`REPO`).
- Status: descriptive, basis of the routing rule `K-CHK-05`.
- Influences: check routing.

**K-PRC-03 · Choose among several variants using an external signal**
- Statement: it is better to generate several angle or plan variants and choose with an external signal (a human, a trained evaluator, audience reaction) than to rewrite a single variant.
- Source: WQRM (experts preferred selection in 66–72% of cases), Verbalized Sampling; in advertising, Meta saw +6.7% clicks when training on real reaction.
- Evidence class: `RES`; for advertising `RES` + field.
- Confidence: medium. There is no experiment for business texts.
- Applies when: where the decision is expensive (angle, form).
- Conflicts: cost and number of calls (`OPEN-06`).
- Status: candidate.
- Influences: angle, form.

**K-PRC-04 · Model self-assessment cannot be a quality filter**
- Statement: an AI judge asking "is this well written / is this slop?" barely agrees with experts: agreement is near zero. The model checks explicit rules well: Amazon reports 89.6% agreement with humans.
- Evidence class: `RES`.
- Confidence: medium-high.
- Status: descriptive.
- Influences: check classes.

**K-PRC-05 · Diversity is built into the plan**
- Statement: diversity is achieved through different forms and paths through the material, not through temperature and word substitution. Diversity and quality conflict, and there is no common metric for them.
- Source: DPWriter (ACL 2026, GPT research), Artificial Hivemind, Doshi & Hauser.
- Evidence class: `RES`.
- Confidence: medium-high. Tested on fiction.
- Status: descriptive → basis for `K-DIV`.

**K-PRC-06 · A Planner deviation is recorded**
- Statement: if the Planner chooses a candidate other than the strongest one from the map, it records the reason.
- Source: decision made during work on #283.
- Evidence class: `OWNER`.
- Status: candidate for a traceability invariant.
- Influences: plan record.

**K-PRC-07 · If the plan doesn't hold, the Writer does not improvise**
- Statement: some decisions honestly become clear only during writing. If the Writer sees that the plan doesn't hold, it returns the work to planning rather than restructuring the text itself.
- Source: DOME (flexible plan), editors' practice; GPT research.
- Evidence class: `RES` + practice + `INF`.
- Status: candidate.

### 3.2. Evidence and material

**K-EVD-01 · Facts only from the ledger**
- Statement: no text on any destination contains a fact, figure, name or causal link outside the evidence ledger, and none claims more strongly than the ceiling.
- Source: the engine's existing factual pipeline.
- Evidence class: `REPO` + `CLIENT` (`evidence.md`).
- Confidence: high.
- Status: **invariant**.
- Influences: all texts, checks.

**K-EVD-02 · Rejected evidence is not used**
- Evidence class: `REPO`. Status: **invariant** (already works).

**K-AST-01 · Strong texts have an irreplaceable asset**
- Statement: all 13 strong texts reviewed have an asset that others lack: access, own figures, a document, a calculation, their own frame, being first.
- Evidence class: `OBS` (n=13, no second annotator) + `VEND` (Orbit Media: original research gives roughly +50% to the chance of a strong result) + `PLAT` (Google demotes unoriginal mass-produced content).
- Confidence: medium.
- Status: descriptive.
- Influences: signal priority, angle.

**K-AST-02 · "No asset, no article"**
- Statement: a signal without an asset is not written.
- Source: inference from `K-AST-01`.
- Evidence class: `INF`.
- Confidence: low as a rule.
- Conflicts: may filter out useful explanatory texts.
- Status: **candidate**. For now this is a flag. Then a human or a priority rule decides: next signal, gathering more material, or lowered priority. To be tested on manual runs and later in `NBX`.
- Influences: admission to planning.

**K-AST-03 · Asset for Never Blank**
- Statement: the real Never Blank stories today are Sveta's own case and Lera's case. The client's position on automation is also an asset.
- Evidence class: `OWNER`.
- Status: client rule candidate. Not yet added to the client documents.
- Influences: `authority`, `first_person`.

### 3.3. Material → form

This is **knowledge for the Planner**, not a routing table. "Strong candidate" does not mean "mandatory".

Common basis for all entries in this section:

- Evidence class: `OBS` (13 texts: six long-form skeletons and five short ones) + `CLIENT` (form library in `structure.md`, doc 12) + practice (Hart: form follows from material; a narrative arc must not be forced onto explanatory material).
- Confidence: medium. There is no comparison with random form selection.
- Status: descriptive.

| ID | Material | Strong candidates | Conditions and caveats | Bad choice if… |
|---|---|---|---|---|
| **K-MAT-01** | `own_figure` | **Finding**: how we measured → what came out → how it works → what it costs. Short form: "number reveal" | The figure is verified, the method can be described | The figure is someone else's: then it is not an own figure but a `company_case` or `market_claim` |
| **K-MAT-02** | `company_case` | **Teardown**: case → what's wrong → how it should have been → what transfers. Short form: "before/after" | The case is documented. Transfer to the reader is almost always needed (doc 12: "otherwise it's someone else's laundry") | There is nothing to say about the company beyond retelling the source |
| **K-MAT-03** | `failure` | **Post-mortem**: what broke → why → the cost → what was changed. Short form: "story-first" | There is a cost or consequence | The failure is someone else's and lacks detail: then it is a `company_case` |
| **K-MAT-04** | `market_claim` | **Argument**: claim → where it doesn't add up → how it really is → turn. Short form: "definition correction" | There is real counter-evidence. Without it this is bait | Nothing to argue with |
| **K-MAT-05** | `mechanism` | **Explainer**: how it works → where it breaks → what to do | The mechanism is supported by evidence | The explanation rests only on the model's guess |
| **K-MAT-06** | `fresh_news` | **Reader questions (FAQ)** as the skeleton (like the DeepSeek FAQ) | There really are many questions around the news | The news is simple: then the form is "Finding" or "Teardown" |
| **K-MAT-07** | `human_story` | **Scene**: scene → thesis → evidence → return to the scene | The scene is real, with a source. **An invented scene is forbidden** (`K-OPN-03`) | There is no scene, only a "typical owner" |
| **K-MAT-08** | `parallel_points` | **Frame + points** | The points are genuinely equal | Often — easily degenerates into a template and "5 lessons". Use sparingly (`K-DIV-03`) |
| **K-MAT-09** | `open_question` | **Inquiry**, a question ending is appropriate | There genuinely is no answer | There is an answer, the model just didn't work it out |

**K-MAT-10 · Form follows from the material, not from the client's niche**
- Evidence class: `OBS` + practice.
- Confidence: medium.
- Status: descriptive.
- Conflicts: today Monday has one rigid arc, spelled out in four places in the engine (`REPO`).

**K-MAT-11 · Material with two types**
- Statement: when material fits two types, choose the one with a visible cost paid by us: our measurement, our mistake, our hours.
- Source: `structure.md`.
- Evidence class: `CLIENT`.
- Status: Never Blank client rule.

**K-MAT-12 · If a form doesn't fit, it isn't forced**
- Statement: if no form fits, write what the material is, and note this in the plan. A forced form is worse than none.
- Source: `structure.md`.
- Evidence class: `CLIENT`.
- Status: client rule.

### 3.4. Opening

**K-OPN-01 · Tension in the first two sentences**
- Statement: all 13 strong texts have tension in sentences 1–2: a contradiction, an unexplained event, an admitted mistake, a threatening figure, or a person in danger. None opens by announcing the topic.
- Evidence class: `OBS`.
- Confidence: medium.
- Status: descriptive.
- Influences: opening.

**K-OPN-02 · Specifics in the first sentence — usually, but not always**
- Statement: in 9 of 13 texts the first sentence contains a name, number, place or date. The exceptions rely on the author's authority.
- Evidence class: `OBS`.
- Confidence: medium.
- Conflicts: a rigid "number in the first sentence" will become a template (`K-CHK-S02`).
- Status: descriptive.

**K-OPN-03 · An invented reader scene is the source of the AI-style opening**
- Statement: openings like "imagine you're an owner…" and "Suppose you…" appear when the reader's stake is depicted as a scene rather than recorded as a fact.
- Source: today this is done by the fields `aha_setup` ("Prefer second person") and `founder_scenario` (`REPO`). This opening is visible in the real Bagels output (`OBS`).
- Evidence class: `REPO` + `OBS`.
- Confidence: high for the current engine.
- Status: invariant candidate: "a scene is allowed only if real, with a source".
- Influences: opening, `reader_stake`.

**K-OPN-04 · Three openings for Never Blank**
- Statement: the hook is one verifiable thing: a number, a named company, or a contradiction.
- Source: doc 12; `structure.md`; #281 `opening_commitment`.
- Evidence class: `CLIENT`.
- Status: Never Blank client rule.
- Conflicts: Hook Engine forbids a hook with a company name, and none of its six types is a "number" or a "company" (`REPO`).

**K-OPN-05 · Keep one variable in reserve**
- Statement: specificity in the opening works up to a certain limit. One thing — how exactly it works — is worth holding back.
- Source: doc 12, the Upworthy study (adding details to a vague headline gave about +5.5% clicks, to an already specific one about −9.9%).
- Evidence class: `CLIENT` + `RES`.
- Confidence: medium.
- Status: descriptive.

**K-OPN-06 · A question opening is a weak option for LinkedIn**
- Statement: the question opening has the lowest median engagement (2.16%), the story opening the highest (2.60%).
- Evidence class: `VEND` (AuthoredUp, 309 thousand posts, correlation).
- Confidence: low-medium. The effect is small.
- Status: descriptive.
- Influences: LinkedIn opening.

**K-OPN-07 · A question works if there is a real puzzle behind it**
- Statement: a rhetorical question is not a defect in itself. The defect is when the question is invented instead of a real puzzle.
- Evidence class: `OBS` (the Vogue example from the GPT research) + `INF`.
- Status: descriptive.

### 3.5. Reveal

**K-REV-01 · Immediate by default**
- Statement: the finding is given early. It can be delayed if the material justifies it: a genuine investigation, a result that only makes sense after setup.
- Source: `structure.md`.
- Evidence class: `CLIENT`.
- Status: client rule.
- Conflicts: Hook Engine requires "the reader earns the thesis at the end" (`REPO`).

**K-REV-02 · Delayed thesis in journalism — paragraph 5 / ~600 words**
- Statement: even with a delayed reveal, the thesis appears no later than the 5th paragraph.
- Evidence class: `OBS` (Atlantic, ProPublica, Founder Mode).
- Status: descriptive.

**K-REV-03 · Delayed reveal — a length constraint**
- Statement: the puzzle must be resolved in roughly four sentences.
- Source: restored in #277.
- Evidence class: `CLIENT` / `OWNER`.
- Status: candidate. Not added to the client documents (question #281).

**K-REV-04 · Short form reveals immediately**
- Statement: a post has no room to delay the idea. The concrete detail goes in lines 1–2.
- Evidence class: `OBS` (reviewed LinkedIn posts) + `PLAT` (Telegram shows an AI summary of long posts since January 2026).
- Status: descriptive.

### 3.6. Tension and concession

**K-TEN-01 · Tension only from the material**
- Statement: the contradiction, puzzle or cost is taken from the evidence. An invented "paradox" is an AI device.
- Evidence class: practice + `INF`.
- Status: candidate.
- Influences: `tension`, opening.

**K-TEN-02 · Contradiction between the source and our data**
- Statement: if research refutes the source's claim, the Evidence Tension lens is activated.
- Source: `evidence_tension_lens.md`.
- Evidence class: `CLIENT` + `REPO` (decided before writing and recorded).
- Status: client rule.
- Conflicts: the lens contradicts itself about the final question (`OPEN-02`).

**K-CON-01 · Almost all strong texts have a concession**
- Statement: a genuine concession is visible in 12 of 13 texts. Placement is free: at the start, as a separate section, in footnotes, as failures at the start of a case.
- Evidence class: `OBS`.
- Status: descriptive.

**K-CON-02 · Only a genuine concession**
- Statement: the concession is evaluated every time, but written only if there is a real objection or limitation that can be cited. It must not be invented.
- Source: `concession.md`.
- Evidence class: `CLIENT`.
- Status: client rule.
- Influences: `concession` in the core.

**K-CON-03 · In a post, the role of concession is played by an admitted mistake**
- Evidence class: `OBS` + `INF`.
- Status: descriptive.

### 3.7. Ending

**K-END-01 · The ending does not recap**
- Statement: none of the 13 strong texts ends with a recap. Endings are a call to action, a human detail, an aphorism, a question, a joke.
- Evidence class: `OBS`.
- Status: descriptive. The check "ending repeats the introduction" is a candidate for a hard check (`K-CHK-H02`).

**K-END-02 · For Never Blank: the ending is the Echo, nothing after it**
- Statement: the last editorial line is the Echo / Kicker. After it only sources: no CTA, no question to the reader, no signature.
- Source: `monday.md`, `structure.md`.
- Evidence class: `CLIENT` + `REPO` (the ending's position is checked by code).
- Status: client rule.
- Conflicts: LinkedIn `length_rules` require an "invitation to the website" (`REPO`); Story Assembly turns uncertainty into an open question (`REPO`); see `OPEN-02`.

**K-END-03 · The return to the opening is decided after the opening**
- Statement: the Kicker returns to an image or fact from the opening with a new meaning. Therefore it is decided after the opening is chosen.
- Source: `structure.md`.
- Evidence class: `CLIENT`.
- Conflicts: today the Echo is written before the text (`REPO`).
- Status: client rule.

**K-END-04 · A question at the end of a post gives almost nothing**
- Statement: about +3% relative, almost zero.
- Evidence class: `VEND` (AuthoredUp).
- Status: descriptive.
- Influences: LinkedIn ending.

### 3.8. Focal subject

**K-FOC-01 · The focal subject is a variable**
- Statement: the focus is the company from the signal, the owner-reader, the client itself, or a person from the story. This depends on material type, evidence and form. For `company_case` and "Teardown" the company is in focus, and the reader's recognition comes in the ending through transfer.
- Source: #281 (Teardown), doc 12, decision on #283.
- Evidence class: `CLIENT` + `OWNER` + `INF`.
- Conflicts: the engine rigidly requires "the protagonist is always the owner": Pattern Extractor, Discovery Builder, Narrative Spine, "company ≤20%" in the assembler (`REPO`).
- Status: candidate (`OPEN-04`).
- Influences: `focal_subject`, form.

### 3.9. Reader

**K-RDR-01 · The American business reader**
- Statement: values original data, a clear problem statement, concrete advice and cases, a fresh perspective that breaks assumptions, a human tone. Considers only 15% of expert content "very good".
- Evidence class: `VEND` (Edelman–LinkedIn 2024, 2025). The geography of the 2025 edition is not confirmed.
- Confidence: medium.
- Status: descriptive.
- Influences: angle, opening, voice.

**K-RDR-02 · US small business: money and time**
- Statement: what hits hardest is cash-flow gaps, overdue invoices (39%), taxes (77% are anxious). 42% spend less than an hour a day on marketing.
- Evidence class: `VEND` (QuickBooks, Constant Contact).
- Status: descriptive.
- Influences: `reader_stake`.

**K-RDR-03 · The B2B buyer verifies**
- Statement: 94% of those who use AI to research a purchase verify its answers. Buyers trust reviews, peers and trial versions.
- Evidence class: `VEND` (TrustRadius 2026).
- Status: descriptive.

**K-RDR-04 · Visible sources remove the "AI" penalty**
- Statement: a "made with AI" label lowers trust, and a list of the sources used largely removes this penalty.
- Evidence class: `RES` (Toff & Simon 2025).
- Confidence: medium.
- Status: descriptive.
- Influences: visible sources on all destinations.

**K-RDR-05 · Reader with English as a second language: simplify the form, not the idea**
- Statement: clarity is hindered by idioms, sports metaphors and long multi-clause sentences. Numbers, names, cities and currencies are understood by everyone and make the text interesting.
- Evidence class: practice (Google and Microsoft style guides, Kohl) + `RES` (plain language studies: faster reading, higher persuasiveness ratings).
- Confidence: medium.
- Status: candidate for clients with an international audience.

**K-RDR-06 · Models Americanize text**
- Statement: AI suggestions pull writers from other cultures toward American defaults and erase cultural details.
- Evidence class: `RES` (CHI 2025).
- Status: descriptive. A risk for immigrant clients.

**K-RDR-07 · Detectors misfire on writers with English as a second language**
- Statement: AI detectors systematically classify non-native speakers' texts as AI. Simplified global English lowers perplexity and thus resembles AI.
- Evidence class: `RES` (Liang et al. — from memory, not re-verified) + `INF`.
- Confidence: low-medium.
- Status: descriptive. The defense is specifics in the content, not "unpredictable" words.

### 3.10. Destinations

General caveat: data on format and length are vendor correlations with small effects (`VEND`). Destination policies are `PLAT`.

**K-DST-WIX-01 · Website**
- Statement: full form, subheadings that state the takeaway immediately, the main point up front (readers scan the text), visible sources, answers to adjacent questions as separate sections.
- Evidence class: practice (Nielsen Norman) + `VEND` (Ahrefs 2026: only 38% of citations in Google AI Overviews come from the top 10; Google breaks a question into sub-questions) + `PLAT` (Google: "unique, non-commodity content").
- Status: descriptive.

**K-DST-LI-01 · LinkedIn: form and length**
- Statement: a post of about 250–400 words; a document carousel gives more reach (1.39×); first line up to 40 characters; a story opening beats a question; one idea.
- Evidence class: `VEND` (AuthoredUp) + `PLAT` (the feed explicitly optimizes for long reading).
- Status: descriptive.

**K-DST-LI-02 · LinkedIn: the "AI slop" filter**
- Statement: since July 2026, user reports and classifiers cut out-of-network impressions; flagged posts get about −40% views. The author receives a private notice. The signals are not disclosed.
- Evidence class: `PLAT`.
- Status: descriptive.
- Influences: avoid overused formulas; specifics in lines 1–2.

**K-DST-META-01 · Meta penalizes similarity, not AI text**
- Statement: there is no label for AI text. Duplicates, "light edits" and unoriginal streams are demoted. Since April 2026, Instagram evaluates an account's monthly output, including photos and carousels.
- Evidence class: `PLAT`.
- Confidence: high for the policy; no data on hidden signals.
- Status: descriptive → basis of `K-DIV-02`.

**K-DST-META-02 · AI images get "AI info"**
- Statement: images from ChatGPT, DALL-E, Firefly, Imagen and Meta AI carry C2PA/IPTC metadata, and the label is applied automatically.
- Evidence class: `PLAT`.
- Status: descriptive. Obligation: a human decides on disclosure (`OPEN-09`).

**K-DST-FB-01 · Facebook**
- Statement: a self-contained text status remains among the best formats. Posts with a link perform worst. Hashtag captions, captions unrelated to the image, and "comment below" bait are demoted.
- Evidence class: `VEND` (Socialinsider, Buffer) + `PLAT`.
- Status: descriptive.

**K-DST-IG-01 · Instagram**
- Statement: carousels deliver engagement and saves, Reels deliver reach. One idea per slide. A short first line, keywords right after it (captions are read by search). 0–3 hashtags.
- Evidence class: `VEND` (Socialinsider, Buffer, Metricool) + `PLAT` (Mosseri on ranking signals).
- Status: descriptive.

**K-DST-TH-01 · Threads**
- Statement: bare text is half as strong as video (2.79% vs 5.55%). Text plus an image. The feed is shifted toward follows.
- Evidence class: `VEND` (Buffer) + `PLAT`.
- Status: descriptive.

**K-DST-TH-02 · Threads: the author's live replies**
- Statement: the author's replies to comments give +42% engagement, the largest effect among destinations.
- Evidence class: `VEND`.
- Status: descriptive. **A human's obligation**, not the machine's.

**K-DST-TG-01 · Telegram**
- Statement: there is no feed; the reader is the one who penalizes: mutes and unsubscribes. Growth comes through forwards. Since January 2026, long posts get an AI summary, so the thesis is needed in the first line and in the first paragraph. Less often and denser.
- Evidence class: `PLAT` + `INF`.
- Status: descriptive.

**K-DST-ALL-01 · What the author sees**
- Statement: none of the Meta destinations or Telegram says whether it considers a post to be AI text. LinkedIn gives a private notice after reports. Instagram and Threads show Account Status, Facebook shows Support Home. Demotion is visible as a drop in non-follower reach against the account median.
- Evidence class: `PLAT`.
- Status: descriptive → measurements `K-DIV-05`.

### 3.11. Voice, bans and exemplars

**K-VOI-01 · A long "don't" list barely works**
- Statement: with hundreds of simultaneous rules, models silently skip some: with 500 rules the best one complied with 68.9%. A topic ban does not work without fine-tuning.
- Evidence class: `RES`.
- Confidence: medium-high.
- Status: descriptive → voice is set by a short positive brief; the long style guide goes into checks.

**K-VOI-02 · Sveta's method ("golden ratio")**
- Statement: no negations and no "not this, but that", no em dashes where they are not asked for, clipped sentences, lists where appropriate, the text always has a purpose.
- Evidence class: `OWNER`.
- Conflicts: of this, the client documents contain only the ban on "X is not about A, it's about B". In the engine's general list, em dashes and triads are delegated to the client, but the client does not have them.
- Status: **client rule candidate** for Never Blank. Not added. #283 states that Sveta's method is one source among others.

**K-VOI-03 · Typical AI phrasings are born from structure**
- Statement: the openings "Suppose you…", "It's easy to assume… But", "This isn't just theory", "Consider where your own…" repeat across all 12 samples and are tied to specific engine fields.
- Evidence class: `REPO` + `OBS`.
- Confidence: high for the current engine.
- Status: descriptive → phrase bans help as hygiene, but not as architecture.

**K-EXM-01 · Exemplars beat abstract rules for register and form**
- Statement: exemplars steer register and form better than abstract rules. The benefit plateaus at 2–5 (up to 10) examples. Selection by topic worsens style; selection must be by text type.
- Evidence class: `RES` (EMNLP 2025, LongLaMP).
- Confidence: medium. There is no "style guide vs exemplars" comparison on business texts.
- Status: descriptive.

**K-EXM-02 · A specific author's voice requires fine-tuning**
- Statement: only fine-tuning on a corpus of the author's texts produced an accurate voice. In the study these were whole books. A typical client has 10–50 posts.
- Evidence class: `RES` (Chakrabarty et al. 2025).
- Status: descriptive.

**K-EXM-03 · An exemplar is a model, not a template**
- Statement: 1–4 exemplars per form and destination. Each is annotated with what to take (opening, concession placement, rhythm) and what not to copy. Plus a copying check.
- Source: the engine's golden-fixture practice (`reasoning_reference_only_do_not_imitate_wording`) + `INF`.
- Evidence class: `REPO` + `INF`.
- Status: candidate.

**K-EXM-04 · An example in the engine contradicts the client**
- Statement: in `research/angles.yaml` the model is shown the example hook "AI isn't replacing jobs. It's replacing layers." This is a construction the client bans.
- Evidence class: `REPO`.
- Status: descriptive (current engine debt, for #281).

### 3.12. Diversity and portfolio memory

**K-DIV-01 · Portfolio similarity is real**
- Statement: AI assistance makes each text better, and the set of texts more alike. Switching models does not help: 22 models produce far less diversity than humans.
- Evidence class: `RES` (Doshi & Hauser 2024, Wenger & Kenett).
- Status: descriptive.

**K-DIV-02 · Cross-client similarity is a top-tier product risk**
- Evidence class: `PLAT` (Meta) + `OWNER` (#283).
- Status: architecture invariant: portfolio memory is mandatory.

**K-DIV-03 · Soft pressure, not quotas**
- Statement: portfolio memory softly penalizes repetition of form, opening, reveal and ending for the same client on the same destination, and similarity with other clients. Hard quotas like "don't repeat the opening type five articles in a row" create a new artificiality.
- Evidence class: `RES` (the quality–diversity conflict in DPWriter) + `INF`.
- Status: candidate.
- Influences: form, opening.

**K-DIV-04 · Text fingerprint**
- Statement: for each published text we store the destination, client, `material_type`, form, opening type, reveal, ending type, headline form, position of the first evidence, paragraph length profile, and the text itself.
- Evidence class: `INF`.
- Status: candidate.
- Today: only the run plan is saved; `portfolio_regularity` is not wired in (`REPO`).

**K-DIV-05 · The "is the diversity real?" check**
- Statement: change the form for the same material. If the text lost nothing, the form was chosen at random.
- Evidence class: `INF`.
- Status: descriptive (audit method).

### 3.13. Check classes

Classes: **H** — hard (blocks), **S** — soft diagnostic signal, **J** — human judgment. The list below is also a research conclusion. Approving the checks is a separate decision (`OPEN-05`).

| ID | Check | Class | Status | Basis |
|---|---|---|---|---|
| K-CHK-H01 | Facts, figures, names only from the ledger; claim strength within the ceiling | H | **Invariant** | `K-EVD-01`; works today for the article |
| K-CHK-H02 | Ending repeats the introduction | H | Candidate | `RES` (a safe hard check) |
| K-CHK-H03 | Fabricated links and sources | H | Candidate (essentially exists already) | `RES` + `REPO` |
| K-CHK-H04 | Near-duplicate of a past text (same client or another) | H | Candidate | `RES` + `PLAT` |
| K-CHK-H05 | Client's banned phrases | H | Client rule | `CLIENT` + `REPO` |
| K-CHK-H06 | Fidelity to the core: same thesis, no new facts (for each destination) | H | Candidate | #283. Today LinkedIn is checked for fidelity to the article |
| K-CHK-S01 | Construction types: "Suppose you…", "not X but Y", question in the ending, invented scene | S | Candidate | `REPO` + `OBS` |
| K-CHK-S02 | Words before the first specific, position of the first evidence, abstraction before evidence | S | Candidate | Not validated (`RES`: no studies) |
| K-CHK-S03 | Repetition of ideas within the text | S | Candidate | `INF` |
| K-CHK-S04 | Uniformity of paragraph and sentence length | S | Candidate | From detectors, not validated as quality |
| K-CHK-S05 | Similarity to the portfolio: form, opening, ending, n-grams | S | Candidate | `RES` (compression, self-BLEU validated on text sets) |
| K-CHK-S06 | Destination rules: link in the body (Facebook), hashtags, bait | S | Candidate | `PLAT` |
| K-CHK-S07 | Global English rules: idioms, American terms without explanation | S | Candidate | practice |
| K-CHK-J01 | The text executed the plan (opening, form, concession in place) | J → model + code | Candidate | #283. Today the reviewer is forbidden to judge structure |
| K-CHK-J02 | Is it interesting; is the surprise earned; is the angle new | J | Descriptive | `K-PRC-04` |
| K-CHK-J03 | Ethics, law, disclosure of AI images | J | Descriptive | — |
| K-CHK-05 | **Routing:** structural failure — back to the destination plan; fact and phrasing failure — text revision | Routing | Invariant candidate | `K-PRC-02` |

**Rule for the entire S layer.** Soft signals do not become thresholds without the owner's decision. Otherwise the model will learn to game the instrument (Goodhart).

---

## 4. How the Planner walks the map

The order in which decisions depend on each other. Each decision in the plan references the numbers of the knowledge entries that determined it.

**Core (once per signal)**

1. Check `asset` → `K-AST-02` (candidate: a flag; the decision belongs to a human or a priority rule).
2. Choose an angle from `angle_candidates` → `K-PRC-03`, `K-RDR-*`, lens.
3. Formulate the thesis.
4. Decide the focal subject → `K-FOC-01`.
5. Main tension → `K-TEN-01`, `K-TEN-02`.
6. Concession: yes or no → `K-CON-02`.
7. Portable noun: coin one, use our own, or do without one.

**Plan for each destination**

8. Form → `K-MAT-*` + the client's allowed forms + lens + `K-DIV-03`.
9. Opening → `K-OPN-*` + `K-DST-*`.
10. Order of moves and evidence.
11. Reveal → `K-REV-*`.
12. Ending → `K-END-*` + `K-DST-*`.
13. Format, length, first line → `K-DST-*`.
14. Exemplars → `K-EXM-03`.
15. Deviations and reasons → `K-PRC-06`.

### 4.1. What a plan record contains

A plan is a record of decisions, not instruction text. For each decision:

- the value;
- the numbers of the knowledge entries that determined it;
- the candidates that were considered;
- the reason for deviation, if a candidate other than the strongest was chosen;
- confidence.

The Writer receives only what is needed for execution: the decisions for its destination, the core, the needed evidence from the ledger, 1–4 exemplars and a short voice brief.

### 4.2. Model call structure — open

**Six logical plans are not the same as six model calls.** Options to be compared (`OPEN-06`):

- one call for the core and all plans;
- code assembles the destination rules, the model decides only the contested points;
- a shared plan plus small adjustments for each destination;
- separate calls only where model judgment is needed.

The phrase "zero additional calls" from #281 refers to the narrow Teardown case and does not carry over to the new architecture.

---

## 5. As is and as it should be

Briefly. Details are in the repository review, especially section 5.3.

| Component | As is (`87ea0f4`) | As it should be |
|---|---|---|
| Beads | Pattern Extractor looks for an "owner scene" and filters out cases | The Analyzer describes the material without decisions |
| Angle and thesis | Three independent versions; the main claim is copied from the signal | One angle and thesis in the core |
| Focal subject | Hard-coded to the owner in five places in the engine | The `focal_subject` variable |
| Form | One block order for everything, spelled out in four places | Form from knowledge and the allowed list, for each destination |
| Opening | Hook Engine's own six types, ban on a hook with a company | `opening_commitment` based on knowledge and the client rule |
| Reveal | The engine requires "at the end" | A plan decision; the client's default is immediate |
| Ending | The Echo is written before the text; its position is checked | The return to the opening is decided after the opening |
| Destinations | LinkedIn is a derivative of the article; the rest are outside the planned flow | Siblings from one core |
| Fidelity check | LinkedIn is checked against the article | Each destination is checked against the core and the ledger |
| Revision | One free revision; the reviser lacks `structure.md`; structure and headline are not checked after revision | A structural failure sends it back to the plan |
| Reviewer | Forbidden to judge order and form | The "text executed the plan" check |
| Exemplars | Don't reach the model; the example in `angles.yaml` contradicts the client | A library by form and destination |
| Portfolio memory | The function exists but is not wired in; texts are not indexed | Fingerprints, soft pressure, cross-client similarity |
| Reader | The audience is chosen by code, there is no profile | Reader profile as context |

---

## 6. Manual signal walkthroughs

Exit condition 7 from #283: run different signals through the map and get different justified plans without inventing rules on the fly. Below are three walkthroughs on real signals from the queue, reviewed in the sample pack.

This is an illustration at the plan level, with no text. The client is Never Blank:

- the audience is small business owners in the US;
- we don't sell in the texts;
- Never Blank is a publisher, not a predetermined conclusion.

### Walkthrough A · "This Dad Lost His Job and Started Making a Breakfast Staple at Home… $85,000" (Entrepreneur)

**Beads**

| Bead | Value |
|---|---|
| `material_type` | `human_story` + `company_case` (a named person, documented growth) |
| `asset` | Weak: the story is known from a single source. There is the $85,000 figure and a concrete mechanism — the capacity of one kitchen. Never Blank has no asset of its own → **flag `K-AST-02`**. Human decision: write it, but the angle must add something that isn't in the source |
| `tension` | There is demand, but growth is capped by the founder's own hands |
| `figures` | $85,000 |
| `reader_stake` | An owner whose revenue is limited by their own time |
| `timeliness` | Weak |
| `angle_candidates` | 1) the business's ceiling is the owner's capacity, not demand; 2) early success locks in a model that is later hard to scale; 3) what changes when revenue hits the limit of hours |

**Core**

- Angle 1.
- Thesis: "A home business hits the owner's hours before it hits demand."
- Focal subject: the founder from the story (`K-FOC-01`: for `human_story` the focus is the person, with transfer to the reader in the ending).
- Concession: "one case, one source; for other products the constraint may lie elsewhere" (`K-CON-02`).

**Plans**

| Decision | Wix | LinkedIn | Telegram |
|---|---|---|---|
| Form | "Teardown" (`K-MAT-02`), not "Scene": we have no first-hand scene, only a retelling of the source (`K-MAT-07`, the "real scene" condition) | "Before/after": one idea | Short "Teardown": thesis + figure + transfer |
| Opening | Number and named person (`K-OPN-04`): $85,000 from a home kitchen | Short first line ≤40 characters with the figure (`K-DST-LI-01`) | Thesis in the first line (`K-DST-TG-01`) |
| Reveal | Immediate (`K-REV-01`) | Immediate (`K-REV-04`) | Immediate |
| Ending | Echo: return to the "kitchen" with a new meaning (`K-END-02`, `K-END-03`) | Echo, no question (`K-END-04`) | One line of transfer |
| What to avoid | An invented scene "imagine you're baking…" (`K-OPN-03`) — exactly what the real output did in August | "Hard truth:" formulas | — |

**Deviation that gets recorded.** For `human_story` the strong candidate is "Scene". "Teardown" was chosen because the "real first-hand scene" condition is not met (`K-PRC-06`).

### Walkthrough B · "Ramp Launches Instant Stablecoin Payments with Stripe's New Technology" (Small Business Trends)

**Beads**

| Bead | Value |
|---|---|
| `material_type` | `fresh_news` + `company_case` |
| `asset` | Being first on the news (weak) plus a possible calculation: what changes in payment timing for small business. If the calculation is supported by evidence, there is an asset; otherwise a flag |
| `tension` | Payments are speeding up, but the rules for them haven't been written yet |
| `reader_stake` | Cash-flow gaps and payment timing (`K-RDR-02`) |
| `timeliness` | High |
| `angle_candidates` | 1) what really changes for small business and what doesn't yet; 2) faster payments shift compliance work onto the owner; 3) questions worth asking your payment provider |

**Core**

- Angle 1.
- Thesis: "Instant payments solve the timing problem, but not the rules problem."
- Focal subject: the owner-reader (product news; the focus is the consequences).
- Concession: "the regulatory picture is unknown; the source is a press release."

**Plans**

| Decision | Wix | LinkedIn | Instagram |
|---|---|---|---|
| Form | "Reader questions (FAQ)" (`K-MAT-06`): 4–5 owner questions as the skeleton | "Definition correction" (`K-MAT-04`, short form): "Faster payments are not a cash-flow fix." — **but this is the "X is not Y" construction**, see the conflict below | Carousel: one question per slide, the last slide for forwarding (`K-DST-IG-01`) |
| Opening | Dated question (`K-MAT-06`) | Short line with a contradiction | First slide — the main question |
| Reveal | Gradual | Immediate | Immediate |
| Ending | "What to watch next"; Echo | Echo | Slide for forwarding |
| Visible sources | Yes (`K-RDR-04`) | Link per the destination plan | — |

**Conflict found by the walkthrough.** The strong candidate for LinkedIn ("definition correction") coincides in form with the client-banned construction "X is not about A" and with Sveta's "no negations" method (`K-VOI-02`). The map must say which is stronger: form knowledge or the client ban. Recorded as `OPEN-10`.

**Second admissible plan for LinkedIn.** "Before/after" with a concrete payment timeline — if the ledger contains a figure. Both plans are justified: portfolio memory decides the choice (`K-DIV-03`).

### Walkthrough C · "U.S. Uranium Production Hits Record High in 2025, Triples from 2024" (Small Business Trends)

**Beads**

| Bead | Value |
|---|---|
| `material_type` | `own_figure`? **No** — the figure is someone else's, industry-level. More likely `market_claim` or `mechanism` |
| `asset` | None. Industry statistics; the material contains no direct link to small business. The real output in September invented the link ("your inbox is suddenly crowded with inspection requests") → **flag `K-AST-02`** |
| `reader_stake` | Not supported by the material |
| `angle_candidates` | 1) the production growth creates demand among contractors and suppliers (evidence needed); 2) rapid growth attracts regulators (not in the source) |

**Decision per the map.** The core cannot be assembled without invention: angle 2 requires facts outside the ledger (`K-EVD-01` is an invariant), angle 1 requires gathering more material.

Options for the human:

- gather evidence about contractors (step 3);
- skip the signal.

**This is the correct outcome, not a failure.** The walkthrough shows that `K-AST-02` is useful as a flag. It would have stopped exactly the text the engine invented in September.

### What the walkthroughs showed

1. **Three signals produced three different cores and different forms on different destinations.** No rules were invented on the fly. One exception is `OPEN-10`, found by a walkthrough.
2. **One signal can have several justified plans for one destination.** Choosing between them is the job of portfolio memory. The map does not turn into a routing table.
3. **The asset flag fired twice, and differently:** in A — "write with a condition", in C — "gather more or skip".
4. **More walkthroughs are needed:** `own_figure` (Sveta's or Lera's case), `failure`, `market_claim` with real counter-evidence, `parallel_points`. And walkthroughs for another client, to test cross-client similarity.

---

## 7. Register of contradictions and open decisions

*Not closed until the cross-review. Some may disappear.*

| ID | Question | Essence | Type |
|---|---|---|---|
| OPEN-01 | The "no asset, no article" candidate | Flag or rule; what to do with a signal without an asset | Policy |
| OPEN-02 | Question in the ending | `evidence_tension_lens` recommends a final question, `monday.md` and `structure.md` forbid it. Possibly this is a variable: appropriate only in an "Inquiry" | Contradiction in client documents |
| OPEN-03 | Subheadings | `structure.md` requires them always, the role in `business_strategy.json` says "optional" | Contradiction in client documents |
| OPEN-04 | Focal subject | A variable instead of the "always the owner" rule; whether a destination may narrow the focus | Design + client |
| OPEN-05 | Approval of check classes | Which H candidates become hard; thresholds for S | Policy |
| OPEN-06 | Call structure and cost | See 4.2 | Design |
| OPEN-07 | Who chooses the angle | The model or a human, and when | Policy |
| OPEN-08 | Exemplars | Who selects, how many, for which forms and destinations | Operations |
| OPEN-09 | AI images | Disclose, or don't use photorealistic ones | Policy |
| OPEN-10 | Form vs. client ban | "Definition correction" and "X is not Y" vs. the ban and Sveta's method. Which is stronger: knowledge or the client rule. Probably the client rule, and then the form is implemented without a negative construction | Found by walkthrough |
| OPEN-11 | Sveta's method | Whether to add it to the client rules and to what extent | Client |
| OPEN-12 | CTA in LinkedIn | `length_rules` require an "invitation to the website", the ending mode forbids CTAs | Contradiction in documents |
| OPEN-13 | Delayed reveal | Whether to add the "four sentences" constraint and the rule on the placement of the conclusion from #277 | Client |
| OPEN-14 | Global English | How much to simplify the form for readers with English as a second language | Client |
| OPEN-15 | Destinations for a signal | Always all six, or the Planner chooses destinations to fit the material | Design |

---

## 8. What is not confirmed

- I did not re-verify the references from the GPT research (DOME, DPWriter, ScaffoldAgent, the Vogue example and others).
- The claim from #283 that "a control run of the historical 11-element version reproduced the same opening" does not come from my materials; I cannot confirm it.
- All walkthroughs in section 6 are manual: this is reasoning over the map, not an experiment.
- The "material → form" knowledge rests on 13 texts without a second annotator.
- Destination data are vendor correlations; the effects are small.
- Nobody has controlled experiments on business texts. `NBX` is still empty.
