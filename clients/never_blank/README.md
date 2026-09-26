# CLIENT: NEVER_BLANK

Never Blank **the client**: Never Blank's own editorial and marketing strategy,
running on the Never Blank **Engine** exactly as any other customer would (owner
decision D12, #240). Everything here says what to write, for whom, in which
voice and under which sourcing policy. Edit these files to change it.

| File | What it decides |
|---|---|
| `streams/monday.md` | What Monday is for, what makes a signal usable for it (D1, D8), and the `## Plan` the run executes the contract as (#267, #268) |
| `lenses/evidence.md` | Never Blank's evidence and source-integrity policy |
| `lenses/structure.md` | Editorial Policy v2 (#268): the fixed frame, the middle-pattern library, the standing obligations, and the ending that stops at the Kicker |
| `lenses/concession.md` | When an article concedes, and when it says nothing (#268) |
| `lenses/portable_noun.md` | Mint our own, reuse our own, or none — and the cut test (#268) |
| `lists/machine_tells.md` | Constructions Never Blank never publishes (#268) |
| `audience.md` | Who Never Blank writes for, in the attributes `knowledge/vocab/audience_attributes.md` declares (#335). The only client context the interpretation boundary reads |
| `editorial/reference/library.md` | The index over the reference documents (#338): one row per item, with the ID S-11 attaches to an approved plan and its "take" / "do not copy" notes |
| `lenses/revision.md` | How a revision may change an article (D10, temporary until #253) |
| `lenses/evidence_tension_lens.md` | **Conditional**, `activates_on: [evidence_tension]` (#263): what Never Blank does when a signal's own research evidence contradicts the source's claim — the Evidence Tension Lens |
| `rules/` | The same rules as knowledge records, in the Step 4 §2 format with front matter (#296). Not read by the Engine yet; `rules/README.md` says what they are for |

How the Engine reads these files is Engine documentation:
`docs/engine/CLIENT_CONTRACTS.md` and `docs/engine/EDITORIAL_PLAN.md`.

The editorial source of truth these policies were written from is in
`editorial/reference/`, indexed by `editorial/reference/library.md` so that
S-11 can hand a plan an example from it by ID (#338). Adding a document there
means adding a row; item IDs are permanent and are never renumbered, because an
exemplar an earlier run recorded still names the item it named then.
Two points there are deliberately superseded by the
owner decisions in #266 and #268: the article no longer ends with a CTA after
the Kicker, and "one deliberate deviation" is now the moment of authorial
risk — editorial judgement, with nothing checking it mechanically.

Old Never Blank editorial documents elsewhere in the repository
(`config/brand_voice.md`, `docs/NEVER_BLANK_EDITORIAL_*.md`,
`strategy/methodology/`) are retired as authority (D12) and are not read.

Still configured outside this directory for now, and moving here in #255:
Monday's prohibitions, voice, channel rules and calls to action
(`strategy/current/business_strategy.json`), and the acceptance rubric
(`config/prompts/editorial_acceptance/never_blank.yaml`).
