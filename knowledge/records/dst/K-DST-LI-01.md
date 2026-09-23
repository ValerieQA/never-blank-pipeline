---
id: K-DST-LI-01
version: 1
status: descriptive
tier: 4
evidence_class: VEND, PLAT
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
---

# What LinkedIn's own numbers say about a post's shape

## Statement
Vendor and platform data associate reach on LinkedIn with a post of roughly
250–400 words carrying one idea, a first line of about 40 characters or fewer
before the preview cuts, and — for a document carousel — about 1.39 times the
reach of the same material as a plain post.

## Applies when
destination is linkedin

## Influences
- S-08 · `E-13.reader_path` — one idea per post, so the path is short.
- S-10 · `E-14.length_target` — the 250–400 word range.
- S-10 · `E-14.first_line_mechanics` — what survives the preview cut.
- S-10 · `E-14.format` — a document carousel where the material suits one.

## Conflicts
None known. Where the client contract fixes a length or a first line, the
contract is tier 2 and wins. Where this record and a hard platform rule
disagree, the tier-1 rule wins and this one is recorded as not applied.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-LI-01` (vendor
data and platform documentation, descriptive, tier 4).

## Notes
Transcribed from the accepted map rather than re-measured, so `verified_on` is
the day the map was accepted and the 90-day review is the first real
re-verification. The "AI slop" filter record (`K-DST-LI-02`) and the automation
policy (`K-DST-LI-03`, tier 1) are part of the incremental migration and are
not in this seed set.

## Change log
- v1, 2026-09-23: created from the accepted map §8 as the LinkedIn seed record
  (NB-02c).
