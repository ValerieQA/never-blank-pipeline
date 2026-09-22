---
id: K-LAD-01
version: 1
status: invariant
tier: A
evidence_class: OWNER
confidence: high
review_by: 2027-09-21
approved_by: owner, 2026-09-21 (U-4, docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md §7)
---

# The universal default strength ladder

## Statement
Four levels, worded as what the evidence shows rather than as a score, so that a
writer can phrase a claim at the strength its evidence actually reaches. An
interpretation's strength is at most the lowest strength among the evidence
claims supporting it; a forecast is capped at level 2, whatever its supports; a
generalization from a single case is capped at level 2, and is also a probe
family.

## Levels

| Level | Wording | Evidence that reaches it |
|---|---|---|
| 1 | Reported: "X says / reports …" | One source, attributed; nothing independent |
| 2 | Documented in a case: "in this case, …" | A primary document or a documented single case: a named company, a record, a filing |
| 3 | Corroborated: "several independent sources show …" | Two or more independent sources agree, with no material contradiction. One individual study, however well designed, reaches this level and no higher |
| 4 | Established: "across … , …" | Either authoritative statistics that directly measure the thing claimed, or convergent evidence across multiple cases: several independent studies agreeing, a systematic review, data spanning many cases |

## Applies when
always

## Influences
- S-06 · `E-11.strength_used` — the strength the anchor may be asserted at.
- S-08 · `E-13.editorial_thesis` — the ceiling of what the thesis may assert.
- S-12 · `E-15.text` — the strength a claim may be phrased at.
- S-13 — the truth call checks the text against the ceiling the ladder fixed.

## Conflicts
A client ladder declared in a Client Contract (`claim_strength_ceiling`) may
rename these levels and may restrict them further. It may never permit a
stronger assertion than this ladder allows for the same evidence: every client
level declares the universal level it maps to, and the effective ceiling is the
lower of the two.

## Source
`docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §7 (U-4 resolved),
as tightened by patch S4-R1 correction 4.

## Notes
Rejected alternatives, for anybody tempted by them again: three levels
(weak / medium / strong) cannot separate "one documented case" — the most common
Never Blank material — from "several sources"; a numeric strength is false
precision, because nobody can tell a writer what 0.6 means; separate ladders for
evidence and for interpretation break the minimum rule, which needs one scale.

## Change log
- v1, 2026-09-21: created from the accepted Step 4 architecture (U-4), with the
  patch S4-R1 wording of level 4.
