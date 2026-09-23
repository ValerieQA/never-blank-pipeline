---
id: K-NB-06
version: 1
status: approved-rule
tier: 2
evidence_class: CLIENT
confidence: high
review_by: 2027-09-23
approved_by: client setup (Never Blank), 2026-09-23 (#268, #269)
---

# The constructions Never Blank does not publish

## Statement
Never Blank does not publish the phrases in its machine-tells list in its own
prose. The list is the client's taste and the only place a phrase is refused
outright; the Engine matches it and never interprets it.

## Applies when
always

## Influences
- S-10 · `E-14.forbidden` — the list reaches the plan as a constraint.
- S-12 · `E-15.text` — the Writer writes against it.
- S-13 · `E-15.text` — V-T06 refuses a text that carries one.

## Conflicts
The Engine's shared list (`config/machine_tells/shared.yaml`) only warns,
because a matcher sees occurrence and not use: a text quoting a tell, or taking
apart the copy that contains one, is not committing it. This record is
narrower on purpose — it is the client speaking about its own prose, so here
the match is a refusal.

## Source
`clients/never_blank/lists/machine_tells.md`, which holds the entries
themselves. This record says what the list is and where it binds; the list says
what is on it.

## Change log
- v1, 2026-09-23: the client's machine-tells list written as a rule record with
  Step 4 §2.2 front matter (NB-02c).
