# Normalized Research Evidence Contract

`src.research.evidence.NormalizedResearchArtifact` is the canonical,
provider-neutral Story #11 research data boundary. Issue #50 defines data only:
it does not call providers, modify orchestration, or persist `research.json`.

The artifact requires run, assignment, signal, and four-field Business Strategy
Configuration identity. Its immutable records keep these concepts separate:

- normalized sources and their URL/identifier;
- explicit `known`, `unknown`, or `not_collected` publication time;
- mandatory UTC retrieval time;
- bounded source-derived support and extracted evidence;
- model-authored interpretation;
- uncertainty and conflicting evidence;
- evidence disposition and artifact readiness.

## Readiness invariants

`ready` is a fail-closed state, not a label that upstream code can apply to an
incomplete result. A `ready` artifact requires at least one evidence record and
allows only `accepted` or `qualified` evidence dispositions. `not_assessed`,
`conflicting`, and `rejected` evidence always block `ready`.

Uncertainty declares both typed materiality (`material` or `non_material`) and
typed resolution (`unresolved` or `resolved`). An unresolved material
uncertainty blocks `ready`. A resolved uncertainty, or an explicitly
non-material unresolved uncertainty, is compatible with `ready`; the
classification is never inferred from description text. Contradictions also
declare resolution, and every unresolved contradiction blocks `ready`.

Partial, unassessed, rejected, uncertain, and conflicting research remains
representable with a non-ready state such as `insufficient`, `needs_review`, or
`blocked`. An inconsistent requested `ready` value is rejected with a validation
error; the model never silently coerces it to another state.

All sources, evidence, interpretations, uncertainties, and contradictions in an
artifact share one global ID namespace. IDs must be unique both within their own
collection and across entity kinds. Cross-kind reuse—including a contradiction
using the ID of a source or evidence record it references—is invalid.

All models use Pydantic `frozen=True` and `extra="forbid"`. Every timestamp must
be timezone-aware UTC. Artifact validation rejects duplicate IDs, dangling
source/evidence references, unknown fields/statuses, and credential-shaped
content. The declared fields cannot hold provider SDK objects, unrestricted raw
responses, credentials, or provider-specific exceptions.

## Serialization

`canonical_json()` emits UTF-8-compatible JSON using `model_dump(mode="json")`,
sorted object keys, compact separators, unescaped Unicode, and no NaN values.
Collection order remains meaningful and is preserved. An equal validated model
therefore produces identical bytes, and
`NormalizedResearchArtifact.model_validate_json()` restores every field.

Run the offline contract tests with:

```bash
python3 -m pytest tests/test_research_evidence_contract.py
```
