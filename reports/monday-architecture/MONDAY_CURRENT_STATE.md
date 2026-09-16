# Monday — current-state architecture trace

Forensic record for Issue #240, deliverables 1–6. Read-only. **Nothing in this
document changes product logic, and nothing in it is a decision.** No live run,
no provider call and no model call was made to produce it.

Base: `58afe47` (tip of `main` at the time of writing, and of the branch this
report is written on). Every claim below is one of:

- `VERIFIED-IN-REPO` — re-derivable from tracked files at `58afe47` by reading
  them. The default; assume it unless a claim says otherwise.
- `AUDIT-EVIDENCE` — established by #233, #234 or #237 and re-checked here
  against the same files. The source is named inline.

Scope is Monday only. Wednesday and Friday are paused and are not modified,
proposed for modification, or reasoned about here beyond the points where
Monday's own path touches them. `strategy/current/business_strategy.json` is
traced and classified; it is **not modified and not deleted**.

---

## 0. Gate: what the audits establish, and where they live

The issue makes #233 an execution gate and names #234 as evidence. Both exist.
Neither is merged to `main`, which is why neither is in this working tree:

| Input | Where it is | Status for this report |
|---|---|---|
| #233 repository reachability audit | `docs/repository-audit/REPOSITORY_AUDIT.md` + `reports/repository_audit/**` on `origin/orch/233` | Read and incorporated (§0a) |
| #234 editorial-wiring forensic | `reports/editorial_wiring/ISSUE_234_EDITORIAL_WIRING_FORENSIC.md` on `origin/evidence/234-editorial-wiring` | Read and incorporated (§0b) |
| #244 Monday semantics inventory | `reports/editorial_wiring/ISSUE_244_MONDAY_SEMANTICS_INVENTORY.md`, same branch | Read, reconciled, and corrected in three places (§0c) |
| #237 Monday selection forensic | `docs/MONDAY_SELECTION_HEAD_OF_LINE.md` on `origin/orch/237` | Read and incorporated (§7) |

The remaining part of the gate is procedural: #233 has to merge, and one of its
findings (F5, the artifact root) is a mechanical prerequisite for the tests this
architecture would need — recorded in the target document's migration order, not
resolved here.

### 0a. What #233 establishes about Monday

Four of its findings bear on Monday directly.

- **F3.** `business_strategy.json:306-342` declares seven `prompt_rule_references`.
  Exactly one is functionally consumed, and only as a version equality check
  (`src/strategy/execution_context.py:296-315`). The other six name files no code
  opens. Re-verified here: §5.
- **F5.** `scripts/generate_and_publish.py:320-321` resolves
  `reports/content_packages` against the process CWD and creates it at *import*
  time, so any test that imports the canonical entrypoint writes run artifacts
  into the tracked tree. 7,796 of 8,399 tracked files are that residue. This is
  why the end-to-end message-capture tests Monday's migration needs cannot be
  written cleanly today.
- **F4d.** `daily_signal_research.yml` runs every day; its inline guard forces
  `NB_RESEARCH_PUBLISH_ENABLED=false` **only** on Wednesday. On a Monday, whether
  a second article publishes is the value of a secret and is not answerable from
  source. Monday's strategy therefore does not govern everything that publishes
  on a Monday.
- **F9/§7.** The one test that mentions the declared reference documents asserts
  `resolved.is_file()`. Re-verified: `tests/strategy/test_never_blank_business_config.py:80-86`.
  A reference no code reads passes it forever.

#233 also names the two patterns this repository already has that are the right
shape for proving consumption — `tests/strategy/test_strategy_semantic_consumption.py:90-112`
and `tests/test_r1_publish_scope.py:47-50`. The target document builds on those
rather than inventing a mechanism.

### 0b. What #234 establishes about Monday

#234's verdict for Monday is **PARTIALLY WIRED**: typed configuration reaches
three writing calls; none of `config/brand_voice.md`,
`docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md`, `docs/NEVER_BLANK_EDITORIAL_STYLE.md`
or `config/prompts/blog_post.yaml` reaches any of them; and the **reviser** — the
call that rewrites the published Wix prose whenever acceptance says `revise` —
receives neither the role nor the voice. Its historical finding is that
`NEVER_BLANK_EDITORIAL_STYLE.md` was genuinely executable until `2466611`
(2026-07-03), when the V2 engine replaced the prompt that loaded it and deleted
the loader; no test noticed, because no test ever asserted its content reached a
prompt.

#234 also carries three owner decisions recorded on 2026-09-15 that bound this
task, and they are the reason the report stops where it does:

- Human-readable **Markdown is the intended source of truth** for product and
  editorial strategy; JSON/JSONL only as derived machine representation, runtime
  state or interchange; the same strategy must never be maintained twice by hand.
- **Wednesday and Friday are paused.** July-fidelity-vs-Golden is not being
  decided, `config/prompts/linkedin_post.yaml` is not to be repaired, and the
  legacy six-channel Friday path is recorded as architecture evidence only.
- **Monday is the first reference implementation**, and the answer must not be
  another Monday-specific Python engine.

### 0c. Where this report corrects #244

`ISSUE_244_MONDAY_SEMANTICS_INVENTORY.md` is an earlier Monday inventory and
proposal on the evidence branch. Its findings hold. Three details differ from
what the files say at `58afe47`, and the corrected values are used throughout:

1. `prompt_rule_references` spans **`business_strategy.json:306-342`**, not
   `312-341`, and declares **seven** references of which six are never opened —
   #244 counts the block from its second entry.
2. `channels.*.visual_rules` are not merely "never passed to the composer".
   They are also carried into `VisualStrategyView`
   (`src/strategy/execution_context.py:243-245`) and handed to the visual
   boundary (`scripts/generate_and_publish.py:1755,1816`), where
   `src/visual/__init__.py:50-66` reads only their `identity` field. They are
   validated, hashed into the configuration identity, carried across a boundary,
   and never read as rules — a stronger form of the same defect.
3. #244 treats the 15-candidate bound as a Monday selection rule to be
   redesigned. #237 establishes that it is a Release 1 cost ceiling whose
   *interaction* with an oldest-first queue is the defect. The issue forbids
   redesigning it around the superseded eligibility contract, so §7 records the
   mechanism and leaves the choice where #237 left it.

---

## 1. Current Monday end-to-end execution

