# Provider-Neutral Research Adapter

Issue #51 introduces a replaceable retrieval boundary that converts provider
responses into the normalized evidence contract from Issue #50. It does not
wire research into the Release 1 orchestration and does not persist
`research.json`; Issue #52 owns those changes.

## Boundary

Core code calls the `ResearchProvider` protocol through `execute_research()`.
The protocol accepts one immutable `ResearchProviderRequest` and returns a
strictly discriminated complete, partial, or failed result. Core code contains
no Exa-, RSS-, OpenAI-, or fake-provider branches.

The request contains only:

- run, assignment, and signal identity;
- the selected immutable `ResearchStrategyView`;
- a strict UTC freshness boundary and request timestamp;
- typed source directives.

The result records typed provider attribution, invocation start/completion,
attempt count, sanitized operation failures, and per-source retrieval outcomes.
`ResearchResultEnvelope` links the request and result, validates identity and
freshness, and provides deterministic JSON for the Issue #52 persistence
handoff.

Every new Pydantic contract is frozen and rejects extra fields. Raw response
bodies, headers, SDK objects, exceptions, credentials, tokens, arbitrary
metadata, and provider configuration have no field through which they can cross
the boundary.

## Source priority

Directives implement the accepted order:

1. `REQUIRED` is an exact client URL or feed that must be attempted. A failed
   material required source prevents a complete result and prevents `READY`.
2. `PREFERRED` is a client-approved URL, feed, or domain. Preferred URLs are
   retrieved directly and preferred domains are searched before discovery.
3. `DISCOVERY` is open-web search for gaps, freshness, independent confirmation,
   and contradictions. It runs only when the request explicitly permits it.
4. `EXCLUDED` is a URL or domain that must not be queried or returned.

Domain policy uses symmetric canonical hostname comparison: hostnames are
case-insensitive and trailing DNS root dots are removed before local include or
exclude checks. Label boundaries remain significant, so a suffix such as
`blocked.example.com.evil.test` is not treated as `blocked.example.com`.
Equivalent URL spellings that differ only by hostname case or a trailing root
dot share one canonical source identity and cannot create duplicate evidence.

Per-source outcomes retain a typed `client_supplied` or
`provider_discovered` origin. Client input determines where retrieval starts;
it is never automatically treated as verified evidence.

## Exa and the deterministic fake

`ExaResearchAdapter` is the first production adapter. Exact URL retrieval uses
Exa Contents, preferred domains use constrained Exa Search, and discovery uses
unrestricted Exa Search only when allowed. The default REST transport uses the
existing `requests` dependency and obtains `NB_EXA_API_KEY` only from the
environment (or explicit construction outside downstream contracts). No Exa
SDK is required.

Tests inject an `ExaTransport`, so they make no network calls and require no
credentials. `DeterministicFakeResearchProvider` independently implements the
same protocol and exposes complete, partial, empty, malformed, timeout,
authentication, rate-limit, unavailable, and source-failure scenarios.

## Execution outcome is not evidence readiness

Provider transport success and evidence readiness are separate dimensions. A
complete provider operation may still contain a non-ready artifact. Retrieved
provider claims default to `not_assessed`; the adapter has no deterministic
assessment policy that could justify `accepted` or `qualified`.

- Partial retrieval always carries a non-ready artifact and explicit failures.
- Empty and fatal outcomes carry no fabricated artifact.
- Required-source failure cannot become complete or `READY`.
- Conflicting evidence and unresolved material uncertainty remain representable
  only through the Issue #50 non-ready states.
- Invalid attempted `READY` construction is rejected by the canonical Issue #50
  validation boundary; adapters do not silently coerce it.

## Failure mapping

Transport timeout, authentication failure, rate limiting, malformed response,
empty result, provider unavailability, and individual source failure map to
bounded provider-neutral codes. Retryability and optional retry delay are typed.
Messages are sanitized and bounded; provider exception text and response bodies
are never copied.

## Issue #52 handoff

Issue #52 will persist the validated `ResearchResultEnvelope` as the run-scoped
`research.json`. Downstream strategy and editorial stages will consume the
canonical `NormalizedResearchArtifact` (or a declared typed view), never an Exa
response or transport object. No persistence or orchestration integration is
implemented by Issue #51.

Run the offline focused tests with:

```bash
python3 -m pytest tests/test_research_provider_adapter.py
```
