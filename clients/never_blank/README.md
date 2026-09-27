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
| `editorial/reference/library.md` | The index the Reference Library loader reads (#338, populated in #353): one row per item, with the ID S-11 attaches to an approved plan and its "take" / "do not copy" notes. Covers **linkedin / post only** — see below |
| `lenses/revision.md` | How a revision may change an article (D10, temporary until #253) |
| `lenses/evidence_tension_lens.md` | **Conditional**, `activates_on: [evidence_tension]` (#263): what Never Blank does when a signal's own research evidence contradicts the source's claim — the Evidence Tension Lens |
| `rules/` | The same rules as knowledge records, in the Step 4 §2 format with front matter (#296). Not read by the Engine yet; `rules/README.md` says what they are for |

How the Engine reads these files is Engine documentation:
`docs/engine/CLIENT_CONTRACTS.md` and `docs/engine/EDITORIAL_PLAN.md`.

The editorial source of truth these policies were written from is in
`editorial/reference/`, indexed by `editorial/reference/library.md`.

**What is in the library.** Three exemplars, all `linkedin` / `post`
(`REF-001`…`REF-003`), from `sample_linkedin_articles_2026-07-21.md` — genuine
Never Blank prose written to demonstrate the editorial system, carrying its own
`cta_mode`, earned-versus-absent Echo and CTA placement. `K-EXM-01` puts the
ceiling at 2–5 examples and selects "by text type, not by topic", which is what
one destination and one format is.

**What is deliberately not in it.** The readability research in the same
directory — `article_readability_research.md` and
`12_—_Структура_статьи…` — is the source the architecture was written from, and
it is **not** indexed. An exemplar is a reference a Writer learns register and
form from; a research note *about* form is not one. #338's first attempt indexed
these and was blocked for that reason.

**What is still missing, and what would close it.** There is no exemplar for
`wix` / `article` — the primary surface — and none for facebook, instagram,
threads or telegram. The repository holds four genuinely published Never Blank
articles in `strategy/published_content_index.jsonl`, but only their `hook`,
`echo`, `topic` and `cta_mode`; the prose itself is not stored, and the only
`generated.json` artifacts belong to test signals. Closing the gap needs
**editorial input, not code**: the body text of one or two published articles for
`wix` / `article`, and a real post per remaining surface, each with its take and
do-not-copy notes. Until then S-11 attaches no exemplar for those destinations,
which is the supported state rather than a fault.

**Authoring the corpus is editorial content work with its own timeline**, not
part of the loader. When it exists, add `editorial/reference/library.md` with one
row per item: the ID S-11 attaches to an approved plan and its "take" / "do not
copy" notes. Item IDs are permanent and are never renumbered, because an
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

## Filenames with non-ASCII characters

Some documents here are named in Russian, and that needs one rule (#325).

**Tracked paths are NFC.** macOS stores `ресёрч` decomposed — `е` + U+0308 — and
git precomposes it to `ё` when it reads the directory, because
`core.precomposeunicode` defaults to true there. If a decomposed spelling is ever
committed, the index ends up holding **two** entries for one file, and on macOS
`git status` stays clean: the filesystem satisfies both from the single file on
disk. The duplicate is invisible exactly where it is made, and appears as two
copies of the document on a Linux checkout.

That is why it came back three times (#321, #288, #289) — any `git add -A` in a
worktree still holding the other spelling re-adds it. `scripts/ci/check_path_normalization.py`
runs in *PR Tests* and fails on a duplicate or on any tracked path that is not
NFC, printing the code points so the two spellings can be told apart.

If you ever need to drop such a duplicate, git precomposes pathspec arguments
too, so the spelling has to be passed literally:

```
git -c core.precomposeunicode=false rm --cached -- '<the NFD path>'
```

The file on disk is untouched; only the duplicate index entry goes.
