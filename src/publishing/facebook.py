"""
Facebook Page publisher — Graph API /v21.0/{page_id}/feed.

dry_run    — validate payload, no API call
draft_only — SKIPPED (Facebook has no draft concept via API)
live       — POST to page feed → PUBLISHED

Requires: NB_META_FB_PAGE_ID, NB_META_FB_PAGE_TOKEN
"""
import json
import os
import urllib.parse

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus

_GRAPH = "https://graph.facebook.com/v21.0"


class FacebookPublisher(BasePublisher):
    name = "facebook"

    def publish(self, draft: DraftPackage, mode: str) -> PublishResult:
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

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=f"dry_run: payload valid — {len(text)} chars",
            )

        params: dict = {"message": text, "access_token": page_token}

        # Attach image if available (as link preview; full photo upload is V2)
        if draft.image_url:
            params["link"] = draft.image_url

        body = urllib.parse.urlencode(params).encode()
        code, resp, _ = _fetch(
            f"{_GRAPH}/{page_id}/feed",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )

        if code in (200, 201):
            post_id = resp.get("id", "")
            url = f"https://www.facebook.com/{post_id}" if post_id else ""
            return self._published(external_id=post_id, url=url)

        err = resp.get("error", {}).get("message", resp.get("_raw", ""))[:200]
        return self._fail(f"HTTP {code}: {err}")
