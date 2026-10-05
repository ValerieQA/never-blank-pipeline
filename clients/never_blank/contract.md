---
contract_id: never-blank
version: 1
voice_ref: config/brand_voice.md
forbidden_ref: never-blank-machine-tells
---

# Client Contract — CLIENT: NEVER_BLANK

<!--
CLIENT: NEVER_BLANK (#337). What this client has switched on, and where its
voice and its forbidden wording live. Three things that are often confused and
are kept apart here on purpose (AD-02 §3):

  * **Enabled** is this list: the destinations the client wants published to.
  * **Capable** is whether the Engine has a publisher, package and preflight
    for a destination. Declared in code, not here.
  * **Rollout scope** is which capable destinations today's deployment actually
    publishes to (`src/publishing/release_scope.py`). A deployment setting, not
    a client decision, and temporary by contract.

A destination enabled here that is outside the rollout scope is not an error: it
is generated and not published (`generate_only`), which is what the migration
map means by "until then the remaining destinations are generate_only".

`voice_ref` is a **reference**. The voice document stays human-editable where it
is and is never copied in here.

`forbidden_ref` names the shared list that holds the phrasing this client does
not publish — `lists/machine_tells.md`, by its `list_id`. Add phrases there
rather than here.

Format: docs/engine/CLIENT_CONTRACTS.md. Loader: src/strategy/client_contract.py.

Three sections below `## Enabled destinations` are #363's: the configuration
S-00's `ContractFitRules` and S-10/S-11's `DestinationRules` are built from.
Loaders: src/strategy/contract_fit.py and src/knowledge/destination_rules.py.

Four more are #368's: the three declarations S-08's `StrategyContract` is built
from, and the static hashtag vocabulary S-10's `AdaptationContract` carries.
Loaders: src/strategy/strategy_contract.py and src/strategy/adaptation_contract.py.
-->

## Enabled destinations

- wix
- linkedin
- facebook
- instagram
- threads
- telegram

## Evidence policy

<!--
Never Blank's evidence requirement, as the part of its policy that code acts on
(owner decision 2026-10-05, #286 PRIMARY-AUTHORITY-DESIGN-V1). The requirement
itself is written for people in `lenses/evidence.md`: where a claim's core fact
has a responsible primary authority, that authority is the factual anchor, and
secondary reporting may serve discovery and context but does not replace it.

This section declares that Never Blank wants the engine to enforce it. The
engine matches these lines against the requirements it can execute and never
interprets them; which claims owe an authority is decided per claim from who
could confirm it, not from a list of topics kept here.
-->

- primary authority when identifiable

## Editorial domain

<!--
What Never Blank takes as an editorial topic (owner, 2026-09-28). This is the
whole of the S-00 topic rule: `FitRule` has no deny construct, so what is out
of domain is out by **absence** from this list and never by being listed.

Out of domain, and deliberately unlisted rather than written as a denial:
material with no meaningful business or entrepreneur relevance; personalised
medical, legal or financial advice; political or electoral advocacy; explicit
sexual content; instructions that are illegal or materially harmful.

`adjacent_business` is load-bearing and is not a spare value. The owner's
decision says the domain is "explicitly not to be read as a narrow allow-list
that rejects legitimate adjacent SMB material merely because its exact noun is
absent", and `FitRule.check` is a strict allow-list over every stated value.
Removing this line turns the owner's decision into the thing the owner forbade.
-->

- entrepreneurship_operations
- marketing_sales_cx
- ai_technology_automation
- productivity_process
- adjacent_business

## Risk level

<!--
The risk levels Never Blank takes (owner, 2026-09-28). `low` and nothing else:
high-risk-domain material is not admitted as an independent Never Blank
editorial topic, and there is no medium or high editorial mode to admit it to.
-->

- low

## Destination rules

<!--
The client's own tier-2 rules fixing a destination value, one row per value.
`fixes` is the E-14 field, `value` is written in the same grammar the register
records use, and `rule_id` is what a plan and a V-P04 finding cite.

Twelve rows, and the six that are missing are missing on purpose. LinkedIn
declares no length here so that `K-DST-LI-01`'s 250–400 words governs, and
Instagram declares no hashtag policy here so that `K-DST-IG-01`'s zero-to-three
governs. Both were migrated away from: the legacy `_WORD_RANGE["medium"]` of
120–220 words and `_COUNT_RANGE["instagram"]` of 3–6 tags would have won on
precedence alone, and migration does not resurrect a legacy value over an
accepted canonical record. The other lengths and policies below *are* those
legacy product decisions, promoted into the authority model they always
belonged in.

A `K-DST-` id is not a client rule id: those are the register's, and a contract
citing one would be claiming an authority it does not own.
-->

| rule_id | destination | fixes | value | statement |
|---|---|---|---|---|
| NB-DST-WIX-FORMAT | wix | E-14.format | article | The canonical article is the form Never Blank publishes on its own site. |
| NB-DST-WIX-LENGTH | wix | E-14.length_target | 400–600 words | A Never Blank article runs 400–600 words. |
| NB-DST-WIX-HASHTAGS | wix | E-14.hashtags | forbidden | The article carries no hashtags. |
| NB-DST-LI-HASHTAGS | linkedin | E-14.hashtags | required | A Never Blank LinkedIn post carries hashtags. |
| NB-DST-FB-LENGTH | facebook | E-14.length_target | 350–600 words | A Never Blank Facebook post runs 350–600 words. |
| NB-DST-FB-HASHTAGS | facebook | E-14.hashtags | required | A Never Blank Facebook post carries hashtags. |
| NB-DST-IG-LENGTH | instagram | E-14.length_target | 80–150 words | A Never Blank Instagram caption runs 80–150 words. |
| NB-DST-TH-LENGTH | threads | E-14.length_target | 150–400 words | A Never Blank Threads post runs 150–400 words. |
| NB-DST-TH-HASHTAGS | threads | E-14.hashtags | allowed | A Never Blank Threads post may carry hashtags and needs none. |
| NB-DST-TG-FORMAT | telegram | E-14.format | channel_post | Telegram is written as a channel post. |
| NB-DST-TG-LENGTH | telegram | E-14.length_target | 180–300 words | A Never Blank Telegram post runs 180–300 words. |
| NB-DST-TG-HASHTAGS | telegram | E-14.hashtags | forbidden | The Telegram channel carries no hashtags. |

## Client positions

<!--
The positional assets a strategy may cite as this client's own position (E-06,
Step 1 §4: `client_position_ref` comes "only from the contract"). Owner
decision, 2026-09-30: Never Blank takes **none**, and `none` is how that
decision is written. It is not the same statement as leaving the section out —
an absent section is a contract that did not answer, and the loader refuses it.

A declared position is one row: `| position_id | rule_id | statement |`.
-->

none

## Client prohibitions

<!--
The client's own tier-2 prohibitions, which S-09 applies as deterministic
exclusions (`ExclusionReason.CONTRACT_PROHIBITION`). Owner decision,
2026-09-30: Never Blank declares **none**.

This is the declaration that matters most, and the reason this section exists at
all. An empty prohibition set is permissive and silent: no candidate is ever
excluded by the contract, and the trace shows nothing was consulted. Written
here, "none" is the client's decision; left out, it would have been
indistinguishable from configuration nobody wrote.

A declared prohibition is one row:
`| rule_id | focal_subjects | reveals | statement |`, where a structural column
with nothing in it is written `—`. The tier is not a column: a rule declared
here is this client's own, which is tier 2, and a contract cannot promote its
own rule to hard platform policy.
-->

none

## Client preferences

<!--
The client's own preferences, which order candidates at §7.3's fifth rung and
never exclude anything. Owner decision, 2026-09-30: Never Blank declares
**none**. Same row shape as `## Client prohibitions`.
-->

none

## Hashtag vocabulary

<!--
The static, client-owned hashtag words, and nothing else (owner decision,
2026-09-30). This is **vocabulary, not policy**: whether a surface carries tags
at all is the destination's decision and stays in `## Destination rules` and the
`K-DST` records, which #363 owns and this section does not touch.

Two values, because only two are static. `#CompoundPresence` is conditional on
the accepted article actually naming Compound Presence, and the industry tag is
derived from the signal: both are computations, and a computed tag declared here
would be a claim the client never made. They stay where they are computed.
-->

- #NeverBlank
- #CustomerTrust
