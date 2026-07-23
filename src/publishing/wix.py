"""
Wix Blog v3 publisher — Never Blank.

Publishing flow:
  1. If draft.image_url is set:
       a. Import image into Wix Media → WixMediaAsset(file_id)
       b. If import fails → return WixDraftCreationError (Wix channel fails,
          other channels are unaffected)
  2. Build richContent nodes from Markdown body
  3. POST /blog/v3/draft-posts (with media.wixMedia.image.id when available)
  4. Verify draft: GET /blog/v3/draft-posts/{id}
       — if image_url was set, verify that draft media contains the imported file_id
       — if media is missing, return WixDraftMediaVerificationError
  5. In live mode: POST /blog/v3/draft-posts/{id}/publish
       — read post_id and actual URL from response
       — if URL absent, GET /blog/v3/posts/{post_id} to resolve it
  6. Return PublishResult with external_id=post_id and url=actual_wix_url

Typed errors (all subclass WixPublisherError):
  WixMediaImportError           — Cloudinary → Wix Media import failed
  WixDraftCreationError         — POST /draft-posts failed
  WixDraftMediaVerificationError — draft exists but media is missing or wrong
  WixPublishError               — POST /publish failed

Env vars:
  NB_WIX_API_KEY        — Wix REST API key
  NB_WIX_SITE_ID        — Wix site ID
  NB_WIX_POST_OWNER_ID  — Wix member ID for post authorship

modes:
  dry_run    — validate payload, no API calls
  draft_only — create and verify draft, do not publish
  live       — full flow including publish
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.wix_media import WixMediaAsset, WixMediaImportError, import_image
from src.utils.logger import get_logger


_API = "https://www.wixapis.com"
_log = get_logger("wix.publisher")


# ── Typed errors ───────────────────────────────────────────────────────────────

class WixPublisherError(Exception):
    """Base class for all Wix publisher failures."""


class WixDraftCreationError(WixPublisherError):
    """POST /blog/v3/draft-posts returned non-2xx or no draft_id."""


class WixDraftMediaVerificationError(WixPublisherError):
    """
    Draft was created but GET /draft-posts/{id} shows media is missing
    or the Wix file_id does not match the imported asset.
    Raised only when the publishing package requires a cover image.
    """


class WixPublishError(WixPublisherError):
    """POST /blog/v3/draft-posts/{id}/publish returned non-2xx."""


# ── Markdown → Wix richContent ─────────────────────────────────────────────────

def _parse_bold_runs(text: str) -> list[tuple[str, bool]]:
    runs = []
    last = 0
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        if m.start() > last:
            runs.append((text[last:m.start()], False))
        runs.append((m.group(1), True))
        last = m.end()
    if last < len(text):
        runs.append((text[last:], False))
    return runs or [(text, False)]


def _md_to_rich_nodes(markdown: str) -> list[dict]:
    nodes = []
    for block in re.split(r"\n{2,}", markdown.strip()):
        block = block.strip()
        if not block:
            continue
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", block, re.MULTILINE)
        if heading_match:
            level = len(heading_match.group(1))
            text  = heading_match.group(2).strip()
            nodes.append({
                "type": "HEADING",
                "headingData": {"level": level},
                "nodes": [{"type": "TEXT", "textData": {"text": text}}],
            })
        else:
            text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"\1", block)
            text = re.sub(r"`(.+?)`", r"\1", text)
            text_nodes = []
            for run_text, is_bold in _parse_bold_runs(text):
                if not run_text:
                    continue
                node = {"type": "TEXT", "textData": {"text": run_text}}
                if is_bold:
                    node["textData"]["decorations"] = [{"type": "BOLD"}]
                text_nodes.append(node)
            if not text_nodes:
                text_nodes = [{"type": "TEXT", "textData": {"text": text}}]
            nodes.append({"type": "PARAGRAPH", "nodes": text_nodes})
    return nodes


# ── Publisher ──────────────────────────────────────────────────────────────────

class WixPublisher(BasePublisher):
    name = "wix"

    def publish(self, draft: DraftPackage, mode: str) -> PublishResult:
        api_key  = os.getenv("NB_WIX_API_KEY", "")
        site_id  = os.getenv("NB_WIX_SITE_ID", "")
        owner_id = os.getenv("NB_WIX_POST_OWNER_ID", "")

        missing = [k for k, v in {
            "NB_WIX_API_KEY":        api_key,
            "NB_WIX_SITE_ID":        site_id,
            "NB_WIX_POST_OWNER_ID":  owner_id,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

        headers = {
            "Authorization": api_key,
            "wix-site-id":   site_id,
            "Content-Type":  "application/json",
        }
        nodes = _md_to_rich_nodes(draft.blog_body)

        if mode == "dry_run":
            image_status = "pending_import" if draft.image_url else "no_image"
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — title={draft.blog_title!r} "
                    f"slug={draft.wix_slug!r} nodes={len(nodes)} "
                    f"cover_image={image_status}"
                ),
            )

        # ── Step 1: Import cover image into Wix Media ─────────────────────────
        media_asset: Optional[WixMediaAsset] = None
        if draft.image_url:
            safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", draft.blog_title[:60])
            try:
                media_asset = import_image(
                    source_url=draft.image_url,
                    display_name=f"NB_{safe_title}",
                    api_key=api_key,
                    site_id=site_id,
                )
            except WixMediaImportError as exc:
                return self._fail(f"Cover image import failed: {exc}")

        # ── Step 2: Build draft payload ───────────────────────────────────────
        post_payload: dict = {
            "title":       draft.blog_title,
            "memberId":    owner_id,
            "slug":        draft.wix_slug,
            "categoryIds": [draft.wix_category_id] if draft.wix_category_id else [],
            "tagIds":      draft.wix_tags,
            "excerpt":     draft.blog_meta.get("meta_description", "")[:500],
            "richContent": {"nodes": nodes},
        }
        if media_asset:
            post_payload["media"] = {
                "wixMedia": {
                    "image": {"id": media_asset.file_id}
                },
                "displayed": True,
                "custom":    True,
            }

        draft_body = json.dumps({"draftPost": post_payload}).encode()

        try:
            # ── Step 3: Create draft ──────────────────────────────────────────
            code, resp, _ = _fetch(
                f"{_API}/blog/v3/draft-posts",
                method="POST", headers=headers, body=draft_body,
            )
            _log.info(
                "wix step3 draft-create: HTTP %s | keys=%s | draftPost.id=%s",
                code, list(resp.keys()),
                resp.get("draftPost", {}).get("id", "—"),
            )
            if code not in (200, 201):
                err = resp.get("message", resp.get("_raw", ""))[:200]
                raise WixDraftCreationError(f"HTTP {code}: {err}")

            draft_id = resp.get("draftPost", {}).get("id", "")
            if not draft_id:
                raise WixDraftCreationError("POST /draft-posts returned 2xx but no draft ID")

            # ── Step 4: Verify draft ──────────────────────────────────────────
            _verify_draft(draft_id, media_asset, headers)

            if mode == "draft_only":
                return self._draft(
                    external_id=draft_id,
                    url=f"https://manage.wix.com/dashboard/{site_id}/blog/draft-posts/{draft_id}",
                )

            # ── Step 5: Publish ───────────────────────────────────────────────
            code2, resp2, _ = _fetch(
                f"{_API}/blog/v3/draft-posts/{draft_id}/publish",
                method="POST", headers=headers, body=b"{}",
            )
            _log.info(
                "wix step5 publish: HTTP %s | top-level keys=%s | post keys=%s | raw=%.600s",
                code2, list(resp2.keys()),
                list(resp2.get("post", {}).keys()),
                str(resp2)[:600],
            )
            if code2 not in (200, 201):
                err = resp2.get("message", resp2.get("_raw", ""))[:200]
                raise WixPublishError(f"HTTP {code2}: {err}")

            post     = resp2.get("post", {})
            post_id  = post.get("id", "") or resp2.get("postId", "")
            post_url = post.get("url", "")

            if not post_id:
                raise WixPublishError(
                    "Publish returned 2xx but no post ID in response — "
                    "cannot record a valid platform_content_id"
                )

            # ── Step 6: Resolve URL if not in publish response ────────────────
            if not post_url:
                post_url = _resolve_post_url(post_id, headers)

            return self._published(external_id=post_id, url=post_url)

        except WixPublisherError as exc:
            return self._fail(str(exc))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _verify_draft(
    draft_id:    str,
    media_asset: Optional[WixMediaAsset],
    headers:     dict,
) -> None:
    """
    GET the draft to confirm it exists and, when a cover image was imported,
    verify that the draft's media.wixMedia.image.id matches the imported file_id.

    Always raises WixDraftMediaVerificationError on failure — fail-closed.
    A non-2xx GET means we cannot confirm the draft is well-formed; publishing
    a draft we cannot verify risks silently delivering a broken post.
    """
    code, resp, _ = _fetch(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}",
        method="GET", headers=headers,
    )
    _log.info(
        "wix step4 draft-verify: HTTP %s | keys=%s | draftPost.status=%s | draftPost.media=%s",
        code, list(resp.keys()),
        resp.get("draftPost", {}).get("status", "—"),
        str(resp.get("draftPost", {}).get("media", "—"))[:200],
    )
    if code not in (200, 201):
        raise WixDraftMediaVerificationError(
            f"Draft {draft_id} verification GET returned HTTP {code} — "
            "cannot confirm draft state before publishing"
        )

    if media_asset is None:
        return  # no cover image expected — draft existence is sufficient

    draft_post = resp.get("draftPost", {})
    draft_media = draft_post.get("media", {})
    wix_media   = draft_media.get("wixMedia", {})
    image_id    = wix_media.get("image", {}).get("id", "")

    if not image_id:
        raise WixDraftMediaVerificationError(
            f"Draft {draft_id} was created but media is missing. "
            f"Expected Wix file_id={media_asset.file_id!r}. "
            "The cover image will not appear on the published post."
        )

    if image_id != media_asset.file_id:
        raise WixDraftMediaVerificationError(
            f"Draft {draft_id} media ID mismatch: "
            f"expected {media_asset.file_id!r}, got {image_id!r}."
        )


def _resolve_post_url(post_id: str, headers: dict) -> str:
    """
    GET /blog/v3/posts/{post_id} to find the actual published URL.
    Returns empty string on failure (URL is non-critical — post is published).
    """
    code, resp, _ = _fetch(
        f"https://www.wixapis.com/blog/v3/posts/{post_id}",
        method="GET", headers=headers,
    )
    post_obj = resp.get("post", {})
    _log.info(
        "wix step6 resolve-url: HTTP %s | keys=%s | post keys=%s | post.url=%s | post.slug=%s | raw=%.600s",
        code, list(resp.keys()), list(post_obj.keys()),
        post_obj.get("url", "—"),
        post_obj.get("slug", "—"),
        str(resp)[:600],
    )
    if code in (200, 201):
        return resp.get("post", {}).get("url", "")
    return ""
