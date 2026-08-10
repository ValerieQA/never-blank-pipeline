"""
src/publishing/providers.py
Abstract provider interfaces for the Publishing pipeline.

These interfaces decouple image generation, image storage, and persistent
upload from their concrete implementations. The controlled run injects fake
implementations; production uses the real ones.

## Interface hierarchy

  ImageProvider          — AI / programmatic image generation → bytes
  ImageReuseStore        — lookup and store reusable image entries
  PersistentStorageAdapter — upload bytes to a permanent URL (e.g. Cloudinary)

## Usage

Production:
    _generate_base_image(prompt, family)          # uses DefaultImageProvider
    upload_to_cloudinary(path, slug)              # uses DefaultPersistentStorageAdapter

Controlled run (injected fakes):
    _run_image_generation(..., image_provider=FakeImageProvider())
    # PersistentStorageAdapter.upload() blocked by policy.check("permanent_storage")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ImageProvider(ABC):
    """Abstract image generation interface."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        visual_family: str = "",
        negative_prompt: str = "",
        size: str = "1024x1024",
    ) -> tuple[bytes, str]:
        """
        Generate an image from `prompt`.

        Returns:
            (image_bytes, method_name) — bytes of the generated image and
            a string identifying the generation method (e.g. "dalle", "programmatic").
        """


class ImageReuseStore(ABC):
    """Abstract store for reusable image entries keyed by signal_id."""

    @abstractmethod
    def get(self, signal_id: str) -> Optional[dict]:
        """
        Return the stored image entry for `signal_id`, or None if not present.
        Entry format: {"url": str, "visual_family": str, ...}
        """

    @abstractmethod
    def put(self, signal_id: str, entry: dict) -> None:
        """Store `entry` for `signal_id`. Overwrites any existing entry."""


class PersistentStorageAdapter(ABC):
    """Abstract interface for uploading assets to permanent storage."""

    @abstractmethod
    def upload(self, image_path: str, slug: str) -> str:
        """
        Upload the image at `image_path` to permanent storage.

        Args:
            image_path: Local filesystem path to the image.
            slug:       Content identifier (used to build the remote path).

        Returns:
            Public URL of the uploaded asset.
        """


# ---------------------------------------------------------------------------
# Default (production) implementations
# ---------------------------------------------------------------------------

class DefaultImageProvider(ImageProvider):
    """
    Production image provider. Wraps _generate_base_image() from image_pipeline.
    This is the default when no provider is injected.
    """

    def generate(
        self,
        prompt: str,
        *,
        visual_family: str = "",
        negative_prompt: str = "",
        size: str = "1024x1024",
    ) -> tuple[bytes, str]:
        from src.publishing.image_pipeline import _generate_base_image
        return _generate_base_image(prompt, visual_family, negative_prompt)


class DefaultPersistentStorageAdapter(PersistentStorageAdapter):
    """
    Production persistent storage: Cloudinary via upload_to_cloudinary().
    """

    def upload(self, image_path: str, slug: str) -> str:
        from src.publishing.image_pipeline import upload_to_cloudinary
        from pathlib import Path
        return upload_to_cloudinary(Path(image_path), slug)


class NullImageReuseStore(ImageReuseStore):
    """
    In-memory reuse store that never persists. Used in controlled runs to
    prevent reading from or writing to the production image library.
    """

    def __init__(self):
        self._store: dict[str, dict] = {}

    def get(self, signal_id: str) -> Optional[dict]:
        return self._store.get(signal_id)

    def put(self, signal_id: str, entry: dict) -> None:
        self._store[signal_id] = entry
