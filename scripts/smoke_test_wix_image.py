"""
Wix cover image smoke test.

Verifies the full image path:
  Cloudinary URL
  → POST /site-media/v1/files/import  (wix_file_id)
  → draftPost.coverMedia.image.{id, url}
  → GET draft-verify → coverMedia.image.id confirmed
  → POST publish
  → GET post → slug → URL

Does NOT publish to LinkedIn. Does NOT write to History.
Use signal_id "wix_coverimage_test" with reports/content_packages/wix_coverimage_test_generated.json.

Usage:
    python scripts/smoke_test_wix_image.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.publishing.base import DraftPackage
from src.publishing.wix import WixPublisher
from src.utils.logger import get_logger

log = get_logger("smoke_wix_image")
SEP = "─" * 64
PKG = Path("reports/content_packages/wix_coverimage_test_generated.json")


def main() -> int:
    print(f"\n{SEP}")
    print("  Wix Cover Image Smoke Test")
    print(SEP)

    if not PKG.exists():
        print(f"ERROR: {PKG} not found")
        return 1

    gen = json.loads(PKG.read_text())
    image_url = gen.get("image_url", "")
    headline  = gen.get("headline", "")
    blog_body = gen.get("blog_article", "")

    print(f"\n  headline:  {headline[:70]}")
    print(f"  image_url: {image_url[:80]}")
    print(f"  blog:      {len(blog_body)} chars")

    if not image_url:
        print("ERROR: image_url is empty — cannot test coverMedia path")
        return 1

    required = {
        "NB_WIX_API_KEY":       os.getenv("NB_WIX_API_KEY", ""),
        "NB_WIX_SITE_ID":       os.getenv("NB_WIX_SITE_ID", ""),
        "NB_WIX_POST_OWNER_ID": os.getenv("NB_WIX_POST_OWNER_ID", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: missing env vars: {missing}")
        return 1
    print("\n  ✓ Wix credentials present")

    draft = DraftPackage(
        draft_dir=PKG.parent,
        blog_title=headline,
        blog_body=blog_body,
        blog_meta={"title": headline, "wix_slug": "", "wix_category_id": "", "wix_tags": []},
        linkedin_text="(not used in this test)",
        instagram_text="",
        facebook_text="",
        threads_sequence=[],
        telegram_text="",
        image_url=image_url,
        wix_slug="",
        wix_category_id=os.getenv("NB_WIX_BLOG_CATEGORY_ID", ""),
        wix_tags=[x.strip() for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",") if x.strip()],
        metadata={"signal_id": "wix_coverimage_test"},
    )

    print(f"\n[1/1] Publishing to Wix (live mode, with cover image)…\n")

    publisher = WixPublisher()
    result = publisher.publish(draft, "live")

    print(f"\n  status:      {result.status}")
    print(f"  external_id: {result.external_id or '—'}")
    print(f"  url:         {result.url or '—'}")
    if result.error_message:
        print(f"  error:       {result.error_message}")

    print(f"\n{SEP}")
    if result.ok():
        print("  PASS — Wix published with cover image.")
        print("  Verify in Wix dashboard that the post has a cover photo.")
    else:
        print("  FAIL — Wix publish did not succeed.")
    print(SEP)

    return 0 if result.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
