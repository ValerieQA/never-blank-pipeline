# Monday — current-state trace (Issue #240, deliverables 1–6)

Forensic record of what Monday actually executes today, read from the checkout
at `orch/240`. Nothing here proposes a change; the proposal is in
`docs/monday-architecture/MONDAY_TARGET_ARCHITECTURE.md`.

Every claim below is anchored to a path, and where a line number is given it
was read from the file rather than inferred.

## 0. Incorporated audit inputs (#233, #237, #234)

The issue makes this task depend on the repository-wide findings from #233 and
names #234 as evidence about current editorial wiring.

### 0a. #233 — present, and incorporated here

**#233's deliverables exist in this repository.** They are on branch
`orch/233` (also pushed, `origin/orch/233`), commits `19bac01` and `e0d00e0`,
and they are not yet merged to `main` — which is why a search of the
working tree alone does not find them:

- `docs/repository-audit/REPOSITORY_AUDIT.md` — the human report.
- `reports/repository_audit/findings.json` — ten ranked findings plus a repair
  order.
- `reports/repository_audit/inventory.json` and `inventory/**` — every one of
  the 8,399 tracked paths classified exactly once.

#233 audited base `58afe47`, which is the commit this branch descends from, so
its reachability claims and this trace's are statements about the same tree and
can be compared directly rather than reconciled across versions.

The gate is therefore **merge, not existence**. The findings below are
incorporated into this trace and reconciled in the target document now; no
production change is proposed before #233 lands and before owner review.

| #233 finding | What it establishes | Relation to this trace |
|---|---|---|
| F3 | `prompt_rule_references` declares seven documents as rules the run follows; one is consumed, and only as a version equality check. `config/brand_voice.md` has no reader anywhere in `src/` or `scripts/`. | **Confirms §5a** independently and repository-wide. #233 also reclassifies `docs/PLATFORM_AND_VISUAL_STRATEGY.md` from documentation to declared-but-unwired (declared at `business_strategy.json:337-341`) — the same row §5a reaches from the Monday side. |
| F9a | The only test over those references asserts `resolved.is_file()` (`tests/strategy/test_never_blank_business_config.py:80-86`) and would pass if every one of them were empty. | **Adds.** §2's "tests proving runtime behaviour" column has no entry for the reference block; F9a is *why* it reads as wired. |
| F9d | `tests/test_cross_platform_overlap_policy.py:326-333` asserts on the **text** of `config/brand_voice.md`. | **Adds a migration dependency §5b did not have.** A test outside the Monday path pins the content of a file the target retires; retiring the file breaks it. |
| F5 + audit §9.4 | `scripts/generate_and_publish.py:320-321` sets `PACKAGES_DIR = Path("reports/content_packages")` and calls `mkdir` at **import** time, against the process CWD. 7,796 of 8,399 tracked files are test residue this produced. | **Adds an ordering constraint** on the target's end-to-end tests (target §11 T3, §10). |
| F6a, F6c | `config/prompts/{blog_post,linkedin_post}.yaml` are reachable only from `scripts/generate.py`; `docs/SYSTEM_MAP.md:28-30` and `:55-58` present dead or legacy artifacts as current. | **Confirms §5c**, and supplies the exact `SYSTEM_MAP.md` lines the target's retirement step has to correct. |
| F1, F2 | Wednesday's declared role is rendered and then discarded before generation (`generate_for_wednesday(signal)` takes one argument); `config/never_blank/wednesday_golden.yaml` has no production caller. | **Bounds a claim in the target.** Out of Monday scope, but it shows the Wednesday fork is wider than the one assertion the target cites. See target §8.3. |
| F4d | `daily_signal_research.yml` runs every day; its publish decision is the value of a secret, not repository state, and that path published live to unauthorized channels on 2026-09-06/07. | **Adds.** §1a calls Stage 11 "a second, non-canonical publisher"; #233 establishes that whether it publishes on a Monday is **not answerable from source**, and that it has. Monday's strategy does not govern it. |
| F8d | `src/strategy/pattern_extractor.py` exists, has compile-only coverage, and is a **different module** from `src/editorial/pattern_extractor.py`. | **Disambiguation.** Every reference to `pattern_extractor` in §3.1 and in the target's REPLACE list means the `src/editorial/` one. |
| Audit §9.1–9.3 | The proposed permanent guardrail: one manifest of artifacts claiming to govern the product, one parametrized test that makes `status: wired` cost something, one reachability test that refuses unclassified artifacts. | **The target's §11 is the Monday instance of this**, not a competing mechanism. Reconciled in target §11. |
| F4a/b/c, F7, F8a–c, F10 | Friday's duplicate publisher and missing concurrency group; dry-run-only configuration; unresolved artifacts; four accepted legacy failures. | No Monday-path dependency. Out of scope for #240 and not restated here. |

Two of #233's conclusions are worth quoting because the target rests on them. On why unwired product config survives review: the repository
"has never had a rule saying *an artifact is not finished until something
proves it is consumed*". And on the Monday path specifically, F3's consequence:
"A brand-voice change has no effect on any published article, and a green test
suite says the references are fine."

### 0b. #237 — the landed editorial-wiring forensic

`docs/MONDAY_SELECTION_HEAD_OF_LINE.md`, on branch `orch/237` (also
`origin/orch/237`), commit `ce1633f`. #233's own `findings.json` names #237 as
the editorial-wiring forensic and defers the Monday/Wednesday prompt-wiring
question to it rather than deciding it.

It is directly load-bearing for deliverable 6 and is incorporated in §7d below.
Its central finding — that Monday's selection window never advances — is a
**correction** to a claim this trace made in §7b, not merely supporting
evidence.

### 0c. #234 — not present in this repository

No #234 artifact exists in the working tree, in any local or remote-tracked
branch, or in any commit message. Searched: every ref under
`refs/heads/**` and `refs/remotes/**`; every commit subject reachable from
`--all`; every path ever added under `docs/**` and `reports/**`. There is no
`orch/234` branch, where every other orchestrated issue in this series (`232`,
`233`, `237`, `240`) has one. GitHub is not reachable from this worktree, so
whether #234 exists as an issue with findings recorded only in its thread
cannot be determined here.

