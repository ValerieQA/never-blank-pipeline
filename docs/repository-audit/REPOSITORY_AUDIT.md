# [R1][AUDIT] Full repository reachability and dead-artifact audit — Issue #233

**Audited commit:** `4a121b2b63983d91581bf241234f9a02647124ce` (`main` at 2026-09-17)
**Tracked paths classified:** 8,392 — every tracked path outside `reports/repository_audit/**` and `docs/repository-audit/**`, exactly once
**Method:** read-only. Nothing was published, no provider call was made, no `CONTROLLED_LIVE` run was started, and no production code or configuration was modified.

| Deliverable | Path |
|---|---|
| Machine inventory | `reports/repository_audit/inventory/*.json` (10 shards, 453 entries) |
| Bulk path lists | `reports/repository_audit/paths/*.txt` (7 files, 7,946 paths) |
| Findings and guardrails | `reports/repository_audit/findings.json` |
| This report | `docs/repository-audit/REPOSITORY_AUDIT.md` |

---

## 1. Executive summary

Two sentences, because they are the whole audit:

**Ninety-three per cent of this repository is debris from test runs that nothing reads, and the editorial contracts the product is named after reach no prompt.** Everything else below is detail, sequencing, or a smaller version of one of those two.

The single most urgent item is neither. It is that **a live Friday cron stands in front of a six-channel publisher that no allowlist covers, and the only thing currently stopping it is a YAML file that fails to parse** — a defect standing in for a control that does not exist (F-01).

### Counts by classification

| Classification | Paths | Outside `reports/` |
|---|---:|---:|
| ACTIVE RUNTIME | 157 | 157 |
| ACTIVE SUPPORT | 246 | 135 |
| AUTHORITATIVE PRODUCT CONFIG — WIRED | 28 | 28 |
| **AUTHORITATIVE PRODUCT CONFIG — UNWIRED/PARTIAL** | **13** | **13** |
| HUMAN DOCUMENTATION | 38 | 37 |
| LEGACY BUT INTENTIONAL | 57 | 36 |
| DEAD / ORPHANED | 7,849 | 25 |
| DUPLICATE / SUPERSEDED | 2 | 2 |
| **SUSPICIOUS / UNRESOLVED** | **2** | **2** |
| **Total** | **8,392** | **435** |

The right-hand column is the one to read. Of 435 tracked paths outside `reports/`, 25 are dead. Of the 7,957 paths under `reports/`, 7,824 are.

### What is genuinely healthy

Worth saying plainly, because an audit that only lists defects misrepresents the repository. The research pipeline, the canonical entrypoint's artifact/provenance/preflight/reporting chain, the visual system, the publishers, the run-identity layer and the call-budget ceilings are all reachable, tested and consistent. The Visibility Intelligence stream is the only stream whose editorial prompts are configuration files end to end — `config/prompts/visibility/*.yaml` is loaded by `src/editorial/vi_pipeline.py:83` and reaches the model. Two places in the repository do artifact retention *correctly*, with the reason written next to the mechanism: `.gitignore:18-19` (the corporate-backlog archive, naming Issue #142) and `strategy/decision_log.md` decision 77 (the two research files). Those are the patterns the fixes below should copy.

---

## 2. AUTHORITATIVE PRODUCT CONFIG — UNWIRED / PARTIAL

Thirteen paths. These are first because the issue asks for them first, and because they are the ones where existence is most convincingly mistaken for implementation.

The structural cause is one line long: **no loader in this repository can read Markdown as configuration.** `src/utils/config_loader.py:11,38` read YAML; `src/strategy/business_config.py:272` reads JSON. Every `.md` opened anywhere in `src/` or `scripts/` is a report being written. So the chain

```
artifact → loader → runtime object → production consumer → model-message construction
```

breaks at the first link for every Markdown product contract, and the documents that declare those contracts executable — `prompt_rule_references`, `research_references` — are validated as *strings*, never opened.

### 2.1 The ten documents

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

`docs/NEVER_BLANK_EDITORIAL_STYLE.md` deserves its own sentence. It was genuinely executable: `scripts/research/publish_packages._load_editorial_style()` injected its text verbatim into the article prompt as `EDITORIAL STYLE (mandatory — follow exactly):`. Commit `2466611` replaced that generation call with the V2 pipeline and deleted the loader. The commit message does not mention it. **No test failed**, because no test ever asserted that STYLE content reached a prompt. That is the exact failure mode the guardrail in §9 exists to prevent, and it is not hypothetical — it already happened, and nobody noticed for ten weeks.

### 2.2 The three machine artifacts

