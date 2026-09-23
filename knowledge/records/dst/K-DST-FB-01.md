---
id: K-DST-FB-01
version: 1
status: descriptive
tier: 4
evidence_class: VEND
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
---

# A Facebook post with a link in its body reaches fewer people

## Statement
Vendor data holds the plain text status among Facebook's best-performing
formats, and associates a post carrying an external link in its body with lower
reach than the same post without one.

## Applies when
destination is facebook

## Influences
- S-10 · `E-14.cross_destination_link` — whether the link goes in the body.
- S-10 · `E-14.format` — the text status as the default form.
- S-13 — the soft signal V-S10 reads the same association in a finished text.

## Conflicts
The cross-destination link is always conditional (refinement R-2): the text must
deliver its promise without it. That rule comes first, so this record can move
the link or drop it, and can never make the text depend on one.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-FB-01` (vendor
data, descriptive, tier 4).

## Notes
Transcribed from the accepted map rather than re-measured, so `verified_on` is
the day the map was accepted. The engagement-bait policy (`K-DST-FB-02`,
tier 1) and the Meta-wide policy records are part of the incremental migration
and are not in this seed set.

## Change log
- v1, 2026-09-23: created from the accepted map §8 as the Facebook seed record
  (NB-02c).
