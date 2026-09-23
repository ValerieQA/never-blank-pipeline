---
id: K-MAT-02
version: 1
status: candidate
tier: 3
evidence_class: OBS
confidence: low
review_by: 2027-09-21
---

# A second record claiming an id that is taken

## Statement
Two files now claim to be K-MAT-02, with different statuses and different
confidences. Every KnowledgeRef to K-MAT-02 would resolve to whichever file the
loader happened to read second, and the trace would not show which.

## Applies when
feature documented_case is yes

## Influences
- S-08 · `E-13.reader_path` — the ordered moves.

## Conflicts
None known.

## Source
A fixture for §8 rule 7.

## Change log
- v1, 2026-09-21: created as an invalid fixture: the id is already taken.
