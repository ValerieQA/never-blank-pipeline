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

## Client Contract

What the client switched on, and where its voice and its forbidden wording live.
Implementation: `src/strategy/client_contract.py`. The file is `contract.md` in
the client directory. Front matter, all four required and nothing else accepted:
`contract_id`, `version`, `voice_ref`, `forbidden_ref`. Body: a `#` title, notes
for people if wanted, then one `## Enabled destinations` section listing one
destination per bullet.

**Three things that are not each other** (AD-02 §3), and the contract supplies
only the first:

* **Enabled** — this list. The destinations the client wants published to.
* **Capable** — whether the Engine has a publisher, package and preflight for a
  destination. Declared in code, never here.
* **Rollout scope** — which capable destinations today's deployment publishes to
  (`src/publishing/release_scope.py`). A deployment setting, temporary by
  contract, and not a client decision.

A destination enabled here and outside the rollout scope is **not** an error: it
is generated and not published (`generate_only`). The loader reads no rollout
scope and decides no mode; S-07 resolves the three in order.

A destination the Engine does not have stops the run, as does a contract that
enables nothing, a front-matter field the contract does not declare, or a
`forbidden_ref` no list in `lists/` declares. **A client with no `contract.md`
raises rather than degrading** — unlike the Reference Library, there is no honest
default for which destinations a run writes for.

### How the enabled list becomes S-07's input

`contract_destinations()` turns the loaded contract into the
`ContractDestinations` S-07 requires. **The contract is authoritative over the six
canonical destinations**, so it produces a row for every one of them and never
leaves one out. S-07 keeps three states apart, and two of them are easy to
confuse:

| State | Row | S-07's answer |
|---|---|---|
| declared and **enabled** — listed | `enabled=True` | decided, eligible unless another rule excludes it |
| declared and **disabled** — not listed | `enabled=False` | excluded as `CONTRACT_DISABLED`, citing the contract's rule |
| **undeclared** | no row | recorded in `DestinationDecisionSet.undeclared` |

A destination missing from the enabled list is the **second** row, not the third.
`ContractDestinations` says why the difference matters: the destinations it does
not declare "are not excluded: they are unknown to the contract … so a reader can
tell a destination the client turned off from one it never mentioned". The client
wrote a contract covering its surfaces and said no to that one, so dropping the
row would report a deliberate choice as an oversight. This producer therefore
never yields `undeclared`.

`rule_id` names the contract's row **for that destination**
(`<contract_id>-destination-<destination> v<version>`), not the contract as a
whole: §1 Post asks for one decision with one rule, and `ContractDestinations`
refuses two rows sharing an ID because "a name two rows answer to names neither".

The producer reads **no** capability and **no** rollout scope. Whether an enabled
destination publishes or only generates is S-07's own resolution from its other
inputs — which is why today's Wix + LinkedIn split survives a contract that
enables all six.

### Forbidden wording

`forbidden_ref` names a shared list in `lists/` by its `list_id`; the entries
live there, so phrases are added to the list rather than to the contract. Each
entry becomes one `E-14` `forbidden` item at **tier 2** — Step 1 §4's "resolved
from the contract (tier 2) and hard policy (tier 1)", which the register names
`APPROVED_CLIENT_RULE`. `rule_ref` is the list and its version, not the entry:
the entry is what was broken, the list is what forbade it, and V-P04's route is
decided by the tier of the rule broken.

Every entry of a shared list is a **phrase**, matched by code, case- and
whitespace-insensitively. A **construction type** is not a string — V-T06 sends
those to the model, "however it is worded" — so nothing is inferred as one.

Tier 1 is hard *platform* policy from the register (a `K-DST-*` record at tier 1).
No record forbids wording today, so the tier-1 contribution is empty, which is an
honest state rather than a gap. `config/machine_tells/shared.yaml` is **not** a
source: every entry there is `tier: directional` — advisory, in the legacy
machine-tells vocabulary — and it also holds regex patterns and lede moves, which
are not phrases. It stays where it is, read by `src/editorial/machine_tells.py`
for the pre-canonical path.

### Voice brief

`voice_ref` is a **reference**, relative to the repository root. The voice
document stays human-editable prose where it is and is never copied into the
contract. It declares its own `voice_id` and `version` in front matter, and
`E-14.voice_brief_ref` is `<voice_id> v<version>` — a reference to a *version*,
which is why an unversioned document cannot be referenced at all. S-12 compares
the brief it is handed against the plan's reference and refuses a voice the plan
was not approved against.

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

**A client may have no library, and that is a state rather than a fault.** With
no `library.md` the loader reports the library absent with its reason, S-11
attaches no exemplar and the destination degrades; the run records it. *Absent*
and *empty* are kept apart: an index holding no rows is refused loudly, so a
half-written library can never pass as an unwritten one. Never Blank is in the
absent state today — `editorial/reference/` holds research material about
readability rather than exemplar texts, and authoring a corpus is editorial
content work, not part of this loader.

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