```
.github/workflows/monday_publish.yml
│   cron "17 8 * * 1" / "17 9 * * 1"  (04:17 America/New_York, #232)
│
├─ due_check.py --day monday --role never-blank-monday-documented-case      :84
│     → which of the two UTC firings is the real Monday; stale firings publish
│       nothing. Writes reports/scheduling/monday_scheduling_decision.json.
│
├─ select_eligible_signal.py --editorial-role never-blank-…-case            :159
│     load_business_strategy_configuration()  → role.eligibility_criteria
│     _load_candidates(signals_active.jsonl minus published_signal_ids.txt)
│     for candidate in candidates[:15]:                     ← MAX_CANDIDATES_CEILING
│         judge_source_eligibility(signal, role, transport) [LLM · model_enrich]
│     exit 0 selected / 3 all-ineligible / 4 judgment failure / 5 truncated
│     → reports/stream_selection/monday_selection.json
│
└─ generate_and_publish.py --signal-id … --editorial-role …                 :271
   │
   ├─ load_business_strategy_configuration()                                :889
   │  StrategyExecutionContext.from_configuration() → research / decision_lens_
   │  editorial / wix / linkedin / visual views, one identity hash            :890
   ├─ resolve_editorial_role(configuration, role_id)                         :910
   │  _editorial_role_rules = {"long": render(role,"wix"),
   │                           "medium": render(role,"linkedin")}            :920
   ├─ load_active_strategy() → strategy.json; role.cta_mode overrides        :928-946
   ├─ assert_campaign_reference(configuration, strategy_version)             :952
   ├─ select_audience(...) → AudienceSelection                               :1096
   ├─ build_research_request(...) → source directives from the signal's own
   │  SOURCE_URL                                                             :1176
   ├─ ExaResearchAdapter → execute_and_persist_research                      :1240
   │     assess_artifact(...) [LLM · model_enrich, per claim]
   │     research gate: READY, named assessor, every record explained        :156-174 (lifecycle)
   │  → run_dir/research.json
   ├─ decision policy: role.decision_policy == "role_bounded_r1"             :1284
   │     → decision_policy.json written, reloaded, identity-verified;
   │       THE DECISION LENS IS NOT CONSULTED ON A MONDAY RUN               :1333-1339
   ├─ require_source_transparency → render_sources_of_record appended to
   │  both role renderings                                                   :1862
   │
   ├─ generate_article(...)  src/editorial/pipeline.py                       :1882
   │     pattern_extractor        [LLM] inline prompt · no configuration
   │     decision_lens_lite       [LLM] inline prompt · typed strategy ✔
   │     narrative_spine          [LLM] inline prompt · no configuration
   │     hook_engine              [LLM] inline prompt · no configuration
   │     reader_context           [LLM] inline prompt · no configuration
   │                                    (skipped for eight household names)
   │     discovery_builder        [LLM] inline prompt · no configuration
   │     story_assembly           [LLM] inline prompt · no configuration
   │     never_blank_voice        [LLM] inline prompt · brand_editorial ✔ · CTA ✔
   │     platform_composer long   [LLM] inline prompt · wix rules ✔ · role ✔
   │     platform_composer medium [LLM] inline prompt · linkedin rules ✔ · role ✔
   │                              (only "long" and "medium" — _R1_COMPOSER_FORMATS :508)
   │
   ├─ blog_body = platforms["long"]["body"]   ← the published Wix prose      :1908
   ├─ linkedin_text = platforms["medium"]["body"]                            :1909
   ├─ run_editorial_acceptance(rubric=editorial_acceptance/never_blank.yaml) :2009
   │     reviewer [LLM] system = rubric.instructions                   rubric ✔
   │     reviser  [LLM] system = rubric.revision_instructions          rubric ✔
   │                                            role ✗ · voice ✗ · channel ✗
   ├─ if revised → recompose_platform("medium", role rules, linkedin rules)  :2151
   ├─ validate_source_transparency(...)                                      :2288
   ├─ image pipeline → visual_system.yaml + prompts/image_generation.yaml
   └─ preflight → Wix → LinkedIn → run_report.json
        then the workflow appends the SIGNAL_ID to published_signal_ids.txt  :285
```

Eleven of the modules that make a model call on this path take their system
prompt from a Python string constant. Exactly two writing calls — the acceptance
reviewer and the reviser — take theirs from a file
(`config/prompts/editorial_acceptance/never_blank.yaml:50,77`), plus the image
prompt from `config/prompts/image_generation.yaml`. No stage on the Monday path
opens a Markdown file, and **no loader in the repository can read Markdown as
configuration**: `load_yaml`/`load_prompt` read YAML
(`src/utils/config_loader.py:11,38`), `load_business_strategy_configuration`
reads JSON only (`src/strategy/business_config.py:272-313`), and the only `.md`
paths in `src/` and `scripts/` are files being *written* or archived
(`src/strategy/history.py:48,88`).

---

## 2. Stage-by-stage classification

Each stage is classified on the seven axes the issue names. "Config received at
runtime" means values that reach the model message or a control decision, proven
by reading the call site — not values that merely exist.

### 2.1 `due_check.py` — scheduling window
- **Generic mechanism:** day/timezone/cron-firing arbitration; writes a decision artifact.
- **Product semantics:** none. Guarded by `tests/test_monday_stream.py:562-575`, which fails if the module learns any day logic.
- **Hard-coded prompt semantics:** none (no model call).
- **Config received:** `--day`, `--time`, `--timezone`, `--role` from the workflow.
- **Dead/duplicated:** `config/schedule.yaml` exists and this path does not read it.
- **State/data:** `reports/scheduling/monday_scheduling_decision.json`, written on every path including skips.
- **Tests:** `tests/test_monday_stream.py:505-534` — real firing arbitration, not a mock.

