"""
Instagram Content Publishing API.

Requires an image (Cloudinary URL).  If no image_url is available,
the publisher returns SKIPPED — other channels are not blocked.

Flow (live):
  1. POST /{ig_user_id}/media  — create media container
  2. POST /{ig_user_id}/media_publish — publish container

dry_run    — validate env + payload, no API call
draft_only — SKIPPED (Instagram has no draft concept)
live       — two-step publish → PUBLISHED

Requires: NB_META_IG_USER_ID, NB_META_FB_PAGE_TOKEN (used as IG token)
"""
import json
import os
import urllib.parse

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus

_GRAPH = "https://graph.facebook.com/v21.0"


class InstagramPublisher(BasePublisher):
    name = "instagram"

    def _publish_impl(self, draft: DraftPackage, mode: str) -> PublishResult:
        ig_user_id = os.getenv("NB_META_IG_USER_ID", "")
        ig_token   = os.getenv("NB_META_FB_PAGE_TOKEN", "")

        missing = [k for k, v in {
            "NB_META_IG_USER_ID":    ig_user_id,
            "NB_META_FB_PAGE_TOKEN": ig_token,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

        if mode == "draft_only":
            return self._skip("Instagram has no draft concept — skipped in draft_only mode")

        image_url = draft.image_for("instagram")
        if not image_url:
            return self._skip(
                "No image_url available. "
                "Run image generation step to upload to Cloudinary first."
            )

        text = draft.instagram_text
        if not text:
            return self._fail("instagram.txt is empty")

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — {len(text)} chars, "
                    f"image={image_url!r}"
                ),
            )

        # Step 1: create media container
        container_params = urllib.parse.urlencode({
            "image_url":    image_url,
            "caption":      text,
            "access_token": ig_token,
        }).encode()

        code, resp, _ = _fetch(
            f"{_GRAPH}/{ig_user_id}/media",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=container_params,
        )
        if code not in (200, 201):
            err = resp.get("error", {}).get("message", resp.get("_raw", ""))[:200]
            return self._fail(f"Container creation HTTP {code}: {err}")

        creation_id = resp.get("id", "")
        if not creation_id:
            return self._fail("Container created but no ID returned")

        # Step 1b: wait for container to finish processing (avoids "Media ID not available")
        import time as _time
        for attempt in range(10):
            _time.sleep(3)
            code_s, status_resp, _ = _fetch(
                f"{_GRAPH}/{creation_id}"
                f"?fields=status_code&access_token={urllib.parse.quote(ig_token)}"
            )
            status_code = status_resp.get("status_code", "")
            if status_code == "FINISHED":
                break
            if status_code in ("ERROR", "EXPIRED"):
                err = status_resp.get("status_code", "")
                return self._fail(f"Container {status_code}: {err}")
            # IN_PROGRESS or unknown: keep waiting
        else:
            return self._fail("Container timed out after 30s — status never FINISHED")

        # Step 2: publish container
        publish_params = urllib.parse.urlencode({
            "creation_id":  creation_id,
            "access_token": ig_token,
        }).encode()

        code2, resp2, _ = _fetch(
            f"{_GRAPH}/{ig_user_id}/media_publish",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=publish_params,
        )
        if code2 not in (200, 201):
            err = resp2.get("error", {}).get("message", resp2.get("_raw", ""))[:200]
            return self._fail(f"Publish HTTP {code2}: {err}")

        media_id = resp2.get("id", "")

        # Fetch permalink (media_id is numeric; shortcode needed for IG URL)
        permalink: str = ""
        if media_id:
            code3, meta, _ = _fetch(
                f"{_GRAPH}/{media_id}?fields=permalink&access_token={urllib.parse.quote(ig_token)}"
            )
            if code3 == 200:
                permalink = meta.get("permalink", "")

        return self._published(
            external_id=media_id,
            url=permalink or f"https://www.instagram.com/",
        )
