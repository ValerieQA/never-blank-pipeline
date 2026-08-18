# Story #20 evidence map — complete per-run validation report

Issue #112. Each acceptance criterion is exactly one of: `SATISFIED` /
`SUPERSEDED` / `DEFERRED-LIVE`.

**No live publication is claimed anywhere in this document.** Story #21 remains
the live-verification track; Story #20 is what makes those future live runs
auditable.

## Criterion map

**1. "One authoritative report is produced per `run_id`."**
`SATISFIED`. `run_report.json` is written into the existing run namespace with
the same atomic create-once discipline as every other canonical artifact
(`ArtifactCollisionError` on collision; an existing report is never
overwritten and never silently updated). It is emitted from a **single
terminalization seam**: `main()` is a thin wrapper that runs the business body
and then persists the report exactly once, after the run has fully returned —
so no return path builds a report itself and none can be forgotten. Runs that
end before the run namespace exists (argument or configuration failures) are
not reportable and produce nothing, because there is no run to account for.

**2. "It contains all fields required by Epic #8 — evidence, strategy version,
decision, article, LinkedIn artifact, visuals, readiness, preflight, publisher
results."**
`SATISFIED` **as an index, not a copy**. The report carries run/signal/
execution identity, the authoritative `ConfigurationIdentity`, the terminal
stage and disposition, truthful completion, the Story #16 provenance summary,
per-channel outcomes, override state, sanitized unusable-evidence notes, and
**references** to the canonical artifacts the run actually produced. The
artifacts themselves remain the evidence: research, decision, editorial
acceptance, composition, visual, generated, preflight and publication payloads
are never reproduced inside the report. No universal artifact IDs, no manifest
platform, no second provenance engine, and no digest fields were added to any
upstream schema for the report's benefit.

**3. "Wix and LinkedIn statuses are reported independently."**
`SATISFIED`. Each channel is a separate outcome carrying its own status,
provider identifier, URL, URL provenance, reuse source and blocking reasons.
The accepted meanings are preserved verbatim — `PUBLISHED`, `REUSED`,
`PROVIDER_DUPLICATE`, `BLOCKED`, `FAILED` — and are never normalized into a
common "success". No status is manufactured for report symmetry.

**4. "Partial completion cannot be reported as full success."**
`SATISFIED`. `completed` is derived from canonical terminal evidence
(`publication_results.completed`), never from the caller's view and never from
the existence of the report. The model enforces the rule structurally: a
report claiming completion must carry the completed disposition, and a run
whose terminal stage is earlier than publication cannot carry channel outcomes
at all. `REUSED` is completed without a fresh provider publication;
`PROVIDER_DUPLICATE` stays incomplete; blocked and failed channels are never
promoted.

**5. "Published identifiers and URLs are verified against the corresponding
artifact package."**
`SATISFIED` **in its truthful form, and proven rather than copied**. A
pre-publication package cannot know a provider-generated identifier in
advance, so the report never reverse-derives a digest from a provider ID.
What it proves is the binding that actually exists — and it proves it rather
than restating the verdict's own claim, because Story #16 verifies the
generation/publication chain but **not** the Story #17 artifact, so a swapped
or relabelled verdict would otherwise pass.

For every channel status that asserts an authorized publication existed, the
report requires the full chain:

> publication result → this run → this signal → this channel → this run's
> authoritative configuration → this authorized target → the exact canonical
> package reconstructed from persisted evidence → whose `package_digest`
> equals the digest recorded in the Story #17 verdict.

This reuses the same two checks the Wix and LinkedIn idempotency scans
already apply (`validated_channel_verdict`, `authorized_package_digest_matches`),
exposed under public names rather than duplicated, so a report and a
suppression decision can never disagree about what "the verdict authorized
this package" means. Reuse-publication runs resolve their generation evidence
exactly as #105/#109 do. Reconstruction or digest failure raises
`RunReportError` and **no report is persisted**.

The minimum truthful matrix, derived from how the entrypoint records
outcomes — a channel only enters the publish path after `ALLOW`:

