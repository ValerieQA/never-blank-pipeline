# Monday architecture (Issue #240)

Design deliverable for *[MONDAY][ARCH][HIGH] Rebuild Monday around
human-readable strategy*. **Architecture and design only — no production change
is implemented or proposed for execution before owner review.**

## The two documents

| Document | Issue deliverables | What it is |
|---|---|---|
| [`reports/monday-architecture/monday_current_state_trace.md`](../../reports/monday-architecture/monday_current_state_trace.md) | 1–6 | Forensic record of what Monday executes today: end-to-end execution, per-stage classification, product semantics hard-coded in Python, config Monday does and does not consume, the `business_strategy.json` dependency map, and the narrow eligibility contract with its 15-candidate mechanism. |
| [`MONDAY_TARGET_ARCHITECTURE.md`](MONDAY_TARGET_ARCHITECTURE.md) | 7–12 | The proposal: human-readable Markdown source of truth, generic runtime, KEEP/CHANGE/REPLACE/RETIRE, migration order, the tests that would prove it, and the owner decisions still required. |

Read the trace first. Every claim in the proposal is anchored to it.

## Status

- **Scope:** Monday only. Wednesday and Friday are paused and untouched.
- **Gate (#233):** the audit deliverables this task depends on **do not exist in
  this repository**. That does not block this report — a report is not a
  production change — but it does block implementation. The trace is therefore
  first-hand rather than derived from a prior audit, and the migration order's
  step 0 is the gate. See trace §0.
- **#234:** likewise absent; no editorial-wiring findings were available to
  incorporate.
- **`strategy/current/business_strategy.json`:** traced, classified, **not
  modified and not deleted**, as the issue requires.

## The finding in one paragraph

Monday's editorial strategy has three authorities that do not agree. The
`editorial_roles[0]` block in `business_strategy.json` holds ~330 lines of
product strategy as JSON — the interface the owner contract says must not be
the human interface. The eight editorial stage modules hold a second copy as
Python prompt literals and deterministic validators, including
`pattern_extractor`'s hard assertion that an article's protagonist is always
`"owner"` — the single decision that forced Wednesday to fork into its own
package. A third copy sits in Markdown that reads as authoritative
(`config/brand_voice.md`, `strategy/worldview.md`,
`docs/NEVER_BLANK_EDITORIAL_*.md`, `strategy/current/strategy.md`) and that **no
code opens** — six of the seven `prompt_rule_references` entries name files the
runtime never reads. Six rules are currently maintained in two or more of those
places at once, two of them at different values. The proposal makes Markdown the
only authority, reduces `business_strategy.json` to generated machine data, and
turns the eight product-shaped stage modules into instances of five generic
capabilities that take their meaning as data.

## Owner decisions

Eleven are listed in [§12](MONDAY_TARGET_ARCHITECTURE.md#12-genuine-owner-decisions-still-required).
Two block the migration outright: **D1** (what replaces the superseded
eligibility contract) and **D3** (whether Monday reinstates the Decision Lens).
No replacement editorial strategy was invented where owner-approved material was
insufficient — the gaps are surfaced as decisions instead.
