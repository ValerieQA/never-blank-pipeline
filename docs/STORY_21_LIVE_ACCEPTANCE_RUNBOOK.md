# Story #21 — live acceptance runbook

Two consecutive live content runs, from two different current signals, with no
code repair between them.

This is an **operator procedure**, not an automated job. Nothing in the
pipeline executes it, and no code in this repository decides whether Story #21
passes. What the code provides is the evidence that makes the operator's claim
checkable: a run records which commit produced it and whether that checkout's
source was untouched (Issue #114).

Read this document end to end before starting. The freeze point in the middle
is the part that is easy to violate by reflex.

## 0. What acceptance actually claims

> The same code, unchanged, produced two complete Release 1 runs from two
> different current signals, and all four publications are publicly real.

Every rule below exists to keep one of those words honest — *same*, *unchanged*,
*different*, *complete*, *publicly real*.

## 1. Preconditions

- [ ] Issue #114 is merged and the exact accepted `main` SHA is recorded here
      in the closure comment.
- [ ] The working checkout is on that SHA.
- [ ] The tracked source is clean under the `tracked-source-v1` rule: no
      tracked file outside `reports/` and `data/` differs from `HEAD`.
      Untracked files are fine. **The test suite writes into tracked files
      under `reports/`** — if you have just run it, confirm the checkout still
      qualifies before starting.
- [ ] The full suite has been run and matches the accepted baseline exactly
      (`scripts/ci/check_test_baseline.py --baseline tests/accepted_full_suite_failures.txt`).
- [ ] Required credentials are present in the local environment and **never**
      printed to a terminal that will be pasted into GitHub, never written into
      the repository, and never committed.
- [ ] **Credential hygiene (prerequisite, not optional).** Long-lived PATs and
      API keys must not sit in plaintext project configuration. The token
      reported in `~/.claude/settings.json` must be revoked or rotated and the
      replacement moved to an appropriate secret mechanism before live
      execution. Do not open the file to read the value; rotate it.
- [ ] Two **different current** signals are selected, neither previously
      consumed in a way that invalidates a fresh run.
- [ ] The Wix and LinkedIn target identities are confirmed to be the intended
      production destinations.

If any box is unchecked, the sequence has not started.

## 2. Run A

1. Record the signal ID for Run A and the exact command executed.
2. Execute the canonical `CONTROLLED_LIVE` path — the normal entrypoint with
   no `--dry-run`. No custom flags invented for the occasion.
3. Do not edit, substitute, delete or hand-repair any canonical artifact,
   before, during or after the run.
4. Record the exact `run_id` the run reports.
5. Require an authoritative `run_report.json` in the run namespace. If none was
   written, the run is not acceptance evidence — investigate before doing
   anything else.
6. Verify provenance for the run (Story #16's verifier over the run namespace).
7. Confirm the report's `code_identity` is present, its `commit_sha` equals the
   accepted `main` SHA, and `tracked_worktree_clean` is `true`. If the identity
   is absent, the run does not qualify — do not reconstruct it by hand.
8. Verify the Wix publication publicly: open the recorded URL in a browser and
   confirm the post is live and is this run's article.
9. Verify the LinkedIn publication publicly. If the report carries a canonical
   URL, open it. If the URL is truthfully unavailable — a legitimate outcome
   under the accepted #108/#109 semantics — locate the post manually in the
   configured account and record the attestation described in §5.
10. Commit the run's canonical **non-secret** artifacts. Never commit API keys,
    tokens, credentials, or secret-bearing environment or configuration files.

## 3. Freeze point

Immediately after Run A succeeds:

- record the exact `HEAD` SHA;
- make **no** source, configuration or architecture change of any kind;
- apply **no** fixes, however small or obviously safe;
- perform **no** manual edit of any canonical artifact.

A change here does not merely weaken the evidence — it makes Run A and Run B
different experiments, which is precisely the thing Story #21 exists to rule
out. If any fix turns out to be required, see §6: the sequence resets.

Committing Run A's artifacts is permitted and expected, and it moves `HEAD`.
That is why the equality check in §5 compares the **`code_identity` recorded in
each run's own evidence**, not whatever `HEAD` happens to be later. Artifact
commits do not change the code that ran. Source commits do — and are forbidden
here.

## 4. Run B

1. Use a **different** current signal.
2. Verify before starting that the checkout still qualifies under
   `tracked-source-v1` and is on the same source commit as Run A. Run A's
   committed artifacts do not disqualify it; a modified source file does.
3. Execute the same canonical `CONTROLLED_LIVE` path, with the same accepted
   architecture and configuration policy.
4. Require an authoritative `run_report.json`.
5. Confirm `code_identity.commit_sha` equals Run A's recorded value.
6. Verify both channels publicly, exactly as in Run A.
7. Record the LinkedIn attestation if the canonical URL is unavailable.
8. Preserve and commit the canonical non-secret artifacts.

## 5. Closure

Story #21 closes only if **both** runs satisfy every criterion. Partial success
is not partial acceptance.

Post one closure comment on Issue #21 containing, **for each run**:

- `signal_id`;
- `run_id`;
- the exact code SHA from that run's `code_identity`;
- clean-worktree qualification (`tracked_worktree_clean`, and the
  `clean_policy` under which it was decided);
- the `run_report.json` evidence path;
- Wix external ID and public URL;
- LinkedIn external ID;
- LinkedIn public URL when available;
- otherwise the human public-verification attestation (below);
- the final status of each channel;
- an explicit confirmation that no artifact was manually substituted.

Then state the comparison outright:

> Run A `code_identity.commit_sha` == Run B `code_identity.commit_sha`

### LinkedIn human attestation

Required only when LinkedIn provides no canonical public post URL. It is
**acceptance evidence, not production provenance** — it is never written into a
run artifact, and it changes nothing about the #108/#109 URL semantics.

It must record at minimum:

- `run_id` and `signal_id`;
- the LinkedIn external/provider ID;
- the configured LinkedIn account identity;
- whether a canonical URL was available (here: no);
- an explicit statement that the post was manually located and publicly
  verified;
- the verifier's identity, through the GitHub account posting the attestation;
- the verification timestamp.

It must contain no secrets and no raw provider payloads.

## 6. Failure and reset semantics

If either run reveals a defect requiring any of:

- a source-code change;
- an architecture change;
- a configuration-contract change;
- a manual canonical-artifact substitution;

then **the current acceptance sequence is invalid**. Fix the defect separately
under its own task, merge it, re-verify, and restart from a **new Run A and a
new Run B**. A repaired sequence is not a sequence; it is the thing Story #21
says must not happen.

A transient provider failure that requires no code or artifact repair — a
timeout, a 5xx, a dropped connection — may be retried **only** where the
accepted retry/idempotency contract (#105 for Wix, #109 for LinkedIn) makes the
retry truthful. In that case:

- the retried run **still qualifies**, because no code changed and no artifact
  was substituted;
- the retry must go through the canonical entrypoint, not a hand-run publish;
- the closure comment must state that a retry occurred, on which channel, and
  what the resulting status was (`REUSED` and `PROVIDER_DUPLICATE` are
  meaningful outcomes here, and neither is a fresh publication).

Anything not covered by the two paragraphs above is a reset. Do not invent a
gentler reading of acceptance in the moment; that judgment is exactly what the
sequence is supposed to remove.

## 7. What this runbook does not do

It does not select the signals, execute the runs, or decide acceptance. It does
not add a LinkedIn confirmation artifact, a human approval workflow, or any new
provider integration. Release 1 uses the existing model-based editorial
acceptance and introduces no separate human approval gate, so Story #21's
*"human editorial approval, if used"* criterion is **not applicable** to this
sequence.
