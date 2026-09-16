# [R1][ARCH] Monday as the reference implementation: Markdown-authoritative strategy, compiler, generic engine — proposal only

Proposal for owner approval. **Nothing here is implemented.** Read-only inventory of the Monday path plus a proposed target architecture. Inputs: the audit in #233 and the wiring evidence in #234. Wednesday and Friday are paused and are not touched by this proposal.

## 1. What Monday's product semantics look like today

**Thirteen of the fifteen model calls on the Monday path take their system prompt from a Python string constant.** The two exceptions are the editorial reviewer and the reviser, which read `config/prompts/editorial_acceptance/never_blank.yaml`.

| Stage | Prompt source |
|---|---|
| Source eligibility | `src/editorial/source_eligibility.py:53` |
| Evidence assessment | `src/research/assessment.py:77` |
| Pattern Extractor | `src/editorial/pattern_extractor.py:32` |
| Decision Lens Lite | `src/editorial/decision_lens_lite.py:30` |
| Narrative Spine | `src/editorial/narrative_spine.py:22` |
| Hook Engine | `src/editorial/hook_engine.py:30` |
| Reader Context | `src/editorial/reader_context.py:26` |
| Discovery Builder | `src/editorial/discovery_builder.py:16` |
| Story Assembly | `src/editorial/story_assembly.py:23` |
| Never Blank Voice | `src/editorial/never_blank_voice.py:29` |
| Platform Composer (blog + LinkedIn) | `src/editorial/platform_composer.py:114` |
| Editorial review / revision | `config/prompts/editorial_acceptance/never_blank.yaml:50,77` |

**No loader in the repository can read Markdown as configuration.** `load_yaml` and `load_prompt` (`src/utils/config_loader.py:11,38`) read YAML; `load_business_strategy_configuration` (`src/strategy/business_config.py:272`) reads JSON only; the acceptance rubric and Decision Lens loaders read YAML. Every `.md` read in Python is generated output, never configuration.

**`brand_voice.md` and the editorial docs are registered but never opened.** `strategy/current/business_strategy.json:312-341` lists `config/brand_voice.md`, `strategy/methodology/*.md` and `docs/PLATFORM_AND_VISUAL_STRATEGY.md` as `prompt_rule_references` with versions, and `src/strategy/business_config.py:187-191` validates only the id, path and version strings. The paths are never opened.

**What the owner can change today without editing Python:** only `business_strategy.json` values that reach three prompts — Decision Lens Lite (`decision_lens_lite.py:148-163`), Never Blank Voice (`never_blank_voice.py:135-146`) and Platform Composer channel plus role rules (`platform_composer.py:434-439,492-495`) — and the acceptance rubric YAML. Everything else is code.

## 2. Product semantics currently in Python (proposed for migration)

Grouped by what they actually are, with examples and file:line. Full inventory available; these are the classes.

1. **Editorial instructions for each stage.** The eleven system prompts above: what a pattern is, what a hook must do, what an Echo is, the article arc, what the composer may and may not write.
2. **Vocabularies and enumerations.** Hook types (`hook_engine.py:21-28`), narrative feelings (`narrative_spine.py:20`), CTA modes (`never_blank_voice.py:61-76`), block policy per format (`platform_composer.py:21-47`).
3. **Numeric editorial rules.** Word ranges per surface (`platform_composer.py:52-55`), hook candidate count (`hook_engine.py:19`), Echo candidates (`never_blank_voice.py:36`), discovery beats 2–4 (`discovery_builder.py:13-14`), reader context ≤25 words (`reader_context.py:24`), corporate evidence share (`never_blank_voice.py:88`, `platform_composer.py:82`), hashtag counts (`hashtags.py:27-32`).
4. **Forbidden-phrase lists.** Hook bans (`hook_engine.py:66-70`), detective narration (`discovery_builder.py:42-44`, `output_guard.py:14-21`), dictionary openings (`output_guard.py:25-31`), CTA bans (`never_blank_voice.py:72-76`), household-name skip list (`reader_context.py:20-22`).
5. **Channel and brand rules.** Branded hashtags (`hashtags.py:35`), prohibited hashtags (`hashtags.py:38`), stopwords (`hashtags.py:41`), attribution token (`platform_composer.py:181`), source footer styles (`formatting.py:72-80`).
6. **Selection rules.** Candidate cap 15 (`select_eligible_signal.py:63,69`), eligibility prompt (`source_eligibility.py:53`), which source fields the judgment may see (`source_eligibility.py:39-51`).
7. **Hard editorial assertions.** `article_protagonist` must always be `"owner"` (`pattern_extractor.py:85-87,146-150`) — a product claim enforced as a code invariant in a generic engine, the same class of defect recorded in #205.

## 3. Proposed target chain

