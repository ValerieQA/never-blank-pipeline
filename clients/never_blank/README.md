# CLIENT: NEVER_BLANK

Never Blank **the client**: Never Blank's own editorial and marketing strategy,
running on the Never Blank **Engine** exactly as any other customer would (owner
decision D12, #240). Everything here says what to write, for whom, in which
voice and under which sourcing policy. Edit these files to change it.

| File | What it decides |
|---|---|
| `streams/monday.md` | What Monday is for, and what makes a signal usable for it (D1, D8) |
| `lenses/evidence.md` | Never Blank's evidence and source-integrity policy |
| `lenses/structure.md` | The article structure: the 11-step arc, step 9 conditional (D4, until #252) |
| `lenses/revision.md` | How a revision may change an article (D10, temporary until #253) |
| `lenses/evidence_tension_lens.md` | **Conditional**, `activates_on: [evidence_tension]` (#263): what Never Blank does when a signal's own research evidence contradicts the source's claim — the Evidence Tension Lens |

How the Engine reads these files is Engine documentation:
`docs/engine/CLIENT_CONTRACTS.md`.

Old Never Blank editorial documents elsewhere in the repository
(`config/brand_voice.md`, `docs/NEVER_BLANK_EDITORIAL_*.md`,
`strategy/methodology/`) are retired as authority (D12) and are not read.

Still configured outside this directory for now, and moving here in #255:
Monday's prohibitions, voice, channel rules and calls to action
(`strategy/current/business_strategy.json`), and the acceptance rubric
(`config/prompts/editorial_acceptance/never_blank.yaml`).