### 2.2 `select_eligible_signal.py` — candidate loading and selection
- **Generic mechanism:** walk an unused queue, ask a role-supplied judgment per candidate, stop at the first eligible one, write an audit, fail closed with distinct exit codes.
- **Product semantics:** the 15-candidate ceiling (`:63,69`) and the oldest-first queue order (`:72-88`) are together a selection semantic — see §7.
- **Hard-coded prompt semantics:** `src/editorial/source_eligibility.py:53-69` — "uncertainty is ineligibility", "judge only from the material shown"; and `:39-51`, the eleven signal fields the judgment is allowed to see.
- **Config received:** `role.eligibility_criteria` verbatim (`source_eligibility.py:301-312`). This is the one place a Monday product rule reaches a model from configuration with nothing added.
- **Dead/duplicated:** none; but `config/prompts/research/signal_selector.yaml` admits signals this role must refuse (#237 §5), so supply and role disagree by construction.
- **State/data:** reads `data/research/signals_active.jsonl` and `data/research/published_signal_ids.txt`; writes `reports/stream_selection/monday_selection.json`. **Rejections are never recorded** (`:32-34`).
- **Tests:** `tests/test_monday_stream.py:805-977` — scripted transport, real dispositions, real exit codes. Genuinely runtime-proving for the selector.

### 2.3 Research retrieval and evidence assessment
- **Generic mechanism:** build directives from the signal's own `SOURCE_URL` (`src/research/lifecycle.py:114-127`), retrieve, assess, gate on READY with a named assessor and a stated reason per record (`:156-174`).
- **Product semantics:** none Monday-specific. Provider choice is scope, not editorial.
- **Hard-coded prompt semantics:** `src/research/assessment.py:77` — `JUDGMENT_INSTRUCTIONS`, the soundness rubric, as a Python constant.
- **Config received:** `ResearchStrategyView` identity only; no editorial text.
- **Dead/duplicated:** none.
- **State/data:** create-once `run_dir/research.json`.
- **Tests:** research-gate tests exist and exercise the real gate.

### 2.4 Decision policy
- **Generic mechanism:** a typed, create-once, reload-and-verify authority record.
- **Product semantics:** that Monday *skips the Decision Lens* is a product decision, and it lives in configuration (`business_strategy.json:393`) — correctly.
- **Hard-coded prompt semantics:** none.
- **Config received:** `role.decision_policy`.
- **Dead/duplicated:** **`config/prompts/decision_lens/never_blank.yaml` is not consumed on a Monday run** — see §5.
- **State/data:** `run_dir/decision_policy.json`.
- **Tests:** exercised through the entrypoint.

### 2.5 `pattern_extractor` — mandatory gate
- **Generic mechanism:** one model call, strict field validation, typed rejection.
- **Product semantics:** heavy. "Never Blank produces articles for small business owners — not about corporations" (`:34`); the central question and the forbidden question (`:38-40`); nine `signal_fit` rejection conditions (`:89-100`) — a **second eligibility gate** with criteria different from the role's; and `article_protagonist` forced to `"owner"` in prompt (`:85-87,103`) *and* validator (`:146-150`).
- **Hard-coded prompt semantics:** the entire 89-line `_SYSTEM_PROMPT`.
- **Config received:** **none.** The stage is called with the signal alone (`pipeline.py:133`).
- **Dead/duplicated:** its owner-protagonist rule duplicates, more strictly, what `editorial_roles[0].structure` already says.
- **State/data:** merged into `enriched` and carried to every later stage (`pipeline.py:139`).
- **Tests:** unit tests on the validator; nothing asserts that any configured value reaches this prompt, because none does.

### 2.6 `decision_lens_lite`
- **Generic mechanism:** one call, six required string fields.
- **Product semantics:** the analytical frame — what `core_pattern`, `owner_system_objective` and three legacy compatibility keys are required to mean (`:44-88`).
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:30-97`).
- **Config received:** **yes** — positioning, audience, proof points, preferred/prohibited claims, restrictions, content objectives and territories, plus the normalized evidence boundary (`:148-163`).
- **Dead/duplicated:** the three "LEGACY COMPATIBILITY KEY" fields carry prose explaining that their names no longer mean what they say.
- **State/data:** in-memory only.
- **Tests:** `tests/strategy/test_strategy_semantic_consumption.py` proves configured values reach this prompt.

### 2.7 `narrative_spine`
- **Generic mechanism:** one call, four fields, one closed enum.
- **Product semantics:** `_VALID_FEELINGS` (`:20`) is a closed editorial vocabulary; the spine quality bar and its three worked examples (`:38-51`).
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:22-69`).
- **Config received:** none. A legacy campaign block appears only when a non-canonical caller set `STRATEGY_PRIMARY_MESSAGE` (`:105-112`); the canonical Monday path does not.
- **Dead/duplicated:** that legacy branch is dead on the Monday path.
- **State/data:** in-memory; emits two backward-compat aliases (`:90-92`).
- **Tests:** validator only.

### 2.8 `hook_engine`
- **Generic mechanism:** generate-N-then-select, with the selection required to match a candidate exactly (`:104-107`).
- **Product semantics:** `_MIN_CANDIDATES = 5` (`:19`); the six-member `_HOOK_TYPES` taxonomy (`:21-28`) enforced as a hard failure; five selection rules and four forbidden hook patterns (`:59-71`).
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:30-78`), including the "research-driven observer" identity hand-copied from `config/brand_voice.md`.
- **Config received:** none.
- **Dead/duplicated:** the forbidden openings duplicate `brand_voice.md:214-250` partially and `business_strategy.json:159` ("never a generic topic introduction or question") exactly in intent.
- **State/data:** in-memory.
- **Tests:** validator only.

### 2.9 `reader_context`
- **Generic mechanism:** a deterministic skip check, one call, one length validator.
- **Product semantics:** `_HOUSEHOLD_NAMES` (`:20-22`) — eight companies the product asserts need no explanation; and the length rule.
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:26-49`).
- **Config received:** none.
- **Dead/duplicated:** **the prompt says "Maximum 20 words" (`:34,38`) and the validator rejects only above 25 (`:24,100-103`)** — one rule at two values inside one file.
- **State/data:** in-memory; `None` is a legitimate result.
- **Tests:** validator only.

### 2.10 `discovery_builder`
- **Generic mechanism:** one call, bounded list, deterministic phrase rejection.
- **Product semantics:** 2–4 beats (`:13-14`); the four required field meanings; a list of banned first-person constructions enforced in Python (`:67-74`) and restated, **not identically**, in the prompt (`:42-44`) — the validator also rejects "I thought maybe", which the prompt never mentions.
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:16-64`).
- **Config received:** none.
- **Dead/duplicated:** the detective ban exists three times — here, in the composer prompt (`platform_composer.py:129-130`) and in `src/content/output_guard.py:14-21`, at three different strictnesses.
- **State/data:** in-memory.
- **Tests:** validator only.

### 2.11 `story_assembly`
- **Generic mechanism:** three spec modules merged into one call to avoid regeneration with no value (`:5-8`).
- **Product semantics:** the arc steps 5–7 and their contracts; "Banned pattern: 'If your goal is X, then Y'" (`:70`); the "paste it under a different article" genericity test (`:67-69`).
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:23-85`).
- **Config received:** none.
- **Dead/duplicated:** its arc is one of four arcs in the repository — see §8.
- **State/data:** in-memory.
- **Tests:** validator only.

