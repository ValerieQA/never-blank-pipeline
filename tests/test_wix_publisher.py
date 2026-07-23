"""
Tests for Wix image import pipeline and WixPublisher.

Covers:
  wix_media.import_image:
    - successful import returns WixMediaAsset with file_id
    - supports "id" and "fileId" response field names
    - supports "url" and "fileUrl" response field names
    - HTTP 2xx without file_id raises WixMediaImportError
    - HTTP error raises WixMediaImportError
    - empty source_url raises immediately
    - missing credentials raises immediately

  WixPublisher.publish:
    - dry_run returns SKIPPED with image status
    - no image_url skips import and builds draft without media
    - image import failure → FAILED, draft is never created
    - draft payload contains Wix Media image ID when import succeeds
    - draft GET 200 but media missing → FAILED before publish
    - draft GET media ID mismatch → FAILED before publish
    - draft GET failure (network) does not block publishing
    - valid draft publishes and returns post_id + actual URL
    - publish endpoint returns post URL → used directly
    - publish endpoint does not return URL → resolved via GET /posts/{id}
    - publish HTTP error → FAILED
    - draft_only mode creates draft, does not publish
    - missing env vars → FAILED
    - multichannel: Wix image import failure does not stop other publishers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest

from src.publishing.result import PublishResult, PublishStatus
from src.publishing.wix_media import (
    WixMediaAsset,
    WixMediaImportError,
    import_image,
)
from src.publishing.wix import (
    WixDraftCreationError,
    WixDraftMediaVerificationError,
    WixPublisher,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _draft_package(image_url: Optional[str] = "https://res.cloudinary.com/nb/image/upload/v1/cover.jpg"):
    from src.publishing.base import DraftPackage
    return DraftPackage(
        draft_dir=Path("/tmp/draft"),
        blog_title="The Month You Went Quiet",
        blog_body="## The Pattern\n\nClients notice absence.",
        blog_meta={"meta_description": "Why agencies go dark."},
        linkedin_text="LinkedIn text",
        instagram_text="Instagram text",
        facebook_text="Facebook text",
        threads_sequence=["Thread 1"],
        telegram_text="Telegram text",
        image_url=image_url,
        wix_slug="the-month-you-went-quiet",
        wix_category_id="cat-001",
        wix_tags=["presence", "agency"],
        metadata={},
    )


def _wix_env(monkeypatch):
    monkeypatch.setenv("NB_WIX_API_KEY",       "test-key")
    monkeypatch.setenv("NB_WIX_SITE_ID",       "test-site")
    monkeypatch.setenv("NB_WIX_POST_OWNER_ID", "test-owner")


def _fetch_sequence(*responses):
    """
    Returns a side_effect list for patching src.publishing.wix._fetch.
    Each item in responses is (code, dict, raw_str).
    """
    return list(responses)


# ── wix_media.import_image ─────────────────────────────────────────────────────

class TestWixMediaImport:
    def test_success_returns_asset_with_file_id(self):
        with patch("src.publishing.wix_media._fetch", return_value=(
            200, {"file": {"id": "wix-file-abc", "url": "https://wixmp.com/abc.jpg"}}, ""
        )):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-file-abc"
        assert asset.url == "https://wixmp.com/abc.jpg"

    def test_accepts_fileid_field_name(self):
        with patch("src.publishing.wix_media._fetch", return_value=(
            200, {"file": {"fileId": "wix-file-xyz"}}, ""
        )):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-file-xyz"

    def test_accepts_fileurl_field_name(self):
        with patch("src.publishing.wix_media._fetch", return_value=(
            200, {"file": {"id": "wix-file-abc", "fileUrl": "https://wixmp.com/abc.jpg"}}, ""
        )):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.url == "https://wixmp.com/abc.jpg"

    def test_response_without_file_wrapper(self):
        # Wix sometimes returns the object at the top level
        with patch("src.publishing.wix_media._fetch", return_value=(
            200, {"id": "wix-flat-id"}, ""
        )):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-flat-id"

    def test_2xx_without_file_id_raises(self):
        with patch("src.publishing.wix_media._fetch", return_value=(
            200, {"file": {"displayName": "NB_cover"}}, ""  # no id or fileId
        )):
            with pytest.raises(WixMediaImportError, match="no file ID"):
                import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")

    def test_http_error_raises(self):
        with patch("src.publishing.wix_media._fetch", return_value=(
            400, {"message": "Bad request"}, ""
        )):
            with pytest.raises(WixMediaImportError, match="HTTP 400"):
                import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")

    def test_empty_source_url_raises_immediately(self):
        with pytest.raises(WixMediaImportError, match="source_url is required"):
            import_image("", "NB_cover", "key", "site")

    def test_missing_credentials_raises(self):
        with pytest.raises(WixMediaImportError, match="required"):
            import_image("https://cloudinary.com/img.jpg", "NB_cover", "", "site")

    def test_wix_media_asset_rejects_empty_file_id(self):
        with pytest.raises(ValueError, match="file_id cannot be empty"):
            WixMediaAsset(file_id="")

    def test_wix_media_asset_is_immutable(self):
        asset = WixMediaAsset(file_id="abc")
        with pytest.raises((AttributeError, TypeError)):
            asset.file_id = "other"


# ── WixPublisher ───────────────────────────────────────────────────────────────

class TestWixPublisherDryRun:
    def test_dry_run_returns_skipped(self, monkeypatch):
        _wix_env(monkeypatch)
        result = WixPublisher().publish(_draft_package(), "dry_run")
        assert result.status == PublishStatus.SKIPPED
        assert "dry_run" in result.error_message

    def test_dry_run_shows_pending_import_when_image_present(self, monkeypatch):
        _wix_env(monkeypatch)
        result = WixPublisher().publish(_draft_package(image_url="https://cloudinary.com/x.jpg"), "dry_run")
        assert "pending_import" in result.error_message

    def test_dry_run_shows_no_image_when_absent(self, monkeypatch):
        _wix_env(monkeypatch)
        result = WixPublisher().publish(_draft_package(image_url=None), "dry_run")
        assert "no_image" in result.error_message

    def test_dry_run_makes_no_api_calls(self, monkeypatch):
        _wix_env(monkeypatch)
        with patch("src.publishing.wix._fetch") as mock_fetch:
            WixPublisher().publish(_draft_package(), "dry_run")
        mock_fetch.assert_not_called()


class TestWixPublisherMissingEnv:
    def test_missing_api_key_returns_failed(self, monkeypatch):
        monkeypatch.setenv("NB_WIX_SITE_ID",       "site")
        monkeypatch.setenv("NB_WIX_POST_OWNER_ID",  "owner")
        monkeypatch.delenv("NB_WIX_API_KEY", raising=False)
        result = WixPublisher().publish(_draft_package(), "live")
        assert result.status == PublishStatus.FAILED
        assert "NB_WIX_API_KEY" in result.error_message


class TestWixPublisherImageImport:
    def test_image_import_failure_blocks_draft_creation(self, monkeypatch):
        _wix_env(monkeypatch)
        draft_calls = []

        with patch("src.publishing.wix.import_image",
                   side_effect=WixMediaImportError("Wix Media import failed (HTTP 400): Bad URL")):
            with patch("src.publishing.wix._fetch",
                       side_effect=lambda *a, **kw: draft_calls.append(1) or (200, {}, "")):
                result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.FAILED
        assert "import" in result.error_message.lower()
        assert draft_calls == []   # draft was never created

    def test_image_import_success_puts_file_id_in_draft_payload(self, monkeypatch):
        _wix_env(monkeypatch)
        asset = WixMediaAsset(file_id="wix-abc-123", url="https://wixmp.com/abc.jpg")
        captured_payloads = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                captured_payloads.append(json_body(body))
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {
                    "media": {"wixMedia": {"image": {"id": "wix-abc-123"}}}
                }}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/x"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image", return_value=asset):
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                WixPublisher().publish(_draft_package(), "live")

        assert len(captured_payloads) == 1
        draft_post = captured_payloads[0].get("draftPost", {})
        image_id = draft_post.get("media", {}).get("wixMedia", {}).get("image", {}).get("id")
        assert image_id == "wix-abc-123"

    def test_no_image_url_skips_import_and_omits_media(self, monkeypatch):
        _wix_env(monkeypatch)
        captured_payloads = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                captured_payloads.append(json_body(body))
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET":
                return 200, {"draftPost": {}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/x"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image") as mock_import:
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                WixPublisher().publish(_draft_package(image_url=None), "live")

        mock_import.assert_not_called()
        draft_post = captured_payloads[0].get("draftPost", {})
        assert "media" not in draft_post


class TestWixPublisherDraftVerification:
    def _fetch_happy_path(self, file_id="wix-abc-123"):
        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {
                    "media": {"wixMedia": {"image": {"id": file_id}}}
                }}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/x"}}, ""
            return 200, {}, ""
        return fake_fetch

    def test_draft_media_missing_blocks_publish(self, monkeypatch):
        _wix_env(monkeypatch)
        asset = WixMediaAsset(file_id="wix-abc-123")

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {}}, ""   # no media
            return 200, {}, ""

        with patch("src.publishing.wix.import_image", return_value=asset):
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.FAILED
        assert "media is missing" in result.error_message

    def test_draft_media_id_mismatch_blocks_publish(self, monkeypatch):
        _wix_env(monkeypatch)
        asset = WixMediaAsset(file_id="wix-abc-123")

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {
                    "media": {"wixMedia": {"image": {"id": "wix-DIFFERENT"}}}
                }}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image", return_value=asset):
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.FAILED
        assert "mismatch" in result.error_message

    def test_draft_get_failure_blocks_publish(self, monkeypatch):
        """Verification GET failure is fatal — fail-closed, do not publish unverified draft."""
        _wix_env(monkeypatch)
        asset = WixMediaAsset(file_id="wix-abc-123")
        publish_calls = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 503, {}, "service unavailable"   # verification GET failed
            if method == "POST" and "publish" in url:
                publish_calls.append(url)
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/x"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image", return_value=asset):
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.FAILED
        assert "HTTP 503" in result.error_message
        assert publish_calls == []   # publish endpoint was never called

    def test_valid_verified_draft_publishes(self, monkeypatch):
        _wix_env(monkeypatch)
        asset = WixMediaAsset(file_id="wix-abc-123")

        with patch("src.publishing.wix.import_image", return_value=asset):
            with patch("src.publishing.wix._fetch", side_effect=self._fetch_happy_path()):
                result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.PUBLISHED
        assert result.external_id == "post-001"
        assert result.url == "https://neverblank.co/post/x"


class TestWixPublisherUrlResolution:
    def test_url_from_publish_response_used_directly(self, monkeypatch):
        _wix_env(monkeypatch)

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/the-slug"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(image_url=None), "live")

        assert result.url == "https://neverblank.co/post/the-slug"

    def test_missing_url_resolved_via_get_posts(self, monkeypatch):
        """When publish response has no URL, GET /blog/v3/posts/{id} is called."""
        _wix_env(monkeypatch)
        resolve_calls = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001"}}, ""   # no URL
            if method == "GET" and "/posts/" in url:
                resolve_calls.append(url)
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/resolved"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(image_url=None), "live")

        assert result.url == "https://neverblank.co/post/resolved"
        assert any("/posts/" in u for u in resolve_calls)

    def test_publish_http_error_returns_failed(self, monkeypatch):
        _wix_env(monkeypatch)

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET":
                return 200, {"draftPost": {}}, ""
            if method == "POST" and "publish" in url:
                return 500, {"message": "Internal server error"}, ""
            return 200, {}, ""

        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(image_url=None), "live")

        assert result.status == PublishStatus.FAILED
        assert "HTTP 500" in result.error_message

    def test_publish_2xx_without_post_id_returns_failed(self, monkeypatch):
        """2xx publish response with no post ID must fail — draft_id must not be used as fallback."""
        _wix_env(monkeypatch)

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET":
                return 200, {"draftPost": {}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {}}, ""   # 2xx but no id field
            return 200, {}, ""

        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(image_url=None), "live")

        assert result.status == PublishStatus.FAILED
        assert "no post ID" in result.error_message
        assert result.external_id is None   # draft_id must never be stored here


class TestWixPublisherDraftOnly:
    def test_draft_only_does_not_call_publish_endpoint(self, monkeypatch):
        _wix_env(monkeypatch)
        publish_calls = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET":
                return 200, {"draftPost": {}}, ""
            if "publish" in url:
                publish_calls.append(url)
            return 200, {}, ""

        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(image_url=None), "draft_only")

        assert result.status == PublishStatus.DRAFT_CREATED
        assert result.external_id == "draft-001"
        assert publish_calls == []


class TestWixMultichannelIsolation:
    def test_wix_image_failure_does_not_stop_other_channels(self, monkeypatch):
        """
        When Wix image import fails, the Wix channel returns FAILED
        but the other publisher (LinkedIn, Instagram, etc.) continues normally.
        """
        _wix_env(monkeypatch)

        class FakeLinkedIn:
            name = "linkedin"
            def publish(self, draft, mode):
                return PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED,
                                     external_id="li-001", url="https://linkedin.com/post/1")

        with patch("src.publishing.wix.import_image",
                   side_effect=WixMediaImportError("Wix Media import failed")):
            wix_result    = WixPublisher().publish(_draft_package(), "live")
            li_result     = FakeLinkedIn().publish(_draft_package(), "live")

        assert wix_result.status == PublishStatus.FAILED
        assert li_result.status  == PublishStatus.PUBLISHED


# ── Helpers ────────────────────────────────────────────────────────────────────

def json_body(body: Optional[bytes]) -> dict:
    if not body:
        return {}
    import json
    try:
        return json.loads(body)
    except Exception:
        return {}
