# Story #18 evidence map — production Wix publishing

Issues #104 (Wix test contract and accepted baseline) and #105 (retry
idempotency and URL provenance). Each acceptance criterion is exactly one of:
`SATISFIED` / `SUPERSEDED` / `DEFERRED-LIVE`.

**Nothing in this document is evidence of a real Wix publication.** All
deterministic proof below comes from fake transports; criteria that require a
real Wix site are marked `DEFERRED-LIVE` and remain on the live-verification
track.

## Criterion map

**1. "All relevant Wix tests pass or obsolete tests are formally replaced with
justified coverage."**
`SATISFIED` (#104). The five accepted-baseline Wix failures were re-run on the
authorized base and classified `STALE_TEST` before any edit: four
`TestWixMediaImport` tests encoded the pre-polling contract, and
`test_draft_media_missing_blocks_publish` asserted error prose the adapter no
longer emits. All five were rewritten against the current contract with their
node IDs preserved, and exactly those five IDs were removed from
`tests/accepted_full_suite_failures.txt` (**9 → 4**). Zero production changes.
New coverage: readiness confirmed immediately, terminal provider failure
state, and readiness never confirmed within the poll budget.

**2. "A validated current-run package publishes through the Wix adapter."**
`DEFERRED-LIVE`. Everything deterministic is proven: a validated current-run
`WixPublicationPackage` (#100) receives preflight `ALLOW` (#101) and is the
exact frozen object handed to `WixPublisher.publish`. The remaining proof —
that a real Wix site accepts it with real credentials — is live work.

**3. "The published post contains the expected article, metadata, and exact
approved visual."**
`DEFERRED-LIVE` for the published artefact itself. Deterministically proven:
the payload is derived only from the authorized package (title, slug, body,
cover URL, target), the cover image identity is verified against the imported
Wix file ID before publishing, and a draft whose media identity cannot be
confirmed is never published (#104 behavioral coverage).

**4. "Wix content ID and final public URL are captured and verified."**
`SATISFIED` in code. A 2xx publish response without a post ID still fails
closed — the draft ID is never stored as a content ID. URL capture is now
truthful (#105): the result carries a typed `UrlProvenance` —
`provider_confirmed` (Wix returned the URL), `locally_derived`
(`NB_WIX_SITE_BASE_URL + /blog/{slug}` constructed after Wix confirmed the
post but returned no URL — the accepted Release 1 fallback), or `unavailable`
(no provenance-confirmed URL). A locally constructed URL is never reported as
provider-confirmed. Real-site URL correctness is `DEFERRED-LIVE`.

**5. "Safe retry behavior prevents duplicate posts."**
`SATISFIED` for sequential retry (#105). The Release 1 publication identity is
`(signal_id, source_article_digest, wix_site_id)`. `run_id` is excluded
because a retry deliberately creates a new run; `configuration_identity` is
excluded so a configuration revision cannot become an implicit republish
channel (it remains mandatory provenance in #100/#101/#16);
`owner_member_id` is excluded because author metadata must not unlock a
duplicate. Only a prior `PUBLISHED` result with a real content ID suppresses a
publication — `DRAFT_CREATED`, `FAILED`, `BLOCKED` and `SKIPPED` never do, and
no draft-resume behavior was added. On a proven match the run performs no
media import, no draft creation and no publish call, and records a typed
`REUSED` result preserving the prior run ID, content ID, URL and URL
provenance, without appending a second publication-history entry.

**Concurrency limitation, stated plainly**: this is deterministic *sequential*
retry idempotency. Two runs started concurrently can both observe "no prior
success" and both publish; per-run create-once artifacts provide no mutual
exclusion, and the Wix Blog v3 calls this adapter makes expose no
provider-native idempotency key. Solving that needs a lock or provider-side
key and is deliberately out of Release 1 scope — not silently claimed as
solved.

**6. "Secrets are absent from code, logs, reports, and fixtures."**
`SATISFIED`. No log call in `wix.py`, `wix_media.py` or `linkedin.py` emits
headers, keys or auth values; canonical packages (#100) and the preflight
verdict (#101) carry no secrets, and unusable prior-evidence reporting (#105)
is limited to typed reason codes and a count — no raw artifact content reaches
logs, results or artifacts.

**7. "Failure paths return normalized actionable results and never report
false success."**
`SATISFIED`. Typed Wix errors, fail-closed media verification, run-identity
normalization on every result, `BLOCKED` channels never counted as published,
no publication evidence fabricated for a blocked run, and — new in #105 —
`REUSED` is deliberately not an "ok" status, so a retry can never be recorded
as a fresh provider success.

## Superseded / clarified original wording

- *"Previously reported full-suite failures include Wix media import and draft
  verification tests"* — resolved by #104; they were stale tests, not adapter
  defects, and the accepted baseline is now 4.
- *"A Never Blank-specific URL fallback remains inside the adapter and needs
  explicit acceptance or replacement"* — **accepted with truthful provenance**
  by product decision: the fallback stays, and the result states that the URL
  was locally derived.
- *"Retry idempotency and duplicate prevention are not proven as an end-to-end
  contract"* — now proven deterministically for sequential retry; concurrent
  runs remain explicitly unguaranteed.

## Deterministic vs live

| Evidence | Kind |
|---|---|
| Test-contract restoration, baseline 9 → 4 | deterministic (#104) |
| Retry identity, reuse suppression, unusable-evidence handling | deterministic (#105) |
| URL provenance states at the adapter boundary | deterministic (#105) |
| A real Wix site accepting a real package with real credentials | **live, deferred** |
| The live post's rendered article, metadata and cover image | **live, deferred** |
| Live duplicate prevention observed against a real site | **live, deferred** |
