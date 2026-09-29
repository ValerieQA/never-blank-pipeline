---
id: K-DST-IG-01
version: 2
status: descriptive
tier: 4
evidence_class: VEND, PLAT
confidence: medium
verified_on: 2026-09-21
review_by: 2026-12-20
supersedes: K-DST-IG-01 v1
---

# What an Instagram carousel is good at, and what it needs per slide

## Statement
Vendor and platform data associate the carousel with engagement and saves and
Reels with reach; within a carousel, one idea per slide, keywords placed after
the first line where search reads them, and between zero and three hashtags.

## Applies when
destination is instagram

## Influences
- S-10 · `E-14.format` — carousel where the material has ordered steps.
  [fixes: carousel]
- S-10 · `E-14.segments` — one idea per slide.
- S-10 · `E-14.first_line_mechanics` — what the first slide carries.
- S-10 · `E-14.hashtags` — zero to three, so tags are permitted and none are
  required, and the keywords sit after the first line. [fixes: allowed]

## Conflicts
None known. Instagram needs an image from the existing image pipeline, and a
unit with no usable image is a destination decision at S-07, not a conflict
with this record.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-IG-01` (vendor
data and platform documentation, descriptive, tier 4).

## Notes
Transcribed from the accepted map rather than re-measured, so `verified_on` is
the day the map was accepted. `K-DST-META-01` (tier 1) was transcribed by #363
and is bound to Instagram, because the map's own row names it. The disclosure
policy `K-DST-META-02` was transcribed **unbound**: the map does not say which
destinations it covers, and that is an open keeper question rather than a
binding this register may infer.

`[fixes: allowed]` is the `HashtagPolicy` the zero-to-three range means: a
surface that wants no tags at all would forbid them, and one that required them
would not start at zero. The count itself is not carried into `E-14.hashtags`,
which is a policy and not a range — what this record still states, and what a
keeper reads, is the zero-to-three above.

## Change log
- v2, 2026-09-29: `[fixes: …]` clauses added to the two S-10 entries that fix a
  value, so `DestinationRules` can be built from this record instead of from a
  fixture (#363). The statement, tier and applicability are unchanged. The
  legacy `_COUNT_RANGE["instagram"]` of three-to-six tags is deliberately not
  promoted over this record.
- v1, 2026-09-23: created from the accepted map §8 as the Instagram seed record
  (NB-02c).
