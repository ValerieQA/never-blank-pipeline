# [R1][AUDIT] Full repository reachability and dead-artifact audit — Issue #233

**Audited commit:** `4a121b2b63983d91581bf241234f9a02647124ce` (`main` at 2026-09-17)
**Tracked paths classified:** 8,392 — every tracked path outside `reports/repository_audit/**` and `docs/repository-audit/**`, exactly once
**Method:** read-only. Nothing was published, no provider call was made, no `CONTROLLED_LIVE` run was started, and no production code or configuration was modified.

| Deliverable | Path |
|---|---|
| Machine inventory | `reports/repository_audit/inventory/*.json` (10 shards, 453 entries) |
| Bulk path lists | `reports/repository_audit/paths/*.txt` (7 files, 7,946 paths) |
| Findings and guardrails | `reports/repository_audit/findings.json` |
| Quoted evidence | `reports/repository_audit/evidence/*.md` |
| This report | `docs/repository-audit/REPOSITORY_AUDIT.md` |

Everything this audit asserts is checkable inside this commit. Where a claim rests on
repository history rather than on a file at `4a121b2`, the history is quoted, with the
command that reproduces it, under `reports/repository_audit/evidence/`. No conclusion here
depends on a file that is not in the tree — see §11.

---

## 1. Executive summary

Two sentences, because they are the whole audit:

**Ninety-three per cent of this repository is debris from test runs that nothing reads, and the editorial contracts the product is named after reach no prompt.** Everything else below is detail, sequencing, or a smaller version of one of those two.

The single most urgent item is neither. It is that **a live Friday cron stands in front of a six-channel publisher that no allowlist covers, and the only thing currently stopping it is a YAML file that fails to parse** — a defect standing in for a control that does not exist (F-01).

### Counts by classification

| Classification | Paths | Outside `reports/` |
|---|---:|---:|
| ACTIVE RUNTIME | 157 | 157 |
| ACTIVE SUPPORT | 260 | 135 |
| AUTHORITATIVE PRODUCT CONFIG — WIRED | 28 | 28 |
| **AUTHORITATIVE PRODUCT CONFIG — UNWIRED/PARTIAL** | **14** | **14** |
| HUMAN DOCUMENTATION | 38 | 37 |
| LEGACY BUT INTENTIONAL | 48 | 41 |
| DEAD / ORPHANED | 7,844 | 20 |
| DUPLICATE / SUPERSEDED | 1 | 1 |
| **SUSPICIOUS / UNRESOLVED** | **2** | **2** |
| **Total** | **8,392** | **435** |

The right-hand column is the one to read. Of 435 tracked paths outside `reports/`, 20 are dead. Of the 7,957 paths under `reports/`, 7,824 are.

#### A correction to these counts, recorded rather than applied quietly

A review of this audit's own method found that it had been calling artifacts dead on the strength of two things that do not mean what they look like: **a loader that refuses a file**, and **the absence of a workflow**. Five reclassifications follow, all in the same direction, and the reasoning is in `findings.json` under `counts_revision_note`:

- `config/prompts/{image_hook,strategy_brief,topic_score}.yaml` — DEAD → **LEGACY BUT INTENTIONAL**. Each says, in its own text, that it is retained to document an architectural decision. Their loader refuses them on purpose, and that refusal is the guarantee they can never become an accidental active path. Deliberately disabled is not purposeless. What each record then says about the code is a different matter, and two of the three are wrong about it: see F-16. (§4.2)
- `scripts/dry_run.py`, `scripts/render_card_audit.py` — DEAD → **LEGACY BUT INTENTIONAL**. Both document their own manual command. Having no workflow is not having no consumer; this audit already classified the dispatch-only smoke tests that way.
- `reports/content_packages/<sig>_generated.json` (8) and `vis_00N_generated.json` (6) — LEGACY → **ACTIVE SUPPORT**. Both groups had been justified by retry capabilities that turn out not to exist (F-15). Both have better justifications that do: a live producer and a live reader for the first, tracked history entries naming each path for the second. (§4.1)
- `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md` — DUPLICATE/SUPERSEDED → **PRODUCT CONFIG — UNWIRED/PARTIAL**. Nothing supersedes it, and the claim that the Wednesday artifacts carry no cross-reference was simply wrong. (§2.3)

### What is genuinely healthy

Worth saying plainly, because an audit that only lists defects misrepresents the repository. The research pipeline, the canonical entrypoint's artifact/provenance/preflight/reporting chain, the visual system, the publishers, the run-identity layer and the call-budget ceilings are all reachable, tested and consistent. The Visibility Intelligence stream is the only stream whose editorial prompts are configuration files end to end — `config/prompts/visibility/*.yaml` is loaded by `src/editorial/vi_pipeline.py:83` and reaches the model. Two places in the repository do artifact retention *correctly*, with the reason written next to the mechanism: `.gitignore:18-19` (the corporate-backlog archive, naming Issue #142) and `strategy/decision_log.md` decision 77 (the two research files). Those are the patterns the fixes below should copy.

---

## 2. AUTHORITATIVE PRODUCT CONFIG — UNWIRED / PARTIAL

Fourteen paths: nine Markdown documents (§2.1), three machine artifacts (§2.2), and the two Wednesday prose contracts (§2.3, detailed in §3). These are first because the issue asks for them first, and because they are the ones where existence is most convincingly mistaken for implementation.

