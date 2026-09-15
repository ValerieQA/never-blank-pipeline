# Never Blank — Repository Reachability and Dead-Artifact Audit

Issue #233. Audited 2026-09-15 against `orch/233` (base `58afe47`).

Machine-readable companions, both under `reports/repository_audit/`:

- `inventory.json` — every tracked path, classified, with its consumer and the evidence.
- `findings.json` — the ranked findings and the repair order, structured so follow-up
  issues can be written from it without re-deriving anything.

This is a forensic record. **Nothing in the repository was repaired by this issue**, and
discovery here does not authorize repair. Where a finding needs a product decision it says
so and stops. In particular, this audit does not touch #231 and does not make its
unresolved product choice, and it defers the Monday/Wednesday prompt-wiring question to
#237, which owns it.

---

## 1. Executive summary

The pipeline's *runtime* is in better shape than its *configuration surface*. Every
scheduled publisher reaches real code, the canonical entrypoint's fail-closed boundaries
are genuinely wired, and the repository already contains two excellent examples of the
guardrail this audit ends up proposing (`src/publishing/release_scope.py` with
`tests/test_r1_publish_scope.py`, and `tests/strategy/test_strategy_semantic_consumption.py`).

What does not hold is the promise that a product-defining file controls the product.

- **The Wednesday editorial role is computed and discarded.** `scripts/generate_and_publish.py`
  renders the declared role's rules into `_editorial_role_rules`, appends the
  sources-of-record block to it, and then calls `generate_for_wednesday(signal)` — a
  one-argument function. Wednesday's article is written by hardcoded `_SYSTEM_PROMPT`
  constants alone. (F1)
- **Brand voice, editorial strategy, platform strategy and visual strategy are declared
  to the configuration as rules the run follows, and nothing opens them.** The one test
  that mentions them asserts the files exist. (F3)
- **The Wednesday product contract is declared twice.** `config/never_blank/wednesday_golden.yaml`
  is validated by a substantial test file and read by no production code; the enforced
  declaration is `strategy/current/business_strategy.json`. (F2)
- **Friday has two scheduled publishers**, and the older of the two is the only publisher
  not in the `never-blank-publish` concurrency group. (F4)
- **93% of the repository is test residue.** 7,796 of 8,380 tracked files are run
  directories for two synthetic signal IDs that exist only in `tests/`. (F5)

The common cause is not carelessness. It is that this repository has never had a rule
saying *an artifact is not finished until something proves it is consumed*, so an artifact
can be authored, documented, tested and merged without ever being connected — and every
signal a reviewer would normally trust says it is fine.

### Counts by classification

| Classification | Files | Notes |
|---|---:|---|
| ACTIVE RUNTIME | 251 | Reachable from a current production entrypoint |
| ACTIVE SUPPORT | 151 | Tests, CI, fixtures, operational tooling |
| AUTHORITATIVE PRODUCT CONFIG — WIRED | 17 | Full chain to a production model message proven |
| **AUTHORITATIVE PRODUCT CONFIG — UNWIRED/PARTIAL** | **9** | **Section 2** |
| HUMAN DOCUMENTATION | 56 | Intentionally for people |
| LEGACY BUT INTENTIONAL | 53 | Retained deliberately, owner and reason identified |
| DEAD / ORPHANED | 7,829 | 7,796 of these are one problem (F5) |
| DUPLICATE / SUPERSEDED | 2 | Section 4 |
| SUSPICIOUS / UNRESOLVED | 12 | Section 5 |
| **Total** | **8,380** | `git ls-files` |

### Counts by area

| Area | Files |
|---|---:|
| `reports/` | 7,954 |
| `src/` | 130 |
| `tests/` | 116 |
| `config/` | 43 |
| `scripts/` | 34 |
| `docs/` | 34 |
| `strategy/` | 26 |
| `.github/workflows/` | 18 |
| `data/` | 13 |
| repository root | 9 |
| `assets/` | 3 |

### What "reachable" meant here

An artifact is ACTIVE only when a path exists from a workflow job step to the code that
opens or imports it. A mention in documentation, a test that reads the file, or the file's
own claim about itself is never a consumer. For product configuration the bar is higher:
the content must be traceable to the `system`/`user` strings handed to
`src.utils.llm_client.chat` on a path a production entrypoint reaches.

