# Monday — proposed target architecture

Design deliverable for Issue #240, deliverables 7–12. **Proposal only. Nothing
here is implemented, and nothing here is a decision.** No production file is
changed by this issue; `strategy/current/business_strategy.json` is not modified
and not deleted.

Every claim about what exists today is established in the companion trace,
[`reports/monday-architecture/MONDAY_CURRENT_STATE.md`](../../reports/monday-architecture/MONDAY_CURRENT_STATE.md),
against `58afe47`. Read it first; this document is only the proposal, and every
section below is anchored to it.

Scope is Monday. Wednesday and Friday are paused: no Wednesday or Friday file is
proposed for change, and the design is deliberately constrained so that
Wednesday can later become a second document against the same engine rather than
a second engine.

---

## 7. Proposed human-readable Markdown source of truth

### 7.1 The shape

Three Markdown files, one directory, no per-stage files:

```
strategy/never-blank/
  never_blank.md      shared: identity, voice, evidence, the Echo, CTAs, prohibitions
  channels.md         shared: Wix and LinkedIn behaviour, lengths, closing shape, hashtags
  streams/
    monday.md         Monday only: purpose, audience, signal guidance, objective, structure
```

Three files replace: eight blocks of hand-maintained product strategy inside
`business_strategy.json` (trace §6), the product semantics currently spread
across eleven Python modules (trace §3), and six Markdown documents the runtime
never opens (trace §5). It is a reduction in the number of places a rule can
live, which is the point of the "avoid configuration-file proliferation"
constraint — the count that matters is *authorities per rule*, and the target is
one.

Everything the issue says a human must be able to understand and edit has
exactly one home:

