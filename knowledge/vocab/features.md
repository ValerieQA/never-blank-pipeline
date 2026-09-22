---
vocab_id: features
version: 1
---

# Material features (E-05)

What S-02 computes about the material, updated by S-03. A condition reads a
feature as `feature <name> is <value>`, and the value must be one this file
declares. The features themselves are map §8.3.

`material_label` is **not** here. It is derived from these features after the
analysis and lives in `labels.md`, which exists so that a record conditioned on
it is refused (I-10).

## Terms

- `documented_case`: yes / no — the material documents a real case: a named
  party, a record, a filing, something a reader can look up.
- `named_company`: yes / no — a company is named, rather than "a manufacturer".
- `figure_provenance`: own / third_party / none — who produced the figures: the
  subject itself, somebody reporting on it, or nobody.
- `method_known`: yes / no — how the figure was measured is stated.
- `freshness`: high / medium / low — how recent the material is against its own
  subject's pace of change.
- `mechanism_present`: yes / no — the material shows how something works, not
  only that it happened.
- `real_scene`: yes / no — a scene that happened, with a source. A scene
  presented as real without one violates I-03.
- `first_person`: yes / no — somebody in the material speaks from inside it.
- `failure_cost`: yes / no — what the failure cost is stated.
- `contested_assertion`: yes / no — a third-party assertion the evidence
  contests.
- `parallel_structure`: yes / no — several comparable items the material treats
  the same way.
- `open_question`: yes / no — a question the material leaves genuinely open.
