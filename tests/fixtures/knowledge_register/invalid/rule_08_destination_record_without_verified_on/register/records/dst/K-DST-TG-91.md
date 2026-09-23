---
id: K-DST-TG-91
version: 1
status: candidate
tier: 4
evidence_class: RES
confidence: low
review_by: 2026-12-21
---

# Telegram channel posts and the preview cut-off

## Statement
Research associates a Telegram channel post whose first line survives the preview
cut-off with more opens than one whose first line is truncated.

## Applies when
destination is telegram

## Influences
- S-10 · `E-14.first_line_mechanics` — what the preview cut-off has to do.

## Conflicts
None known.

## Source
A fixture for §8 rule 8: destination knowledge with no date on it. The number is
in the fixture range on purpose — the shipped register holds `K-DST-TG-01`
(#296), and a fixture reusing that id would overwrite the real record rather
than add a dated-less one beside it, firing rule 7 as well as rule 8.

## Change log
- v1, 2026-09-21: created as an invalid fixture: `verified_on` is missing.
