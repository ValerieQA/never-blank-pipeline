"""
LinkedIn publisher — REST API /rest/posts.

If image_url is available:
  1. Initialize image upload  (POST /rest/images?action=initializeUpload)
  2. Upload image bytes        (PUT uploadUrl)
  3. Post with media reference (POST /rest/posts with content.media.id)
Otherwise: text-only post.

dry_run    — validate payload, no API call
draft_only — SKIPPED (LinkedIn has no draft concept)
live       — POST /rest/posts → PUBLISHED

Author URN is resolved via token introspection (sub field).
Requires: NB_LINKEDIN_ACCESS_TOKEN, NB_LINKEDIN_CLIENT_ID, NB_LINKEDIN_CLIENT_SECRET
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from src.publishing.base import BasePublisher, DraftPackage, _fetch, _fetch_h
from src.publishing.result import PublishResult, PublishStatus

_LI_VERSION = "202601"
_LI_HEADERS_BASE = {
    "LinkedIn-Version":          _LI_VERSION,
    "X-Restli-Protocol-Version": "2.0.0",
}


def _get_author_urn(token: str, client_id: str, client_secret: str) -> tuple[str, str]:
    """
    Resolve the LinkedIn author URN for posting.

    Resolution order:
      1. NB_LINKEDIN_AUTHOR_URN env var (most reliable — set this)
      2. Token introspection `sub` field (only present with openid scope)

    Returns (urn, error_message).
    """
    # 1. Explicit env var — always preferred
    static_urn = os.getenv("NB_LINKEDIN_AUTHOR_URN", "")
    if static_urn:
        return static_urn if static_urn.startswith("urn:li:") else f"urn:li:person:{static_urn}", ""

    # 2. Introspection (requires openid scope — may not be available)
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    code, resp, _ = _fetch(
        "https://www.linkedin.com/oauth/v2/introspectToken",
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        body=urllib.parse.urlencode({
            "token":         token,
            "client_id":     client_id,
            "client_secret": client_secret,
        }).encode(),
    )
    if code != 200:
        return "", f"Introspection HTTP {code}: {resp.get('error_description', '')[:120]}"
    sub = resp.get("sub", "")
    if sub:
        return f"urn:li:person:{sub}", ""

    return (
        "",
        "Cannot resolve LinkedIn author URN. "
        "Add NB_LINKEDIN_AUTHOR_URN to GitHub Secrets. "
        "Find it: LinkedIn Developer Portal → Tools → OAuth 2.0 tools → "
        "generate a token, the API returns your member URN, "
        "OR check your profile URL and look for the numeric id."
    )


def _upload_image_to_linkedin(
    author_urn: str,
    token: str,
    image_url: str,
) -> tuple[str, str]:
    """
    Upload an image to LinkedIn via the Images API.
    Returns (image_urn, error_message).
    """
    auth_headers = {
        **_LI_HEADERS_BASE,
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    # Step 1: initialize upload
    code, resp, _ = _fetch(
        "https://api.linkedin.com/rest/images?action=initializeUpload",
        method="POST",
        headers=auth_headers,
        body=json.dumps({
            "initializeUploadRequest": {"owner": author_urn}
        }).encode(),
    )
    if code != 200:
        err = resp.get("message", resp.get("_raw", ""))[:200]
        return "", f"initializeUpload HTTP {code}: {err}"

    value      = resp.get("value", {})
    upload_url = value.get("uploadUrl", "")
    image_urn  = value.get("image", "")
    if not upload_url or not image_urn:
        return "", "LinkedIn initializeUpload returned no uploadUrl or image URN"

    # Step 2: download image bytes from Cloudinary
    try:
        with urllib.request.urlopen(image_url, timeout=30) as r:
            image_bytes = r.read()
    except Exception as exc:
        return "", f"Could not download image from {image_url}: {exc}"

    # Step 3: PUT image bytes to LinkedIn
    put_req = urllib.request.Request(
        upload_url,
        data=image_bytes,
        method="PUT",
    )
    put_req.add_header("Content-Type", "image/png")
    try:
        with urllib.request.urlopen(put_req, timeout=60) as r:
            pass  # expect 201 No Content
    except urllib.error.HTTPError as exc:
        if exc.code not in (200, 201):
            return "", f"Image PUT failed HTTP {exc.code}"
    except Exception as exc:
        return "", f"Image PUT error: {exc}"

    return image_urn, ""


class LinkedInPublisher(BasePublisher):
    name = "linkedin"

    def publish(self, draft: DraftPackage, mode: str) -> PublishResult:
        token         = os.getenv("NB_LINKEDIN_ACCESS_TOKEN", "")
        client_id     = os.getenv("NB_LINKEDIN_CLIENT_ID", "")
        client_secret = os.getenv("NB_LINKEDIN_CLIENT_SECRET", "")

        missing = [k for k, v in {
            "NB_LINKEDIN_ACCESS_TOKEN":  token,
            "NB_LINKEDIN_CLIENT_ID":     client_id,
            "NB_LINKEDIN_CLIENT_SECRET": client_secret,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

        if mode == "draft_only":
            return self._skip("LinkedIn does not support draft posts — skipped in draft_only mode")

        text      = draft.linkedin_text
        has_image = bool(draft.image_url)
        if not text:
            return self._fail("linkedin.txt is empty")

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — {len(text)} chars, "
                    f"image={'yes' if has_image else 'none (text-only post)'}"
                ),
            )

        # Resolve author URN
        author_urn, err = _get_author_urn(token, client_id, client_secret)
        if err:
            return self._fail(f"Could not resolve author URN: {err}")

        auth_headers = {
            **_LI_HEADERS_BASE,
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

        # Upload image if available
        image_urn: str = ""
        if has_image:
            image_urn, err = _upload_image_to_linkedin(author_urn, token, draft.image_url)
            if err:
                # Non-fatal: fall back to text-only with a note
                image_urn = ""

        # Build post payload
        post: dict = {
            "author":      author_urn,
            "commentary":  text,
            "visibility":  "PUBLIC",
            "distribution": {
                "feedDistribution":               "MAIN_FEED",
                "targetEntities":                 [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState":            "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        if image_urn:
            post["content"] = {
                "media": {
                    "id":    image_urn,
                    "title": draft.blog_title[:200],
                }
            }

        code, resp, _, resp_headers = _fetch_h(
            "https://api.linkedin.com/rest/posts",
            method="POST",
            headers=auth_headers,
            body=json.dumps(post).encode(),
        )

        if code in (200, 201):
            # LinkedIn returns the post URN in X-RestLi-Id header
            restli_id = resp_headers.get("X-RestLi-Id", resp_headers.get("x-restli-id", ""))
            post_id   = restli_id or resp.get("id", resp.get("value", ""))
            # Construct share URL from URN (urn:li:share:ID → linkedin.com/feed/update/urn:li:share:ID/)
            post_url = ""
            if post_id and ":" in str(post_id):
                post_url = f"https://www.linkedin.com/feed/update/{post_id}/"
            note = "(with image)" if image_urn else "(text-only — image upload failed)"
            return self._published(
                external_id=str(post_id),
                url=post_url or "https://www.linkedin.com/feed/",
                raw_path=note,
            )

        err_msg = resp.get("message", resp.get("_raw", ""))[:200]
        return self._fail(f"HTTP {code}: {err_msg}")
