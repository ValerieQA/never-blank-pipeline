# Story #21 — live acceptance runbook

**One** successful canonical `CONTROLLED_LIVE` end-to-end run, from a fresh
current signal.

> **Superseding product decision (2026-08-18).** This Story originally required
> two consecutive runs (Run A and Run B) on a frozen commit. That criterion was
> **withdrawn by the product owner** — not satisfied. Release 1 acceptance is
> now one qualifying live run. A second run is not required: further executions
> occur naturally in continued operation, and any repeatability or
> environment-specific defect will be handled from real evidence rather than by
> blocking Release 1 on a two-run ceremony.
>
> Nothing in this document claims two runs occurred. The sections below describe
> the single acceptance run.

This is an **operator procedure**, not an automated job. Nothing in the
pipeline executes it, and no code in this repository decides whether Story #21
passes. What the code provides is the evidence that makes the operator's claim
checkable: a run records which commit produced it and whether that checkout's
tracked source was untouched (Issue #114).

Read this document end to end before starting. The freeze rule in §3 is the
part that is easy to violate by reflex, and violating it invalidates the
sequence rather than merely weakening it.

## 0. What acceptance actually claims

> A fresh current signal went through the complete Release 1 lifecycle on
> recorded code, and both publications are publicly real.

Every rule below exists to keep one of those words honest — *fresh*, *complete*,
*recorded*, *publicly real*.

### What code identity still does

`code_identity` (Issue #114) remains part of the evidence: the run records the
exact commit that produced it and whether the tracked source matched that
commit under `tracked-source-v1`. With the two-run requirement withdrawn there
is no cross-run SHA equality to prove, so the frozen-SHA discipline and the
between-runs commit freeze are **withdrawn with it**. What remains is the
single-run claim: *this* run names the code that produced it, and says whether
that checkout's behavioral source was untouched.

`tracked-source-v1` still ignores the pipeline's own output roots (`reports/`,
`data/`), because a run's own generated artifacts are output, not code repair.

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
- [ ] One **fresh current** signal is available from the canonical research
      path, `RECOMMENDED_FOR_ARTICLE`, not already consumed. An unused
      historical queue entry is not a current signal.
- [ ] The Wix and LinkedIn target identities are confirmed to be the intended
      production destinations.
- [ ] The execution environment is decided and can **preserve the run's
      canonical artifacts**. A run whose evidence is destroyed with its runner
      cannot be verified, and an unverifiable publication is not acceptance.

If any box is unchecked, the sequence has not started.

## 2. Record the execution commit

Before the run, record the exact commit it will execute:

```
git rev-parse HEAD
```

This is not a freeze — with the two-run requirement withdrawn nothing needs to
stay pinned. It is recorded so the closure evidence can be compared against the
`code_identity.commit_sha` the run writes for itself, confirming the account
describes the code that actually ran.

## 3. The acceptance run

1. Record the signal ID and the exact command executed.
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
   commit recorded in §2, and `tracked_worktree_clean` is `true`. If the
   identity is absent, the run does not qualify — do not reconstruct it by hand.
8. Verify the Wix publication publicly: open the recorded URL in a browser and
   confirm the post is live and is this run's article.
9. Verify the LinkedIn publication publicly. If the report carries a canonical
   URL, open it. If the URL is truthfully unavailable — a legitimate outcome
   under the accepted #108/#109 semantics — locate the post manually in the
   configured account and record the attestation described in §6.

**Preserve the canonical artifacts.** The run namespace
`reports/content_packages/<signal_id>/runs/<run_id>/` is the acceptance
evidence. If the run executes on a hosted runner, the namespace must be
uploaded or committed before the runner is destroyed — a real publication whose
evidence is gone cannot be verified, and cannot close this Story.

## 4. Verification and closure

Story #21 closes only if the single run satisfies **every** criterion. Partial
success is not partial acceptance: a Wix publication without a truthful
LinkedIn result, or a real publication without verifiable canonical evidence,
does not close this Story.

The acceptance proof is:

- `code_identity` is present, and its `commit_sha` equals the commit recorded
  in §2;
- `tracked_worktree_clean == true` under `tracked-source-v1`;
- Story #16 provenance verification passes over the exact run namespace;
- `run_report.json` exists, validates, and is honestly marked complete.

Post one closure comment on Issue #21 containing:

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

The canonical **non-secret** artifacts of the run are preserved in GitHub as
the acceptance record. Never commit API keys, tokens, credentials, or
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

## 5. Failure semantics

The acceptance attempt is **invalid** — and a new run is required — if it
needed any of:

- a source-code change;
- an architecture change;
- a configuration-contract change;
- a manual canonical-artifact substitution.

Fix whatever needs fixing under its own task, merge it, re-verify, then execute
a fresh acceptance run on the merged code. A run that had to be repaired
mid-flight is not acceptance evidence: *"no code repair"* is the claim, so
patch-and-continue would defeat the point. **A failed live run is evidence, not
permission to modify the system quietly.**

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

## 6. What this runbook does not do

It does not select the signal, execute the run, or decide acceptance. The
deterministic code only records trustworthy evidence; the acceptance judgment
is the operator's, made here. It adds
no LinkedIn confirmation artifact, no human approval workflow, and no new
provider integration. Release 1 uses the existing model-based editorial
acceptance and introduces no separate human approval gate, so Story #21's
*"human editorial approval, if used"* criterion is **not applicable** to this
sequence.
