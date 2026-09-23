---
id: K-DST-TH-01
version: 1
status: descriptive
tier: 4
evidence_class: VEND, PLAT
confidence: low
verified_on: 2026-09-21
review_by: 2026-12-20
---

# Plain text is the weakest thing to post on Threads

## Statement
Vendor and platform data associate a plain-text post on Threads with about half
the pull of a post carrying video, and text with an image with something
between the two. The feed leans towards accounts the reader already follows, so
a post's reach depends less on the individual post than it does elsewhere.

## Applies when
destination is threads

## Influences
- S-10 · `E-14.format` — text with an image where one exists in the assets.
- S-10 · `E-14.segments` — how the sequence is broken into posts.
- S-13 — the soft signal V-S10 reads the same association in a finished text.

## Conflicts
None known. The record about live author replies (`K-DST-TH-02`) describes
something an autonomous run cannot do; it is Client Contract knowledge and not
an input to a production run.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-TH-01` (vendor
data and platform documentation, descriptive, tier 4).

## Notes
Confidence is `low` rather than `medium`: Threads is the destination the map
has least data on, and the figure is a ratio from one vendor. Transcribed from
the accepted map rather than re-measured, so `verified_on` is the day the map
was accepted.

## Change log
- v1, 2026-09-23: created from the accepted map §8 as the Threads seed record
  (NB-02c).
