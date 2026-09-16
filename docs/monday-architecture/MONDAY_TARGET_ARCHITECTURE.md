# Monday — target architecture (Issue #240, deliverables 7–12)

Design only. Nothing here is implemented, and nothing here should be
implemented before owner review and before the #233 audit deliverables exist.

Evidence for every claim about current behaviour is in
`reports/monday-architecture/monday_current_state_trace.md`; section numbers
below refer to it as *(trace §n)*.

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
being a Python assertion (`pattern_extractor.py:146`) and becomes a declared
constraint whose value comes from `monday/editorial.md`. Wednesday can then
declare a different protagonist without forking the engine — which is exactly
the fork that exists today in `src/never_blank/wednesday_july/`.

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
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md`, `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md`, `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md`, `strategy/worldview.md`, `strategy/methodology/*.md`, `strategy/stage2_reference_article_example.md` | **content migrates** into the new structure; the files retire as separate authorities. `docs/SYSTEM_MAP.md` updates to point at the new structure |
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

**Step 0 — gate.** #233's deliverables exist and its Monday-relevant findings
are incorporated. No production change before this.

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
*Must change:* the selection audit shows different dispositions for the same
queue.

**Step 7 — reduce `business_strategy.json` to generated machine data.**
Only now, with every consumer reading resolved strategy, does the file shrink
to §8.4 and become generated. Its identity hash, snapshot and provenance chain
are preserved.
*Must change:* the file stops containing editorial prose; hand-editing it no
longer changes an article.

**Step 8 — retire the dead artifacts** listed in §9, and update
`docs/SYSTEM_MAP.md` to point at the real authority.

Ordering constraints that must not be relaxed: 1 before 2; 3 and 4 before 5;
5 before 6 (a widened contract with the old engine still asserting `owner`
would fail closed on exactly the signals it newly admits); 6 before 7; 7 before
8.

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

**D10 — The queue divergence.**
The selector judges from `signals_active.jsonl`; the run loads from
`selected_signals.jsonl` first (trace §7c). *Owner must state:* one source of
truth for the Monday queue.

**D11 — Russian-language strategy material.**
`strategy/worldview.md` is the only strategy artifact in Russian and declares
itself the file all others derive from. *Owner must state:* which language the
authoring files are in, and whether that content is authoritative.

---

**STOP.** Per the issue: architecture and design only. No production change is
proposed for execution before owner review of this document and the decisions
in §12, and no implementation step may begin before #233's deliverables exist.
