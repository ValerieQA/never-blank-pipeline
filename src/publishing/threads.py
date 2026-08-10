"""
Threads publisher — publishes as a reply chain (thread sequence).

Flow per post:
  1. POST /me/threads         — create container (text, optional reply_to_id)
  2. POST /me/threads_publish — publish container

If the API returns an error on any reply post, that post is skipped with a warning.
The first post must succeed; otherwise the whole publish fails.

dry_run    — validate env + payload
draft_only — SKIPPED (Threads has no draft concept)
live       — publish full sequence as reply chain → PUBLISHED

Requires: NB_THREADS_ACCESS_TOKEN
"""
import json
import os
import time
import urllib.parse

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus

_BASE = "https://graph.threads.net/v1.0"


def _create_container(token: str, user_id: str, text: str, reply_to_id: str = None) -> tuple[str, str]:
    """Returns (container_id, error)."""
    params: dict = {
        "text":         text,
        "media_type":   "TEXT",
        "access_token": token,
    }
    if reply_to_id:
        params["reply_to_id"] = reply_to_id

    code, resp, _ = _fetch(
        f"{_BASE}/{user_id}/threads",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=urllib.parse.urlencode(params).encode(),
    )
    if code not in (200, 201):
        err = resp.get("error", {}).get("message", resp.get("_raw", ""))[:200]
        return "", f"HTTP {code}: {err}"
    return resp.get("id", ""), ""


def _publish_container(token: str, user_id: str, container_id: str) -> tuple[str, str]:
    """Returns (media_id, error)."""
    code, resp, _ = _fetch(
        f"{_BASE}/{user_id}/threads_publish",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=urllib.parse.urlencode({
            "creation_id":  container_id,
            "access_token": token,
        }).encode(),
    )
    if code not in (200, 201):
        err = resp.get("error", {}).get("message", resp.get("_raw", ""))[:200]
        return "", f"HTTP {code}: {err}"
    return resp.get("id", ""), ""


class ThreadsPublisher(BasePublisher):
    name = "threads"

    def _publish_impl(self, draft: DraftPackage, mode: str) -> PublishResult:
        token = os.getenv("NB_THREADS_ACCESS_TOKEN", "")
        if not token:
            return self._fail("Missing env var: NB_THREADS_ACCESS_TOKEN")

        if mode == "draft_only":
            return self._skip("Threads has no draft concept — skipped in draft_only mode")

        sequence = draft.threads_sequence
        if not sequence:
            return self._fail("threads.json has no sequence posts")

        if mode == "dry_run":
            post_chars = [len(p) for p in sequence]
            over_limit = [i for i, c in enumerate(post_chars) if c > 500]
            issues = (
                f" WARNING: posts {over_limit} exceed 500 chars" if over_limit else ""
            )
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: {len(sequence)} posts, "
                    f"chars={post_chars}{issues}"
                ),
            )

        # Resolve user ID from /me
        code_me, me, _ = _fetch(
            f"{_BASE}/me?fields=id&access_token={urllib.parse.quote(token)}"
        )
        if code_me != 200:
            return self._fail(f"Could not resolve Threads user ID (HTTP {code_me})")
        user_id = me.get("id", "")
        if not user_id:
            return self._fail("Threads /me returned no ID")

        published_ids: list[str] = []
        prev_id: str = None

        for i, post_text in enumerate(sequence):
            text = post_text[:500]  # enforce limit

            container_id, err = _create_container(token, user_id, text, reply_to_id=prev_id)
            if err:
                if i == 0:
                    return self._fail(f"First post container failed: {err}")
                break

            # Threads requires container to finish processing before publish
            time.sleep(5)

            media_id, err = _publish_container(token, user_id, container_id)
            if err:
                if i == 0:
                    return self._fail(f"First post publish failed: {err}")
                break

            published_ids.append(media_id)
            prev_id = media_id

        if not published_ids:
            return self._fail("No posts were published")

        first_id = published_ids[0]
        return self._published(
            external_id=first_id,
            url=f"https://www.threads.net/t/{first_id}" if first_id else None,
        )
