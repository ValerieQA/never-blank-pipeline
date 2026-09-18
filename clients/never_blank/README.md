# CLIENT: NEVER_BLANK

This directory is **Never Blank the client** — Never Blank's own editorial and
marketing strategy, running on the Never Blank **Engine** exactly as any other
customer would. Owner decision D12 (#240): the Engine is content-domain
agnostic; everything that says *what* to write, for *whom*, in *which voice*,
under *which sourcing policy* belongs to a client, and lives here as documents a
person can open, read and edit.

**Replace-the-client test.** Another business would replace this directory, not
the Engine's code. If a rule here only works because Python knows about it,
that is a leak and belongs in #255.

## What is here

| Path | What it is | Which stages the Engine routes it to |
|---|---|---|
| `streams/monday.md` | The Monday stream contract: its purpose and what makes a signal usable | purpose → writing; selection rules → selection |
| `lenses/evidence.md` | Never Blank's evidence and source-integrity policy | as its front matter says |
| `lenses/revision.md` | The temporary reviser contract (D10, until #253) | as its front matter says |

## Two kinds of document

**A stream contract** (`streams/*.md`) says what one stream is for. The Engine
parses it, so its headings are a contract: `## Purpose`, then `## Selection`.
Under `## Selection`, group rules under any `###` headings you like; every
bullet (`- `) is one rule a candidate signal is judged against. Front matter:
`stream_id`, `version`, `role_id`, `selection` (`first_valid` is the only mode:
signals are read in queue order and the first one that satisfies every rule
wins).

**A lens** (`lenses/*.md`) is any further rule document the client wants
applied — tone, a perspective, a sourcing policy, a campaign. The Engine does
not parse a lens; it delivers the whole text to the stages named in its front
matter. Front matter: `lens_id`, `version`, `applies_to` (stream ids), `stages`
(any of `selection`, `writing`, `revision`). Zero lenses is valid.

Nothing is applied that is not in these files. Historical Never Blank editorial
documents elsewhere in the repository (`config/brand_voice.md`,
`docs/NEVER_BLANK_EDITORIAL_*.md`, `strategy/methodology/`) are retired as
authority (D12) and are not loaded.

## Still configured elsewhere, for now

Monday's article structure, prohibitions, voice and channel rules are still read
from `strategy/current/business_strategy.json`, and the acceptance rubric from
`config/prompts/editorial_acceptance/never_blank.yaml`. They move here in the
Engine/Client work of #255.
