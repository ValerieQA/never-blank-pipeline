---
vocab_id: reason_categories
version: 1
---

# Reason categories

The closed vocabulary a run ends a scope with. A RunSummary records the ARP
outcome, a machine state code and one of these — **never free text** (Step 3
§4.2). No money, no raw error, no prompt.

These are the reasons that are decided *outside* a route. The per-route reasons
are the route causes in the stage-topology registry
(`src/editorial_core/topology.py`), which is their one authority; a terminal
outcome reached by exhausting a counter is recorded with its route's cause, not
with a term from this file.

## Terms

- `knowledge_register_invalid` — the register failed validation at run start
  (§8). The run does not start. Fail-closed, and no human is needed during the
  run: the broken record is fixed offline.
- `mandatory_knowledge_exceeds_capacity` — the knowledge that may never be
  truncated did not fit the request, so the stage failed closed before the model
  call (§9, patch S4-R1). No incomplete hard-policy surface is ever sent.
- `no_admissible_interpretation` — the boundary admits nothing (E-09).
- `no_admissible_strategy` — no candidate survived selection for any destination
  of the unit.
- `idempotency_authority_unavailable` — publication could not establish whether
  the text was already published.
- `publication_possibly_exists` — an intent from an earlier run has no marker,
  and no external lookup confirmed that no publication exists.
