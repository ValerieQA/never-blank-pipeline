# Investigate: empty `wix_url` on latest generated package

Package `reports/content_packages/76cddc4be3a57826_generated.json`
(strategy `2026-07-presence-debt-campaign-1`, generated
2026-07-23T22:00:17Z — the laptop-shortage / Samsung article) has an empty
`wix_url` field, and its `content_id` does not appear in
`strategy/published_content_index.jsonl` at all.

Please determine why, and report back plainly rather than assuming the
most likely explanation is the actual one. Specifically check:

1. **Was Wix publishing simply disabled for this run?**
   `scripts/research/publish_packages.py` skips its whole publishing stage
   if `NB_RESEARCH_PUBLISH_ENABLED` is not `"true"`. If that's what
   happened here, this isn't a bug — say so directly, and confirm whether
   that's the intended state right now or should be flipped on.
2. **If publishing was attempted, did the Wix publisher fail silently?**
   Check logs/exceptions around the Wix publish step for this
   `content_id` — a swallowed exception would also produce this exact
   symptom (empty `wix_url`, no index entry) without surfacing an error
   anywhere visible.
3. **Was this package only generated (e.g. via a dry-run, preview, or
   manual/local script invocation) and never actually run through the
   publish path at all?** If so, that's expected — just confirm it.
4. **Was this article actually published by Val by hand, directly in the
   Wix editor**, separately from the pipeline? If yes, please reconcile:
   the repo's `wix_url` field and `published_content_index.jsonl` should
   reflect what's actually live, not silently disagree with reality. Add
   the correct data if that's the case.

Whatever the answer turns out to be, report it clearly — including if it's
simply "publishing was off for this run, nothing is broken."
