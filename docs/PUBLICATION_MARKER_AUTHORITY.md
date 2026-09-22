# NB-00a evidence map — publication marker authority

Issue #287 (SL-0). The durable idempotency authority invariant **S3-I1**
requires: `docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md` §3.6,
`06_STEP5_MIGRATION_MAP.md` §1.1, `03_STEP2_STAGE_CONTRACTS.md` S-14 ARP.

Each acceptance criterion below is exactly one of `SATISFIED` /
`DEFERRED-LIVE` / `NOT DELIVERED`.

**Nothing in this document is evidence of a real external publication.** Every
deterministic proof comes from fake publishers; the one criterion that needs a
real run is marked and carries the dry-run equivalent instead.

## What was built

`src/publishing/publication_markers.py` — the authority, and nothing else. It
publishes nothing, authorizes nothing, and reads no credential.

```
data/editorial/publication_markers/<client>/<destination>/<key>.json
data/editorial/publication_markers/<client>/<destination>/<key>.intent.json
```

- **Identity key** = `(client, destination, sorted source signal IDs)`. No
  article digest: one publication per signal set per destination, the same
  semantics `data/research/published_signal_ids.txt` already has and stricter
  than the digest-based Wix key in `src/publishing/idempotency.py`.
  The file name is a readable prefix plus a SHA-256 of the canonical signal
  set, so a person can find a key by eye and two different sets can never
  collide.
- **The client** is the deployment's client directory name (`NB_CLIENT_DIR`,
  default `clients/never_blank`).
- **The store root** is `data/editorial/publication_markers`, redirectable with
  `NB_PUBLICATION_MARKERS_DIR` exactly as `NB_PACKAGES_DIR` redirects the run
  artefact root. It is un-ignored in `.gitignore` and carries a `.gitkeep`,
  because it is committed evidence, not runtime scratch.

The transaction, per destination:

| Step | Call | Refusal |
|---|---|---|
| 1. Lookup | `PublicationGuard.check` | marker → `REUSED`; intent without marker → `SKIP` (`publication_possibly_exists`); store unreadable or absent → `SKIP` (`idempotency_authority_unavailable`) |
| 2. Intent | `PublicationGuard.record_intent` | not durable → `SKIP` (`idempotency_authority_unavailable`); the external call is not made |
| 3. Call | the existing publisher | — |
| 4. Marker | `PublicationGuard.record_marker` | not durable → the key is listed under `publication_unconfirmed` in the run's evidence; the run ends normally and the next run skips the key |

Both files are written through a temp file + `fsync` + `os.replace` +
directory `fsync`, so a crash leaves a whole file or no file, never half of
one.

**Ambiguity resolves towards "possibly published".** A marker that cannot be
parsed still proves a successful publication happened, because nothing else
writes one. This is deliberately the opposite of `src/publishing/idempotency.py`,
where unusable evidence must never suppress an authorized publication: that
module asks *can I prove this was published?*, this one asks *can I prove it
was not?* At most once — a lost post is preferred to a duplicate.

Clearing an unconfirmed key is offline maintenance (I-02): a person deletes the
`.intent.json`. Nothing inside a run clears one by assumption.

## Where it is wired

Every current publishing path that can make an external call:

| Path | Destinations it can reach | Source of the key |
|---|---|---|
| `scripts/generate_and_publish.py` (Monday, Wednesday, research Fri/Sun) | Wix, LinkedIn | the run's `signal_id` |
| `scripts/research/publish_packages.py` (daily research Stage 11) | Release-1 scope of the six | `SIGNAL_ID` |
| `scripts/generate_and_publish_visibility.py` (Tue/Thu) | Release-1 scope of the six | `queue_item_id` |
| `scripts/publish.py` (legacy Friday, via `scheduled_publish.py`) | all six | `manual_topic_id` |

The store keys **all six** destination names; release scope still decides which
a run may publish to. A marker is evidence, not an authorization.

In the canonical entrypoint the authority is consulted **before** the existing
`find_prior_*` run-directory scan, because it is the authority that survives a
fresh checkout. Re-pointing `find_prior_*` onto the store is NB-00b and is
explicitly out of scope here; until then the two run in series and either one
alone can suppress a call, never authorize one. Both end in the same recorded
state, through one shared `_record_reuse` seam.

Two rules keep the authority from recording a rehearsal:

- **Only a live mode reaches it.** A dry run makes no external call, so an
  intent written by one would suppress the real publication that follows. The
  canonical entrypoint returns before the publication section in `--dry-run`;
  the visibility path skips ahead of the guard; `publish.py` and
  `publish_packages.py` build no guard unless the mode is `live`.
- **Only `PUBLISHED` earns a marker** (`proves_publication`). A Wix draft is
  not proof the article is live, and a marker written for one would suppress
  the real publication forever — the same rule
  `src/publishing/idempotency.py` already keeps for prior evidence.

## Acceptance evidence

**1. "Fault-injection test: destination A succeeds, destination B fails → a
second run does not republish A."**
`SATISFIED`.
`tests/test_publication_markers.py::test_a_partial_failure_never_republishes_what_already_succeeded`,
parametrised over all six destinations (each one as A, its neighbour as B). The
assertion is that the publisher is **not reached at all** on the second run, not
merely that the result is relabelled afterwards. A is `REUSED` with the external
ID and run the first run recorded; B is `SKIP` with
`publication_possibly_exists`, because a failed call can still have reached the
platform.
`tests/test_publication_markers.py::test_stage_11_partial_failure_does_not_republish_on_the_next_run`
proves the same scenario through the real `publish_packages` path, run twice
over the same signal: Wix published, LinkedIn failed, and the second run reaches
neither publisher.

