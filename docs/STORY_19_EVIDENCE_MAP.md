# Story #19 evidence map — production LinkedIn publishing

Issues #108 (truthful publication results) and #109 (retry idempotency). Each
acceptance criterion is exactly one of: `SATISFIED` / `SUPERSEDED` /
`DEFERRED-LIVE`.

**Nothing in this document is evidence that a real LinkedIn post was
published.** Every deterministic proof below comes from fake transports;
criteria requiring a real Zernio/LinkedIn account are `DEFERRED-LIVE`.

## Criterion map

**1. "LinkedIn/Zernio credentials and target configuration pass controlled
preflight."**
`SATISFIED` (#100 + #101). `NB_ZERNIO_API_KEY` presence is a per-channel
preflight verdict recorded as a boolean; the Zernio `account_id` is package
data, so the adapter never re-reads target identity from the environment. A
missing credential blocks LinkedIn only. Real credential *validity* against
Zernio is `DEFERRED-LIVE`.

**2. "A validated current-run LinkedIn package publishes successfully."**
`DEFERRED-LIVE`. Deterministically proven: the frozen
`LinkedInPublicationPackage` receives preflight `ALLOW` and is the exact
object handed to the adapter, whose Zernio payload is derived only from that
package plus the API key.

**3. "The exact approved text and visual/link are verified on the created
post."**
`DEFERRED-LIVE` for the created post. Deterministically proven upstream: the
body comes only from the accepted canonical composition (no `reading` or
article fallback, Story #14), the optional visual follows Story #15 passport
semantics, and #108 proves the outbound `content`, `accountId` and
`mediaItems` are exactly the package's.

**4. "A real publication ID and verifiable post URL are captured, or the run
remains explicitly incomplete."**
`SATISFIED` (#108). A 2xx without a real publication ID fails closed — the
`external_id="unknown"` fabrication is gone. The generic
`https://www.linkedin.com/feed/` is never recorded as the created post's URL;
a real ID with no returned URL stays `PUBLISHED` with `UrlProvenance`
`unavailable`, and LinkedIn never invents a `locally_derived` URL (there is no
legitimate construction, unlike the accepted Wix base+slug fallback).

**Provider-duplicate semantics**: a Zernio `409` is its own typed
`PROVIDER_DUPLICATE` state — it proves a duplicate exists but never *which
post*, so it is neither `PUBLISHED` nor `REUSED`, is absent from both the OK
and the completed status sets (the run stays incomplete, no history entry is
written), and it can never suppress a later publication. A 409 encountered
after a real attempt is **never** retroactively reinterpreted as a reuse.

**5. "Safe retry behavior prevents duplicates."**
`SATISFIED` for sequential retry (#109). The Release 1 LinkedIn publication
identity is:

```
(signal_id, accepted_linkedin_body_digest, linkedin_account_id)
```

where the digest is `sha256` of the accepted `linkedin_body` persisted in
`linkedin_composition.json`. The middle component is the accepted **body**,
not the article: a different composition of the same article is a different
publication payload and publishes normally. `run_id` and
`configuration_identity` are excluded — configuration remains mandatory
provenance, never a republish switch.

The accepted body is resolved through the publication's `generation_run_id`,
because a `--from-package` publication run never writes its own composition;
a legitimate reuse candidate would otherwise be silently unmatchable.

A candidate may suppress only when **all** hold: LinkedIn status is literally
`PUBLISHED`; the provider publication ID is real and non-empty; the run passes
Story #16 `verify_run_provenance` through `publication_results`; its Story #17
verdict is proven to be its own (run, signal, authoritative configuration,
`ALLOW` LinkedIn channel, target account); the canonical package reconstructs
through the existing #100 builder to the digest that verdict recorded; the
accepted-body digest matches; and the account matches. `FAILED`, `BLOCKED`,
`SKIPPED`, `REUSED`, `PROVIDER_DUPLICATE` and `PUBLISHED`-without-ID never
suppress.

On a proven match: **zero Zernio calls**, a typed `REUSED` result preserving
the prior run ID, publication ID, URL and URL provenance, current run identity
kept separate, and no second publication-history entry.

Unusable evidence — malformed, missing, foreign, corrupted or unverifiable —
yields sanitized typed reason codes and a count, never suppression, never a
failed current run, and scanning continues.

**Reusable URL evidence is validated, never coerced.** Because `REUSED`
preserves the prior URL and provenance verbatim, evidence that cannot be read
exactly is not reusable: a missing, misspelled or foreign `url_provenance`, a
non-string `url`, or a provenance that contradicts its URL (claiming
provider-confirmed with no URL, claiming unavailable while carrying one, or
claiming a `locally_derived` form LinkedIn has no legitimate construction for)
is recorded as `prior_url_evidence_invalid` and never becomes a match. The
legitimate URL-less shape is preserved: a real publication ID with
`url = null` and `url_provenance = unavailable` **is** proven evidence and may
be reused, since URL availability is not part of the duplicate identity — and
on reuse the unavailable provenance is preserved exactly, never upgraded and
never replaced by a constructed link.

**Concurrency limitation, stated plainly**: this is deterministic *sequential*
retry idempotency. Two runs started concurrently can both observe "no prior
success" and both publish. Zernio's 24-hour duplicate window is **secondary
provider behavior, not Never Blank's guarantee** — and by product decision a
409 never becomes a proven reuse. No lock, mutex service, external database or
cross-channel locking was introduced.

**6. "Provider errors are normalized without exposing secrets."**
`SATISFIED` (#108). Errors are built from the provider's response body only;
the API key appears in no result, message, log or persisted artifact, and
unusable-evidence reporting is limited to typed reason codes and a count.

**7. "Contract tests use fake clients and cannot publish unintended content."**
`SATISFIED` (#108 + #109). `tests/test_linkedin_publisher.py` is the dedicated
adapter contract suite LinkedIn previously lacked, and
`tests/test_linkedin_idempotency.py` covers the retry boundary. Every test
patches the adapter's only network seam, so none can reach Zernio.

## Superseded / clarified original wording

- *"The adapter has not been proven to reject packages that failed the
  complete Release 1 preflight"* — **SUPERSEDED** by #101: rejection is not the
  adapter's job. A blocked channel's publisher is never constructed, and the
  adapter accepts only the frozen authorized package. #109 proves a `BLOCK`
  is not bypassable by idempotency.
- *"Returning the generic LinkedIn feed URL … does not satisfy verifiable
  publication URL requirements"* — resolved by #108 with typed URL provenance.
- *"Retry idempotency and duplicate prevention are not proven"* — proven
  deterministically for sequential retry by #109; concurrent runs remain
  explicitly unguaranteed.

## Deterministic vs live

| Evidence | Kind |
|---|---|
| Truthful publication results, provider-duplicate state, adapter contract suite | deterministic (#108) |
| Duplicate identity, reuse suppression, unusable-evidence handling, zero-call retry | deterministic (#109) |
| A real Zernio/LinkedIn account accepting a real package with real credentials | **live, deferred** |
| The live post's text, visual and URL | **live, deferred** |
| Duplicate prevention observed against the real provider | **live, deferred** |
