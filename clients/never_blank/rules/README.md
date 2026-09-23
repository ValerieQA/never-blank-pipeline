# Never Blank's own rules, as knowledge records

*Step 4 · `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §1, §2*

Client rules stay in the client folder. The knowledge register
(`knowledge/`) holds universal knowledge only, because the Client Contract is
already the authority for a client's rules and a shared register would create a
second one.

What arrives here with NB-02c is the **format**: each rule is one file in the
Step 4 §2 shape — front matter with `id`, `version`, `status`, `tier`,
`evidence_class`, `confidence`, `review_by`, then `## Statement`,
`## Applies when`, `## Influences`, `## Conflicts`, `## Source` and
`## Change log`. The rules themselves are not new. Every one of them is written
down in the documents the Engine already reads, and each record names the file
and the bullet it comes from; where the two ever disagree, the document the
Engine reads is the one in force until the loader arrives.

| Record | What it decides |
|---|---|
| `K-NB-01.md` | The article ends on the Kicker, and nothing follows it |
| `K-NB-02.md` | A social text adds nothing the run has not established |
| `K-NB-03.md` | Another publication's coined term is always attributed |
| `K-NB-04.md` | A consequence carries the evidence's number, or is falsifiable |
| `K-NB-05.md` | One case is a mechanism, not the reader's outcome |
| `K-NB-06.md` | The constructions Never Blank does not publish |

**Status and tier.** These are Never Blank's approved rules: `approved-rule`,
tier 2. A rule the client has not approved is written here too, as `candidate`
at tier 3, and approval is what moves it to tier 2 (§2.3). Neither needs an
owner's approval — an owner is needed for an invariant and for a tier-1 hard
platform rule, which is not what a client writes.

**The strength ladder.** A client may declare its own ladder in its contract,
as the `claim_strength_ceiling` plan slot, and then every level of it must say
which universal level it maps to. **Never Blank declares no ladder**, so the
universal one (`knowledge/ladders/default.md`) is in force unchanged, and
`K-NB-05` is what the client says about the evidence a single case reaches. If
a ladder is ever declared in `streams/monday.md`, the register validator checks
its mappings on every change — that check is already running.

**Nothing here is loaded into a run yet.** The loader that reads records into a
stage arrives with its own slice; until then these files are the written form
of rules the Engine gets from `streams/`, `lenses/` and `lists/` as it always
has. `tests/test_296_knowledge_seed_set.py` holds them to the register's own
rules, by validating them as records, so the format cannot rot while it waits.
