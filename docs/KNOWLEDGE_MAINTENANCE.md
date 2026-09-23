# NB-02d evidence map — expiry review happens when nothing is published

Issue #297 (SL-2), on top of NB-02a (#294, the register and its validator) and
NB-01d (#293, the durable ledger). Requires:
`docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §5 and §5.2 (patch
`PATCH_S4R1_STEP4.md`), and `04_STEP3_STORAGE_AND_RUN_TRACE.md` §3.2.

Each acceptance criterion below is exactly one of `SATISFIED` /
`NOT DELIVERED`.

## What was built

| Piece | Where |
|---|---|
| The KnowledgeQueueItem, and the `expiry_review` kind of it | `src/run/knowledge_queue.py` |
| The job: scan the register and the client rules, write the items | `src/knowledge/maintenance.py` |
| The entry point a schedule calls | `scripts/knowledge_maintenance.py` |
| A register whose dates make each §5 case happen | `tests/fixtures/knowledge_maintenance/` |
| The tests | `tests/test_297_knowledge_maintenance.py` |

Patch S4-R1 splits the producers of a queue item by kind, and §3.2 gives each
kind exactly one producer: S-15 writes `observation` and `vt02_feedback` items
from a finished run, and this job writes `expiry_review` items. The kind
vocabulary is in `knowledge_queue.py` and the producing is not — S-15's half
arrives with the slice that builds it, and neither producer can reach the
other's kind by accident.

**1. "A test fixture with an expired record creates exactly one queue item
across repeated job runs."**
`SATISFIED`.

`test_an_expired_record_makes_exactly_one_queue_item_across_repeated_runs`
runs the job three times over the fixture register — twice on the same day and
once nine days later — and asserts that the queue holds exactly one file for
`K-DST-FX-01`, that the second and third passes wrote nothing, and that the
listing of the queue directory is byte-identical to the one the first pass
left.

The mechanism is not a bookkeeping file that could drift from the queue.
An item's id is **derived** from the record and the `review_by` that lapsed
(`ExpiryReviewItem.identity_for`), and the ledger write is the repository's
create-once `link(2)` commit, so a second pass computes the same path and the
filesystem refuses it. Two overlapping passes therefore cannot both add the
same expiry, and neither can a pass that crashed after writing half its items.

Two further tests hold the halves that "exactly one" alone would not:

- `test_the_item_a_second_pass_did_not_write_is_the_one_the_first_wrote`
  reads the file before and after a later pass. Idempotency here is *nothing
  happened*, not *it was written again with the same contents* — the item still
  says it was raised on the day the review actually fell due.
- `test_a_review_the_keeper_moved_forward_is_a_new_expiry_and_a_new_item`
  copies the register, answers the item the way a keeper answers one (a new
  `review_by`), and shows the record drop out of the due set and come back as a
  **second** item when the new date falls due. One item per record per expiry is
  two statements, and this is the other one.

**2. "The job has no dependency on publications."**
`SATISFIED`.

§5.2: "It does not depend on a publication or a run happening, so expiry review
continues even when nothing is published." Proven twice, because the two claims
are different:

- `test_the_job_needs_only_a_register_and_a_date` drives the job with a
  register directory, a date and an empty ledger — no run summary, no
  fingerprint, no publication observation, no marker — which is what a month
  with nothing published leaves behind. Six reviews are still raised, and the
  ledger ends up holding queue items and nothing else.
- `test_neither_module_the_job_is_built_from_names_a_run_or_a_publication`
  checks both modules the job is made of for any reach into `src/publishing/`,
  the publication markers, the published index, the run workspace, the run
  manifest or the RunSummary. The second module is checked because a dependency
  that arrived through the record on its way to the ledger would be just as
  real as one in the job.

The run side of the split holds too, and was already true: the loader computes
§5 demotion for itself and writes no queue item (`src/knowledge/loader.py`,
`effective_status`). Nothing was added to it here.

## What the item says about a record, and why

§5 does three different things to an expired record, and the item records which
one happened rather than inviting the keeper to recompute it:

| The fixture record | File status | Effective status | Test |
|---|---|---|---|
| `K-DST-FX-01`, tier 4, review lapsed | `candidate` | `weak-candidate` | `test_an_expired_candidate_is_recorded_as_the_weak_candidate_it_became` |
| `K-DST-FX-02`, tier 1, review lapsed | `approved-rule` | `approved-rule` | `test_an_expired_hard_platform_rule_is_still_an_approved_rule` |
| `V-S01`, a check, review lapsed | `candidate` | `candidate` | `test_an_expired_check_keeps_its_rule_status` |
| `K-FX-04`, inside the warning window | `candidate` | `candidate` | `test_a_record_inside_the_warning_window_is_raised_before_it_expires` |
| `K-FX-05`, retired | — | not queued | `test_a_retired_record_is_not_asked_about` |

The check row is the one a shared code path would have got wrong: §5's table
demotes a `descriptive` or a `candidate` **record**, and gives check records
their own row — they keep their rule status and are flagged. An expired
candidate check is still a candidate check.

Client rules are scanned where they live (§1), and the item says `client`
rather than carrying the path: a path is the one free-text field such a record
could have, and a client's path names the client. The id and the source say
what the keeper needs, in terms the public ledger can hold (§3.3, P9).

## The warning window

§5.2 asks for "a warning window" before `review_by` and fixes no number, so
`DEFAULT_WARNING_DAYS` is 14 — a tunable parameter in the sense §5 gives the
periods themselves, and `--warning-days` on the entry point.
`test_the_window_decides_what_is_due` runs the scan at 0 and at 200 days and
watches the due set change, so the window is doing the deciding and not a
second rule hidden behind it.

Raising the item early is what makes one-per-expiry possible at all: an item at
the window and another one at the date would be two questions about one expiry.
The item carries `expired`, so the keeper can see which side of the date the
record is on.

## What this job never does

- **It changes no knowledge status.** The issue puts that out of scope and I-02
  puts it with the keeper, offline. `test_the_job_changes_no_knowledge_status`
  digests the fixture register before and after a pass.
- **It never runs inside a production run, and never blocks one.** It takes a
  register and a date; there is nothing in it for a run to wait on. A register
  file it cannot read is reported and stepped over
  (`test_a_file_it_cannot_read_is_reported_and_the_scan_goes_on`): refusing the
  whole pass is the validator's verdict, and one broken record silencing the
  review of every sound one would be the wrong failure for the part of the
  system whose job is to keep asking.
- **It does not commit unless asked.** `--commit` is off by default. Writing a
  record and committing it are separate steps because a commit can fail and a
  written record must not depend on one (Step 3 §3.1).

## What is not here

**The schedule itself.** The job is an entry point; nothing in this change adds
a workflow to run it, because the issue declares no containment for
`.github/workflows/`, and a job that widened its own permissions would be the
wrong thing to guess at. Wiring `scripts/knowledge_maintenance.py` into a daily
schedule is a one-file change to be made where the repository's other schedules
are, and until it is made, the job is run by hand:

```
python3 scripts/knowledge_maintenance.py --dry-run
python3 scripts/knowledge_maintenance.py --commit
```

Nothing about the queue depends on how often that happens. A pass that never
runs raises nothing; a pass that runs ten times raises what one pass would.

## Production safety

An offline job. It makes no model call, reads no provider, publishes nothing,
and touches no file of a run. The only thing it writes is one JSON record per
expiry under `data/editorial/knowledge_queue/`, and the only thing it reads is
markdown a keeper wrote.
