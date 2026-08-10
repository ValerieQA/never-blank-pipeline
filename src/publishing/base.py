"""
Shared infrastructure for all publishers:
  - BasePublisher ABC
  - DraftPackage (loaded from data/drafts/latest/)
  - _fetch() HTTP helper (mirrors test_publishers.py)
"""
import json
import os
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional
from pathlib import Path

from src.publishing.result import PublishResult, PublishStatus

if TYPE_CHECKING:
    from src.controlled_run.policy import ControlledRunPolicy, PolicyRequiredError


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
    metadata:       dict = field(default_factory=dict)

    def image_for(self, platform: str) -> Optional[str]:
        """Return the best image URL for this platform, falling back to image_url."""
        return self.platform_image_urls.get(platform) or self.image_url


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

    def __init__(self):
        # Instance-level policy (set at construction or via set_policy).
        # The template method uses this if no policy= kwarg is passed.
        self._policy: "ControlledRunPolicy | None" = None

    def set_policy(self, policy: "ControlledRunPolicy") -> None:
        """Inject a ControlledRunPolicy for this publisher instance."""
        self._policy = policy

    # ── Template method (primary policy gate) ─────────────────────────────────

    def publish(
        self,
        draft: "DraftPackage",
        mode: str,
        **kwargs,
    ) -> PublishResult:
        """
        Template method — concrete, non-overrideable gate.

        Gate order:
          1. Resolve effective policy: kwarg `policy=` takes precedence
             over instance `self._policy`.
          2. If policy is provided: call policy.check("publication") before
             any I/O. This is the PRIMARY protection (ControlledRunPolicy DI).
             Raises PolicyViolation (subclass of Exception) on block.
          3. If no policy AND NB_CONTROLLED_RUN=1 is set: raise PolicyRequiredError.
             This prevents legacy callers from silently bypassing protection
             in a controlled-run context.
          4. Delegates to _publish_impl(draft, mode, **kwargs).

        Subclasses implement _publish_impl() ONLY. They MUST NOT add their own
        policy calls — the gate runs unconditionally here.

        An unknown publisher that only implements _publish_impl() is
        automatically protected: ANY publication attempt in a controlled-run
        context (with policy or with env-var set) is blocked before _publish_impl.

        **kwargs: forwarded verbatim to _publish_impl. Telegram uses wix_url= here.

        mode: 'dry_run' | 'draft_only' | 'live'
        """
        from src.controlled_run.policy import PolicyRequiredError

        policy = kwargs.pop("policy", None) or self._policy
        adapter_name = getattr(self, "name", type(self).__name__)

        if policy is not None:
            policy.check("publication", adapter=adapter_name)
        elif os.environ.get("NB_CONTROLLED_RUN") == "1":
            raise PolicyRequiredError(adapter_name)

        return self._publish_impl(draft, mode, **kwargs)

    @abstractmethod
    def _publish_impl(self, draft: "DraftPackage", mode: str, **kwargs) -> PublishResult:
        """
        Subclasses implement publication logic here.

        **kwargs: extra keyword arguments forwarded from publish().
          - TelegramPublisher uses kwargs.get("wix_url").
          - All other publishers should ignore **kwargs.
        """

    def _check_policy(
        self,
        policy: "ControlledRunPolicy | None",
        operation: str = "publication",
    ) -> None:
        """
        Legacy helper — kept for backward compatibility with any publisher
        that was written before the template method was finalized.
        New code should rely on publish() for policy checks.
        """
        from src.controlled_run.policy import PolicyRequiredError

        effective = policy or self._policy
        adapter_name = getattr(self, "name", type(self).__name__)
        if effective is not None:
            effective.check(operation, adapter=adapter_name)
        elif os.environ.get("NB_CONTROLLED_RUN") == "1":
            raise PolicyRequiredError(adapter_name)

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
