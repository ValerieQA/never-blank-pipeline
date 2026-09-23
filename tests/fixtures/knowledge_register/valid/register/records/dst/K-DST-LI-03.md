---
id: K-DST-LI-03
version: 2
status: candidate
tier: 4
evidence_class: VEND
confidence: low
verified_on: 2026-09-21
review_by: 2026-12-21
supersedes: K-DST-LI-03 v1
---

# External link in the body of a LinkedIn post

## Statement
Vendor data associates a link in the body of a LinkedIn post with lower reach
than the same post without it.

## Applies when
destination is linkedin

## Influences
- S-10 · `E-14.cross_destination_link` — where the cross-destination link goes.
- S-13 — the soft signal V-S10 reads the same association.

## Conflicts
None known.

## Source
Vendor reach study cited in the research report "Link placement on LinkedIn",
section 3.

## Change log
- v2, 2026-09-21: confidence lowered from medium to low (keeper, from queue item
  KQ-0041).
- v1, 2026-09-21: created as a fixture record for the register validator.