Dynamic loading was traced, not assumed dead. `config/prompts/visibility/*.yaml` are
loaded through an f-string key built from an enum (`src/editorial/vi_pipeline.py:80`) and
have no literal path reference anywhere; they are WIRED. A static search would have called
them orphans.

Nothing was excluded as vendor or build output — this repository tracks no such directory.
`reports/content_packages/images/` is the only gitignored generated path and holds no
tracked file.

---

## 2. AUTHORITATIVE PRODUCT CONFIG — UNWIRED / PARTIAL

These come first because for Never Blank they are the failure that matters: a file that
looks like it defines the product and does not reach the product.

### F1 — Wednesday's declared editorial role never reaches Wednesday's generation prompt

`strategy/current/business_strategy.json:398-446` declares the role
`never-blank-wednesday-golden`: nine structure rules, nine prohibitions, per-surface Wix
and LinkedIn rules, and `require_source_transparency: true`.

The canonical entrypoint renders all of it:

```
generate_and_publish.py:920-922   _editorial_role_rules = {"long": …wix…, "medium": …linkedin…}
generate_and_publish.py:1863-1868 + render_sources_of_record(...)   (because the role requires it)
generate_and_publish.py:1878-1880 if is_wednesday_role(...): article = generate_for_wednesday(editorial.to_legacy_dict())
```

`src/never_blank/wednesday_routing.py:57` is `def generate_for_wednesday(signal: dict)`.
One argument. No role rules, no CTA mode, no strategy views, no closing contract. The
Monday/Friday branch immediately below it (`:1882-1890`) passes
`editorial_role_rules=_editorial_role_rules` into `generate_article()`, which carries it
to `src/editorial/platform_composer.py:492-495` and into the user prompt at `:511`.

The only Wednesday consumer of `_editorial_role_rules` is `recompose_platform(…, "medium", …)`
at `:2151-2157`, which runs only when editorial acceptance revised the article.

Draw the boundary precisely, because part of the chain does hold: the Wednesday acceptance
rubric is wired (`:924`, from `business_strategy.json:442`), and the reviewer and reviser
do receive the sources-of-record block (`:2013-2019`). It is **generation** — and only
generation — that the declared role does not reach. Editing the Wednesday role changes the
article a reader sees only in the revision case.

**This is #237's question.** #237 owns the Monday/Wednesday prompt wiring and is blocked on
an owner choice. This audit records the reachability fact and makes no product choice.

### F2 — The Wednesday product contract is declared twice; only one runs

`config/never_blank/wednesday_golden.yaml` + `src/never_blank/wednesday_golden.py` declare
the Golden reasoning movement, prohibitions, title contract, text shape and source policy
as a strict typed profile. `WednesdayGoldenProfile.load()` (`:167`), `generation_rules()`
(`:195`) and `source_eligibility_rules()` (`:173`) have **no caller in `src/` or
`scripts/`**. The module is imported at runtime only as a side effect of
`src/never_blank/__init__.py:7`, so an import-graph check reports it as reachable while
none of its behaviour executes. Its own docstring (`:197-201`) says so: the canonical
entrypoint carries the declared role through the generic renderer, and this renderer
"remains useful for strict profile tests".

The enforced declaration is `strategy/current/business_strategy.json:398-446`. Two files
describe one contract in product language; a change made in the wrong one is silently
inert and the suite still passes.

### F3 — `prompt_rule_references` declares six documents as product rules; five are never loaded

`strategy/current/business_strategy.json:306-341` declares seven references. Exactly one is
functionally consumed, and only as a version equality check
(`src/strategy/execution_context.py:296-315`, `assert_campaign_reference`).

