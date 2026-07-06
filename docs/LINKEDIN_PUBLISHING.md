# LinkedIn Publishing — via Zernio

**Status:** Live. Changed 2026-07-06.

## Why not LinkedIn's API directly

`src/publishing/linkedin.py` used to call LinkedIn's REST API
(`/rest/posts`) directly with a personal OAuth token. That worked for
posting as a person, but Never Blank posts as an **organization** (its
LinkedIn company page), and LinkedIn only grants the API product required
for organization posting (Community Management API) to legally registered
entities (LLC, Corporation, 501(c), etc). We don't have one, so every
attempt to post as the organization returned:

```
HTTP 400: Organization Or Events permissions must be used when using
organization as author
```

## The fix

`src/publishing/linkedin.py` now posts through [Zernio](https://zernio.com),
a third-party unified social API that already holds LinkedIn Partner Program
approval. Connecting the Never Blank LinkedIn page to Zernio is a normal
OAuth click in the Zernio dashboard — no LinkedIn app review, no entity
registration required.

**Required env vars** (see `.env.example` for setup instructions):
- `NB_ZERNIO_API_KEY` — Zernio API key (Bearer token)
- `NB_ZERNIO_LINKEDIN_ACCOUNT_ID` — Zernio's internal ID for the connected
  "Never Blank" LinkedIn organization

**Removed:** `NB_LINKEDIN_ACCESS_TOKEN`, `NB_LINKEDIN_CLIENT_ID`,
`NB_LINKEDIN_CLIENT_SECRET`, `NB_LINKEDIN_AUTHOR_URN` — no longer read
anywhere in the codebase; safe to delete from GitHub Secrets.

**Also updated:** all 6 GitHub Actions workflows that publish
(`connectivity_audit.yml`, `daily_signal_research.yml`,
`generate_and_publish.yml`, `live_publish_test.yml`, `publish.yml`,
`scheduled_publish.yml`), `scripts/test_publishers.py`'s LinkedIn audit
check, and `src/utils/env_validator.py`'s `ALL` secrets list.

## Zernio pricing note

First 2 connected accounts are free; $6/account after that, up to 10.
Never Blank currently has 1 connected account (LinkedIn).

## If this breaks again

Check `docs.zernio.com/platforms/linkedin` for API changes first — this
integration is a thin wrapper around Zernio's `/api/v1/posts` endpoint, not
a deep LinkedIn integration. If Zernio's response shape changes, the
`post_url` extraction logic in `LinkedInPublisher.publish()` may need
updating (it looks for `platforms`/`results` arrays in the response, which
aren't formally documented as stable).
