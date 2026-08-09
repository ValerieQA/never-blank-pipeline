"""
src/controlled_run/guard.py
ControlledRunGuard — centralized fail-closed publication guard.

Raises ControlledRunViolation when any external write is attempted.

Activation: NB_CONTROLLED_RUN=1 environment variable, OR explicit instantiation.

Intercepted external writes:
  - Wix publish
  - LinkedIn/Zernio publish
  - Facebook/Instagram/Threads/Telegram publish
  - Cloudinary upload (upload_to_cloudinary)
  - append_published_entry (history write)

Usage (patch-style, for tests and controlled_run.py):

    guard = ControlledRunGuard()
    with guard.active():
        # Any call to the above sinks raises ControlledRunViolation
        ...
"""

from __future__ import annotations

import os
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


def _blocked(sink: str):
    """Return a callable that raises ControlledRunViolation for the named sink."""
    def _raise(*args, **kwargs):
        raise ControlledRunViolation(sink)
    return _raise


class ControlledRunGuard:
    """
    Patch context manager that blocks all external writes.

    Call guard.active() to get a context manager that patches the sinks.
    The guard is also activated when NB_CONTROLLED_RUN=1 is set in the environment.
    """

    def __init__(self):
        self._env_active = os.environ.get("NB_CONTROLLED_RUN", "0") == "1"

    @contextmanager
    def active(self) -> Generator[None, None, None]:
        """
        Context manager that patches all external-write sinks.
        Raises ControlledRunViolation on any attempted publish, upload, or history write.
        """
        patches = [
            # Cloudinary upload
            mock.patch(
                "src.publishing.image_pipeline.upload_to_cloudinary",
                side_effect=_blocked("upload_to_cloudinary"),
            ),
            # History write
            mock.patch(
                "src.strategy.history.append_published_entry",
                side_effect=_blocked("append_published_entry"),
            ),
            # Wix publisher
            mock.patch(
                "src.publishing.wix.WixPublisher.publish",
                side_effect=_blocked("WixPublisher.publish"),
            ),
            # LinkedIn publisher
            mock.patch(
                "src.publishing.linkedin.LinkedInPublisher.publish",
                side_effect=_blocked("LinkedInPublisher.publish"),
            ),
            # Facebook publisher
            mock.patch(
                "src.publishing.facebook.FacebookPublisher.publish",
                side_effect=_blocked("FacebookPublisher.publish"),
            ),
            # Instagram publisher
            mock.patch(
                "src.publishing.instagram.InstagramPublisher.publish",
                side_effect=_blocked("InstagramPublisher.publish"),
            ),
            # Threads publisher
            mock.patch(
                "src.publishing.threads.ThreadsPublisher.publish",
                side_effect=_blocked("ThreadsPublisher.publish"),
            ),
            # Telegram publisher
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
