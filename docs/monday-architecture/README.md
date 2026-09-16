# Monday architecture (Issue #240)

Design deliverable for *[MONDAY][ARCH][HIGH] Rebuild Monday around
human-readable strategy*. **Architecture and design only — no production change
is implemented or proposed for execution before owner review.**

## The two documents

| Document | Issue deliverables | What it is |
|---|---|---|
| [`reports/monday-architecture/monday_current_state_trace.md`](../../reports/monday-architecture/monday_current_state_trace.md) | 1–6 | Forensic record of what Monday executes today: end-to-end execution, per-stage classification, product semantics hard-coded in Python, config Monday does and does not consume, the `business_strategy.json` dependency map, and the narrow eligibility contract with its 15-candidate mechanism. Its **§0** is the audit incorporation the issue requires — what #233 and #237 establish, and how each finding relates to this trace. |
| [`MONDAY_TARGET_ARCHITECTURE.md`](MONDAY_TARGET_ARCHITECTURE.md) | 7–12 | The proposal: human-readable Markdown source of truth, generic runtime, KEEP/CHANGE/REPLACE/RETIRE, migration order, the tests that would prove it, and the owner decisions still required. |

Read the trace first. Every claim in the proposal is anchored to it.

## Status

- **Scope:** Monday only. Wednesday and Friday are paused and untouched.
- **Gate (#233):** the audit deliverables exist — on branch `orch/233`
  (`origin/orch/233`), not yet merged to `main`, which is why they are not in
  this working tree. Their Monday-relevant findings **are incorporated** in
  trace §0a and reconciled through the target document; the remaining gate is
  procedural (#233 merges) plus one mechanical prerequisite (its F5 artifact-root
  fix, which the §11 tests depend on). See [§10 step 0](MONDAY_TARGET_ARCHITECTURE.md#10-migration-order).
- **#237:** the landed editorial-wiring forensic
  (`docs/MONDAY_SELECTION_HEAD_OF_LINE.md` on `orch/237`) is incorporated in
  trace §7d. It **corrects** this report rather than only supporting it — see
  below.
- **#234:** not present in the working tree, in any local or remote-tracked
  branch, or in any commit message, and GitHub is not reachable from this
  worktree. Trace §0c records exactly what was searched and states the bounded
  gap: if #234 holds editorial-wiring findings beyond #233's F1/F3/F6/F9 and
  #237's, this report should be re-reconciled against them.
- **`strategy/current/business_strategy.json`:** traced, classified, **not
  modified and not deleted**, as the issue requires.

## What the audits changed

Incorporating #233 and #237 was not confirmation. Four things moved:

1. **Selection is blocked by a mechanism, not by the criteria** (#237). The
   queue is oldest-first and rejections are never persisted, so the same
   15-candidate head is re-judged every Monday and 73 September signals are
   unreachable. The trace's original claim that widening the eligibility
   contract "reduces sweep depth naturally" was wrong and is corrected in
   §7b/§7d; migration step 6 gains a new blocking decision, **D12**.
2. **Monday's strategy does not govern everything that publishes on a Monday**
   (#233 F4d). The daily research path's Monday publish decision is a secret,
   and it has published live. New decision **D13**.
3. **Retiring `config/brand_voice.md` is not file-only** (#233 F9d): a test
   outside the Monday path asserts on its text, and that guarantee has to move
   with the content.
4. **The tests in §11 have a prerequisite** (#233 F5): until the artifact root
   is injectable, the end-to-end test that would prove this migration also
   writes run residue into the tracked tree.

## The finding in one paragraph

Monday's editorial strategy has three authorities that do not agree. The
`editorial_roles[0]` block in `business_strategy.json` holds ~330 lines of
product strategy as JSON — the interface the owner contract says must not be
the human interface. The eight editorial stage modules hold a second copy as
Python prompt literals and deterministic validators, including
`pattern_extractor`'s hard assertion that an article's protagonist is always
`"owner"` — the hardest-coded product decision on the path, and the one that
makes a second stream impossible to express in the shared engine. A third copy
sits in Markdown that reads as authoritative
(`config/brand_voice.md`, `strategy/worldview.md`,
`docs/NEVER_BLANK_EDITORIAL_*.md`, `strategy/current/strategy.md`) and that **no
code opens** — six of the seven `prompt_rule_references` entries name files the
runtime never reads. Six rules are currently maintained in two or more of those
places at once, two of them at different values. The proposal makes Markdown the
only authority, reduces `business_strategy.json` to generated machine data, and
turns the eight product-shaped stage modules into instances of five generic
capabilities that take their meaning as data.

## Owner decisions

Thirteen are listed in [§12](MONDAY_TARGET_ARCHITECTURE.md#12-genuine-owner-decisions-still-required);
D12 and D13 come from the audits. Three block the migration outright: **D1**
(what replaces the superseded eligibility contract), **D3** (whether Monday
reinstates the Decision Lens) and **D12** (whether the selection window
advances at all). No replacement editorial strategy was invented where
owner-approved material was insufficient — the gaps are surfaced as decisions
instead.
