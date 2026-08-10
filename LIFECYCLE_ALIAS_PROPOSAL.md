# LIFECYCLE_ALIAS_PROPOSAL.md

## Proposed Rule

Allow `RECOMMENDED_FOR_ARTICLE=true` to activate `article_ready=True`
when the canonical `ARTICLE_READY` field is absent from a signal dict.

## Status

**PENDING PRODUCT OWNER CONFIRMATION** — normalization is NOT active.

The provisional implementation was removed (Option A, commit TBD) because
the product owner has not explicitly confirmed that the two fields are
semantically equivalent.

## Open Question

Is `RECOMMENDED_FOR_ARTICLE=true` semantically equivalent to `ARTICLE_READY=true`?

### Case where they ARE equivalent
Older pipeline runs wrote `RECOMMENDED_FOR_ARTICLE` as the output key after
scoring. A signal with `RECOMMENDED_FOR_ARTICLE=true` was enriched, scored,
and passed all quality checks — functionally identical to `ARTICLE_READY=true`.

### Case where they are NOT equivalent
`RECOMMENDED_FOR_ARTICLE` may mean "selected for editorial consideration"
(top-N by score), NOT "factually verified and ready for article generation".
A signal could have `RECOMMENDED_FOR_ARTICLE=true` but fail enrichment, meaning
`article_ready` should remain `false`. If we alias the two fields, such a
signal bypasses the factual-readiness gate.

## Impact of NOT normalizing

The controlled run uses `synthetic-signal` mode, which always sets
`ARTICLE_READY=true` explicitly. No signals in the current `signals_active.jsonl`
have `RECOMMENDED_FOR_ARTICLE` without `ARTICLE_READY` (confirmed by field audit).
The normalization is therefore not needed for any current production path.

## Activation Instructions (when confirmed)

1. Uncomment the alias block in `src/lifecycle/signal_lifecycle.py::_resolve_article_ready()`
2. Add a test to `tests/test_lifecycle_normalization.py` verifying the alias
3. Document the product owner's confirmation date and context here

## Product Owner Confirmation Required

- [ ] Confirm: `RECOMMENDED_FOR_ARTICLE=true` means factual enrichment passed
- [ ] Confirm: `RECOMMENDED_FOR_ARTICLE=true` is safe to treat as `ARTICLE_READY=true`
- [ ] Date confirmed:
- [ ] Confirmed by:
