---
id: K-DST-WIX-03
version: 1
status: approved-rule
tier: 1
evidence_class: PLAT
confidence: high
verified_on: 2026-09-21
review_by: 2026-12-20
approved_by: owner, 2026-09-28
---

# Google sanctions scaled unoriginal content, however it was produced

## Statement
Google's published policy sanctions content produced at scale that adds nothing
of its own, and states that the sanction does not depend on how the content was
made: material assembled from other pages is treated the same whether a person
or a model assembled it. What is sanctioned is the absence of the site's own
contribution, not the use of a tool.

## Applies when
destination is wix

## Influences
- S-10 · `E-14.exemplars` — a reference is a model for form, never material to
  reproduce; the do-not-copy note is the operative half.
- S-10 · `E-14.citations` — the article carries what it draws on rather than
  restating it as its own.
- S-13 — near-exact republication is what this policy reads.

## Conflicts
None known. Where a client rule and this record disagree, this is tier 1 and
wins: a contract may not contract around a platform's hard policy.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-WIX-03`
(platform documentation, platform rule, tier 1).

## Notes
Tier 1, so it is mandatory knowledge that is never cut for context size, and it
is the half of `K-DST-WIX-01` the map's review separated out as a rule rather
than a description.

It admits a compliant variant — an article that makes its own contribution
complies — so breaking it is replanned around rather than terminal (V-P04). The
register has no field for "admits no compliant variant", and a record that
admitted none would end a destination outright, which is an owner decision on
the record rather than something a loader may infer.

Transcribed from the accepted map rather than re-checked against the platform,
so `verified_on` is the day the map was accepted; `review_by` is the platform
90 days, because a published policy changes on the platform's own schedule.

## Change log
- v1, 2026-09-29: created from the accepted map §8.6 as the Google policy
  record, the tier-1 half `K-DST-WIX-01` was split from (#363).
