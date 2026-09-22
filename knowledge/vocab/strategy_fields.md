---
vocab_id: strategy_fields
version: 1
---

# Strategy fields usable in a condition (E-13)

A condition reads one as `strategy <field> is <value>`.

Only the E-13 fields with a **closed** set of values are here. `editorial_job`,
`angle`, `editorial_thesis` and `ending_intention` are open text by design
(I-10: no enum), so no condition can compare them.

A record whose condition uses one of these terms must influence a stage from
S-09 to S-13 (§4): before S-09 no strategy exists to read, so such a condition
could only ever be false, and the validator refuses it rather than letting a
record apply to nothing.

## Terms

- `reveal`: immediate / gradual / delayed — when the withheld variable arrives.
- `concession`: present / absent — whether the strategy concedes a limitation.
- `focal_subject`: company / owner_reader / client / person_in_story — who the
  text is about. `person_in_story` requires a documented case in the core.
