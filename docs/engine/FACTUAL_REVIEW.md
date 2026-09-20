# ENGINE — executing the plan: two reviewers and a mechanical gate

How a run *executes* the editorial plan it built (#269, under epic #264), and
what refuses an article that does not. Implementations:
`src/editorial/factual_review.py`, `src/editorial/machine_tells.py`, and the
lifecycle in `src/editorial/editorial_acceptance.py`. The plan itself is
[EDITORIAL_PLAN.md](EDITORIAL_PLAN.md); the documents it is built from are
[CLIENT_CONTRACTS.md](CLIENT_CONTRACTS.md).

## Why two reviewers

One reviewer was being asked two questions at once. "Is every sentence true to
the evidence behind it?" and "is this the article the client wanted?" have
different authorities — the first is universal and the Engine owns it, the
second is editorial and the client owns it — and asked together they trade
against each other. The trade always goes the same way: a well-executed
article with one invented figure reads better than a dull honest one, so the
invented figure survives as a sentence in the rationale.

So factual integrity is its own boundary, run first, against the run's own
`EditorialPlan` rather than against a rubric. What it finds is not an
annotation. A finding means the article is not accepted as it stands: it goes
to the reviser as a specific finding, and an article still carrying one after
its single controlled revision does not publish.

| Reviewer | Asks | Against | On a finding |
|---|---|---|---|
| Factual (`factual_review`) | is this true to the evidence? | the plan: claim, ceiling, evidence package, restrictions | rejects |
| Editorial (`editorial_acceptance`) | is this the article we wanted? | the client's rubric and lenses | ACCEPT / REVISE / REJECT |

## What the factual reviewer enforces

Each kind is a way a sentence can fail the evidence behind it, never an
editorial preference:

| Finding | Raised when |
|---|---|
| `unsupported_claim` | a factual claim or inference the evidence package does not support |
| `invented_causality` | a cause or consequence the evidence does not establish |
| `claim_strength_escalation` | the claim stated above `claim_strength_ceiling` — in scope, modality, direction or causality — on the contract's own ladder |
| `invented_entity` | an entity the evidence does not name, or a real one misidentified |
| `invented_attribution` | words, a finding or a position put in a source's mouth |
| `untraceable_number` | a figure the evidence package does not contain |
| `factual_restriction_breach` | a statement the plan's `factual_restrictions` forbid |
| `provenance_breach` | evidence used against what the run recorded about it |

It fails closed in both directions. A transport that fails, an answer that is
not readable as a verdict, or a finding of a kind the Engine does not carry
raises `FactualReviewError` and stops the run: an unreadable factual review is
not a clean one.

**Quantities: meaning and provenance, not string equality.** A faithful
rephrase is allowed; a new or strengthened quantity is not (owner decision,
#269 review). String comparison can answer neither question, so the boundary
is hybrid. Deterministic code extracts the quantities and clears what it can
*prove* equivalent — `1,200,000` and `1.2 million` are one value, `28%` and
`28 percent` are one value, a numbered list marker and an identifier like
`R-114` are not quantities at all. Whatever it cannot vouch for goes to the
semantic reviewer as `figures_to_verify`: a question, never a verdict, and the
request says so in as many words. A quantity the evidence does not support, or
one carrying a changed meaning, fails there — on a reading rather than a
token. Nothing hard-rejects on spelling, and `figures_to_verify` is recorded
with the review so a later reader can see what was asked.

The check is article-wide and client-neutral by design: the Engine does not
know which paragraph a client calls its Consequence, and a rule that held only
there would be a rule about someone's section names.

## What the editorial reviewer may not do

Execution is judged; a template is not. `EXECUTION_REVIEW_SCOPE` is Engine
text delivered in the reviewer's own request, so it holds for every client
rubric rather than being restated in each. The reviewer may never pass or fail
an article on:

- the order its paragraphs or sections appear in;
- which of the client's optional elements it happens to contain;
- which shape it chose where the client's own rules offer several.

The Engine names no client's elements here (#268): which of them are optional
is stated by that client's own lenses, which travel in the same request. If a
repeated shape can be reconstructed from the output, that is a possible
template defect to report as one — never evidence that the article is correct.

**What the reviewer receives.** The same authoritative `EditorialPlan` the
article was written under, as `plan.as_review_text()`, plus
`active_client_obligations` — every lens routed to writing, with the condition
that activated a conditional one. Without them a lens can govern the writing
while the reviewer judging that writing has never heard of it (#269 review).
`PLAN_REVIEW_SCOPE` travels beside it: the plan is there to judge execution
against, not to check off, and an element the client's own text leaves to the
article is not a defect when the article does without it.

## The mechanical gate

Separate from anybody's taste: `config/machine_tells/shared.yaml` is a
versioned Engine document. It is deliberately short, and the test each entry
has to pass is not "does this look AI-ish to us" but "would we impose this on
a client whose house style we have never seen" (#269 review). What survives
that test is machine-authorship boilerplate no house publishes — which gates —
and a few constructions strongly associated with generated text that a human
may still legitimately write, which only warn. Lede moves are matched in the
opening paragraph only, and a repeated pattern carries a `max_occurrences` so
"repeated" means repeated. Changing what it matches means bumping its
`version` in a reviewed commit, and its identity is recorded in every factual
review.

House taste is not here. Transitions like `moreover,`, rhetorical-question
openings, triads and em-dash asides are ordinary human writing that one client
may not want, so they live in that client's own list — a normal construction
must not become a universal publication blocker. An entry the Engine list
already carries is not repeated client-side.

A client extends it with its own `lists/*.md` documents. A client entry says
"this client never publishes these words" — an explicit prohibition rather
than an evidence-tiered heuristic — so a client entry gates.

**Tiers are not flattened.** Every shared entry declares the evidence tier
behind it, and the tier decides what a match does:

| Tier | Outcome | Effect |
|---|---|---|
| `hard_evidence` | `gate` | blocks; goes to the reviser as a finding |
| `directional` | `warning` | recorded, never blocks |
| `observed_practice` | `suggestion` | recorded, never blocks |
| `owner_judgement` | `owner_review` | recorded for the owner to decide |

Turning a rule we merely suspect into a rule that stops a run is the failure
this ordering prevents; so is the opposite, quietly downgrading a proven tell
to advice.

## The reviser

The reviser receives the same authority the writer had: the run's editorial
role, the configured voice, every client lens routed to `revision` (standing
ones and the conditional ones this run activated), the authoritative plan
including both sides of the evidence package — and the specific findings to
resolve, each quoting the words at fault. Revision stays surgical: it changes
what the findings implicate and leaves the rest, unless a client rule in the
request explicitly requires the article to be written again.

## What a run records

`editorial_acceptance.json` carries both verdicts — `factual_review` and
`final_factual_review` beside the editorial reviews — including every
mechanical finding in its own tier. `accepted_composition.json` carries the
plan and contract lineage the accepted article was executed under: the stream,
lens and list digests, which lenses were active at which stage and what
activated them, the claim-strength ceiling, and what the run decided that the
contract left open. Without it, "this article was accepted" says nothing about
which version of the editorial policy accepted it.

`tests/test_269_plan_execution.py` proves the chain the way #267's tests do:
canary strings in a fixture client's contract, the real production entrypoint,
and assertions on the exact messages the composer, both reviewers and the
reviser receive — each with the mutation twin that removing the wiring removes
every canary.
