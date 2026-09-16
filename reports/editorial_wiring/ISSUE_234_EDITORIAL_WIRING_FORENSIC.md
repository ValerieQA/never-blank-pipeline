<!-- Verbatim export of GitHub issue #234 (body + all comments), placed in the repository so an offline builder can cite it.
     Source of truth remains the issue: https://github.com/ValerieQA/never-blank-pipeline/issues/234
     Exported 2026-09-16T02:50Z from main 3e4059f..58afe47. Do not edit here; re-export instead. -->

# [R1][FORENSIC] Editorial contracts exist in repo but may not reach canonical prompts

Read-only forensic. No code, branch or PR. Nothing published, no provider calls, no CONTROLLED_LIVE. Main `3e4059fcce991e256d8427b85e7ecaf88f6f4801`.

> **Answer to the question:** mostly the second — *right contracts, disconnected from the machine* — with a qualification that matters. The prose Monday and Wednesday actually publish is written by **hard-coded Python prompt strings** in `src/editorial/*.py` and `src/never_blank/wednesday_july/*.py`. None of `brand_voice.md`, `NEVER_BLANK_EDITORIAL_WORLDVIEW.md`, `NEVER_BLANK_EDITORIAL_STYLE.md` or `blog_post.yaml` is loaded by either stream. Fragments of those documents were **hand-copied** into some inline prompts once, inconsistently, with no link, version or test tying them together, and they have drifted since. STYLE was genuinely executable until **2026-07-03**, when the V2 engine replaced the prompt that loaded it and dropped the loader. The newer typed configuration (`business_strategy.json`) *is* partly wired — for Monday. Wednesday's configured Golden contract was deliberately disconnected from generation by #210.

---

## 1. Executive verdict

| Stream | Verdict | In one line |
|---|---|---|
| **Monday** | **PARTIALLY WIRED** | Typed config (brand_editorial, role rules, channel rules, rubric) reaches three writing calls. The four named documents reach none. The reviser gets no role or voice. |
| **Wednesday** | **PARTIALLY WIRED — article generation NOT WIRED** | The model that writes the published Wix article receives **no configured editorial instruction at all**. Only the acceptance rubric reaches review/revision; role rules reach LinkedIn only when a revision forces recomposition. |

## 2. Monday runtime chain (actual)

```
.github/workflows/monday_publish.yml   (cron, due_check)
 └ scripts/streams/select_eligible_signal.py   [LLM: eligibility judgment — not a writer]
 └ scripts/generate_and_publish.py --editorial-role never-blank-monday-documented-case
     resolve_editorial_role(business_strategy.json)                         :909
     _editorial_role_rules = render_editorial_role_rules(role, wix|linkedin) :920
     research: Exa adapter → research.json
     generate_article(…, strategy_context, wix/linkedin_strategy,
                      editorial_role_rules, closing_contract)               :1882
       src/editorial/pipeline.py
         pattern_extractor(signal)                    inline prompt · no config
         decision_lens_lite(enriched, typed_strategy) inline prompt · strategy ✔
         narrative_spine(lens, enriched)              inline prompt · no config
         hook_engine(spine, lens, enriched)           inline prompt · no config
         reader_context(enriched)                     inline prompt · no config
         discovery_builder(…)                         inline prompt · no config
         story_assembly(…)                            inline prompt · no config
         never_blank_voice(…, typed_strategy, cta)    inline prompt · brand_editorial ✔
         platform_composer(long, medium,
             wix/linkedin rules, role rules, closing) inline prompt · role ✔ channel ✔
     blog_body = platforms["long"]["body"]   ← published Wix prose       :1908
     run_editorial_acceptance(rubric=editorial_acceptance/never_blank.yaml) :2009
         reviewer  chat(system=rubric.instructions)          rubric ✔
         reviser   chat(system=rubric.revision_instructions) rubric ✔ · role ✗ · voice ✗
     if revised → recompose_platform("medium", role rules, linkedin rules)  :2151
     accept_linkedin_composition → preflight → Wix → LinkedIn
```

**Every writing stage loads zero files.** The only file access in pattern_extractor, decision_lens_lite, narrative_spine, hook_engine, reader_context, discovery_builder, story_assembly, never_blank_voice and platform_composer is `json.loads(raw)` — parsing the model's *response*. Their system prompts are module-level string constants.

