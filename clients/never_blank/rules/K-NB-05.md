---
id: K-NB-05
version: 1
status: approved-rule
tier: 2
evidence_class: CLIENT
confidence: high
review_by: 2027-09-23
approved_by: client setup (Never Blank), 2026-09-23 (#268)
---

# One case is evidence of a mechanism, never proof of the reader's outcome

## Statement
A documented case shows how something works. It does not show what will happen
to the reader, and the text says so where it matters. Where a figure comes from
a single vendor, a single sample or a self-reported measurement, that is stated
beside the figure rather than in a note at the end.

## Applies when
feature documented_case is yes

## Influences
- S-06 · `E-11.strength_used` — the anchor is asserted at the strength one case
  reaches.
- S-08 · `E-13.concession` — the limitation is conceded inside the strategy.
- S-12 · `E-15.text` — the provenance sits beside the figure.

## Conflicts
The universal strength ladder (`K-LAD-01`) caps a generalization from a single
case at level 2. The two agree, and the effective ceiling is the lower of the
two, as it is for any client ladder. Never Blank declares no ladder of its own
in its contract, so the universal ladder is the one in force.

## Source
`clients/never_blank/streams/monday.md`, plan slot `acknowledged_limits`, both
bullets.

## Change log
- v1, 2026-09-23: the client's acknowledged limits written as a rule record
  with Step 4 §2.2 front matter (NB-02c).
