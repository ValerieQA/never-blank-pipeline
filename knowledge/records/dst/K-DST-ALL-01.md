---
id: K-DST-ALL-01
version: 1
status: descriptive
tier: 3
evidence_class: PLAT
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
---

# No platform reports "AI or not", so demotion is read from the numbers

## Statement
No platform tells a publisher whether it judged a post to be machine-written.
What is observable is the consequence: reach outside the follower graph, and
the account statuses a platform does expose. A run that wants to know whether it
was demoted reads those two and infers; it never waits for a verdict nobody
publishes.

## Applies when
always

## Influences
- S-15 — demotion is read from non-follower reach and account status, and never
  from a platform's own label.

## Conflicts
None known. `K-DST-META-03` describes the one label a platform does apply, which
is read off an image's metadata and is not a judgment about the post.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-ALL-01`
(platform documentation, descriptive, no tier — measurements).

## Notes
**The map gives this row no tier**, noting it as measurements, and the register
format has no "no tier" value. It is filed at tier 3, the descriptive tier that
is not ranking behaviour, which keeps the consequence the map's dash intended:
tier 3 is outside the two tiers S-10 applies as platform rules, so this record
is never a `PlatformRule` and fixes no destination value.

`always` is a real binding here rather than an unresolved one: the statement is
about every platform, which is what `ALL` means, and it influences S-15 — which
runs after publication and reads whatever destination was published to.

Transcribed from the accepted map rather than re-measured, so `verified_on` is
the day the map was accepted.

## Change log
- v1, 2026-09-29: created from the accepted map §8.6 as the cross-destination
  measurement record (#363).
