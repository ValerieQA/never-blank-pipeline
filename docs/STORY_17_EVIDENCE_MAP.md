# Story #17 evidence map — deterministic publication package and fail-closed preflight

Issues #100 (canonical packages) and #101 (preflight). This document maps
every Story #17 acceptance criterion to its implementation evidence so the
closure is auditable without chat history. Each criterion is exactly one of:
`SATISFIED` / `SUPERSEDED` / `DEFERRED`.

## Criterion map

**1. "Normalized Wix and LinkedIn package schemas are documented and tested."**
`SATISFIED` (#100). Evidence: `src/publishing/package.py` —
`WixPublicationPackage` / `LinkedInPublicationPackage`, strict
(`extra="forbid"`) and frozen, run-bound, channel-specific, composed only
from canonical accepted artifacts, with non-secret
`WixPublicationTarget` / `LinkedInPublicationTarget`. Deterministic
`package_digest()` (sha256 over canonical JSON bytes). Tests:
`tests/test_publication_package.py` (27), `tests/test_publication_target_binding.py` (9).

**2. "Preflight verifies required fields, same `run_id`, strategy version,
readiness, visuals, credentials, target configuration, policy, and freshness."**
Split by element:
- *Required fields, visuals* — `SATISFIED`: enforced by the #100 strict
  models at construction (required Wix cover; LinkedIn visual per Story #15
  semantics); preflight records package validity and binds to the digest
  rather than re-implementing the rules.
- *Same `run_id`* — `SATISFIED` (#101): shared check that both packages
  belong to the run under evaluation (`run_blocked`), on top of the
  construction-time binding in #100 and the whole-run verification in #98.
- *Strategy version, target configuration, freshness* — `SATISFIED` using
  the rules that actually exist: `generated_at >= active_strategy.started_at`,
  `strategy_id`/`strategy_version` equality, `ConfigurationIdentity` equality
  across package/active/source snapshot, `freshness.retrieved_not_before` on
  reloaded research, per-channel strategy-view identity checks. Recorded in
  `preflight_result.freshness` and `configuration_consistent`.
- *Readiness* — `SATISFIED`: the canonical readiness gate remains, and after
  #101 it is fail-closed with no bypass (see criterion 4).
- *Credentials* — `SATISFIED` (#101): presence-only readiness per channel
  (`NB_WIX_API_KEY`, `NB_ZERNIO_API_KEY`) hoisted before publisher
  construction; recorded as a boolean, never a value.
- *Policy* — `SUPERSEDED`/`DEFERRED`: no generalized policy engine exists in
  the product, and none was invented. The deterministic rules that exist are
  the strategy-lineage and configuration rules listed above; anything broader
  implied by the original wording is deferred to a future product decision.

**3. "Invalid, incomplete, stale, cross-run, or unapproved packages cannot
call external publishers."**
`SATISFIED` (#98 + #100 + #101). `evaluate_publication_preflight` runs after
package construction and before any external effect; a run-level BLOCK
prevents both publishers from being constructed, a channel-level BLOCK
prevents that channel's publisher. The verdict is persisted before the first
allowed call, and the entrypoint asserts the package digest still equals the
recorded verdict before invoking each publisher. Tests:
`tests/test_publication_preflight.py` (32, incl. end-to-end zero-call proofs).

**4. "Overrides require explicit authorization metadata and audit evidence."**
`SUPERSEDED` by the Release 1 product decision recorded on Issue #101.
Inspection established that no trustworthy authorization identity exists
anywhere in the current architecture: `force_override` is a bare boolean
derived from `FORCE_PUBLISH_OVERRIDE` / `APPROVED_OVERRIDE` in the signal
record, `APPROVED_OVERRIDE` originates from a Google Sheets edit synced by
`scripts/research/sync_from_sheets.py`, which records no editor identity, no
timestamp, and no bound reason. Rather than inventing IAM/RBAC or
synthesizing a self-asserted actor, **Release 1 has no authorized bypass**:
an override never converts BLOCK into ALLOW, and the preflight artifact
records only `override_state ∈ {none, attempted_rejected}`. The artifact
deliberately has **no** `authorized_by` field and claims no human actor. The
previous silent readiness bypass in the canonical entrypoint is removed.
Real override authorization remains a separate post-R1 product decision.

**5. "Preflight produces a preserved per-channel result."**
`SATISFIED` (#101): run-scoped create-once `preflight_result.json`
(`PreflightResult`, strict/frozen/reloadable) carrying schema version, run and
signal identity, authoritative configuration identity, `evaluated_at`,
`override_state`, provenance verdict, readiness verdict, freshness verdict,
run disposition with machine-readable reasons, and per-channel verdicts
(channel, exact `package_digest`, non-secret target, package validity,
optional construction-failure reason, credential readiness, `ALLOW`/`BLOCK`,
blocking reasons). No secrets, tokens, raw provider objects, or adapter
responses are persisted.

The preflight is the **single publication-authorization boundary**: every
decision inside Story #17's authorization model is explained by the preserved
verdict, and no publication decision is taken before the artifact exists.
Concretely:

- *Readiness* is evaluated as a shared check and its stop persists the verdict
  (run-level `readiness_failed`, both channels blocked, zero publisher calls)
  before the run ends. An override attempted against it is recorded as
  `attempted_rejected` in that same artifact — the rejection that motivated
  the audit requirement is canonical run evidence, not a console message.
- *Channel packages are constructed independently*, so a channel-local package
  or target failure is a typed channel BLOCK (`package_invalid` /
  `target_missing`) while a valid channel still publishes. A channel whose
  canonical package could not be constructed carries **no** digest and **no**
  target — a digest is never fabricated — and the strict model enforces that
  an `ALLOW` always carries a real digest and target.
- *Construction failures carry their scope*. The #100 builders enforce two
  different classes of invariant, so `PublicationPackageError` now carries a
  typed `PackageFailureCategory`: `TARGET` and `CHANNEL_PACKAGE` are
  channel-scoped, while `CONFIGURATION`, `PROVENANCE` and `LINEAGE` are
  run-scoped. A run-scoped construction failure — authoritative configuration
  drift, cross-run or cross-signal substitution of the generated artifact,
  visual passport or LinkedIn composition, and accepted-article ↔ visual ↔
  composition digest corruption — blocks **every** channel
  (`configuration_mismatch` / `run_evidence_inconsistent`) even when the other
  channel's package builds perfectly. Scope is read from the typed category,
  never inferred from exception message text.

**6. "Fake-client tests prove zero external calls after a blocked preflight."**
`SATISFIED` (#101): deterministic fake transports prove zero calls for
corrupted provenance, configuration mismatch, failed freshness, missing Wix
credential, missing LinkedIn credential, missing both, override attempt on a
blocking condition, and an unready signal with an override attempt — plus
per-channel isolation (one channel blocked, the other still publishes) and
proof that no publication evidence or history is fabricated for a blocked run.

## Superseded / clarified original wording

- **"Required visual failures can degrade to warnings or skipped visual
  publication"** — `SUPERSEDED` by Story #15 / Issue #96: the visual contract
  gate is fail-closed on both branches; after #100 the Wix package cannot even
  be constructed without a valid required cover, making the adapter's legacy
  no-cover branch unreachable from the canonical boundary.
  **Scope boundary preserved by #101**: the Wix *visual* requirement remains
  an upstream Story #15 **shared** invariant — a run without a valid Wix
  visual never reaches publication packaging at all, and that was deliberately
  not reclassified as channel-local. What #101 treats as channel-local is the
  channel's own **publication package/target** state (for example an unusable
  Wix site/member identity or an unusable LinkedIn account identity), which is
  exactly what the strict #100 target models reject at construction.
- **"Preflight does not deterministically verify same-run ownership"** —
  re-evaluated after Story #16 rather than re-implemented: ownership is proven
  by `verify_run_provenance` (#98), which #101 now invokes at the publication
  boundary. No provenance logic was duplicated.
- **"There is no single normalized, immutable package contract carrying
  complete lineage"** — satisfied in the corrected form: the package carries
  the lineage needed to identify the exact side effect (run, signal,
  configuration, accepted-article digest, target) while full run lineage
  remains in the canonical run artifacts verified by #98. The package is
  deliberately not a copy of all upstream evidence.
- **"Credential/config validation is deferred into adapters"** — corrected:
  credential *readiness* is now a preflight verdict; adapters still read the
  secret value when executing an already-authorized call. Target identity is
  package data since #100 and is never re-read from the environment.

## Boundary summary

`accepted content → canonical package (#100) → preflight ALLOW bound to
package_digest (#101) → publisher`. Publishers accept only the frozen
canonical package and derive any internal representation from it, so no
mutable object can diverge from what was authorized, and no second target
selection is possible after construction.
