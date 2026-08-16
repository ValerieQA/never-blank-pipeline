# Story #16 evidence map — run-scoped artifacts and provenance

Issue #98. This document maps every Story #16 acceptance criterion to its
implementation evidence so the closure is auditable without chat history.
Each criterion is exactly one of: `SATISFIED` / `SUPERSEDED` / `DEFERRED`.

## Criterion map

**1. "Every run has a unique storage namespace keyed by `run_id`."**
`SATISFIED` (Story #9 / Issue #28, unchanged). Evidence:
`src/artifacts/__init__.py::resolve_run_dir` +
`atomic_write_json`/`atomic_write_bytes` create-once (tmp + hardlink) —
collision raises `ArtifactCollisionError`. Tests:
`tests/test_artifacts.py`, `tests/test_provenance_chain.py::test_same_signal_two_runs_stay_independent`.

**2. "Input, research, evidence, strategy version, Decision Lens, article,
LinkedIn composition, visuals, readiness, preflight, requests, and responses
have stable artifact IDs."**
Split by element:
- *Input* — `SATISFIED` by this task: run-scoped `assignment.json`
  (`AssignmentRecord` envelope binding the canonical `ContentAssignment`
  with its `assignment_id` to `run_id` + `ConfigurationIdentity`).
- *Research, evidence* — `SATISFIED` (#50–#52): `research.json` canonical
  envelope with `artifact_id`, source IDs, evidence IDs, canonical bytes,
  `research_artifact_digest`.
- *Strategy version* — `SATISFIED` (#42): `business_strategy.json` snapshot
  with recomputable `ConfigurationIdentity` (hash), plus
  `strategy_id`/`strategy_version` recorded in downstream artifacts.
- *Decision Lens* — `SATISFIED` (#58/#60): `decision.json` with
  `decision_artifact_id` and canonical bytes.
- *Article* — `SATISFIED` (#93 convention): the accepted article's stable
  identity is `sha256(blog_article)` recorded as `source_article_digest` in
  both the LinkedIn and visual records; no parallel article schema exists by
  design.
- *LinkedIn composition* — `SATISFIED` (#93): `linkedin_composition.json`.
- *Visuals* — `SATISFIED` (#96): `visual_assets.json` with
  `run_id`/`origin_run_id`/`reused` and per-channel derivatives.
- *Readiness, preflight* — `DEFERRED` to **Story #17**, which owns the
  publication preflight gate; no preflight semantics were pulled forward.
- *Requests and responses* — `SUPERSEDED`: canonical research
  request/result information is part of the trusted `research.json`
  envelope; raw LLM/provider prompts, responses, SDK objects, credentials,
  and arbitrary payloads are **deliberately excluded** by the accepted
  Story #12/#13 trust boundaries (#58/#59/#89 contracts). Persisting them
  is prohibited, not missing.

**3. "Every artifact records producer, inputs, timestamps, and `run_id`."**
`SATISFIED`. Canonical contracts carry producer attribution (research
provider/adapter attribution; Decision Lens evaluator identity/version and
instruction version; editorial rubric identity; LinkedIn composition rules
version; visual provider/method), timestamps, and run identity.
`assignment.json` closes the last gap (intake). `business_strategy.json`
carries no run fields by design — its identity is recomputable and verified
against every downstream artifact by the chain verifier.

**4. "Artifacts are append-only or version-preserving for release evidence."**
`SATISFIED` (Story #9 + #12–#15, unchanged): every run-scoped artifact is
atomic create-once; retry follows new-run semantics. Legacy signal-scoped
caches (`visual_registry.json`, `image_library.json`, flat
`<signal_id>.json`) are operational caches, **not** canonical run evidence,
and remain outside Release 1 provenance (post-R1 cleanup is planned
separately).

**5. "Cross-run artifact substitution is detected and blocked."**
`SATISFIED` by this task (whole-run) on top of per-artifact protections
(#58/#60/#93/#96): `src/artifacts/provenance.py::verify_run_provenance`
verifies relationships — assignment↔research↔decision digests and
identities, accepted-article digest ↔ LinkedIn ↔ visual, visual
origin/reuse semantics, publication run/source/generation identities.
Tests: `tests/test_provenance_chain.py` substitution/tamper suite.

**6. "Repeated execution of the same signal cannot overwrite prior evidence."**
`SATISFIED`: create-once writes + independent run namespaces. Test:
`test_same_signal_two_runs_stay_independent` (both chains independently
verifiable; first run byte-identical after the second).

**7. "Provenance integrity tests pass."**
`SATISFIED` by this task: `tests/test_provenance_chain.py` — 23 deterministic
tests covering complete chains, legitimate stops (Decision Lens non-PROCEED,
editorial REJECT, failed research), cross-run substitution at every seam,
tampered research/article states, forged downstream artifacts, corruption,
configuration drift, and reuse-publication runs.

## Verifier semantics (summary)

`verify_run_provenance(packages_dir, signal_id, run_id)` is read-only: it
never regenerates content, calls models/publishers, or mutates artifacts. It
distinguishes **generation** runs from **reuse-publication** runs (classified
from the artifacts themselves: `visual.reused` / publication
`source_run_id`), supports valid partial chains for legitimately stopped
runs, and fails only for: a missing artifact required by the stage actually
reached; artifacts belonging to another run/source/configuration;
digest/reference inconsistency; later artifacts without their valid upstream
chain; malformed artifacts. A blocked business outcome is not corrupted
provenance.

No `run_manifest.json`, no universal artifact-ID migration, no provenance
platform: verification is performed directly over the existing canonical
artifacts, and no existing artifact contract required a new field (the only
new construct is the new `assignment.json` artifact itself).
