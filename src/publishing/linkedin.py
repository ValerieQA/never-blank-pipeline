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

Required env vars:
  NB_ZERNIO_API_KEY            — Zernio API key (Bearer token)
  NB_ZERNIO_LINKEDIN_ACCOUNT_ID — Zernio accountId for the connected
                                  "Never Blank" LinkedIn organization

dry_run    — validate payload, no API call
draft_only — SKIPPED (LinkedIn has no draft concept)
live       — POST https://zernio.com/api/v1/posts → published immediately

Docs: https://docs.zernio.com/platforms/linkedin
"""
import json
from typing import TYPE_CHECKING

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus

if TYPE_CHECKING:
    from src.strategy.execution_context import LinkedInStrategyView

_ZERNIO_POSTS_URL = "https://zernio.com/api/v1/posts"


class LinkedInPublisher(BasePublisher):
    name = "linkedin"

    def publish(
        self,
        draft: DraftPackage,
        mode: str,
        *,
        strategy_view: "LinkedInStrategyView | None" = None,
    ) -> PublishResult:
        if strategy_view is not None:
            draft.require_configuration_identity(
                strategy_view.identity, "linkedin-publisher"
            )
        import os

        api_key    = os.getenv("NB_ZERNIO_API_KEY", "")
        account_id = os.getenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", "")

        missing = [k for k, v in {
            "NB_ZERNIO_API_KEY":             api_key,
            "NB_ZERNIO_LINKEDIN_ACCOUNT_ID":  account_id,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

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
            return self._published(
                external_id=str(post_id) or "unknown",
                url=post_url or "https://www.linkedin.com/feed/",
                raw_path=note,
            )

        err_msg = resp.get("message", resp.get("error", resp.get("_raw", "")))[:200] if isinstance(resp, dict) else str(resp)[:200]

        # 409 = duplicate content within 24h — content was already posted successfully.
        # Treat as SKIPPED rather than FAILED so the pipeline doesn't halt on re-runs.
        if code == 409:
            return self._skip(f"Zernio 409: duplicate content — post already exists ({err_msg[:120]})")

        return self._fail(f"Zernio HTTP {code}: {err_msg}")
