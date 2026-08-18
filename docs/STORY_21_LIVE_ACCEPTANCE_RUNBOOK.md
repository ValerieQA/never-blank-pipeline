# Story #21 — live acceptance runbook

Two consecutive live content runs, from two different current signals, with no
code repair between them.

This is an **operator procedure**, not an automated job. Nothing in the
pipeline executes it, and no code in this repository decides whether Story #21
passes. What the code provides is the evidence that makes the operator's claim
checkable: a run records which commit produced it and whether that checkout's
tracked source was untouched (Issue #114).

Read this document end to end before starting. The freeze rule in §3 is the
part that is easy to violate by reflex, and violating it invalidates the
sequence rather than merely weakening it.

## 0. What acceptance actually claims

> The same code, unchanged, produced two complete Release 1 runs from two
> different current signals, and all four publications are publicly real.

Every rule below exists to keep one of those words honest — *same*, *unchanged*,
*different*, *complete*, *publicly real*.

### Two separate guarantees that must not be conflated

The mechanism answers two different questions, and acceptance needs both:

| question | answered by |
|---|---|
| Were tracked behavioral source or configuration files modified in the checkout? | `tracked_worktree_clean` under `tracked-source-v1` |
| Did both runs start from the exact same repository commit? | equality of `code_identity.commit_sha` |

`tracked-source-v1` deliberately ignores the pipeline's own output roots
(`reports/`, `data/`), so a run's generated artifacts do not make the next run
non-qualifying. That exclusion is about *working-tree changes only*. It says
nothing about commits: **committing anything, including generated artifacts,
moves `HEAD` and therefore changes the recorded identity.** Cleanliness
exclusions never substitute for commit-identity equality.

## 1. Preconditions

- [ ] Issue #114 is merged and the exact accepted `main` SHA is recorded in the
      closure comment.
- [ ] The working checkout is on that SHA.
- [ ] The tracked source is clean under `tracked-source-v1`: no tracked file
      outside `reports/` and `data/` differs from `HEAD`. Untracked files are
      fine. **The test suite writes into tracked files under `reports/`** — if
      you have just run it, confirm the checkout still qualifies.
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
- [ ] Any automation that writes to this repository is understood: automated VI
      publishing commits to `data/` and report artifacts. Those commits move
      `HEAD` like any other. Either they are paused for the duration of the
      sequence, or the sequence is executed knowing that such a commit landing
      on the working branch between the runs forces a restart (§6).

If any box is unchecked, the sequence has not started.

## 2. Freeze the acceptance SHA

Immediately before Run A, record the exact commit the sequence is anchored to:

```
git rev-parse HEAD
```

Write that 40-character SHA down. It is the **frozen acceptance SHA** for the
whole sequence, and every later check refers to it.

From this moment until Run B has completed and its evidence has been verified,
**no commit of any kind may be made on the working branch** — not a source
commit, not a configuration commit, not a documentation commit, not a merge,
and not a commit containing only generated artifacts under `reports/` or
`data/`.

## 3. Run A

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
   **frozen acceptance SHA**, and `tracked_worktree_clean` is `true`. If the
   identity is absent, the run does not qualify — do not reconstruct it by hand.
8. Verify the Wix publication publicly: open the recorded URL in a browser and
   confirm the post is live and is this run's article.
9. Verify the LinkedIn publication publicly. If the report carries a canonical
   URL, open it. If the URL is truthfully unavailable — a legitimate outcome
   under the accepted #108/#109 semantics — locate the post manually in the
   configured account and record the attestation described in §6.

**Do not commit anything.** Run A's generated artifacts stay as working-tree
changes; `tracked-source-v1` excludes those output roots precisely so that they
can. Committing them here would move `HEAD` and make the same-SHA proof in §5
impossible to satisfy.

## 4. Between the runs — the freeze rule

Between Run A and Run B:

- make **no** source, configuration or architecture change;
- apply **no** fixes, however small or obviously safe;
- perform **no** manual edit of any canonical artifact;
- make **no commit at all**, including artifact-only commits;
- allow no automation to push or commit onto the working branch.

Before starting Run B, check the anchor is intact:

```
git rev-parse HEAD
```

It must still be **exactly** the frozen acceptance SHA. If it is not — for any
reason, by anyone, including an automated commit touching only `data/` or
`reports/` — the sequence is invalid and restarts from a new Run A (§6). Do not
attempt to reason that a changed `HEAD` was "only artifacts": the contract uses
exact commit identity on purpose, and a changed `HEAD` is a changed identity.

Working-tree changes under `reports/` and `data/` left by Run A are expected
and are **not** a violation. Commits are.

## 5. Run B

1. Use a **different** current signal.
2. Verify `git rev-parse HEAD` still equals the frozen acceptance SHA, and that
   the checkout still qualifies under `tracked-source-v1`. Run A's uncommitted
   output does not disqualify it; a modified tracked source file does.
3. Execute the same canonical `CONTROLLED_LIVE` path, with the same accepted
   architecture and configuration policy.
4. Require an authoritative `run_report.json`.
5. Confirm `code_identity.commit_sha` equals the frozen acceptance SHA and
   `tracked_worktree_clean` is `true`.
6. Verify both channels publicly, exactly as in Run A.
7. Record the LinkedIn attestation if the canonical URL is unavailable.
8. **Still do not commit.** Artifacts are committed only after the acceptance
   decision in §6.

## 6. Verification, closure, and only then committing

Story #21 closes only if **both** runs satisfy every criterion. Partial success
is not partial acceptance.

The acceptance proof is four checks, all required:

- Run A `code_identity.commit_sha` == frozen acceptance SHA;
- Run B `code_identity.commit_sha` == frozen acceptance SHA;
- Run A `code_identity.commit_sha` == Run B `code_identity.commit_sha`;
- both runs have `tracked_worktree_clean == true` under `tracked-source-v1`.

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

Then state the comparison outright, naming the frozen acceptance SHA:

> Run A `code_identity.commit_sha` == Run B `code_identity.commit_sha` ==
> frozen acceptance SHA

**Only after that verification** may the canonical **non-secret** artifacts from
Run A and Run B be committed — both runs together, in one step, after the
acceptance decision. Never commit API keys, tokens, credentials, or
secret-bearing environment or configuration files.

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

## 7. Failure and reset semantics

The sequence is **invalid and restarts from a new Run A** if any of these occur
between the freeze in §2 and the verification in §6:

- a source-code change;
- an architecture change;
- a configuration-contract change;
- a manual canonical-artifact substitution;
- **any commit on the working branch**, including an artifact-only or
  automated one;
- any other movement of `HEAD` away from the frozen acceptance SHA.

Fix whatever needs fixing under its own task, merge it, re-verify, then start a
new sequence with a new frozen SHA, a new Run A and a new Run B. A repaired
sequence is not a sequence; it is the thing Story #21 says must not happen.

A transient provider failure that requires no code or artifact repair — a
timeout, a 5xx, a dropped connection — may be retried **only** where the
accepted retry/idempotency contract (#105 for Wix, #109 for LinkedIn) makes the
retry truthful. In that case:

- the retried run **still qualifies**, because no code changed, no artifact was
  substituted, and `HEAD` did not move;
- the retry must go through the canonical entrypoint, not a hand-run publish;
- the closure comment must state that a retry occurred, on which channel, and
  what the resulting status was (`REUSED` and `PROVIDER_DUPLICATE` are
  meaningful outcomes here, and neither is a fresh publication).

Anything not covered by the two paragraphs above is a reset. Do not invent a
gentler reading of acceptance in the moment; that judgment is exactly what the
sequence is supposed to remove.

## 8. What this runbook does not do

It does not select the signals, execute the runs, or decide acceptance. No
production code compares Run A with Run B — the deterministic code only records
trustworthy evidence, and the comparison is the operator's, made here. It adds
no LinkedIn confirmation artifact, no human approval workflow, and no new
provider integration. Release 1 uses the existing model-based editorial
acceptance and introduces no separate human approval gate, so Story #21's
*"human editorial approval, if used"* criterion is **not applicable** to this
sequence.