- **`strategy/current/business_strategy.json` — partial.** It loads on every canonical run. Of the fifteen model calls on the Monday path its content reaches three: `decision_lens_lite`, `never_blank_voice`, and the `platform_composer` channel plus role rules. For Wednesday its role rules reach generation not at all. Its `prompt_rule_references` block is the inventory that made seven of the ten documents above look wired.
- **`config/never_blank/wednesday_golden.yaml` — unwired.** See §3.
- **`src/never_blank/wednesday_golden.py` — unwired loader.** It *executes* in production, because `src/never_blank/__init__.py:7` re-exports it and `scripts/generate_and_publish.py:175` imports the package. No production call site ever invokes `load()`, `source_eligibility_rules()` or `generation_rules()`. Only tests do. An eagerly re-exported loader that nothing calls is the most convincing possible disguise for an unwired artifact: static reachability says yes, execution says no.

### 2.3 Conflicts that must be resolved before any of this is repaired

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

**Yes, for now — the 63 daily research reports and 47 per-signal packages.** Their tracking is deliberate and expressed in the workflow that commits them (`daily_signal_research.yml:106`), and `src/run/code_identity.py:34-43` states the repository's own position: `reports/` and `data/` are output roots a run legitimately dirties, and a rule covering them "would make the second of two consecutive runs permanently non-qualifying". That reasoning is sound. What those groups lack is a **retention policy**, not a justification.

There is a third, smaller case that is worse than either: **`reports/card_audit/`, 26 PNGs, tracked against an explicitly recorded decision.** `strategy/decision_log.md` decision 97 (2026-08-07) records the owner deciding that this directory stays untracked — *"не добавлен в .gitignore и не закоммичен — статус untracked сохраняется до отдельного решения"* — and the Часть 22 status line repeats it. `ffe199a` committed all 26 ten days later. The decision log is the record of truth; the repository contradicting it is a defect in the repository, not in the log.

### 4.2 The 25 outside `reports/`

| Group | Paths | Why dead |
|---|---:|---|
| Strategy Engine monthly loop | 9 | `src/strategy/{market_analyzer,content_planner,decision_engine,pattern_extractor}.py` + `scripts/strategy/*`. No workflow executes any of them; `strategy_tests.yml:64-67` only `py_compile`s them, and compiling is not a consumer. `build_monthly_plan.py:33` reads `reports/signals/`, which does not exist; `content_planner.py` writes `strategy/current/content_plan.*`, which does not exist. Built to the spec in `strategy/claude_code_prompt_strategy_engine_FINAL_2026-07-22.md`, and never wired. |
| Their output directories | 3 | `strategy/reviews/{weekly,monthly,recommendations}/.gitkeep` — no review has ever been written. |
| Investigation layer | 2 | `src/investigation/*`. Only consumer is its own test. |
| Orphaned scripts | 3 | `scripts/dry_run.py`, `scripts/render_card_audit.py`, `scripts/research/sync_from_sheets.py`. The last one is the human-override half of the two-way sheet sync that `docs/SYSTEM_MAP.md:17` presents as part of the pipeline; `run_daily_research.py:31` imports only `sync_to_sheets`. |
| Orphaned config and prompts | 8 | `config/content_matrix.yaml` (shadowed by `config/prompts/content_matrix.yaml`), `config/intelligence.yaml` (loaded only from the unreachable `dry_run.py`), four observation/topic prompts named only in `dry_run.py`, and three prompts carrying `status: not_needed`, which `config_loader.py:49-53` turns into a raised `ValueError` — they cannot be loaded even on purpose. |

**Do not delete any of these on static-search evidence alone.** Each group corresponds to a documented intention, and the issue forbids deletion on the strength of a missing import. What they need is one owner decision per group.

---

## 5. DUPLICATE / SUPERSEDED and source-of-truth conflicts

Only two paths carry the classification, because most duplication here is *unresolved* rather than *superseded*: nobody has said which copy wins.

| Subject | Copies | Winner today |
|---|---|---|
| Wednesday Golden contract | `config/never_blank/wednesday_golden.yaml`, `docs/NEVER_BLANK_GOLDEN_EDITORIAL_PATTERNS.md`, `docs/product/wednesday_golden_contract.md` | none declared; the runtime honours only `business_strategy.json:442-443` |
| Never Blank worldview | `strategy/worldview.md` (RU, declared at `strategy.json:59`), `docs/NEVER_BLANK_EDITORIAL_WORLDVIEW.md` (EN, declared nowhere) | none declared |
| Active strategy | `strategy/current/strategy.json` (executed), `strategy/current/strategy.md` (hand-maintained) | the JSON — which is the inverse of the owner's 2026-09-15 ruling |

The Strategy Engine build prompts are the counter-example and the model to copy: `claude_code_prompt_strategy_engine_FINAL_2026-07-22.md:3-6` says in its own first paragraph which document is the base spec. That one line is the entire fix for the three rows above.

Four further collisions make the wrong file easy to open:

- `scripts/generate_and_publish.py` (**the** canonical entrypoint) vs `.github/workflows/generate_and_publish.yml` (a manual **legacy** workflow that never touches it). Identical names, opposite meanings.
- `config/strategy.yaml` (V1, legacy Friday) vs `strategy/current/strategy.json` (canonical). Neither mentions the other.
- `src/editorial/pattern_extractor.py` (live) vs `src/strategy/pattern_extractor.py` (dead).
- Two schedule authorities: Monday/Wednesday use crons + `scripts/streams/due_check.py`; Friday uses `config/schedule.yaml` + `scripts/scheduled_publish.py:180`. Only the first is covered by a test.

