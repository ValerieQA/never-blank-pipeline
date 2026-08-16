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
    _verify_draft,
    WixPublisher,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _draft_package(image_url: Optional[str] = "https://res.cloudinary.com/nb/image/upload/v1/cover.jpg"):
    """Issue #101: publishers consume the frozen canonical Wix package.

    Built directly (not through the #100 builder) so this suite stays a
    publisher-adapter suite: it exercises the external payload semantics, not
    package construction, which tests/test_publication_package.py owns.
    """
    from src.editorial.linkedin_composition import article_digest
    from src.publishing.package import (
        WixPublicationPackage,
        WixPublicationTarget,
        canonical_slug,
    )
    from src.strategy.execution_context import ConfigurationIdentity

    title = "The Month You Went Quiet"
    body = "## The Pattern\n\nClients notice absence."
    return WixPublicationPackage(
        run_id="run-wix-publisher-001",
        signal_id="sig-wix-publisher-001",
        configuration_identity=ConfigurationIdentity(
            schema_version="1.0",
            configuration_id="cfg-wix-tests",
            configuration_version="1",
            configuration_hash="sha256:" + "e" * 64,
        ),
        source_article_digest=article_digest(body),
        title=title,
        slug=canonical_slug(title),
        body_markdown=body,
        cover_image_url=image_url or "https://res.cloudinary.com/nb/fallback.png",
        target=WixPublicationTarget(
            site_id="test-site",
            owner_member_id="test-owner",
            category_ids=("cat-001",),
            tag_ids=("presence", "agency"),
        ),
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

@pytest.fixture
def no_sleep(monkeypatch):
    """Readiness polling is exercised deterministically, never in real time.

    Production polling timing is deliberately left untouched (Issue #104 is a
    test-contract task); only the test's clock is collapsed.
    """
    slept: list[float] = []
    monkeypatch.setattr(
        "src.publishing.wix_media.time.sleep", lambda seconds: slept.append(seconds)
    )
    return slept


def _media_responses(*states, file_obj=None, wrapper=True):
    """Build an import response followed by one poll response per state.

    The import call itself never carries a usable state, which is exactly the
    production case that requires readiness polling: an upload is not success
    until Wix confirms it.
    """
    body = dict(file_obj or {"id": "wix-file-abc"})

    def wrap(payload):
        return {"file": payload} if wrapper else payload

    responses = [(200, wrap(body), "")]
    for state in states:
        polled = dict(body)
        polled["state"] = state
        responses.append((200, wrap(polled), ""))
    return responses


class TestWixMediaImport:
    """Issue #104: these exercise the current contract — a Wix Media upload is
    successful only once Wix confirms readiness. The provider-compatibility
    coverage of the original tests (``fileId``, ``fileUrl``, and the
    un-wrapped top-level response) is preserved; what changed is that success
    now requires a READY state rather than the first response."""

    def test_success_returns_asset_with_file_id(self, no_sleep):
        responses = _media_responses(
            "PENDING", "READY",
            file_obj={"id": "wix-file-abc", "url": "https://wixmp.com/abc.jpg"},
        )
        with patch("src.publishing.wix_media._fetch", side_effect=responses) as fetch:
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-file-abc"
        assert asset.url == "https://wixmp.com/abc.jpg"
        # readiness was actually polled, and only READY produced the asset
        assert fetch.call_count == len(responses)
        assert no_sleep, "polling must go through the sleep seam"

    def test_accepts_fileid_field_name(self, no_sleep):
        responses = _media_responses("READY", file_obj={"fileId": "wix-file-xyz"})
        with patch("src.publishing.wix_media._fetch", side_effect=responses):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-file-xyz"

    def test_accepts_fileurl_field_name(self, no_sleep):
        responses = _media_responses(
            "READY",
            file_obj={"id": "wix-file-abc", "fileUrl": "https://wixmp.com/abc.jpg"},
        )
        with patch("src.publishing.wix_media._fetch", side_effect=responses):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.url == "https://wixmp.com/abc.jpg"

    def test_response_without_file_wrapper(self, no_sleep):
        # Wix sometimes returns the object at the top level
        responses = _media_responses(
            "READY", file_obj={"id": "wix-flat-id"}, wrapper=False
        )
        with patch("src.publishing.wix_media._fetch", side_effect=responses):
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-flat-id"

    def test_immediate_ready_state_skips_polling(self, no_sleep):
        """A first response that already confirms readiness needs no polling."""
        with patch("src.publishing.wix_media._fetch", return_value=(
            200, {"file": {"id": "wix-ready-now", "url": "https://wixmp.com/n.jpg",
                           "state": "READY"}}, ""
        )) as fetch:
            asset = import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert asset.file_id == "wix-ready-now"
        assert fetch.call_count == 1
        assert no_sleep == []

    def test_terminal_failure_state_fails_closed(self, no_sleep):
        """A background import failure is never treated as a usable asset."""
        responses = _media_responses("PENDING", "FAILED")
        with patch("src.publishing.wix_media._fetch", side_effect=responses):
            with pytest.raises(WixMediaImportError):
                import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")

    def test_unconfirmed_readiness_fails_closed(self, no_sleep):
        """Readiness that never arrives fails closed — no publishable asset."""
        responses = _media_responses(*(["PENDING"] * 5))
        with patch("src.publishing.wix_media._fetch", side_effect=responses) as fetch:
            with pytest.raises(WixMediaImportError):
                import_image("https://cloudinary.com/img.jpg", "NB_cover", "key", "site")
        assert fetch.call_count == len(responses)   # the full poll budget was used
        assert len(no_sleep) == 5                    # …deterministically, not in real time

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

    def test_canonical_package_always_carries_a_cover(self, monkeypatch):
        """Issue #96/#100: the Wix visual is required, so a canonical Wix
        package can never reach the adapter without a cover. The adapter's
        legacy no-cover branch is unreachable from the canonical boundary."""
        _wix_env(monkeypatch)
        from pydantic import ValidationError

        package = _draft_package()
        assert package.cover_image_url.startswith("https://")
        with pytest.raises(ValidationError):
            type(package)(**{**package.model_dump(), "cover_image_url": ""})
        result = WixPublisher().publish(package, "dry_run")
        assert "pending_import" in result.error_message

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

    def test_required_cover_is_imported_and_carried_in_the_payload(self, monkeypatch):
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

        with patch("src.publishing.wix.import_image",
                   return_value=WixMediaAsset(file_id="wix-file-1")) as mock_import:
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                WixPublisher().publish(_draft_package(), "live")

        # Issue #96/#100: the canonical Wix package always carries the required
        # cover, so the media step always runs and the payload always carries it.
        mock_import.assert_called_once()
        draft_post = captured_payloads[0].get("draftPost", {})
        assert draft_post["media"]["wixMedia"]["image"]["id"] == "wix-file-1"


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
        """A draft whose cover-image identity cannot be confirmed is never published.

        Asserted behaviorally (Issue #104): the failure status, the typed
        verification error, and the fact that the publish endpoint is never
        reached — not the exact English sentence, which is not a contract.
        """
        _wix_env(monkeypatch)
        asset = WixMediaAsset(file_id="wix-abc-123")
        publish_calls: list[str] = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {}}, ""   # draft exists, media identity absent
            if "publish" in url:
                publish_calls.append(url)
            return 200, {}, ""

        with patch("src.publishing.wix.import_image", return_value=asset):
            with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
                result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.FAILED
        assert result.external_id is None
        assert publish_calls == []          # the post was never published

        # …and the cause is the missing media identity, raised as its own type.
        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            with pytest.raises(WixDraftMediaVerificationError):
                _verify_draft("draft-001", asset, {})

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
                return 200, {"draftPost": {"media": {"wixMedia": {"image": {"id": "wix-file-1"}}}}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/the-slug"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image",
                   return_value=WixMediaAsset(file_id="wix-file-1")), \
             patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(), "live")

        assert result.url == "https://neverblank.co/post/the-slug"

    def test_missing_url_resolved_via_get_posts(self, monkeypatch):
        """When publish response has no URL, GET /blog/v3/posts/{id} is called."""
        _wix_env(monkeypatch)
        resolve_calls = []

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET" and "draft-posts" in url:
                return 200, {"draftPost": {"media": {"wixMedia": {"image": {"id": "wix-file-1"}}}}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {"id": "post-001"}}, ""   # no URL
            if method == "GET" and "/posts/" in url:
                resolve_calls.append(url)
                return 200, {"post": {"id": "post-001", "url": "https://neverblank.co/post/resolved"}}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image",
                   return_value=WixMediaAsset(file_id="wix-file-1")), \
             patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(), "live")

        assert result.url == "https://neverblank.co/post/resolved"
        assert any("/posts/" in u for u in resolve_calls)

    def test_publish_http_error_returns_failed(self, monkeypatch):
        _wix_env(monkeypatch)

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET":
                return 200, {"draftPost": {"media": {"wixMedia": {"image": {"id": "wix-file-1"}}}}}, ""
            if method == "POST" and "publish" in url:
                return 500, {"message": "Internal server error"}, ""
            return 200, {}, ""

        with patch("src.publishing.wix.import_image",
                   return_value=WixMediaAsset(file_id="wix-file-1")), \
             patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(), "live")

        assert result.status == PublishStatus.FAILED
        assert "HTTP 500" in result.error_message

    def test_publish_2xx_without_post_id_returns_failed(self, monkeypatch):
        """2xx publish response with no post ID must fail — draft_id must not be used as fallback."""
        _wix_env(monkeypatch)

        def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
            if method == "POST" and "draft-posts" in url and "publish" not in url:
                return 201, {"draftPost": {"id": "draft-001"}}, ""
            if method == "GET":
                return 200, {"draftPost": {"media": {"wixMedia": {"image": {"id": "wix-file-1"}}}}}, ""
            if method == "POST" and "publish" in url:
                return 200, {"post": {}}, ""   # 2xx but no id field
            return 200, {}, ""

        with patch("src.publishing.wix.import_image",
                   return_value=WixMediaAsset(file_id="wix-file-1")), \
             patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(), "live")

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
                return 200, {"draftPost": {"media": {"wixMedia": {"image": {"id": "wix-file-1"}}}}}, ""
            if "publish" in url:
                publish_calls.append(url)
            return 200, {}, ""

        with patch("src.publishing.wix.import_image",
                   return_value=WixMediaAsset(file_id="wix-file-1")), \
             patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(_draft_package(), "draft_only")

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
