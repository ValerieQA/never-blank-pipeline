# Story #21 evidence map — one live acceptance run without code repair

Issue #114 is the deterministic half of this Story. Each criterion below is
exactly one of `SATISFIED-DETERMINISTIC` / `PENDING-LIVE` / `NOT-APPLICABLE` /
`WITHDRAWN`.

> **Superseding product decision (2026-08-18).** The two-run criterion (Run A
> and Run B on a frozen commit) was **withdrawn by the product owner**. It was
> *not* satisfied, and no second run occurred or is claimed. Release 1
> acceptance is now **one** successful canonical `CONTROLLED_LIVE` end-to-end
> run. Criteria that existed only to serve the second run are marked
> `WITHDRAWN` below; every other guarantee is unchanged.

**Story #21 is not complete, and deterministic tests cannot complete it.** This
document exists so that when the live sequence is run, the only open questions
are the live ones.

## Criterion map

**1. "Run A starts from a current signal and completes the full Release 1
lifecycle."**
`PENDING-LIVE`. Every stage of the lifecycle is code-complete and verified
deterministically (Stories #9–#20), and the canonical `CONTROLLED_LIVE` path
exists and is exercised by the entrypoint suites. Whether a *particular current
signal* completes it against real providers is exactly what the live run
establishes.

**2. "Run B starts from a different current signal and completes the same
lifecycle."**
`WITHDRAWN`. Removed as an acceptance requirement by the product decision above.
No second run occurred, and none is claimed. Run isolation remains
deterministic — every run has its own namespace and its own create-once
artifacts — so later operational runs cannot contaminate the accepted run's
evidence.

**3. "No source-code or architecture change occurs between Run A and Run B."**
`WITHDRAWN` **as a cross-run requirement** — there is no second run to compare
against. What survives, and remains `SATISFIED-DETERMINISTIC`, is the
single-run form: the run names the code that produced it. Before Issue #114 this rested on operator testimony: no
artifact recorded which code ran. Each run now captures a `CodeIdentity` at run
start — the exact 40-character `HEAD` commit SHA and whether the tracked source
was clean — and persists it on `assignment.json`, the anchor Story #16 already
verifies the chain against. `run_report.json` carries it **read from that
verified anchor**, never re-derived at terminalization, so the report describes
the code that ran rather than the checkout as it stands when the report is
written. The closure evidence therefore names the exact commit that produced
the accepted run, checked against the commit recorded before execution. The
frozen-SHA discipline and the between-runs commit freeze are withdrawn together
with the second run; they existed only to make two runs comparable. Story #21
remains an acceptance procedure — the deterministic code records trustworthy
evidence, it does not judge acceptance.

**4. "No research, article, visual, decision, readiness, provenance, or report
artifact is manually substituted."**
`SATISFIED-DETERMINISTIC`. Create-once atomic writes make substitution
detectable rather than merely forbidden: canonical artifacts cannot be
overwritten, a swapped artifact breaks the digest chain, and `run_report`
fails closed over corrupt or foreign evidence instead of producing an
authoritative account (Stories #16, #20).

**5. "Human editorial approval, if used, is explicit and recorded."**
`NOT-APPLICABLE`. Release 1 introduces no separate human approval gate; the
canonical model-based editorial acceptance (Story #13, Issue #89) remains the
Release 1 behavior, and no approval workflow was built. The criterion is
conditional and its condition is not met.

**6. "Both Wix and LinkedIn publications are publicly verifiable."**
`PENDING-LIVE`. Deterministically, the results are already truthful rather than
merely present: a publication is recorded only with a real provider identifier,
URLs carry an explicit `UrlProvenance`, and LinkedIn has no locally-derived URL
form by design (Stories #18, #19). A real LinkedIn publication may therefore
legitimately carry `url = null` with provenance `unavailable`. Where that
happens, public verification is a **human attestation recorded in Issue #21**
per the product-owner decision — deliberately *not* a new run-scoped artifact,
because acceptance evidence and production provenance are different things.
The required attestation fields are in the runbook.

**7. "Both validation reports prove same-run lineage."**
`SATISFIED-DETERMINISTIC`. `verify_run_provenance` (Story #16) proves the chain
from the intake anchor forward, and `run_report.json` (Story #20) is an
authoritative account that refuses to exist over contradictory evidence. Both
were verified before this Story and are unchanged by Issue #114 apart from the
authorized identity addition.

**8. "Failures are fixed before restarting the two-run acceptance sequence."**
`PENDING-LIVE` **as a process**, in its single-run form: a run that required a
source, architecture, configuration or artifact repair to complete is not
acceptance evidence — the fix lands under its own task and a fresh run follows
on the merged code. *"No code repair"* is the claim, so patch-and-continue
would defeat it. The single narrow exception is a transient provider failure
retried through the canonical entrypoint, where the accepted #105/#109
idempotency contract makes the retry truthful.

## How the hosted acceptance run preserves its evidence

The live acceptance run executes on GitHub Actions, where the existing
repository secrets are already available — production credentials are not
copied to a local machine for it.

A hosted runner is destroyed when the job ends, and with it the canonical run
namespace `reports/content_packages/<signal_id>/runs/<run_id>/`. A real
publication whose evidence is gone cannot be verified by Story #16 provenance,
cannot be validated as a Story #20 report, and cannot close this Story — so the
workflow uploads that namespace as a **GitHub Actions artifact**
(`run-evidence-<signal_id>`) as the last step after the canonical execution
attempt.

Three properties make it evidence rather than a convenience:

- **The path follows production, it does not restate it.** `run_id` is
  generated inside the process and is never knowable in advance, so the upload
  is scoped by the signal the run was launched with — `<signal_id>/runs/` —
  and no marker file or log scraping introduces a second source of truth.
- **Evidence never vetoes bookkeeping.** The upload runs *after*
  `Mark signal as published`, which is guarded by `success()`. In front of it,
  an upload failing for an unrelated artifact-service reason would silently
  skip the record of a publication that really happened, leaving a later run
  free to treat an already-published signal as unconsumed. Running last, with
  `always()`, it preserves evidence without being able to suppress anything.
- **Failed and blocked attempts are preserved too** (`if: always()`). A blocked
  preflight or a failed publication is Story #21 evidence, and Story #20 writes
  `run_report.json` on those paths; uploading only on success would discard
  exactly the runs that matter most. A run that legitimately stopped early
  keeps only the artifacts appropriate to its terminal stage — none are
  manufactured.
- **Secrets cannot enter it.** The step declares no environment and
  interpolates no secret; the path cannot reach `.env` or the repository root;
  and the canonical artifacts are already forbidden by the Stories #16–#20
  trust boundary from carrying credentials, tokens, raw provider payloads,
  prompts or exception dumps.

Artifacts are **not** committed to `main` before verification. The closure
record is the verified evidence published to Issue #21, not the artifact
itself.

## The code-identity contract

| field | meaning |
|---|---|
| `commit_sha` | the exact `HEAD` commit, 40 lowercase hex; abbreviated or upper-case values are rejected |
| `tracked_worktree_clean` | whether the tracked source matched `HEAD` under `clean_policy` |
| `clean_policy` | the rule the flag was decided by — currently `tracked-source-v1` |

**Absence means "not proven", and fails closed.** A run outside a Git checkout,
or one where `git` cannot be executed, records no identity rather than a
fabricated one, and does not qualify as Story #21 acceptance evidence. Runs
recorded before this contract read the same way, which is correct: they
genuinely cannot prove their code identity. Qualification is *derived*
(`qualifies_for_live_acceptance`), never stored, so no summary boolean can
drift from the fields it summarizes.

**Why the policy is named in the artifact.** `tracked-source-v1` means: no
tracked file outside the pipeline's own output roots (`reports/`, `data/`)
differs from `HEAD`. Recording the rule's name beside the flag means a future
change to the exclusion set cannot silently rewrite the meaning of an
already-persisted `true`.

**Why output roots are excluded at all.** A run writes into tracked files under
`reports/`, and so does the test suite. Those writes are the pipeline's own
output, not a modification of the code that produced them, so counting them as
"dirty" would misreport every completed run as non-qualifying. What must not
differ from `HEAD` is the code and configuration that decide behavior.

**The exclusion is about working-tree changes, never about commits.** Because
`commit_sha` is the exact `git rev-parse HEAD`, any commit — including an
artifact-only or automated one under `reports/` or `data/` — produces a
different identity. That distinction drove the frozen-SHA discipline while two
comparable runs were required. With the second run withdrawn there is no
cross-run comparison to protect, and the freeze is withdrawn with it; the
cleanliness rule itself is unchanged.

**What is deliberately not captured**: no branch, remote, author, message or
diff; no environment values; no build, deployment or platform metadata. This is
not a build-metadata system, and Issue #114 did not introduce one.

## Deterministic vs live

| Evidence | Kind |
|---|---|
| Exact `HEAD` SHA captured at run start, read-only and local | deterministic (#114) |
| Identical checkout → identical identity; changed `HEAD` → different identity | deterministic (#114) |
| Modified tracked source disqualifies; untracked files do not | deterministic (#114) |
| Unresolvable repository yields absence, never a fabricated SHA | deterministic (#114) |
| Identity persisted on the verified anchor and propagated to the report | deterministic (#114) |
| An artifact-only commit changes `commit_sha` (why identity is recorded, not inferred) | deterministic (#114) |
| One live run from a fresh current signal completing the lifecycle | **live, pending** |
| Two publicly verifiable publications (Wix + LinkedIn) from that run | **live, pending** |
| The run's own `code_identity.commit_sha` matching the commit it executed | **live, pending** |
| A second consecutive run on the same commit | **withdrawn** |