What this means for the deliverable, stated rather than worked around: the
editorial-wiring evidence incorporated below is #233's F1/F3/F6/F9 and #237's
forensic, plus this trace's own first-hand reading of the Monday path. If #234
holds editorial-wiring findings not covered by those, they are not in this
report and it should be re-reconciled against them when they are available.
That is a bounded gap in the inputs, and it is recorded as such rather than
being allowed to look like completeness.

## 1. Current Monday end-to-end execution

Two independent processes. They share only files in `data/research/`.

### 1a. Supply (daily, not Monday-specific)

```
.github/workflows/daily_signal_research.yml   cron "0 8 * * *" (04:00 ET, every day)
  └─ scripts/research/run_daily_research.py
       ├─ scripts/research/discover.py   RSS fetch      ← config/research_sources.yaml
       │                                 LLM selection  ← config/prompts/research/signal_selector.yaml
       ├─ scripts/research/score.py      rule score     ← config/scoring_weights.yaml
       │                                                ← config/prompts/research/score.yaml
       ├─ scripts/research/enrich.py     LLM enrichment ← config/prompts/research/enrich.yaml
       ├─ scripts/research/angles.py     LLM angles     ← config/prompts/research/angles.yaml
       ├─ scripts/research/prepare_content.py           ← config/prompts/research/content_package.yaml
       └─ writes data/research/signals_active.jsonl
                 data/research/selected_signals.jsonl
                 data/research/seen_index.json
```

`run_daily_research.py`'s own docstring says it is "DISCOVERY/PREPARATION ONLY
— NOT a Release 1 canonical run". It creates no `RunContext`, and its optional
Stage 11 publishing is disabled for Wednesday by the workflow but is otherwise
a second, non-canonical publisher.

#233's F4d sharpens that last clause into something the target architecture has
to account for: the inline guard at `daily_signal_research.yml:82-83` forces
`NB_RESEARCH_PUBLISH_ENABLED=false` **only** on Wednesday, so on a Monday the
publish decision is the value of a secret that is not in the repository.
Whether a second article publishes on Monday is therefore not answerable from
source, and the #159 forensics in `src/publishing/release_scope.py:12-18`
record that this path did publish live — to Facebook, Instagram and Telegram —
on 2026-09-06 and 2026-09-07. **A Monday strategy authored in Markdown governs
`monday_publish.yml` and nothing else.**

### 1b. Publication (Monday)

```
.github/workflows/monday_publish.yml   cron "17 8 * * 1" / "17 9 * * 1"
  │  MONDAY_ROLE = never-blank-monday-documented-case  (a literal in the workflow)
  │
  ├─ [window]     scripts/streams/due_check.py --day monday --time 04:17 --timezone America/New_York
  │                 → reports/scheduling/monday_scheduling_decision.json
  │
  ├─ [select]     scripts/streams/select_eligible_signal.py --editorial-role $MONDAY_ROLE
  │                 ├─ load_business_strategy_configuration()        strategy/current/business_strategy.json
  │                 ├─ resolve_editorial_role(...)                   → EditorialRole
  │                 ├─ candidates = signals_active.jsonl − published_signal_ids.txt
  │                 ├─ for each of the first 15: judge_source_eligibility()   1 model call each
  │                 │     src/editorial/source_eligibility.py, model = model_enrich()
  │                 └─ exit 0 / 3 / 4 / 5 → reports/stream_selection/monday_selection.json
  │
  └─ [generate+publish]  scripts/generate_and_publish.py --signal-id … --editorial-role $MONDAY_ROLE
        │
        ├─ load_business_strategy_configuration()  → StrategyExecutionContext (5 typed views)
        ├─ resolve_editorial_role() → render_editorial_role_rules(role, surface="wix"|"linkedin")
        ├─ load_active_strategy()   strategy/current/strategy.json → cta_mode ("reflection")
        │     …overridden to "none" by role.cta_mode                       [gap.py:934-946]
        ├─ assert_campaign_reference()  — compares ONE version string, reads no file
        ├─ _load_signal()           selected_signals.jsonl → signals_active.jsonl
        ├─ JsonlIntakeAdapter.adapt() → ContentAssignment → RunContext (run_id)
        ├─ audience_request() → select_audience() → AudienceSelection
        │     TARGET_AUDIENCE from the daily angles prompt; unmatched ⇒ configured default
        ├─ readiness gate            ARTICLE_READY / SOURCE_PREMISE_VERIFIED on the signal
        ├─ research                  build_source_directives(signal) → ExaResearchAdapter
        │                            → evidence assessment → READY or stop
        ├─ decision policy           role.decision_policy == "role_bounded_r1"
        │                            ⇒ decision_policy.json written, DECISION LENS NOT CONSULTED
        ├─ generate_article()        src/editorial/pipeline.py
        │     pattern_extractor → decision_lens_lite → narrative_spine → hook_engine
        │     → reader_context → discovery_builder → story_assembly → never_blank_voice
        │     → platform_composer(formats=("long","medium"))
        ├─ editorial acceptance      config/prompts/editorial_acceptance/never_blank.yaml
        │                            ACCEPT | one REVISE round | stop
        ├─ social re-composition     recompose_platform("medium") when the article was revised
        ├─ source transparency       validate_source_transparency() / validate_social_lineage()
        ├─ visual                    build_visual_assets_record()  blog + linkedin only
        ├─ packages                  build_wix_publication_package / build_linkedin_publication_package
        ├─ preflight                 evaluate_publication_preflight() → preflight_result.json
        └─ publish                   WixPublisher → LinkedInPublisher → publication_results.json
                                     → run_report.json → append_published_entry()
```

### Corrections to the stage order assumed by the issue

