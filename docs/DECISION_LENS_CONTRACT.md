# Decision Lens decision contract

`src.editorial.decision_contract` owns the single canonical immutable Decision
Lens judgment for Story 12. Issue #58 defines validation and serialization only.
It does not call an evaluator, change pipeline ordering, persist `decision.json`,
or enforce a decision downstream; those are Issue #59 responsibilities.

The contract is a **generic canonical decision artifact**. It does not assume any
particular business or audience. Business-specific judgment semantics belong to a
**lens profile**, identified in the artifact but never embedded in it.

## Ownership and lineage

`DecisionLensDecisionArtifact` belongs to exactly one run, assignment, signal,
configuration, selected audience, lens profile, and canonical current-run research
artifact. It reuses `ConfigurationIdentity` and `AudienceSelection` without
flattening or redeclaring them. `research_digest` is `sha256:` plus the SHA-256
digest of `NormalizedResearchArtifact.canonical_bytes()`; the complete research
artifact is not duplicated inside the decision.

External lineage validation must use `validate_for_research()` or
`validate_json_for_research()` with the expected research artifact, audience,
configuration identity, and lens profile identity. These boundaries reject run,
assignment, signal, configuration, audience, lens-profile, digest, source, and
evidence drift. Decision source IDs must exactly equal the sources supporting the
cited evidence IDs.

## Lens profile identity

`DecisionLensProfileIdentity` carries `lens_profile_id` and `lens_profile_version`.
It identifies which profile's semantics produced the judgment. It is distinct from:

- business/configuration identity (`ConfigurationIdentity`);
- audience selection (`AudienceSelection`);
- evaluator attribution (`DecisionEvaluatorAttribution`);
- the decision artifact `schema_version`.

The complete profile definition and its prompts are never stored in the artifact.
The contextual validation boundary rejects an unexpected profile identity; direct
construction and strict JSON reload cannot bypass that check because both external
validation paths require the expected profile.

## Structured judgment

The judgment separately records:

- direct, indirect, or irrelevant business/audience relevance;
- sufficient, partial, or insufficient evidence;
- why the signal matters;
- the evidence-to-business-value connection;
- the configured audience problem, tension, question, or opportunity;
- a defensible evidence-grounded perspective;
- the strongest supported editorial angle;
- typed configured-audience relevance bases;
- profile-defined criterion results;
- typed handling of referenced research uncertainties and contradictions;
- bounded restrictions and disposition reasons.

Evidence remains source-derived research. The Decision Lens fields are evaluator
interpretation. Strategy proof points are boundaries and are never factual evidence.
No prompt, raw model response, provider object, exception, credential, arbitrary
metadata, or unrestricted mapping is part of the canonical artifact.

## Criterion results

`DecisionCriterionResult` lets a lens profile define what its Decision Lens
evaluates without changing the canonical schema. Each result carries a stable
`criterion_id`, a bounded `CriterionAssessment` (`SATISFIED`, `NOT_SATISFIED`,
`UNCERTAIN`), a bounded conclusion, exact cited evidence and source IDs, and
bounded restrictions.

Invariants:

- criterion IDs are unique within a judgment;
- criterion citations must be subsets of the decision's declared source and
  evidence IDs, which in turn resolve against the current-run research artifact;
- a `SATISFIED` criterion requires at least one cited evidence item;
- a criterion citing evidence must cite its supporting sources, and a criterion
  citing sources must cite the evidence they support — neither list may be
  non-empty alone;
- at the contextual boundary, a criterion's source IDs must exactly match the
  sources supporting its cited evidence in the current-run research artifact —
  a criterion cannot borrow an artifact-declared source that does not support
  its own cited evidence;
- raw mappings, prompts, provider payloads, credentials, and unrestricted metadata
  remain forbidden.

**The universal schema does not enumerate any business's criterion IDs.** Profile
criterion IDs (for example Never Blank presence criteria) appear only in profile
fixtures and profile documentation.

## Configured-audience relevance

Source selection should begin with the configured audience's problem. Decision Lens
validates relevance and interpretation; it does not manufacture relevance after
research.

`PROCEED` requires at least one cited, structured `AudienceRelevanceBasis` of one
of these types:

- `DIRECT_AUDIENCE_EVIDENCE`: research directly concerns the configured audience;
- `CLIENT_FIRST_PARTY_EVIDENCE`: client evidence identifies the audience's problem
  or decision;
- `DOCUMENTED_DIRECT_IMPACT`: cited evidence documents a change with a stated
  direct consequence for that audience;
- `CREDIBLE_SECTOR_EVIDENCE`: credible sector evidence documents the same
  constraint, decision, or consequence for that class of audience.

`ANALOGY_ONLY` is universally non-qualifying for `PROCEED`. An unrelated
large-company case cannot proceed because an evaluator can imagine a similar choice
at a different scale. A corporate action is admissible only when cited research
documents its direct consequence for the configured audience. The affected audience
remains the subject; the corporate action is supporting evidence.

The typed basis makes the evaluator's relevance claim auditable and rejects
analogy-only `PROCEED`. It does not perform semantic fact checking of
natural-language claims; the evaluator and later integration must supply truthful,
cited classifications.

## Dispositions

- `PROCEED` is the only success disposition.
- `REVISE`, `HOLD`, `REJECT`, and `INSUFFICIENT_EVIDENCE` are explicit non-success
  states and preserve bounded reasons.

There is no parallel readiness or success flag. Inconsistent input is rejected, not
coerced.

`PROCEED` requires direct relevance, sufficient evidence, at least one cited source
and evidence record, a supported angle, a defensible perspective, and a qualifying
configured-audience relevance basis. The contextual boundary also requires READY
research, acceptable cited evidence, no unresolved contradiction, and no unresolved
material uncertainty. Rejected, conflicting, or not-assessed evidence cannot support
`PROCEED`.

`research_condition_handling` may reference only uncertainty and contradiction IDs
present in the supplied research artifact. Each entry records a bounded typed
treatment (`ACKNOWLEDGED`, `BOUNDED`, `RESOLVED`, or `EXCLUDED_FROM_ANGLE`) and an
explanation. Recording a treatment never overrides the research contract: unresolved
contradictions and unresolved material uncertainties still block `PROCEED`.

## Release 1 / Release 2 boundary

- Issue #58 defines the generic canonical decision artifact plus lens profile
  identity and generic criterion results.
- **Never Blank is the first Release 1 lens profile.** Its profile semantics
  require direct small-business relevance and reject analogy-only corporate
  relevance. Those semantics are demonstrated through Never Blank profile fixtures
  in the test suite, not through universal schema names or validators.
- The legacy `decision_lens_lite.py` and its downstream dictionary remain
  unchanged legacy output in this task; they are not a second canonical contract.
- Issue #59 may implement the Never Blank evaluator against this contract.
- Release 2 Epic #63 and Story #67 own full profile externalization, profile
  loading, and editorial projection.
- Issue #58 does not implement a profile registry, multi-tenant configuration UI,
  second production editorial engine, or Release 2 migration.
- This task does not persist or enforce decisions.

## Strictness and serialization

Every canonical model is frozen and uses `extra="forbid"`. IDs and references are
unique, source/evidence namespaces cannot collide, timestamps are timezone-aware UTC,
and evaluation completion cannot precede its start. Schema versions and SHA-256
digests are strict.

Canonical serialization is UTF-8 JSON with sorted keys, compact separators,
JSON-native enum values, preserved collection order, and no insignificant whitespace.
Canonical bytes include the lens profile identity and criterion results. Repeated
serialization produces identical bytes, and contextual strict reload reconstructs
the same validated artifact without loss.
