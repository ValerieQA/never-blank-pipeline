---
vocab_id: stages
version: 1
---

# Stages (Step 2)

The stages a record's `## Influences` may name. This list mirrors the
stage-topology registry (`src/editorial_core/topology.py`), which is the one
place that says what the engine is (CE-1), and the validator refuses the
register if the two disagree.

A record may influence any stage. In practice S-14 and S-15 take no editorial
decision: S-14 packages and publishes, S-15 observes.

## Terms

- `S-00` — signal selection.
- `S-01` — Evidence Core (initial) and the relevance screen.
- `S-02` — material features and initial assets.
- `S-03` — the enrichment loop.
- `S-04` — the Interpretation Boundary.
- `S-05` — Editorial Units.
- `S-06` — the anchor.
- `S-07` — destinations.
- `S-08` — candidate strategies.
- `S-09` — strategy selection.
- `S-10` — the executable plan.
- `S-11` — plan check and exemplars.
- `S-12` — the writer.
- `S-13` — the text check.
- `S-14` — publication and fingerprint.
- `S-15` — observation, after the run.