**2. "Fault-injection test: crash after intent, before marker → the next run
treats the key as possibly published and skips (at most once)."**
`SATISFIED`.
`tests/test_publication_markers.py::test_a_crash_after_the_intent_makes_the_next_run_skip`,
parametrised over all six.
`…::test_a_marker_that_cannot_be_made_durable_leaves_the_key_suppressed` covers
the same state arrived at the other way — the post exists, the marker write
failed — and `…::test_an_unreadable_marker_never_becomes_a_licence_to_publish_again`
covers a marker that is present but corrupt.

**3. "Tests parametrised over all six destination names."**
`SATISFIED`. `DESTINATIONS` is composed from `R1_PUBLISH_CHANNELS +
NON_R1_PUBLISH_CHANNELS` rather than restated, so it cannot drift from the
release-scope lists. Five scenarios are parametrised over it, plus
`test_the_authority_covers_all_six_destinations` as the literal check.

**4. "One real run's trace shows intent and marker files committed, including
in a partial-failure case (or a documented dry-run equivalent)."**
`SATISFIED` by the accepted deterministic equivalent below. Only the "real run"
wording needs a live publication; everything the criterion is *about* — intent
and marker files **committed**, in a **partial-failure** case — is proven
against a real git repository and a real remote, with a fresh clone standing in
for the next runner:
`tests/test_287_marker_durability.py::test_a_later_destination_failing_does_not_strand_the_earlier_marker`.

### Dry-run equivalent

Deterministic, no credential and no network. Two runs of the real Stage 11 path
over one signal, Wix succeeding and LinkedIn failing:

```
python3 -m pytest tests/test_publication_markers.py \
  -k stage_11_partial_failure -q
```

The store after run 1 — a marker for the destination that succeeded, an intent
with no marker for the one that failed:

```
data/editorial/publication_markers/never_blank/wix/reg-test-0001-<digest>.json
data/editorial/publication_markers/never_blank/wix/reg-test-0001-<digest>.intent.json
data/editorial/publication_markers/never_blank/linkedin/reg-test-0001-<digest>.intent.json
```

Run 2 over the same signal reaches no publisher: `wix` is `REUSED`
(`external_id` from run 1), `linkedin` is `SKIPPED` with
`publication_possibly_exists`.

The same trace on a live canonical run is visible in the run's
`publication_results.json`, which now carries a `publication_unconfirmed` list
alongside `unusable_prior_publication_evidence`.

## Durability across runners

**The workflow step that commits the markers.** `SATISFIED`.

The store is written inside the publishing step — intent before each
irreversible call, marker immediately after that destination succeeds. On a
GitHub-hosted runner that working tree dies with the job, so until this landed
the authority was inert in CI: it could only ever refuse, never wrongly permit,
but it would not catch the partial-failure republication it was built for.

`scripts/ci/persist_publication_markers.sh` is the whole seam, wired into every
workflow that can publish: `monday_publish.yml`, `wednesday_golden.yml`,
`research_generate_and_publish.yml`, `visibility_publish.yml`,
`scheduled_publish.yml` and `daily_signal_research.yml`.

It is its own step, under `always()`, and that is the point. The existing
"mark signal as published" commits are guarded by `success()`, so a run whose
second destination fails commits nothing — and the marker of the destination
that *did* publish is exactly what has to survive that failure. It commits the
marker store and nothing else, and a dry run persists nothing: the workflow
guards it and the script checks `DRY_RUN` again itself, because the cost of
being wrong is a real publication suppressed by evidence of one that never
happened.

It is not a second idempotency architecture and it is not the learning ledger.
It persists the files the authority already writes.

Proven in `tests/test_287_marker_durability.py` against a real repository with a
real remote, a fresh clone standing in for the next runner:

| What | Test |
|---|---|
| a later destination failing does not strand the earlier marker | `test_a_later_destination_failing_does_not_strand_the_earlier_marker` |
| a fresh checkout refuses to republish | `test_a_fresh_checkout_refuses_to_republish_what_a_previous_run_published` |
| a crash after the claim survives to the next checkout | `test_a_crash_after_the_claim_survives_to_the_next_checkout` |
| a dry run persists nothing | `test_a_dry_run_persists_nothing` |
| only the store is committed | `test_the_script_persists_the_markers_and_nothing_else` |
| every publishing workflow persists, under `always()`, never `success()` | `test_every_publishing_workflow_persists_the_markers`, `test_the_persistence_step_survives_a_later_destination_failing` |

## One run wins a key

`record_intent` used to write the intent the way a marker is written — a temp
file renamed over the target. That is the right shape for a value being
replaced and the wrong one for a claim being taken: two runs that both read
"nothing published" would both rename their own intent into place, both believe
they may call, and both publish. `lookup` cannot see that case, because at the
moment both runs look there is nothing to see.

The claim is now an exclusive create. The filesystem decides which run wins,
and only the winner may make the external call. A run may re-record its own
claim — re-entry is not a race — and a claim that cannot be read is treated as
another run's, because a half-written claim is still a claim.

## A durability failure is never reported as success

A rename is not durable until the directory holding it is synced, and
`_fsync_dir` used to swallow that failure. An intent that vanishes after its
publication is exactly the double publication this store exists to prevent, so
the sync now reports its result, `_write_durably` carries it out to the caller,
and every directory the write had to create is synced too.

## Production safety

Additive. The authority can refuse a publication; it can never cause one. Every
refusal is a recorded `SKIP` or `REUSED` with a sanitized reason, never a wait
and never a silent omission. A path whose draft carries no source identity has
no key, so it publishes nothing — deliberate (S3-I1 rule 7: a destination may
have `mode = publish` only if an idempotency authority exists for it), and the
loudest way for an unidentifiable publication to surface.
