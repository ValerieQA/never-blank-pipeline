# Canonical visual contract and fail-closed channel gate

Issue #96 / Story #15. `src.visual.contract` plus the canonical entrypoint
visual gate.

## Release 1 product rule (fixed, not strategy-configurable)

- The **Wix** visual (the `blog` master derivative, 1920×1080) is
  **required**: if it cannot be truthfully produced, uploaded, and validated
  as a publishable remote asset, the run fails closed before Wix
  packaging/publication.
- The **LinkedIn** visual (1200×628) is **optional**: a genuinely
  absent/not-requested LinkedIn visual leaves the valid text-only LinkedIn
  path open. But an **attempted** LinkedIn visual that failed generation,
  upload, or validation is never silently converted into "text-only
  success" — it fails closed. Optionality never hides failures.

## Business objective

A visual reported by Never Blank must be a real publication asset with a
truthful passport: which run produced it, which content it belongs to, how it
was produced, which design version produced it, which channel derivative it
represents, and whether it is actually valid for publication. Visual success
is never claimed merely because an image-generation function returned
something.

## Remote asset invariant (critical correction)

A local filesystem path is never a publishable remote asset URL. The
canonical fallback in `prepare_content` that substituted the local render
path when Cloudinary upload failed is removed: upload failure now stays an
explicit failure (`url: "", upload_failed: true`), and the gate rejects any
non-`https` URL for a publishable derivative.

## Canonical visual passport

One immutable run-scoped `visual_assets.json` (create-once, standard atomic
protocol): schema version, `run_id`, `signal_id`, `source_article_digest`
(SHA-256 of the accepted article body — the stable current-run content
identity shared with the LinkedIn composition record), provider (derived
truthfully from the asset host), render method (passed through from the
image pipeline), timestamp, design version, overall status, LinkedIn visual
state (`valid` / `not_requested`), master asset URL, and per-channel
derivative records (channel, remote URL, width, height, format, status).
Only Release 1 channels (Wix, LinkedIn) are recorded — no
Instagram/Facebook/Threads/Telegram visual behavior is introduced.
`verify_visual_assets_record()` fails closed on cross-run or source drift.

## Result validation

The gate validates the **resulting** derivative, not the requested render
parameters: when the local rendered file is available its actual pixel
dimensions and format are read (PIL) and must match the channel requirement;
the recorded URL must be a publishable `https` URL; `upload_failed` markers,
malformed size metadata, unsupported formats, stale design versions, and
missing entries all fail closed with distinct reasons (generation failure,
upload failure, validation failure, missing — never collapsed into `None`).

## Wiring

The gate runs in both canonical branches of the entrypoint — fresh
generation (after the LinkedIn composition gate, before `generated.json`)
and `--from-package` reuse (after image preparation, before publication).
`VisualArtifactRequest` is now active (`blocked=False`); rendering continues
to use the existing image pipeline and the master→derivative architecture.

## Deferred live verification

Real Cloudinary/Wix/LinkedIn asset behavior is deferred live verification
(Stories #19/#21) and is not faked here. Legacy image registry/library
cleanup is out of scope (Story #16 owns broader provenance).