---

## 6. SUSPICIOUS / UNRESOLVED

Two paths. Both are unresolved in the strict sense the issue means: their purpose cannot be established safely.

**`config/prompts/linkedin_post.yaml`.** It is reached by a live scheduled entrypoint, it raises on load, and that raise is currently the only thing preventing an unscoped six-channel publication. Whether it is configuration or a brake cannot be answered from the repository — and the owner has already ruled that it must not be "fixed", because fixing it re-enables the publisher. A file whose *defect* is load-bearing is not classifiable as ACTIVE. See F-01.

**`docs/SYSTEM_MAP.md`.** It presents itself as the index of the system, and it describes only V1. Monday, Wednesday, Visibility, the canonical entrypoint and `release_scope` are absent entirely. Seven of its entries point at files with no consumer; `:73` names `reports/full_live_matrix_test.{json,md}`, which no script writes. As an *index*, it is the artifact most likely to be believed, and nothing validates it. It is either the map of the system or a V1 historical artifact, and it does not say which.

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
| 7 | Documentation-only corrections: the `role_bounded_r1` Decision Lens bypass, the `release_scope` docstring, one source-of-truth line per conflict | F-12, F-13, F-14 | nothing |
| 8 | Rewrite or retire `docs/SYSTEM_MAP.md` first; then one decision per orphaned group | F-07 | owner decision for the Strategy Engine and investigation groups |
| 9 | Sentinel wiring test, built as part of the first #244 vertical slice | G-2 | the #244 rulings |
| 10 | The product-configuration repairs themselves | F-03, F-04 | #231, #240/#244, and the Wednesday July-fidelity decision — **explicitly out of scope here** |

Rows 1, 3, 4, 5, 6 and 7 are unblocked today and touch no product semantics. Row 10 is where the real editorial work is, and it cannot start until someone rules on §2.3.

---

## 11. Method, and what this audit does not prove

**Sources.** Every claim is anchored to a file and line at `4a121b2`. Where I relied on prior work rather than re-deriving it — the Monday and Wednesday prompt chains, the Meta channel matrix, the static import reachability — the source is named: `reports/editorial_wiring/ISSUE_234_EDITORIAL_WIRING_FORENSIC.md`, `reports/editorial_wiring/ISSUE_244_MONDAY_SEMANTICS_INVENTORY.md`, `reports/audit_inputs/ISSUE_248_META_CHANNEL_AUDIT.md` and `reports/audit_inputs/PY_REACHABILITY.json`, all on the unmerged branch `evidence/234-editorial-wiring`, plus `reports/monday-architecture/MONDAY_CURRENT_STATE.md` on `main`. Those were treated as evidence to check against source, not as verdicts to copy; where I checked them they held, and §2.2 corrects one of them in a small way (`PY_REACHABILITY.json` lists `src/never_blank/wednesday_golden.py` as unreachable — it is in fact imported in production via the package `__init__`, and unreachable only in the sense that matters, which is that nothing calls it).

**Limits, stated plainly:**

- **No execution.** This environment could not run Python, so nothing here was verified by running it. The most consequential place that matters is `config/prompts/linkedin_post.yaml`: I did not parse it. The classification rests on three independent in-repo records — `tests/test_cross_platform_overlap_policy.py:312-320`, the #234 forensic, and the owner's verification comment quoting the PyYAML error — plus the readable mechanism at lines 63-67, where a space-preceded `#` opens a YAML comment inside a block-sequence scalar.
- **Static reachability under-reports and over-reports.** It cannot follow dynamic dispatch — `src/editorial/vi_pipeline.py:80` builds a prompt filename from an enum value, which is why the three `config/prompts/visibility/*.yaml` files are ACTIVE despite matching no literal string in the codebase. And it over-reports the other way: an imported module is not an executed one (§2.2). Every DEAD/ORPHANED classification here was checked for both, and none is offered as grounds for deletion.
- **Reachable is not executed.** `ACTIVE_RUNTIME` means a workflow can reach it, not that it runs on a given day. Several ACTIVE_RUNTIME paths are on streams the owner has paused; that is recorded per entry, and it is the substance of §7.
- **Two workflow-run facts are unknowable from the repository:** whether the #247 recovery was actually dispatched (F-08), and whether any Friday run has reached `publish.py` since the YAML broke. Both are answerable from GitHub run records, which this audit did not query.

**Coverage, verified mechanically.** The union of every `path` entry and every line of every `paths_file`, sorted, is byte-identical to `git ls-files` at `4a121b2`: 8,392 paths, no omission, no duplicate, nothing outside the commit. Both high-risk classes carry one entry per path and appear in no group.

---

*Read-only audit. No production code or configuration was modified, nothing was published, no provider call was made, and the unresolved product choice in #231 was not made implicitly.*
