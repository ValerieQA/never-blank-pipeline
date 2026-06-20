"""
Wix Blog v3 publisher.

dry_run    — validate env vars + payload, no API call
draft_only — create draft post (default safe mode)
live       — create draft, then publish it
"""
import json
import os
import re
from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus


_API = "https://www.wixapis.com"


def _md_to_rich_nodes(markdown: str) -> list[dict]:
    """
    Convert Markdown to Wix richContent nodes.
    Handles H1/H2/H3 headings and paragraph text.
    """
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
            # Strip inline markdown (bold/italic) for plain text fallback
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", block)
            text = re.sub(r"\*(.+?)\*", r"\1", text)
            text = re.sub(r"`(.+?)`", r"\1", text)
            nodes.append({
                "type": "PARAGRAPH",
                "nodes": [{"type": "TEXT", "textData": {"text": text}}],
            })
    return nodes


class WixPublisher(BasePublisher):
    name = "wix"

    def publish(self, draft: DraftPackage, mode: str) -> PublishResult:
        api_key    = os.getenv("NB_WIX_API_KEY", "")
        site_id    = os.getenv("NB_WIX_SITE_ID", "")
        owner_id   = os.getenv("NB_WIX_POST_OWNER_ID", "")

        missing = [k for k, v in {
            "NB_WIX_API_KEY": api_key,
            "NB_WIX_SITE_ID": site_id,
            "NB_WIX_POST_OWNER_ID": owner_id,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

        headers = {
            "Authorization": api_key,
            "wix-site-id":   site_id,
            "Content-Type":  "application/json",
        }

        nodes = _md_to_rich_nodes(draft.blog_body)
        draft_body = json.dumps({
            "draftPost": {
                "title":       draft.blog_title,
                "memberId":    owner_id,
                "slug":        draft.wix_slug,
                "categoryIds": [draft.wix_category_id] if draft.wix_category_id else [],
                "tagIds":      draft.wix_tags,
                "excerpt":     draft.blog_meta.get("meta_description", "")[:500],
                "richContent": {"nodes": nodes},
            }
        }).encode()

        if mode == "dry_run":
            node_count = len(nodes)
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — title={draft.blog_title!r} "
                    f"slug={draft.wix_slug!r} nodes={node_count}"
                ),
            )

        # Create draft
        code, resp, raw = _fetch(
            f"{_API}/blog/v3/draft-posts",
            method="POST",
            headers=headers,
            body=draft_body,
        )
        if code not in (200, 201):
            err = resp.get("message", resp.get("_raw", ""))[:200]
            return self._fail(f"Draft creation failed (HTTP {code}): {err}")

        draft_id = resp.get("draftPost", {}).get("id", "")
        if not draft_id:
            return self._fail("Draft created but no ID returned in response")

        if mode == "draft_only":
            return self._draft(
                external_id=draft_id,
                url=f"https://manage.wix.com/dashboard/{site_id}/blog/draft-posts/{draft_id}",
            )

        # Publish (live mode)
        code2, resp2, _ = _fetch(
            f"{_API}/blog/v3/draft-posts/{draft_id}/publish",
            method="POST",
            headers=headers,
            body=b"{}",
        )
        if code2 not in (200, 201):
            err = resp2.get("message", resp2.get("_raw", ""))[:200]
            return self._fail(f"Publish failed (HTTP {code2}): {err}")

        post = resp2.get("post", {})
        post_id  = post.get("id", draft_id)
        post_url = post.get("url", "")
        return self._published(external_id=post_id, url=post_url)
