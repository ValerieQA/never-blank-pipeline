# NB-02a evidence map — a hand edit cannot silently break a run

Issue #294 (SL-2), on top of NB-01a (#290, `src/editorial_core/topology.py`).
Requires: `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §1–§4,
§7, §8.

Each acceptance criterion below is exactly one of `SATISFIED` /
`NOT DELIVERED`.

**This document exists because the evidence is spread across a corpus.** The
implementation is one validator and ten rules; the proof that it does its job
is a directory of deliberately broken files, and a table of which file proves
which rule is easier to check than the files are. Every row below names a file
or a test in the tree, so each claim can be checked without reading the whole
change.

## What was built

| Piece | Where |
|---|---|
| The register layout, the record, check-record and probe-family formats | `knowledge/README.md` |
| Closed vocabularies, including the label vocabulary (I-10) | `knowledge/vocab/*.md`, read by `src/knowledge/vocabulary.py` |
| The universal strength ladder (U-4) | `knowledge/ladders/default.md`, read by `src/knowledge/ladder.py` |
| The `Applies when` controlled grammar (§4) | `src/knowledge/grammar.py` |
| Front matter and section parsing | `src/knowledge/markdown.py`, `src/knowledge/records.py` |
| Rules 1–10, and KR-00 | `src/knowledge/validator.py` |
| The CI caller | `scripts/ci/check_knowledge_register.py` |
| The run-start caller | `src/knowledge/run_start.py` |

One validator, two callers. `validate_register` is the only thing that knows a
rule; CI and run start differ in exactly one respect, stated below.

Seed content was out of scope here and arrived with NB-02c (#296), which filled
`knowledge/records/` and `knowledge/checks/`; `docs/KNOWLEDGE_SEED_SET.md` is
its evidence map. The corpus below supplies the records the validator is proven
against, laid over the **real** vocabularies and the **real** universal ladder
rather than over copies — a fixture register carrying its own vocabularies
would go on passing after the shipped ones stopped agreeing with the code that
reads them (`build_register`, `tests/test_294_knowledge_register.py`).

## Acceptance evidence

**1. "A corpus of invalid files, one per validator rule, all rejected."**
`SATISFIED`.

`tests/fixtures/knowledge_register/invalid/rule_NN_…/` — one directory per
rule, each dropped into the accepted register, each carrying exactly one
defect:

| Rule | Fixture | The one defect |
|---|---|---|
| KR-01 | `rule_01_missing_required_field/…/K-MAT-91.md` | `review_by` is missing, so nothing can expire the record |
| KR-02 | `rule_02_status_and_tier_not_a_pair/…/K-MAT-92.md` | `descriptive` claims tier 1; §2.3 gives it 3–6 |
| KR-03 | `rule_03_invariant_without_approval/…/K-INV-01.md` | an invariant with no `approved_by` |
| KR-04 | `rule_04_condition_uses_a_label/…/K-MAT-93.md` | the condition reads a label term (I-10) |
| KR-05 | `rule_05_influences_an_unknown_stage/…/K-MAT-94.md` | it influences `S-16`, which the engine does not have |
| KR-06 | `rule_06_route_differs_from_the_registry/…/V-P91.md` | the check's `## Route` row spends the wrong counter and ends in the wrong outcome |
| KR-07 | `rule_07_id_already_exists/…/K-MAT-02-copy.md` | a second file claiming `K-MAT-02` |
| KR-07 | `rule_07_version_did_not_increase/…/K-MAT-02.md` | a changed statement at the same version, with no change-log line |
| KR-08 | `rule_08_destination_record_without_verified_on/…/K-DST-TG-91.md` | destination knowledge with no date on it |
| KR-09 | `rule_09_client_ladder_is_not_monotonic/client/streams/weekly.md` | the second level maps *lower* than the first |
| KR-10 | `rule_10_file_carries_a_credential/…/K-MAT-95.md` | a key pasted into the file (Q8) |

`test_each_invalid_file_is_rejected_by_its_own_rule` is parametrised over that
directory listing and asserts, per case, that the register is refused **and**
that the set of rules fired is exactly `{its own}`. A fixture that tripped two
rules would prove neither of them, so that equality is the point of the
assertion rather than a tightening of it.

**A fixture id is in the fixture range** — `K-MAT-91`…`K-MAT-95`,
`K-DST-TG-91`, `V-P91` — **and never an id the accepted register already
holds.** The corpus is laid *over* that register, so a fixture reusing one of
its ids replaces the record instead of adding one: the defect is then also a
changed body at an unchanged version, and rule 7 fires beside the rule the
fixture exists to prove. `V-P01` and `K-DST-TG-01` were free when this corpus
was written and were taken by the seed set (#296), which is what moved them
here. The two deliberate exceptions are rule 7's own cases — `K-MAT-02-copy.md`
and the `K-MAT-02` that does not bump its version — which need an id already in
the register to have anything to collide with.

`test_the_corpus_covers_every_numbered_rule` compares the directory names
against `RULES` in the validator. **The corpus is the test's data, not its
code:** a new rule is a new directory, and this test fails until one exists.

`test_the_ci_script_refuses_each_invalid_file` runs the same cases through the
CI script's `main()` and requires exit `1`.

**KR-00 is not one of the ten**, and is excluded from that coverage set
deliberately: it says the file could not be read as a register file at all —
there is no record to judge. It is proven separately by
`test_a_file_that_is_not_a_record_at_all_is_refused`,
`test_a_vocabulary_that_has_drifted_from_the_code_refuses_the_register` and
`test_a_register_that_is_not_there_is_refused`, and it stops a run exactly as
the ten do.

**2. "A valid corpus accepted."**
`SATISFIED`.

`tests/fixtures/knowledge_register/valid/` — a universal record
(`K-MAT-02`), a destination record (`K-DST-LI-03`, with `verified_on`), a
probe family (`K-TEMPT-01`, U-1), a hard check (`V-T01`, class `H`), a soft
check (`V-S10`, class `S`) and a client ladder
(`client/streams/weekly.md`, three levels each declaring its universal level).

`test_the_valid_corpus_is_accepted` asserts no findings, with a baseline
supplied, so rule 7's version half is in force rather than skipped.
`test_the_shipped_register_is_valid` and
`test_the_ci_script_accepts_the_shipped_register` assert the same for the
register the repository actually ships, which is what CI validates.

Acceptance is proven to be load-bearing rather than vacuous:
`test_a_check_may_reach_a_second_version` shows a legitimate version bump
passing, and `test_a_sound_client_ladder_has_no_problems` and
`test_a_feature_that_merely_contains_a_label_word_is_not_a_label` show the
two rules most likely to over-reach declining to fire.

**3. "Run-start validation failure produces the SKIP in a fixture run."**
`SATISFIED`.

`tests/test_294_run_start_validation.py`. `_FixtureRun` is not an engine and
holds no stage logic: it validates the register, and only if the gate lets it
start does it walk `CANONICAL_TOPOLOGY.stage_ids` and record what it executed.
"The run did not start" is therefore something the run *produces* — an empty
executed path — rather than a flag the test asserts about.

- `test_a_run_starts_on_a_valid_register` — the executed path is the whole
  canonical stage order, and there is no outcome and no reason.
- `test_a_broken_register_skips_the_signal_before_any_stage_runs` — over
  `rule_03_invariant_without_approval`, the executed path is empty and the
  single recorded outcome is `(signal, TerminalOutcome.SKIP_SIGNAL,
  knowledge_register_invalid)`. The decision's summary names `KR-03` and
  `approved_by`, so the record is fixed offline rather than guessed at.
- `test_no_invalid_file_lets_a_run_start` — the same, parametrised over
  **every** case of the invalid corpus.
- `test_a_register_that_is_not_there_stops_the_run_too` — a missing register
  is a refusal, not an empty one. Fail-closed.
- `test_the_reason_is_a_term_of_the_register_s_own_vocabulary` —
  `knowledge_register_invalid` is a term of `knowledge/vocab/reason_categories.md`,
  not a string invented in code. `KNOWLEDGE_REGISTER_INVALID` is defined in
  `src/knowledge/vocabulary.py`, beside the vocabulary it is mirrored against,
  so the two cannot drift apart.

The gate reads the register and nothing else — no stage, no configuration, no
weekday (`test_the_gate_reads_the_register_and_nothing_else`). Wiring it into
the scheduled entry points belongs with the loader that reads the register
into a run, in the slice that builds one; this issue delivers the gate and its
proof.

## In CI

`SATISFIED`, by the pytest suite **and** by a step of its own.

`.github/workflows/pr_tests.yml` runs the complete pytest suite for every pull
request targeting `main`, and `test_the_ci_script_accepts_the_shipped_register`
runs `main()` over the shipped `knowledge/` and `clients/` inside it. §8 asks
for validation on every change to `knowledge/` and to the client folders' rule
files; running on every pull request is a superset of that, and it cannot be
defeated by a path filter somebody later gets wrong.

That half alone was not enough. Rule 7's version-increase half needs the tree
as it was, a working tree is not one, and the script used to treat a baseline
it could not read as nothing to compare — so the documented invocation
enforced nine and a half of the ten rules while reporting ten (#328 review).
The workflow now also runs the script directly, against the branch the pull
request targets, with `fetch-depth: 0` so that ref exists:

```yaml
- name: Knowledge register (rules 1-10, versions against the base)
  env:
    PYTHONPATH: .
  run: |
    git fetch --no-tags --depth=1 origin "${{ github.base_ref || 'main' }}"
    python3 scripts/ci/check_knowledge_register.py \
      --baseline-ref "origin/${{ github.base_ref || 'main' }}"
```

It fails closed: a base ref it cannot read stops the job rather than passing.
`test_ci_runs_the_register_check_against_the_base_ref` holds that wiring in
place, because a check that CI stops asking for is a check that is gone.

The script is also runnable by hand, which is how a keeper checks an edit
before pushing it:

```
python3 scripts/ci/check_knowledge_register.py --baseline-ref origin/main
python3 scripts/ci/check_knowledge_register.py --baseline-ref HEAD
python3 scripts/ci/check_knowledge_register.py --no-baseline
```

`--baseline-ref` defaults to `origin/main`. `--no-baseline` is the only way to
skip rule 7's version half, and it says on stderr that it did — there is no
longer a spelling of this command that quietly checks less than it claims.

A refusal prints every finding, then the wording of each rule that fired, then
what it means: a run started on this register would `SKIP` at signal scope
with the reason `knowledge_register_invalid`. Fix the file, not the check.

## The one difference between the two callers

Rule 7 has a half no single tree can answer: whether `version` went up when
the body changed. That needs the tree as it was, so the CI script reads it
from git — every record in `<ref>:knowledge/`, by id, with the digest of the
surface a version bump has to cover. The register path is resolved against the
repository root first: `git ls-tree` matches nothing for a path outside the
checkout and returns success with no output, and an empty baseline reads as
"no record existed before", which passes everything.

At run start there is no earlier tree, so that half is CI's alone. Every other
rule is enforced identically in both places, because both call the same
`validate_register`.

**Without a baseline the half is skipped and said to be skipped.**
`test_a_baseline_ref_git_cannot_read_is_reported_rather_than_faked` gives the
script a ref git cannot read: it exits `0` and prints, to stderr, that rule 7's
version-increase half was **NOT** checked and that every other rule was. A
check that quietly compared a record with itself would report a clean tree it
never examined.
`test_without_a_baseline_the_version_half_is_not_invented` makes the same
point from the other side: `rule_07_version_did_not_increase` passes with no
baseline and is refused with one, and the test asserts both.

## Must preserve

- **Q1, human-editable.** The register is markdown a person opens, edits and
  puts back. The validator is the only thing that reads it strictly, and a
  refusal names the file, the line where it can, and the rule in §8's own
  wording. `knowledge/README.md` is written for that person, not for a caller.
- **I-10, no label conditions.** The grammar refuses a label term in
  `Applies when` however it is spelt — `material_label`, `strategy_label`, the
  label's own words as a bare term, either case
  (`test_a_label_is_refused_however_it_is_spelt`). The refusal cites I-10. It
  is scoped to whole words, so `feature real_scene is yes` remains a feature
  and the grammar does not lose a term it needs.
- **I-12, soft signals do not become thresholds.** A check carrying a
  `threshold` that is not `none` is refused unless `approved_by` names an owner
  and a date (`test_a_threshold_on_a_soft_check_needs_an_owner`; the refusal
  cites I-12). Rule 6 closes the other half: a soft check that routes anything
  at all is refused, because its results are hints and portfolio signals and
  never block.
- **I-13, research findings do not become hard checks.** `class: H` together
  with `evidence_class: RES` needs the owner's approval
  (`test_a_hard_check_drawn_from_research_needs_an_owner`; the refusal cites
  I-13). The invariant arm of the same rule is the corpus's
  `rule_03_invariant_without_approval`, and an `approved_by` without a date is
  refused too — it records who approved it *and when*.

The route table a check declares is compared against the stage-topology
registry (`src/editorial_core/topology.py`), not against a second copy of it —
one engine means one place that says what the engine is (CE-1). A route a check
invents, or a counter it spends that the route of record does not, is caught
against the same authority a run executes.

## Production safety

Files and CI only. Nothing here publishes, calls a provider or spends a model
call. One existing file changed: `src/strategy/client_contracts.py`, where
`plan_values("claim_strength_ceiling")` now strips the `→ universal level N`
declaration from each level before handing it to the Engine. The declaration is
about the level, not part of its name, so what a plan carries stays the wording
a person reads, and a contract that declares no mapping is unaffected
(`test_an_unannotated_ladder_passes_through_untouched`). `plan_slots` keeps the
line as written, which is what the validator reads it from. Nothing else in the
pipeline was touched.

The only run-facing effect is refusal — a register that does not validate stops
a run before any stage runs. That is fail-closed and needs no human during the
run (I-01): the broken record is fixed offline, and the next run reads it.
