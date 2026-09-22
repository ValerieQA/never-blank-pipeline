---
vocab_id: labels
version: 1
---

# Labels — the vocabulary no condition may use (I-10, AD-07)

Labels are written **after** the decision, by the label job, for observability.
They never reach S-00…S-13.

This file exists for two reasons, and neither is to be used:

1. so the `Applies when` parser can **refuse** a record conditioned on a label,
   and say which term did it (§4);
2. so the label job knows its own closed vocabulary.

A term here is refused however it is spelt: `material_label`, `Material Label`
and `material label` are the same term. The path names are the reader-path
labels of map §8.3 — they describe a path for a person, and no check and no
condition may use one (I-10). What a record conditions on instead is the
features in `features.md` and the strategy fields in `strategy_fields.md`.

## Terms

- `material_label` — the label derived from E-05 features after the analysis.
- `strategy_label` — the label given to a chosen strategy.
- `form_label` — the label given to the produced form.
- `Finding` — path label (K-MAT-01).
- `Teardown` — path label (K-MAT-02).
- `Post-mortem` — path label (K-MAT-03).
- `Argument` — path label (K-MAT-04).
- `Explainer` — path label (K-MAT-05).
- `Reader questions` — path label (K-MAT-06).
- `Scene` — path label (K-MAT-07).
- `Frame and points` — path label (K-MAT-08).
- `Inquiry` — path label (K-MAT-09).
