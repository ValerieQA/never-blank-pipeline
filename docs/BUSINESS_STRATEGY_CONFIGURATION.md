# Business Strategy Configuration Contract

Issue #39 defines the Release 1 provider-neutral boundary for business meaning.
The executable schema is `BusinessStrategyConfiguration` in
`src/strategy/business_config.py`.

## Identity

The run-bound configuration identity has four fields:

- `schema_version`: revision of the contract shape;
- `configuration_id`: stable identity of a business configuration;
- `configuration_version`: revision of that business configuration's meaning.
- `configuration_hash`: deterministic content identity of the validated meaning.

### Canonical serialization and hash

The serialization contract is `business-strategy-json-v1`: validate with
`BusinessStrategyConfiguration`, serialize `model_dump(mode="json")` as UTF-8
JSON with lexicographically sorted object keys, no insignificant whitespace,
unescaped Unicode, and no non-JSON numeric values. Arrays retain their declared
order. The source path, raw key order, whitespace, and file metadata never enter
the serialization.

`configuration_hash` is `sha256:` followed by the lowercase SHA-256 hex digest
of those canonical bytes. A run writes the validated model to its create-once
`<signal_id>/runs/<run_id>/business_strategy.json`; reuse validates that snapshot
and requires its four-field identity to equal both `generated.json` and the
selected current configuration. Historical snapshots are never replaced or
silently reconstructed from the current file.

## Required sections

The contract requires business identity/model, products and services, audience
segments and their decision factors, positioning and expertise, value
propositions and proof points, commercial priorities, content objectives and
territories, voice and editorial policy, preferred/prohibited claims,
restrictions, calls to action, separate Wix and LinkedIn rules, and versioned
prompt/rule references.

All models are immutable and reject unknown fields. Required collections cannot
be empty, and identifiers inside repeated sections must be unique. Credentials,
provider SDK objects, and provider payloads do not belong in this contract.

## Production loading

`load_business_strategy_configuration()` is strict. Missing, unreadable,
malformed, schema-invalid, or inactive configuration raises a typed
`BusinessStrategyConfigurationError`; the loader never returns `None` and never
creates a default strategy.

The existing `Strategy` and `load_active_strategy()` APIs remain a temporary
legacy campaign boundary; canonical Release 1 business meaning comes from this
strict configuration contract.

## Out of scope

This contract does not contain credentials, client onboarding, a configuration
management UI, multi-tenant storage, billing, or post–Release 1 channel rules.