What reaches each writing call:

| Call | business_strategy `brand_editorial` | Monday role rules (#142) | channel rules | acceptance rubric | brand_voice / STYLE / WORLDVIEW / blog_post.yaml |
|---|---|---|---|---|---|
| article content stages (spine, hook, discovery, story) | ✗ | ✗ | ✗ | ✗ | ✗ (hand-copied fragments only) |
| never_blank_voice | **✔** voice, principles, claims, restrictions | ✗ | ✗ | ✗ | ✗ |
| platform_composer → **Wix article** | ✗ | **✔** | **✔** | ✗ | ✗ |
| platform_composer → **LinkedIn** | ✗ | **✔** | **✔** | ✗ | ✗ |
| acceptance reviewer | ✗ | ✗ | ✗ | **✔** | ✗ |
| acceptance **reviser** (rewrites published Wix prose) | ✗ | ✗ | ✗ | **✔** | ✗ |

## 3. Wednesday runtime chain (actual)

```
.github/workflows/wednesday_golden.yml   (cron, due_check)
 └ scripts/generate_and_publish.py --editorial-role never-blank-wednesday-golden
     resolve_editorial_role → _editorial_role_rules built (as Monday)       :920
     wednesday_supply → July RSS/select/enrich/score/angles
                        [LLM ×~35: research, not publication prose]
     DirectUrlResearchProvider → research.json
     generate_for_wednesday(editorial.to_legacy_dict())                     :1880
        ↑ ONLY the signal dict. No strategy, no role rules, no channel rules,
          no CTA, no closing contract, no sources block.
       src/never_blank/wednesday_routing.py → wednesday_july/pipeline.py
         decision_lens_lite(signal)      inline · no config
         narrative_spine / hook_engine / reader_context / discovery_builder /
         story_assembly / never_blank_voice   inline · no config
         compose_platforms(structured_article)    ← single argument
             5 formats: long, reading, medium, instagram, short
     blog_body = platforms["long"]["body"]   ← published Wix prose
     run_editorial_acceptance(rubric=role.acceptance_rubric_path
                              = editorial_acceptance/never_blank_golden_wednesday.yaml)
         reviewer rubric ✔ · reviser rubric ✔ · role ✗ · voice ✗
     if revised → recompose_platform("medium", role rules ✔, linkedin rules ✔)
                   via the SHARED src/editorial/platform_composer
```

No `wednesday_july` module loads any file. `_editorial_role_rules` is computed for Wednesday and then ignored by generation. The LinkedIn body receives Wednesday role rules **only on a revised run**, because only then is it recomposed by the shared composer. The live end-to-end run 33931982390 was revised, so its LinkedIn post did get them — and its Wix article was last rewritten by a reviser with no role or voice.

## 4. Artifact matrix

| Artifact | Class | Monday | Wednesday | Actual consumer |
|---|---|---|---|---|
| `config/brand_voice.md` | **C** dead product config | ✗ | ✗ | None. Listed in `business_strategy.json` `prompt_rule_references` (id `brand-voice`, version `r1-2026-08-13`) as metadata only. `git log -S brand_voice -- src scripts` is **empty**: no code has ever read it. Partial hand-copies: "research-driven observer…" (narrative_spine, hook_engine), the "In today's…" ban (hook_engine). Absent: "never open with a question", "if the first sentence could be removed…", "no resolution, no advice". |
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md` | **C** dead product config (formerly runtime) | ✗ | ✗ | None today. **Was RUNTIME until `2466611` (2026-07-03)**: `publish_packages._load_editorial_style()` injected it verbatim as `EDITORIAL STYLE (mandatory — follow exactly):`. Its core frame `Signal → Tension → Response → Outcome → Lesson` appears in no runtime prompt. The July Wednesday `decision_lens_lite` carries one hand-copied line ("Never Blank does not explain events"). |
| `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md` | **D** human documentation | ✗ | ✗ | None, and not referenced by any config either. It describes itself as the document "all other documents (prompts, scoring rubrics, CTA rules) follow from": an authoring source, not loadable config. Hand-copied fragments exist ("customer memory…" in pattern_extractor). |
| `config/prompts/blog_post.yaml` | **E** legacy | ✗ | ✗ | `load_prompt("blog_post")` ← `src/content/generator.py:126 generate_blog_post` ← `generate_content_package` ← `scripts/generate.py` ← **Friday** `scheduled_publish.py` step 1, plus the dispatch-only `generate_content.yml` / `generate_and_publish.yml`. The canonical entrypoint calls `prepare_content_packages(content_package=False)` and never reaches it. **Its nine-step structure does not apply to Monday or Wednesday.** |
| `business_strategy.json` → `brand_editorial` | **B** partial | ✔ voice stage only | ✗ | `never_blank_voice.finalize_article` renders voice, principles, preferred/prohibited claims, restrictions. |
| `business_strategy.json` → `editorial_roles[monday]` | **B** partial | ✔ composer (Wix + LinkedIn) | — | Not upstream content stages; not the reviser. |
| `business_strategy.json` → `editorial_roles[wednesday]` | **B** partial | — | ✔ LinkedIn recompose on revision only | Never reaches Wix article generation (#210). |
| `business_strategy.json` → `prompt_rule_references` | **C** | ✗ | ✗ | `{reference_id, path, version}` metadata. Only consumer: `assert_campaign_reference` compares the `active-campaign-strategy` **version**. No code opens any `path`. |
| `strategy/methodology/{editorial_strategy,platform_strategy,strategy_methodology}.md`, `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | **C** | ✗ | ✗ | Named in `prompt_rule_references` only. No `.md` content is read anywhere in `src/` or `scripts/`: every `.md` path there is a report being *written*. |
| `config/never_blank/wednesday_golden.yaml` + `src/never_blank/wednesday_golden.py` | **C** | — | ✗ | Loaded by `wednesday_golden.py`, which is **imported only by tests** and has never been imported by production code (`git log -S` empty). |
| `config/prompts/editorial_acceptance/never_blank.yaml` | **A** runtime | ✔ reviewer + reviser | ✗ | `EditorialAcceptanceRubric.load(DEFAULT_RUBRIC_PATH)`. |
| `config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml` | **A** runtime | ✗ | ✔ reviewer + reviser | `role.acceptance_rubric_path`. |
| Inline prompt constants in `src/editorial/*.py`, `src/never_blank/wednesday_july/*.py` | **A** — the real editorial system | ✔ | ✔ | Hard-coded in Python; no external source of truth. |
| `config/prompts/{linkedin_post,instagram_caption,facebook_post,threads_post,telegram_post}.yaml` | **E** legacy | ✗ | ✗ | Friday / legacy generator only. `linkedin_post.yaml` **does not parse**. |

## 5. Product-contract violations

**V1 — #143 required test, true when #148 merged, false since #210.**
- *Criterion:* "Configuration contract: the turn, the invariant and the anti-flattening prohibitions **reach the real prompts** · the forbidden shapes (\"5 lessons\", \"3 takeaways\", generic advice) are named in the configuration that reaches generation."
- *Actual:* those strings exist in `business_strategy.json` and `config/never_blank/wednesday_golden.yaml`, and **in no Wednesday generation prompt**. `grep` over `src/never_blank/wednesday_july/*.py` finds no "5 lessons", "3 takeaways" or "list of takeaways".
- *Status:* #210 disclosed this ("Wednesday role rules and the sources-of-record block no longer reach generation … faithful to July … makes #203 inert"). The deviation was **accepted, not hidden**. The defect is that the test claiming the opposite still passes.

**V2 — #40: "Business meaning and prompts remain outside executable orchestration code."**
- *Actual:* every prose-writing prompt for both streams is a Python string constant, including Never Blank semantics (the "research-driven observer" identity, owner-protagonist rules in `pattern_extractor`, forbidden openings). These predate #142/#143; neither added them.

**V3 — #40/#41 reference and wiring criteria satisfied literally, hollow at runtime.**
- #40: "Configuration references resolve deterministically." #41: "tests prove the same configuration **identity** reaches all required stage boundaries."
- *Actual:* both are true as written — the files exist, and the configuration *hash* is carried to every boundary. Neither criterion ever asked for reference *content* to reach a prompt, and #40 explicitly scoped out wiring consumers. So `prompt_rule_references` shipped as an inventory that looks like a prompt contract. That is a specification gap rather than a false claim, but it is the direct source of the belief that `brand_voice.md` governs output.

**V4 — #142 required test: "verified facts, observable mechanism, and bounded reflection reach actual consumer inputs distinctly."**
- *Actual:* role rules reach the composer, which writes the published Wix and LinkedIn bodies, and that is proven with a real call capture. They do **not** reach the upstream stages that choose the hook, spine, discovery and story, and they do **not** reach the **reviser**, which rewrites the published article whenever acceptance says `revise`. "One observable mechanism" on a revised article is enforced by the rubric alone.

**V5 — the reviser writes published prose with neither voice nor role (both streams).** No explicit criterion is violated, but for a revised run it changes which instructions produced the text that ships.

## 6. Why CI allowed this

1. **Existence tests standing in for wiring.** `tests/strategy/test_never_blank_business_config.py::test_all_prompt_and_rule_references_resolve_inside_repository` asserts `resolved.is_file()`. A reference that no code reads passes forever.
2. **Handoff-by-mock.** `tests/test_monday_stream.py::test_the_role_rules_are_handed_to_generation` patches `generate_article` and asserts it was *called with* `editorial_role_rules`. It proves the argument was passed, not that any model saw it. (`test_the_role_reaches_composition_through_the_real_call` is a genuine capture, but only of the composer.)
3. **Testing a constructor production does not use.** `tests/test_wednesday_golden.py::test_golden_rules_reach_the_existing_wix_and_linkedin_prompt_constructor` builds prompts with the **shared** `src/editorial/platform_composer._build_user_prompt`. Since #210, Wednesday generation uses `src/never_blank/wednesday_july/platform_composer.compose_platforms(structured_article)`, which takes no rules. The test was not retargeted when production moved, so it still passes.
4. **No test spans entrypoint → model messages.** Nothing runs `generate_and_publish.main` for a role and inspects the `(system, user)` of every writing call. Such a test is hard to write naively for a real reason: each stage binds `chat` by name (`from src.utils.llm_client import chat`), so patching `src.utils.llm_client.chat` intercepts nothing.
5. **Documents are not code.** Deleting `_load_editorial_style()` in `2466611` broke no test, because no test ever asserted STYLE content reached a prompt.

## 7. Minimum repair boundary (identified, not modified)

Listed so a decision can be taken. Nothing here should be done before the product decisions noted.

- **Wednesday generation receiving its configured contract:** `scripts/generate_and_publish.py:1880`, `src/never_blank/wednesday_routing.py`, `src/never_blank/wednesday_july/pipeline.py`, `src/never_blank/wednesday_july/platform_composer.py`. ⚠ This changes restored July module signatures, which #207/#210 forbid to preserve byte-fidelity, and the byte-fidelity tests enforce it. **Product decision required first:** July fidelity vs configured Golden contract.
- **Reviser receiving role and voice (both streams):** `src/editorial/editorial_acceptance.py` (`_revise_article`, `run_editorial_acceptance`) and the call site at `scripts/generate_and_publish.py:2009`.
- **Monday role reaching upstream content stages, if intended:** `src/editorial/pipeline.py`, plus the prompt builders in `story_assembly.py` and `never_blank_voice.py` at minimum.
- **Making `prompt_rule_references` documents executable, if they are meant to be:** a loader (`src/utils/config_loader.py` or `src/strategy/execution_context.py`), plus each prompt builder that should receive them. **Decision required first:** which of these are executable contracts and which are authoring documents. STYLE was once executable, brand_voice.md is declared as a prompt rule, WORLDVIEW describes itself as upstream.
- **No change for `blog_post.yaml`** on Monday or Wednesday. It belongs to the Friday question (#144).

## 8. Required regression tests

Each must capture real model-message construction on the production path. Patch `chat` **in every stage module's own namespace**, not in `src.utils.llm_client`.

1. **Monday end-to-end message capture.** Run `scripts/generate_and_publish.main` with `--editorial-role never-blank-monday-documented-case`, patching `chat` in each stage module to record `(module, system, user)`. Assert distinctive role sentinels ("exactly one mechanism actually visible", "Sources section") appear in the composer `long`/`medium` calls, and pin *which* stages carry them, so a future move is a visible decision.
2. **Wednesday end-to-end message capture.** Same, for the Golden role, recording calls made from `src.never_blank.wednesday_july.*`. Assert "5 lessons" and "3 takeaways" appear in the call that produces `platforms["long"]`. **Fails today — that is the point.**
3. **Reviser receives role and voice.** Force a `revise` verdict, capture the reviser call, assert role and `brand_editorial.voice` sentinels. **Fails today.**
4. **Reference content, not reference existence.** For every `prompt_rule_references` entry classed as executable, write a unique sentinel into a temporary copy of the file, run generation with captured `chat`, and assert the sentinel reaches at least one writing call. **Fails today for `brand_voice.md`.**
5. **The tested constructor is the production constructor.** Assert the composer module Wednesday production actually invokes is the one `test_golden_rules_reach…` exercises, so the #210 retargeting gap cannot recur silently.
6. **A document loader cannot vanish.** If STYLE or brand_voice become executable again, a test asserting their sentinel reaches the prompt would have made `2466611` fail CI.

## 9. Historical accountability

| Connection | Should have been established or kept at | What happened |
|---|---|---|
| `NEVER_BLANK_EDITORIAL_STYLE.md` → article prompt | **`2466611` (2026-07-03), "Wire Editorial Engine V2 into the live publish path"** — pushed straight to main, no PR | Before it, `publish_packages._generate_blog_article` injected STYLE verbatim as mandatory. The commit replaced that generation with the eight-stage V2 pipeline and deleted `_load_editorial_style()`. Its message does not mention dropping STYLE. |
| `brand_voice.md` → any prompt | **#41** "Wire typed strategy views through every Release 1 consumer" (2026-08-13), if references were meant to be executable | Never read by code at any point in history. **#46** (task #40, 2026-08-13) added it to `prompt_rule_references` as versioned metadata; #40 explicitly scoped out consumer wiring; #41 wired configuration *identity*, not reference *content*. |
| `NEVER_BLANK_EDITORIAL_WORLDVIEW.md` | None identifiable | Never referenced by code or configuration. |
| Wednesday role rules → Wednesday generation | **#148** (#143, 2026-08-21) established it via the shared composer; **#210** (#209, 2026-08-29) removed it | Disclosed deviation in #210's body. The #148 test was left targeting the shared constructor, so CI kept reporting the contract as met. |
| `wednesday_golden.yaml` / `wednesday_golden.py` → production | **#148** | Introduced as the "Golden product contract", consumed only by tests, never imported by production. |
| Reviser → role and voice | **#89** (editorial acceptance and controlled revision) or **#142/#143** | Designed around the rubric only. |

---

## Collateral finding — Friday, and a correction to my #159 report

This was found while tracing `blog_post.yaml`. It is outside this forensic's question, but time-sensitive.

**Correction.** On #159 (comment 5576286655) I wrote that Friday "shells out to the canonical path … never constructs a publisher", and PR #230 carries a test to that effect (`test_the_friday_publisher_reaches_no_channel_of_its_own`). **That is wrong.** `scripts/scheduled_publish.py:226-240` shells out to the **legacy** path:

```
step 1  scripts/generate.py --qc            → generator → blog_post.yaml, linkedin_post.yaml, …
step 3  scripts/publish.py --live --channels wix
step 4  scripts/publish.py --live --channels linkedin | facebook | instagram | threads
step 5  scripts/publish.py --live --channels telegram      (if Wix succeeded)
```

The #230 test only checked that `scheduled_publish.py` constructs no `*Publisher` class in-process. It could not see subprocesses, so it passed while missing the whole path. **#230 did not close Friday's non-R1 publishing.**

**Why nothing has happened yet, and why that is about to change.** Every scheduled Friday since 2026-08-28 skipped on the old window check (2026-09-11: "Window passed … 254 min ago"). #226 merged 2026-09-13, so **Friday 2026-09-18 will genuinely run**, earlier still once #232 lands. By code reading, not a live run, it will spend one paid `blog_post` generation and then abort: `generate_linkedin` → `load_prompt("linkedin_post")` raises, because that YAML does not parse, and step 1 is `abort_on_fail=True`. That is another accidental brake of exactly the #222/#230 kind: repairing `linkedin_post.yaml` would let Friday publish Wix, LinkedIn, Facebook, Instagram, Threads and Telegram from a generator that has none of the canonical gates.

Not acted on here — reported so it can be decided before 2026-09-18.

---

**Stopped after publishing this report.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)



---

## Comment — ValerieQA (2026-09-15T23:05:57Z)

**Independent read-only verification of the Friday finding.** Confirmed, with one correction about what happens this Friday. No code changed, no runs, no provider calls.

Confirmed:
- `scripts/scheduled_publish.py:226-241` shells out with `subprocess` to the legacy scripts: `scripts/generate.py --qc` (abort on failure), then `scripts/publish.py --live --channels <ch>` for `wix`, then `linkedin`, `facebook`, `instagram`, `threads`, and `telegram` if Wix succeeded.
- `scripts/publish.py:50-58` carries its own six-channel map and imports the Facebook, Instagram, Threads and Telegram publishers directly.
- `release_scope` is imported by **none** of `scheduled_publish.py`, `generate.py` or `publish.py`. The #229 allowlist governs the canonical entrypoint, the visibility publisher and research Stage 11 — not this path.

Correction on the immediate risk: **the brake is in front of generation, not in front of publication.** `config/prompts/linkedin_post.yaml` fails to parse (`line 60, column 3: expected <block end>`), and it is loaded during generation by `src/content/generator.py:134`, inside step 1, which is `abort_on_fail=True`. So the run aborts before `publish.py` is ever invoked, and this Friday nothing reaches any channel — one paid `blog_post` call and then a red run. The exposure appears the moment that YAML parses again, whether or not anyone connects it to publishing.

Two facts for whoever decides:
- **#232 is merged.** Friday now fires at 04:17 America/New_York instead of 06:17, so this path starts earlier in the day; #226 also lets a delayed firing still run.
- I am not touching this path. The canonical Friday stream is owner-accepted and out of scope for the model-routing work; whether a six-channel legacy publisher is the intended Friday behaviour is a product decision.


---

## Comment — ValerieQA (2026-09-15T23:18:35Z)

**Owner decisions recorded (2026-09-15).** Nothing in this comment is implemented; it is the scope boundary for current work.

- **Friday is paused and out of scope.** Do not repair it. No changes to `scheduled_publish.py`, `generate.py`, `publish.py`, channel ownership, Friday semantics — and **`config/prompts/linkedin_post.yaml` is not to be fixed as part of the current work.** The legacy six-channel path and the invalid YAML are recorded here as architecture evidence only.
- **The invalid YAML is not an accepted safety mechanism.** It is what currently prevents publication, and it is a defect standing in for a control that does not exist. Anyone repairing that file later is re-enabling a six-channel publisher that no allowlist covers.
- **Wednesday is paused.** July fidelity versus the configured Golden contract is **not** being decided now. No changes to Wednesday architecture, prompts, generation path, acceptance logic or product semantics. Wednesday returns only after Monday is rebuilt as the reference implementation.
- **Executable product contracts:** human-readable **Markdown is the intended source of truth** for product/editorial strategy. JSON/JSONL may exist only as a derived machine representation, runtime/state format, or interchange format. Python must not be the authoritative home of product/editorial semantics, a non-programmer must be able to change strategy in Markdown without editing Python, and the same strategy must not be maintained twice by hand in Markdown and JSON.
- **Current priority: Monday as the first reference implementation** — human-readable Monday strategy → loader/compiler if needed → machine/runtime representation if needed → **generic reusable engine capabilities** → Monday result. Not another Monday-specific Python engine.
- **#238 stays unmerged**, Research publication stays disabled, and Research ownership is not decided implicitly.


---

## Comment — ValerieQA (2026-09-16T00:17:39Z)

**Owner decision (2026-09-15): Wednesday's schedule keeps running while Wednesday is architecturally paused.** The pause covers architecture, prompts, generation, acceptance and product semantics — not the runtime. `wednesday_golden.yml` stays active with its #232 crons (`17 8`/`17 9 * * 3`), so the 2026-09-16 firing will run on its own. Unlike 2026-09-09, when both firings were green but stale-skipped under the old 59-minute rule, #226 now lets a late same-local-day firing proceed — so this run can publish to Wix and LinkedIn and consume a signal under the current, un-rebuilt logic. That is accepted. It is also the only stream presently able to prove that #226 + #232 lead to a real automatic publication: Monday is blocked on supply (#237), Friday is paused (this issue), Visibility and Research are blocked on model routing (#236/#238). The run will be observed, not triggered; no manual dispatch.