| What a human edits | File | Section |
|---|---|---|
| Monday purpose | `monday.md` | `## Purpose` |
| Audience | `monday.md` (Monday's reader) → may defer to `never_blank.md` | `## Audience` |
| Topics / signals / source guidance | `monday.md` | `## Signals` |
| How research interprets the intent | `monday.md` | `## Signals → Research brief` |
| What makes a signal useful | `monday.md` | `## Signals → Useful` |
| Evidence / factual requirements | `never_blank.md` | `## Evidence` |
| Editorial objective | `monday.md` | `## Objective` |
| Writing / voice requirements | `never_blank.md` | `## Voice`, `## Writing` |
| Monday-specific article structure | `monday.md` | `## Structure` |
| Channel behaviour | `channels.md`, overridable per stream | `## Wix`, `## LinkedIn` |
| Prohibited behaviour | `never_blank.md` `## Never do`, plus `monday.md` `## Never do` for stream-specific additions |

### 7.2 The rule that keeps it from becoming a second JSON file

**A heading is the contract.** Each document carries YAML front matter for
identity and for values the engine must have as data — ids, versions, numeric
bounds, enumerations, the active channel list — and headed prose for everything
editorial. The compiler knows the full set of permitted headings per document
kind. An unknown heading fails the build; a missing required heading fails the
build. A typo therefore turns into a red check rather than a silently dropped
rule — which is precisely the failure mode of `2466611`, where deleting the
loader for `NEVER_BLANK_EDITORIAL_STYLE.md` broke no test (trace §0b).

Sketch of `monday.md`, showing the two registers:

```markdown
---
stream_id: never-blank-monday
version: "1"
extends: never_blank
channels: [wix, linkedin]
cta_mode: none
closing_contract: branded_echo_then_sources
hook_candidates_min: 5
investigation_beats: [2, 4]
---

## Purpose
<prose — one paragraph a non-programmer writes>

## Audience
<prose, or "Inherits Never Blank." >

## Signals
### Look for
### Useful
### Not eligible
### Research brief

## Objective

## Structure
- <one bullet per movement; the bullets ARE the composer's structure rules>

## Never do
- <one bullet per prohibition>

## Channels
### Wix
### LinkedIn
```

Front matter holds only values that must be exact for the engine to run.
Everything with editorial meaning is prose under a heading, because prose is
what a non-programmer can write and because the engine's job is to carry it, not
to parse it.

### 7.3 One direction only

```
strategy/never-blank/**.md      human-authoritative; the only place an owner edits
        │  compile  (deterministic, no model call)
        ▼
build/strategy/never-blank/*.json   derived, generated, committed, never hand-edited
        │  load  (strict typed loader, the existing contract extended)
        ▼
runtime strategy objects        frozen, validated, identity-stamped
```

Markdown is edited; JSON is generated. CI regenerates and fails if the committed
JSON differs from the regenerated JSON, so the two cannot drift and nobody is
asked to maintain both — the owner's explicit constraint. The generated JSON
exists because the runtime already depends on a strict typed contract with an
identity hash carried to every boundary
(`src/strategy/execution_context.py:42-90`), and that machinery is correct and
worth keeping. It is a build artifact, not an interface.

Every compiled rule carries an id and a version stamped into the run record, so
a published article can be traced to the exact strategy text that produced it.
That is already how the acceptance rubric works
(`config/prompts/editorial_acceptance/never_blank.yaml:8-9`); the proposal
generalizes it rather than inventing it.

### 7.4 Shared rules have one owner

`never_blank.md` owns what is true of every Never Blank article: the voice, the
evidence and factual requirements, the Echo, the calls to action, the
prohibitions. `monday.md` says `extends: never_blank` and may **add** but not
silently restate. The compiler refuses a stream rule that duplicates a shared
rule verbatim, and records an explicit override when a stream deliberately
replaces one — so "the same strategy maintained twice by hand" is a build
failure rather than a discipline.

This is the rule that dissolves the current duplication directly:
`never_blank_voice.py:61-76` restates `calls_to_action` in prose to a model that
is already being handed `calls_to_action` as data (trace §3); under this rule
there is one text and it is shipped once.

### 7.5 What the Markdown is populated from — and what it is not

Populated from owner-approved material only: the role blocks in
`business_strategy.json:344-396`, the channel rule groups at `:233-305`,
`brand_editorial` at `:149-187`, `calls_to_action` at `:188-232`, and the
Markdown documents the owner already wrote, where a ruling says they win.

**Not** populated by promoting today's Python prompt text wholesale. Much of it
encodes the superseded narrow contract — "Never Blank produces articles for
small business owners — not about corporations", the owner-protagonist
assertion, the "small business" premise in eight separate system prompts (trace
§7.2). Lifting it into Markdown would launder a superseded contract into the new
source of truth and is exactly the accident §10 is ordered to avoid. Where
owner-approved material is insufficient, §12 records a decision instead of an
invention.

---

## 8. Proposed generic runtime architecture

### 8.1 The property to satisfy

> change strategy → the same capabilities execute a different editorial intent

Concretely: with no Python change, replacing `monday.md` with a document whose
protagonist is not the owner, whose mechanism vocabulary is different and whose
article movement is different must produce that article. Today that is
impossible — `pattern_extractor.py:146-150` raises unless
`article_protagonist == "owner"`.

### 8.2 Five capabilities

Every stage on the Monday path is an instance of one of five generic
capabilities, each taking its meaning as data from the compiled strategy. This
is a re-binding of code that already exists, not a new engine.

| Capability | What it does | Configured by | Today's instances |
|---|---|---|---|
| **Judge** | Apply supplied criteria to a supplied subject; return a typed verdict with a bounded reason; fail closed | criteria text, the subject fields the judgment may see, the verdict schema | `source_eligibility`, `research/assessment`, the acceptance reviewer |
| **Derive** | One call producing a declared set of named fields from declared inputs; validate against a declared schema | field names, meanings, per-field constraints, input bindings | `pattern_extractor`, `decision_lens_lite`, `narrative_spine`, `reader_context`, `story_assembly` |
| **Propose and select** | Produce N candidates in a declared vocabulary, select one, prove the selection is one of the candidates | N, vocabulary, selection rules, prohibitions | `hook_engine`, the Echo half of `never_blank_voice` |
| **Compose** | Render a declared block policy into one surface body under declared bounds and a declared closing shape | block policy, length bounds, format rules, closing contract | `platform_composer` |
| **Enforce** | Deterministic validators parametrized by declared values: phrase bans, numeric bounds, structural shapes, citation shapes | the banned phrases, the numbers, the shapes | `output_guard`, the closing-contract validators, `linkedin_composition`, `source_transparency` |

`Judge` is already generic and is the working proof that this shape is
achievable here: `source_eligibility.py` carries the role's criteria to the
model and validates what comes back, and its docstring (`:11-15`) states the
property explicitly — "a different business's roles bring entirely different
criteria through the same code". The other four capabilities are the same move
applied to stages that currently hold their meaning inline.

### 8.3 What stays in Python, permanently

Mechanism, never editorial meaning:

- how a prompt is assembled from a stage contract, and which model routes to it;
- deterministic validators — the *values* they enforce come from strategy;
- fail-closed gates: research readiness, decision-policy authority, acceptance,
  source transparency, composition acceptance, preflight, publisher scope;
- run and configuration identity, create-once artifacts, provenance, the call
  budget as a safety ceiling;
- evidence integrity and provenance generally. Per the issue, these are generic
  mechanics. What counts as a *useful* signal, which sources or topics Monday
  works from, and what the article argues are product decisions and live in
  strategy.

So `platform_composer` keeps its closing-contract validators; the 400–600 range
moves to `channels.md`. `output_guard` keeps `validate_no_duplicate_echo`; the
0.55 threshold and the banned phrases move to `never_blank.md`.
`pattern_extractor`'s field validation stays; `article_protagonist == "owner"`
becomes a declared field constraint the role supplies.

### 8.4 Stage contracts, not stage modules

A stage becomes `run_stage(contract, inputs)`, where the contract is compiled
from the strategy and carries: the instruction text, the input bindings, the
output schema, the vocabularies, the numeric bounds, the prohibitions, and the
stage's id and version. Monday is then *a strategy document plus the existing
engine*. The five capability implementations are the only Python that knows how
a stage runs, and none of them knows what Monday means.

The existing guard `tests/test_monday_stream.py:562-575` — no engine module may
contain the word "monday" — is the right idea applied to the wrong quantity. Its
successor (§11.5) is the same assertion applied to product semantics rather than
to the stream's name.

### 8.5 Source versus signal

Evidence integrity stays generic and unchanged: retrieval from the signal's own
`SOURCE_URL` (`src/research/lifecycle.py:114-127`), assessment, the READY gate
with a named assessor, the transparency check against the run's real sources.
None of that encodes what kind of source Monday works from.

What Monday works from — source categories, topics, what makes a signal useful —
is prose in `monday.md` under `## Signals`, and it is compiled into two
destinations: the admission criteria the selector's `Judge` applies, and the
research brief that shapes supply (§12, D15). Source type is never the editorial
product: `monday.md` may say Monday works from documented cases, from data
releases, or from regulatory changes, and the engine does not care which.

### 8.6 Not a Monday engine

Nothing in §8 is Monday-specific. The capabilities, the contract shape and the
compiler are stream-agnostic; `monday.md` is the only Monday artifact. When
Wednesday is unpaused it becomes `streams/wednesday.md` against the same
binaries — which is why no Monday-shaped abstraction may be introduced now, and
why `pattern_extractor`'s owner-protagonist assertion is the acceptance test for
the whole design rather than a detail.

---

## 9. Files and modules: KEEP / CHANGE / REPLACE / RETIRE

**KEEP** — correct as they are; the design depends on them.

| Artifact | Why |
|---|---|
| `src/editorial/source_eligibility.py` | Already the generic `Judge`. The reference shape. |
| `src/editorial/editorial_role.py` | Already carries role text without interpreting it. Gains a compiled source. |
| `src/strategy/execution_context.py` | Identity hashing and boundary verification are exactly right. |
| `src/research/**`, `src/artifacts/**`, `src/run/**` | Evidence integrity, provenance, budgets — generic mechanics. |
| `src/publishing/release_scope.py` + `tests/test_r1_publish_scope.py` | The authorization-boundary pattern §11 generalizes. |
| `config/prompts/editorial_acceptance/never_blank.yaml` | Already a file-owned rubric with a versioned identity. Its content moves to Markdown; its *pattern* is the target. |
| `src/editorial/decision_lens_evaluator.py` + `config/prompts/decision_lens/never_blank.yaml` | Untouched pending D9. |
| `src/never_blank/**` (Wednesday) | Paused. Not touched. |

**CHANGE** — keep the mechanism, move the meaning out.

| Artifact | Change |
|---|---|
| `src/editorial/platform_composer.py` | `_BLOCK_TABLE`, `_WORD_RANGE`, `_FORMAT_CONSTRAINTS`, the arc, the bans and `BRAND_ATTRIBUTION` become compiled inputs. Validators stay. |
| `src/content/output_guard.py` | Patterns and thresholds become compiled inputs; the matchers stay. |
| `src/publishing/hashtags.py` | The trio, counts, prohibitions and stopwords become compiled inputs (after D7). |
| `src/editorial/linkedin_composition.py` | Length envelope from `channels.md` instead of importing `_WORD_RANGE`. |
| `src/strategy/business_config.py` | Loads the compiled artifact; gains stage contracts. Still the strict typed boundary. |
| `scripts/generate_and_publish.py` | `_R1_COMPOSER_FORMATS` from `channels.md`; sources-of-record and acceptance wiring unchanged except as D10 decides. |
| `src/editorial/editorial_acceptance.py` | Rubric from the compiled strategy; reviser inputs per D10. |
| `src/research/assessment.py` | `JUDGMENT_INSTRUCTIONS` from `never_blank.md` `## Evidence`. |
| `scripts/streams/select_eligible_signal.py` | Criteria already come from configuration. Changes only if D8 changes selection order or persists rejections. |

**REPLACE** — the module is the wrong shape; a capability instance replaces it.

| Artifact | Replaced by |
|---|---|
| `src/editorial/pattern_extractor.py` | A `Derive` instance. **The owner-protagonist assertion (`:85-87,146-150`) and the second eligibility gate (`:89-100`) do not survive as code.** This is the single most load-bearing replacement in the migration. |
| `src/editorial/decision_lens_lite.py` | A `Derive` instance; the three "LEGACY COMPATIBILITY KEY" fields are renamed or retired as part of it (D4 territory). |
| `src/editorial/narrative_spine.py` | A `Derive` instance; `_VALID_FEELINGS` becomes a declared vocabulary. |
| `src/editorial/hook_engine.py` | A `Propose and select` instance; `_HOOK_TYPES` becomes a declared vocabulary. |
| `src/editorial/reader_context.py` | A `Derive` instance with a declared skip list and **one** length value. |
| `src/editorial/discovery_builder.py` | A `Derive` instance with declared bounds and declared bans. |
| `src/editorial/story_assembly.py` | A `Derive` instance; its arc merges into the single ruled arc (D4). |
| `src/editorial/never_blank_voice.py` | A `Propose and select` instance for the Echo plus a `Derive` for the CTA; the restated CTA prose is deleted, not moved. |

**RETIRE** — after the owner rules on D12, and never on static evidence alone.

| Artifact | Disposition |
|---|---|
| `config/brand_voice.md` | Content migrates into `never_blank.md` and `channels.md` where a ruling says it wins (D7 splits it: the file loses on the branded trio and wins on the count). Note: `tests/test_cross_platform_overlap_policy.py:326-334` asserts on its text, and that guarantee has to move with the content, not be dropped. |
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md`, `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md`, `strategy/worldview.md` | Either migrate, or be re-declared as authoring material with an explicit in-band status line saying the runtime does not read them. |
| `strategy/methodology/{strategy_methodology,editorial_strategy,platform_strategy}.md`, `strategy/methodology/evaluation_rules.md`, `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | Same choice, per document. |
| `business_strategy.json` `prompt_rule_references` (`:306-342`) | Removed once every entry is either compiled or reclassified. Until then it remains, unchanged. |
| `business_strategy.json` human blocks (trace §6) | Become **generated** output of the compiler. The file's end state is machine data only — and that end state is reached by proving each dependency, never by deleting the file. |
| `channels.*.visual_rules` (`:264-268`, `:299-303`) | Either wired to the visual boundary or marked not-consumed. They are currently validated, identity-hashed and read by nothing. |

---

## 10. Migration order

Ordered so that no step can accidentally carry the current product semantics
forward. Each step is a separate authorized task; none starts without the
owner's go-ahead, and none is started by this issue.

**0. Prerequisites.** #233 merges. Its F5 fix — make the artifact root in
`scripts/generate_and_publish.py:320-321` injectable — lands first, because the
end-to-end message-capture tests in §11 drive the canonical entrypoint and would
otherwise write run residue into the tracked tree.

**1. Rulings.** §12, recorded in the issue. D1, D4 and D8 block everything
below; the rest block only the steps that touch them. **No rule may be compiled
before it has exactly one ruled value** — this is the whole defence against
laundering the superseded contract into the new source of truth.

**2. One vertical slice, end to end.** `channels.md` `## Wix` → compiler →
generated JSON → loader → the composer's `long` call, with a CI drift check and
one sentinel test from §11.1. Proposed because it is the smallest complete
chain, it produces the published article, and it carries three of the ruled
conflicts (D2, D4, D5). Behaviour changes only where a ruling changed it.

**3. `never_blank.md`, the shared document.** The voice, evidence, Echo, CTA and
prohibition rules — and with them the deletion of the hand-written second copies
in `never_blank_voice.py:61-76`, `output_guard.py:14-31`,
`discovery_builder.py:42-44,67-74` and `platform_composer.py:129-133`. Deleting
the duplicate in the same change that compiles the original is what makes the
step irreversible in the right direction.

**4. `monday.md` — Purpose, Audience, Objective, Structure, Never do.** The
ruled arc (D4) replaces all four existing ones at once. Not one stage at a time:
migrating `story_assembly` while `platform_composer` still carries a different
arc would leave the engine with two, and the second would look like a deliberate
override.

**5. The `Derive` and `Propose and select` stages.** One task per stage, in
pipeline order, each deleting its `_SYSTEM_PROMPT` as it lands.
`pattern_extractor` goes **last** of these, because it is the one whose removal
changes what the pipeline will accept, and it should change only when every
downstream stage already takes its meaning from the ruled strategy.

**6. `monday.md` `## Signals` — the replacement for the superseded eligibility
contract (D1).** After step 5, so that the narrow contract cannot survive inside
`pattern_extractor` while the selector runs the new one. This step also settles
whether the research brief reaches supply (D15) and takes #237's A/B/C (D8) —
the selection window and the admission criteria are decided together, because
changing only the criteria can mask the head-of-line defect (trace §7.3).

**7. `business_strategy.json` becomes generated.** Only after every human block
has a Markdown owner and the drift check has been green across the steps above.
The file is reduced to machine data by generation, not edited down by hand.

**8. Retire the documents (D12)** and remove `prompt_rule_references`.

**9. Only then, Wednesday** — unpaused separately, as a second document against
the same engine. If step 9 requires any Python change beyond adding
`streams/wednesday.md`, the design in §8 failed and should be reworked before
Wednesday is attempted.

---

## 11. Tests that prove the chain, not the file

Each test below captures real model-message construction on the production path.
Per #234 §8, `chat` must be patched **in each stage module's own namespace** —
patching `src.utils.llm_client.chat` intercepts nothing, because every stage
binds the name at import. The repository already has both halves of the
technique: `tests/strategy/test_strategy_semantic_consumption.py:90-112` reads
`chat.call_args.kwargs["user"]` and asserts configured values appear in it, and
`tests/test_r1_publish_scope.py:47-50` enumerates paths and pins what they can
reach.

**11.1 Markdown sentinel → model message.** Write a unique sentinel into a
temporary copy of `monday.md` under a given heading, compile, load, run the
canonical entrypoint with every stage module's `chat` patched, and assert the
sentinel appears in the `system` or `user` of the named stage — and in no other
stage unless the contract says it should. Parametrized over every heading, so a
heading that reaches nothing fails the build. This is what
`test_all_prompt_and_rule_references_resolve_inside_repository` should have been.

**11.2 Markdown → control decision.** Not every rule is prompt text. Change
`cta_mode` in front matter and assert the CTA block disappears from the composer
prompt; change `closing_contract` and assert a different validator runs; change
the active channel list and assert the composer makes fewer calls. Proves the
strategy governs control flow, not only wording.

**11.3 Markdown → output.** With a scripted transport returning a fixed body,
assert the ruled numeric bounds are the ones enforced: a 900-word `long` body
fails when `channels.md` says 400–600, and passes when the same test changes the
document to 700–1000. The failure has to come from the document, not from a
constant.

**11.4 The generic-engine property test.** The acceptance test for §8. Compile a
second, non-Monday strategy document — a different protagonist, a different
mechanism vocabulary, a different movement — and run the same pipeline. It must
produce that article with **zero** Python change. Today this test cannot pass:
`pattern_extractor.py:146-150` raises. It should be written early and expected
to fail, as the tracking signal for the whole migration.

**11.5 No product semantics in the engine.** The successor to
`tests/test_monday_stream.py:562-575`. Over every capability module, assert the
absence of the ruled vocabularies, the ruled numbers and the ruled phrases — by
reading them from the compiled strategy and asserting they do **not** appear in
the module source. A number that must be in two places is a number the strategy
does not own.

**11.6 Compiled-artifact drift.** Regenerate from Markdown in CI and fail if the
committed JSON differs. The one test that makes "edit the Markdown" the only
working way to change behaviour.

**11.7 Duplicate-authority refusal.** Assert the compiler rejects a stream rule
that restates a shared rule without declaring an override — the mechanical form
of "do not maintain the same strategy twice".

**11.8 Every writing call is accounted for.** Run the entrypoint for the Monday
role, record `(module, system, user)` for every call, and assert the set of
modules that made a call is exactly the declared set, and that each carries the
stage id and version of the contract it ran under. This is the test whose
absence let #210 retarget Wednesday's production composer while the test kept
passing against the old one (#234 §6.3), and whose absence let `2466611` delete
a loader with no CI signal.

**11.9 The reviser.** Per D10: if the reviser is to receive role and voice,
force a `revise` verdict, capture the call and assert the sentinels. Fails today
(#234 V5) — deliberately, until D10 is taken.

---

## 12. Genuine owner decisions still required

None of these is taken here, and none is recommended here. **D1, D4 and D8 block
the migration outright.**

| # | Decision | Why it cannot be settled without you | Blocks |
|---|---|---|---|
| **D1** | **What replaces the superseded `documented small-business case` contract?** What source and signal classes may Monday start from, and what makes one useful? | The issue supersedes the narrow contract and forbids inventing a replacement. The current criteria (`business_strategy.json:374-380`), the role's `intent`, its `forbidden` list and `pattern_extractor`'s second gate all encode the old one (trace §7.2). | Steps 5–6 |
| **D2** | Blog length: 400–600, 700–1000, or 600–1200? | Three written authorities disagree (trace §8.1). | Step 2 |
| **D3** | LinkedIn length: 120–220 or 350–600? | Two authorities disagree (trace §8.2). | Step 2 |
| **D4** | **Which article arc is the arc?** Four or five are written down. | Compilation admits one. Every `Derive` stage inherits it (trace §8.3). | Steps 2, 4, 5 |
| **D5** | Corporate evidence share: 20 % or 20–25 %, and is it enforced or advisory? | Two values, neither enforced (trace §8.4). | Step 2 |
| **D6** | The voice self-check: a gate, or removed? | `checklist_pass` only warns (`never_blank_voice.py:184-190`). A declared bar with no gate is neither. | Step 5 |
| **D7** | Hashtags: the fixed branded trio, or `brand_voice.md`'s "NOT a fixed reused set"? And is the LinkedIn count 3–5 or 3–6? | On the trio the code looks right and the document stale; on the count the document agrees with `business_strategy.json:284` and the code does not — the reverse of D2–D4, in the same rule (trace §8.5). | Step 3 |
| **D8** | **Monday selection: does the window advance?** #237's A (change order / persist rejections), B (operator unblock, a live run needing its own authorization), or C (role-aware supply, #202). | Not taken since #237. Until it is, exit 5 every Monday is the expected outcome, and a widened D1 could mask it rather than fix it (trace §7.3). | Step 6 |
| **D9** | Does Monday reinstate the Decision Lens, or is `role_bounded_r1` permanent? | The entrypoint calls the Lens verdict the mandatory business gate in the comment above the branch Monday never takes; the bypass is auditable and #151 is named as the reconciliation (trace §8.8). | Step 7 |
| **D10** | Does the reviser receive the role and the voice? | It rewrites the published article under the rubric alone (#234 V5). Changing it changes which instructions produced shipped prose. | Steps 3–4 |
| **D11** | Is "the owner is always the protagonist" a Monday rule or a Never Blank rule — and is it a rule at all now that the narrow contract is superseded? | It is currently a code invariant in a shared stage (`pattern_extractor.py:146-150`) and the reason a second stream cannot use the engine. Its home decides whether it lands in `monday.md` or `never_blank.md`. | Step 5 |
| **D12** | For each of the seven unread documents: executable contract, authoring material, or retired? | `NEVER_BLANK_EDITORIAL_STYLE.md` was once executable; `brand_voice.md` is declared as a prompt rule; `WORLDVIEW` describes itself as upstream of everything. Three different answers are defensible (trace §5). | Step 8 |
| **D13** | Does Monday's strategy govern everything that publishes on a Monday? | #233 F4d: the daily research path's Monday publish decision is a secret, not a repository fact, and that path has published live. A Monday strategy that governs one of two publishers is not a source of truth. | — |
| **D14** | Does Monday declare its own acceptance rubric, or keep the shared default? | Wednesday declares one (`:442-443`); Monday silently takes `DEFAULT_RUBRIC_PATH`. Under the new structure a stream's rubric is part of its document or explicitly inherited. | Step 3 |
| **D15** | Does Monday's signal guidance reach research supply, or is the disconnection deliberate? | `signal_selector.yaml` admits signals Monday must refuse (#202, trace §7.4). Today no mechanism exists by which a Monday strategy change could reach the research path. | Step 6 |

**Stopped after architecture and design, as the issue requires.** No production
change is implemented or proposed for execution before owner review.
</content>
