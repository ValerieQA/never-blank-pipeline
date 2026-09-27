# GitHub Actions audit

Issue #326, Phase 1. Audited against `main` at `2b28b5edc84750a86152ac0913aeb55db0189b07`.

**This document changes nothing.** It is the evidence the issue requires before any
workflow may be deleted, and its result is that **no workflow is proposed for
deletion yet** — three are close, and each is missing one fact a person has to
supply. Section 5 says exactly which.

## 1 · How the evidence was gathered

| Question | How |
|---|---|
| Triggers and cron | parsed each file as YAML, not read by eye |
| Scripts invoked | `scripts/**.py` referenced in the file, then checked each exists |
| Can it publish? | presence of destination secrets (`NB_WIX_*`, `NB_LINKEDIN_*`, Meta, Telegram) |
| Can it spend money? | presence of provider secrets (`NB_OPENAI_*`, Cloudinary) |
| Is it referenced? | `grep -rl "<name>.yml"` across `*.md`, `*.py`, `*.yml`, `*.txt`, excluding the file itself |
| Does it actually pass? | `gh run list`, last 12 runs per workflow |

Two corrections the evidence forced, both worth stating because they contradict
what was previously believed:

- **`strategy_tests.yml` is not red.** Its last 12 runs are 12 × success. It had
  been carried as a known-red workflow; it is not one now.
- **A reference count from a loose grep is worthless.** Searching `publish`
  matched `scripts/publish.py` in 339 files. Every count below is for the exact
  `<name>.yml` string.

Every script referenced by every workflow exists. **No workflow calls another** —
no `workflow_call`, `workflow_run` or local `uses:`, so there are no reusable
workflows and no hidden callers.

## 2 · Inventory — 20 workflows

