"""
tests/helpers/controlled_run_helpers.py
Fake provider implementations for controlled-run integration tests.

These fakes are injected into the production code path via dependency
injection — NO mock.patch of internal symbols in integration tests.

## Why no mock.patch?

mock.patch intercepts a symbol in a specific module's namespace. If the
internal implementation changes (e.g. a function is renamed or moved),
the patch silently passes while calling the wrong function. Fake provider
injection is explicit: the production code calls `llm_provider.chat(...)` —
if the provider interface changes, tests fail loudly.

## Fakes provided

  FakeLLMProvider       — returns canned JSON responses in sequence
  FakeFeedProvider      — returns canned RSS XML bytes
  FakeImageProvider     — returns a minimal 1×1 white PNG
  FakeStorageAdapter    — writes to run_dir only; never to Cloudinary
  FakeArtifactStore     — wraps IsolatedRunArtifactStore for tests
  ControlledRunViolation — moved here from src/controlled_run/guard.py
                          (guard.py removed; this is the test-only exception)
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any, Optional

from src.research.providers import LLMProvider, FeedProvider
from src.publishing.providers import ImageProvider, ImageReuseStore, PersistentStorageAdapter
from src.controlled_run.artifact_store import IsolatedRunArtifactStore


# ---------------------------------------------------------------------------
# Test-only exception (moved from src/controlled_run/guard.py)
# ---------------------------------------------------------------------------

class ControlledRunViolation(Exception):
    """
    Raised in test assertions when an external write boundary is reached
    unexpectedly. This is a TEST helper only — not used in production code.
    Production uses PolicyViolation from src.controlled_run.policy.
    """

    def __init__(self, sink: str, detail: str = ""):
        self.sink = sink
        super().__init__(
            f"ControlledRunViolation: unexpected external write — sink={sink!r}"
            + (f" ({detail})" if detail else "")
        )


# ---------------------------------------------------------------------------
# FakeLLMProvider
# ---------------------------------------------------------------------------

class FakeLLMProvider(LLMProvider):
    """
    LLM provider that returns canned responses in sequence.
    Raises AssertionError if called more times than responses provided
    (or if `strict=True` and unexpected extra calls occur).

    Usage:
        provider = FakeLLMProvider([
            json.dumps({"selected": [0, 1]}),
            json.dumps({"HEADLINE": "Test", "SIGNAL_TYPE": "business trust"}),
        ])
        result = provider.chat("system", "user", json_mode=True)
        assert result == '{"selected": [0, 1]}'
    """

    def __init__(self, responses: list[str], strict: bool = False):
        self._responses = list(responses)
        self._index     = 0
        self.calls: list[dict] = []
        self._strict = strict

    def chat(self, system: str, user: str, *, json_mode: bool = False,
             model: str = "", **kwargs: Any) -> str:
        self.calls.append({
            "system":    system[:80],
            "user":      user[:80],
            "json_mode": json_mode,
            "model":     model,
        })
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        if self._strict:
            raise AssertionError(
                f"FakeLLMProvider: unexpected extra call #{self._index + 1}. "
                f"Only {len(self._responses)} responses were configured."
            )
        # Default: return an empty JSON object for JSON-mode, empty string otherwise
        return "{}" if json_mode else ""

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def assert_call_count(self, expected: int) -> None:
        assert self.call_count == expected, (
            f"Expected {expected} LLM calls, got {self.call_count}"
        )


# ---------------------------------------------------------------------------
# FakeFeedProvider
# ---------------------------------------------------------------------------

_MINIMAL_RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Fake Feed</title>
    <link>https://example.com</link>
    {items}
  </channel>
</rss>"""

_RSS_ITEM_TEMPLATE = """
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <pubDate>{pub_date}</pubDate>
      <description>{description}</description>
    </item>"""


class FakeFeedProvider(FeedProvider):
    """
    Feed provider that returns canned RSS items without making network calls.

    Usage:
        provider = FakeFeedProvider(items=[
            {"title": "Test article", "link": "https://ex.com/1",
             "pub_date": "Mon, 09 Aug 2026 12:00:00 +0000",
             "description": "Test description"},
        ])
        raw = provider.fetch("https://any-url.com")  # returns RSS XML bytes
    """

    def __init__(self, items: list[dict] | None = None):
        self._items = items or [
            {
                "title":       "Fake news item about customer trust",
                "link":        "https://example.com/article/fake-news",
                "pub_date":    "Mon, 09 Aug 2026 12:00:00 +0000",
                "description": "Fake description about why businesses lose customers.",
            }
        ]
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout: int = 15) -> bytes:
        self.calls.append(url)
        items_xml = "".join(
            _RSS_ITEM_TEMPLATE.format(
                title       = it.get("title", ""),
                link        = it.get("link", "https://example.com"),
                pub_date    = it.get("pub_date", "Mon, 09 Aug 2026 12:00:00 +0000"),
                description = it.get("description", ""),
            )
            for it in self._items
        )
        return _MINIMAL_RSS_TEMPLATE.format(items=items_xml).encode("utf-8")

    @property
    def call_count(self) -> int:
        return len(self.calls)


