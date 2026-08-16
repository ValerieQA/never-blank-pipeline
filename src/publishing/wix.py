"""
Wix Blog v3 publisher — Never Blank.

Publishing flow:
  1. If draft.image_url is set:
       a. Import image into Wix Media → WixMediaAsset(file_id)
       b. If import fails → return WixDraftCreationError (Wix channel fails,
          other channels are unaffected)
  2. Build richContent nodes from Markdown body
  3. POST /blog/v3/draft-posts (with media.wixMedia.image.{id,url} when available)
  4. Verify draft: GET /blog/v3/draft-posts/{id}
       — if image_url was set, verify draft media.wixMedia.image.id matches imported file_id
       — if media.wixMedia.image.id missing, return WixDraftMediaVerificationError
  5. In live mode: POST /blog/v3/draft-posts/{id}/publish
       — read post_id and actual URL from response
       — if URL absent, GET /blog/v3/posts/{post_id} to resolve it
  6. Return PublishResult with external_id=post_id and url=actual_wix_url

Typed errors (all subclass WixPublisherError):
  WixMediaImportError           — Cloudinary → Wix Media import failed
  WixDraftCreationError         — POST /draft-posts failed
  WixDraftMediaVerificationError — draft exists but media is missing or wrong
  WixPublishError               — POST /publish failed

Env vars (credential secret only — Issue #100):
  NB_WIX_API_KEY        — Wix REST API key

Target identity (site ID, post owner member ID) is NOT read here: it comes
from the canonical publication package via the draft package, so the target
recorded by the package is exactly the target the external call uses.

modes:
  dry_run    — validate payload, no API calls
  draft_only — create and verify draft, do not publish
  live       — full flow including publish
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional, TYPE_CHECKING

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.wix_media import WixMediaAsset, WixMediaImportError, import_image
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.publishing.package import WixPublicationPackage
    from src.strategy.execution_context import WixStrategyView


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

    def publish(
        self,
        package: "WixPublicationPackage",
        mode: str,
        *,
        strategy_view: "WixStrategyView | None" = None,
    ) -> PublishResult:
        # Issue #101: the adapter receives the exact frozen package the
        # preflight authorized and derives its internal representation from
        # it. Nothing between ALLOW and this call can change content or target.
        if strategy_view is not None and package.configuration_identity != strategy_view.identity:
            return self._fail(
                "package configuration identity does not match the Wix strategy view"
            )
        draft = DraftPackage.from_wix_package(package)
        # Credential secret — environment-only (readiness gate is Issue #101).
        api_key  = os.getenv("NB_WIX_API_KEY", "")
        # Target identity — package-derived (Issue #100): the environment was
        # read exactly once at canonical package construction; a second
        # independent target selection here would let the external call go to
        # a target the package digest does not identify.
        site_id  = draft.wix_site_id
        owner_id = draft.wix_owner_member_id

        missing = [k for k, v in {
            "NB_WIX_API_KEY":        api_key,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")
        missing_target = [k for k, v in {
            "wix_site_id":           site_id,
            "wix_owner_member_id":   owner_id,
        }.items() if not v]
        if missing_target:
            return self._fail(
                f"Missing package target identity: {missing_target}"
            )

        headers = {
            "Authorization": api_key,
            "wix-site-id":   site_id,
            "Content-Type":  "application/json",
        }
        nodes = _md_to_rich_nodes(draft.blog_body)

        image_url = draft.image_for("blog")
        if mode == "dry_run":
            image_status = "pending_import" if image_url else "no_image"
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
        if image_url:
            safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", draft.blog_title[:60])
            try:
                media_asset = import_image(
                    source_url=image_url,
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
            # Wix Blog v3 actual response shape (confirmed from live posts):
            # media.wixMedia.image.{id, url} — both id and url are required.
            # custom:True means this image is used instead of auto-selecting from content.
            post_payload["media"] = {
                "wixMedia": {
                    "image": {
                        "id":  media_asset.file_id,
                        "url": media_asset.url or "",
                    }
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
                "wix step3 draft-create: HTTP %s | keys=%s | draftPost.id=%s | media_sent=%s",
                code, list(resp.keys()),
                resp.get("draftPost", {}).get("id", "—"),
                str(post_payload.get("media", "not_sent"))[:200],
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
        "wix step4 draft-verify: HTTP %s | status=%s | media=%s",
        code,
        resp.get("draftPost", {}).get("status", "—"),
        str(resp.get("draftPost", {}).get("media", "—"))[:300],
    )
    if code not in (200, 201):
        raise WixDraftMediaVerificationError(
            f"Draft {draft_id} verification GET returned HTTP {code} — "
            "cannot confirm draft state before publishing"
        )

    if media_asset is None:
        return  # no cover image expected — draft existence is sufficient

    draft_post = resp.get("draftPost", {})
    media      = draft_post.get("media", {})
    image_id   = media.get("wixMedia", {}).get("image", {}).get("id", "")

    if not image_id:
        raise WixDraftMediaVerificationError(
            f"Draft {draft_id} was created but media.wixMedia.id is missing. "
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

    Fallback: if Wix confirms the post exists (HTTP 200) but post.url is absent,
    and both slug and NB_WIX_SITE_BASE_URL are available, constructs the canonical
    URL locally. This is Never Blank-specific (assumes /blog/{slug} path format).
    Logs the URL source so future readers can tell whether the URL came from the
    Wix API or was constructed locally.
    """
    code, resp, _ = _fetch(
        f"https://www.wixapis.com/blog/v3/posts/{post_id}",
        method="GET", headers=headers,
    )
    post_obj = resp.get("post", {})
    slug     = post_obj.get("slug", "")
    api_url  = post_obj.get("url", "")

    _log.info(
        "wix step6 resolve-url: HTTP %s | post.slug=%s | post.url=%s",
        code, slug or "—", api_url or "—",
    )

    if code not in (200, 201):
        return ""

    # URL came directly from Wix API — preferred path
    if api_url:
        _log.info("wix URL source: api | url=%s", api_url)
        return api_url

    # Fallback: Wix confirmed the post exists (HTTP 200) but returned no url.
    # Construct from base + slug only when all conditions are met:
    #   1. slug is confirmed from the GET /posts/{id} response (not constructed locally)
    #   2. NB_WIX_SITE_BASE_URL is configured
    # This is NB-specific: assumes public blog path is {base}/blog/{slug}.
    if slug:
        base = os.getenv("NB_WIX_SITE_BASE_URL", "").rstrip("/")
        if base:
            url = f"{base}/blog/{slug}"
            _log.info("wix URL source: fallback_base_plus_slug | base=%s | url=%s", base, url)
            return url
        else:
            _log.warning(
                "wix URL source: fallback skipped — slug=%s but NB_WIX_SITE_BASE_URL is empty",
                slug,
            )

    return ""