```
config/strategy/**.md          human-authoritative, the only place an owner edits
        ↓  compiler (scripts/strategy/compile.py, deterministic, no model)
build/strategy/*.json          derived, generated, committed, never hand-edited
        ↓  loader (extends src/strategy/business_config.py)
runtime strategy objects       frozen, validated, identity-stamped
        ↓  generic engine capabilities
Monday result
```

**Design choices needing your approval:**

- **(a) Markdown structure.** Proposed: YAML front matter for identity and machine-critical values (`role_id`, versions, numeric bounds), and headed prose sections for everything editorial, where a heading is the contract (`## Structure`, `## Never do`, `## Eligibility`, `## Hook rules`). The compiler refuses unknown headings and missing required ones, so a typo fails the build rather than silently dropping a rule.
- **(b) One direction only.** Markdown is edited; JSON is generated. CI regenerates and fails if the committed JSON differs, so the two can never drift. No hand-maintained duplication, which is the rule you set.
- **(c) What stays in Python.** Proposed: only mechanism, never editorial meaning — how a prompt is assembled, deterministic validators, fail-closed gates, provenance, budgets as safety ceilings. The *values* those validators enforce come from the compiled strategy. So `platform_composer` keeps the validator; the 400–600 range moves to Markdown.
- **(d) Generic engine capabilities, not Monday code.** Each stage becomes "run this configured stage", with the stage's instructions, vocabulary, bounds and bans supplied by the role. Monday then *is* a strategy document plus the existing engine. Wednesday and Friday later become other documents against the same engine, which is why no Monday-specific engine may be built now. `pattern_extractor`'s owner-protagonist assertion is the test case: in a generic engine it must come from the role, not from the module.
- **(e) Prompt identity and versioning.** Every compiled stage instruction carries an id and version stamped into the run record, so a published article can be traced to the exact strategy text that produced it. This is how the acceptance rubric already works (`never_blank.yaml:8-9`).

## 4. Conflicts requiring your ruling before migration

Compilation forces one winner per rule. These are the collisions found; I am not choosing any of them.

1. **Blog length:** code and `business_strategy.json:237` say 400–600; `docs/PLATFORM_AND_VISUAL_STRATEGY.md:27` says 700–1000; `strategy/methodology/platform_strategy.md:30` says 600–1200.
2. **LinkedIn length:** code 120–220 (tolerance 72–308, `linkedin_composition.py:49-51`); `docs/PLATFORM_AND_VISUAL_STRATEGY.md:57` says 350–600.
3. **Article arc:** four different arcs — `platform_composer.py:121-122`, `config/brand_voice.md:262-265`, `docs/NEVER_BLANK_EDITORIAL_STYLE.md:48-60`, and the role structure at `business_strategy.json:347-358`.
4. **Corporate evidence share:** 20–25% (`never_blank_voice.py:88`) vs at most 20% (`platform_composer.py:82`); neither is enforced.
5. **Hashtags:** the code emits the fixed branded trio (`hashtags.py:35`), which matches your standing rule; `config/brand_voice.md:200-201` says "NOT a fixed reused set" and blacklists 16 tags where the code prohibits 2. **Here the document looks stale and the code looks right** — the opposite of the other rows, which is exactly why one source must win per rule rather than per file.
6. **Forbidden phrases:** `config/brand_voice.md:214-250` lists ~36 auto-fail phrases. The only code encoding them, `src/quality/voice.py:28-70`, is not imported anywhere on the Monday path.
7. **Decision Lens:** `docs/DECISION_LENS_CONTRACT.md` describes it as the mandatory gate; Monday bypasses it via `decision_policy: role_bounded_r1` (`business_strategy.json:393`).
8. **Reader context length:** prompt says max 20 words, validator allows 25 (`reader_context.py:24,38`).
9. **`visual_rules`** are declared (`business_strategy.json:264-268,299-303`) and never passed to the composer (`platform_composer.py:571-593`).
10. **Voice self-check** produces `checklist_pass`, which only logs a warning (`never_blank_voice.py:184-190`); no gate consumes it.

## 5. Proposed sequencing

Each step is a separate authorized task; none starts without your go-ahead.

1. **Rulings** on section 4, recorded in this issue.
2. **One vertical slice first:** Markdown → compiler → JSON → loader, for a single stage, with a CI drift check. Proposed slice: the Platform Composer's blog rules, because they are the rules that produce the published article and they carry three of the conflicts.
3. **Migrate the remaining stages** in order, one task each, no behavior change except where a ruling above changes it deliberately.
4. **Remove the `prompt_rule_references` metadata** once those documents are either compiled or reclassified as authoring material.
5. **Only then** Wednesday, as a second document against the same engine.

Related: #233 (audit), #234 (wiring evidence), #237 (Monday selection cannot reach past the queue head — a supply defect, not an architecture one), #238 (unmerged).

