# ENGINE — the editorial plan

How a run executes a client's human-readable editorial contract (#267, under
epic #264). Implementation: `src/editorial/editorial_plan.py`. The contracts it
is built from are loaded by `src/strategy/client_contracts.py`, documented in
[CLIENT_CONTRACTS.md](CLIENT_CONTRACTS.md).

## What it is for

The disease this fixes is documents that exist and are never read: an editorial
policy written by people, approved, versioned — and absent from every message a
model receives. An `EditorialPlan` is the object between the two. It is built
from a loaded contract snapshot plus what the run found, validated before
anything is written, rendered into the composition messages, and persisted next
to the exact contract and lens digests behind it.

`tests/test_editorial_plan.py` proves the chain rather than describing it:
canary strings in a fixture client's contract, the real production prompt path,
and an assertion on the exact messages the composer hands to the model — with
the mutation twin that removing the wiring removes every canary.

## Engine slots, client values

The Engine carries the slots. Every value is the client's, declared under
`## Plan` in the stream contract. There is deliberately no Python enum of
editorial choices: an editorial rotation is a document edit.

| The plan carries | Where it comes from |
|---|---|
| `central_claim` | the run: the claim it is built on, with what supports it |
| `claim_strength_ceiling` | the contract; a run decision where its ladder has several values |
| `evidence_package` | the run's research, including what it may **not** use |
| `factual_restrictions` | the contract, plus what the run adds |
| `active_lenses` | routing: standing obligations + what this run's evidence activated |
| `reader_verifiable_artifact` | the contract; a run decision where it permits several |
| `ending_mode` | the contract; a run decision where it permits several |
| `audience_currency` | the contract; a run decision where it permits several |
| `acknowledged_limits` | the contract, plus what the run adds |
| `portable_noun` | the run: the noun, the decision, the reason |
| `lineage` | the snapshot: identity, path and digest of every document |
| `run_decisions` | what the run decided that the contract left open, and on what |

It is **not** a paragraph outline. The Engine does not know that paragraph 1 is
a Hook, and must not: the article's shape is the client's, written in a lens.

## Run decisions

A contract can leave two things open: whether a conditional lens applies
(`activates_on`), and which value a multi-value scalar slot takes. Both are
decided per run, from the run's own evidence, before anything is written
(`src/editorial/plan_decisions.py`):

    research artifact → evidence package → plan decider → PlanDecisions
                     → build_editorial_plan(decisions=…) → active_lenses / slot values
                     → generation, derivation and the composer's messages

The decider is asked only what the contract left open — each condition with the
text of every lens that names it, verbatim; each open slot with its permitted
values, verbatim — plus the central claim and the evidence package. It never
sees an article. In production it is one budget-charged model call
(`ModelPlanDecider`, `NB_ENRICH_MODEL`); the canonical entrypoint takes any
other decider as `main(plan_decider=…)`. A contract that leaves nothing open —
Never Blank's today — makes no call.

The Engine holds the answer to the contract:

- every open condition and slot is answered exactly once, and nothing else is;
- a condition is met only with a finding and the ids of evidence items this run
  holds and may use — activation evidence cannot be invented;
- a chosen value is one the contract permits (whitespace aside), verbatim;
- no answer, an unreadable answer, an empty or hedged choice stops the run —
  the first value is never a default and an unanswered condition is never
  "inactive".

`editorial_plan.json` records all of it under `run_decisions`: who decided, the
contract identity and digest the options came from, every condition (met or
not) with its finding, evidence ids, reason and declaring lenses, and every
selection with its value, its position among the permitted values, the
evidence ids and the reason. An activated lens also carries its finding into
the writer's message.

