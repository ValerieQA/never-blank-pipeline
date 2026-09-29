---
id: K-DST-META-03
version: 1
status: descriptive
tier: 3
evidence_class: PLAT
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
---

# The "AI info" label is read off the image, and text gets no label at all

## Statement
Meta applies its "AI info" label automatically, from the C2PA and IPTC metadata
an image carries. Text is not labelled: there is no metadata on a paragraph to
read, so no label follows from how the words were written. The label is a
mechanism that reads a file, not a judgment about a post.

## Applies when
always

## Influences
- S-14 — what the platform labels by itself, and what it does not.
- S-15 — a label observed on a published item came from the image's metadata.

## Conflicts
None known. `K-DST-META-02` is the obligation to disclose and this is the
mechanism that labels; an automatic label does not discharge a disclosure
obligation, and a disclosure obligation does not create a label.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-META-03`
(platform documentation, descriptive mechanism, no tier).

## Notes
**The map gives this row no tier**, and the register format has no "no tier"
value: `tier` is required and a `descriptive` record is tier 3 to 6. It is filed
at tier 3, the descriptive tier that is not ranking behaviour, which is where
`K-DST-TG-01` and `K-DST-LI-02` sit for the same reason. Tier 3 is outside the
two tiers S-10 applies as platform rules, so the filing keeps the consequence
the map's dash intended: this record is never a `PlatformRule` and fixes no
destination value.

`always` here means **unbound**, exactly as in `K-DST-META-02`: the map does not
say which destinations the mechanism covers, and a binding is never inferred
from the `META-` prefix.

Transcribed from the accepted map rather than re-checked against the platform,
so `verified_on` is the day the map was accepted.

## Change log
- v1, 2026-09-29: created from the accepted map §8.6 as the label mechanism the
  map's review separated from the disclosure rule (#363).
