# Monday architecture (Issue #240)

Design deliverable for *[MONDAY][ARCH][HIGH] Rebuild Monday around
human-readable strategy*. **Architecture and design only.** No production change
is implemented, and none is proposed for execution before owner review.
`strategy/current/business_strategy.json` is traced and classified; it is not
modified and not deleted.

## The two documents

| Document | Issue deliverables | What it is |
|---|---|---|
| [`reports/monday-architecture/MONDAY_CURRENT_STATE.md`](../../reports/monday-architecture/MONDAY_CURRENT_STATE.md) | 1–6 | What Monday executes today: the end-to-end path, a stage-by-stage classification on the seven axes the issue names, the product semantics hard-coded in Python, the configuration Monday does and does not consume, the `business_strategy.json` dependency map, and the superseded eligibility contract with its 15-candidate mechanism. Its §0 is the audit incorporation the issue requires. |
| [`MONDAY_TARGET_ARCHITECTURE.md`](MONDAY_TARGET_ARCHITECTURE.md) | 7–12 | The proposal: the Markdown source of truth, the generic runtime, KEEP/CHANGE/REPLACE/RETIRE, the migration order, the tests that would prove the chain, and the owner decisions still required. |

Read the trace first. Every claim in the proposal is anchored to it, and both
are anchored to `58afe47`.

## Gate status

The issue makes #233 an execution gate and names #234 as evidence. Both exist,
and both are incorporated. Neither is merged to `main`, which is why neither is
in this working tree:

- **#233** — `docs/repository-audit/REPOSITORY_AUDIT.md` and
  `reports/repository_audit/**` on `origin/orch/233`. Monday-relevant findings
  F3, F4d, F5 and F9 are incorporated in trace §0a.
- **#234** — `reports/editorial_wiring/ISSUE_234_EDITORIAL_WIRING_FORENSIC.md`
  on `origin/evidence/234-editorial-wiring`, together with the owner decisions
  recorded on it on 2026-09-15. Incorporated in trace §0b.
- **#244** — `ISSUE_244_MONDAY_SEMANTICS_INVENTORY.md`, same branch. An earlier
  Monday inventory; reconciled, and corrected in three places in trace §0c.
- **#237** — `docs/MONDAY_SELECTION_HEAD_OF_LINE.md` on `origin/orch/237`.
  Incorporated in trace §7.3; its three options remain untaken and become D8.

The remaining part of the gate is procedural: #233 merges, and its F5 artifact-
root fix lands before the tests in §11 can be written without writing run
residue into the tracked tree. That is [migration step 0](MONDAY_TARGET_ARCHITECTURE.md#10-migration-order).

## Scope

Monday only. Wednesday and Friday are paused: no file belonging to either is
changed or proposed for change, and the design is constrained so that Wednesday
can later be a second strategy document against the same engine rather than a
second engine.

## The finding in one paragraph

Monday's editorial strategy has three authorities that do not agree.
`editorial_roles[0]` in `business_strategy.json` holds the Monday role as JSON —
the interface the owner contract says must not be the human interface, and the
only one of the three that reaches the writing calls. Eleven Python modules hold
a second copy as prompt constants, closed vocabularies and numeric bounds, and
four more hold it as deterministic phrase bans and length gates — including
`pattern_extractor`'s hard assertion that an article's protagonist is always
`"owner"`, the hardest-coded product decision on the path and the one thing that
makes a second stream inexpressible in the shared engine. A third copy sits in
Markdown that reads as authoritative and that no code opens; six of the seven
declared `prompt_rule_references` name files the runtime never reads. Ten rules
are maintained in two or more places at once, six of them at different values. The proposal makes Markdown the only authority, reduces
`business_strategy.json` to generated machine data, and turns the eight
product-shaped stage modules into instances of five generic capabilities that
take their meaning as data.

## Owner decisions

Fifteen are listed in
[§12](MONDAY_TARGET_ARCHITECTURE.md#12-genuine-owner-decisions-still-required).
Three block the migration outright: **D1** (what replaces the superseded
eligibility contract), **D4** (which of the four or five written article arcs is
the arc) and **D8** (whether Monday's selection window advances at all). No
replacement editorial strategy was invented where owner-approved material was
insufficient — the gaps are surfaced as decisions instead.
