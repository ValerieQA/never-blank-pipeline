# Phase 5D — Controlled Live Publish Test

**Date:** 2026-06-20  
**Run ID:** `20260620_183113`

## Summary

First end-to-end live publish across all six channels.  
**5 of 6 channels published successfully.**

| Channel | Status | Live URL |
|---------|--------|----------|
| Wix | ✅ PUBLISHED | Wix dashboard (id: `3adb55fc-19a2-4477-ab90-9b57daf0e01e`) |
| Telegram | ✅ PUBLISHED | [t.me/never_blank_inneros/7](https://t.me/never_blank_inneros/7) |
| Facebook | ✅ PUBLISHED | [Post](https://www.facebook.com/1219637131228622_122110184097356169) |
| Instagram | ✅ PUBLISHED | [instagram.com/p/DZ0V48Bjk8o/](https://www.instagram.com/p/DZ0V48Bjk8o/) |
| Threads | ✅ PUBLISHED | [threads.net/t/18125757235646787](https://www.threads.net/t/18125757235646787) |
| LinkedIn | ❌ FAILED | One manual step required (see below) |

## LinkedIn — Manual Step Required

**Blocker:** The `w_member_social` OAuth scope does not expose a user identity claim via token introspection. The pipeline cannot resolve the author URN automatically.

**Fix (one-time):**
1. Go to [LinkedIn Developer Portal](https://www.linkedin.com/developers/tools/oauth/token-generator)
2. Generate a token with any scope — the JSON response includes a `"member"` field containing your URN (e.g. `urn:li:person:XXXXXXX`)
3. Add that value to GitHub Secrets as `NB_LINKEDIN_AUTHOR_URN`

Once the secret is set, LinkedIn publishes without any further changes.

## Infrastructure Delivered (Phases 5B–5D)

| Component | File |
|-----------|------|
| Publisher base + DraftPackage | `src/publishing/base.py` |
| PublishResult dataclass | `src/publishing/result.py` |
| Wix Blog v3 adapter | `src/publishing/wix.py` |
| LinkedIn adapter (image upload) | `src/publishing/linkedin.py` |
| Facebook adapter | `src/publishing/facebook.py` |
| Instagram adapter (polling) | `src/publishing/instagram.py` |
| Threads adapter | `src/publishing/threads.py` |
| Telegram adapter | `src/publishing/telegram.py` |
| Image pipeline (AI + fallback) | `src/publishing/image_pipeline.py` |
| Publisher runner | `scripts/publish.py` |
| Image generator | `scripts/generate_image.py` |
| Live test runner | `scripts/live_publish_test.py` |
| Content fixture builder | `scripts/create_fixture.py` |
| Publisher workflow | `.github/workflows/publish.yml` |
| Live test workflow | `.github/workflows/live_publish_test.yml` |
| Image generation workflow | `.github/workflows/generate_image.yml` |

## Phase 6 Readiness

The pipeline is ready for scheduled autonomous publishing.  
LinkedIn will join the rotation once `NB_LINKEDIN_AUTHOR_URN` is set in GitHub Secrets.

Full test report: [`reports/live_publish_test.md`](reports/live_publish_test.md)
