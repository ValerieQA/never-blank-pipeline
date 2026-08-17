"""
LinkedIn publisher — via Zernio unified social API (https://zernio.com).

Why Zernio and not LinkedIn's REST API directly:
  Posting as an ORGANIZATION (company/showcase page) requires LinkedIn's
  Community Management API product, which LinkedIn only grants to legally
  registered entities (LLC, Corporation, 501(c), etc). We don't have one.
  Zernio already holds LinkedIn Partner Program approval and lets any
  page admin connect their company page via OAuth — no entity required.

Setup (one-time, done in the Zernio dashboard, not in code):
  1. zernio.com → sign up → Connections → Connect LinkedIn
  2. Authorize as the "Never Blank" organization (not personal profile)
  3. Copy the connection's Account ID (Connections page, copy icon)
  4. Copy an API key from API Keys page

Required env vars (credential secret only — Issue #100):
  NB_ZERNIO_API_KEY            — Zernio API key (Bearer token)

The Zernio accountId is NOT read here: it comes from the canonical LinkedIn
publication package via the draft package, so the target recorded by the
package is exactly the account the external call posts to.

dry_run    — validate payload, no API call
draft_only — SKIPPED (LinkedIn has no draft concept)
live       — POST https://zernio.com/api/v1/posts → published immediately

Docs: https://docs.zernio.com/platforms/linkedin
"""
import json
from typing import TYPE_CHECKING

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus, UrlProvenance

if TYPE_CHECKING:
    from src.publishing.package import LinkedInPublicationPackage
    from src.strategy.execution_context import LinkedInStrategyView

_ZERNIO_POSTS_URL = "https://zernio.com/api/v1/posts"


class LinkedInPublisher(BasePublisher):
    name = "linkedin"

    def publish(
        self,
        package: "LinkedInPublicationPackage",
        mode: str,
        *,
        strategy_view: "LinkedInStrategyView | None" = None,
    ) -> PublishResult:
        # Issue #101: exact frozen package in, internal representation derived
        # here — no mutable object can diverge from the authorized digest.
        if strategy_view is not None and package.configuration_identity != strategy_view.identity:
            return self._fail(
                "package configuration identity does not match the LinkedIn strategy view"
            )
        draft = DraftPackage.from_linkedin_package(package)
        import os

        # Credential secret — environment-only (readiness gate is Issue #101).
        api_key    = os.getenv("NB_ZERNIO_API_KEY", "")
        # Target identity — package-derived (Issue #100): never re-read from
        # the environment after canonical package construction.
        account_id = draft.linkedin_account_id

        missing = [k for k, v in {
            "NB_ZERNIO_API_KEY":             api_key,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")
        if not account_id:
            return self._fail(
                "Missing package target identity: ['linkedin_account_id']"
            )

        if mode == "draft_only":
            return self._skip("LinkedIn does not support draft posts — skipped in draft_only mode")

        text      = draft.linkedin_text
        image_url = draft.image_for("linkedin")
        has_image = bool(image_url)
        if not text:
            return self._fail("linkedin.txt is empty")

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — {len(text)} chars, "
                    f"image={'yes' if has_image else 'none (text-only post)'}, "
                    f"via Zernio accountId={account_id}"
                ),
            )

        # Build Zernio post payload
        platform_entry: dict = {
            "platform":  "linkedin",
            "accountId": account_id,
        }

        post: dict = {
            "content":    text,
            "platforms":  [platform_entry],
            "publishNow": True,
        }

        if has_image:
            post["mediaItems"] = [{"type": "image", "url": image_url}]

        code, resp, _ = _fetch(
            _ZERNIO_POSTS_URL,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            body=json.dumps(post).encode(),
        )

        if code in (200, 201):
            post_obj = resp.get("post", resp) if isinstance(resp, dict) else {}
            post_id  = post_obj.get("_id") or post_obj.get("id") or ""

            # Try to surface a direct LinkedIn URL if Zernio returns the per-platform
            # result (varies by response shape); fall back to the LinkedIn feed.
            post_url = ""
            platform_results = post_obj.get("platforms") or post_obj.get("results") or []
            if isinstance(platform_results, list):
                for p in platform_results:
                    if isinstance(p, dict) and p.get("platform") == "linkedin":
                        post_url = p.get("url") or p.get("postUrl") or ""
                        break

            note = "(with image, via Zernio)" if has_image else "(text-only, via Zernio)"

            # Issue #108: a 2xx without a real publication ID is not a
            # publication. No identifier is invented, exactly as the Wix
            # contract requires — the run stays honest about having no proof.
            if not str(post_id).strip():
                return self._fail(
                    "Zernio returned success but no publication ID — "
                    "the post cannot be identified and is not recorded as published"
                )

            # The generic LinkedIn feed is not the created post's URL. When
            # Zernio returns no per-platform URL the publication is still real,
            # but its URL is truthfully unavailable rather than substituted.
            # LinkedIn has no legitimate locally-derived form (unlike the
            # accepted Wix base+slug fallback), so only two states apply.
            result = self._published(
                external_id=str(post_id).strip(),
                url=post_url or None,
                raw_path=note,
            )
            result.url_provenance = (
                UrlProvenance.PROVIDER_CONFIRMED if post_url
                else UrlProvenance.UNAVAILABLE
            )
            return result

        err_msg = resp.get("message", resp.get("error", resp.get("_raw", "")))[:200] if isinstance(resp, dict) else str(resp)[:200]

        # 409 = Zernio's own duplicate-content window (24h). It proves that a
        # duplicate exists, but never which post — so it is neither a proven
        # publication nor a proven reuse (Issue #108). It is recorded as its
        # own state: not successful, not complete, and never able to suppress
        # a later publication.
        if code == 409:
            return PublishResult(
                platform=self.name,
                status=PublishStatus.PROVIDER_DUPLICATE,
                error_message=(
                    "Zernio 409: provider reported duplicate content — "
                    f"no publication is proven by this response ({err_msg[:120]})"
                ),
            )

        return self._fail(f"Zernio HTTP {code}: {err_msg}")
