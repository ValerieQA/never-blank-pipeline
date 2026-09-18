# ENGINE — client contracts

How the Engine reads a client's human-readable contracts and routes them to
stages. Owner decision D12 (#240): the Engine is content-domain agnostic; a
client's topic, audience, tone, sourcing policy and editorial method arrive as
documents the client owns. Implementation: `src/strategy/client_contracts.py`.

## The active client

`NB_CLIENT_DIR` names the client's directory (default: this repository's own
client, `clients/never_blank`). Replacing the client means pointing this at
another directory — no Engine code changes. That is the Replace-the-client test
(#240 D12 addendum), and `tests/test_client_contracts.py` runs it as code.

```
<client>/
  streams/*.md   one stream contract per stream
  lenses/*.md    0..N lenses
```

## Stream contract

Parsed, so its shape is a contract.

- **Front matter**, all required, nothing else accepted, no duplicate keys:
  `stream_id`, `version`, `role_id` (the editorial role it governs), `selection`.
- **Headings**: exactly `## Purpose`, then `## Selection`. One `#` title may
  precede them. Under `## Selection` the client may group rules under `###`
  headings of any name; nothing deeper, and no `###` anywhere else.
- `## Purpose` becomes the role's intent and reaches the writing stage.
- Every bullet (`- `, continuation lines indented) under `## Selection` is one
  rule a candidate signal is judged against.
- `selection: first_valid`: candidates are read in queue order; the first that
  satisfies every rule — the stream's and every lens routed to selection — is
  used, and no later candidate is judged.

A missing, extra, misplaced or misspelt heading fails the run instead of
silently dropping a rule (#233 F-03).

## Lens

Not parsed: the body is delivered verbatim to every stage its front matter
names. Front matter, all required, no duplicate keys: `lens_id`, `version`,
`applies_to` (stream ids), `stages` (any of `selection`, `writing`,
`revision`). Zero lenses is valid.

| Stage | Where the text arrives |
|---|---|
| `selection` | after the stream's own rules, in the candidate judgment's criteria |
| `writing` | in the editorial role rules, for both published surfaces |
| `revision` | in the reviser's request, beside role and voice |

## Notes for people

An HTML comment (`<!-- ... -->`) in either kind of document is for people and
never reaches a model. An unclosed comment fails the run.

## Refused, never guessed

Two stream contracts for one role, one `stream_id` in two contracts, a lens id
declared twice, or any unreadable document anywhere in the client stops the run.

## Evidence

Every run writes `client_contracts.json` — identity, path and SHA-256 digest of
the stream contract and each routed lens — from the same snapshot the run
executed. The selection audit carries the same record.
