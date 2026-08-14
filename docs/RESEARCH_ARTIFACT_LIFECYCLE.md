# Canonical research artifact lifecycle

Every new Release 1 generation run creates its `RunContext`, loads the strict
Business Strategy Configuration, invokes the provider-neutral `ResearchProvider`
through `execute_research()`, and commits the complete `ResearchResultEnvelope` as
`<signal_id>/runs/<run_id>/research.json` before Decision Lens, editorial, visuals,
package mutation, or publishers.

The file is compact canonical UTF-8 JSON from `ResearchResultEnvelope.canonical_json()`.
It is atomically create-once, strict-reloaded, and checked against the run,
assignment, signal, four-field configuration identity, source outcomes, retrieval
freshness, and provider timing. The explicit future-clock allowance is five minutes.
An existing or partially failed write is never repaired or overwritten; retry uses
a new run namespace.

Source directives are deterministic: REQUIRED exact client URLs first, then
PREFERRED URLs/domains, explicitly enabled DISCOVERY queries, and EXCLUDED
URLs/domains. Priority is not evidence truth. The provider must enforce exclusions,
including the canonical hostname rules documented for the adapter.

Provider completion is not evidence readiness. Raw Exa retrieval is currently
`NEEDS_REVIEW`; it is persisted honestly and the run is held. Only a complete
envelope containing a strictly valid `READY` artifact crosses into editorial. No
disposition is promoted or coerced. Partial, failed, insufficient, rejected,
conflicting, contradictory, or materially uncertain research blocks. Failures
before a valid envelope exists do not fabricate `research.json`.

`--from-package` performs no fresh research. It loads the original generation
run's immutable `research.json`, validates canonical bytes and full lineage, and
uses its READY artifact without copying or rewriting it. A prepared package alone
cannot satisfy the gate. Legacy packages without canonical research lineage block.

Production credentials remain only at the Exa composition root. They are never
persisted. Tests inject deterministic providers and make no network or paid calls.
