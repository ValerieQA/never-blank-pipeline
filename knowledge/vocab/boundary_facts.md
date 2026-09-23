---
vocab_id: boundary_facts
version: 1
---

# Interpretation Boundary facts (E-09)

Facts **code** computes from the boundary. A condition reads one as
`boundary has <fact>`, and a countable one also as
`boundary has at least <n> <fact>`, where the fact may be written in the plural:
`boundary has at least 2 admissible_interpretations`.

A model is never asked whether one of these holds. They are counted and compared
by code at the stage the record influences, and the result goes into the
StageRecord's routing evidence (§4, "Time of evaluation").

## Terms

- `contested_assertion` — the boundary carries an assertion the evidence
  contests.
- `counter_evidence` — the boundary carries evidence against one of its own
  interpretations.
- `admissible_interpretation`: <count> — an interpretation the boundary admits.
- `inadmissible_interpretation`: <count> — an interpretation S-04 generated or
  tested and refused. The list is evidence of what was tested, never a claim
  that everything tempting was found.
- `limitation`: <count> — a boundary-level limit, for example "single case" or
  "no second source".
- `ambiguity`: <count> — a contradiction, and which interpretations it affects.
  Whether it touches the anchor is decided at S-06, not here.