**One plan, every consumer (#269).** The run builds exactly one
`EditorialPlan`, and every downstream stage executes or judges against that
same object: the composer and the argument-building stages through
`as_prompt_text()`, the editorial reviewer through `as_review_text()` plus the
obligations active for the run, the factual boundary through `FactualGate`,
and the reviser through `RevisionContext`. No stage builds a second plan, and
no stage decides authority of its own — build once, execute everywhere,
review against the same authority, revise against the same authority.

**Which consumers see a stage's obligations (#279).** A client document
declares contract stages (`selection`/`writing`/`revision`); the Engine decides
which of its own stages consume each. For `writing` that is the stages which
*build* the argument — narrative spine, hook engine, Never Blank voice — and
then the composer. They read `lens_text_for(stage)` through the enriched
signal; the composer keeps receiving standing obligations with the role's
rendered rules, and the reviser keeps its revision route. One projection, no
second authority.

Forensic #278 is why this exists: standing obligations reached the composer
alone, so the stage that wrote the opening had never been given the client's
rule about openings. The article obeyed the ending (a plan slot, which did
reach those stages) and ignored the opening (lens text, which did not).

**Proving it afterwards.** Each run writes `stage_routing.json`
(`src/run/stage_routing.py`): per stage, the lens identities and digests it was
routed, a SHA-256 per outgoing request, and `contained` — computed from the
request itself rather than from the intention to send it. No prompt, credential
or article text is stored. A stage that was routed an obligation and issued a
request without it is recorded as `missing`, which is the fact #278 had to read
source code to establish.

**Stages.** A plan routes lenses to every stage that runs after research —
`writing` and `revision` (`PLAN_STAGES`). Each condition is decided once, and
the decision records every stage its lenses route to (`stages`);
`active_by_stage` in `editorial_plan.json` lists what reached each stage.
`as_prompt_text()` is the writing stage's input and carries the conditional
lenses routed to writing. It reaches the stages that BUILD the argument, not
only the composer that dresses it: the pipeline puts it in the enriched signal
under `PLAN_SIGNAL_KEY` and the narrative spine, hook engine and Never Blank
voice read it through `plan_block` (#263 — an obligation applied after the
article is shaped is applied cosmetically). The same route serves any client
lens declaratively; the Engine adds nothing of its own to it. `activated_lens_texts("revision")` is what the
reviser receives beside the standing revision lenses. A conditional lens
cannot route to `selection` — see [CLIENT_CONTRACTS.md](CLIENT_CONTRACTS.md#lens).

A run builds a plan whenever its contract needs one (`requires_plan`): a
`## Plan`, or any conditional lens — a conditional lens applies only through a
plan, so it needs none of the plan slots to be executable.

The canonical Editorial v2 path receives the plan as `editorial_plan=` — the
generation, derivation and composition stages in `src/editorial/`. The restored
July Wednesday pipeline (`src/never_blank/wednesday_july`) is **not** a plan
execution path: it is reference material pinned verbatim to July (#207), kept
until its editorial semantics are extracted into client documents, bound to
this architecture and proven, and the legacy implementation retired. Nothing
here adapts it, and a client contract is not executable through it.

Nothing here knows a weekday. A new stream — a different day, a different
ending, a different lens — is a stream contract bound to a role the business
configuration declares, plus whatever lenses it needs; no Engine Python changes
(`tests/test_plan_decisions.py::test_a_new_stream_day_policy_is_documents_only_and_reaches_the_composer`).

## Fails closed

The run stops, rather than carrying a plan that is quietly less than the
contract, on any of:

- a value the contract does not permit for a slot;
- a slot the contract requires a choice for and the run did not make, or a
  run decision that is missing, unreadable, ambiguous or not held to the
  evidence (see Run decisions);
- a `### slot` name the Engine does not carry, or a contract stating a value
  only the run can find;
- activation evidence for a condition no lens declares, or a lens activated
  with no evidence;
- a central claim citing evidence the package does not contain, or evidence the
  run marked do-not-use.

A central claim that cites nothing is recorded as unsupported and carried into
the writing stage as such; it is a premise, not a breach.

## Evidence integrity

Universal, never editorial — what it means for a sentence to be supported by
the evidence behind it. `check_claims` reports, and the caller decides what is
fatal:

| Finding | Raised when |
|---|---|
| `unsupported_inference` | the claim cites nothing, or cites an item the package does not contain |
| `do_not_use_evidence` | the claim rests on an item this run may not use |
| `claim_strength_escalation` | the claim is stated above the ceiling, on the contract's own ladder |
| `invented_entity_attribution` | the claim names an entity its cited evidence does not |
| `untraceable_number` | the claim states a figure its cited evidence does not |

A claim strength that is not on the contract's ladder cannot be compared with
anything: that raises rather than reporting.

## Portfolio regularity

`portfolio_regularity(records, slot)` counts how often each value of a slot
occurs across persisted plan records. Counting is all it does: no threshold and
no verdict. What a repetition means — a signature worth keeping, a rut worth
breaking — is the client's to decide in its own documents.

## What a run writes

`editorial_plan.json` in the run directory: the plan, every evidence item
including the withdrawn ones and why, which lenses were active and what
activated them, and the lineage — the same digests `client_contracts.json`
carries, from the same snapshot.

## How the plan is executed

Building the plan is half of it; the other half is what refuses an article
that is not true to it. Factual integrity is reviewed separately from
editorial execution, against this plan rather than against a rubric, and it
rejects rather than annotates; a shared versioned machine-tell scan runs
beside it, in evidence tiers that are never flattened into one hard rule; and
the accepted article records the plan and contract lineage it ran under.
See [FACTUAL_REVIEW.md](FACTUAL_REVIEW.md) (#269).
