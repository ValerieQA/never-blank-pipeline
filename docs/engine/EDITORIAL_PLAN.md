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
| `claim_strength_ceiling` | the contract, chosen from its ladder |
| `evidence_package` | the run's research, including what it may **not** use |
| `factual_restrictions` | the contract, plus what the run adds |
| `active_lenses` | routing: standing obligations + what this run activated |
| `reader_verifiable_artifact` | the contract |
| `ending_mode` | the contract |
| `audience_currency` | the contract |
| `acknowledged_limits` | the contract, plus what the run adds |
| `portable_noun` | the run: the noun, the decision, the reason |
| `lineage` | the snapshot: identity, path and digest of every document |

It is **not** a paragraph outline. The Engine does not know that paragraph 1 is
a Hook, and must not: the article's shape is the client's, written in a lens.

## Fails closed

The run stops, rather than carrying a plan that is quietly less than the
contract, on any of:

- a value the contract does not permit for a slot;
- a slot the contract requires a choice for and the run did not make;
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
