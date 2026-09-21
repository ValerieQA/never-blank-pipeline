# Never Blank: editorial mechanisms, repository track (read-only)

*Research track opened 2026-09-21. Repository `ValerieQA/never-blank-pipeline`, `main` @ `87ea0f4` (#279/#280 merged). Nothing was modified, nothing was generated, no paid calls were made. Line numbers refer to that commit.*

*This is one of two tracks. It covers the repository only. The external-market synthesis comes separately. The report stops at a gap matrix. It contains no coding plan, no #281 design and no new architecture.*

---

## 0. Evidence base and limits

**Sources used**
- Code: `scripts/generate_and_publish.py` (GAP below), `src/editorial/*`, `src/strategy/client_contracts.py`, `src/never_blank/*`, `src/content/*`, `src/quality/*`.
- Client documents: `clients/never_blank/**`.
- Engine docs: `docs/engine/*`.
- Recovered reference documents: `clients/never_blank/editorial/reference/` (11, 12, readability research).
- Real outputs: the project's sample pack of 12 real bodies (2026-09-15).

**Limits**
1. **#277 and #281 were read after the first version of this report** (via the issue pages; the API is still closed to this session). Section 5 reconciles this track with them. Both are treated as evidence, not as the answer. Where #281 corrects this report, the correction has been applied in place and is marked *[corrected after #281]*.
2. **Output of the current Monday path is not readable from here.** #277 cites a controlled v2 dry-run (the Invisalign/TikTok article), and #281 refers to "all three articles". Those bodies are GitHub Actions artifacts and are not in the repository. The only committed Monday article (Bagels, 24.08) predates EditorialPlan v2 (#267–#280). Behaviour claims about the current path are therefore inferred from the code, cross-checked against #277's description of the dry-run: strongest evidence late, generic opening, lead-quality claims beyond the metrics.
3. **Paths in scope.** Monday is the only stream that has a plan, lenses and a factual gate. Wednesday runs frozen July modules with no client documents (GAP:2160, `src/never_blank/wednesday_routing.py`). The daily research generator (`config/prompts/research/content_package.yaml`) is an unreviewed path, used here only as evidence of recurring shapes.

---

## 1. How the Monday path is built

This is needed to read the rest of the report.

**Stages before drafting.** Signal → eligibility (model) → research + evidence verdicts (model) → plan decider (model; it decides only `evidence_tension` and `reader_verifiable_artifact`) → `EditorialPlan`. Then eight model stages produce **structured fields, not prose**:
- Pattern Extractor
- Decision Lens Lite
- Narrative Spine
- Hook Engine
- Reader Context
- Discovery Builder
- Story Assembly
- Never Blank Voice

**Drafting.** The Platform Composer (`platform_composer.py:724`) is the **only stage that writes article prose**. It receives the fields in a fixed block order:

```
hook → reader_context → observation (= first_wrong_explanation)
→ recognition (= aha_setup) → evidence_pattern (= puzzle + investigation_sequence)
→ explanation → reframe → business_meaning → cta → echo
```

`_BLOCK_TABLE` is at `platform_composer.py:21-26`; the field mapping is `_block_content` at `:538-554`. The composer also gets all standing client lenses verbatim, plus the role rules and the plan text.

**After drafting.**
1. Factual review (model plus a mechanical ban list).
2. Editorial review (model, 9 criteria).
3. At most one free-text revision.
4. Both reviews again.
5. LinkedIn recomposition from the accepted article, plus a fidelity judge.

**Routing (#279).** Lenses reach Spine, Hook, Voice, the Composer and the reviewers. **Pattern Extractor, Decision Lens Lite, Reader Context, Discovery Builder and Story Assembly receive no plan and no lens** (`pipeline.py:60-62, 175-193`). These are the stages that fix the evidence order, the tension, the "wrong explanation" and the reframe.

---

## 2. Mechanism by mechanism

Format for every entry:

- **Problem**: the editorial problem the mechanism solves
- **NB now**: the current Never Blank equivalent
- **Seam**: exact code or document location
- **Executes?**
- **Decided at / should be at**: the stage that makes the decision now, and where it logically belongs
- **Conflict**: conflicts or duplication
- **Smallest seam**: the smallest plausible implementation seam
- **Needs**: model call, deterministic code, client document, exemplar retrieval, or human decision

### Family 1. Structural decisions before drafting

#### 1.1 Angle / central claim

- **Problem:** the article argues one thing that is worth arguing, instead of retelling the source.
- **NB now:** there are four separate "angle" objects, and nothing reconciles them:
  1. The plan's `central_claim`, which is the raw signal `CORE_FACT` or `HEADLINE`. It is copied, not decided (GAP:2111-2114). `build_editorial_plan` accepts a claim with no evidence refs (`editorial_plan.py:718`).
  2. Pattern Extractor `mechanism`.
  3. Decision Lens Lite `never_blank_insight`.
  4. Narrative Spine `narrative_spine`: "the single sentence the entire article is built to earn" (`narrative_spine.py:23-70`).
- **Executes?** Yes, all four, independently. The plan claim is what the reviewers judge against. The spine is what the composer writes toward.
- **Decided at:** deterministic copy (plan), then three model calls before drafting. Pattern Extractor and Decision Lens Lite run without the plan or lenses.
- **Should be at:** one decision before drafting, after evidence verdicts. Every later stage should consume it.
- **Conflict:** the reviewers judge against `central_claim`, the composer writes toward the spine, and the two can differ. The angle is shaped by stages that never see the client's evidence policy or structure lens.
- **Smallest seam:** make `central_claim` a run-derived plan slot that one of the existing pre-draft calls fills. It is already declared a run slot in `PLAN_RUN_SLOTS` (`client_contracts.py:93-95`).
- **Needs:** a model call, the output of which goes into an existing plan slot. Choosing between candidate angles is arguably a **human-in-the-loop** point.

#### 1.2 Opening commitment (Dek, Hook, Stakes)

- **Problem:** the first screen commits to one checkable thing and says why it concerns the reader.
- **NB now:**
  - Hook Engine `selected_hook` (`hook_engine.py:249-271`). It uses six Engine hook types, each with an inline example.
  - The client's Dek and Stakes (`structure.md:36-45`) have **no field**.
- **Executes?** The hook executes as a field. Dek and Stakes exist as prose advice only. The composer may reword the hook, and nothing checks that the committed hook survived.
- **Decided at:** hook, by a model before drafting. Dek and Stakes, implicitly inside the composer.
- **Should be at:** before drafting, as one opening commitment (claim + checkable item + held-back variable). It is then checked after drafting.
- **Conflict:**
  - `hook_engine.py:65` ("Does NOT reveal the narrative_spine early — the reader earns the spine at the end") contradicts `structure.md:38-39` (the Dek states the claim with its number) and `structure.md:60` (front-loading is the default).
  - `hook_engine.py` and `platform_composer.py:174-175` forbid opening with a company. `structure.md:40-41` allows "a named company".
  - **Field-order conflict:** the composer places `reader_context` (a sentence on what the company does) and `first_wrong_explanation` directly after the hook. That is the generic setup the Dek/Stakes frame is meant to replace.
- **Smallest seam:** an opening-commitment output on the existing Hook Engine call, plus a deterministic post-draft check that the committed item appears in the first N words.
- **Needs:** a model call (existing stage) and deterministic code (check).

#### 1.3 Middle pattern / story shape

- **Problem:** the body's shape follows what the material is (Finding, Post-mortem, Argument, Explainer, Teardown), so articles don't all share one arc.
- **NB now:** a keyed table exists only as lens prose (`structure.md:65-80`). The lens says "Choose one pattern for the middle before writing… say so in the plan".
- **Executes?** **No.** There is no plan slot: the scalar slots are `claim_strength_ceiling`, `ending_mode`, `audience_currency`, `reader_verifiable_artifact` (`client_contracts.py:79-82`). No stage outputs a pattern and nothing records one. The body shape that actually executes is the composer's fixed block order.
- *[corrected after #281]* **Why the order is mandatory.** The composer already drops any block whose content is empty (`platform_composer.py:630`, `if mode == "skip" or not content: continue`). The fixed order is therefore mandatory only because `discovery_builder._validate` (`discovery_builder.py:77-78`) requires `first_wrong_explanation`, `puzzle` and `aha_setup` to be non-empty. Consequences:
  - **Dropping blocks is representable today.** Making those three fields optional removes their blocks.
  - **Reordering blocks is not.** The order itself is still a module constant.
- **Decided at:** effectively nowhere. De facto it is the Engine's hard-coded arc, repeated in four places:
  1. `_BLOCK_TABLE`.
  2. Wix `article_rules`: "Follow the arc: observation, tension, question, mechanism, evidence, reframe, one focused practical consequence, close." (`business_strategy.json:238`).
  3. Role `structure` (10 steps).
  4. The brand principle sent to Voice (`never_blank_voice.py:140`).
- **Should be at:** before evidence ordering and before the structural stages (Discovery, Story Assembly). The pattern determines what those stages should produce.
- **Conflict:** the largest single conflict in the repo. The client asks for a pattern library and "never detectable as a template". The Engine hard-codes one template in four places, and the stages that build the middle never see the lens.
- **Smallest seam:** a scalar plan slot (`middle_pattern`) whose permitted values the client declares in `monday.md ## Plan`.
  - With a single declared value, the contract decides it and no model call happens (`editorial_plan.py:574`; `plan_decisions.py:206-211` selects only slots with more than one value).
  - With several values, the existing `ModelPlanDecider` decides it (`plan_decisions.py:60-84, 257`).
  - Subset patterns (patterns that only drop blocks) execute through emptiness, as described above. Patterns that need a different order do not.
- **Needs:** a client document (the value list), deterministic code; a model call only for multi-value selection. A **new primitive** is needed only for reordering.

#### 1.4 Evidence ordering

- **Problem:** evidence appears in the order that builds the argument, and specifics come before abstractions.
- **NB now:** Discovery Builder `investigation_sequence` (2–4 beats, `discovery_builder.py:142-150`). The plan lists evidence in research-artifact order (`editorial_plan.py:355-358`). The final order is left to the composer.
- **Executes?** Yes as a field, but Discovery receives no lens and no plan.
- **Decided at:** a model call before drafting, with no client input.
- **Should be at:** before drafting, derived from the middle pattern (1.3) and the reveal decision (1.5).
- **Conflict:** the fixed block order puts `observation` (= `first_wrong_explanation`) and `recognition` *before* `evidence_pattern`. The Engine therefore structurally places abstraction and a straw explanation ahead of evidence (see 3.7).
- **Smallest seam:** route the plan and structure lens to Discovery Builder by adding it to `ARGUMENT_STAGES`. Order would still be advisory, because the block order is fixed.
- **Needs:** routing via existing code; real control needs the new primitive from 1.3.

#### 1.5 Reveal timing

- **Problem:** the article chooses deliberately between giving the finding early and withholding it, and a withheld result is resolved quickly.
- **NB now:** no field. The Engine prompts say "reveal at the end" (`hook_engine.py:65`). The block order builds a wrong-explanation → puzzle → explanation reveal arc. The client says front-load by default (`structure.md:60-63`). The research doc's "resolve within ~4 sentences / 40 words" is not implemented.
- **Executes?** The Engine's reveal-late arc executes structurally. The client's front-load default is advice only.
- **Decided at:** hard-coded by the Engine.
- **Should be at:** before drafting, as a per-article decision tied to the middle pattern.
- **Conflict:** a direct Engine–client contradiction.
- **Smallest seam:** a scalar plan slot (`reveal: front|withheld`), plus a deterministic post-draft check (position of the claim's number or term relative to article length).
- **Needs:** a client document, a model call (existing decider), deterministic code. It only takes effect together with the 1.3 primitive.

#### 1.6 Tension / contradiction

- **Problem:** the article is driven by a real contradiction in the material, not a manufactured one.
- **NB now:** several sources:
  - Signal `CORE_TENSION`.
  - Decision Lens Lite primary tension (legacy key `delivery_vs_presence_conflict`).
  - Discovery `puzzle`.
  - Plan activation `evidence_tension` (`plan_decisions.py:357-390`), backed by evidence ids.
- **Executes?** Yes. `evidence_tension` is the best-built mechanism in the repo: decided before drafting, recorded with evidence ids, routed to writers and reviewers.
- **Decided at:** model calls before drafting. The source-vs-evidence tension is recorded. The article's *main* tension is not.
- **Should be at:** before drafting. It is.
- **Conflict:**
  - `evidence_tension_lens.md:88-90` recommends ending on an open question ("Are we the only ones seeing the mismatch?"). `:95-96` of the same file, `monday.md:59` and `structure.md:53-56` forbid a closing question. The client contradicts itself.
  - Decision Lens Lite's tension key is still framed as "delivery vs presence". That pre-shapes every tension toward the old Compound Presence thesis.
- **Smallest seam:** none needed for the activation itself. Recording the main tension as a plan field would reuse the same decider.
- **Needs:** a model call (exists). The lens self-contradiction is a **human decision**.

#### 1.7 Concession

- **Problem:** state the real objection or limit before the reader raises it, only when one exists.
- **NB now:** the `concession.md` lens (standing; writing + revision). Pattern Extractor `evidence_limit` is the closest data, but it never reaches the composer (not in `_block_content`). Story Assembly `remaining_uncertainty` is produced "framed as an open question" (`story_assembly.py:53-54`).
- **Executes?** As advice only. No stage decides whether a concession exists or what it is.
- **Decided at:** implicitly in the composer, or by the Story Assembly field that turns a limit into a *question*.
- **Should be at:** before drafting, from evidence verdicts (qualified/rejected items and `acknowledged_limits` are already in the plan). The output is "none" or one attributable limit.
- **Conflict:** the client wants a concession stated as a limitation. The Engine turns the limit into an open question (`story_assembly.py`), which feeds the rhetorical-question problem (3.3).
- **Smallest seam:** a run-derived plan field (concession: none | text + evidence id), filled by the existing plan decider from `acknowledged_limits` and qualified evidence.
- **Needs:** a model call, an existing plan mechanism, deterministic validation of the evidence id.

#### 1.8 Ending strategy

- **Problem:** the article stops on a line that returns to the opening with new meaning, with no CTA or question after it.
- **NB now:**
  - `ending_mode` has one permitted value (`monday.md:55-59`).
  - The Echo line is written by Never Blank Voice *before any prose exists* (`never_blank_voice.py:37-60`).
  - Placement ("**Never Blank:** echo", then Sources only) is enforced deterministically (`platform_composer.py:328-385`).
- **Executes?** Mode and placement execute. The kicker's callback to the hook does not: the Echo is chosen "memorable out of context", which is not the same as "returns to the hook's image".
- **Decided at:** deterministic (mode, placement) plus a model before drafting (the line).
- **Should be at:** mode before drafting. The callback line should come after the opening is fixed, and could also be checked after drafting.
- **Conflict:**
  - The reviser can break the Echo line, because the validator isn't re-run after revision (`editorial_acceptance.py:445`; GAP:459-494 re-extracts the Echo and it may come back empty).
  - LinkedIn `length_rules` still say "website invitation" while the plan says no CTA.
  - Empirical: the Bagels ending (the only Monday output) is a paragraph of generic consequence ("For any owner who finds themself in this position, the practical consequence is clear…") before the Echo. The ending lens exists to remove exactly this.
- **Smallest seam:** re-run the existing closing validator on the revised text. Also give Voice the selected hook so the Echo can call back to it (both inputs already exist).
- **Needs:** deterministic code; routing of an existing field.

#### 1.9 Adjacent: portable noun and title

- **Portable noun:** the `PortableNoun` plan slot exists (`editorial_plan.py:196-205`). Production never sets it (GAP:2129 omits it), so it is always `None`. The noun is implicit in the composer. This is category C: representable now.
- **Title:** decided implicitly by the composer ("the hook, not a description", `platform_composer.py:184-186`). It is **not re-derived after revision**, so the published headline can describe a pre-revision article.

### Family 2. Exemplar- and reference-based writing

#### 2.1 Whole-article exemplars reaching generation

- **Problem:** show the model what "good" looks like, instead of describing it.
- **NB now:** **none.** No reference article, golden article or past published article reaches any generation call. The candidates are all read by nothing, or by tests only:
  - `editorial/reference/*`
  - `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md`
  - `strategy/stage2_reference_article_example.md`
  - `tests/fixtures/golden_wednesday/*.yaml`
  - `reports/sample_linkedin_articles_2026-07-21.md`
  - `data/memory/voice_examples.json`, whose loader exists (`memory.py:328`) but the file does not.

  What does reach models is **one-line register examples** hard-coded in stage prompts: hook types (`hook_engine.py:44-54`), spine sentences (`narrative_spine.py:47`), Echo lines (`never_blank_voice.py:53`), mechanism phrasings (`story_assembly.py:36`, `pattern_extractor.py`). All are marked "register only — do not copy".
- **Executes?** Only the one-liners do.
- **Decided at:** not applicable.
- **Should be at:** at composition (and possibly at the structural stages), selected by pattern.
- **Conflict:**
  - The golden Wednesday fixtures force `usage_rule: "reasoning_reference_only_do_not_imitate_wording"` (`wednesday_golden.py:130`). That policy is correct, but it is used only in tests.
  - `config/prompts/research/angles.yaml:11` gives the model a "Strong hook example": *"AI isn't replacing jobs. It's replacing layers."* That is exactly the "X isn't A, it's B" construction `structure.md:123` bans. It enters the signal as `POTENTIAL_HOOK` and reaches Pattern Extractor and Hook Engine. An exemplar the client bans is being fed to the pipeline.
- **Smallest seam:** there is no loader for client exemplars. `load_stream_contract` / `load_lens` read only `streams/`, `lenses/`, `lists/` (`client_contracts.py:586-593`). A client `exemplars/` directory would need a loader and a route.
- **Needs:** a client document (curated exemplars), exemplar retrieval (**new primitive**), and a **human decision** on which texts qualify.

#### 2.2 Selecting examples by article or source type

- **Problem:** the exemplar should match the kind of piece being written. A Teardown exemplar for a Teardown, not a generic "good article".
- **NB now:** none. The only keyed structure is the middle-pattern table in lens prose. Reference doc 12 names a model piece per pattern (e.g. the HBR "workslop" piece for Finding), but in an unread document. `SourceKind` (`wednesday_golden.py:73-81`) exists, but only for eligibility.
- **Executes?** No.
- **Decided at:** not applicable.
- **Should be at:** after the middle-pattern decision (1.3).
- **Conflict:** none (it doesn't exist).
- **Smallest seam:** depends on 1.3 (a recorded pattern) and 2.1 (an exemplar store).
- **Needs:** a **new primitive** (keyed retrieval) and a **human decision** (curation).

#### 2.3 How style is represented

- **Problem:** voice has to reach the model in a form it can act on.
- **NB now:** style is **prose rules plus banned phrases plus one-line register examples.** Representations:
  1. Client lenses, verbatim prose.
  2. `business_strategy.json` voice and principles, prose.
  3. Role rules, prose.
  4. Hard-coded stage prompts, prose with FORBIDDEN lists.
  5. The client ban list (30 literal phrases, gating).
  6. The shared tells list (8 entries, warn-only).
  7. Enums (hook types, `target_feeling`, `cta_mode`).

  There is no measurable style target: no sentence-length profile, no paragraph-variance target, no contrastive pairs in the live path. WRONG/RIGHT pairs exist only in legacy prompts (`config/prompts/blog_post.yaml:129` etc.), which the live path doesn't use.
- **Executes?** Yes, as instructions. Only the ban list is enforced.
- **Decided at:** not applicable.
- **Should be at:** not applicable.
- **Conflict:** Sveta's stated method (no negations / no "not this but that", no em dashes, chopped sentences, lists where they fit) is **absent from client documents** except the single "X is not about A" ban. `config/machine_tells/shared.yaml:11-14` explicitly delegates em dashes and triads to the client list, and the client list contains neither. This is recorded as a fact, not as a recommendation to adopt the method.
- **Smallest seam:** client list entries (literals) are representable today. Anything statistical is not (see 3.8).
- **Needs:** a client document, plus a **human decision** on whether the method becomes policy.

#### 2.4 Negative / contrastive exemplars

- **Problem:** showing the model what a failure looks like, alongside the fix.
- **NB now:** only in the legacy path. The Wednesday rubric has negative descriptions (`never_blank_golden_wednesday.yaml`), with no texts.
- **Executes?** No, in the live path.
- **Needs:** a client document and retrieval. It could reuse the blocked-run bodies already saved as `editorial_review_content.json`.

### Family 3. Anti-AI-shaped prose

A cross-cutting finding comes first. In the sample pack, the same shapes recur across streams:

- **"It's easy to assume… / At first glance… But the reality is…"**: Ramp, Uranium, ChargePoint, Versant.
- **"This isn't just [hypothetical / theory / a small-business problem]. In one documented case / When [company]…"**: Bagels, Sales calls, Ramp, Uranium.
- **"Consider where your own…"** as the closing line: Sales calls, Ramp, Uranium.

These map one-to-one onto Engine fields and prompts:
- `first_wrong_explanation`, placed as the `observation` block.
- The hypothetical owner scene: Pattern Extractor `founder_scenario`, "the moment they recognize their situation" (`pattern_extractor.py:53-55`).
- The role structure's "Why this case" step ("This case is worth examining because…" in Bagels).
- The practical-question step.

**Much of the AI shape is generated by the structure, not by sentence choice.** Surface bans cannot repair it.

#### 3.1 Generic reader setup ("Most founders…", "If you're a…", "For any owner who…")

- **Created by:**
  - Discovery Builder `aha_setup`: "A concrete owner-recognition scene… Prefer second person" (`discovery_builder.py:46-48`). It is required by `_validate`, so it lands in the composer's `recognition` block.
  - Discovery's protagonist rules (`discovery_builder.py:21-24`).
  - Pattern Extractor `founder_scenario`.
  - Hook types built around owner recognition (`hook_engine.py:22-29`).
  - Composer `_FORMAT_CONSTRAINTS["long"]`: "one central owner-centered idea" (`platform_composer.py:94-101`).
  - *[corrected after #281]* The `reader_context` block is **not** a source: it is a 10–20-word line on what the company does, and is skipped for household names.
- **Detected by:** no regex. `hook_engine.py:66-68` forbids "Many founders…" in hooks only. The model criterion `audience-recognition` judges the result.
- **Repairable later?** Only by the free-text reviser, and only if the reviewer flags it. The block order reintroduces it on every regeneration.
- **Smallest seam:** client list literals for the common openers (gates, representable now). The real fix is upstream (the order of 1.2 and 1.4).
- **Needs:** a client document plus the 1.3 primitive.

#### 3.2 Hypothetical "Suppose you… / Imagine… / Picture this" openings

- **Created by:** the same `founder_scenario` field, plus `_FORMAT_CONSTRAINTS["instagram"]`: "Make the reader feel a specific owner situation" (`platform_composer.py:121`). Bagels opens with a second-person hypothetical ("A sudden income shock can jolt you into action…").
- **Detected by:**
  - `shared.yaml:84-93`: `imagine-opening` and `picture-this-opening` regexes, first paragraph only, **warn-only** (`tier: directional`).
  - "Suppose" is not matched at all.
  - Because the Dek now sits on its own line above the text (`structure.md:38-39`), the "first paragraph" scope usually covers only the Dek, so a hypothetical in paragraph 2 escapes even the warning.
- **Repairable later?** Reviser only, and only if flagged.
- **Smallest seam:** extend the scope to the first N words after the Dek. Promote to a client gate if the client decides to.
- **Needs:** deterministic code, a client document.

#### 3.3 Rhetorical-question framing

- **Created by:**
  - Story Assembly `remaining_uncertainty` "framed as an open question" (`story_assembly.py:53-54`).
  - Role structure: "One practical question or consequence".
  - Wix arc: "…tension, **question**, mechanism…" (`business_strategy.json:238`).
  - `evidence_tension_lens.md:88-90`.
  - Old outputs show both mid-body and closing questions (Toyota, ChargePoint, Sales calls).
- **Detected by:** only the literals `what do you think?` and `let us know in the comments` (client gate). There is no `?` count and no check of question position.
- **Repairable later?** Reviser only.
- **Conflict:** four Engine sources ask for questions, and three client sources forbid them.
- **Smallest seam:** a deterministic count of `?` outside quotations, by position (first screen, last paragraph). Resolve the lens contradiction.
- **Needs:** deterministic code; a **human decision** on the lens.

#### 3.4 Predictable transitions

- **Created by:** composer prose generation. Transitions come from the model's default register. The block order also forces a transition at every block seam: ten blocks means nine seams.
- **Detected by:** client list literals `here's the thing`, `the bottom line is`, `moreover,`, `furthermore,`, `at the end of the day`, `in conclusion`, `it's worth noting that`, `when it comes to`, `the harsh reality is`. These gate on Monday.

  Not matched: "But here's…", "The bottom line" without "is", "This isn't just…", "It's easy to assume…", "The real mechanism…", "The practical consequence is clear", "That is the part…". The families observed in real output are almost entirely absent.
- **Repairable later?** Yes for literals: the reviser gets gated findings.
- **Smallest seam:** client list additions, representable now. Families (pattern classes, not literals) need regex entries in a client list. The client list format today is literal-only (`machine_tells.py:289-302`), while the shared list supports regex.
- **Needs:** a client document; a small format extension (deterministic).

#### 3.5 Symmetric paragraph structure

- **Created by:** a ten-block fixed order at a 400–600-word target (`platform_composer.py:67`) yields roughly equal blocks. Every block gets "full" treatment in `long`.
- **Detected by:** nothing. `structure.md:104-108` says so explicitly ("nothing checks it mechanically… what they recognise is evenness").
- **Repairable later?** No stage is asked to vary it. The reviser preserves structure (`never_blank.yaml:85-86`).
- **Smallest seam:** a deterministic paragraph-length distribution metric, recorded first and then optionally thresholded.
- **Needs:** deterministic code; a **human decision** on any threshold.

#### 3.6 Repeated explanation / rephrasing

- **Created by:** the field architecture. `mechanism`, `never_blank_insight`, `narrative_spine`, `surviving_explanation`, `reframe` and `business_translation` are six fields that frequently state the same idea. The composer renders each one as a block. The Bagels body states "capacity is the ceiling" in at least four paragraphs.
- **Detected by:**
  - `output_guard.py:145-158`: exact repeated 8+-word sentence, or last-two-sentence overlap ≥0.55. It gates via retry, but catches only verbatim repeats.
  - Semantic restatement is left to the `generic-filler` criterion (one sentence, no bar).
- **Repairable later?** Partly, via the reviser.
- **Smallest seam:** a deterministic within-article paragraph-to-paragraph similarity measure (n-gram or embedding; `src/internal/memory.py` has embedding code on the legacy path). The structural cause is fields that overlap semantically.
- **Needs:** deterministic code; the structural fix is the 1.3 primitive.

#### 3.7 Unsupported abstraction before evidence

- **Created by:** the block order. `observation` (the wrong explanation) and `recognition` (aha setup) come before `evidence_pattern`. The Engine prompts front-load mechanism language. The evidence reaches the composer only through plan text, not as blocks.
- **Detected by:** nothing deterministic. The client hook rule "Not a summary, not a generalisation" (`structure.md:40-44`) is advice.
- **Repairable later?** Reviser only; structure is preserved.
- **Smallest seam:** a deterministic "first evidence anchor position" measure (first sentence containing a figure, named entity or source link from the usable evidence). The inputs exist: the figure trace in `machine_tells.py:418-432` already matches numbers against evidence.
- **Needs:** deterministic code.

#### 3.8 Excessive smoothness / evenness

- **Created by:** the drafting model, amplified by one-pass composition from pre-digested fields. The composer never touches the raw evidence text, only summaries of summaries.
- **Detected by:** nothing. There are no sentence-length statistics anywhere in the codebase.
- **Repairable later?** No stage targets it. "Moment of authorial risk" is explicitly judgement-only (`structure.md:102-108`).
- **Smallest seam:** deterministic per-article statistics (sentence-length SD, share of short sentences, paragraph-length SD, punctuation mix), recorded as run evidence. These are **not** an AI detector, only a distribution description.
- **Needs:** deterministic code. What counts as "enough" variation is a **human decision**, and should come from a reference distribution computed over exemplars the client approves.

#### 3.9 Portfolio-level structural repetition

- **Created by:** the fixed arc, the fixed hook-type enum and one Echo pattern ("Never Blank: Sometimes…"). This is visible across the sample pack.
- **Detected by:**
  - Nothing in the live path.
  - `EXECUTION_REVIEW_SCOPE` asks the reviewer to report "one repeated shape from articles like this one" (`editorial_acceptance.py:233-235`), but the reviewer only ever sees the current article. **The instruction cannot be executed.**
  - `portfolio_regularity` (`editorial_plan.py:815`) counts plan-slot values across runs, but it is never passed into a run (GAP:2129 omits `regularity=`), and the only slot with variety today is `reader_verifiable_artifact`.
  - `echo_memory.check_echo_uniqueness` exists and would raise, but nothing calls it.
- **Repairable later?** Not at all today.
- **Smallest seam:**
  1. Persist per-article structural features at acceptance (hook type, opening-sentence class, pattern, reveal, ending type, title shape, paragraph profile, first-evidence position). `editorial_plan.json` and `published_content_index.jsonl` already persist per run. Published article bodies are **not** stored in any index.
  2. Wire `portfolio_regularity` into the run.
  3. Give the reviewer the last N feature records.
- **Needs:** deterministic code, plus a state store (published bodies/features). The reviewer's use of it is a model call. Thresholds are a **human decision**.

**Portfolio signals that need no AI detector.** All are deterministic and computed over stored accepted articles:

- Opening-sentence class distribution (hypothetical-you / assumption-reversal / figure / named case / quote).
- Hook-type and Echo-template frequency. The shared prefix "Never Blank: Sometimes…" is already visible.
- Title shape (length, "The X…/How…/Why…" leads, colon use).
- Position of the first evidence anchor (normalised).
- Paragraph-count and length profile; sentence-length SD.
- Cross-article 4–5-gram overlap. `derivation_fidelity.py:76-102` already implements an n-gram check, but only between a draft and its own revision.
- Transition-family frequency (per-family regex counts).
- `?` count and position.
- Plan-slot value rotation: `activation_rates` exists, but only in a manual script (`scripts/portfolio_activation.py:65`).
- Middle-pattern rotation, once 1.3 exists.

### Family 4. Generation architecture

#### 4.1 Which stage creates which behaviour

| Behaviour | Created by (stage · seam) | Client lens visible to that stage? |
|---|---|---|
| Owner-hypothetical opening | Discovery `aha_setup` ("Prefer second person", required by `_validate`) → `recognition` block; Pattern Extractor `founder_scenario` → Hook Engine | No (Discovery, Pattern Extractor); yes (Hook) |
| Straw "you might assume…" | Discovery `first_wrong_explanation` → `observation` block (`platform_composer.py:545`) | No |
| Late reveal | Hook Engine rule `:65` plus block order | Yes, but conflicting |
| Abstraction before evidence | Block order (`_BLOCK_TABLE`) | n/a (hard-coded) |
| Repetition of the mechanism | Six overlapping fields (Pattern, Decision Lens, Spine, Story ×3) | Mostly no |
| Open question | Story Assembly `remaining_uncertainty`; role structure; Wix arc | No / prose |
| Generic consequence paragraph | Story `business_translation` → `business_meaning` block; role "practical consequence" step | No |
| Echo with no callback | Voice, before prose | Yes, but it can't see the hook in final form |
| Uniform evenness | Composer, one pass over ten equal blocks | Yes (prose only) |
| Company-as-evidence cap / Teardown rejection | Pattern Extractor rejects "corporate example cannot be removed" (`pattern_extractor.py:94`); composer ≤20% (`:98-99`) | No |

#### 4.2 What later stages can and cannot repair

- **Reviser (one call, free text).**
  - *Can:* rewrite anything, including structure. It is followed only by factual and editorial review.
  - *Cannot:* repair things nobody flags. The reviewer is told not to judge order or shape (`editorial_acceptance.py:225-238`). The reviser is told to preserve structure (`never_blank.yaml:85-86`, "Revision is surgical", `:397-403`). It **does not receive `structure.md`**: only concession, portable_noun, revision and evidence_tension reach it.
  - *After it runs:* the closing validator is not re-run and the title is not re-derived.
  - **In effect, structural defects created before drafting cannot be repaired after it, by design.**
- **Stage retry.** It regenerates the same stage with the same inputs, so it reproduces the same structure.
- **Recomposer.** It works from the accepted article only, so it inherits the article's structure.

#### 4.3 Engine vs client policy conflicts (confirmed in code)

1. **Reveal:** `hook_engine.py:65` against `structure.md:38-39, 60`.
2. **Named company in the hook:** `hook_engine.py` and `platform_composer.py:174-175` against `structure.md:40-41`.
3. **Owner-only protagonist and the Teardown reject:** `pattern_extractor.py:85-94`, `never_blank_voice.py:87-88` and `platform_composer.py:98-99` against the Teardown and Argument rows of `structure.md:69-75`. The gate at 9a can exit-6 exactly the signals Teardown exists for.
4. **Fixed arc (×4) against the pattern library:** see 1.3.
5. **Subheads:** role structure "not required" against `structure.md:95` "Always present".
6. **Questions:** four Engine sources against three client sources, and the client contradicts itself.
7. **LinkedIn CTA:** `length_rules` "website invitation" against plan `ending_mode`. The structure lens (200-word opening, Dek, subheads) is also sent to a 120–220-word LinkedIn post.
8. **Reviewer scope:** "never judge order" against `structure.md:36` "these four in this order".
9. **Voice person:** `story_assembly.py:282` "First-person investigative" against `discovery_builder.py:156-157` and `platform_composer.py:171-172`, which forbid it.
10. **Length:** a 400–600-word target against ~200 words of opening plus subheads, middle and kicker.
11. **Banned exemplar:** `research/angles.yaml:11` "AI isn't replacing jobs. It's replacing layers." against `structure.md:123`.

#### 4.4 Is the model asked to make an editorial decision too late?

**Yes, in three concrete ways.**

1. **Middle pattern, concession, portable noun, reveal, subhead plan and the Dek** are all left to the composer, which must decide and execute them in the same pass while holding ten pre-shaped blocks that already imply a different arc.
2. **The Echo is decided before the prose, and the hook before the evidence order.** The one element that should be decided last (the callback) is decided first.
3. **The five stages that fix the argument's content and order (Pattern, Decision Lens, Reader Context, Discovery, Story) run before any client decision reaches them.** Their outputs are then treated as fixed material. The client's decisions arrive only at the one stage that can no longer change the material, only its phrasing.

### Family 5. Review and measurement

#### 5.1 What is measured and enforced

**Gates** (can block or force a revision):
- Client ban list: 30 literals, Monday only.
- Factual reviewer: model, 8 finding kinds.
- Editorial acceptance: model, 9 pass/fail criteria, no numeric bars. "ACCEPT only when every rubric criterion passes" (`never_blank.yaml:61-62`, enforced at `editorial_acceptance.py:172-188`).
- Output guard: dictionary-style opener, detective first-person, exact repetition.
- Derived-figure and fidelity checks on social.
- Source transparency.

**Warnings or logs only:**
- Shared tells: all `tier: directional`.
- Voice self-checklist: `log.warning`.
- Word-count range.
- Differentiation: legacy path only.

**Counted, never used:** `portfolio_regularity`, `activation_rates`, fidelity diagnostics, `analytics_score`. The last is collected and written back, and read by no generation, planning or review code.

#### 5.2 What reviewers actually enforce

- **Facts, provenance, claim strength:** strongly enforced. This is the most mature part of the system.
- **Editorial quality:** enforced as nine model judgements with no bar. `generic-filler` is the only criterion about AI-shaped prose, and it is one sentence.
- **Structure:** **explicitly not enforced.** The reviewer is instructed not to judge order, shape or optional elements (`EXECUTION_REVIEW_SCOPE`, `PLAN_REVIEW_SCOPE`). The intention is clear (avoid checklist writing), but the result is that no stage enforces structure at all.

#### 5.3 Important decisions that are advisory only

- Middle pattern.
- Reveal timing.
- Dek/Stakes.
- Concession.
- Portable noun.
- Moment of authorial risk (by design).
- Subheads.
- Kicker callback.
- Evidence-before-abstraction.
- Any non-literal machine tell (hypotheticals past paragraph 1, transition families, questions, triads, em dashes, evenness).
- Portfolio repetition.

---

## 3. Mechanisms the current system cannot represent at all

These are distinct from mechanisms that exist but aren't enforced.

1. **A per-article block order.** Which blocks appear can already be controlled through empty fields (see the correction in 1.3). The order cannot: it is a module constant. No data structure can say "these blocks, in this order".
2. **Exemplars as inputs.** There is no client exemplar store, no loader, no route to a prompt, and no retrieval keyed by pattern or source type.
3. **Portfolio state as an input to a run.** Published article bodies and structural features aren't persisted. No run reads the history of other runs (the one function that could, `portfolio_regularity`, isn't wired).
4. **Distributional style targets.** There is no representation of "sentence-length variance should look like this", only literals and prose.
5. **Pattern-class (non-literal) client bans.** The client list is literal-only. The shared list supports regex but can't gate.
6. **Positional constraints.** "The first evidence anchor within N words", "no question in the last paragraph" and "the claim's number in the Dek" can't be expressed as client policy. The only positional scope that exists is "lede = first paragraph".
7. **A structural check after revision.** The revised text is free text. No structural contract, closing validator or title re-derivation is re-applied.
8. **Decisions made after the draft.** The pipeline is strictly pre-draft fields → one composition → repair. There is no two-pass shape (draft, then choose the kicker, title and cut from the draft). Kicker and title are exactly the decisions that benefit from seeing the draft.
9. **Human selection between candidates.** Hook Engine produces 5–7 candidates and picks one internally. No seam exists for a human to pick an angle, hook or pattern.

---

## 4. Gap matrix

**A. Implemented and genuinely executable**

| Mechanism | Seam |
|---|---|
| Evidence verdicts; the do-not-use set excluded from writing | `assessment.py:287-293`; `editorial_plan.py:900-921` |
| Evidence-tension activation (before drafting, recorded with evidence ids, routed) | `plan_decisions.py:357-390`; `evidence_tension_lens.md` |
| `reader_verifiable_artifact` decided per run | `monday.md` Plan; `ModelPlanDecider` |
| Ending mode and closing placement (Echo → Sources, no CTA) | `platform_composer.py:328-385` |
| Client literal ban list as a gate (Monday) | `machine_tells.py:289-302` |
| Factual / provenance / claim-strength review as a gate | `factual_review.py` |
| Exact-repetition, dictionary-opener and detective-voice guards | `output_guard.py` |
| Social derivation fidelity and figure trace | `derivation_fidelity.py`, `platform_composer.py:472-535` |
| Lens routing with a delivery record (#279) | `client_contracts.py`, `pipeline.py:175-193` |

**B. Implemented as prose but not enforced**

| Mechanism | Where it lives |
|---|---|
| Middle-pattern library and choice | `structure.md:65-80` |
| Dek / Hook / Stakes frame and its order | `structure.md:36-49` (the reviewer is told not to judge order) |
| Front-load default / reveal timing | `structure.md:60-63` (contradicted by `hook_engine.py:65`) |
| Concession | `concession.md` |
| Portable noun | `portable_noun.md` (the slot exists and is always `None`) |
| Subheads; inline working link | `structure.md:95-100` |
| Kicker returns to the hook | `structure.md:53` |
| Consequence carries a number | `structure.md:117-119`; `monday.md` restrictions |
| Hypothetical / "Imagine" openings | `shared.yaml` (warn-only, paragraph 1 only) |
| `not just…but` | `shared.yaml` (warn-only) |
| Voice self-checklist | `never_blank_voice.py:184-191` (log only) |
| "Report one repeated shape" | `editorial_acceptance.py:233-235` (not executable: no history) |
| `generic-filler` | a single un-thresholded model criterion |

**C. Missing but representable with the existing architecture**

| Mechanism | Existing seam it would use |
|---|---|
| `central_claim` as a decided run slot (not copied from the signal) | `PLAN_RUN_SLOTS` + decider |
| `portable_noun` actually filled | Existing `PortableNoun` slot |
| Middle pattern, reveal, concession recorded as plan decisions | `PLAN_SCALAR_SLOTS` / run slots + `ModelPlanDecider` (a single-value slot costs no call) |
| Subset-type middle patterns executed through optional fields | `discovery_builder._validate` + the composer's empty-block skip (`platform_composer.py:630`) |
| Plan and lenses routed to Discovery / Story / Pattern Extractor | `ARGUMENT_STAGES` routing (#279 mechanism) |
| Additional client literal bans (observed transition families, generic openers) | `lists/machine_tells.md` |
| Opening-hypothetical check extended past the Dek | `shared.yaml` scope / `_lede` |
| Closing validator and title re-derivation after revision | Existing validator; existing composer field |
| Voice receives the final hook for the kicker callback | Existing fields |
| `portfolio_regularity` passed into a run | `build_editorial_plan(regularity=…)` |
| Per-article deterministic style statistics recorded as run evidence | Run-evidence JSON pattern |
| Removing the banned exemplar from `research/angles.yaml` | Engine prompt file |
| Resolving the Engine/client prompt conflicts in §2 4.3 | The prompt strings named there |

**D. Requiring a new primitive**

| Primitive | Why the existing architecture can't hold it |
|---|---|
| Pattern-conditioned block **order** | Order is a module constant. Selecting a **subset** of blocks is category C: fields made optional drop their blocks |
| Client exemplar store plus keyed retrieval into prompts | No loader, no directory type, no route |
| Portfolio state store (accepted bodies and structural features) plus a read path into runs and reviewers | Bodies aren't persisted; runs don't read other runs |
| Pattern-class and positional client policy (regex/position rules that gate) | The client list is literal-only; the only position is "lede" |
| Post-draft decision pass (kicker, title, cut chosen from the draft) | The pipeline is strictly fields → one composition → repair |
| Structural contract re-checked after revision | Revision output is unconstrained free text |
| Distributional style targets derived from an approved reference set | No representation for distributions |

**E. Genuinely requiring human editorial judgement**

- Which texts qualify as exemplars, per pattern. Curation cannot be delegated to the system that produces the problem.
- Whether Sveta's method (no negations, no em dashes, chopped sentences) becomes client policy, and to what extent. It currently conflicts with nothing in code, because it isn't in the client documents.
- Resolving the client's own contradiction on closing questions (`evidence_tension_lens.md:88-90` vs `:95-96`).
- The Teardown/Argument versus owner-only protagonist policy (Pattern Extractor's reject rule against `structure.md`).
- Thresholds for any evenness or repetition metric: what counts as "too even" or "too similar".
- The moment of authorial risk. The client has declared it judgement-only.
- Angle selection, where a human wants a veto before drafting.
- Whether the reviewer should enforce structure at all, given the deliberate anti-checklist stance of #269.

---

## 5. Reconciliation with #277 and #281

*Read-only. This section neither designs nor amends #281. It records what the repository shows next to what the two issues state.*

### 5.1 Where the issues and this track agree

- **The missing mechanism is a structure decision made before writing.**
  - #281, decision 1.
  - Here: 1.3 and 4.4.
- **The hypothetical-owner opening is produced upstream, not by the composer.**
  - #281 names `discovery_builder` as the blocker.
  - Here: 3.1, 3.2 and 4.1.
- **`hook_engine.py:65` ("reader earns the spine at the end") contradicts the client's front-loading default and wins, because it sits closer to generation.**
  - #281 §B.2.
  - Here: 1.5 and 4.3 item 1.
- **Owner-protagonist policy is hard-coded in generic Engine prompts.**
  - #281 §B.1 and B.4.
  - Here: 4.3 item 3.
- **The `unsupported-claims` criterion does not cover opening generalisations.**
  - #281 §C.
  - Here: 3.7 and 5.2.
  - This matches #277's description of the dry-run: generic opening, lead-quality claims beyond the metrics, ACCEPT anyway.

### 5.2 Corrections to this report, from #281 (applied in place)

1. **Why the blocks are mandatory.** It is `discovery_builder._validate`, not `_BLOCK_TABLE`. The composer already skips empty blocks. Dropping blocks moves from D to C; reordering stays D.
2. **`reader_context` is not a source of generic setup.**
3. **The source of the hypothetical opening is Discovery `aha_setup`** ("Prefer second person"), in addition to Pattern Extractor `founder_scenario`.

All three were verified in code at `87ea0f4`.

### 5.3 Repository facts that bear on Teardown and are outside #281's per-stage list

These are facts, not recommendations. Each one either reaches the Monday path today or sits in a stage #281 marks "no change".

| # | Fact | Seam | Bearing on a case-first Teardown |
|---|---|---|---|
| a | Pattern Extractor runs **first** and rejects a signal when "the corporate example cannot be removed without the pattern collapsing" or when "the founder_scenario requires the reader to know the corporate example". `article_protagonist` is "Always 'owner'… never the corporate example's name". A rejection exits with code 6 and the signal is skipped. | `pattern_extractor.py:85-97`; GAP:2197-2211 | Signals whose case *is* the article can be discarded before any plan-aware stage runs. #281 lists the stage in the chain but gives it no per-stage entry. |
| b | Composer `long` format constraint: "Corporate evidence… at most 20 percent of the body, and the article must remain coherent without the company example". | `platform_composer.py:98-99` | This is Engine prose inside the stage #281 marks "no change in step 1". It reaches the composer on every run. |
| c | The Voice checklist says corporate evidence should be "not more than 20-25%". | `never_blank_voice.py:87` | Log-only (the checklist doesn't gate), but it is in a stage that receives the plan. |
| d | Hook Engine: "A hook that requires knowing the company name to make sense has failed." | `hook_engine.py:131` | Separate from the six types and rule 5 that #281 addresses. It opposes the `opening_commitment` value "the named company". |
| e | Decision Lens Lite asks for `owner_system_objective` and a delivery-vs-presence tension, with no plan and no lens. | `decision_lens_lite.py:44-72`; `pipeline.py:60-62` | It pre-shapes the tension toward the owner before any Teardown instruction arrives. |
| f | Story Assembly `remaining_uncertainty` is "framed as an open question". | `story_assembly.py:53-54` | #281 marks the stage "no change". It is the main Engine source of the closing question (3.3), which `monday.md:59` forbids. |
| g | The Engine reviewer clause says "Never pass or fail this article on the order its paragraphs or sections appear in". | `editorial_acceptance.py:225-238` | The proposed `pattern-executed` criterion judges a move sequence, which is an order. Both would arrive in the same review request. |
| h | The reviser does not receive `structure.md`. The closing validator isn't re-run after revision. The title isn't re-derived. | GAP:2337-2343; §4.2 | A pattern executed in the draft can be undone in the one revision, and nothing re-checks it. |
| i | The Monday role `structure` in `business_strategy.json` is a third structural authority, next to the lens and the plan. It is already case-first ("Verified account of what happened… Why this case is worth examining… exactly ONE mechanism…") and includes "One practical question or consequence". The Wix `article_rules` add a different arc ("observation, tension, question, mechanism…"). | `business_strategy.json` Monday role; `:238` | Both reach the composer through the role rules on every run. #281 doesn't mention them. |
| j | The daily research prompt gives the model the "strong hook example" "AI isn't replacing jobs. It's replacing layers." That example enters the signal as `POTENTIAL_HOOK`. | `config/prompts/research/angles.yaml:11` | It feeds the banned "X isn't A, it's B" construction into Pattern Extractor and Hook Engine regardless of the pattern. |

### 5.4 What neither #277/#281 nor the current repository covers

These come from this track's categories C, D and E and are left open by #281's scope boundaries:

- Measuring or reviewing portfolio-level repetition (3.9).
- Evenness and distribution metrics (3.5, 3.8).
- Pattern-class and positional client bans (3.2–3.4).
- A structural re-check after revision (5.3 h).
- Exemplars: #277 asked for worked examples as part of the deliverable, but the repository has no route for exemplars to reach generation (2.1, 2.2).
- The four-sentence bound on a withheld reveal, and the conclusion-placement rule. #281 lists both as unplaced (owner decision 4).

### 5.5 Gap-matrix status against #281

#281 is open and blocked on the owner. Nothing in it is implemented, so every classification in §4 stands as of `87ea0f4`. If #281 were implemented as written:

- **Middle pattern (Teardown only) and opening commitment** would move from B to A.
- **Rows a–j in 5.3** would keep their current status.
- **Every other §4 row** would be unchanged.

---

*Stopping here. Waiting for the external research synthesis.*