The structural cause is one line long: **no loader in this repository can read Markdown as configuration.** `src/utils/config_loader.py:11,38` read YAML; `src/strategy/business_config.py:272` reads JSON. Every `.md` opened anywhere in `src/` or `scripts/` is a report being written. So the chain

```
artifact → loader → runtime object → production consumer → model-message construction
```

breaks at the first link for every Markdown product contract, and the documents that declare those contracts executable — `prompt_rule_references`, `research_references` — are validated as *strings*, never opened.

### 2.1 The nine documents, and one that belongs with them

| Path | Declared where | Consumer |
|---|---|---|
| `config/brand_voice.md` | `business_strategy.json:313-314`, id `brand-voice`, version `r1-2026-08-13` | none |
| `docs/NEVER_BLANK_EDITORIAL_STYLE.md` | `docs/SYSTEM_MAP.md:4` as *the* editorial style | none — **was runtime until `2466611` (2026-07-03)** |
| `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md` | itself, as the document all prompts follow from | none, and declared nowhere |
| `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | `business_strategy.json:338-339` | none |
| `strategy/methodology/strategy_methodology.md` | `business_strategy.json:323-324` **and** `strategy.json:58` | none |
| `strategy/methodology/editorial_strategy.md` | `business_strategy.json:328-329` | none |
| `strategy/methodology/platform_strategy.md` | `business_strategy.json:333-334` | none |
| `strategy/methodology/evaluation_rules.md` | nowhere — header says `Status: Production` | none |
| `strategy/worldview.md` | `strategy.json:59` | none |
| `strategy/current/strategy.md` | hand-maintained twin of `strategy.json` | none |

Nine of these ten rows carry the classification. The tenth, `strategy/current/strategy.md`, is classified **HUMAN DOCUMENTATION** in the inventory, because unlike the others it never claims to be executable — it is listed here because it is the same hand-maintained-twin problem and falls under the same owner ruling of 2026-09-15.

`docs/NEVER_BLANK_EDITORIAL_STYLE.md` deserves its own sentence, and its own evidence file. It was genuinely executable: `scripts/research/publish_packages._load_editorial_style()` injected its text verbatim into the article prompt as `EDITORIAL STYLE (mandatory — follow exactly):`. Commit `2466611` (2026-07-03) replaced that generation call with the V2 pipeline and deleted the loader. The commit message is unusually explicit about every other semantic change it makes — Threads moving to one post, hashtags "intentionally dropped" — and does not mention this one.

The claim that follows is often made loosely, so state it precisely: **no test failed, because no test could have.** At `2466611^` the only two references to the document anywhere under `src/`, `scripts/` or `tests/` were the two lines inside `publish_packages.py` that the commit itself deleted. A deletion nothing asserts on cannot turn anything red. `reports/repository_audit/evidence/EDITORIAL_STYLE_DISCONNECTION.md` quotes the loader, the prompt block, the diff and both greps, with the commands that reproduce them from this repository's history — no other branch, no external record. That is the exact failure mode the guardrail in §9 exists to prevent, and it is not hypothetical: it already happened, and nobody noticed for ten weeks.

### 2.2 The three machine artifacts

- **`strategy/current/business_strategy.json` — partial.** It loads on every canonical run. Of the fifteen model calls on the Monday path its content reaches three: `decision_lens_lite`, `never_blank_voice`, and the `platform_composer` channel plus role rules. For Wednesday its role rules reach generation not at all. Its `prompt_rule_references` block is the inventory that made seven of the ten documents above look wired.
- **`config/never_blank/wednesday_golden.yaml` — unwired.** See §3.
- **`src/never_blank/wednesday_golden.py` — unwired loader.** It *executes* in production, because `src/never_blank/__init__.py:7` re-exports it and `scripts/generate_and_publish.py:175` imports the package. No production call site ever invokes `load()`, `source_eligibility_rules()` or `generation_rules()`. Only tests do. An eagerly re-exported loader that nothing calls is the most convincing possible disguise for an unwired artifact: static reachability says yes, execution says no.

### 2.3 The two Wednesday prose contracts

`docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md` and `docs/product/wednesday_golden_contract.md` complete the fourteen. Both declare product behaviour; neither is opened by anything. They are treated in §3 with the machine profile, because the three of them are one subject.

The first of the two was classified DUPLICATE/SUPERSEDED in an earlier revision of this audit, on the reasoning that the second is newer. That was wrong on both halves. **A newer date is not authority** — nothing in the repository declares either document to supersede the other, and a supersession that nobody wrote down has not happened. And the supporting claim that the Wednesday artifacts carry no cross-reference was false: `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md:19-22` names both machine artifacts by path, calling `config/never_blank/wednesday_golden.yaml` "the machine-readable product profile" and `config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml` its acceptance artifact. It is the only one of the three that points anywhere at all. Exactly one of the two links it declares executes — the rubric is wired, the profile is not — and *that* is what makes it PARTIAL.

Only one path in the whole audit now carries DUPLICATE/SUPERSEDED: `strategy/claude_code_prompt_strategy_engine_2026-07-22.md`, where the superseding document says so in its own first paragraph. That is the standard of evidence the classification requires (§5).

### 2.4 Conflicts that must be resolved before any of this is repaired

Compilation forces one winner per rule, and there is no winner today:

| Rule | Code says | `docs/PLATFORM_AND_VISUAL_STRATEGY.md` | `strategy/methodology/platform_strategy.md` |
|---|---|---|---|
| Blog length | 400–600 (`platform_composer.py:52-55`, `business_strategy.json:237`) | 700–1000 (`:27`) | 600–1200 (`:30`) |
| LinkedIn length | 120–220 (`linkedin_composition.py:49-51`) | 350–600 (`:57`) | — |

And the direction is not always "document right, code stale": on hashtags the **code is right** (`src/publishing/hashtags.py:35` emits the fixed branded trio, matching the owner's standing rule) and `config/brand_voice.md:200-201` is stale. That is precisely why one source must win *per rule*, not per file.

**This audit proposes no repair here.** #240/#244 own it and are blocked on owner rulings. What this audit adds is the guardrail in §9 — which must exist *before* any of these documents is declared wired again, or the same silent disconnection will happen a second time.

---

## 3. Wednesday: one contract, three copies, zero consumers

Separated out because it is the single clearest instance of the repository-integrity risk this issue was opened for.

`config/never_blank/wednesday_golden.yaml` holds the nine-stage reasoning movement, the title contract, the text shape, the source policy, and the prohibitions — including the explicit bans on "5 lessons" and "3 takeaways". What Wednesday generation actually receives is:

```
scripts/generate_and_publish.py:1880
  generate_for_wednesday(editorial.to_legacy_dict())     ← the signal dict. Nothing else.
    src/never_blank/wednesday_routing.py
      src/never_blank/wednesday_july/pipeline.py
        compose_platforms(structured_article)            ← one argument. No rules parameter exists.
