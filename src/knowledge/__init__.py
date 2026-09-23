"""The knowledge register: the files a person edits, and the net under them.

`knowledge/` holds the universal knowledge the Editorial Core runs on, as plain
markdown a keeper can edit without code and without an AI (requirement Q1).
This package is the machine side of that: it reads those files, holds their
format and their closed vocabularies, parses the `Applies when` grammar, and
**refuses** a register that a hand edit has broken — in CI on every change, and
again at the start of every run, where a refusal is a `SKIP` at signal scope
with the reason `knowledge_register_invalid` (Step 4 §8).

`loader.py` is the other half: what a run *makes* of a valid register — the
effective status expiry gives each record today, which records are eligible and
applicable at a stage, and the knowledge a stage may never cut from its request
(§5, §5.1, §9).

It is deliberately **not** in `src/editorial_core/`. The register is not a
stage: it is repository content the stages read, versioned by git and referenced
by commit and digest (Step 4 §11). Nothing here takes an editorial decision, and
nothing here may: the loader says what reaches a stage and what a demoted record
may not do, and every editorial decision made on that knowledge stays with the
stage that makes it. The register index belongs to a slice after this one.

Sources: `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §1–§5, §7,
§8 and §9, with patch `PATCH_S4R1_STEP4.md`.
"""
