# Decision Lens lifecycle and disposition gate

`src.editorial.decision_lifecycle` owns the Release 1 business gate between
research and all downstream work (Issue #60). The Decision Lens verdict is
mandatory: a run may proceed beyond the Decision Lens only when one canonical,
strictly validated `DecisionLensDecisionArtifact` exists for that exact run and
its disposition is `PROCEED`. Every other outcome is an explicit stop.

## Canonical lifecycle (fresh generation run)

Inside the canonical entrypoint (`scripts/generate_and_publish.py`):

1. the current run's canonical `research.json` is executed/persisted and
   strictly validated (Issue #52 lifecycle);
2. the exact typed strategy view, selected audience, configuration identity,
   Release 1 lens profile identity (`RELEASE1_LENS_PROFILE`), and exact
   run/assignment/signal identity are resolved;
3. the Issue #59 production evaluator is invoked exactly once
   (`evaluate_and_persist_decision`);
4. a successful canonical decision result is required — evaluator failure
   (transport error/timeout, malformed output, invalid citations,
   context/profile mismatch, contract violation) raises `DecisionGateError`
   and is never mapped into a synthetic decision artifact;
5. immutable run-scoped `decision.json` is created atomically with create-once
   semantics (collision → `ArtifactCollisionError`, a business stop);
6. the persisted artifact is strict-reloaded (`load_decision_artifact`),
   byte-compared against canonical serialization, and revalidated against the
   same current-run research, configuration, audience, and lens profile;
7. the persisted-and-reloaded artifact — never the in-memory pre-write
   object — is the final gate: `require_proceed` allows only `PROCEED` into
   narrative, hook, story, voice, platform composition, visual, package, and
   publisher work.

## Disposition semantics

- `PROCEED` — the only continuation.
- `REVISE`, `HOLD`, `REJECT`, `INSUFFICIENT_EVIDENCE` — legitimate canonical
  business decisions: persisted honestly in `decision.json`, then the run
  stops before any downstream effect.
- Evaluator/system failure — no valid decision artifact exists; nothing is
  persisted; the run stops. The distinction between a non-`PROCEED` business
  decision and an evaluator failure is preserved in the stop message.

All stops are business stops, not warnings: no narrative, hook, story, voice,
platform composition, visuals, publishing package, or publisher effects occur.

## `decision.json`

Canonical Issue #58 JSON bytes (`canonical_bytes()`): deterministic,
create-once, immutable, atomically written (same tmp+hardlink protocol as
`research.json`), run-scoped at
`reports/content_packages/<signal_id>/runs/<run_id>/decision.json`, and
independently reloadable through the strict contextual boundary. It preserves
exact decision artifact ID, run/assignment/signal identity, configuration
identity, audience selection, lens profile identity, canonical research
digest, evidence/source lineage, evaluator identity/version,
decision-lens/instruction version, and timestamps.

## Retry semantics

A retry after a failed or blocked generation follows new-run semantics: a new
`RunContext` produces a new run namespace with its own `research.json` and
`decision.json`. The original decision artifact is never mutated or
overwritten; a collision on the same run namespace fails closed.

## Reuse (`--from-package`)

Reuse preserves historical decision reproducibility:

1. the original generation run is resolved from `--source-run-id`;
2. its immutable `research.json` is loaded and strictly validated;
3. its immutable `decision.json` is loaded via `load_decision_artifact` —
   the Decision Lens is **not** re-run and neither artifact is rewritten;
4. the decision is byte-checked as canonical and revalidated against that
   original research and its exact configuration/audience/profile/run lineage
   (cross-run, configuration, audience, lens-profile, research-digest, and
   citation-lineage mismatches all fail closed);
5. only an original validated `PROCEED` decision allows reuse to continue;
   missing, corrupt, or non-`PROCEED` decisions fail before any downstream
   side effect.

## Expected profile

`RELEASE1_LENS_PROFILE` pins the complete lens profile identity
(`never-blank-editorial-lens` / `1.0`) that this orchestration expects.
Changing the maintained instruction profile requires updating this expectation
in a reviewed commit; a mismatch is a business stop, not a fallback.

## Scope notes

Story #13 article-quality acceptance, visuals functionality, complete
provenance (Story #16), reporting (Story #20), and the Story #12 marker/gate
remain out of scope. The legacy `decision_lens_lite.py` dictionary path is not
part of the canonical Release 1 flow and is never used to synthesize a
canonical decision.