| channel status | ALLOW verdict + package binding required? |
|---|---|
| `PUBLISHED` | **yes** — a fresh publication was authorized |
| `REUSED` | **yes** — authorized, then suppressed by idempotency |
| `PROVIDER_DUPLICATE` | **yes** — a real attempt followed authorization |
| `FAILED` | **yes** — the failure happened during an authorized attempt |
| `BLOCKED` | **no** — the channel never reached the publisher; its verdict is read for blocking reasons only and no digest is claimed |

The provider's own output is then preserved exactly (`external_id`, `url`,
`UrlProvenance`, `reused_from_run_id`). Live confirmation that the provider's
post matches is `DEFERRED-LIVE`.

**6. "Warnings, failures and overrides are preserved."**
`SATISFIED`. The preflight override state (`none` / `attempted_rejected`),
sanitized unusable prior-evidence notes (typed reason codes and a count), the
per-channel blocking reasons, and the normalized errors explaining the
terminal disposition are all carried. Raw provider payloads, raw LLM
responses, prompts, credentials and exception dumps are structurally excluded:
the model forbids unknown fields, restricts artifact references to the
canonical set, and validates the unusable-evidence note's shape.

**7. "Report schema and integrity tests pass."**
`SATISFIED`. `tests/test_run_report.py` covers the legitimate terminal
outcomes (full success, Wix success with LinkedIn blocked, LinkedIn reuse,
provider duplicate, preflight block, editorial rejection, Decision Lens stop,
research failure), the fail-closed behavior over corrupt or tampered lineage,
create-once protection, the credential/payload trust boundary, and the model's
own truthfulness rules.

## Fail-closed behavior

Story #16's `verify_run_provenance` — with its existing stopped-run ladder
semantics — decides whether the chain is internally consistent. A legitimately
partial chain is reported normally with the last proven stage; an internally
contradictory one produces **no authoritative report at all**, and the
corruption is never normalized into a business stop.

One consistency check belongs to the report itself rather than to provenance:
the publication and preflight records being summarized must not claim a
different `run_id` or `signal_id` than the namespace they are stored under.
This is an input check on the report's own sources — Story #16 verifies the
chain but does not currently compare the signal recorded inside those records
against the run namespace, so without it a record claiming another signal
could be summarized as though it belonged here.

## Report-write failure never rewrites the outcome

If the run is already failing for reason X and writing the report fails, the
run still exits with X; a successful run is never turned into a failure
because its account could not be written. Collisions leave the existing report
untouched. The absence of a report is itself visible in the run namespace.

## Superseded / clarified original wording

- *"Reports do not contain a first-class `run_id`"* — **SUPERSEDED**: run
  identity has been first-class since Story #9 and was already on the report
  object before this task.
- *"The current report spans more channels than Release 1"* — **SUPERSEDED**:
  results have only ever contained `wix` and `linkedin`; non-R1 channels are
  printed as skipped and never enter the record.
- *"Decision Lens result, editorial acceptance, evidence references, preflight
  details, overrides and exact artifact IDs are missing or incomplete"* —
  **SUPERSEDED as evidence**: all of it existed and was verified before #112
  (Stories #12–#19). The accurate statement was that it had never been
  *assembled and verified into one authoritative account*, which is exactly
  what this task does — it creates no new evidence.
- *"Partial publisher failure returns a non-zero result in key paths"* —
  strengthened since: partial completion is structurally unable to be reported
  as success.

## Deterministic vs live

| Evidence | Kind |
|---|---|
| One create-once report per terminal run, from a single seam | deterministic (#112) |
| Truthful terminal stage/disposition for partial and full runs | deterministic (#112) |
| Independent channel outcomes with accepted meanings preserved | deterministic (#112) |
| Publication bound to the preflight-authorized package, reconstructed and digest-matched | deterministic (#112) |
| Fail-closed over corrupt/tampered lineage | deterministic (#112) |
| A real Wix/LinkedIn post matching the reported identifiers | **live, deferred** |
| Two consecutive live runs without code repair | **live, deferred (Story #21)** |
