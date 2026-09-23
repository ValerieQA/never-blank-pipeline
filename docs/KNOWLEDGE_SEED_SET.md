# NB-02c evidence map — the knowledge the engine needs to run

Issue #296 (SL-2), on top of NB-02a (#294, the register format and its
validator). Requires: `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md`
§3, §6, §7; `docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md` S-11 and
S-13 route tables, §4 U-1.

Each acceptance criterion below is exactly one of `SATISFIED` /
`NOT DELIVERED`.

**This document exists because the deliverable is a corpus.** NB-02a shipped a
validator and no content; this ships content. Forty-two records are harder to
review than a table that says what each one is and which criterion it answers.

## What was built

| Piece | Where | Count |
|---|---|---|
| The universal strength ladder (U-4) | `knowledge/ladders/default.md` | 1, already shipped with #294 |
| Plan check records | `knowledge/checks/V-P0*.md` | 5 |
| Text check records | `knowledge/checks/V-T0*.md` | 8 |
| Soft signal records | `knowledge/checks/V-S*.md` | 10 |
| Probe families (U-1) | `knowledge/records/tempt/K-TEMPT-0*.md` | 7 |
| Destination records | `knowledge/records/dst/K-DST-*.md` | 6, one per destination |
| Never Blank's rules as records | `clients/never_blank/rules/K-NB-0*.md` | 6 |
| The acceptance tests | `tests/test_296_knowledge_seed_set.py` | — |

Nothing but content and its tests. The validator, the grammar, the vocabularies
and the CI caller are #294's and are untouched; no module under `src/` and no
workflow was edited.

## Acceptance evidence

**1. "Validator passes on the seed set."**
`SATISFIED`.

`test_the_validator_accepts_the_seed_set` runs `validate_register` over the
shipped `knowledge/` with the client rule files, and asserts no findings —
as do #294's `test_the_shipped_register_is_valid` and
`test_the_ci_script_accepts_the_shipped_register`, which now run over a register
that has content in it. CI runs the same ten rules against the branch the pull
request targets, so rule 7's version half is in force for every later edit to
these files.

The seed set is not exempt from anything. Every record here was written to the
same §2 format a keeper edits by hand, and the two rules that most often catch a
hand edit apply to it in full: `## Influences` names only stages and fields the
vocabularies declare, and every `## Applies when` is one line of the §4 grammar
(`always`, `destination is telegram`, `feature real_scene is no`,
`not (destination is wix)`).

**2. "Check-record route tables match Step 2 (validator rule 6)."**
`SATISFIED`.

Rule 6 compares each `## Route` row against the stage-topology registry
(`src/editorial_core/topology.py`), which is where the Step 2 §5.3 table lives.
`test_each_check_routes_exactly_as_the_topology_declares` is parametrised over
all 23 checks and asserts the same comparison directly — target, counter and
terminal outcome per row — so the criterion is proven by an assertion and not
only by the validator's silence.

| Check | Rows | Route of record |
|---|---|---|
| V-P01, V-P02 | S-11 → S-08 | `plan_check_failed`, `L_strategy`, `skip_destination` |
| V-P03 | S-11 → S-08 | `plan_deviates_from_the_unit`, `L_strategy`, `skip_destination` |
| V-P04 | S-11 → S-08, and one terminal row | tier 2 replans; a tier-1 rule with no compliant variant ends the destination |
| V-P05, V-S01…V-S10 | `hint` | a soft check routes nothing (I-12) |
| V-T01 | S-13 → S-12 ×3, S-13 → S-08 | the `removable` / `load-bearing` branches |
| V-T02 | S-13 → S-04 | `interpretation_inadmissible_or_unlisted`, `L_boundary` |
| V-T03, V-T07 | S-13 → S-08 | `structural_or_load_bearing_fault`, `L_strategy` |
| V-T04, V-T06 | S-13 → S-12 | `phrasing_or_removable_fact`, `L_edit` |
| V-T05 | terminal | `skip_publication` |
| V-T08 | S-13 → S-08 and S-13 → S-12 | the `strategy` / `execution` branches |

`test_the_two_branching_checks_carry_their_branches` holds the part a route
table cannot state: V-T01 and V-T08 carry a `## Branch criterion`, and their
rows reach both owners — the Writer for what it wrote, S-08 for what it was
told to write. Both criteria end where Step 2 §5.3 ends: **when uncertain, the
plan branch.**

**3. "Each of the six destinations has ≥1 K-DST record."**
`SATISFIED`.

| Destination | Record | What it says | Tier |
|---|---|---|---|
| `wix` | `K-DST-WIX-01` | the article is scanned before it is read | 3 |
| `linkedin` | `K-DST-LI-01` | 250–400 words, one idea, the first line before the cut | 4 |
| `facebook` | `K-DST-FB-01` | a link in the body costs reach | 4 |
| `instagram` | `K-DST-IG-01` | carousel for saves, one idea per slide, 0–3 hashtags | 4 |
| `threads` | `K-DST-TH-01` | plain text is the weakest form | 4 |
| `telegram` | `K-DST-TG-01` | no feed, so the first line is the whole offer | 3 |

`test_every_destination_has_at_least_one_record` does not read that table. It
parses each record's condition with the register's own grammar, collects the
destinations the conditions name, and asserts the set equals the destination
vocabulary — which itself mirrors `src/publishing/release_scope.py`. A seventh
destination therefore fails this test until it has a record, and a record
naming a destination that does not exist fails at KR-04 first.

Each of them carries `verified_on`, which rule 8 requires and §5 computes the
90-day expiry from. All six are `descriptive`, tier 3 or 4. **The tier-1 hard
platform policy records are deliberately not here**: they are part of the
incremental migration this issue puts out of scope, and each one needs the
owner's approval recorded in the file. Every record names the map row it came
from and the sibling records left behind.

