"""
LinkedIn publisher — REST API /rest/posts.

dry_run    — validate payload, no API call
draft_only — SKIPPED (LinkedIn has no draft concept)
live       — POST /rest/posts → PUBLISHED

Author URN is resolved via token introspection (sub field).
Requires: NB_LINKEDIN_ACCESS_TOKEN, NB_LINKEDIN_CLIENT_ID, NB_LINKEDIN_CLIENT_SECRET
"""
import base64
import json
import os
import urllib.parse

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus

_LI_VERSION = "202504"


def _get_author_urn(token: str, client_id: str, client_secret: str) -> tuple[str, str]:
    """
    Call /oauth/v2/introspectToken to get the user's sub (person ID).
    Returns (urn, error_message).
    """
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    code, resp, _ = _fetch(
        "https://www.linkedin.com/oauth/v2/introspectToken",
        method="POST",
        headers={
            "Authorization":  f"Basic {basic}",
            "Content-Type":   "application/x-www-form-urlencoded",
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
    if not sub:
        return "", "Introspection returned no 'sub' field — cannot resolve author URN"

    return f"urn:li:person:{sub}", ""


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

        text = draft.linkedin_text
        if not text:
            return self._fail("linkedin.txt is empty")

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — {len(text)} chars"
                ),
            )

        # Resolve author URN via introspection
        author_urn, err = _get_author_urn(token, client_id, client_secret)
        if err:
            return self._fail(f"Could not resolve author URN: {err}")

        post_body = json.dumps({
            "author":            author_urn,
            "commentary":        text,
            "visibility":        "PUBLIC",
            "distribution": {
                "feedDistribution":              "MAIN_FEED",
                "targetEntities":                [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState":              "PUBLISHED",
            "isReshareDisabledByAuthor":   False,
        }).encode()

        code, resp, _ = _fetch(
            "https://api.linkedin.com/rest/posts",
            method="POST",
            headers={
                "Authorization":  f"Bearer {token}",
                "LinkedIn-Version": _LI_VERSION,
                "Content-Type":   "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            body=post_body,
        )

        if code in (200, 201):
            # LinkedIn returns the post URN in the X-RestLi-Id header (not in body)
            # We get the body response; URN may be in resp or in headers (not accessible via urllib)
            post_id = resp.get("id", resp.get("value", ""))
            post_url = f"https://www.linkedin.com/feed/" if not post_id else ""
            return self._published(external_id=str(post_id), url=post_url)

        err = resp.get("message", resp.get("error", {}).get("message", resp.get("_raw", "")))[:200]
        return self._fail(f"HTTP {code}: {err}")
