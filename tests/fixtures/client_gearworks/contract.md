---
contract_id: gearworks-supply
version: 1
---

# Client Contract — CLIENT: GEARWORKS SUPPLY (fixture)

<!--
The second client's contract, and only as much of one as the Replace-the-client
test needs. What is here is what a *running* client must state and Gearworks had
no reason to state before: the static words its posts are tagged with.

Since #368 the hashtag vocabulary is client configuration and nothing else, and
`src/publishing/hashtags.py` is a consumer of it. So a client that publishes
declares its own words, and the words below are Gearworks' — not Never Blank's.
That is the point of this fixture: replacing the client replaces the tags too,
and no Engine module carries a tag of its own to fall back on.

The rest of the contract (`voice_ref`, `forbidden_ref`, `## Enabled
destinations`, the #363 rule sections) is deliberately absent. This fixture
exercises the document-driven stages, not `client_contract()`, and inventing
configuration no test reads would put values here that nobody decided.
-->

## Hashtag vocabulary

- #GearworksSupply
- #ShopFloor
