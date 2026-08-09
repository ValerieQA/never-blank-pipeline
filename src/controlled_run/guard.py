"""
src/controlled_run/guard.py
ControlledRunGuard — centralized fail-closed publication guard.

## Runtime protection (architectural, not test-only)

NB_CONTROLLED_RUN=1 is checked at each external-write sink BEFORE any
network client is reached:

  upload_to_cloudinary        — src/publishing/image_pipeline.py
  append_published_entry      — src/strategy/history.py
  WixPublisher.publish        — src/publishing/wix.py
  LinkedInPublisher.publish   — src/publishing/linkedin.py
  FacebookPublisher.publish   — src/publishing/facebook.py
  InstagramPublisher.publish  — src/publishing/instagram.py
  ThreadsPublisher.publish    — src/publishing/threads.py
  TelegramPublisher.publish   — src/publishing/telegram.py

All 8 sinks call BasePublisher._guard_controlled_run() or perform the
env-var check directly. Setting NB_CONTROLLED_RUN=1 is sufficient to
block external writes at runtime without any test-level patching.

## Architectural limitation acknowledged

The current architecture uses no dependency injection or capability passing.
The env-var guard is the minimum change that provides runtime protection
without a full template-method refactor of BasePublisher. A proper
refactor (BasePublisher.publish → concrete wrapper calling _publish_impl())
would allow injecting a ControlledRunPolicy object and is tracked separately.

## Test-time protection

ControlledRunGuard.active() additionally applies unittest.mock.patch on
the 8 sinks as a defense-in-depth layer. Tests verify each mock was NOT
called. Monkeypatch is explicitly NOT the primary runtime protection.
"""

from __future__ import annotations

import unittest.mock as mock
from contextlib import contextmanager
from typing import Generator


class ControlledRunViolation(Exception):
    """Raised when a blocked external write is attempted in controlled-run mode."""

    def __init__(self, sink: str, detail: str = ""):
        self.sink = sink
        super().__init__(
            f"ControlledRunGuard: external write blocked — sink={sink!r}"
            + (f" ({detail})" if detail else "")
        )


class ControlledRunGuard:
    """
    Defense-in-depth context manager for controlled-run isolation.

    Primary protection: NB_CONTROLLED_RUN=1 env-var checked at each sink.
    Secondary protection: mock.patch on known sinks for test verification.
    """

    @contextmanager
    def active(self) -> Generator[None, None, None]:
        """
        Context manager: patches all external-write sinks.
        Used in tests and orchestrator code that also sets NB_CONTROLLED_RUN=1.
        """
        def _blocked(sink: str):
            def _raise(*args, **kwargs):
                raise ControlledRunViolation(sink)
            return _raise

        patches = [
            mock.patch(
                "src.publishing.image_pipeline.upload_to_cloudinary",
                side_effect=_blocked("upload_to_cloudinary"),
            ),
            mock.patch(
                "src.strategy.history.append_published_entry",
                side_effect=_blocked("append_published_entry"),
            ),
            mock.patch(
                "src.publishing.wix.WixPublisher.publish",
                side_effect=_blocked("WixPublisher.publish"),
            ),
            mock.patch(
                "src.publishing.linkedin.LinkedInPublisher.publish",
                side_effect=_blocked("LinkedInPublisher.publish"),
            ),
            mock.patch(
                "src.publishing.facebook.FacebookPublisher.publish",
                side_effect=_blocked("FacebookPublisher.publish"),
            ),
            mock.patch(
                "src.publishing.instagram.InstagramPublisher.publish",
                side_effect=_blocked("InstagramPublisher.publish"),
            ),
            mock.patch(
                "src.publishing.threads.ThreadsPublisher.publish",
                side_effect=_blocked("ThreadsPublisher.publish"),
            ),
            mock.patch(
                "src.publishing.telegram.TelegramPublisher.publish",
                side_effect=_blocked("TelegramPublisher.publish"),
            ),
        ]

        started = []
        try:
            for p in patches:
                started.append(p.start())
            yield
        finally:
            for p in reversed(patches):
                try:
                    p.stop()
                except RuntimeError:
                    pass