**4. The seven probe families (U-1).**
`SATISFIED`.

`K-TEMPT-01` transfer to the reader · `-02` benefit inflation · `-03` invented
scene · `-04` causal overreach · `-05` generalization from a single case ·
`-06` forecast stated as fact · `-07` burden inflation — Step 2 §4's list, in
its order.

§6 asks for two things a record does not normally have, and
`test_each_probe_family_asks_a_question_and_cites_a_real_output` asserts both:
`## Probe` is the question the S-04 probe call asks, and `## Real examples`
cites **real engine output**. The citations are of two kinds, and no family has
an invented one:

- a package this repository holds, by file and generation date —
  `reports/content_packages/0c3ab0c08576373a_generated.json` (2026-09-17) and
  `reports/content_packages/a71d52f27d921529_generated.json` (2026-09-18),
  quoted exactly;
- a walkthrough of `CANONICAL_EDITORIAL_MAP_v1.md` §13, where the map itself
  records that the reading "appeared in the real output" — which is where
  "the compliance checklist doubles" and "owners were buried in inspections"
  come from.

All seven are tier 3, `descriptive`, and influence S-04 and nothing else
(`test_each_probe_family_is_tier_3_and_influences_s_04_only`). The boundary
stays bounded: these are what S-04 probes for, and V-T02 is not limited to them
(patch R1).

**5. Never Blank's client rules, with front matter.**
`SATISFIED`.

Six rules in `clients/never_blank/rules/`, each in the §2 format with the §2.2
front matter, each naming the document and the bullet it was written from:
the Kicker ending, the derivative restriction, attribution of a coined term,
the falsifiable consequence, the acknowledged limits and the machine-tells
list. They stay in the client folder because the Client Contract is already
their authority (§1), and they are `approved-rule` at tier 2, which is what an
approved client rule is (§2.3).

The register's CI caller reads the client folder for two things only — a
declared ladder and credentials — so these files would otherwise be checked by
nothing. `test_the_client_rules_are_records_the_register_would_accept` lays
them over a copy of the register under their own family directory and runs the
full validator, so they answer for their front matter, their status and tier,
their conditions, the stages and fields they name and their versioning exactly
as a register record does.

`K-NB-02` is the one that needed a decision rather than a transcription. As
written for the current engine it says a post carries only what the accepted
**article** contains, and I-06 says no text is the source of another. The
record states the rule as the client wrote it and resolves the conflict in
`## Conflicts`: the tier-A invariant decides where material comes from, and
what survives at tier 2 is the rule's actual force — a destination text asserts
nothing the run has not established. No invariant, stage responsibility or
accepted decision was changed to fit it.

**6. Client ladder mapping, if a ladder is declared.**
`SATISFIED`, conditionally and on purpose.

**Never Blank declares no `claim_strength_ceiling`**, so the universal ladder
is in force unchanged, and there is no client level to map. Declaring one is a
client editorial decision, not something this issue may make on the client's
behalf. `test_a_declared_client_ladder_maps_every_level_to_a_universal_one` is
written so that it costs nothing today and bites the moment a contract declares
a ladder: it walks every client stream contract this repository ships and, for
each one that declares levels, asserts `client_ladder_problems` is empty.
Rule 9 in CI says the same thing on every change.

## Must preserve

- **I-13, no research finding becomes a hard check without approval.** The seed
  set ships no hard check drawn from research at all:
  `test_no_hard_check_rests_on_research_alone` asserts that no `class: H`
  record carries `RES`. What research did produce — the construction types, the
  repetition signal, the ending with no progression — is shipped as soft
  signals, `class: S`, `rule_status: candidate`, routing nothing.
- **I-12, soft signals do not become thresholds.** Every soft check declares
  `threshold: none` and no `approved_by`
  (`test_no_soft_check_carries_a_threshold_without_an_owner`), and every one of
  their rows is a `hint` with nothing in the cause, counter or exhaustion
  column.
- **I-10, no record is conditioned on a label.** The conditions in this seed
  set use destinations and two material features. The one place a label is read
  at all is `V-S06`, the anti-template test, which runs after the run on
  fingerprints and reaches no stage — the check record says so in its own
  criterion.
- **Q1, human-editable.** Every file here is markdown a keeper opens and edits.
  Where a record was transcribed from the map rather than re-verified, its
  `## Notes` says so, and `verified_on` is the day the source it came from was
  last checked rather than the day it was typed.

## What this moved in #294's corpus

Two of NB-02a's invalid fixtures claimed ids this seed set now ships: `V-P01`
and `K-DST-TG-01`. The corpus is laid *over* the real register, so those two
stopped **adding** a defective record and started **replacing** a real one —
which is also a changed body at an unchanged version, so rule 7 fired beside
the rule each fixture exists to prove, and
`test_each_invalid_file_is_rejected_by_its_own_rule` refused the pair.

They are now `V-P91` and `K-DST-TG-91`, in the range the corpus already used
for `K-MAT-91`…`K-MAT-95`. Neither defect changed: the rule-6 fixture still
spends the wrong counter and ends in the wrong outcome, and the rule-8 fixture
is still a `K-DST-*` record with no `verified_on` — KR-06 and KR-08 read the
route table and the id *prefix*, neither of which the renumbering touches. The
convention is written down in `docs/KNOWLEDGE_REGISTER_VALIDATION.md` so the
next seed record does not walk into it again.

## Production safety

Files only. Nothing here publishes, calls a provider or spends a model call. No
stage reads the register yet: the loader arrives with its own slice, and until
then a broken record can only stop a run at the gate, never change what a run
publishes.
