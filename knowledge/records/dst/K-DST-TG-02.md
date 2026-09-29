---
id: K-DST-TG-02
version: 1
status: descriptive
tier: 4
evidence_class: PLAT, INF
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
---

# Telegram distributes by the forward, so the post is written to be forwarded

## Statement
A Telegram channel grows when a reader forwards a post into a conversation
somebody else is having. There is no feed deciding who else sees it, so the
distribution mechanism is the forwarded post itself: it arrives without the
channel's context, and it has to carry its own. What travels is a post whose
opening states something worth quoting and whose first paragraph stands alone
when it is read somewhere else.

## Applies when
destination is telegram

## Influences
- S-10 · `E-14.first_line_mechanics` — the opening is what a forward carries.
- S-10 · `E-14.segments` — the first segment stands on its own, because it is
  the one that travels.

## Conflicts
None known. `K-DST-TG-01` is the same surface at tier 3 and points the same way:
it describes why length is paid for by a reader who has already subscribed, and
this record describes how a post reaches a reader who has not. Neither fixes any
of E-14's three mandatory values, which the client contract states.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-TG-01` — "growth
through forwards" — read as the ranking half of a row the map records at tier 3
as a whole. Owner decision of 2026-09-28: Telegram gets its own tier-4
platform-ranking record rather than a promotion of `K-DST-TG-01`.

## Notes
This record exists because of the descriptive-versus-ranking separation the map
already applies to the other destinations, and the owner's decision was explicit
that `K-DST-TG-01` stays at tier 3 and is **not** promoted. TG-01 describes what
a subscribed reader punishes; this describes the mechanism that reaches an
unsubscribed one. Splitting them keeps one record to one tier, which is the
defect the map's own review §3 found in the LinkedIn and Facebook rows.

Confidence is `medium` and the evidence carries `INF`: the forward is documented
platform behaviour, and the editorial consequence drawn from it is inference.

It fixes none of E-14's three mandatory values, so it carries no `[fixes: …]`
clause and enters Telegram's adaptation as a constraint.

## Change log
- v1, 2026-09-29: created per the owner decision of 2026-09-28, as Telegram's
  tier-4 platform-ranking record beside the tier-3 `K-DST-TG-01` (#363).