| Declared reference | Path | Loader |
|---|---|---|
| active-campaign-strategy | `strategy/current/strategy.json` | version check only |
| brand-identity | `config/brand.yaml` | legacy path only — `src/quality/voice.py:159`, `rewrite.py:56`, `src/internal/strategy.py:73`, none reachable from a schedule |
| brand-voice | `config/brand_voice.md` | **none** |
| strategy-methodology | `strategy/methodology/strategy_methodology.md` | **none** |
| editorial-strategy | `strategy/methodology/editorial_strategy.md` | **none** |
| platform-strategy | `strategy/methodology/platform_strategy.md` | **none** |
| platform-visual-strategy | `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | **none** |

The configuration states that the product's voice and editorial strategy are rules the run
follows. A brand-voice change has no effect on any published article. The only test that
mentions them — `tests/strategy/test_never_blank_business_config.py:80-86` — asserts
`resolved.is_file()` and would pass unchanged if every one of them were empty. (See F9a.)

### F6a — The prompts that look like the product's article prompts are legacy-only

`config/prompts/blog_post.yaml` and `config/prompts/linkedin_post.yaml` are loaded only by
`src/content/generator.py:126` and `:134`, reachable only from `scripts/generate.py`, which
only `generate_content.yml` and `generate_and_publish.yml` invoke — both
`workflow_dispatch`-only. `docs/SYSTEM_MAP.md:30` presents `blog_post.yaml` as "Blog
generation prompt" without qualification.

The articles Never Blank actually publishes are built from hardcoded `_SYSTEM_PROMPT`
constants in `src/editorial/*.py` and `src/never_blank/wednesday_july/*.py`, plus the
`business_strategy.json` role rules. That is a deliberate design; the problem is that
nothing in the repository says so, so `blog_post.yaml` reads as the product's article
prompt to anyone who opens it.

---

## 3. DEAD / ORPHANED

### F5 — 93% of tracked files are test residue (7,796 files)

| Path | Files | Owner |
|---|---:|---|
| `reports/content_packages/sig-identity-test-001/**` | 3,094 | `tests/test_run_identity.py:63` |
| `reports/content_packages/sig-test-001/**` | 4,702 | `tests/test_visual_contract.py:78`, `test_wednesday_supply.py:302`, `test_wednesday_live_fixes.py:401` |

Neither signal ID exists outside `tests/`. The root cause is two lines:

```python
# scripts/generate_and_publish.py:320-321
PACKAGES_DIR   = Path("reports/content_packages")
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
```

A relative path resolved against the process CWD, created at **import** time. Importing the
canonical entrypoint from a test is enough to create the directory, and any test that
drives a run writes real run artifacts into the tracked repository path. The daily
workflow is not the source: its commit step (`daily_signal_research.yml:106`) adds
`reports/content_packages/*.json`, a flat glob that never matches the nested run
directories. A local `git add -A` after a test run is.

The consequence is reviewability. Every diff, every search and every file-by-file audit —
including this one — is dominated by artifacts with no consumer, and a real content package
is harder to tell apart from residue.

### F7 — Orphaned configuration kept alive by a single unreachable script

| Artifact | Only "consumer" |
|---|---|
| `config/prompts/observation_discovery.yaml` | `scripts/dry_run.py:95-100` |
| `config/prompts/observation_score.yaml` | `scripts/dry_run.py:95-100` |
| `config/prompts/topic_extract.yaml` | `scripts/dry_run.py:95-100` |
| `config/intelligence.yaml` | `scripts/dry_run.py:82` |
| `config/content_matrix.yaml` | none — only `docs/SYSTEM_MAP.md:28` mentions it |
| `scripts/dry_run.py` | none — no workflow, no test |
| `scripts/render_card_audit.py` + `reports/card_audit/*.png` (26) | none |

All five configuration files carry `status: ready`, so nothing in-band signals disuse.
`config/intelligence.yaml:1` reads `sources: []  # populated in Phase 7 (Intelligence Engine)`
— an unimplemented phase.

The repository already has the better pattern one directory over:
`config/prompts/{image_hook,topic_score,strategy_brief}.yaml` carry `status: not_needed`,
and `src/utils/config_loader.py:49-53` refuses to load them with the reason attached. That
is retirement a reader can see. These six are retirement nobody recorded.

**Do not delete on static evidence alone.** Confirm with the owner, then either apply
`status: not_needed` with a reason or remove them together with the dry-run harness.

---

## 4. DUPLICATE / SUPERSEDED and source-of-truth conflicts

| Duplicate | Authoritative | Evidence |
|---|---|---|
| `config/never_blank/wednesday_golden.yaml` + `src/never_blank/wednesday_golden.py` | `strategy/current/business_strategy.json:398-446` | F2 |
| `.github/workflows/research_generate_and_publish.yml` (Friday cron) | `.github/workflows/scheduled_publish.yml` (Friday owner per its own header) | F4a |
| `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md` ("Release 1 product configuration for Issue #143") | `business_strategy.json` role declaration | Three artifacts describe the same Wednesday contract |
| `strategy/decision_log.md` | `strategy/history/decisions/decision_log.jsonl` (`src/strategy/history.py:52`) | Name collision; only the `.jsonl` is written by code |

One duplication is **intentional and correctly owned**, and is recorded here so it is not
rediscovered as an accident: `src/never_blank/wednesday_july/**` (16 files) deliberately
parallels `src/editorial/*`, including its own feed config
(`wednesday_july/research/research_sources_july.yaml`, loaded at
`wednesday_july/research/discover.py:47` with a comment at `:45-46` explaining why it is
not `config/research_sources.yaml`). `scripts/generate_and_publish.py:1869-1877` states the
reason. `tests/fixtures/wednesday_july/july_originals/*.py.txt` guards it against drift.

---

## 5. SUSPICIOUS / UNRESOLVED

| Artifact | Why unresolved |
|---|---|
| `src/investigation/hypothesis_generator.py` (+ `__init__`) | No importer in `src/` or `scripts/`; only `tests/test_hypothesis_generator.py`. `docs/LERA_OPERATING_SYSTEM.md:5-7` says "Branch: feature/business-investigation-layer / Status: Under development. Not merged to main" — while both the document and the module are in `main`. Staged capability or abandoned branch? Unanswerable from the repository. |
| `scripts/research/sync_from_sheets.py` | `docs/NEVER_BLANK_RESEARCH_PIPELINE.md:75` calls it "Stage 8"; `run_daily_research.py:25-32` imports nine sibling stages and not this one, and no workflow invokes it. Manual operator step, or a documented stage that does not run? |
| `scripts/strategy/*.py` (5) and `src/strategy/{market_analyzer,content_planner,decision_engine,pattern_extractor}.py` (4) | No workflow executes them; `strategy_tests.yml:64-67` only `py_compile`s four scripts. `approve_strategy_recommendation.py` is the only path that archives a strategy after human approval. Nine files whose only automated guarantee is that they parse. |
| `src/research/adapters/fake.py` | A test double under `src/`, easy to mistake for production code. Low risk, worth a note. |

None of these should be deleted. Each needs a status statement somewhere a reader will
find it — a module docstring or an in-band marker — not a stale branch header.

---

## 6. Active legacy paths that can still execute unexpectedly

### F4a — Two workflows publish on Friday

- `scheduled_publish.yml:23-24` — Friday 04:17 America/New_York. Its own header says
  "Friday remains on this legacy path until #144".
- `research_generate_and_publish.yml:33` — `cron: "0 7 * * 5,0"`, Friday **and** Sunday.
  Its comment says only that Monday and Wednesday moved away, and that "Friday and Sunday
  remain unchanged here".

Both reach a publisher. The reasoning #142 applied to Monday — two publishers on one day is
two articles, and a consumption marker written *after* a run can never be a concurrency
guard — applies to Friday unaddressed.

### F4b — The Friday publisher is not serialized

`monday_publish.yml:53-55`, `wednesday_golden.yml:32-34` and
`research_generate_and_publish.yml:37-39` all declare `concurrency: group: never-blank-publish`.
`scheduled_publish.yml` declares no concurrency block at all — while writing the same
`strategy/published_content_index.jsonl` and `data/research/published_signal_ids.txt`.

### F4c — Publishing days outside the stated cadence

`research_generate_and_publish.yml` fires Sunday; `visibility_publish.yml:6-7` fires Tuesday
and Thursday. The most recent scheduling work describes the product cadence as
Monday/Wednesday/Friday (commit `58afe47`, #232). Four live publishing days that the current
scheduling narrative does not mention is a reverse-reachability question, not a defect —
but it should be answered deliberately rather than inherited.

### F4d — The daily path's publish authorization is not in the repository

`daily_signal_research.yml` runs every day. An inline shell guard at `:82-83` forces
`NB_RESEARCH_PUBLISH_ENABLED=false` **only** when the local weekday is Wednesday. On every
other day the publish decision is the value of a secret. Whether a second article publishes
on a Monday cannot be determined from source. The #159 forensics recorded in
`src/publishing/release_scope.py:12-18` are what this path did on 2026-09-06 and 2026-09-07:
it published to Facebook, Instagram and Telegram while Wix and LinkedIn failed.

### Manual paths that can publish live

`publish.yml`, `generate_and_publish.yml` and `live_publish_test.yml` are
`workflow_dispatch`-only and can post for real. Manual dispatch is the intended
authorization boundary and this audit does not object to it — it is recorded so the set is
known. Note that `generate_and_publish.yml` does **not** call
`scripts/generate_and_publish.py`; the workflow named after the canonical entrypoint is the
one legacy workflow that does not use it (F6b).

---

## 7. Tests and CI gaps that let this happen

The suite is large, the CI gate is strict, and neither would have caught any finding in
section 2. That is the gap.

| Test | What it proves | What it does not |
|---|---|---|
| `tests/strategy/test_never_blank_business_config.py:80-86` | The declared reference paths exist on disk | That anything opens them. This single test is why F3's five unconsumed documents pass as wired product rules |
| `tests/test_research_prompts.py` | Six YAML files load, have long-enough system text and no unresolved `{placeholder}` | That the loaded text reaches a model call. These prompts *are* wired — the test simply would not have noticed if they were not |
| `tests/test_wednesday_golden.py` | The strict profile validates, and Wednesday workflow ownership | That production loads the profile. Substantial test weight behind an artifact nothing calls makes F2's duplicate look live |
| `tests/test_cross_platform_overlap_policy.py:326-333` | A withdrawn rule is absent from `config/brand_voice.md` | Anything about consumption. Asserting on the text of a file nothing loads makes the file look governed |

`tests/accepted_full_suite_failures.txt` holds four permanently accepted failures, all in
`tests/test_editorial_pipeline.py::TestGeneratorTelegramStories` — the Telegram/Stories path
of the legacy V1 generator. The comparator itself is strict and fail-closed
(`scripts/ci/check_test_baseline.py:28-42` rejects both new and resolved failures), so the
baseline cannot silently grow. The debt is small and sits on code nothing schedules. (F10)

### What the repository already does right

Two existing patterns are the answer to this gap, and the proposal in section 9 is simply
to generalize them rather than invent anything.

**Reachability as an assertion.** `src/publishing/release_scope.py` holds one list of
authorized channels and imports no publisher, so it is an authorization boundary rather than
an implementation. `tests/test_r1_publish_scope.py:47-50` enumerates *every automatic path
that owns a publisher list* and pins that none can reach a non-R1 channel. That is why
`src/publishing/{facebook,instagram,threads,telegram}.py` can stay in the repository, fully
working, without being reachable from a schedule — the rarest thing in this audit: legacy
code that is provably not an accidental active path.

**Consumption as an assertion.** `tests/strategy/test_strategy_semantic_consumption.py:90-112`
patches `src.editorial.never_blank_voice.chat`, reads `chat.call_args.kwargs["user"]` and
asserts seven distinct configured values appear in the actual prompt string; `:115-128`
proves that changing the CTA mode changes the prompt. `tests/test_r1_surface_reduction.py:30-43`
does the same trick from the other direction, identifying a surface by reading the `FORMAT:`
line out of the composer's real user message.

---

## 8. Recommended repair order by risk

Ordered by what can go wrong soonest, not by effort.

1. **F4 — scheduling.** A duplicate publisher on a live day can publish a second article
   this week. It is the only finding with a same-week product consequence. Establish one
   documented owner per publishing day, put every publisher in the `never-blank-publish`
   concurrency group, and make the daily path's publish authorization readable from source.
2. **F1 — Wednesday's role.** Blocked on the #237 owner decision. Listed second so it is not
   lost behind cleanup work.
3. **F3 — `prompt_rule_references`.** Every week this stays unwired is a week of articles no
   voice document governed. Either load the references or narrow the declaration to what is
   consumed and re-describe the rest as human methodology.
4. **F5 — test residue.** Fix the mechanism first (tests must not write into the tracked
   path), clean up the 7,796 files second, as a separate change. Cheap, uncontroversial, and
   it makes every later review readable.
5. **F2 — duplicate Wednesday contract.** Low risk to resolve once F1 is decided; resolving
   it early prevents another inert edit.
6. **Section 9 guardrail.** Put it in *before* the cleanup below, so nothing re-enters the
   repository unwired.
7. **F6 — documentation.** `docs/SYSTEM_MAP.md` is the single most load-bearing out-of-date
   document here: it lists a config file with no consumer, a dry-run-only config, the legacy
   article prompt as *the* article prompt, and three orphaned prompts as current. No runtime
   risk, high reader risk — and while it stands it keeps re-authorizing dead artifacts.
8. **F7 — orphan retirement.** Owner confirmation required; never on static evidence alone.
9. **F8 — status statements** for the investigation layer, Stage 8 and the strategy operator
   tools.
10. **F10 — the four accepted failures**, with whatever decision the legacy V1 path receives.

Each of 1, 3, 4, 5, 6, 7, 8 should become a narrowly scoped follow-up issue. F1 belongs to
#237 and must not get a competing issue. No broad cleanup belongs in the audit PR.

---

## 9. Proposed permanent guardrail

The rule to enforce:

> A new executable/config artifact is not DONE until its intended production consumer is
> proven. An authoritative product/config artifact intended to influence model output must
> have a regression test proving that a distinctive instruction/value reaches the actual
> production model-message construction. Intentional human-only documentation must be
> clearly distinguishable. Unjustified orphaned production artifacts are not allowed.

No framework is needed. This repository has already built both halves of the mechanism; it
has just never applied them to configuration as a class. The smallest durable version is
three things.

### 9.1 One manifest that says what claims to govern the product

A single file — `config/product_config_manifest.yaml` is the natural home, next to what it
describes — listing each artifact the product claims is authoritative, and for each one:

```yaml
- path: strategy/current/business_strategy.json
  role: never-blank-monday-documented-case
  status: wired
  consumer: src.editorial.platform_composer.chat        # where it must arrive
  proof: tests/strategy/test_strategy_semantic_consumption.py::test_editorial_consumes_voice_principles_claims_restrictions_and_cta_rules
- path: config/brand_voice.md
  status: human_documentation                            # or: wired / not_needed
  reason: "Editorial reference for writers. Not loaded by any run."
```

`status` is the distinguishing mechanism the rule asks for. It is the same in-band
retirement marker `config/prompts/*.yaml` already uses via `status: not_needed`, extended
from prompts to every product artifact.

### 9.2 One parametrized test that makes `status: wired` cost something

For every manifest entry with `status: wired`, one test that puts a distinctive sentinel
value into the artifact (or reads a distinctive value already in it), runs the named
production path with `chat` patched, and asserts the value appears in
`chat.call_args.kwargs["user"]` or `["system"]`.

This is exactly `tests/strategy/test_strategy_semantic_consumption.py:90-112`, parametrized
over the manifest instead of hand-written per artifact. Under this test, F3 fails the moment
`config/brand_voice.md` is declared a prompt rule, and F1 fails the moment the Wednesday role
is declared wired — which is the whole point.

It also replaces the weaker
`test_all_prompt_and_rule_references_resolve_inside_repository`: existence checking becomes
the fallback for `status: human_documentation`, where it is the correct assertion.

### 9.3 One reachability test that refuses unclassified artifacts

Extend the pattern of `tests/test_r1_publish_scope.py`: walk `config/**`, `strategy/**` and
the product-bearing parts of `src/`, and fail when a file is neither (a) reachable from a
workflow entrypoint by import or literal path, nor (b) listed in the manifest with a
non-`wired` status and a reason. Dynamically composed consumers — `vi_pipeline.py:80` is the
live example — are declared in the manifest rather than inferred, which is both honest and
cheaper than trying to resolve f-strings statically.

The cost of a new artifact becomes one manifest line. The cost of an *unjustified* one
becomes a red check. That is the smallest thing that would have caught every finding in
section 2, and it is built from parts this repository already trusts.

### 9.4 One mechanical guard, unrelated to configuration

Independently of the manifest: make the artifact root in `scripts/generate_and_publish.py`
injectable (or default to `tmp_path` under pytest) so tests cannot write into
`reports/content_packages/`. Without it, F5 regenerates itself after every cleanup.
