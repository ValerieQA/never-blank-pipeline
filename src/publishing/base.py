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
from typing import Dict, TYPE_CHECKING
from pathlib import Path
from typing import Optional

from src.publishing.result import PublishResult, PublishStatus

if TYPE_CHECKING:
    from src.strategy.execution_context import ConfigurationIdentity


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
    # Per-platform image URLs. Publishers resolve: platform_image_urls[platform] or image_url.
    # Allows each platform to receive its correctly-sized asset (e.g. Instagram 1080×1350
    # vs blog 1920×1080) instead of sharing one blog-sized URL across all channels.
    platform_image_urls: Dict[str, Optional[str]] = field(default_factory=dict)
    wix_slug:       str = ""
    wix_category_id: str = ""
    wix_tags:       list = field(default_factory=list)
    # Run identity — propagated from RunContext at the canonical entry point.
    # Default "" for backward compat with non-canonical callers and existing tests.
    run_id:         str = ""
    metadata:       dict = field(default_factory=dict)

    def image_for(self, platform: str) -> Optional[str]:
        """Return the best image URL for this platform, falling back to image_url."""
        return self.platform_image_urls.get(platform) or self.image_url

    def require_configuration_identity(
        self, expected: "ConfigurationIdentity", boundary: str
    ) -> None:
        """Fail closed if a controlled draft carries stale strategy identity."""

        from src.strategy.execution_context import (
            identity_from_mapping,
            require_configuration_identity,
        )

        actual = identity_from_mapping(
            self.metadata.get("configuration_identity"), boundary=boundary
        )
        require_configuration_identity(expected, actual, boundary)


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


def _fetch_h(
    url: str,
    *,
    method: str = "GET",
    headers: dict = None,
    body: bytes = None,
    timeout: int = 20,
) -> tuple[int, dict, str, dict]:
    """Like _fetch() but also returns response headers as a dict."""
    req = urllib.request.Request(
        url, data=body, method=method, headers=headers or {}
    )
    resp_headers: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw          = resp.read()
            code         = resp.status
            resp_headers = dict(resp.headers)
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        resp_headers = dict(exc.headers) if exc.headers else {}
    except Exception as exc:
        return 0, {}, str(exc), {}

    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {"_raw": text}
    return code, parsed, text, resp_headers


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