The issue's stage list is `… never_blank_voice -> reviewer/reviser ->
platform_composer -> output`. The code does not run in that order, and the
difference matters for any migration:

| Issue's assumption | Actual behaviour |
|---|---|
| `enrichment` is a Monday stage | Enrichment happens a day or more earlier, in the daily research job. The Monday run never enriches; it only verifies the signal's cited source. |
| `hook -> reader_context` | `reader_context` runs after `hook` but is built from the *signal*, not from the hook — `build_reader_context(enriched)` (`src/editorial/pipeline.py:168`). It is an independent stage placed mid-chain. |
| `reviewer/reviser -> platform_composer` | Composition runs **first** (`pipeline.py:191`), for both surfaces. Editorial acceptance then reviews the **Wix long-form only**. If it revises, `recompose_platform("medium")` regenerates the LinkedIn derivative from the accepted body. The LinkedIn artifact is never itself reviewed. |
| `decision lens` is a Monday stage | Monday's role declares `decision_policy: "role_bounded_r1"`, so the canonical Decision Lens is skipped entirely. `decision_lens_lite` — a different module with a different purpose — does run. |

## 2. Per-stage classification

Columns are the six the issue asks for, plus the tests that prove *runtime*
behaviour rather than file existence.

| Stage | Generic mechanism | Monday product/editorial semantics | Hard-coded prompt semantics | Strategy/config received at runtime | Dead / duplicated config | State & data | Tests proving runtime behaviour |
|---|---|---|---|---|---|---|---|
| workflow (`monday_publish.yml`) | cron, concurrency group, artifact upload, secret presence checks | role id is a literal string in the workflow; 04:17 ET; Wix+LinkedIn secret set | — | `MONDAY_ROLE` env literal | `config/schedule.yaml` no longer lists monday | writes `published_signal_ids.txt`, commits `published_content_index.jsonl` | `tests/test_monday_stream.py` §J,§K (workflow YAML assertions — structural, not runtime) |
| due check (`scripts/streams/due_check.py`) | weekday/timezone/cron-identity gate | none — day name is an argument | — | `--day/--time/--timezone/--role` | `config/schedule.yaml:time` duplicated as a workflow literal (a test pins them together) | `reports/scheduling/monday_scheduling_decision.json` | `test_monday_stream.py::test_only_one_of_the_two_firings_is_the_window` (real invocation) |
| candidate loading (`select_eligible_signal.py::_load_candidates`) | JSONL read, published-set difference | queue is `signals_active.jsonl` only, while the run later loads from `selected_signals.jsonl` first | — | `--active-path`, `--published-path` | the two paths disagree (see §6c) | reads `signals_active.jsonl`, `published_signal_ids.txt` | `test_monday_stream.py` §eligibility suite (real `main()` invocation with a fake transport) |
| eligibility (`src/editorial/source_eligibility.py`) | criteria→judgment carrier, strict verdict contract, fail-closed, provider circuit breaker | **all** of it comes from `role.eligibility_criteria` in JSON | `_INSTRUCTIONS` (:53) fixes "uncertainty is ineligibility" and the field set `_SOURCE_FIELDS` (:39) | `EditorialRole.eligibility_criteria` | — | `reports/stream_selection/monday_selection.json` | `test_selector_circuit_breaker.py`, `test_monday_stream.py` §eligibility — real transport seam, asserted verdicts |
| enrichment (daily job) | LLM call + JSON schema fill | `signal_selector.yaml` defines what a signal *is*; `angles.yaml` mints `NEVER_BLANK_ANGLE`, `POSSIBLE_SIGNATURE_LINE`, `TARGET_AUDIENCE` vocabulary | entire prompt bodies | `config/research_sources.yaml`, `config/scoring_weights.yaml`, `config/prompts/research/*` | `signal_categories` / `avoid_categories` encode the superseded presence thesis | `signals_active.jsonl`, `seen_index.json` | `tests/test_research_prompts.py`, `test_research_pipeline.py` |
| research (`src/research/lifecycle.py`) | directive building, retrieval, evidence assessment, READY gate | none found — directives derive from signal fields | `JUDGMENT_INSTRUCTIONS` in `assessment.py` is evidence-generic | `ResearchStrategyView` (positioning, restrictions, preferred claims) | `ResearchStrategyView.prompt_rule_references` carried but never dereferenced | run-scoped `research.json` | `test_research_evidence_contract.py`, `test_research_artifact_lifecycle.py` |
| decision policy | typed record, create-once write, strict reload, identity verify | Monday **skips** the Decision Lens | — | `role.decision_policy` | `config/prompts/decision_lens/never_blank.yaml` is unreachable on Monday | `decision_policy.json` | `tests/test_decision_lens_contract.py`, `test_decision_lifecycle.py` |
| `pattern_extractor` | retry-once, JSON schema validation | **severe** — see §3.1 | whole prompt (:32) | none | `visibility_pattern` field name retained for a mechanism that is no longer about visibility | — | `tests/strategy/test_pattern_extractor.py` (prompt + validator, real call seam) |
| `decision_lens_lite` | LLM call + schema | legacy key names carry Monday's superseded thesis | whole prompt (:30) | `DecisionLensEditorialStrategyView`, `AudienceSelection`, evidence boundary | three "LEGACY COMPATIBILITY KEY" fields | — | `tests/strategy/test_strategy_semantic_consumption.py::test_decision_lens_consumes_claim_boundaries_and_selected_audience` |
| `narrative_spine` | LLM call + enum validation | `_VALID_FEELINGS` (:20) is an editorial vocabulary | whole prompt (:22) | only the legacy `STRATEGY_*` mapping branch, which R1 never enters | `strategy_section` dead on the canonical path (`narrative_spine.py:106`) | — | none asserting the prompt |
| `hook_engine` | ≥5 candidates, exact-match selection | `_HOOK_TYPES` (:21) — six named hook archetypes | whole prompt (:30), incl. forbidden openers | none | — | — | none asserting the prompt |
| `reader_context` | word/line limits, skip-on-household-name | `_HOUSEHOLD_NAMES` (:20) — a literal 8-company list | whole prompt (:26) | none | — | — | none |
| `discovery_builder` | 2–4 beats, detective-template rejection | "the owner situation is the protagonist" asserted in Python doc and prompt | whole prompt (:16), `_contains_detective_template` (:67) | none | detective markers duplicated in `src/content/output_guard.py` | — | none asserting the prompt |
| `story_assembly` | LLM call + schema | Steps 5–7 arc | whole prompt (:23) | none | — | — | none |
| `never_blank_voice` | echo/CTA optionality, prohibited-claim exact-match guard | Echo concept, checklist incl. "corporate evidence ≤ 20–25%" | whole prompt (:29) | `brand_editorial` lists, `selected_cta` | — | — | `test_strategy_semantic_consumption.py::test_editorial_consumes_voice_principles_claims_restrictions_and_cta_rules` |
| `platform_composer` | format loop, word-count warn, echo-mode validators, source-citation validator | `_BLOCK_TABLE` (:21), `_WORD_RANGE` (:52), `_FORMAT_CONSTRAINTS` (:77), the arc at :121, `BRAND_ATTRIBUTION` (:181) | whole `_SYSTEM_PROMPT` (:114) | `WixStrategyView`, `LinkedInStrategyView`, `editorial_role_rules`, `closing_contract` | `_WORD_RANGE["long"] = (400,600)` duplicates `channels.wix.article_rules` | — | `test_monday_stream.py::test_the_role_reaches_composition_through_the_real_call`; `test_monday_echo_contract.py` (validators exercised on real bodies) |
| reviewer / reviser | rubric load, one revision round, audit persistence | 9 rubric criteria in YAML | `instructions` / `revision_instructions` in the rubric | `config/prompts/editorial_acceptance/never_blank.yaml` (default — Monday declares no override) | Monday's role rules and the rubric criteria overlap without a stated precedence | `editorial_acceptance.json`, `editorial_review_content.json` | `tests/test_editorial_acceptance.py`, `test_editorial_review_content.py` |
| transparency | URL/name attribution, structural URL comparison, social lineage | gated by `role.require_source_transparency` | — | role flag + run research artifact | — | — | `tests/test_story21_hosted_evidence.py`, `test_canonical_social_lineage.py` |
| packaging / preflight / publish | idempotency, canonical URL verify, per-channel ALLOW/BLOCK, R1 scope | `BRANDED_HASHTAGS` (`hashtags.py:35`), `PROHIBITED_HASHTAGS` (:38), `_SIGNATURE_PREFIX` (`formatting.py:17`) | — | `config/schedule.yaml` publication order/channel behaviour | `schedule.yaml.publication_order` lists six channels; R1 publishes two | `publication_results.json`, `run_report.json`, `published_content_index.jsonl` | `test_publication_preflight.py`, `test_r1_publish_scope.py`, `test_hashtags.py` |

## 3. Product/editorial semantics hard-coded in Python

Format required by the issue:
`path | function/class | exact behavior | why it is product semantics | proposed human-readable strategy destination`.

The proposed destinations refer to the Markdown structure defined in
`docs/monday-architecture/MONDAY_TARGET_ARCHITECTURE.md` §7.

### 3.1 The severe cases — these define what Monday argues

| path | function/class | exact behavior | why it is product semantics | proposed destination |
|---|---|---|---|---|
| `src/editorial/pattern_extractor.py:32` | `_SYSTEM_PROMPT` | "Never Blank produces articles for small business owners — not about corporations." Declares the central question and forbids "What did the company do?". | This is the editorial subject of the product, stated as an unchangeable string. No configuration can alter it. | `monday/editorial-objective.md` |
| `src/editorial/pattern_extractor.py:146` | `_validate` | Raises unless `article_protagonist == "owner"`. A **deterministic Python gate**, not a prompt instruction. | The protagonist of an article is an editorial decision. As written, no strategy file can produce an article whose protagonist is anything else — this single check is why Wednesday had to fork into `src/never_blank/wednesday_july/`. | `monday/editorial-objective.md` (protagonist declaration) |
| `src/editorial/pattern_extractor.py:89-96` | `_SYSTEM_PROMPT` field 8 | `signal_fit = "reject"` when the signal "is only relevant to large-company strategy", when the corporate example cannot be removed, or when it is "generic AI/tech news". | A second, invisible eligibility gate — after the selector already judged eligibility against the configured criteria, and using different rules. | `monday/what-makes-a-signal-useful.md` |
| `src/editorial/pattern_extractor.py:63-68` | `_SYSTEM_PROMPT` field 3 | Four worked mechanism examples ("price rations the constraint that is actually binding", "non-urgent visibility work is displaced by urgent delivery work"…). | Register-setting examples steer output as strongly as rules do. They are editorial taste. | `monday/editorial-objective.md` |
| `src/editorial/decision_lens_lite.py:55-66` | `_SYSTEM_PROMPT` fields 3–4 | Output keys `delivery_vs_presence_conflict` and `customer_memory_consequence`, each labelled "LEGACY COMPATIBILITY KEY", with prose walking the model back from the name. | The schema still *names* the superseded presence/memory thesis. Every downstream stage reads those key names (`narrative_spine.py:121-122`, `discovery_builder.py:122`, `story_assembly.py:121-122`). | retire the names; the concept belongs in `never-blank/worldview.md` as an optional lens |
| `src/editorial/platform_composer.py:121` | `_SYSTEM_PROMPT` | The production article arc: `Hook → Recognition → Tension → Market Observation → Investigation → Mechanism → Business Consequence → Reframe → Echo → Soft CTA`. | This is *the* article structure. Monday's role in JSON declares a different, nine-beat structure; both reach the same model call and neither is authoritative over the other. | `monday/article-structure.md` (and the shared arc to `never-blank/article-shape.md`) |
| `src/editorial/platform_composer.py:21` | `_BLOCK_TABLE` | Per-format `full`/`compressed`/`skip`/`adapt` decisions for ten named blocks. | Which parts of an argument survive compression to LinkedIn is an editorial decision, expressed as a Python dict. | `never-blank/channels.md` |
| `src/editorial/platform_composer.py:52` | `_WORD_RANGE` | `long: (400, 600)`; `medium: (120, 220)`. | Duplicates `business_strategy.json → channels.wix.article_rules` ("Use 400–600 words"). Two authorities for one rule. | `never-blank/channels.md`, once |
| `src/editorial/platform_composer.py:77` | `_FORMAT_CONSTRAINTS` | Per-format prose rules: "Corporate evidence… may occupy at most 20 percent of the body"; "One corporate example maximum". | Quantified editorial limits. | `never-blank/channels.md` |
| `src/editorial/never_blank_voice.py:78-96` | `_SYSTEM_PROMPT` checklist | Eleven self-check items including "corporate evidence does not occupy more than 20-25% of the article". | A third statement of the same limit, at a *different value* than the composer's 20%. | `never-blank/article-shape.md` |
| `src/publishing/hashtags.py:35` | `BRANDED_HASHTAGS` | `("#NeverBlank", "#CompoundPresence", "#CustomerTrust")` — always first, in this order. | `#CompoundPresence` is the superseded house thesis, appended to every LinkedIn post regardless of what the article argues. | `never-blank/channels.md` |
| `src/publishing/hashtags.py:38` | `PROHIBITED_HASHTAGS` | `{"#presencesystem", "#contentmarketing"}` | A brand prohibition list. | `never-blank/prohibited.md` |

### 3.2 The structural cases — editorial vocabulary frozen as Python literals

| path | function/class | exact behavior | why it is product semantics | proposed destination |
|---|---|---|---|---|
| `src/editorial/hook_engine.py:21` | `_HOOK_TYPES` | Exactly six hook archetypes; a candidate of any other type raises. | The taxonomy of openings a publication uses is an editorial house style. | `never-blank/article-shape.md` |
| `src/editorial/hook_engine.py:66-71` | `_SYSTEM_PROMPT` | Forbidden openers: "In today's…", "It's not about…", "Many founders…", opening with a question. | Style prohibitions. | `never-blank/prohibited.md` |
| `src/editorial/narrative_spine.py:20` | `_VALID_FEELINGS` | `{recognition, unease, reframe, clarity, anticipation}`; anything else raises. | The set of reader effects the publication aims at. | `never-blank/article-shape.md` |
| `src/editorial/reader_context.py:20` | `_HOUSEHOLD_NAMES` | Literal set of eight company names; substring match on the headline skips the context stage. | An editorial judgment about reader knowledge, and a maintenance liability — matched by substring, so "Meta" matches "Metabolic". | `never-blank/audience.md` |
| `src/editorial/reader_context.py:26-49` | `_SYSTEM_PROMPT` | Mandatory one-sentence company description, 10–20 words, with three worked examples. | Article furniture, decided in code. | `monday/article-structure.md` |
| `src/editorial/discovery_builder.py:67-74` | `_contains_detective_template` | Nine banned first-person phrases, deterministically rejected. | A voice prohibition enforced as a validator. Duplicated in `src/content/output_guard.py:14`. | `never-blank/prohibited.md`, once |
| `src/editorial/story_assembly.py:70` | `_SYSTEM_PROMPT` | Banned construction: `"If your goal is X, then Y"`. | Voice prohibition. | `never-blank/prohibited.md` |
| `src/content/output_guard.py:25-31` | `_DICTIONARY_OPENING_PATTERNS` | Regex rejection of encyclopedic openings. | Editorial prohibition as a publication gate. | `never-blank/prohibited.md` |
| `src/publishing/formatting.py:17` | `_SIGNATURE_PREFIX` | `"Never Blank"` — the literal brand token the bolding pass looks for. | Brand identity in a formatting module; paired with `platform_composer.BRAND_ATTRIBUTION` (:181), the same literal twice. | `never-blank/identity.md` (one owner, one value) |
| `src/strategy/validators.py` | `_REQUIRED_STRATEGY_FIELDS` | A strategy is invalid unless it declares `compound_presence_role`. | Requires the house thesis to exist as a field, even after #157 removed it as a publication gate. | retire |

### 3.3 Not product semantics — deliberately listed so a migration does not move them

`src/editorial/source_eligibility.py`, `src/editorial/editorial_role.py`,
`src/editorial/source_transparency.py`, `src/editorial/sources_of_record.py`,
`src/research/*`, `src/run/*`, `src/publishing/{preflight,idempotency,package,canonical_url}.py`,
`src/artifacts/*`. Each carries the criteria it is given and knows no weekday,
company class or topic. `tests/test_monday_stream.py::test_no_engine_module_knows_what_monday_means`
already holds nine of them to that standard. These are the *reusable
capabilities* the target architecture should keep and build on.

## 4. Strategy/config Monday actually consumes at runtime

Confirmed by following imports and loader calls from the two entry points.

| File | Loader | What is read | Reaches a model prompt or control decision? |
|---|---|---|---|
| `strategy/current/business_strategy.json` | `load_business_strategy_configuration()` (`business_config.py:272`) | whole file, strictly validated | yes — both |
| `strategy/current/strategy.json` | `load_active_strategy()` (`loader.py:22`) | `strategy_id`, `strategy_version`, `started_at`, `primary_cta_intent` | control only; `primary_cta_intent` is then **overridden** to `none` by the role |
| `config/prompts/editorial_acceptance/never_blank.yaml` | `EditorialAcceptanceRubric.load()` (`editorial_acceptance.py:47`) | criteria + instructions + revision instructions | yes — prompt and ACCEPT/REVISE/REJECT |
| `config/schedule.yaml` | publication ordering / channel behaviour | `publication_order`, `channel_behavior`, `fallback_rules`, `time` | control |
| `config/visual_system.yaml` | `src/publishing/image_pipeline.py:42` | palette, families, rhythm rules | visual generation |
| `config/prompts/image_generation.yaml` | `image_pipeline.py:43` | style suffix + generation instructions | yes |
| `config/research_sources.yaml` | `scripts/research/discover.py:26` | feeds, `signal_categories`, `avoid_categories`, caps | supply-side prompt + control (**previous day**, not the Monday run) |
| `config/scoring_weights.yaml` | `scripts/research/score.py:19` | weights, thresholds | supply-side control |
| `config/prompts/research/{signal_selector,score,enrich,angles,content_package}.yaml` | `load_prompt()` | prompts | supply-side prompts |
| `data/research/signals_active.jsonl` | selector | candidate queue | control |
| `data/research/selected_signals.jsonl` | `_load_signal` (`gap.py:373`) | the dispatched signal | control |
| `data/research/published_signal_ids.txt` | selector + workflow | consumption marker | control |

Environment (not files): `NB_OPENAI_API_KEY`, `NB_EXA_API_KEY`,
`NB_ENRICH_MODEL` / `NB_ARTICLE_MODEL` / `NB_SOCIAL_MODEL`,
`NB_RUN_TEXT_CALL_BUDGET`, the Wix/LinkedIn/Cloudinary credentials.

**Total human-editable surface that actually governs a Monday article:** one
JSON file, one YAML rubric, and — a day earlier and in a different process —
one YAML source list plus five YAML prompts. No Markdown file is read by any
of it.

## 5. Apparently authoritative Monday-relevant files Monday does NOT consume

Verified: no `src/` or `scripts/` module opens any of these on the Monday path.

### 5a. Named in `business_strategy.json.prompt_rule_references` — and never dereferenced

`assert_campaign_reference` (`execution_context.py:296`) looks up exactly one
reference (`active-campaign-strategy`) and compares only its `version` string
against the campaign. **No reference's `path` is ever opened.** The block is a
manifest of files the system does not read.

#233 reaches the same conclusion repository-wide as F3, and its F9a supplies
the part this trace could not see from the Monday path alone: the reason the
block survives review is `tests/strategy/test_never_blank_business_config.py:80-86`,
which asserts `resolved.is_file()` and would pass unchanged if every referenced
document were empty.

| Referenced path | Status |
|---|---|
| `config/brand.yaml` | Loaded only by `src/quality/*` and `src/internal/strategy.py`, reachable solely from the legacy `scripts/generate.py`. Not on Monday's path. |
| `config/brand_voice.md` | 330 lines defining reader, voice, forbidden phrases, hook rules, per-platform differences. **Never opened by any Python.** Its content is paraphrased inside `pattern_extractor`, `hook_engine`, `never_blank_voice` and `platform_composer` prompts. |
| `strategy/current/strategy.json` | Consumed (see §4) — the only live reference. |
| `strategy/methodology/strategy_methodology.md` | Never opened. |
| `strategy/methodology/editorial_strategy.md` | Never opened. |
| `strategy/methodology/platform_strategy.md` | Never opened. |
| `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | Never opened. |

### 5b. Authoritative-looking, not referenced anywhere, never read

| File | What it claims to be | Reality |
|---|---|---|
| `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md` | editorial worldview | never read, and not referenced by `SYSTEM_MAP.md` or `prompt_rule_references` — authoritative by title alone |
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md` | `docs/SYSTEM_MAP.md` lists it first, as "article formula, audience, writing rules" | never read |
| `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md` | editorial patterns | never read |
| `strategy/worldview.md` | states it is the file all others derive from, and that strategy, prompts, rubrics and CTAs are its consequence | never read; also the only Russian-language strategy artifact |
| `strategy/current/strategy.md` | the human rendering of `strategy.json` | never read. `src/strategy/history.py:87` *archives* it and nothing writes it — it is hand-maintained alongside the JSON, which is precisely the double-maintenance the owner contract forbids |
| `strategy/methodology/evaluation_rules.md` | evaluation rules | never read |
| `strategy/stage2_reference_article_example.md` | reference article | never read |
| `strategy/decision_log.md` | decision history, cited by `strategy.json.research_references` | never read |
| `docs/EDITORIAL_ENGINE_V2.md`, `docs/NARRATIVE_SPINE.md`, `docs/LERA_OPERATING_SYSTEM.md` | named as the spec in the docstrings of seven `src/editorial/` modules and two `src/publishing/` modules | never read; the modules' own prompt literals are the real spec |
| `config/prompts/image_hook.yaml` | an image prompt beside one that is used | never loaded — `scripts/dry_run.py:101` lists `image_hook` among prompts that are "not_needed" |

### 5c. Reachable code, unreachable from Monday

| File | Why it looks authoritative | Reality on Monday |
|---|---|---|
| `config/prompts/decision_lens/never_blank.yaml` | 149 lines of Release 1 editorial-judgment policy with a versioned profile identity | **Not consulted.** Monday's role declares `decision_policy: "role_bounded_r1"` (`business_strategy.json:393`), so `gap.py:1284` takes the branch that writes `decision_policy.json` and never constructs the evaluator. |
| `config/prompts/{blog_post,linkedin_post,facebook_post,instagram_caption,threads_post,telegram_post,stories_post}.yaml` | per-platform generation prompts | legacy `scripts/generate.py` path only |
| `config/prompts/{qc_factuality,qc_voice,rewrite_with_feedback}.yaml` | quality gates | `src/quality/gate.py`, imported only by `scripts/generate.py` |
| `config/quality.yaml`, `config/strategy.yaml`, `config/content_matrix.yaml`, `config/intelligence.yaml`, `config/platforms.yaml` | core-looking configuration | legacy path only |
| `config/prompts/visibility/*` | visibility framework | `scripts/generate_and_publish_visibility.py` only |
| `config/never_blank/wednesday_golden.yaml`, `config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml` | Wednesday | frozen; out of scope |

## 6. `business_strategy.json` dependency map

447 lines. Every top-level key traced to its consumer. The file is **not
deleted or altered by this task**.

### 6a. Field-by-field classification

| Path in file | Consumed by | Classification |
|---|---|---|
| `schema_version`, `configuration_id`, `configuration_version`, `status` | `ConfigurationIdentity`, run/package identity checks, `require_active` | **machine/runtime data** — keep as machine data |
| `business.*` | `ResearchStrategyView`, `DecisionLensEditorialStrategyView` — carried, never rendered into a Monday prompt | **human product strategy** (identity); currently inert on Monday |
| `products_services[]` | `ResearchStrategyView` only; never reaches a Monday prompt | **human product strategy**, unresolved: nothing on Monday uses it |
| `default_audience_id`, `audiences[]` | `_select_audience` (`execution_context.py:146`); `audience_selection` reaches `decision_lens_lite` and `never_blank_voice` prompts | **human product strategy** — audience definition |
| `audiences[].selection_terms` | alias matching for the discovery label | **machine/runtime data** (a lookup table), derived from the human audience names |
| `positioning.statement`, `positioning.proof_points` | rendered into the `decision_lens_lite` prompt as an evidence boundary | **human product strategy** |
| `positioning.expertise`, `positioning.value_propositions` | carried in the typed view; never rendered | **human product strategy**, unresolved — no consumer |
| `commercial.priorities` | `ResearchStrategyView`; never rendered on Monday | **obsolete/unresolved** on this path |
| `content.objectives`, `content.territories` | rendered into `decision_lens_lite` | **human product strategy** |
| `brand_editorial.voice`, `.editorial_principles`, `.preferred_claims` | rendered into `never_blank_voice`; `preferred_claims` also into `decision_lens_lite` | **human product strategy** — belongs in Markdown |
| `brand_editorial.prohibited_claims` | rendered into prompts **and** used as an exact-match fail-closed guard (`never_blank_voice.py:226`) | **dual**: the text is human strategy; the guard is a generic mechanism |
| `brand_editorial.legal_factual_reputational_restrictions` | rendered into `decision_lens_lite` and `never_blank_voice` | **human product strategy** |
| `calls_to_action[]` | `cta()` lookup; the selected CTA's `intent`/`rules` render into `never_blank_voice` | **human product strategy**. On Monday only `cta_id: "none"` is ever selected, so the other four are unreachable for this role |
| `channels.wix.{article_rules,metadata_rules,link_rules,cta_rules}` | `_wix_rules()` → composer `long` prompt | **human product strategy**; `article_rules` **duplicates** `_WORD_RANGE["long"]` and the composer's one-idea rule |
| `channels.linkedin.{opening,length,formatting,link,cta}_rules` | `_linkedin_rules()` → composer `medium` prompt | **human product strategy**; `formatting_rules` duplicates the deterministic hashtag rule in `hashtags.py` |
| `channels.*.visual_rules` | `VisualStrategyView` — carried; the visual contract does not render them into the image prompt | **unresolved** — declared, not enforced |
| `prompt_rule_references[]` | only `active-campaign-strategy.version` is compared | **obsolete** — six of seven entries point at files nothing reads (§5a) |
| `editorial_roles[].role_id` | `resolve_editorial_role`, `AssignmentRecord.editorial_role` | **machine/runtime data** (an identifier) |
| `editorial_roles[].intent` | first line of `render_editorial_role_rules` | **human product strategy** |
| `editorial_roles[].structure` (9 items) | rendered into both surface prompts | **human product strategy** — and it **conflicts** with `platform_composer._SYSTEM_PROMPT:121`, which states a different arc |
| `editorial_roles[].forbidden` (13 items) | rendered into both surface prompts | **human product strategy**; partially duplicates `hook_engine` and `story_assembly` prohibitions |
| `editorial_roles[].eligibility_criteria` (5 items) | the **only** input to `judge_source_eligibility` | **human product strategy** — the narrow contract the issue supersedes |
| `editorial_roles[].wix_rules`, `.linkedin_rules` | surface-scoped prompt appendix | **human product strategy** |
| `editorial_roles[].require_source_transparency` | switches `validate_source_transparency` on | **machine/runtime switch** over a human requirement |
| `editorial_roles[].decision_policy` | selects the gate branch (`gap.py:1284`) | **machine/runtime data**, but encoding an R1 product decision |
| `editorial_roles[].cta_mode` | overrides `strategy.json.primary_cta_intent` | **human product strategy** — and a **duplicate authority**: two files declare the CTA and the role silently wins |
| `editorial_roles[].closing_contract` | selects composer validator + echo mode | **machine/runtime data** naming a human editorial contract |
| `editorial_roles[].acceptance_rubric_path` / `_identity` | rubric selection | **machine/runtime data**; Monday declares neither, so it silently inherits the shared rubric |
| `editorial_roles[]` (Wednesday entry) | Wednesday only | frozen; out of scope |

### 6b. Summary

- **Genuine machine/runtime data:** identity block, `role_id`, `selection_terms`, `require_source_transparency`, `decision_policy`, `closing_contract`, `acceptance_rubric_*`. Roughly 30 of 447 lines.
- **Human product strategy currently trapped in JSON:** audiences, positioning, content objectives/territories, the whole `brand_editorial` block, CTAs, both channel rule sets, and the entire Monday `editorial_roles[0]` — intent, structure, forbidden, eligibility, surface rules. Roughly 330 lines.
- **Obsolete/superseded:** `prompt_rule_references` (6 of 7), `commercial.priorities` on this path, `channels.*.visual_rules`, the four unreachable CTAs.
- **Duplicated:** word count (JSON + `_WORD_RANGE`), article arc (JSON structure + composer prompt), CTA mode (JSON role + `strategy.json`), corporate-evidence share (20% composer / 20–25% voice checklist), hashtag rules (JSON + `hashtags.py`), listicle and detective prohibitions (JSON forbidden + three Python modules).
- **Unresolved:** `products_services`, `positioning.expertise`, `positioning.value_propositions`, `channels.*.visual_rules` — declared, validated, carried into typed views, and never used on the Monday path.

The file is therefore neither authoritative nor machine data. It is one blob
mixing a small runtime record with the product's entire editorial strategy,
and the strategy half is duplicated against Python in six places.

## 7. The narrow eligibility contract, and everything that depends on it

### 7a. Implementation

1. **Criteria** — `business_strategy.json:374-380`, five statements restricting
   Monday to documented small/owner-led/early-stage cases and declaring
   "Unknown is ineligible".
2. **Carrier** — `src/editorial/source_eligibility.py`. Sends
   `role.eligibility_criteria` plus eleven source fields (`_SOURCE_FIELDS`, :39)
   under fixed instructions (`_INSTRUCTIONS`, :53) to `model_enrich()`. Returns
   a strict `SourceEligibilityVerdict`; anything malformed raises.
3. **Sweep** — `scripts/streams/select_eligible_signal.py`. Walks unused
   candidates in queue order, stops at the first eligible one, records every
   disposition, and exits 0/3/4/5.
4. **Workflow** — `monday_publish.yml:127-180` maps exit 3 to "publish nothing,
   stay green" and every other non-zero code to a visible failure.

### 7b. The 15-candidate behaviour, and every dependency on it

| Dependency | Where | Nature |
|---|---|---|
| `DEFAULT_MAX_CANDIDATES = 15` | `select_eligible_signal.py:63` | default sweep depth |
| `MAX_CANDIDATES_CEILING = 15` | `select_eligible_signal.py:69` | **enforced**, not clamped: `1 <= n <= 15` or exit 1, before any queue read (`:107`) |
| `candidates[: args.max_candidates]` | `:145` | the actual truncation |
| `audit["truncated"]` → exit 5 | `:140`, `:225`, `:244` | an incomplete search must not read as "nothing eligible" |
| Cost rationale | `src/run/call_budget.py:12-15` | the selector is explicitly *outside* the per-run budget; 15 + the circuit breaker is its only bound |
| Provider circuit breaker | `source_eligibility.py:237` + `select_eligible_signal.py:151-184` | a provider-scope failure stops the sweep early, which also produces exit 4 |
| Workflow exit-code handling | `monday_publish.yml:166-178` | 3 → green empty run; 4/5 → red |
| Tests | `test_selector_circuit_breaker.py:419-420` pins both constants to 15; `:435` proves out-of-bound values are refused before any model call; `test_monday_stream.py:1214-1262` exercises 1, 2 and 15 | behavioural lock |
| From-package bypass | `monday_publish.yml:144-157` | a retry skips the sweep entirely — eligibility was judged in the source run |

**What the number actually is:** a cost bound on a per-candidate paid model
call, not an editorial rule. It exists because each candidate costs one call
and the sweep runs outside the run budget. #237 traces it to its origin: a hard
Release 1 cost bound from #171 (`ae96c07`), refused rather than clamped because
the selector is the largest pre-run call multiplier.

**What is entangled with it:** only the narrow criteria make the sweep
expensive, because a narrow contract rejects most of a queue that was itself
filtered for a different (presence-shaped) purpose by
`config/research_sources.yaml` and `config/prompts/research/signal_selector.yaml`.
Keeping the supply's presence bias while widening the role would produce
eligible-but-unusable candidates.

**Correction, from #237.** An earlier version of this section also said that
widening the contract "reduces sweep depth naturally". That is wrong, and §7d
is why: the bound is not a depth the sweep chooses, it is a fixed window over a
queue ordered oldest-first, and no widening moves the window. Widening changes
which of the same 15 head candidates are judged eligible; it cannot make
candidate 16 reachable.

The issue directs that the narrow contract is superseded and that the
15-candidate mechanism must not be preserved *around* it. §10 of the target
document treats the bound as what it is — a cost control belonging to the
runtime — and removes the editorial contract it currently defends. §7d adds a
second requirement that this trace did not originally carry: removing the
editorial contract is **not sufficient**, because the bound also blocks the
queue independently of what the criteria say.

### 7c. An inconsistency found while tracing (not part of the brief, recorded because a migration would inherit it)

The selector reads candidates **only** from `data/research/signals_active.jsonl`
(`select_eligible_signal.py:101`), while the run loads the chosen signal from
`data/research/selected_signals.jsonl` **first**, falling back to
`signals_active.jsonl` (`gap.py:322-330`, `:373`). If a `SIGNAL_ID` appears in
both files with different content, Monday judges eligibility on one record and
publishes from another. No test covers the divergence. Flagged for the owner;
no change made.

### 7d. The window never advances (#237)

`docs/MONDAY_SELECTION_HEAD_OF_LINE.md` on `orch/237` establishes that the
15-candidate bound is not only a cost control — combined with two other
properties it is a standstill. All three are re-derivable from tracked files;
#237 marks them `VERIFIED-IN-REPO`.

1. **Queue order is append order, oldest first.** `_load_candidates` walks
   `signals_active.jsonl` in file order, so `DATE_FOUND` is non-decreasing down
   the file — line 1 is `2026-06-22`, line 105 is `2026-09-15`.
2. **Rejections are never recorded.** A rejected candidate is skipped, not
   persisted. Consumption is written only after a successful publication, so no
   file remembers that a candidate was judged ineligible.
3. **Therefore the same prefix is re-judged every week.** Of 105 signals, 5 are
   published, leaving 100 unused. Positions 0–14 — the exact window one Monday
   can afford — are file lines 5 and 7–20. **The 73 September signals occupy
   positions 27–99 and no Monday can reach them.**

Monday 2026-09-14 (run `34868092082`) ended at exit 5 with all 15 judgments
completed and no provider failure. #237's conclusion is that this is "the
expected weekly outcome, not an incident".

Three consequences for this task:

- **The bound has a second dependency §7b did not list**: the "rejections are
  only skipped" contract. Any migration that re-declares `MAX_CANDIDATES` as a
  pure cost control inherits head-of-line blocking unchanged.
- **Freshness is inversely correlated with reachability.** The newest signals
  are the least reachable ones. A widened eligibility contract authored in
  Markdown would be evaluated against the oldest 15 rows in the queue and
  nothing else.
- **The eligibility logic did not regress.** #237 checks this three ways: the
  two rules that produced all 15 rejections are byte-identical to their text at
  `3fc0eff` (#142); Monday published successfully under them on 2026-08-24; and
  `pattern_extractor`'s "protagonist always owner" is **not** on the selection
  path — `select_eligible_signal.py` calls `judge_source_eligibility` and
  nothing else. The defect is supply and order, not judgment.

#237 records three owner options and explicitly takes none: **A** change
selection order or persist per-role rejections; **B** operator unblock for one
Monday by dispatching an explicit `signal_id` (a live run, needing
authorization); **C** role-aware supply (#202). The target document reconciles
these against its own decisions rather than re-deciding them.
