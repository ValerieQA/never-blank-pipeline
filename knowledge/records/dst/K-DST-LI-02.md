---
id: K-DST-LI-02
version: 1
status: descriptive
tier: 3
evidence_class: PLAT
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
---

# LinkedIn's "AI slop" filter, and why no checkable rule follows from it

## Statement
LinkedIn combines reader complaints with classifiers to demote posts it reads as
low-effort machine writing: about a 40% fall in out-of-network views, and a
private notice to the author. The criteria are not disclosed. So nothing
checkable follows from this record — what follows is an editorial conclusion:
avoid the patterns everyone else is using, and put something specific in the
first two lines.

## Applies when
destination is linkedin

## Influences
- S-10 · `E-14.first_line_mechanics` — something specific in lines 1 and 2.
- S-13 — the overused pattern is what the filter is reading for.

## Conflicts
None known. `K-DST-LI-01` is the same surface's ranking behaviour at tier 4 and
points the same way; this record is tier 3 because it describes a filter whose
criteria nobody has, not a ranking anybody measured.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-LI-02` (platform
documentation, descriptive, tier 3).

## Notes
Tier 3 rather than 4 is the map's own split of `K-DST-LI-02` from
`K-DST-LI-03`, and it is the point of the record: an undisclosed criterion is
not ranking behaviour a plan can be adapted to. Tier 3 is also outside the two
tiers S-10 applies as platform rules (§3, tiers 1 and 4), so this record shapes
the stage through the register's own selection and never through
`DestinationRules`. That is the correct reading of an editorial conclusion
drawn from a filter nobody can see.

Transcribed from the accepted map rather than re-checked against the platform,
so `verified_on` is the day the map was accepted.

## Change log
- v1, 2026-09-29: created from the accepted map §8.6 as the descriptive half of
  the LinkedIn pair the map's review split (#363).