| # | File | Actions name | Triggers | Cron (UTC) | Publishes | Paid | Refs | Last 12 runs |
|---|---|---|---|---|---|---|---|---|
| 1 | `pr_tests.yml` | PR Tests | pull_request, dispatch | — | no | no | 3 | 12 ✅ |
| 2 | `strategy_tests.yml` | Strategy Engine Tests | pull_request, push, dispatch | — | no | no | 2 | 12 ✅ |
| 3 | `editorial_preflight.yml` | Editorial Publishing Preflight | push, dispatch | — | no | no | 1 | 8 ✅ / 4 ❌ |
| 4 | `monday_publish.yml` | Monday — Never Blank Business Case | dispatch only | **paused** | YES | YES | 24 | 7 ✅ / 5 ❌ |
| 5 | `wednesday_golden.yml` | Wednesday — Never Blank Golden | schedule, dispatch | `17 8/9 * * 3` | YES | YES | 13 | 8 ✅ / 4 ❌ |
| 6 | `scheduled_publish.yml` | Scheduled Publisher | schedule, dispatch | `17 8/9 * * 5` | YES | YES | 12 | 8 ✅ / 2 ❌ |
| 7 | `knowledge_maintenance.yml` | Knowledge Maintenance | schedule, dispatch | `0 13 * * *` | no | no | 1 | **3 ❌** |
| 8 | `daily_signal_research.yml` | Daily Signal Research | schedule, dispatch | `0 8 * * *` | YES | YES | 14 | 3 ✅ / **9 ❌** |
| 9 | `visibility_publish.yml` | Visibility Intelligence | schedule, dispatch | `0 7 * * 2,4` | YES | YES | 9 | **9 ❌** |
| 10 | `research_generate_and_publish.yml` | Research — Full LLM Cycle | schedule, dispatch | `0 7 * * 5,0` | YES | YES | 14 | **9 ❌** |
| 11 | `recovery_wednesday_meta_247.yml` | Recovery — Wednesday Meta (#247) | dispatch only | — | YES | no | 2 | — |
| 12 | `generate_and_publish.yml` | Generate + Image + Publish | dispatch only | — | YES | YES | 18 | — |
| 13 | `publish.yml` | Publisher | dispatch only | — | YES | YES | 32 | — |
| 14 | `generate_content.yml` | Generate Content | dispatch only | — | no | YES | 2 | — |
| 15 | `generate_image.yml` | Generate Image | dispatch only | — | no | YES | 4 | — |
| 16 | `run_analytics.yml` | Run Analytics Pipeline | dispatch only | — | YES | no | 1 | — |
| 17 | `connectivity_audit.yml` | Publisher Connectivity Audit | dispatch only | — | YES | YES | 2 | — |
| 18 | `live_publish_test.yml` | Phase 5D — Live Publish Test | dispatch only | — | YES | YES | 4 | — |
| 19 | `smoke_test_full_cycle.yml` | Smoke Test — Full Publish + Analytics | dispatch only | — | YES | no | 3 | — |
| 20 | `smoke_test_wix_image.yml` | Smoke Test — Wix Cover Image | dispatch only | — | YES | no | **0** | — |

## 3 · Schedule ownership, as the files themselves state it

| Day | Owner | State |
|---|---|---|
| Monday | `monday_publish.yml` | **schedule paused** — *"SCHEDULE PAUSED — temporary safety control, not a product change"* |
| Wednesday | `wednesday_golden.yml` | scheduled, running |
| Friday | `scheduled_publish.yml` | scheduled, running — **legacy path until #144** |
| Tue / Thu | `visibility_publish.yml` | scheduled, failing every run |
| Fri / Sun | `research_generate_and_publish.yml` | scheduled, failing every run |
| Daily 08:00 | `daily_signal_research.yml` | owner-disabled in the Actions UI |
| Daily 13:00 | `knowledge_maintenance.yml` | scheduled, failing every run |

`scheduled_publish.yml` had Monday and Wednesday removed by #142 — its own header
explains that two publishers on one day is two articles, and that the consumption
marker is written after a run so it can never act as a concurrency guard. **No two
workflows are scheduled for the same day.**

## 4 · Dispositions

### KEEP — 8

`pr_tests.yml`, `strategy_tests.yml` — the PR gates, both green.
`editorial_preflight.yml` — push-triggered preflight; its 4 failures are branch
states, not a workflow defect.
`monday_publish.yml`, `wednesday_golden.yml` — the canonical Monday and Wednesday
publishers. Monday's pause is a deliberate safety control and not a reason to
touch the file.
`knowledge_maintenance.yml` — required, and its failure is configuration rather
than code (§5.1).
`generate_image.yml`, `run_analytics.yml` — dispatch-only utilities that publish
nothing editorial; no duplicate exists.

### KEEP TEMPORARILY — 2

| Workflow | Required until | Removal condition |
|---|---|---|
| `scheduled_publish.yml` | **#144** | Friday moves to the canonical entrypoint. Stated in the file's own header |
| `recovery_wednesday_meta_247.yml` | **#247** | That issue is still OPEN; it is the one-time recovery path for those saved payloads. Delete when #247 closes |

### DISABLE — 1

`daily_signal_research.yml`. Already disabled by the owner in the Actions UI and
must not be re-enabled. It cannot be deleted yet: **#231 is an open owner decision**
about whether daily research publishes at all, and option B would reuse this
workflow. Retain, do not schedule, revisit when #231 is answered.

### INVESTIGATE — 9

Two are blocked on an open issue, and seven are dispatch-only paths capable of
live publication whose obsolescence cannot be proven from the repository alone.

| Workflow | What is missing |
|---|---|
| `visibility_publish.yml` | **#236** — red every run on a provider 400. That issue offers three resolutions, one of which is "stop scheduling". Disposition follows #236 |
| `research_generate_and_publish.yml` | **#236**, same failure shape and same three resolutions |
| `generate_and_publish.yml` | 18 references, and it is the legacy manual generate→publish path. Whether the owner still uses it to publish by hand is not answerable from the repository |
| `publish.yml` | 32 references — the most-referenced workflow in the repository. Almost certainly still the manual publisher of record; needs confirmation, not inference |
| `generate_content.yml` | dispatch-only generation, no publish secrets. Possibly superseded by the canonical streams; 2 references give no evidence either way |
| `connectivity_audit.yml` | a diagnostic that touches every publisher. Useful precisely when something is broken, so "unused" is not evidence of obsolete |
| `live_publish_test.yml` | named for **Phase 5D**, a completed migration phase, which is the strongest obsolescence signal here — but it can publish live, and 4 references remain |
| `smoke_test_full_cycle.yml` | can publish; 3 references; overlaps `connectivity_audit.yml` and `run_analytics.yml` in part but is not obviously redundant to either |
| `smoke_test_wix_image.yml` | **0 references** — the only workflow nothing mentions. Still needs one fact: whether any other path covers Wix cover-image verification |

### DELETE — 0

Nothing is proposed for deletion. The issue requires each `DELETE` to prove that
no active workflow calls it, no current production path requires it, no Editorial
Core migration task expects to reuse it, **and** that it is not the only
implementation of an active responsibility. The first three hold for several of
the nine above; the fourth cannot be established from the repository for any
workflow capable of live publication, because "nobody has run it lately" and
"nobody needs it" are different claims.

Per the issue's own instruction — *"If any proposed deletion is ambiguous, stop
after the audit and report it rather than deleting"* — the audit stops here.

## 5 · What needs a person

### 5.1 `KNOWLEDGE_MAINTENANCE_WARNING_DAYS` is not set — and that is why the job is red

`Knowledge Maintenance` has failed every run, most recently 2026-09-26. The cause
is not a defect:

> The warning window is not configured. Set the repository variable
> `KNOWLEDGE_MAINTENANCE_WARNING_DAYS` … Step 4 §5.2 asks for a warning window and
> deliberately fixes no duration, so this job will not choose one. `'0'` is a valid
> setting and means: no advance warning, queue a record only when it is due or past
> due.

The workflow is refusing to invent a policy the architecture left open (#297). It
will stay red until the variable exists, and a daily red workflow is exactly the
thing that teaches everyone to stop reading the colour. **Decision: pick a number
of days (`0` is valid) and set the repository variable.** No code change.

### 5.2 The three near-DELETE candidates

Each needs one yes/no that only the owner has:

1. `smoke_test_wix_image.yml` — is Wix cover-image verification covered anywhere else?
2. `live_publish_test.yml` — is Phase 5D finished for good, so its live test has no remaining use?
3. `generate_content.yml` — is hand-run generation without publishing still used?

A yes to 1's replacement, and a no to 2 and 3, would make all three provable
`DELETE`s in the separate cleanup PR the issue asks for.

### 5.3 Two open issues own four dispositions

`#231` decides `daily_signal_research.yml`. `#236` decides
`visibility_publish.yml` and `research_generate_and_publish.yml`. `#144` releases
`scheduled_publish.yml`. None can be pre-empted here.

## 6 · Counts

```
current total  20
KEEP            8
KEEP TEMPORARILY 2
DISABLE         1
DELETE          0
INVESTIGATE     9
```

**Remaining active scheduled workflows: 6** — `wednesday_golden.yml`,
`scheduled_publish.yml`, `knowledge_maintenance.yml`, `daily_signal_research.yml`
(disabled in the UI, schedule still in the file), `visibility_publish.yml`,
`research_generate_and_publish.yml`. Monday's is paused in the file.

**Remaining workflows capable of live publication: 12** — every one in the
inventory marked *Publishes: YES*. That is more than half the workflows in the
repository, and it is the number worth reducing first.

## 7 · Not done here

No workflow was added, removed, renamed, disabled or re-enabled. No publication
behaviour changed. No client knowledge, no Editorial Core code, no paid API call,
no live publication. The cleanup PR the issue describes remains to be opened once
§5.2's three answers exist.
