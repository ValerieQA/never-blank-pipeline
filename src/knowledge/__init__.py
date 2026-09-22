"""The knowledge register: the files a person edits, and the net under them.

`knowledge/` holds the universal knowledge the Editorial Core runs on, as plain
markdown a keeper can edit without code and without an AI (requirement Q1).
This package is the machine side of that: it reads those files, holds their
format and their closed vocabularies, parses the `Applies when` grammar, and
**refuses** a register that a hand edit has broken — in CI on every change, and
again at the start of every run, where a refusal is a `SKIP` at signal scope
with the reason `knowledge_register_invalid` (Step 4 §8).

It is deliberately **not** in `src/editorial_core/`. The register is not a
stage: it is repository content the stages read, versioned by git and referenced
by commit and digest (Step 4 §11). Nothing here takes an editorial decision, and
nothing here may: the loader that routes records to stages, precedence, expiry
demotion and the register index all belong to the slices after this one.

Sources: `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §1–§4, §7
and §8, with patch `PATCH_S4R1_STEP4.md`.
"""
