# Decision Lens evaluator boundary

`src.editorial.decision_lens_evaluator` owns the Release 1 production Decision
Lens evaluator boundary (Issue #59). It consumes strict typed inputs, invokes a
narrow injectable transport, and returns the canonical Issue #58
`DecisionLensDecisionArtifact` — always validated through the canonical
contextual boundary before any caller sees it.

## Inputs and trust

`DecisionLensEvaluator.evaluate()` accepts only typed inputs:

- validated current-run `NormalizedResearchArtifact`;
- `DecisionLensEditorialStrategyView` (exact typed strategy view);
- typed `AudienceSelection`;
- supplied `ConfigurationIdentity`;
- expected `DecisionLensProfileIdentity`;
- exact `run_id`, `assignment_id`, `signal_id`.

There is no unrestricted signal/context mapping on this boundary: arbitrary
metadata, nested mappings, credentials, headers, or provider data cannot cross
the public evaluator API. The judgment is grounded in the research artifact,
strategy boundaries, audience, and exact execution identity alone.

Canonical lineage fields — run/assignment/signal identity, configuration
identity, audience selection, lens profile, research digest, evaluator
attribution, timestamps, schema version, artifact ID — are taken exclusively
from these trusted inputs. Model output can never supply or override lineage:
unknown output fields are rejected, not silently dropped.

Before any transport call the evaluator fails closed on: instruction/profile
mismatch, strategy-view/configuration mismatch, research configuration or
execution-identity mismatch, and an audience not declared by the strategy view.

## Transport boundary

`DecisionLensTransport` is a one-method protocol
(`complete(instructions, request) -> str`). The evaluator contains no provider
branching — replacing the transport cannot change evaluator behavior (verified
by test). The production `LlmChatDecisionLensTransport` wraps the repository
LLM client internally; deterministic tests inject fakes and never call live
providers. There are no retries at this boundary: a failed evaluation remains a
typed failure and can never be retried into silent success.

## Evidence discipline

The evaluation request carries the normalized research evidence as the only
factual boundary, and strategy positioning/proof points/claims explicitly
labeled as decision boundaries that are never evidence. After the transport
returns, the evaluator independently verifies every citation scope (decision
level, each relevance basis, each criterion result):

- cited evidence IDs must exist in the current-run research artifact;
- cited source IDs must exist and exactly equal the union of sources
  supporting the cited evidence — borrowed or missing sources are rejected.

The canonical #58 validation then re-enforces the full contract (blocked
evidence, unresolved contradictions/material uncertainty, analogy-only
relevance, false `PROCEED`, credential-shaped text, extra fields, exact
digest/lineage). Evaluator success cannot bypass any #58 invariant.

## Failure mapping

Every failure is a typed `DecisionEvaluationFailure`; no failure path returns
an artifact, and none can become `PROCEED`:

| Condition | `DecisionEvaluationFailureKind` |
|---|---|
| transport raised timeout (`DecisionLensTransportTimeout` / `TimeoutError`) | `TRANSPORT_TIMEOUT` |
| transport raised any other exception | `TRANSPORT_ERROR` |
| output not JSON / not an object / unknown fields / schema-shape errors | `MALFORMED_OUTPUT` |
| citations unknown to research or not exactly supporting | `INVALID_CITATION` |
| strategy/research/execution/audience context mismatch | `CONTEXT_MISMATCH` |
| expected profile does not match maintained instructions | `PROFILE_MISMATCH` |
| canonical #58 invariant rejection (false proceed, blocked evidence, …) | `CONTRACT_VIOLATION` |

Failure detail is evaluator-authored bounded text only: raw provider
responses, SDK objects, prompts, credentials, headers, and raw exception
messages never cross the boundary (only the exception class name is recorded).

Legitimate editorial non-success (`REVISE`, `HOLD`, `REJECT`,
`INSUFFICIENT_EVIDENCE`) is not a failure: it returns a canonical validated
artifact with an explicit non-success disposition.

## Maintained instructions

The Decision Lens instructions are externalized to
`config/prompts/decision_lens/never_blank.yaml` with explicit
`instruction_id`, `profile_id`, `profile_version`, and `version`.
`profile_id`/`profile_version` name the complete lens profile identity the
instructions implement; `version` is the instruction revision — distinct
concepts that are not collapsed. The evaluator records
`<instruction_id>/<version>` in the canonical `decision_lens_version` field and
refuses to run — before any transport call — when the expected
`DecisionLensProfileIdentity` does not match the instruction profile identity
in full (ID and version). Changing judgment semantics requires a version bump
in a reviewed commit.

Never Blank is the Release 1 lens profile; its mechanism-neutral judgment
criteria (`nb-supported-mechanism`, `nb-supported-business-consequence`) live
in the instruction artifact and surface through the generic
`criterion_results` collection — the universal canonical contract is
unchanged. The profile permits presence or customer-memory interpretations when
the run evidence supports them, but never requires those interpretations. A
Release 2 profile registry or generalized profile loading (Epic #63 / Story
#67) is explicitly out of scope.

## Legacy compatibility

`decision_lens_lite.py` and its downstream dictionary remain unchanged for
non-canonical callers. The canonical Release 1 path does not use the legacy
mapping. This task does not persist `decision.json`, wire orchestration
gating, or implement Story #13 acceptance — those remain later Story #12 work.
