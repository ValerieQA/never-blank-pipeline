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
  audience.md    the Audience Profile, exactly one
  editorial/reference/library.md   the Reference Library index, 0 or 1
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

A stream that declares no `## Plan` and has no conditional lens builds no plan
and runs exactly as before; a conditional lens alone is enough to build one.
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

A condition is decided on the run's research evidence, so a conditional lens
may route only to the stages that run after research: `writing` and
`revision`. One routed to `selection` is refused when the contract loads — the
candidate is chosen before any research exists, so nothing could activate it.
Make it a standing lens to apply it at selection. A condition is decided once
per run and that one decision serves every stage its lenses name.

## Shared list

A list of strings the client's output may not contain — machine tells, banned
phrases, whatever the client puts in it. Front matter, all required, no
duplicate keys: `list_id`, `version`, `applies_to` (stream ids). Body: a `#`
title for people if wanted, then one bullet per entry, no repeats. Shared
because one list applies to as many streams as it names. The Engine matches
case- and whitespace-insensitively and reports which list an entry came from;
what belongs in the list is client policy.

## Audience Profile

Who the client writes for. Implementation: `src/strategy/audience_profile.py`;
it is configuration like everything else here, produced by no stage and changed
by no run. Front matter, both required, nothing else accepted: `profile_id`,
`version`. Body: a `#` title and notes for people if wanted, then one
`## Attributes` table — `Attribute | Value | Why`.

What the profile may say is not the client's to widen.
`knowledge/vocab/audience_attributes.md` declares the attributes a condition may
read and the closed set of values each one takes; the profile states **every**
declared attribute, each with a value from that attribute's own set, and may
state nothing else. A missing attribute, a value outside the set, an attribute
the vocabulary does not declare, or a value with an empty `Why` stops the run.

It reaches exactly two stages, S-04 and S-08 — Step 1 §295 admits the Audience
Profile to the interpretation boundary and admits no other client context with
it, so the client's positions, its lenses and its portfolio have no attribute to
arrive under. What those two stages get is what `audience <attribute> is
<value>` conditions are evaluated against (Step 4 §4).

## Reference Library

The examples S-11 attaches to an approved plan. Implementation:
`src/strategy/reference_library.py`; configuration like everything else here.
The index is `editorial/reference/library.md`, beside the documents it points
at. Front matter, both required, nothing else accepted: `library_id`, `version`.
Body: a `#` title and notes for people if wanted, then one `## Items` table —
`Item ID | Destination | Format | Take | Do not copy | Source`.

One row is one item: the ID an exemplar names, the destination and format it is
an example **for**, what a Writer may carry across, what belongs to that
document alone, and the file in the same directory it is from. `Take` without
`Do not copy` is refused — an example handed over without the second note is a
template.

**Item IDs are `REF-` and three digits, and they are permanent.** They spell out
nothing about the item, so nothing forces them to change: an item re-pointed at
another destination, re-worded or moved in the table keeps its name, adding an
item renumbers none of the others, and an exemplar an earlier run recorded still
names the same item. Two rows claiming one ID stops the run, as does an ID in
any other shape, a destination or format the Engine does not have, or a `Source`
that is not a file of the reference directory.

**It is the one input that may be missing.** A client with no index runs
without exemplars, and S-11 records the absence per destination
(`reference_library_unavailable`, a `DEGRADE`). An index that *is* there and
does not load stops the run like every other document below — a library read as
empty would strip the exemplars out of every plan of every run and say nothing
about why.

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
