# Monday — target architecture (Issue #240, deliverables 7–12)

Design only. Nothing here is implemented, and nothing here should be
implemented before owner review and before #233 merges.

Evidence for every claim about current behaviour is in
`reports/monday-architecture/monday_current_state_trace.md`; section numbers
below refer to it as *(trace §n)*.

The audit inputs the issue requires — #233's repository-wide findings and the
available editorial-wiring evidence — are incorporated in **trace §0**, and
this document is reconciled against them. Where an audit finding changed a
proposal rather than merely supporting it, the section says so in place:
§8.3 (F1/F2), §9 (F9d, F6c, F8d), §10 steps 0/5/6 (F5, #237), §11 (audit
§9.1–9.3, F9a), and §12 D1/D9/D12/D13 (#237, F4d).

The intended shape, from the issue:

```
human-readable Markdown strategy → loader/compiler if needed →
machine/runtime representation only if useful → reusable engine capabilities →
Monday output
```

## 7. Proposed human-readable Markdown source of truth

### 7.1 The two problems the structure has to solve

1. **One owner per rule.** The trace found the same rule stated in up to four
   places — word count in JSON and `_WORD_RANGE`; the article arc in the role's
   `structure` and in `platform_composer._SYSTEM_PROMPT`; corporate-evidence
   share at 20% in one module and 20–25% in another; the CTA mode in
   `strategy.json` and in the role, with the role silently winning (trace §3.1,
   §6a). A structure that does not assign exactly one owner per rule will
   reproduce this.
2. **Shared vs Monday-specific.** Most of what is in Monday's role today is not
   Monday-specific: prohibitions on listicles, on invented sources and on
   detective narration are Never Blank rules. Duplicating them into Monday is
   how Wednesday and Monday drifted apart.

### 7.2 Proposed layout

Nine files. Two directories. No file exists unless a human would actually open
it to change something.

```
strategy/
  never-blank/                  ← shared: one owner for every shared rule
    identity.md                 ← who the publisher is; the brand token; the Echo concept
    audience.md                 ← who is being written for, and what they already know
    worldview.md                ← the optional lenses, incl. Compound Presence, as lenses
    article-shape.md            ← the shared arc, hook register, reader effects, evidence limits
    channels.md                 ← per-surface behaviour: Wix and LinkedIn
    prohibited.md               ← every prohibition, once
  monday/                       ← Monday only: what makes Monday not Wednesday
    purpose.md                  ← what Monday is for; what a Monday article must leave behind
    signals.md                  ← topics/sources/signals; what makes a signal useful; research intent
    editorial.md                ← editorial objective, structure if it differs, evidence requirements
```

**Not created:** a Monday voice file, a Monday prohibitions file, a Monday
channel file. If Monday needs to differ from a shared rule it says so in
`monday/editorial.md` with an explicit override block; if it says nothing it
inherits. Inheritance-by-silence is what keeps the shared rules genuinely
shared.

### 7.3 What each file owns, and where its content comes from today

| File | Owns | Sourced from |
|---|---|---|
| `never-blank/identity.md` | publisher identity; the literal brand attribution token; what the Echo is and when it is earned | `business_strategy.json.business`, `.positioning`; `formatting._SIGNATURE_PREFIX`; `platform_composer.BRAND_ATTRIBUTION`; `never_blank_voice._SYSTEM_PROMPT` §1; `config/brand_voice.md` |
| `never-blank/audience.md` | the audiences, their problems, decision factors, objections; what the reader is assumed to already know | `business_strategy.json.audiences`; `reader_context._HOUSEHOLD_NAMES`; `config/brand_voice.md` "The Reader" |
| `never-blank/worldview.md` | Compound Presence and the other lenses, explicitly as lenses the material may or may not earn | `strategy/worldview.md`, `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md`, `strategy.json.compound_presence_role`, `decision_lens_lite` legacy key prose |
| `never-blank/article-shape.md` | the shared arc; hook register; reader effects; the corporate-evidence limit **as one number**; length ranges | `platform_composer._SYSTEM_PROMPT:121`, `_BLOCK_TABLE`, `_WORD_RANGE`, `_FORMAT_CONSTRAINTS`; `hook_engine._HOOK_TYPES`; `narrative_spine._VALID_FEELINGS`; `never_blank_voice` checklist |
| `never-blank/channels.md` | Wix and LinkedIn behaviour: openings, length, formatting, links, hashtags, visuals, what the system appends | `business_strategy.json.channels.*`; `hashtags.BRANDED_HASHTAGS` / `PROHIBITED_HASHTAGS`; `config/schedule.yaml.channel_behavior` |
| `never-blank/prohibited.md` | every prohibition, once | `business_strategy.json.brand_editorial.prohibited_claims`, `.legal_factual_reputational_restrictions`, role `forbidden`; `hook_engine` forbidden openers; `discovery_builder._contains_detective_template`; `story_assembly` banned construction; `output_guard._DICTIONARY_OPENING_PATTERNS` |
| `monday/purpose.md` | what Monday is for; its governing question; what a reader should leave with; the CTA/closing decision | role `intent`, `cta_mode`, `closing_contract`; `monday_publish.yml` header comment |
| `monday/signals.md` | what Monday operates on; what makes a signal useful; how research should read the intent; how far to look | role `eligibility_criteria`; `config/research_sources.yaml.signal_categories` / `avoid_categories`; `config/prompts/research/signal_selector.yaml`; `pattern_extractor` reject conditions |
| `monday/editorial.md` | editorial objective; protagonist; Monday's structure where it differs; evidence/factual requirements; review criteria | role `structure`, `wix_rules`, `linkedin_rules`, `require_source_transparency`; `pattern_extractor._SYSTEM_PROMPT`; `config/prompts/editorial_acceptance/never_blank.yaml` criteria |

### 7.4 The coverage the issue asks for

| Required | File |
|---|---|
| Monday purpose | `monday/purpose.md` |
| audience | `never-blank/audience.md` (Monday may narrow it in `monday/purpose.md`) |
| topics/signals/source guidance | `monday/signals.md` |
| how research interprets the intent | `monday/signals.md` |
| what makes a signal useful | `monday/signals.md` |
| evidence/factual requirements | `monday/editorial.md` |
| editorial objective | `monday/editorial.md` |
| writing/voice requirements | `never-blank/identity.md` + `never-blank/article-shape.md` |
| Monday-specific article structure | `monday/editorial.md` (omit to inherit) |
| channel behaviour | `never-blank/channels.md` |
| prohibited behaviour | `never-blank/prohibited.md` |

### 7.5 Authoring format

Plain Markdown. Headings are the addressable unit — a loader resolves
`never-blank/channels.md#linkedin` the way a reader would. Bullets are rules;
prose is context; a fenced block marked `override` is the only way a
Monday file may contradict a shared file, and it must name what it overrides.

No front-matter, no YAML islands, no key/value tables where a sentence works.
The test of the format is whether a non-programmer can open
`monday/signals.md`, delete the sentence restricting Monday to small
businesses, and have the next run behave differently. That is the acceptance
criterion for the whole design.

## 8. Proposed generic runtime architecture

### 8.1 Shape

```
strategy/**.md                         authored by a human, the only editorial authority
        │
        ▼
  StrategyLoader          reads Markdown → StrategyDocument (headings, rules, overrides)
        │                 no product vocabulary; knows headings, bullets, override blocks
        ▼
  StrategyResolver        shared + stream, applies overrides → ResolvedStrategy
        │                 records which file and heading every rule came from
        ▼
  strategy_resolved.json  run-scoped ARTIFACT, never authored by hand
        │                 provenance per rule: file, heading, content hash
        ▼
  Capabilities            generic mechanics, each taking rules as data
        │   ├─ Judge(criteria, subject)        → typed verdict     [today: source_eligibility]
        │   ├─ Stage(instruction, inputs, schema) → validated dict [today: the 8 editorial modules]
        │   ├─ Compose(surface, rules, article)  → body            [today: platform_composer]
        │   ├─ Review(criteria, article)         → disposition     [today: editorial_acceptance]
        │   └─ Attest(artifact, body)            → pass/stop       [today: source_transparency]
        ▼
  Monday output           Wix article + LinkedIn artifact, unchanged contracts
```

### 8.2 The one rule that makes it generic

**No capability may contain a noun from the product.** A capability may know
about criteria, instructions, schemas, surfaces, word counts and validation. It
may not know about owners, small businesses, presence, hooks-of-six-types, or
Never Blank. Everything it knows about the product arrives as data on the call.

This is not a new principle in this repository — it is already how
`source_eligibility.py`, `editorial_role.py`, `source_transparency.py` and
`sources_of_record.py` are written, and
`test_monday_stream.py::test_no_engine_module_knows_what_monday_means` already
enforces it for nine modules. The target extends the same rule and the same
test to the eight editorial stages, which are today the opposite (trace §3).

### 8.3 Stages become instances, not modules

Today each stage is a Python module whose prompt *is* the product
(`pattern_extractor.py`, `hook_engine.py`, …). In the target, a stage is:

```
Stage(
  stage_id      = "pattern",
  instruction   = <resolved from strategy Markdown>,
  inputs        = <named fields from prior stages>,
  output_schema = <declared field names and types>,
  model_role    = "enrich" | "article" | "social",
)
```

The **schema** stays in code — it is a machine contract between stages, the
kind of derived machine representation the owner contract permits. The
**instruction** never does. So `article_protagonist must be "owner"` stops
being a Python assertion (`pattern_extractor.py:146` — the `src/editorial/`
module, not the unrelated `src/strategy/pattern_extractor.py` of #233's F8d)
and becomes a declared constraint whose value comes from `monday/editorial.md`.

**Bounded by #233's F1 and F2.** The sentence this section used to end on —
that Wednesday could then declare a different protagonist "without forking the
engine, which is exactly the fork that exists today" — claimed more than the
evidence supports. F1 shows Wednesday's declared role is rendered and then
**discarded** before generation: `generate_for_wednesday(signal)` takes one
argument, so no role rules, CTA mode or closing contract reach the Wednesday
generation prompt at all, and F2 shows its Golden profile has no production
caller. Wednesday's divergence is therefore an entire unwired declaration plus
a parallel package, not one assertion in a shared stage.

The design property still holds and is worth stating precisely: a generic
`Stage` removes the *engine-level* reason a stream must fork to change its
protagonist. It does not by itself repair Wednesday, and this task must not be
read as proposing that — Wednesday is paused (§8.6), and F1 is #237's question,
not this one's.

Which stages run, and in what order, is part of the resolved strategy, not a
hard-coded chain in `pipeline.py`. A stream that needs no `reader_context`
omits it and pays for no call.

### 8.4 What `business_strategy.json` becomes

Reduced to machine data only, and **generated**, not authored:

```json
{
  "schema_version": "…", "configuration_id": "…",
  "configuration_version": "…", "status": "active",
  "strategy_source": {"files": [...], "content_hash": "sha256:…"},
  "streams": [{"stream_id": "monday", "decision_policy": "…",
               "require_source_transparency": true,
               "closing_contract": "…", "surfaces": ["wix", "linkedin"]}]
}
```

Identity, provenance and runtime switches — nothing a human edits for
editorial reasons. Everything removed from it moves to Markdown; nothing is
maintained twice. The existing strict Pydantic loader, identity hashing and
`write_business_strategy_snapshot` provenance survive unchanged, because they
are exactly the machine concerns that should remain machine concerns.

### 8.5 What the compiler must guarantee

1. **Provenance** — every resolved rule names its file, heading and content
   hash. A reviewer reading `strategy_resolved.json` can answer "which sentence
   in which file produced this instruction".
2. **Fail closed** — a Markdown file that does not parse, a missing required
   heading, or an override naming a heading that does not exist stops the run
   before any model call. Same posture as `load_business_strategy_configuration`.
3. **No invention** — the compiler never supplies a default for a missing
   editorial rule. Absent means absent.
4. **Determinism** — same files in, same resolved artifact out, byte for byte.
5. **No second authority** — the compiler may not add, reword or re-order
   rules. Anything it would need to add is a gap in the Markdown, to be fixed
   there.

### 8.6 Scope discipline

Monday only. Wednesday and Friday are paused and must not be migrated,
generalized or touched. The capabilities are built generic because that is the
cheapest correct way to build them, not because anything else migrates now.
Wednesday's isolated July package keeps running against the old path until its
own owner decision is taken.

## 9. Files and modules: KEEP / CHANGE / REPLACE / RETIRE

### KEEP unchanged — already generic, already correct

| Path | Why |
|---|---|
| `src/editorial/source_eligibility.py` | criteria carrier; knows no product noun |
| `src/editorial/editorial_role.py` | role identity + deterministic rule rendering |
| `src/editorial/source_transparency.py`, `sources_of_record.py` | attestation against the run's real sources |
| `src/research/**` | directives, retrieval, assessment, READY gate |
| `src/run/**` | run identity, call budget, code identity, decision policy record |
| `src/artifacts/**` | create-once, immutable, identity-verified writes |
| `src/publishing/{preflight,idempotency,package,canonical_url,release_scope,result}.py` | publication lifecycle |
| `src/intake/**` | assignment, audience routing |
| `src/reporting/**`, `src/visual/contract.py` | run report, visual gate |
| `scripts/streams/due_check.py` | generic day/timezone/cron gate |
| `.github/workflows/monday_publish.yml` | **not touched by this task**, and not in the containment block |

### CHANGE — keep the mechanism, take the product meaning out

| Path | Change |
|---|---|
| `src/editorial/platform_composer.py` | `_SYSTEM_PROMPT`, `_BLOCK_TABLE`, `_WORD_RANGE`, `_FORMAT_CONSTRAINTS` become parameters from resolved strategy. The echo-mode and source-citation **validators** stay — they are mechanism. `BRAND_ATTRIBUTION` becomes a resolved value. |
| `src/editorial/pipeline.py` | becomes a generic stage runner over a declared stage list; keeps retry-once, `rejected_sink`, budget semantics |
| `src/editorial/editorial_acceptance.py` | rubric criteria and instructions arrive from Markdown; the load/validate/one-revision machinery stays |
| `src/strategy/business_config.py` | contract shrinks to the machine-only shape in §8.4 |
| `src/strategy/execution_context.py` | typed views become views over `ResolvedStrategy`; identity verification unchanged |
| `scripts/streams/select_eligible_signal.py` | criteria come from resolved strategy; `MAX_CANDIDATES` becomes a declared **cost** bound (§10 step 6) |
| `scripts/generate_and_publish.py` | role resolution replaced by strategy resolution; every other gate untouched |
| `src/content/output_guard.py` | keeps structural guards; the prohibition **lists** come from `never-blank/prohibited.md` |
| `src/publishing/hashtags.py` | keeps deterministic assembly; `BRANDED_HASHTAGS` and `PROHIBITED_HASHTAGS` become resolved values |
| `src/publishing/formatting.py` | `_SIGNATURE_PREFIX` becomes a resolved value shared with the composer |

### REPLACE — the product is the module, so the module goes

| Path | Replaced by |
|---|---|
| `src/editorial/pattern_extractor.py` | `Stage("pattern")`; prompt → `monday/editorial.md`; the `article_protagonist` assertion → a declared constraint |
| `src/editorial/decision_lens_lite.py` | `Stage("lens")`; legacy key names retired with the prose that apologises for them |
| `src/editorial/narrative_spine.py` | `Stage("spine")`; `_VALID_FEELINGS` → `never-blank/article-shape.md` |
| `src/editorial/hook_engine.py` | `Stage("hook")`; `_HOOK_TYPES` and forbidden openers → Markdown |
| `src/editorial/reader_context.py` | `Stage("reader_context")`; `_HOUSEHOLD_NAMES` → `never-blank/audience.md` |
| `src/editorial/discovery_builder.py` | `Stage("discovery")`; detective markers → `never-blank/prohibited.md` |
| `src/editorial/story_assembly.py` | `Stage("story")` |
| `src/editorial/never_blank_voice.py` | `Stage("voice")`; the exact-match prohibited-claim guard survives as a capability |

Replacement means the file stops existing as a product artifact. The schema it
enforced survives as a declared output contract, so downstream field names do
not move in the same step.

### RETIRE — dead, duplicated or superseded

| Path | Reason |
|---|---|
| `business_strategy.json.prompt_rule_references` | six of seven entries name files nothing opens (trace §5a) |
| `strategy/current/strategy.md` | hand-maintained duplicate of `strategy.json`, never read (trace §5b) |
| `strategy/current/strategy.json` | after migration only `strategy_id`/`version`/`started_at` remain live; move to the machine record, retire the campaign prose |
| `validators._REQUIRED_STRATEGY_FIELDS: "compound_presence_role"` | requires the superseded house thesis to exist as a field |
| `decision_lens_lite` legacy keys | `delivery_vs_presence_conflict`, `customer_memory_consequence` |
| `pattern_extractor` field name `visibility_pattern` | retained only as a downstream contract; retire with the stage |
| `config/research_sources.yaml.signal_categories` / `avoid_categories` | presence-shaped supply filter → `monday/signals.md` |
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md`, `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md`, `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md`, `strategy/worldview.md`, `strategy/methodology/*.md`, `strategy/stage2_reference_article_example.md` | **content migrates** into the new structure; the files retire as separate authorities. `docs/SYSTEM_MAP.md` updates to point at the new structure — specifically `:28-30` and `:55-58`, the lines #233's F6c identifies as re-authorizing dead artifacts |
| `config/brand_voice.md` | **content migrates** into `never-blank/{identity,audience,article-shape,prohibited}.md`. Named as a declared prompt rule and read by nothing (trace §5a, #233 F3). Retiring it is **not** file-only: #233's F9d records that `tests/test_cross_platform_overlap_policy.py:326-333` asserts on this file's text, so that assertion has to move to whichever authoring file inherits the rule, in the same change. Otherwise a withdrawn-rule guarantee from #221 is silently dropped |
| `config/prompts/decision_lens/never_blank.yaml` | **decide, do not delete** — Monday does not consult it (trace §5c). Owner decision D3 |

Explicitly **not** retired by this task: `business_strategy.json` itself (the
issue forbids deleting it during investigation; it becomes generated), anything
Wednesday or Friday, `config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml`,
`config/never_blank/wednesday_golden.yaml`.

## 10. Migration order

Ordered so that no step can silently preserve the current product semantics.
The hazard is real: the fastest migration is to paste today's prompts into
Markdown, which would satisfy every structural test and change nothing.

Each step names the thing that must be *seen to change*.

**Step 0 — gate.** #233's Monday-relevant findings **are incorporated** — trace
§0a, and reconciled through this document — so the analytical half of the gate
is discharged rather than deferred. What remains is procedural and one
mechanical prerequisite:

- **#233 merges.** Its deliverables are on `orch/233`, not on `main`. No
  production change here before that lands, so that the repair order the audit
  sets and the migration order below are sequenced against one tree.
- **#233's F5 mechanism fix lands first** — the injectable artifact root of
  audit §9.4, so that `scripts/generate_and_publish.py:320-321` stops creating
  `reports/content_packages/` at import against the process CWD. This is a
  hard prerequisite for step 3 onward, not housekeeping: the §11 tests drive
  real runs, and under the current mechanism every one of them writes run
  artifacts into the tracked repository path. Building T3 before F5 is fixed
  means the test that proves this migration is also the test that regenerates
  the 7,796-file residue F5 describes.
- **F3 is not repaired separately on the Monday path.** #233 ranks F3 third in
  its own repair order, with the option of "load the declared references" into
  the prompt chain. Taking that option for `config/brand_voice.md` or
  `strategy/methodology/*.md` would create a second editorial authority that
  step 1 then has to unpick, which is the exact duplication §7.1 exists to
  prevent. **The durable repair of F3 for Monday is steps 1–3 of this
  migration**; the other #233 option — narrow `prompt_rule_references` to what
  is consumed — is compatible with it and is what step 7 does. This is a
  sequencing claim about the Monday path only, and does not bind #233's
  treatment of F3 for any other consumer.

**Step 1 — author the Markdown from the owner, not from the code.**
Write `strategy/never-blank/**` and `strategy/monday/**` from owner-approved
material. Where such material does not exist, **leave the gap and raise an
owner decision** — do not paraphrase the current prompt into Markdown. This is
the step that decides whether the migration is real.
*Must change:* the corpus of editorial rules, because today's prompts contain
rules nobody approved (trace §3).
*Ships alone.* No code reads these files yet.

**Step 2 — loader and resolver, proven on the files.**
`StrategyLoader` + `StrategyResolver` + `strategy_resolved.json` with
per-rule provenance. Nothing consumes it in production yet.
*Must change:* nothing in output. This step is provably inert.

**Step 3 — one stage, end to end.**
Migrate `platform_composer` first: it is the last stage before output, so a
strategy change is visible in the published artifact in one hop, and its
validators already exist to catch regressions.
*Must change:* editing a sentence in `never-blank/channels.md` changes the
composed body. Proven by the §11 tests, not asserted.

**Step 4 — the gate that currently blocks everything.**
Migrate `pattern_extractor`. Its `article_protagonist == "owner"` assertion is
the single hardest-coded product decision on the path and the reason Wednesday
forked.
*Must change:* a strategy declaring a different protagonist produces a
different article, and the old assertion no longer exists in Python.

**Step 5 — the remaining stages, and the stage list itself.**
`decision_lens_lite`, `narrative_spine`, `hook_engine`, `reader_context`,
`discovery_builder`, `story_assembly`, `never_blank_voice`. The stage list
moves into resolved strategy in this step, not before — moving it earlier
would leave a declared list that nothing could vary.
*Must change:* removing a stage from Monday's declared list removes its model
call from the run.

**Step 6 — selection and supply.**
Eligibility criteria resolve from `monday/signals.md`. The narrow
small-business contract is replaced by whatever the owner approved in step 1 —
**not** widened, not reinterpreted, not defaulted. The 15-candidate bound is
re-declared as what it is, a cost control on a per-candidate paid call, and is
decoupled from the editorial contract it currently defends (trace §7b). The
supply-side presence filter in `config/research_sources.yaml` moves to
`monday/signals.md` in the same step, because widening the role while leaving
the supply narrow produces an empty queue.

**Revised by #237 (trace §7d).** As originally written this step was not
sufficient, and the reason is a defect in the selector that is independent of
the criteria. The queue is ordered oldest-first, rejections are never
persisted, and the bound is a fixed window over the head of that queue — so the
same 15 candidates are re-judged every Monday and positions 15–99 are
unreachable. Today that means the 73 September signals cannot be evaluated at
all. Three consequences bind this step:

- Re-declaring `MAX_CANDIDATES` as a pure cost control **inherits head-of-line
  blocking unchanged**. The bound has a second dependency the trace's original
  §7b did not list: the "rejections are only skipped" contract.
- A widened contract authored in Markdown would be evaluated against the oldest
  15 rows in the queue and nothing else. *Must change* below cannot be
  satisfied by a strategy edit alone, because the candidate set the edit is
  judged against does not move.
- Selection order and rejection persistence are **owner decision D12**
  (#237 option A), not a choice this migration may make on its own. Step 6 is
  blocked on D12 in the same way it is blocked on D1.

*Must change:* the selection audit shows different dispositions for the same
queue, **and** a queue whose head is entirely ineligible no longer produces the
same 15 dispositions the following week.

**Step 7 — reduce `business_strategy.json` to generated machine data.**
Only now, with every consumer reading resolved strategy, does the file shrink
to §8.4 and become generated. Its identity hash, snapshot and provenance chain
are preserved.
*Must change:* the file stops containing editorial prose; hand-editing it no
longer changes an article.

**Step 8 — retire the dead artifacts** listed in §9, and update
`docs/SYSTEM_MAP.md` to point at the real authority.

Ordering constraints that must not be relaxed: 0 before everything, including
its F5 prerequisite before step 3 (the §11 tests drive real runs); 1 before 2;
3 and 4 before 5; 5 before 6 (a widened contract with the old engine still
asserting `owner` would fail closed on exactly the signals it newly admits);
6 before 7; 7 before 8.

Step 8 also inherits the `config/brand_voice.md` retirement dependency in §9:
the assertion in `tests/test_cross_platform_overlap_policy.py:326-333` moves
with the content, in the same change, or a #221 guarantee is dropped silently.

## 11. Tests that prove behaviour, not file existence

The current suite is strong on wiring and weak on effect. It proves that role
rules reach the composer through a real call
(`test_monday_stream.py::test_the_role_reaches_composition_through_the_real_call`)
and that the Echo contract is structurally enforced
(`test_monday_echo_contract.py`). It does **not** prove that changing a
strategy file changes what the model is asked or what comes out — the
entrypoint suites mock `generate_article` wholesale
(`test_monday_stream.py::_run_with_role`).

The required chain is `human Markdown → runtime → actual model prompt or
control decision → output`. Five test classes, each written so that it fails if
the migration is cosmetic.

**Relation to #233's proposed guardrail.** #233 §9 proposes a repository-wide
mechanism for the same problem: a manifest (`config/product_config_manifest.yaml`)
declaring every artifact that claims to govern the product with a `status`, one
parametrized test that makes `status: wired` cost something, and one
reachability test that refuses unclassified artifacts. These are not competing
designs, and this task should not build a second mechanism:

- **T1 is the Monday instance of audit §9.2.** #233's version parametrizes over
  manifest entries and asserts a distinctive value reaches
  `chat.call_args.kwargs["user"]`; T1 parametrizes over the authoring files of
  §7.2 and asserts a *mutation* propagates. The mutation form is the stronger
  of the two and should be the one adopted where both apply — a value that is
  present in both the file and the prompt can be a coincidence of vocabulary; a
  value that appears only after the file is edited cannot.
- **T4 subsumes audit §9.3 for the migrated surface.** Once editorial rules
  live in `strategy/**.md`, "unclassified artifact" and "rule duplicated
  between Markdown and Python" are the same failure.
- **The manifest still has a job after this migration**, for the artifacts this
  task does not touch: `config/visual_system.yaml`, the research prompts,
  `config/schedule.yaml`, and everything on the Wednesday and Friday paths.
  §7.2's files should be manifest entries too, so one list answers "what claims
  to govern the product".
- **F9a is the anti-pattern these replace.** `test_never_blank_business_config.py:80-86`
  asserts `resolved.is_file()` over the declared references; it belongs in the
  "must not be accepted as proof" list below, and #233 reaches that conclusion
  independently. If this migration lands without deleting or replacing that
  assertion, the existence check outlives the thing it was checking.

### T1 — Markdown edit changes the prompt (mutation, not assertion)

Take the real strategy files, mutate **one sentence** in a fixture copy, run
the real stage with a capturing transport, and assert the captured prompt
differs in exactly the mutated way.

```
def test_changing_the_channel_rule_changes_the_composer_prompt(tmp_path):
    files   = copy_strategy(tmp_path)
    before  = captured_prompt(resolve(files), surface="linkedin")
    edit(files / "never-blank/channels.md", "short paragraphs", "single-sentence paragraphs")
    after   = captured_prompt(resolve(files), surface="linkedin")
    assert "single-sentence paragraphs" in after
    assert "single-sentence paragraphs" not in before
```

Parametrized over every file in §7.2. A file no mutation can reach is a file
nothing reads — the test that finds the next `prompt_rule_references`.

### T2 — Markdown edit changes a control decision

Not a prompt: a branch. Same mutation technique, asserted on behaviour.

- Changing the eligibility sentence flips a fixed candidate's disposition in
  `monday_selection.json` under a stubbed judge.
- Changing the CTA declaration changes which CTA rules reach `never_blank_voice`.
- Changing `require_source_transparency` changes whether
  `validate_source_transparency` runs.
- Removing a stage from the declared list removes its transport call.

### T3 — Markdown edit changes the output

The full chain with a scripted transport that echoes the instruction it was
given. Assert the published Wix body and LinkedIn artifact reflect the edited
rule. This is the test the current suite has no equivalent of, because it mocks
the generator.

**Prerequisite, from #233's F5.** T3 drives the canonical entrypoint, and
importing it is today enough to create `reports/content_packages/` in the
tracked tree (`scripts/generate_and_publish.py:320-321`); a run then writes real
run directories there. T3 must not be written until the artifact root is
injectable (audit §9.4, §10 step 0), or the test that proves this migration
becomes a new source of the residue F5 measured at 7,796 files.

### T4 — no product semantics survive in code

Extend `test_no_engine_module_knows_what_monday_means` to the migrated stages,
and add the inverse: for a sampled set of rules in the Markdown, assert the
rule's distinctive phrasing appears in **exactly one** authoring file and in
**no** `.py` file. This is the duplication test the current architecture would
have failed in six places (trace §6b).

### T5 — provenance is real

For one run, assert every instruction in `strategy_resolved.json` names a file,
a heading and a content hash; that the hash matches the file on disk; and that
an override resolves to the overriding file. A rule with no provenance is a
rule the compiler invented — §8.5 rule 5 made falsifiable.

### What must *not* be accepted as proof

A test asserting a Markdown file exists. A test asserting a heading is present.
A test asserting a rule's text appears in a resolved artifact without following
it to a prompt, a branch or a body. Each would pass on a migration that changed
nothing.

## 12. Genuine owner decisions still required

These are decisions, not gaps to be filled by inference. Per the issue's
instruction, no replacement editorial strategy is invented here.

**D1 — What replaces the superseded eligibility contract.**
The narrow "documented small-business case" contract is superseded (issue §7).
Nothing in the repository states what Monday may now start from. Step 6 cannot
proceed without an owner answer. *Owner must state:* what source/signal
categories Monday may operate on, and what makes a case ineligible.
*Sharpened by #237:* the current criteria are not failing by accident — 12 of
15 rejections on 2026-09-14 were "no specific company" and 3 were "currently
large company", both consistent with the criteria as written, and the criteria
are byte-identical to their #142 text under which Monday published on
2026-08-24. D1 is therefore a decision about what Monday is *for*, not a repair
of a regression.

**D2 — Compound Presence: lens, or nothing.**
`strategy.json.compound_presence_role` requires it; `validators` requires the
field; `hashtags.BRANDED_HASHTAGS` appends `#CompoundPresence` to every
LinkedIn post; #157 already removed it as a publication gate; Monday's role
forbids "forcing Compound Presence onto a story it does not fit". Four
positions in one repository. *Owner must state:* is it an optional lens, or is
it retired.

**D3 — The Decision Lens.**
149 lines of versioned Release 1 judgment policy that Monday does not consult,
under `decision_policy: "role_bounded_r1"` described in code as pending "R2
reconciliation in #151". *Owner must state:* does Monday reinstate it, adopt a
reduced form, or retire it. The target treats all three as viable; the file is
not deleted meanwhile.

**D4 — Which article arc is authoritative.**
The role declares a nine-beat structure; `platform_composer._SYSTEM_PROMPT:121`
declares a ten-beat arc. Both reach the same call. *Owner must state:* one arc,
and whether Monday differs from the shared one.

**D5 — Corporate evidence share.**
20% in the composer, 20–25% in the voice checklist, "at most ONE evidence item"
in the discovery builder. *Owner must state:* one limit, in one place.

**D6 — Who reviews the LinkedIn artifact.**
Editorial acceptance reviews only the Wix long-form; the LinkedIn body is
composed, and re-composed after revision, but never reviewed. *Owner must
state:* is that intended.

**D7 — The audience trio.**
Three audiences are configured; Monday always resolves to the default because
the discovery label rarely names one (`audience_routing.py`). *Owner must
state:* does Monday address one audience or select per article.

**D8 — Branded hashtags.**
Three fixed tags precede every LinkedIn post, one of them the disputed house
thesis. *Owner must state:* keep, change, or make them article-specific.

**D9 — The supply's editorial filter.**
`config/research_sources.yaml` (`signal_categories`, `avoid_categories`) and
`config/prompts/research/signal_selector.yaml` decide, a day earlier, what
Monday will ever see. They are shaped by the superseded presence thesis and are
shared with other consumers. *Owner must state:* does Monday get its own
declared supply intent, or is the shared supply re-approved.
*This is #237's option C (role-aware supply, #202),* and #237 quantifies the
mismatch: 82 of the 100 unused signals carry `"REAL_COMPANY_EXAMPLE": null`,
and most of the 18 that name a company name a large one. #237 also warns that
field is a weak proxy and must not be read as an eligibility count — the
2026-08-24 winner is itself one of the 82.

**D10 — The queue divergence.**
The selector judges from `signals_active.jsonl`; the run loads from
`selected_signals.jsonl` first (trace §7c). *Owner must state:* one source of
truth for the Monday queue.

**D11 — Russian-language strategy material.**
`strategy/worldview.md` is the only strategy artifact in Russian and declares
itself the file all others derive from. *Owner must state:* which language the
authoring files are in, and whether that content is authoritative.

**D12 — Selection order and rejection persistence.**
New, from #237 (trace §7d). Monday's selector re-judges the same 15-candidate
head every week because the queue is oldest-first and rejections are only
skipped, never recorded. The 73 September signals sit at positions 27–99 and no
Monday can reach them. This is a defect in the *mechanism*, so unlike D1 it
does not resolve itself when the strategy moves to Markdown — and it blocks
step 6 just as hard. #237's option A is "walk newest first, or persist per-role
rejections"; it notes that either relaxes the current "rejections are only
skipped" contract and changes selection semantics. *Owner must state:* whether
the window advances by order, by persisted rejections, or not at all — and if
not at all, that Monday's reachable supply is the oldest 15 unpublished
signals, permanently. #237's option B (dispatch an explicit `signal_id` to
unblock one Monday) is a live run and is **out of scope here**: this task's
authorization is `controlled_live: false`.

**D13 — Whether Monday's strategy governs Monday's output.**
New, from #233's F4d (trace §1a). `daily_signal_research.yml` runs every day and
force-disables publishing only on Wednesday; on a Monday its Stage 11 publish
decision is the value of a secret not visible in the repository, and that path
published live to Facebook, Instagram and Telegram on 2026-09-06/07 (#159
forensics, `src/publishing/release_scope.py:12-18`). Everything this document
proposes governs `monday_publish.yml`. *Owner must state:* whether the daily
path may publish on a Monday at all, and if so, whether it is in scope for the
Markdown strategy or is explicitly declared a separate, non-editorial surface.
Until that is answered, "Monday output" in §8.1 means the canonical run's Wix
article and LinkedIn artifact, and nothing else.

---

**STOP.** Per the issue: architecture and design only. No production change is
proposed for execution before owner review of this document and the decisions
in §12, and no implementation step may begin before #233 merges and its F5
mechanism fix lands (§10 step 0).