```

`_editorial_role_rules` **is** computed for Wednesday at `:920` and then not passed. `grep` for "5 lessons" or "3 takeaways" across `src/never_blank/wednesday_july/` finds nothing.

And CI reports the opposite. `tests/test_wednesday_golden.py:397` — `test_golden_rules_reach_the_existing_wix_and_linkedin_prompt_constructor` — builds prompts with the **shared** `src/editorial/platform_composer._build_user_prompt`. Since #210, Wednesday composes through a *different* module that takes no rules. The test was never retargeted when production moved, so it passes, green, asserting a contract that is not met.

There are three copies of this contract and none declares which is authoritative: the YAML, `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md` (2026-08-20, self-declared "Release 1 product configuration"), and `docs/product/wednesday_golden_contract.md` (2026-09-05 — written *ten days after* #210 disconnected the contract from generation). A fourth partial copy, the rubric path and identity, is duplicated into `business_strategy.json:442-443`, and that JSON copy is the only one the runtime honours.

One cross-reference exists among them, and it runs outward from the 2026-08-20 document: `:19-22` names the YAML profile and the acceptance rubric. Nothing points back, and the 2026-09-05 document names none of the others. So this is an **unresolved** source-of-truth conflict, not a resolved one — and this audit deliberately does not nominate a winner between the two prose contracts, because choosing is the Wednesday product decision of #234, not an editorial-hygiene call. The 2026-08-20 document's "Canonical integration" section (`:137-151`) states that the configured structure and prohibitions are carried into the real Wix and LinkedIn composition prompts; since #210 they are not, which is the same fact the trace above establishes.

**Nothing here is repairable now.** #210 disclosed the deviation, Wednesday is architecturally paused, and the fix collides with the July byte-fidelity fixtures that #207/#210 deliberately installed. Two things *can* be done without touching the product decision: retarget or `xfail` the test so CI stops lying, and name one source of truth among the three documents.

---

## 4. DEAD / ORPHANED

### 4.1 The 7,824 under `reports/` — and the question the issue asks

**Do ~8,000 tracked run records belong in source control? Split the answer.**

**No — the 7,796 test-run records.** `reports/content_packages/sig-test-001/runs/<uuid>/` and `.../sig-identity-test-001/runs/<uuid>/` hold 4,702 and 3,094 files. Across both namespaces there are exactly six distinct basenames — `business_strategy.json` (2,422), `generated.json` (2,263), `editorial_acceptance.json` (1,343), `assignment.json` (1,263), `publication_results.json` (469), `run_report.json` (36) — one set per test execution of the canonical entrypoint. Nothing reads any of them.

The mechanism is three lines:

```
scripts/generate_and_publish.py:320   PACKAGES_DIR = Path("reports/content_packages")   ← relative
scripts/generate_and_publish.py:321   PACKAGES_DIR.mkdir(parents=True, exist_ok=True)   ← at import
scripts/generate_and_publish.py:1052  resolve_run_dir(PACKAGES_DIR, signal_id, run_id)  ← one dir per uuid4
```

`tests/conftest.py` isolates OpenAI credentials and does not isolate the filesystem. Nothing under `reports/` is ignored except `reports/content_packages/images/`.

They entered in one commit: `ffe199a` (2026-08-17) — 7,830 files, 917,551 insertions, on a change whose actual subject is 69 lines of `src/reporting/run_report.py`. And they keep costing: `dd54dc5` (#223), a **two-line** message change in `src/utils/config_loader.py`, shipped 145 files and 864 insertions/deletions, all of it this debris, and the same happened on both of its rebases. Every diff taken after a local test run carries this noise, which is how a real change hides.

**Yes, for now — the 63 daily research reports, the 47 per-signal packages, the 8 flat generated packages and the 6 visibility packages.** Their tracking is deliberate and expressed in the workflows that commit them (`daily_signal_research.yml:106`, `visibility_publish.yml:102`), and `src/run/code_identity.py:34-43` states the repository's own position: `reports/` and `data/` are output roots a run legitimately dirties, and a rule covering them "would make the second of two consecutive runs permanently non-qualifying". That reasoning is sound. What those groups lack is a **retention policy**, not a justification.

This audit very nearly got the last two of those four wrong, and the correction is worth stating, because it is the audit's own method failing in exactly the way §8 describes:

- The 8 `<signal_id>_generated.json` packages were called *legacy* input to a `--legacy-package` fallback. There is no fallback. `scripts/generate_and_publish.py` accepts the flag (`:854`) and then rejects it unconditionally at `:1380-1382`, before the loader at `:1407-1421` can ever run — that loader is unreachable code. What these files actually are is **current** output of research Stage 11 (`scripts/research/publish_packages.py:288`), added by the daily workflow's own commits as recently as 2026-09-14, with a real reader: `scripts/smoke_test_publish_analytics.py:61`, driven by `smoke_test_full_cycle.yml`.
- The 6 `vis_00N_generated.json` packages were justified by a "`--from-package` style resume" of the visibility publisher. That flag does not exist: `scripts/generate_and_publish_visibility.py:344-347` defines only `--item-id` and `--dry-run`, and the script never reads a package back. The comment at `:425` claims the capability; the code does not implement it. Their real justification is one line further down — `:479` writes each package's exact path into the immutable history entry, and all six paths appear verbatim in the tracked `data/strategy/visibility_history.jsonl`. Deleting one would leave a tracked record pointing at nothing.

Both were **advertised capabilities mistaken for consumers**, which is precisely the error this audit exists to find in other people's work. They are recorded as F-15 so the correction is inspectable rather than silent.

There is a third, smaller case that is worse than either: **`reports/card_audit/`, 26 PNGs, tracked against an explicitly recorded decision.** `strategy/decision_log.md` decision 97 (2026-08-07) records the owner deciding that this directory stays untracked — *"не добавлен в .gitignore и не закоммичен — статус untracked сохраняется до отдельного решения"* — and the Часть 22 status line repeats it. `ffe199a` committed all 26 ten days later. The decision log is the record of truth; the repository contradicting it is a defect in the repository, not in the log.

### 4.2 The 20 outside `reports/`

| Group | Paths | Why dead |
|---|---:|---|
| Strategy Engine monthly loop | 9 | `src/strategy/{market_analyzer,content_planner,decision_engine,pattern_extractor}.py` + `scripts/strategy/*`. No workflow executes any of them; `strategy_tests.yml:64-67` only `py_compile`s them, and compiling is not a consumer. `build_monthly_plan.py:33` reads `reports/signals/`, which does not exist; `content_planner.py` writes `strategy/current/content_plan.*`, which does not exist. Built to the spec in `strategy/claude_code_prompt_strategy_engine_FINAL_2026-07-22.md`, and never wired. |
| Their output directories | 3 | `strategy/reviews/{weekly,monthly,recommendations}/.gitkeep` — no review has ever been written. |
| Investigation layer | 2 | `src/investigation/*`. Only consumer is its own test. |
| Orphaned scripts | 1 | `scripts/research/sync_from_sheets.py` — the human-override half of the two-way sheet sync. What makes it dead rather than manual is that it declares itself **"Stage 8"** of the research pipeline (`:1-4`), and `docs/SYSTEM_MAP.md:17` repeats the claim, while `run_daily_research.py:31` imports only `sync_to_sheets`. A declared position in a pipeline that never calls it is not a retained purpose. |
| Orphaned config and prompts | 5 | `config/content_matrix.yaml` (shadowed by `config/prompts/content_matrix.yaml`), `config/intelligence.yaml` (loaded only from `dry_run.py`), and three observation/topic prompts named only in `dry_run.py:96-97`. All three prompts carry `status: ready` — they present themselves as usable and are not. |

**Do not delete any of these on static-search evidence alone.** Each group corresponds to a documented intention, and the issue forbids deletion on the strength of a missing import. What they need is one owner decision per group.

#### Five paths that were in this section and should not have been

`config/prompts/image_hook.yaml`, `config/prompts/strategy_brief.yaml`, `config/prompts/topic_score.yaml`, `scripts/dry_run.py`, `scripts/render_card_audit.py` — all previously counted here and proposed for deletion. Recorded rather than quietly dropped, because the mistake is instructive:

The three prompts are **not unused prompts. They are decision records that happen to be YAML.** `image_hook.yaml:3-7` says so outright — *"This file is retained for documentation of the architectural decision"* — and then states the decision (`:9-13`) and points at the code it says implements that decision instead (`:15-17`). `strategy_brief.yaml` and `topic_score.yaml` have the same three-part shape. Their `status: not_needed` makes `config_loader.py:49-53` raise a `ValueError` that quotes the file's own `decision` field back at the caller, so the reason for the absence is what a would-be user receives. **A loader refusing a file by design is the mechanism that keeps it inert, not proof that it is pointless** — it is the strongest available evidence that this is not an accidental active path, which is exactly what LEGACY BUT INTENTIONAL asks for.

**Their third part does not survive verification, and this audit first repeated it instead of checking it.** An earlier revision of this section claimed each record names where its deterministic implementation lives. At `4a121b2` that is false for two of the three and stale for the third, and the classification rests on the refusal mechanism above, never on the accuracy of the pointer:

| Record | What it points at | What the tree proves |
| --- | --- | --- |
| `image_hook.yaml:15-17` | `src/content/image_builder.py`, slicing the observation to `brand_config.image.hook_max_chars` | The module does not exist. The hook comes from `src/publishing/image_pipeline.py:596` `trim_hook_text(observation)`, which is **word**-based (`:172-182`, 7 preferred, 10 hard). `config/brand.yaml:36 hook_max_chars: 80` is read by nothing. The decision — derive the hook deterministically, no model call — still holds. |
| `strategy_brief.yaml:7-12` | `src/internal/strategy.py`, with slug uniqueness against `memory/published.json`, a `platform_format` mapping and a `content_goal_by_observation_type` mapping | The module is real and two rules hold (tag assignment `:38-53`, slug from title `:22-35`, `:77-79`). The other three do not: `generate_slug` checks no uniqueness and the module never imports `src/internal/memory.py`; the brief takes `platforms=topic.platform_fit` and `content_goal=topic.content_goal` from the candidate. Both named config keys (`config/strategy.yaml:31`, `:43`) have no reader. |
| `topic_score.yaml:9-13` | `src/internal/topic_scorer.py`, a weighted formula with inputs from `config/intelligence.yaml` | The module does not exist and nothing implements the formula. `src/internal/topic_prioritizer.py:64,:74` records the Intelligence Engine as a stub, *"not wired yet (Phase 7)"*. Its named weights source is `DEAD_ORPHANED` here (only reader `dry_run.py:82`). The scoring that does run reads a different file, `config/scoring_weights.yaml`. This record documents a design that was never built. |

That changes no classification and no count: all three stay LEGACY BUT INTENTIONAL, kept inert by the loader. It does change what they are worth as evidence — a record that sends a reader to a module that is not there manufactures exactly the wrong assumption it was written to prevent. Recorded as **F-16**, with the repair reserved for the owner, because #233 may not edit source YAML. `topic_score.yaml` in particular is not a prompt question at all: retiring it is one decision together with `config/intelligence.yaml` and the Intelligence Engine stub.

The two scripts document their own invocation (`dry_run.py:1-9`, `render_card_audit.py:1-17`). Having no workflow is not having no consumer; the operator is the consumer, which is already how this audit classifies the dispatch-only smoke tests. In `dry_run.py`'s case the inconsistency was sharper still: §9 proposes promoting its parse check into CI as guardrail **G-1**, and it makes no sense to retire a tool while adopting its behaviour.

Two real defects survive. One belongs to a different file: `docs/SYSTEM_MAP.md` lists all three prompts (`:32`, `:46`, `:58`) as live parts of the system, when each says in its own text that it is deliberately not used — F-07's SYSTEM_MAP problem, not a prompt problem. The other belongs to the prompts themselves, and is the table above: F-16.

---

## 5. DUPLICATE / SUPERSEDED and source-of-truth conflicts

**Exactly one path carries the classification**, because duplication here is almost always *unresolved* rather than *superseded*: nobody has said which copy wins.

The standard applied is deliberately strict, and it was tightened after the review that caught this audit applying it loosely to the Wednesday contract (§2.3). DUPLICATE/SUPERSEDED requires **demonstrated** supersession — an artifact stating that another supersedes it, or that it supersedes another. A later date does not qualify. Neither does being shorter, tidier, better formatted, or written by someone who evidently knew about the first. Absent that statement, the honest classification is the conflict itself, recorded with no winner.

The one path that meets it: `strategy/claude_code_prompt_strategy_engine_2026-07-22.md`, because `claude_code_prompt_strategy_engine_FINAL_2026-07-22.md:3-6` says in its own first paragraph which document is the base spec and which is the earlier draft. That is the counter-example and the model to copy — one sentence, in-band, and the question never has to be re-litigated.

The conflicts with no winner:

| Subject | Copies | Winner today |
|---|---|---|
| Wednesday Golden contract | `config/never_blank/wednesday_golden.yaml`, `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md`, `docs/product/wednesday_golden_contract.md` | none declared; the runtime honours only `business_strategy.json:442-443`. The one existing cross-reference (`GOLDEN_EDITORIAL_PATTERNS.md:19-22` → both machine artifacts) establishes a relationship, not an authority. Naming the winner is an owner decision — see §3. |
| Never Blank worldview | `strategy/worldview.md` (RU, declared at `strategy.json:59`), `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md` (EN, declared nowhere) | none declared |
| Active strategy | `strategy/current/strategy.json` (executed), `strategy/current/strategy.md` (hand-maintained) | the JSON — which is the inverse of the owner's 2026-09-15 ruling |

One in-band line in each losing file is the entire fix for the second and third rows.

Four further collisions make the wrong file easy to open:

- `scripts/generate_and_publish.py` (**the** canonical entrypoint) vs `.github/workflows/generate_and_publish.yml` (a manual **legacy** workflow that never touches it). Identical names, opposite meanings.
- `config/strategy.yaml` (V1, legacy Friday) vs `strategy/current/strategy.json` (canonical). Neither mentions the other.
- `src/editorial/pattern_extractor.py` (live) vs `src/strategy/pattern_extractor.py` (dead).
- Two schedule authorities: Monday/Wednesday use crons + `scripts/streams/due_check.py`; Friday uses `config/schedule.yaml` + `scripts/scheduled_publish.py:180`. Only the first is covered by a test.

---

## 6. SUSPICIOUS / UNRESOLVED

Two paths. Both are unresolved in the strict sense the issue means: their purpose cannot be established safely.

**`config/prompts/linkedin_post.yaml`.** It is reached by a live scheduled entrypoint, it raises on load, and that raise is currently the only thing preventing an unscoped six-channel publication. Whether it is configuration or a brake cannot be answered from the repository — and the owner has already ruled that it must not be "fixed", because fixing it re-enables the publisher. A file whose *defect* is load-bearing is not classifiable as ACTIVE. See F-01.

**`docs/SYSTEM_MAP.md`.** It presents itself as the index of the system, and it describes only V1. Monday, Wednesday, Visibility, the canonical entrypoint and `release_scope` are absent entirely. Seven of its entries name files that no code loads — including the three retained decision records at `:32`, `:46` and `:58`, which it lists as live prompts although each says in its own text that it is deliberately not used (§4.2); `:73` names `reports/full_live_matrix_test.{json,md}`, which no script writes. As an *index*, it is the artifact most likely to be believed, and nothing validates it. It is either the map of the system or a V1 historical artifact, and it does not say which.

---

## 7. Active legacy paths that can still execute unexpectedly

This is the issue's reverse-reachability question: live code that should not be live under current scope or authoritative decisions.

### F-01 — the Friday cron (critical)

```
scheduled_publish.yml            cron "17 8 * * 5" and "17 9 * * 5"   ← live
 └ scripts/scheduled_publish.py:226-240   (subprocess, not import)
     1. generate.py --qc                  abort_on_fail=True
     2. generate_image.py --upload
     3. publish.py --live --channels wix
     4. publish.py --live --channels linkedin | facebook | instagram | threads
     5. publish.py --live --channels telegram   (if Wix returned 0)
```

`scripts/publish.py:50-58` maps all six publishers. Neither it, nor `generate.py`, nor `scheduled_publish.py` imports `src/publishing/release_scope.py`. The #229 allowlist governs the canonical entrypoint, the visibility publisher and research Stage 11 — not this path.

The test that says otherwise, `tests/test_r1_publish_scope.py:274`, checks that `scheduled_publish.py` contains no `*Publisher` class name. It cannot see a subprocess. Its docstring's claim that Friday "shells out to the canonical entrypoint" is simply wrong: it shells out to the legacy one.

Friday is owner-declared **paused**. The cron is live.

### F-05 — two Friday publishers, one of them role-less (high)

`research_generate_and_publish.yml` fires Friday **and** Sunday at 07:00 UTC, auto-selects a signal, and calls the canonical entrypoint with **no `--editorial-role`** (`:170`). With no role, `scripts/generate_and_publish.py:1286` cannot take the role-bounded branch: no Never Blank role rules, no surface rules, no source-transparency requirement apply. Monday and Wednesday are the two configured Never Blank products; this path publishes a third thing that no role describes. Its "Check publish secrets" step is additionally skipped on every scheduled run, because `if: inputs.dry_run == 'false'` (`:100`) and `inputs` is empty on a cron.

**Publication ownership of this path is undecided in the repository.** Its own comment (`:30-33`) asserts "Friday and Sunday remain unchanged here" — written before the #229 scope work and before Friday was paused. The owner's 2026-09-15 note says Research publication stays disabled and #238 stays unmerged; this cron is live and is not what #238 gates. *That is the answer to the question the issue asks: nobody owns it, and the workflow comment that claims otherwise predates every decision that would have changed it.*

### F-06 — no concurrency group on three publishing workflows (medium)

`monday_publish.yml`, `wednesday_golden.yml` and `research_generate_and_publish.yml` share `concurrency: never-blank-publish`. `scheduled_publish.yml`, `visibility_publish.yml` and `daily_signal_research.yml` declare none — while several of them append and `git push` the same two files, `data/research/published_signal_ids.txt` and `strategy/published_content_index.jsonl`. On Friday the two publishers can overlap by design.

### F-08 — the #247 recovery (low)

Completed, and its own workflow header (`:9`) and script docstring (`:39`) both ask for removal. Still dispatchable, and it is the one path that can publish to non-R1 channels by design. It is also the best-contained thing in the repository — dispatch-only, dry-run default, typed run-id confirmation, read-only token, digest-bound, single-shot — which is why it is `low` and not higher. It should still not outlive its purpose by accident.

### F-13 — `release_scope.py` claims a control it does not have (medium)

Its docstring (`:1-25`) states that adding a channel is "a change to this file and nowhere else". About twenty other places hard-code Wix and LinkedIn: `generate_and_publish.py:508,509,2768,2314,2582-2632,2821-2825,3129`; `preflight.py:62-65,226,280,484-492`; `visual/contract.py:44-47,146-150,291-309`; `run_report.py:131-136,336,446`; `idempotency.py:227-231,278-305`; `business_config.py:182-184`; `execution_context.py:190-253`; `editorial_role.py:104-106`; and `package.py:174-265`, which has no package model for any other channel at all. Two opposite risks from one false sentence: someone adding a channel by editing that file alone gets a run that passes the allowlist and dies deep in preflight, and someone reading it believes the allowlist is the whole control — which is how F-01 stayed invisible.

---

## 8. Tests and CI gaps that let this happen

Four tests report a contract as met that production does not meet. Each was true when written; production moved underneath three of them.

| Test | Proves | Does not prove |
|---|---|---|
| `tests/strategy/test_never_blank_business_config.py:80` | each `prompt_rule_reference` path `is_file()` | that any code opens it — this is what let `brand_voice.md` ship as a versioned prompt contract no prompt has seen |
| `tests/test_monday_stream.py:203` | `generate_article` was *called with* `editorial_role_rules` (it is patched) | that any model message contains them |
| `tests/test_wednesday_golden.py:397` | the **shared** composer incorporates Golden rules when given them | anything about Wednesday, which composes through a different module that takes no rules (§3) |
| `tests/test_r1_publish_scope.py:274` | `scheduled_publish.py` contains no `*Publisher` name | that Friday reaches no channel — it shells out to a script that reaches all six (§7) |

The general shape: **each proves the weakest thing that is easy to assert** — existence, a call signature, a constructor in isolation, the absence of a symbol.

The structural gap is that **no test in the repository spans entrypoint → model messages.** That is genuinely hard to write naively, for a real reason: every stage does `from src.utils.llm_client import chat`, binding the function *by name*, so patching `src.utils.llm_client.chat` intercepts nothing. The patch must go into each stage module's own namespace. Any guardrail that ignores this will be written, will pass, and will prove nothing — which is the failure this section is about.

A fifth gap has no test at all: **nothing checks that a configuration file loads.** `config/prompts/linkedin_post.yaml` has been unparseable long enough for three separate investigations to record it independently.

Two tests deserve credit as the counter-examples: `tests/test_model_routing.py` ("wired, not just supported") and `tests/strategy/test_strategy_semantic_consumption.py` prove consumption rather than capability, and `tests/test_research_evidence_contract.py` says in its own docstring that it deliberately does not test wiring. Honest scope is not the problem; unstated scope is.

---

## 9. Permanent guardrails

The rule to enforce:

> A new executable/config artifact is not DONE until its intended production consumer is proven. An authoritative product/config artifact intended to influence model output must have a regression test proving that a distinctive instruction/value reaches the actual production model-message construction. Intentional human-only documentation must be clearly distinguishable. Unjustified orphaned production artifacts are not allowed.

Three small things, all inside the gate that already exists (`pr_tests.yml` runs the full suite on every PR and compares against `tests/accepted_full_suite_failures.txt`). No new workflow, no new dependency, no framework.

### G-1 — Configuration parse gate *(~30 lines)*

One test module that walks every tracked `config/**/*.yaml` plus `strategy/current/*.json` and asserts each loads. Prompts carrying `status: not_needed` are asserted to raise the *specific* `ValueError` from `config_loader.py:49-53`, not a parse error, so the two failure modes stay distinguishable.

Would have caught `config/prompts/linkedin_post.yaml` at the commit that broke it. Cheapest durable thing in this document; do it first.

### G-2 — Sentinel wiring test for declared-executable product artifacts *(one module + a two-line schema change)*

For each artifact declared executable — the `prompt_rule_references` block, minus entries explicitly flagged `authoring_only: true`:

1. copy the artifact to a temp path with a unique sentinel inserted;
2. point the loader at the copy;
3. run the production entrypoint for the relevant role with `chat` patched **in each stage module's own namespace**, recording `(module, system, user)` for every call;
4. assert the sentinel appears in at least one recorded message — **and name which stage.**

Step 4's "which stage" is the point. It makes a future move of a rule between stages a visible decision rather than a silent one, which is exactly what `2466611` was allowed to be.

This **replaces**, for executable entries, the `is_file()` assertion at `test_never_blank_business_config.py:80`. Existence remains the right test for `authoring_only` entries — which is also how "intentional human-only documentation must be clearly distinguishable" gets satisfied: by a required flag in the schema, not by a convention.

It will **fail today** for `config/brand_voice.md`. That is the signal, not a reason to weaken it.

### G-3 — Tracked-path classification manifest *(~40 lines)*

Keep `reports/repository_audit/inventory/*.json` — this audit's own output — as a live manifest, and add a test asserting that every tracked path outside the audit directories matches exactly one entry or `paths_file` group. A new file then fails CI until someone writes one line saying what it is for and who consumes it.

Deliberately **not** a reachability analyser. The assertion is that a *human* classified the path, not that a tool proved it: a tool would be wrong about dynamic loading and about `src/never_blank/wednesday_golden.py`, and it would teach people to route around it.

One honest caveat: this only pays for itself if the bulk groups stay groups. If `reports/` keeps accumulating run records the manifest must keep addressing them by `paths_file`, which makes F-02's retention policy a prerequisite rather than a nice-to-have.

---

## 10. Recommended repair order

Ranked by risk, and by whether anything blocks it. **Discovery here does not authorize repair**; each row names its own follow-up issue.

| # | Action | Finding | Blocked on |
|---:|---|---|---|
| 1 | Put a real control in front of the Friday cron — disable the schedule, or make `publish.py` honour `release_scope`, or both. **Do not repair the YAML.** | F-01 | nothing |
| 2 | Decide publication ownership of the Fri/Sun Research path; disable its cron meanwhile | F-05 | owner decision (the interim cron change is not blocked) |
| 3 | Untrack the 7,796 test-run records and the 26 card-audit PNGs; ignore both; isolate `PACKAGES_DIR` in the suite | F-02, F-02b | nothing |
| 4 | Configuration parse gate | G-1 | nothing |
| 5 | Retarget or `xfail` `tests/test_wednesday_golden.py:397` so CI stops asserting an unmet contract | F-10 | nothing — it changes only what CI reports |
| 6 | Add `concurrency: never-blank-publish` to the three workflows that lack it | F-06 | nothing |
| 7 | Documentation-only corrections: the `role_bounded_r1` Decision Lens bypass, the `release_scope` docstring, the two advertised-but-absent package retry paths, one source-of-truth line per conflict | F-12, F-13, F-15, F-14 | nothing, except the Wednesday row of F-14 |
| 8 | Rewrite or retire `docs/SYSTEM_MAP.md` first; then one decision per orphaned group | F-07 | owner decision for the Strategy Engine and investigation groups |
| 9 | Sentinel wiring test, built as part of the first #244 vertical slice | G-2 | the #244 rulings |
| 10 | The product-configuration repairs themselves | F-03, F-04 | #231, #240/#244, and the Wednesday July-fidelity decision — **explicitly out of scope here** |

Rows 1, 3, 4, 5, 6 and 7 are unblocked today and touch no product semantics. Row 10 is where the real editorial work is, and it cannot start until someone rules on §2.4.

---

## 11. Method, and what this audit does not prove

**Sources — and a change of rule.** Every claim is anchored to a file and line at `4a121b2`, or to this repository's own git history quoted under `reports/repository_audit/evidence/`. Nothing here is supported by a document that is not in this tree.

An earlier revision of this report delegated several load-bearing claims to `reports/editorial_wiring/ISSUE_234_EDITORIAL_WIRING_FORENSIC.md`, `ISSUE_244_MONDAY_SEMANTICS_INVENTORY.md`, `reports/audit_inputs/ISSUE_248_META_CHANNEL_AUDIT.md` and `reports/audit_inputs/PY_REACHABILITY.json` — all of them on the unmerged branch `evidence/234-editorial-wiring`, and therefore absent from any checkout of this commit. A reader could not check them, which for the historical conclusions (the STYLE loader's deletion, "no test failed") meant they could not be checked at all. Every one of those citations has been removed and replaced:

- The STYLE disconnection is now quoted in full in `reports/repository_audit/evidence/EDITORIAL_STYLE_DISCONNECTION.md`, from `git show 2466611` and two `git grep`s at `2466611^`, with the commands. The "no test failed" claim is restated in the form the evidence actually supports: no test *referenced* the document or its loader, so none could have failed.
- `config/brand_voice.md` never being wired now rests on `git log --oneline -S brand_voice -- src scripts` returning empty in this repository — a stronger statement than the forensic's, and one anyone can re-run.
- The static import reachability was corroboration only; every DEAD/ORPHANED row was already carrying its own grep and importer chain, and those are what remain. Nothing was reclassified by removing it.
- The `DraftPackage` missing-attribute failure is now anchored to tracked run evidence inside this commit: `data/strategy/visibility_history.jsonl` entries `vis_005` and `vis_006` record the exact exception strings.
- The Monday prompt chain is now cited per stage, by file and line, in `reports/repository_audit/inventory/03_src.json` — the thirteen `_SYSTEM_PROMPT` constants and the two that read YAML.

`reports/monday-architecture/MONDAY_CURRENT_STATE.md` remains cited and remains checkable: it is merged on `main`. Where it and this audit differ, it is anchored to the earlier commit.

**Limits, stated plainly:**

- **No execution.** This environment could not run Python, so nothing here was verified by running it. The most consequential place that matters is `config/prompts/linkedin_post.yaml`: **I did not parse it.** The classification rests on two things a reader of this commit can check and one they cannot. Checkable: `tests/test_cross_platform_overlap_policy.py:312-320`, whose docstring states in the repository's own words that "that file does not currently parse as YAML (an inline `#hashtag` truncates a scalar around line 64), a pre-existing defect on the non-R1 `generate_content_package` path" — and which reads the file as raw text specifically to avoid `load_prompt`; and the readable mechanism at `:62-65`, where a space-preceded `#` opens a YAML comment inside a block-sequence scalar and `(never use):` additionally turns the item into a mapping. Not checkable from this tree: the owner's verification comment of 2026-09-15 quoting the PyYAML error, which lives in the #234 issue thread. Nothing in this audit rests on that third item alone.
- **Static reachability under-reports and over-reports.** It cannot follow dynamic dispatch — `src/editorial/vi_pipeline.py:80` builds a prompt filename from an enum value, which is why the three `config/prompts/visibility/*.yaml` files are ACTIVE despite matching no literal string in the codebase. And it over-reports the other way: an imported module is not an executed one (§2.2). Every DEAD/ORPHANED classification here was checked for both, and none is offered as grounds for deletion.
- **Reachable is not executed.** `ACTIVE_RUNTIME` means a workflow can reach it, not that it runs on a given day. Several ACTIVE_RUNTIME paths are on streams the owner has paused; that is recorded per entry, and it is the substance of §7.
- **Two workflow-run facts are unknowable from the repository:** whether the #247 recovery was actually dispatched (F-08), and whether any Friday run has reached `publish.py` since the YAML broke. Both are answerable from GitHub run records, which this audit did not query.

**Coverage, verified mechanically.** The union of every `path` entry and every line of every `paths_file`, sorted, is byte-identical to `git ls-files` at `4a121b2`: 8,392 paths, no omission, no duplicate, nothing outside the commit. Both high-risk classes carry one entry per path and appear in no group.

---

*Read-only audit. No production code or configuration was modified, nothing was published, no provider call was made, and the unresolved product choice in #231 was not made implicitly.*
