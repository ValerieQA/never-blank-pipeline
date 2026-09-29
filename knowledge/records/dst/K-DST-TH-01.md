---
id: K-DST-TH-01
version: 2
status: descriptive
tier: 4
evidence_class: VEND, PLAT
confidence: low
verified_on: 2026-09-21
review_by: 2026-12-20
supersedes: K-DST-TH-01 v1
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
- S-10 · `E-14.format` — a post, carrying an image where one exists in the
  assets. [fixes: post]
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

`[fixes: post]` is the form, not the media: E-14's format vocabulary has no term
for "text with an image", and whether an image is attached is the assets' answer
rather than the format's. What this record fixes is that a Threads unit is one
post and not a thread of them.

## Change log
- v2, 2026-09-29: a `[fixes: …]` clause added to the S-10 format entry, so
  `DestinationRules` can be built from this record instead of from a fixture
  (#363). The statement, tier and applicability are unchanged.
- v1, 2026-09-23: created from the accepted map §8 as the Threads seed record
  (NB-02c).
