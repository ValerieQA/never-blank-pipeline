"""
Facebook Page publisher — Graph API v21.0.

If image_url is available: POST /{page_id}/photos (image + caption).
Otherwise:                 POST /{page_id}/feed  (text only).

dry_run    — validate payload, no API call
draft_only — SKIPPED (Facebook has no draft concept via API)
live       — PUBLISHED

Requires: NB_META_FB_PAGE_ID, NB_META_FB_PAGE_TOKEN
"""
import os
import urllib.parse

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus

_GRAPH = "https://graph.facebook.com/v21.0"


class FacebookPublisher(BasePublisher):
    name = "facebook"

    def _publish_impl(self, draft: DraftPackage, mode: str, **kwargs) -> PublishResult:
        page_id    = os.getenv("NB_META_FB_PAGE_ID", "")
        page_token = os.getenv("NB_META_FB_PAGE_TOKEN", "")

        missing = [k for k, v in {
            "NB_META_FB_PAGE_ID":    page_id,
            "NB_META_FB_PAGE_TOKEN": page_token,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

        if mode == "draft_only":
            return self._skip("Facebook does not support draft posts — skipped in draft_only mode")

        text = draft.facebook_text
        if not text:
            return self._fail("facebook.txt is empty")

        image_url = draft.image_for("facebook")
        has_image = bool(image_url)

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — {len(text)} chars, "
                    f"image={'yes (' + image_url + ')' if has_image else 'none (text-only post)'}"
                ),
            )

        if has_image:
            # Photo post: image + caption
            params = {
                "url":          image_url,
                "caption":      text,
                "access_token": page_token,
            }
            endpoint = f"{_GRAPH}/{page_id}/photos"
        else:
            # Text-only feed post
            params = {
                "message":      text,
                "access_token": page_token,
            }
            endpoint = f"{_GRAPH}/{page_id}/feed"

        code, resp, _ = _fetch(
            endpoint,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urllib.parse.urlencode(params).encode(),
        )

        if code in (200, 201):
            post_id = resp.get("post_id", resp.get("id", ""))
            url = f"https://www.facebook.com/{post_id}" if post_id else ""
            return self._published(external_id=post_id, url=url)

        err = resp.get("error", {}).get("message", resp.get("_raw", ""))[:200]
        return self._fail(f"HTTP {code}: {err}")
