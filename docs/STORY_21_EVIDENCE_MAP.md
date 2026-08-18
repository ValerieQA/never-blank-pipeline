# Story #21 evidence map — two consecutive live runs without code repair

Issue #114 is the deterministic half of this Story. Each criterion below is
exactly one of `SATISFIED-DETERMINISTIC` / `PENDING-LIVE` / `NOT-APPLICABLE`.

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
`PENDING-LIVE`. Same as criterion 1. Run isolation is deterministic — every run
has its own namespace and its own create-once artifacts — so two runs cannot
contaminate each other's evidence.

**3. "No source-code or architecture change occurs between Run A and Run B."**
`SATISFIED-DETERMINISTIC` **as a proof mechanism**; the claim itself is
`PENDING-LIVE`. Before Issue #114 this rested on operator testimony: no
artifact recorded which code ran. Each run now captures a `CodeIdentity` at run
start — the exact 40-character `HEAD` commit SHA and whether the tracked source
was clean — and persists it on `assignment.json`, the anchor Story #16 already
verifies the chain against. `run_report.json` carries it **read from that
verified anchor**, never re-derived at terminalization, so the report describes
the code that ran rather than the checkout as it stands when the report is
written. Comparing the two runs is then a comparison of two recorded values.

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

**6. "Both Wix and LinkedIn publications are publicly verifiable for both
runs."**
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
`PENDING-LIVE` **as a process**, with its semantics now written down rather
than improvised: `docs/STORY_21_LIVE_ACCEPTANCE_RUNBOOK.md` defines the freeze
point, what forces a full reset (any source, architecture, configuration or
artifact repair), and the single narrow case that does not — a transient
provider failure retried through the canonical entrypoint, where the accepted
#105/#109 idempotency contract makes the retry truthful.

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
`reports/`, and so does the test suite. A rule covering them would make the
two-run sequence impossible to execute: Run A would dirty the checkout by
finishing, and committing its artifacts to clean up would move `HEAD` — so Run
A and Run B could never share a commit SHA, breaking the very criterion this
mechanism exists to prove. What must not differ between the runs is the code
and configuration that decide behavior.

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
| Two live runs from two current signals completing the lifecycle | **live, pending** |
| Four publicly verifiable publications | **live, pending** |
| Run A SHA == Run B SHA, from the runs' own evidence | **live, pending** |
