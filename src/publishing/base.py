"""
Shared infrastructure for all publishers:
  - BasePublisher ABC
  - DraftPackage (loaded from data/drafts/latest/)
  - _fetch() HTTP helper (mirrors test_publishers.py)
"""
import json
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.publishing.result import PublishResult, PublishStatus


# ── Draft loading ──────────────────────────────────────────────────────────────

@dataclass
class DraftPackage:
    draft_dir:      Path
    blog_title:     str
    blog_body:      str           # Markdown
    blog_meta:      dict
    linkedin_text:  str
    instagram_text: str           # caption + hashtags combined
    facebook_text:  str
    threads_sequence: list[str]
    telegram_text:  str
    image_url:      Optional[str] # Cloudinary URL, None if not yet generated
    wix_slug:       str
    wix_category_id: str
    wix_tags:       list[str]
    metadata:       dict


def load_draft(base_dir: Optional[Path] = None) -> DraftPackage:
    """
    Load draft from data/drafts/latest/final/ if it exists (QC-approved),
    else from data/drafts/latest/.  Raises FileNotFoundError if neither exists.
    """
    root = base_dir or (Path(__file__).parent.parent.parent / "data" / "drafts" / "latest")
    final = root / "final"
    draft_dir = final if (final / "metadata.json").exists() else root

    if not (draft_dir / "metadata.json").exists():
        raise FileNotFoundError(
            f"No draft found at {draft_dir}. Run scripts/generate.py first."
        )

    def _read(name: str) -> str:
        return (draft_dir / name).read_text(encoding="utf-8").strip()

    def _json(name: str) -> dict:
        return json.loads((draft_dir / name).read_text(encoding="utf-8"))

    meta     = _json("metadata.json")
    blog_meta = _json("blog_meta.json")

    # Threads sequence
    threads_data = _json("threads.json") if (draft_dir / "threads.json").exists() else {}
    threads_seq  = threads_data.get("sequence", [])

    # Image URL — written by image generation step (not yet implemented)
    image_url: Optional[str] = None
    image_url_file = draft_dir / "image_url.txt"
    if image_url_file.exists():
        image_url = image_url_file.read_text(encoding="utf-8").strip() or None

    return DraftPackage(
        draft_dir       = draft_dir,
        blog_title      = blog_meta.get("title", ""),
        blog_body       = _read("blog_post.md"),
        blog_meta       = blog_meta,
        linkedin_text   = _read("linkedin.txt"),
        instagram_text  = _read("instagram.txt"),
        facebook_text   = _read("facebook.txt"),
        threads_sequence= threads_seq,
        telegram_text   = _read("telegram.txt"),
        image_url       = image_url,
        wix_slug        = blog_meta.get("wix_slug", ""),
        wix_category_id = blog_meta.get("wix_category_id", ""),
        wix_tags        = blog_meta.get("wix_tags", []),
        metadata        = meta,
    )


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict = None,
    body: bytes = None,
    timeout: int = 20,
) -> tuple[int, dict, str]:
    req = urllib.request.Request(
        url, data=body, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw  = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            raw = exc.read()
        except Exception:
            raw = b""
    except Exception as exc:
        return 0, {}, str(exc)

    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {"_raw": text}
    return code, parsed, text


# ── Base publisher ─────────────────────────────────────────────────────────────

class BasePublisher(ABC):
    name: str

    @abstractmethod
    def publish(self, draft: DraftPackage, mode: str) -> PublishResult:
        """
        mode: 'dry_run' | 'draft_only' | 'live'
        """

    # Convenience factories
    def _skip(self, reason: str) -> PublishResult:
        return PublishResult(platform=self.name, status=PublishStatus.SKIPPED,
                             error_message=reason)

    def _fail(self, reason: str, raw_path: str = None) -> PublishResult:
        return PublishResult(platform=self.name, status=PublishStatus.FAILED,
                             error_message=reason, raw_response_path=raw_path)

    def _draft(self, external_id: str, url: str = None, raw_path: str = None) -> PublishResult:
        return PublishResult(platform=self.name, status=PublishStatus.DRAFT_CREATED,
                             external_id=external_id, url=url, raw_response_path=raw_path)

    def _published(self, external_id: str, url: str = None, raw_path: str = None) -> PublishResult:
        return PublishResult(platform=self.name, status=PublishStatus.PUBLISHED,
                             external_id=external_id, url=url, raw_response_path=raw_path)

    @staticmethod
    def _fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        return _fetch(url, method=method, headers=headers, body=body, timeout=timeout)