# ---------------------------------------------------------------------------
# FakeImageProvider
# ---------------------------------------------------------------------------

def _make_minimal_png(width: int = 1, height: int = 1) -> bytes:
    """Return a minimal valid 1×1 white PNG in bytes."""
    def _pack(fmt, *args):
        return struct.pack(fmt, *args)

    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    # IHDR chunk: width, height, bit depth 8, color type 2 (RGB)
    ihdr_data = _pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc  = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr      = _pack(">I", 13) + b"IHDR" + ihdr_data + _pack(">I", ihdr_crc)

    # IDAT chunk: one row of white pixels (filter byte 0 + 3 bytes per pixel)
    raw_row    = bytes([0] + [255, 255, 255] * width) * height
    compressed = zlib.compress(raw_row)
    idat_crc   = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat       = _pack(">I", len(compressed)) + b"IDAT" + compressed + _pack(">I", idat_crc)

    # IEND chunk
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend     = _pack(">I", 0) + b"IEND" + _pack(">I", iend_crc)

    return sig + ihdr + idat + iend


class FakeImageProvider(ImageProvider):
    """
    Image provider that returns a synthetic PNG without any API call.

    Usage:
        provider = FakeImageProvider()
        img_bytes, method = provider.generate("test prompt")
        assert method == "fake"
        assert img_bytes[:4] == b"\x89PNG"
    """

    def __init__(self, method: str = "fake_dalle"):
        self._method    = method
        self.calls: list[dict] = []
        self._png_bytes = _make_minimal_png(width=1, height=1)

    def generate(
        self,
        prompt: str,
        *,
        visual_family: str = "",
        negative_prompt: str = "",
        size: str = "1024x1024",
    ) -> tuple[bytes, str]:
        self.calls.append({
            "prompt":          prompt,
            "visual_family":   visual_family,
            "negative_prompt": negative_prompt,
            "size":            size,
        })
        return self._png_bytes, self._method

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def assert_called_once(self) -> None:
        assert self.call_count == 1, f"Expected 1 image generation call, got {self.call_count}"


# ---------------------------------------------------------------------------
# FakeStorageAdapter (never writes to real storage)
# ---------------------------------------------------------------------------

class FakeStorageAdapter(PersistentStorageAdapter):
    """
    Persistent storage adapter that writes images to `run_dir` instead of
    Cloudinary. Returns a fake local URL.

    Usage:
        adapter = FakeStorageAdapter(run_dir)
        url = adapter.upload("/path/to/image.png", "my-post")
        assert url.startswith("file://")
    """

    def __init__(self, run_dir: Path):
        self._run_dir = run_dir
        self.calls: list[dict] = []

    def upload(self, image_path: str, slug: str) -> str:
        self.calls.append({"image_path": image_path, "slug": slug})
        # Simulate upload by copying to run_dir
        import shutil
        src = Path(image_path)
        dst = self._run_dir / f"uploaded_{src.name}"
        if src.exists():
            shutil.copy2(src, dst)
        return f"file://{dst}"

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def assert_not_called(self) -> None:
        assert self.call_count == 0, (
            f"FakeStorageAdapter.upload() was called {self.call_count} time(s); "
            "expected 0 (permanent storage should be blocked by policy)"
        )


# ---------------------------------------------------------------------------
# FakeImageReuseStore (always returns None; never persists)
# ---------------------------------------------------------------------------

class FakeImageReuseStore(ImageReuseStore):
    """
    Image reuse store that never returns existing entries and never persists.
    Used in controlled runs to prevent reading from or writing to the
    production image library.

    Usage:
        store = FakeImageReuseStore()
        assert store.get("any-id") is None  # no reuse
        store.put("any-id", {"url": "..."})  # no-op (not persisted)
        assert store.get_calls == 1
        assert store.put_calls == 1
    """

    def __init__(self):
        self.get_calls: list[str] = []
        self.put_calls: list[dict] = []

    def get(self, signal_id: str) -> Optional[dict]:
        self.get_calls.append(signal_id)
        return None  # always: no reuse

    def put(self, signal_id: str, entry: dict) -> None:
        self.put_calls.append({"signal_id": signal_id, "entry": entry})
        # no-op — not persisted to disk

    def assert_get_not_called(self) -> None:
        assert not self.get_calls, (
            f"ImageReuseStore.get() called {len(self.get_calls)} time(s); "
            "expected 0 (image reuse should be blocked by policy)"
        )

    def assert_put_not_called(self) -> None:
        assert not self.put_calls, (
            f"ImageReuseStore.put() called {len(self.put_calls)} time(s); "
            "expected 0 (image reuse should be blocked by policy)"
        )


# ---------------------------------------------------------------------------
# FakeArtifactStore
# ---------------------------------------------------------------------------

class FakeArtifactStore(IsolatedRunArtifactStore):
    """
    Test-friendly artifact store with call tracking.
    Inherits IsolatedRunArtifactStore so artifacts still land in run_dir.
    """

    def __init__(self, run_dir: Path):
        super().__init__(run_dir)
        self.write_calls: list[str] = []

    def write(self, name: str, data: bytes | str) -> Path:
        self.write_calls.append(name)
        return super().write(name, data)