### 2.12 `never_blank_voice`
- **Generic mechanism:** candidate generation, optional outputs, an exact-phrase prohibited-claim check against configuration (`:226-230`).
- **Product semantics:** what the Echo is and is not, with three register examples (`:36-59`); the five CTA modes restated in prose and six forbidden CTA phrases (`:61-76`); an eleven-item self-check including "corporate evidence does not occupy more than 20-25% of the article" (`:78-96`).
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:29-104`).
- **Config received:** **yes** — voice, principles, preferred/prohibited claims, restrictions, the selected CTA's intent and rules (`:130-146`).
- **Dead/duplicated:** the CTA prose at `:61-76` is a second, hand-written copy of `business_strategy.json:188-232`, which the same call already receives as data.
- **State/data:** produces `structured_article`, the contract every later stage consumes.
- **Tests:** `tests/strategy/test_strategy_semantic_consumption.py:90-128` — a real call capture, including that changing the CTA mode changes the prompt.
- **Note:** `checklist_pass=False` only logs a warning (`:184-190`). Nothing gates on it.

### 2.13 `platform_composer`
- **Generic mechanism:** per-format block policy, per-format prompt assembly, deterministic closing-contract validators (`:257-367`), per-format model routing (`:509`).
- **Product semantics:** `_BLOCK_TABLE` (`:21-47`); `_WORD_RANGE` (`:52-55`); `_FORMAT_CONSTRAINTS` (`:77-112`); the production arc (`:121-122`); the detective and company-opening bans (`:129-133`); `BRAND_ATTRIBUTION = "Never Blank"` (`:181`).
- **Hard-coded prompt semantics:** `_SYSTEM_PROMPT` (`:114-148`) plus every constraint string above.
- **Config received:** **yes, the most of any stage** — channel rule groups (`:434-439`, via `_wix_rules`/`_linkedin_rules` at `:571-593`) and the rendered role, per surface (`:492-495`).
- **Dead/duplicated:** `_FORMAT_CONSTRAINTS["long"]` restates `channels.wix.article_rules` — at 20 % corporate evidence where the voice stage says 20–25 %, and at a word range that three other authorities contradict (§8). `channels.*.visual_rules` are the only rule group `_wix_rules`/`_linkedin_rules` omit.
- **State/data:** returns bodies; `long.title` becomes the published headline (`generate_and_publish.py:1914-1917`).
- **Tests:** `tests/test_monday_stream.py:250-263` captures the real call and proves the role reaches exactly the two published surfaces. `tests/test_monday_echo_contract.py` exercises the closing-contract validators against real bodies. These are the strongest runtime proofs on the path.

### 2.14 Editorial acceptance — reviewer and reviser
- **Generic mechanism:** load a strict rubric, verify its identity against the role's declared identity (`generate_and_publish.py:2000-2008`), one review, at most one revision, one recheck; persist the verdict on every outcome.
- **Product semantics:** the nine criteria and both instruction blocks — correctly in a file (`config/prompts/editorial_acceptance/never_blank.yaml:11-89`).
- **Hard-coded prompt semantics:** none. This stage is the model the rest of the path should follow.
- **Config received:** the rubric. **Not** the role, the voice or the channel rules — #234 V5, re-verified at `generate_and_publish.py:2009-2032`.
- **Dead/duplicated:** the rubric's `voice` criterion says "the configured brand voice" to a reviewer that was never shown it.
- **State/data:** `run_dir/editorial_acceptance.json`.
- **Tests:** acceptance tests exercise the real rubric.

### 2.15 Composition acceptance, transparency, packaging, publication
- **Generic mechanism:** LinkedIn composition record and length gate (`src/editorial/linkedin_composition.py`), source-transparency verification against the run's real sources (`generate_and_publish.py:2288`), preflight, Wix, LinkedIn, run report.
- **Product semantics:** `LINKEDIN_MIN_WORDS`/`LINKEDIN_MAX_WORDS` (72–308, derived at `:49-51`); hashtag rules (`src/publishing/hashtags.py:27-47`); source-footer renderings (`src/publishing/formatting.py:72-88`).
- **Hard-coded prompt semantics:** none (deterministic).
- **Config received:** channel credentials and scope; no editorial text.
- **Dead/duplicated:** the branded hashtag trio (`hashtags.py:35`) and `brand_voice.md:198-201` disagree — and here the code looks right and the document looks stale (§8.5).
- **State/data:** `publication_results.json`, `strategy/published_content_index.jsonl`, `data/research/published_signal_ids.txt`.
- **Tests:** `tests/test_r1_publish_scope.py` pins the authorized channel set; `tests/test_monday_stream.py:395-423` pins Monday's publishers and its sole ownership of the day.

---

## 3. Product semantics currently hard-coded in Python

The issue's required shape. "Destination" names the file in the proposed
structure (target document §7); it is a proposal, not a decision, and the rows
marked ⚠ carry a conflict that must be ruled on before anything moves.

| Path | Function / class | Exact behaviour | Why it is product semantics | Proposed destination |
|---|---|---|---|---|
| `src/editorial/pattern_extractor.py:34-42` | `_SYSTEM_PROMPT` | "Never Blank produces articles for small business owners — not about corporations"; the central question is fixed and the alternative is "forbidden here" | Declares the reader and the subject of every article | `monday.md` → Audience, Editorial objective |
| `src/editorial/pattern_extractor.py:85-87,103,146-150` | `_SYSTEM_PROMPT`, `_validate` | `article_protagonist` must equal `"owner"`; any other value raises and fails the run | A product claim enforced as a code invariant in a stage shared by every role | `monday.md` → Editorial objective, as a role value a generic validator enforces |
| `src/editorial/pattern_extractor.py:89-100` | `_SYSTEM_PROMPT` | five `signal_fit = reject` conditions, incl. "only relevant to large-company strategy" | A second eligibility gate, with criteria neither equal to nor derived from the role's | ⚠ `monday.md` → What makes a signal useful — **after D1** |
| `src/editorial/source_eligibility.py:39-51` | `_SOURCE_FIELDS` | exactly eleven signal fields are shown to the eligibility judgment | Decides what evidence the product's own gate may see | `monday.md` → What makes a signal useful |
| `src/editorial/source_eligibility.py:53-69` | `_INSTRUCTIONS` | "Uncertainty is ineligibility"; judge only from material shown; never infer scale or ownership | A fail-closed posture that is simultaneously an editorial policy | `never_blank.md` → Evidence requirements |
| `src/research/assessment.py:77` | `JUDGMENT_INSTRUCTIONS` | the soundness rubric for whether an excerpt supports its claim | Evidence policy | `never_blank.md` → Evidence requirements |
| `src/editorial/decision_lens_lite.py:44-88` | `_SYSTEM_PROMPT` | six named outputs, three of them "LEGACY COMPATIBILITY KEY"s whose documented meaning differs from their name | The analytical frame every later stage inherits | `monday.md` → How the article reasons |
| `src/editorial/narrative_spine.py:20` | `_VALID_FEELINGS` | five permitted target feelings; anything else fails the stage | Closed editorial vocabulary | `monday.md` → Article structure (vocabulary) |
| `src/editorial/narrative_spine.py:38-51` | `_SYSTEM_PROMPT` | the spine must "work for any small business owner", must be "specific enough to be wrong", three worked examples | Editorial register and quality bar | `never_blank.md` → Writing requirements |
| `src/editorial/hook_engine.py:19,21-28` | `_MIN_CANDIDATES`, `_HOOK_TYPES` | at least five candidates; type must be one of six named kinds | Editorial taxonomy and a numeric rule | `monday.md` → Hook rules |
| `src/editorial/hook_engine.py:59-71` | `_SYSTEM_PROMPT` | five selection rules; four forbidden openings ("In today's…", a question, the conclusion, "Here's what research shows") | Editorial prohibitions | `never_blank.md` → Never do |
| `src/editorial/reader_context.py:20-22` | `_HOUSEHOLD_NAMES` | eight companies skip the stage entirely | A product judgment about what the reader already knows | `monday.md` → Article structure; the list becomes data |
| `src/editorial/reader_context.py:24,34` | `_MAX_WORDS`, `_SYSTEM_PROMPT` | prompt says max 20 words, validator rejects above 25 | ⚠ One editorial rule at two values in one file | `monday.md` → Article structure — **one value** |
| `src/editorial/discovery_builder.py:13-14` | `_MIN_SEQUENCE`, `_MAX_SEQUENCE` | two to four investigation beats | Numeric editorial rule | `monday.md` → Article structure |
| `src/editorial/discovery_builder.py:42-44,67-74` | `_SYSTEM_PROMPT`, `_contains_detective_template` | banned first-person constructions, enforced deterministically; the validator's list is one entry longer than the prompt's | Phrase-level editorial ban, already maintained twice at two values inside one file | `never_blank.md` → Never do |
| `src/editorial/story_assembly.py:32-70` | `_SYSTEM_PROMPT` | the Explanation → Reframe → Business Translation arc; "Banned pattern: 'If your goal is X, then Y'"; the "would it paste under another article" test; the enumerated commercial consequences the translation may reach for (`:60-62`) | The article's argumentative shape, and its vocabulary of outcomes | ⚠ `monday.md` → Article structure — **after D4** |
| `src/editorial/never_blank_voice.py:36-59` | `_SYSTEM_PROMPT` | 3–5 Echo candidates; four things the Echo is not, five it is; three register examples | The brand's signature device | `never_blank.md` → The Echo |
| `src/editorial/never_blank_voice.py:61-76` | `_SYSTEM_PROMPT` | the five CTA modes restated in prose plus six forbidden CTA phrases | A hand-written second copy of `calls_to_action`, which the same call already receives as data | `never_blank.md` → Calls to action (single owner) |
| `src/editorial/never_blank_voice.py:78-96` | `_SYSTEM_PROMPT` | eleven self-check items, incl. corporate evidence ≤ 20–25 % | ⚠ Acceptance criteria stated in a prompt and enforced nowhere | `never_blank.md` → Evidence requirements — **after D5** |
| `src/editorial/never_blank_voice.py:184-190` | `finalize_article` | `checklist_pass=False` logs a warning and the run continues | A declared quality bar with no gate behind it | engine: gate it or drop it — **D6** |
| `src/editorial/platform_composer.py:21-47` | `_BLOCK_TABLE` | which of ten blocks each of five surfaces renders full / compressed / skip / adapt | Per-surface editorial shape | `channels.md` → block policy |
| `src/editorial/platform_composer.py:52-55` | `_WORD_RANGE` | long 400–600, medium 120–220, enforced at 0.6×/1.4× tolerance | ⚠ Numeric editorial rule with three competing authorities | `channels.md` → Length — **after D2/D3** |
| `src/editorial/platform_composer.py:77-112` | `_FORMAT_CONSTRAINTS` | per-format prose rules, incl. "corporate evidence … at most 20 percent" and the H1 contract | Restates `channels.wix.article_rules` at a different value | `channels.md` |
| `src/editorial/platform_composer.py:121-122` | `_SYSTEM_PROMPT` | the production arc: Hook → Recognition → Tension → Market Observation → Investigation → Mechanism → Business Consequence → Reframe → Echo → Soft CTA | ⚠ The article's canonical shape; a fourth arc in the repository | `monday.md` → Article structure — **after D4** |
| `src/editorial/platform_composer.py:129-133` | `_SYSTEM_PROMPT` | detective-template ban; never open with a company, headline, source or dictionary-style description | Editorial prohibitions | `never_blank.md` → Never do |
| `src/editorial/platform_composer.py:181` | `BRAND_ATTRIBUTION` | the literal string `"Never Blank"` the Echo validators require | Brand identity as a code constant | `never_blank.md` front matter |
| `src/content/output_guard.py:14-31` | `_DETECTIVE_PATTERNS`, `_DICTIONARY_OPENING_PATTERNS` | six regexes (two hits fail the composition); three dictionary-opening shapes fail it outright | Phrase-level editorial bans compiled into regex | `never_blank.md` → Never do, compiled by the engine |
| `src/content/output_guard.py:81-94` | `validate_no_duplicate_echo` | a repeated long sentence, or ≥0.55 token overlap between the last two, fails | Numeric editorial rule | `never_blank.md` → The Echo |
| `src/publishing/hashtags.py:27-47` | `_COUNT_RANGE`, `BRANDED_HASHTAGS`, `PROHIBITED_HASHTAGS`, `_STOPWORDS` | three fixed branded tags always first; 3–6 tags on LinkedIn; two prohibited tags; a stopword list | ⚠ Channel brand rules; `brand_voice.md:200-205` contradicts the trio, the count and the prohibition list | `channels.md` → LinkedIn — **after D7** |
| `src/publishing/formatting.py:72-88` | `source_line` | three source-footer renderings keyed by a style string | Channel presentation rule | `channels.md` |
| `src/editorial/linkedin_composition.py:49-51` | `LINKEDIN_MIN_WORDS`, `LINKEDIN_MAX_WORDS` | a LinkedIn body outside 72–308 words fails the run closed | Numeric editorial rule, derived from the composer's table | `channels.md` → LinkedIn length |
| `scripts/generate_and_publish.py:508` | `_R1_COMPOSER_FORMATS` | only `long` and `medium` are composed | Release scope — which channels are live | `channels.md` → active channels |
| `scripts/streams/select_eligible_signal.py:63,69` | `DEFAULT_MAX_CANDIDATES`, `MAX_CANDIDATES_CEILING` | at most 15 candidates per sweep; a larger value is refused before the queue is read | A cost bound that has become a selection semantic (§7) | operational bound, not strategy — **D8** |

---

## 4. Strategy and configuration Monday actually consumes

"Consumes" means the content reaches a `system`/`user` string handed to
`src.utils.llm_client.chat`, or a control decision, on the Monday path.

| Artifact | Loader | What of it reaches a prompt or a decision |
|---|---|---|
| `strategy/current/business_strategy.json` | `src/strategy/business_config.py:272` | See the dependency map in §6 |
| `strategy/current/strategy.json` | `src/strategy/loader.py:22` | `strategy_id`, `strategy_version`, `cta_mode` (then overridden by the role); the version is equality-checked against `prompt_rule_references` |
| `config/prompts/editorial_acceptance/never_blank.yaml` | `EditorialAcceptanceRubric.load` (`src/editorial/editorial_acceptance.py:46-52`) | Criteria, `instructions` → reviewer system prompt, `revision_instructions` → reviser system prompt; identity verified against the role |
| `config/visual_system.yaml` | `src/publishing/image_pipeline.py:42` | Brand and rhythm rules for the cover asset |
| `config/prompts/image_generation.yaml` | `src/publishing/image_pipeline.py:43` | Image prompt and style suffix |
| `data/research/signals_active.jsonl` | `select_eligible_signal.py:72-88` | The candidate queue |
| `data/research/published_signal_ids.txt` | same, and the workflow at `:285` | The consumption marker |

Supply-side configuration decides what Monday can ever select, even though the
Monday workflow never opens it: `config/research_sources.yaml`,
`config/scoring_weights.yaml` and `config/prompts/research/*.yaml` — in
particular `signal_selector.yaml`, whose admission criteria are not Monday's
(§7.4). Any Monday strategy that says what a useful signal is has to reach this
path or be knowingly disconnected from it.

---

## 5. Apparently authoritative Monday-relevant files Monday does NOT consume

| Artifact | What makes it look authoritative | Actual consumer |
|---|---|---|
| `config/brand_voice.md` (330 lines) | Declared at `business_strategy.json:313-316` as prompt rule `brand-voice`, versioned `r1-2026-08-13`; contains the Echo rules, hook rules, CTA form, ~36 auto-fail phrases | **None.** Fragments were hand-copied into `narrative_spine` and `hook_engine` once and have drifted since (#234 §4) |
| `strategy/methodology/strategy_methodology.md` | Declared at `:322-326` | **None** |
| `strategy/methodology/editorial_strategy.md` | Declared at `:327-331` | **None** |
| `strategy/methodology/platform_strategy.md` | Declared at `:332-336`; states a 600–1200-word blog | **None** |
| `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | Declared at `:337-341`; states a 700–1000-word blog and a 350–600-word LinkedIn post | **None** |
| `config/brand.yaml` | Declared at `:307-311` as `brand-identity` | Only `src/quality/{voice,rewrite}.py` and `src/internal/strategy.py`, none of which the Monday path imports |
| `strategy/methodology/evaluation_rules.md` | Sits beside three declared siblings | **None**, and not declared either (#233 §5) |
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md` | Names the `Signal → Tension → Response → Outcome → Lesson` frame | **None today.** Was injected verbatim into the article prompt until `2466611` (2026-07-03) |
| `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md` | Describes itself as the document all prompts and rubrics follow from | **None**, and not referenced by any configuration |
| `strategy/worldview.md` | Same self-description, in Russian, citing decision 12 of `strategy/decision_log.md` | **None** |
| `strategy/current/strategy.md` | Sits beside the `strategy.json` the run loads | Read only to be copied into `strategy/history/` (`src/strategy/history.py:48,88`) |
| `config/prompts/decision_lens/never_blank.yaml` | The Decision Lens rubric; the entrypoint calls the Lens verdict "the mandatory business gate" (`generate_and_publish.py:1342-1344`) | **Not on a Monday run** — `decision_policy: role_bounded_r1` (`business_strategy.json:393`) takes the branch at `generate_and_publish.py:1284` instead |
| `config/prompts/blog_post.yaml`, `linkedin_post.yaml` | Named as the blog and LinkedIn prompts, incl. by `docs/SYSTEM_MAP.md:30` | Legacy generator only; `linkedin_post.yaml` does not parse |
| `channels.wix.visual_rules` (`:264-268`), `channels.linkedin.visual_rules` (`:299-303`) | Validated by a strict contract, hashed into the configuration identity, carried across a typed boundary | **Nothing reads them.** `_wix_rules`/`_linkedin_rules` (`platform_composer.py:571-593`) omit exactly this group, and the visual boundary reads only `identity` (`src/visual/__init__.py:50-66`) |
| `config/schedule.yaml` | Names the publishing cadence | Not read by `due_check.py`; the Monday times are workflow env values (`monday_publish.yml:96-97`) |

Six of the seven declared `prompt_rule_references` are in this table. The
seventh, `active-campaign-strategy`, is consumed as a version string only. The
only test that mentions any of them asserts the file exists
(`tests/strategy/test_never_blank_business_config.py:80-86`).

---

## 6. `business_strategy.json` dependency map

Every Monday dependency, classified as the issue requires. **The file is not
modified and not deleted by this report.** "Machine/runtime data" means a value
the engine needs to execute; "human product strategy" means text a
non-programmer would want to edit; "unresolved" means its status cannot be
settled without an owner.

| Block (lines) | Monday consumer | Classification |
|---|---|---|
| `schema_version`, `configuration_id`, `configuration_version`, `status` (2-5) | loader, identity hash, `EditorialRoleIdentity` | Machine/runtime data |
| `business` (6-10) | validated; not read into any prompt | Unresolved — human material with no consumer |
| `products_services` (11-22) | validated only | Unresolved — same |
| `default_audience_id`, `audiences` (23-104) | `select_audience` → `decision_lens_lite` prompt (`:150-153`) | Human product strategy (audience), with `audience_id`/`selection_terms` as machine data |
| `positioning` (105-125) | `statement` and `proof_points` → `decision_lens_lite` (`:151,154`) | Human product strategy |
| `commercial` (126-133) | none | Unresolved — no consumer |
| `content.objectives`, `content.territories` (134-148) | → `decision_lens_lite` (`:159-160`) | Human product strategy |
| `brand_editorial` (149-187) | all five lists → `never_blank_voice` (`:138-142`); `prohibited_claims` also exact-match enforced (`:226-230`) | Human product strategy — **shared**, not Monday's |
| `calls_to_action` (188-232) | the selected CTA's `intent` and `rules` → `never_blank_voice` (`:143-144`) | Human product strategy; **duplicated by hand** in `never_blank_voice.py:61-76` |
| `channels.wix.{article,metadata,link,cta}_rules` (235-263) | → composer `long` (`platform_composer.py:571-580`, `:434-439`) | Human product strategy (channel) |
| `channels.wix.visual_rules` (264-268) | **none** | Human product strategy that is currently inert |
| `channels.linkedin.{opening,length,formatting,link,cta}_rules` (270-298) | → composer `medium` (`:583-593`) | Human product strategy (channel) |
| `channels.linkedin.visual_rules` (299-303) | **none** | Same as above |
| `prompt_rule_references` (306-342) | `assert_campaign_reference` reads one `version` (`execution_context.py:296-315`) | Obsolete as declared — six entries claim an authority the runtime does not grant |
| `editorial_roles[0].role_id` (345) | role resolution, run records, decision-policy record | Machine/runtime data |
| `editorial_roles[0].intent` (346) | → both composer surfaces (`editorial_role.py:96`) | Human product strategy |
| `editorial_roles[0].structure` (347-358) | → both composer surfaces (`:100`) | Human product strategy — the largest single block of Monday editorial meaning in the file |
| `editorial_roles[0].forbidden` (359-373) | → both composer surfaces (`:103`) | Human product strategy |
| `editorial_roles[0].eligibility_criteria` (374-380) | → the selector's judgment verbatim (`source_eligibility.py:303`) | **Superseded** — the issue supersedes the narrow documented-small-business contract; what replaces it is **D1** |
| `editorial_roles[0].wix_rules` (381-385) | → composer `long` only (`:104-110`) | Human product strategy |
| `editorial_roles[0].linkedin_rules` (386-391) | → composer `medium` only | Human product strategy |
| `editorial_roles[0].require_source_transparency` (392) | appends the sources block and arms the transparency gate (`generate_and_publish.py:1862,2288`) | Machine/runtime data (a switch over generic mechanics) |
| `editorial_roles[0].decision_policy` (393) | selects the branch at `generate_and_publish.py:1284` | Machine/runtime data expressing a product decision — see **D9** |
| `editorial_roles[0].cta_mode` (394) | overrides the campaign CTA (`:940-946`) | Human product strategy, one enumerated value |
| `editorial_roles[0].closing_contract` (395) | selects the branded-echo validators (`platform_composer.py:317-333`) | Machine/runtime data naming a product shape |
| `editorial_roles[0]` — absent `acceptance_rubric_path`/`_identity` | Monday falls back to `DEFAULT_RUBRIC_PATH` (`editorial_acceptance.py:46-52`) | Unresolved — Monday's rubric is a default, not a declaration, while Wednesday's is declared (`:442-443`) |
| `editorial_roles[1]` (397-445) | Wednesday | Out of scope; loaded and validated on every Monday run |

Summary: of the seventeen top-level blocks, **eight are human product strategy
that the owner contract says belongs in Markdown**, five are genuine
machine/runtime data, one is superseded, one is obsolete as declared, and three
have no consumer at all. Nothing in the file is a duplicate *of another JSON
file*; the duplication is against Python (`calls_to_action`,
`channels.wix.article_rules`) and against Markdown (§8).

---

## 7. The narrow eligibility contract and the 15-candidate mechanism

The issue supersedes the `documented small-business case` contract and forbids
preserving or redesigning the 15-candidate mechanism around it. This section
records what exists and every dependency on it, so that removing the contract is
a deliberate act rather than a discovery mid-migration.

### 7.1 Where the narrow contract is written
`business_strategy.json:374-380`, five criteria: eligible is a documented case
about a small, owner-led, founder-led or early-stage business; a large company
qualifies only for an episode from when it was small; ineligible are current
large-company behaviour, connection by analogy only, and — decisively —
*"any case whose business scale, stage, or ownership the available material does
not establish. Unknown is ineligible."*

### 7.2 Every dependency on it

| Dependency | Where | What breaks if the criteria change |
|---|---|---|
| The selector's judgment | `select_eligible_signal.py:148` → `source_eligibility.py:301-312` | Nothing structural — the criteria travel as opaque text. This is the one clean seam. |
| The role's `intent` | `business_strategy.json:346` | Says "a documented small-business, owner-led, or early-stage business story" and reaches **both composer prompts**. Changing eligibility without changing `intent` leaves the narrow contract governing the writing. |
| The role's `structure` | `:347-358` | "The Never Blank reading, only where the material earns it" and the one-mechanism rule are written for this source class. |
| The role's `forbidden` | `:359-373` | "A large-company outcome transferred … to smaller businesses" and "Analogy represented as evidence" are the eligibility criteria restated as writing prohibitions. |
| `pattern_extractor` | `pattern_extractor.py:34,89-100` | An independent second gate that rejects signals "only relevant to large-company strategy with no small-business mechanism", and forces the owner protagonist. **A widened eligibility contract does not widen this**, and a signal the new contract admits can still be refused here, mid-run, after research has been paid for. |
| `decision_lens_lite`, `narrative_spine`, `hook_engine`, `discovery_builder`, `story_assembly`, `never_blank_voice` | the `_SYSTEM_PROMPT` of each | Every one says "small business owner" or "small businesses" as a fixed fact. |
| Tests | `tests/test_monday_stream.py:266-294,805-851`, `tests/test_monday_echo_contract.py` | Assert the narrow contract's exact phrases. They pass today because the phrases exist; they will fail the moment the contract changes, which is correct — but they assert against configuration text, so they need to move with it. |

The eligibility criteria are the *only* dependency that is genuinely
configuration-driven. Every other one is prose — in JSON or in Python — that
restates the same narrow contract in a place the selector never reads.

### 7.3 The 15-candidate mechanism (#237)

`DEFAULT_MAX_CANDIDATES = MAX_CANDIDATES_CEILING = 15`
(`select_eligible_signal.py:63,69`) is a Release 1 cost bound from #171: one
model call per candidate, refused rather than clamped if a caller asks for more.
`_load_candidates` (`:72-88`) walks `signals_active.jsonl` in file order —
append order, oldest first — and **rejections are never recorded** (`:32-34`).
The three properties together are a standstill: the same 15-wide head is
re-judged every Monday, and #237 established that at that time 73 September
signals sat at positions 27–99, unreachable by any Monday. Run `34868092082`
(2026-09-14) ended at exit 5 for exactly this reason, with all fifteen judgments
completing.

Per the issue this mechanism is **not** to be redesigned around the superseded
contract. Two things follow for the architecture, and neither is a decision
taken here:

- Whatever replaces the eligibility contract changes *which* candidates are
  eligible, not *how far* the sweep reaches. A wider contract may make the head
  eligible again and mask the defect without fixing it.
- #237's options A (change selection order or persist rejections), B (operator
  unblock) and C (role-aware supply, #202) remain open and untaken. The target
  document carries this forward as **D8**.

### 7.4 Supply does not match the role
`config/prompts/research/signal_selector.yaml` admits mechanism, trend and data
signals and rejects listicles, trend roundups and generic AI news — it never
requires a documented specific small or owner-led business. #237 found 82 of 100
unused signals carrying `"REAL_COMPANY_EXAMPLE": null`, and most of the named
ones large. Whatever Monday's source guidance becomes, it has to reach this
prompt or be knowingly disconnected from it; today there is no mechanism by
which a Monday strategy change could reach the research path at all.

---

## 8. Where the authorities disagree

Compilation forces one winner per rule, so these have to be ruled on before any
migration. Each is re-verified here; none is decided.

1. **Blog length.** `platform_composer.py:52` and `business_strategy.json:237` say 400–600; `docs/PLATFORM_AND_VISUAL_STRATEGY.md` says 700–1000; `strategy/methodology/platform_strategy.md` says 600–1200. → **D2**
2. **LinkedIn length.** Code says 120–220 with a hard 72–308 envelope (`linkedin_composition.py:49-51`); `docs/PLATFORM_AND_VISUAL_STRATEGY.md` says 350–600. → **D3**
3. **The article arc — four of them.** `platform_composer.py:121-122` (`Hook → Recognition → Tension → Market Observation → Investigation → Mechanism → Business Consequence → Reframe → Echo → Soft CTA`); `story_assembly.py:32-70` (steps 5–7 of a nine-step arc); `business_strategy.json:347-358` (the role's ten structure items); and `docs/NEVER_BLANK_EDITORIAL_STYLE.md:51-76` (`Signal → What businesses are actually doing → Real company example → Outcome → Business lesson → Never Blank signature → Source`). → **D4**
4. **Corporate evidence share.** `never_blank_voice.py:86` says 20–25 %; `platform_composer.py:82` says at most 20 %. Neither is enforced — both are prompt text. → **D5**
5. **Hashtags.** `hashtags.py:35` emits a fixed branded trio; `config/brand_voice.md:200-201` says the set is explicitly *not* fixed, and `:203-205` blacklists sixteen tags where the code prohibits two (`hashtags.py:38`). The count disagrees too: `hashtags.py:28` allows 3–6 on LinkedIn, while `business_strategy.json:284` and `brand_voice.md:200` both say three to five. **Here the document looks stale on the trio and right on the count** — the opposite of rows 1–3, which is why the unit of ownership has to be the rule, not the file. → **D7**
6. **Forbidden phrases.** `config/brand_voice.md:214-250` lists roughly thirty-six auto-fail phrases. The only code that encodes any of them, `src/quality/voice.py`, is not imported anywhere on the Monday path.
7. **Reader context length.** 20 words in the prompt, 25 in the validator, one file (`reader_context.py:24,34`).
8. **The Decision Lens.** `scripts/generate_and_publish.py:1342-1344` calls its verdict "the mandatory business gate between research and all narrative/editorial/downstream work" — in the comment above the branch Monday never takes. Monday bypasses it by configuration (`business_strategy.json:393`), auditably, with #151 named as the reconciliation (`:1337-1338`). A gate described as mandatory that one of two live streams does not run is a contract stated in one place and answered in another. → **D9**
9. **The voice self-check** produces `checklist_pass`, which only warns (`never_blank_voice.py:184-190`). → **D6**
10. **The reviser** rewrites the published article under the rubric alone — no role, no voice, no channel rules (`generate_and_publish.py:2009-2032`). → **D10**

---

## 9. What the tests prove, and what they do not

| Test | Proves | Does not prove |
|---|---|---|
| `tests/test_monday_stream.py:250-263` | The rendered role reaches the real composer call, on exactly the two published surfaces | Anything about the eight upstream stages |
| `tests/test_monday_stream.py:203-214` | `generate_article` was *called with* `editorial_role_rules` | That any model saw them — `generate_article` is patched |
| `tests/test_monday_stream.py:562-575` | No engine module contains the word "monday" or branches on a weekday | That the modules contain no *product* semantics — they contain a great deal (§3) |
| `tests/test_monday_stream.py:578-586` | The role's distinctive phrases live in configuration, not code | That configuration is the *only* place they live — `pattern_extractor` states the same contract independently |
| `tests/test_monday_stream.py:805-977` | The real selector, real dispositions, real exit codes, real audit shape | Anything about the queue's ability to advance (§7.3) |
| `tests/test_monday_echo_contract.py` | The closing-contract validators against real bodies, including the exact live rejection that motivated them | — this is the strongest runtime-behaviour test on the path |
| `tests/strategy/test_strategy_semantic_consumption.py:90-128` | Seven configured values reach the real voice prompt, and changing the CTA mode changes it | Anything about the other ten writing calls |
| `tests/strategy/test_never_blank_business_config.py:80-86` | The seven declared reference paths exist | That anything opens them. This single assertion is why six unread documents pass as product rules |

The pattern is consistent: where a test captures a real model message, the wiring
it covers is genuinely sound. Where a test asserts existence or a handoff, the
wiring behind it has drifted or was never made. No test spans entrypoint →
every writing call's `(system, user)`, and #234 §6.4 names why a naive attempt
fails: each stage binds `chat` by name (`from src.utils.llm_client import chat`),
so patching `src.utils.llm_client.chat` intercepts nothing. Each stage module's
own namespace must be patched.

---

## 10. The finding

Monday's editorial strategy has three authorities that do not agree.

`editorial_roles[0]` in `business_strategy.json` holds about fifty lines of
product strategy as JSON — the interface the owner contract says must not be the
human interface, and the only one of the three that reaches the writing calls.
Eleven Python modules hold a second copy as prompt constants, closed
vocabularies, numeric bounds and phrase bans — including
`pattern_extractor`'s hard assertion that the protagonist is always `"owner"`,
which is the hardest-coded product decision on the path and the single thing
that makes a second stream inexpressible in the shared engine. A third copy sits
in Markdown that reads as authoritative — `config/brand_voice.md`,
`strategy/worldview.md`, `docs/NEVER_BLANK_EDITORIAL_*.md`,
`strategy/methodology/*.md` — and that **no code opens**; six of the seven
`prompt_rule_references` name files the runtime never reads.

Ten rules are currently maintained in two or more of those places at once, six
of them at different values (§8). A non-programmer editing the one interface
that looks authoritative — the Markdown — changes nothing at all.

The proposal is in
[`docs/monday-architecture/MONDAY_TARGET_ARCHITECTURE.md`](../../docs/monday-architecture/MONDAY_TARGET_ARCHITECTURE.md).
