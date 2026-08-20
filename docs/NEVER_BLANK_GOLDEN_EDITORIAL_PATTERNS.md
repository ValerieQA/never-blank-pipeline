# Never Blank Wednesday Golden Editorial Pattern

Status: Release 1 product configuration for Issue #143. This is a Never Blank
editorial asset, not a universal Engine rule.

## Product invariant

Wednesday demonstrates how Never Blank thinks. It moves through one discovery:

> documented event or fact → obvious reading X → turn → overlooked Y → one
> primary mechanism → evidence supporting Y → bounded business question →
> Never Blank insight → contextual close and configured website invitation

The movement matters; literal headings and stock transition wording do not.
The intended reader experience is: everyone was looking at X, but the more
interesting business question is Y; here is why, here is what the evidence
supports, and here is the bounded question another business can examine.

The machine-readable product profile is
`config/never_blank/wednesday_golden.yaml`. The profile's existing strict
acceptance artifact is
`config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml`.

## Evidence boundary

X and Y perform different editorial functions. X names the recognizable
surface reading. Y is one overlooked observation. Y must be supported by the
accepted evidence; being surprising, plausible, or contrarian is not support.

The mechanism explains Y. Wednesday uses exactly one primary mechanism. The
article then returns to the evidence and states what the case does and does not
establish.

A large-company case is valid source material when the documented event has
enough factual substance for X, Y, and one mechanism. The source company's
outcome must not be silently universalized. Transfer to the configured audience
is a bounded question: what should the reader examine, not what result they
will obtain.

Wednesday is not restricted to same-day news. Current events, decisions,
acquisitions, strategic shifts, historical cases, product/market behaviour,
and other documented cases may qualify. A merely interesting event does not
qualify when its connection to Compound Presence is only an invented analogy.

Issue #141 remains open. This profile neither weakens editorial acceptance nor
licenses Never Blank pattern claims unsupported by the current run's evidence.

## Golden reasoning references

References below are annotations of the reasoning operation. They are not
templates and their wording must not be copied.

### Primary — Versant / Full Swing

Repository signal: `37a503640b83be6c`.

| Function | Reference annotation |
|---|---|
| X | A $530 million acquisition diversifies Versant's media assets. |
| Turn | The useful question is not only what asset was bought, but which legacy dependency the transaction reduces. |
| Y | The move can be read as reducing exposure to revenue tied to declining cable distribution. |
| Mechanism | Capital moves toward an experiential revenue stream whose demand is not structurally tied to the legacy channel. |
| Evidence | The recorded transaction, price, nontraditional-media expansion, and diversification beyond cable support the reading; integration and long-term outcome remain unknown. |
| Bounded question | Which revenue line still depends on an operating assumption customers are leaving behind? |

### Secondary — GM / V8

Repository signal: `73035a9f1e61abd0`.

| Function | Reference annotation |
|---|---|
| X | GM introduced a redesigned Sierra with new V-8 engines while the industry discusses electrification. |
| Turn | The more useful business question concerns what a company does with its profitable present while the future transition is unsettled. |
| Y | The product decision also defends and improves a current high-margin category. |
| Mechanism | Incremental investment in a profitable core can preserve earnings capacity alongside longer-horizon bets. |
| Evidence | The documented product changes and the recorded importance of Sierra's premium trims support the reading; post-launch outcomes remain unknown. |
| Bounded question | Which profitable current offer deserves investment while a future shift becomes economically real? |

The structured fixture annotations live under
`tests/fixtures/golden_wednesday/` and explicitly say
`reasoning_reference_only_do_not_imitate_wording`.

## Negative reference — TikTok / Invisalign

Run `e9e966f2-8d91-40ab-b059-c997f104dde1`, signal
`80725c18fd4ed61c`, is a counterexample for editorial movement. It was
technically disciplined and evidence-bounded, but phrase-driven and flat. A
generic lesson about campaign structure does not create the X → turn → Y →
mechanism discovery. Its prose is not a Wednesday template.

Issue #141 records the separate conflict exposed by that run: some Never Blank
editorial pattern claims are not supported by one external case. Wednesday
does not solve or bypass that conflict.

## Anti-flattening

The profile explicitly rejects news recap, source-summary prose, “5 lessons
from X”, “3 takeaways”, generic SMB advice, multiple mechanisms, manufactured
contrarianism, unsupported Y, silent corporate-outcome transfer, generic
AI/business-blog language, long background, and titles that copy the source or
give away the entire reframe.

The title creates honest curiosity around the discrepancy. It should make the
reader wonder what everyone missed without clickbait or invented contradiction.

Wix is concise and LinkedIn is native/compressed. Both carry the same central
discovery and mechanism. Both earn a contextual Never Blank close and use the
configured `reflection` CTA with `https://www.inneros.online`.

## Visual inheritance

No Golden-specific visual style is authorized or needed for this phase. The
Wednesday run is expected to inherit the canonical Never Blank path:

1. accepted signal and research context;
2. `prepare_content_packages`;
3. the current Never Blank visual prompt/profile and `choose_visual_family`;
4. image generation or approved deterministic fallback;
5. deterministic Never Blank text/logo composition;
6. platform derivatives (Wix/blog and LinkedIn dimensions);
7. Cloudinary upload and recorded URLs;
8. existing Wix and LinkedIn publishers consume the validated derivatives.

Editorial role selection does not participate in that visual call chain.
Therefore no additional Wednesday visual wiring is necessary.
A future Golden-specific visual treatment would be a separate product decision;
it must not be invented under #143, and #136 remains out of scope.

## Canonical integration

`never-blank-wednesday-golden` is declared in the strict business strategy
configuration and selected explicitly by the Wednesday workflow through
`scripts/generate_and_publish.py --editorial-role`. The generic resolver fails
closed on unknown roles. The selected `EditorialRoleIdentity` is stored in the
immutable run-scoped `assignment.json`; a weekday is never used as evidence.

The generic renderer carries the configured structure and prohibitions into
the real Wix and LinkedIn composition prompts. Surface-specific rules reach
only their own surface. The role also selects
`never-blank-golden-wednesday-acceptance/1.0`; the entrypoint verifies that the
loaded rubric identity matches configuration before review. Roles without a
configured rubric retain the accepted default acceptance behavior.

The dedicated workflow owns Wednesday at 06:00 America/New_York through the
repository's two-UTC-cron DST convention and generic due check. Wednesday was
removed, and only Wednesday was removed, from both previous shared scheduled
publishers and from the legacy schedule configuration. Daily discovery remains
active, but its optional non-canonical publishing stage is disabled on
Wednesday. Tue/Thu, Monday, Friday, and Sunday schedules retain their prior
days.

Input remains `data/research/signals_active.jsonl`. Automatic selection chooses
the next unused item that already carries the canonical `ARTICLE_READY=true`
signal. It does not pretend to infer editorial quality from keywords. The
canonical research, Decision Lens, and Golden acceptance gates must still
authorize the run. Wednesday uses its own post-success consumption record;
Monday success, failure, no-signal result, or marker cannot suppress Wednesday.
The marker is bookkeeping after successful publication, never a race lock.

Deterministic tests prove that the configured movement, prohibitions, title
rules, source policy, and acceptance criteria reach the canonical prompt/review
boundaries. They do not claim to judge arbitrary prose by string counting; the
configured editorial acceptance decision remains responsible for the Golden
turn against the current run's evidence.
