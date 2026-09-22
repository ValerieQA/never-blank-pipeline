---
vocab_id: destinations
version: 1
---

# Destinations (E-12)

The six surfaces the engine writes for. A condition reads one as
`destination is <name>`.

This list mirrors the one authorization boundary in code
(`src/publishing/release_scope.py`), and the validator refuses the register if
the two ever disagree: a duplicated list is a list that drifts (#227). Which of
them an automatic run may *publish* to is that module's business, not this
file's — a record applies to a destination whether or not today's rollout scope
publishes it.

Static destination knowledge — length norms, policy, ranking behaviour — is not
here either. It lives in `K-DST-*` records.

## Terms

- `wix` — the canonical article surface. Published first, because other
  destinations may link to it.
- `linkedin` — the native derivative.
- `facebook`
- `instagram` — needs an image.
- `threads`
- `telegram`
