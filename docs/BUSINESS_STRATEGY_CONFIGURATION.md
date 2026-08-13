# Business Strategy Configuration Contract

Issue #39 defines the Release 1 provider-neutral boundary for business meaning.
The executable schema is `BusinessStrategyConfiguration` in
`src/strategy/business_config.py`.

## Identity

The contract keeps three identities separate:

- `schema_version`: revision of the contract shape;
- `configuration_id`: stable identity of a business configuration;
- `configuration_version`: revision of that business configuration's meaning.

Task #42 will add deterministic content hashing and immutable run snapshots.

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

The existing `Strategy` and `load_active_strategy()` APIs are a temporary legacy
campaign boundary. Task #40 will provide the complete Never Blank production
configuration. Task #41 will move canonical Release 1 consumers to the new
strict boundary. Keeping that migration explicit prevents Issue #39 from
silently inventing incomplete production values.

## Out of scope

This contract does not contain credentials, client onboarding, a configuration
management UI, multi-tenant storage, billing, or post–Release 1 channel rules.
