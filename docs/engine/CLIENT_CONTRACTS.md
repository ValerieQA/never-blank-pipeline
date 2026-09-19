# ENGINE — client contracts

How the Engine reads a client's human-readable contracts and routes them to
stages. Owner decision D12 (#240): the Engine is content-domain agnostic; a
client's topic, audience, tone, sourcing policy and editorial method arrive as
documents the client owns. Implementation: `src/strategy/client_contracts.py`.

## The active client

`NB_CLIENT_DIR` names the client's directory (default: this repository's own
client, `clients/never_blank`). Replacing the client means pointing this at
another directory — no Engine code changes. That is the Replace-the-client test
(#240 D12 addendum), and `tests/test_client_contracts.py` runs it as code.

```
<client>/
  streams/*.md   one stream contract per stream
  lenses/*.md    0..N lenses
  lists/*.md     0..N shared lists
```

## Stream contract

Parsed, so its shape is a contract.

- **Front matter**, all required, nothing else accepted, no duplicate keys:
  `stream_id`, `version`, `role_id` (the editorial role it governs), `selection`.
- **Headings**: exactly `## Purpose`, then `## Selection`, optionally followed
  by `## Plan`. One `#` title may precede them. Under `## Selection` the client
  may group rules under `###` headings of any name; nothing deeper, and no `###`
  outside those two sections.
- `## Purpose` becomes the role's intent and reaches the writing stage.
- Every bullet (`- `, continuation lines indented) under `## Selection` is one
  rule a candidate signal is judged against.
- `selection: first_valid`: candidates are read in queue order; the first that
  satisfies every rule — the stream's and every lens routed to selection — is
  used, and no later candidate is judged.

A missing, extra, misplaced or misspelt heading fails the run instead of
silently dropping a rule (#233 F-03).

## Plan (optional)

What an article for this stream must be true to. Each `###` heading names one
**plan slot** the Engine carries; its bullets are that slot's values, in the
client's own words and order. A `###` heading the Engine does not carry stops
the run — a misspelt slot would otherwise be policy nobody reads.

| Slot | The bullets are | |
|---|---|---|
| `claim_strength_ceiling` | the strength ladder, **weakest first** | choose one |
| `ending_mode` | the permitted endings | choose one |
| `audience_currency` | the permitted currencies | choose one |
| `reader_verifiable_artifact` | the permitted artifacts | choose one |
| `factual_restrictions` | restrictions that stand for every run | all apply |
| `acknowledged_limits` | limits that stand for every run | all apply |

"Choose one" is the run's choice, refused unless the contract permits it. Where
a slot permits exactly one value, the contract has already chosen and the run
need not; where it permits several, the run's plan decider chooses one from
this run's evidence (see [EDITORIAL_PLAN.md](EDITORIAL_PLAN.md#run-decisions))
and the run stops if it chooses none, chooses two, or chooses a value the
contract does not permit — it never falls back to the first value. `central_claim`, `evidence_package`,
`active_lenses`, `portable_noun` and `lineage` are slots a run derives from its
own evidence: a contract may not state their values.

A stream that declares no `## Plan` builds no plan and runs exactly as before.
See [EDITORIAL_PLAN.md](EDITORIAL_PLAN.md).

## Lens

Not parsed: the body is delivered verbatim to every stage its front matter
names. Front matter, all required, no duplicate keys: `lens_id`, `version`,
`applies_to` (stream ids), `stages` (any of `selection`, `writing`,
`revision`). Zero lenses is valid.

| Stage | Where the text arrives |
|---|---|
| `selection` | after the stream's own rules, in the candidate judgment's criteria |
| `writing` | in the editorial role rules, for both published surfaces |
| `revision` | in the reviser's request, beside role and voice |

Optional front matter `activates_on` (a list of conditions) makes a lens
**conditional**: it reaches its stages only on the runs whose research evidence
meets one of those conditions — decided per run by the plan decider, which is
handed the condition name and this lens's text verbatim — through an `EditorialPlan` that records
which condition fired and on what evidence. Without `activates_on` a lens is a
**standing obligation** and applies to every run. The routing above is standing
obligations only: a conditional lens has no path to a stage that does not go
through a plan.

## Shared list

A list of strings the client's output may not contain — machine tells, banned
phrases, whatever the client puts in it. Front matter, all required, no
duplicate keys: `list_id`, `version`, `applies_to` (stream ids). Body: a `#`
title for people if wanted, then one bullet per entry, no repeats. Shared
because one list applies to as many streams as it names. The Engine matches
case- and whitespace-insensitively and reports which list an entry came from;
what belongs in the list is client policy.

## Notes for people

An HTML comment (`<!-- ... -->`) in either kind of document is for people and
never reaches a model. An unclosed comment fails the run.

## Refused, never guessed

Two stream contracts for one role, one `stream_id` in two contracts, a lens or
list id declared twice, or any unreadable document anywhere in the client stops
the run.

## Evidence

Every run writes `client_contracts.json` — identity, path and SHA-256 digest of
the stream contract, each routed lens (with the conditions it activates on) and
each shared list — from the same snapshot the run executed. The selection audit
carries the same record, and so does `editorial_plan.json` where a plan was
built.
