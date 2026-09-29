---
id: K-DST-LI-03
version: 1
status: approved-rule
tier: 1
evidence_class: PLAT
confidence: high
verified_on: 2026-09-21
review_by: 2026-12-20
approved_by: owner, 2026-09-28
---

# Automated comments and automated engagement are blocked on LinkedIn

## Statement
LinkedIn's platform policy blocks automated commenting and automated
engagement: a program may publish what its owner wrote, and may not work the
feed on the owner's behalf. Detection ends in restriction of the account rather
than in a demoted post.

## Applies when
destination is linkedin

## Influences
- S-14 — the run publishes the text it produced and automates no comment, like
  or follow around it.

## Conflicts
None known. This is tier 1 and no client rule reaches past it.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-LI-03` (platform
documentation, platform rule, tier 1).

## Notes
It influences S-14 and not S-10, and that is not an oversight: the policy is
about actions taken around a post, and S-10 plans the post. So it reaches no
`DestinationRules` — there is nothing in an executable plan for it to fix — and
a reader looking for it in LinkedIn's adaptation constraints is looking in the
wrong stage.

Transcribed from the accepted map rather than re-checked against the platform,
so `verified_on` is the day the map was accepted.

## Change log
- v1, 2026-09-29: created from the accepted map §8.6 as the tier-1 half of the
  LinkedIn pair the map's review split (#363).
