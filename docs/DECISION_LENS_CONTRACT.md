# Decision Lens decision contract

`src.editorial.decision_contract` owns the single canonical immutable Decision
Lens judgment for Story 12. Issue #58 defines validation and serialization only.
It does not call an evaluator, change pipeline ordering, persist `decision.json`,
or enforce a decision downstream; those are Issue #59 responsibilities.

## Ownership and lineage

`DecisionLensDecisionArtifact` belongs to exactly one run, assignment, signal,
configuration, selected audience, and canonical current-run research artifact.
It reuses `ConfigurationIdentity` and `AudienceSelection` without flattening or
redeclaring them. `research_digest` is `sha256:` plus the SHA-256 digest of
`NormalizedResearchArtifact.canonical_bytes()`; the complete research artifact is
not duplicated inside the decision.

External lineage validation must use `validate_for_research()` or
`validate_json_for_research()` with the expected research artifact, audience, and
configuration identity. These boundaries reject run, assignment, signal,
configuration, audience, digest, source, and evidence drift. Decision source IDs
must exactly equal the sources supporting the cited evidence IDs.

## Structured judgment

The judgment separately records:

- direct, indirect, or irrelevant business/audience relevance;
- sufficient, partial, or insufficient evidence;
- why the signal matters;
- the evidence-to-business-value connection;
- the configured audience problem, tension, question, or opportunity;
- a defensible evidence-grounded perspective;
- the strongest supported editorial angle;
- typed small-business relevance bases;
- typed handling of referenced research uncertainties and contradictions;
- bounded restrictions and disposition reasons.

Evidence remains source-derived research. The Decision Lens fields are evaluator
interpretation. Strategy proof points are boundaries and are never factual evidence.
No prompt, raw model response, provider object, exception, credential, arbitrary
metadata, or unrestricted mapping is part of the canonical artifact.

## Direct small-business relevance

Source selection should begin with the small-business problem. Decision Lens
validates relevance and interpretation; it does not manufacture relevance after
research.

`PROCEED` requires at least one cited, structured relevance basis of one of these
types:

- `DIRECT_AUDIENCE_EVIDENCE`: research directly concerns the configured
  small-business audience, including applicable SBA, Census, or BLS evidence;
- `CLIENT_FIRST_PARTY_EVIDENCE`: client evidence identifies the audience's problem
  or decision;
- `DOCUMENTED_DIRECT_IMPACT`: cited evidence documents a law, regulation, market,
  platform, financing, labor, tax, licensing, supplier, customer, or comparable
  change with a stated direct consequence for that audience;
- `CREDIBLE_SECTOR_EVIDENCE`: credible sector evidence documents the same
  constraint, decision, or consequence for that class of small business.

`ANALOGY_ONLY` is explicitly non-qualifying. An unrelated Toyota, Nike, or other
large-company case cannot proceed because an evaluator can imagine a similar choice
at smaller scale. A large-company action is admissible only when cited research
documents its direct consequence for the configured small-business audience. The
affected owner remains the subject; the corporate action is supporting evidence.

The typed basis makes the evaluator's relevance claim auditable and rejects
analogy-only `PROCEED`. It does not perform semantic fact checking of natural-language
claims; the evaluator and later integration must supply truthful, cited classifications.

## Dispositions

- `PROCEED` is the only success disposition.
- `REVISE`, `HOLD`, `REJECT`, and `INSUFFICIENT_EVIDENCE` are explicit non-success
  states and preserve bounded reasons.

There is no parallel readiness or success flag. Inconsistent input is rejected, not
coerced.

`PROCEED` requires direct relevance, sufficient evidence, at least one cited source
and evidence record, a supported angle, a defensible perspective, and a qualifying
direct small-business relevance basis. The contextual boundary also requires READY
research, acceptable cited evidence, no unresolved contradiction, and no unresolved
material uncertainty. Rejected, conflicting, or not-assessed evidence cannot support
`PROCEED`.

`research_condition_handling` may reference only uncertainty and contradiction IDs
present in the supplied research artifact. Each entry records a bounded typed
treatment (`ACKNOWLEDGED`, `BOUNDED`, `RESOLVED`, or `EXCLUDED_FROM_ANGLE`) and an
explanation. Recording a treatment never overrides the research contract: unresolved
contradictions and unresolved material uncertainties still block `PROCEED`.

## Strictness and serialization

Every canonical model is frozen and uses `extra="forbid"`. IDs and references are
unique, source/evidence namespaces cannot collide, timestamps are timezone-aware UTC,
and evaluation completion cannot precede its start. Schema versions and SHA-256
digests are strict.

Canonical serialization is UTF-8 JSON with sorted keys, compact separators,
JSON-native enum values, preserved collection order, and no insignificant whitespace.
Repeated serialization produces identical bytes, and contextual strict reload
reconstructs the same validated artifact without loss.
