---
contract_id: never-blank
version: 1
voice_ref: config/brand_voice.md
forbidden_ref: never-blank-machine-tells
---

# Client Contract — CLIENT: NEVER_BLANK

<!--
CLIENT: NEVER_BLANK (#337). What this client has switched on, and where its
voice and its forbidden wording live. Three things that are often confused and
are kept apart here on purpose (AD-02 §3):

  * **Enabled** is this list: the destinations the client wants published to.
  * **Capable** is whether the Engine has a publisher, package and preflight
    for a destination. Declared in code, not here.
  * **Rollout scope** is which capable destinations today's deployment actually
    publishes to (`src/publishing/release_scope.py`). A deployment setting, not
    a client decision, and temporary by contract.

A destination enabled here that is outside the rollout scope is not an error: it
is generated and not published (`generate_only`), which is what the migration
map means by "until then the remaining destinations are generate_only".

`voice_ref` is a **reference**. The voice document stays human-editable where it
is and is never copied in here.

`forbidden_ref` names the shared list that holds the phrasing this client does
not publish — `lists/machine_tells.md`, by its `list_id`. Add phrases there
rather than here.

Format: docs/engine/CLIENT_CONTRACTS.md. Loader: src/strategy/client_contract.py.
-->

## Enabled destinations

- wix
- linkedin
- facebook
- instagram
- threads
- telegram
