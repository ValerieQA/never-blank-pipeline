---
id: K-INV-01
version: 1
status: invariant
tier: 0a
evidence_class: REPO
confidence: high
review_by: 2027-09-21
---

# An invariant nobody approved

## Statement
This record says it must always hold, and violating it is a failure — and no owner
ever signed it off. An invariant that a keeper can add alone is not an invariant.

## Applies when
always

## Influences
- S-12 · `E-15.text` — the text itself.

## Conflicts
None known.

## Source
A fixture for §8 rule 3.

## Change log
- v1, 2026-09-21: created as an invalid fixture: `approved_by` is missing.
