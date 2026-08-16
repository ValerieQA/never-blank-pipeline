"""Issue #100 follow-up: the package target IS the external target.

The canonical publication package records a non-secret publication target.
These tests prove the external publisher actually uses that package-derived
target — the environment provides the target exactly once, at package
construction, and no second target selection happens at the publisher
boundary. Otherwise the package (and its digest) would identify target A
while the real external side effect went to target B, which is precisely the
target-level TOCTOU seam Issue #101 could not close by hashing the package.

Credential secrets stay environment-only and are never carried by any
package or by the adapter-facing boundary.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from src.publishing.base import DraftPackage
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.package import (
    LinkedInPublicationTarget,
    WixPublicationTarget,
)
from src.publishing.result import PublishStatus
from src.publishing.wix import WixPublisher
from src.publishing.wix_media import WixMediaAsset
from tests.test_publication_package import (
    _build_linkedin,
    _build_wix,
)

# Target A — recorded in the canonical packages under review.
SITE_A = "site-AAAA-authorized"
MEMBER_A = "member-AAAA-authorized"
ACCOUNT_A = "zernio-account-AAAA"

# Target B — a later, unauthorized environment state.
SITE_B = "site-BBBB-hijacked"
MEMBER_B = "member-BBBB-hijacked"
ACCOUNT_B = "zernio-account-BBBB"

API_KEY = "wix-secret-key-do-not-leak"
ZERNIO_KEY = "zernio-secret-key-do-not-leak"


def _draft_from_packages(tmp_path):
    """Derive the publisher-facing object exactly as the entrypoint does."""

    wix_package = _build_wix(
        tmp_path,
        target=WixPublicationTarget(
            site_id=SITE_A, owner_member_id=MEMBER_A, category_ids=("cat-1",),
        ),
    )
    linkedin_package = _build_linkedin(
        tmp_path, target=LinkedInPublicationTarget(account_id=ACCOUNT_A)
    )
    draft = DraftPackage(
        draft_dir=tmp_path,
        blog_title=wix_package.title,
        blog_body=wix_package.body_markdown,
        blog_meta={"title": wix_package.title, "wix_slug": wix_package.slug},
        linkedin_text=linkedin_package.linkedin_body,
        instagram_text="",
        facebook_text="",
        threads_sequence=[],
        telegram_text="",
        image_url=wix_package.cover_image_url,
        platform_image_urls={
            "blog": wix_package.cover_image_url,
            "linkedin": linkedin_package.linkedin_image_url,
        },
        wix_slug=wix_package.slug,
        wix_category_id=wix_package.target.category_ids[0],
        wix_tags=list(wix_package.target.tag_ids),
        wix_site_id=wix_package.target.site_id,
        wix_owner_member_id=wix_package.target.owner_member_id,
        linkedin_account_id=linkedin_package.target.account_id,
        run_id=wix_package.run_id,
        metadata={},
    )
    return wix_package, linkedin_package, draft


def _hijack_environment(monkeypatch):
    """Environment moves to target B AFTER the packages were constructed."""

    monkeypatch.setenv("NB_WIX_API_KEY", API_KEY)
    monkeypatch.setenv("NB_WIX_SITE_ID", SITE_B)
    monkeypatch.setenv("NB_WIX_POST_OWNER_ID", MEMBER_B)
    monkeypatch.setenv("NB_ZERNIO_API_KEY", ZERNIO_KEY)
    monkeypatch.setenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", ACCOUNT_B)


# ── Wix target TOCTOU ────────────────────────────────────────────────────────


def test_wix_publishes_to_package_target_after_environment_moves(tmp_path, monkeypatch):
    _, _, draft = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)
    calls: list[dict] = []

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        calls.append({"url": url, "method": method, "headers": dict(headers or {}),
                      "body": body})
        if method == "POST" and "draft-posts" in url and "publish" not in url:
            return 201, {"draftPost": {"id": "draft-001"}}, ""
        if method == "GET" and "draft-posts" in url:
            return 200, {"draftPost": {
                "media": {"wixMedia": {"image": {"id": "wix-file-1"}}}
            }}, ""
        if method == "POST" and "publish" in url:
            return 200, {"post": {"id": "post-001",
                                  "url": "https://neverblank.co/post/x"}}, ""
        return 200, {}, ""

    with patch("src.publishing.wix.import_image",
               return_value=WixMediaAsset(file_id="wix-file-1")):
        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(draft, "live")

    assert result.status == PublishStatus.PUBLISHED
    assert calls, "the publisher must have made outbound calls"

    # Every outbound request identifies site A.
    site_headers = {call["headers"].get("wix-site-id") for call in calls}
    assert site_headers == {SITE_A}

    # The created post is authored by member A.
    create = next(
        call for call in calls
        if call["method"] == "POST" and "draft-posts" in call["url"]
        and "publish" not in call["url"]
    )
    payload = json.loads(create["body"].decode())
    assert payload["draftPost"]["memberId"] == MEMBER_A

    # Target B never appears anywhere in the outbound traffic.
    serialized = json.dumps(
        [{**call, "body": (call["body"] or b"").decode()} for call in calls]
    )
    assert SITE_B not in serialized
    assert MEMBER_B not in serialized


def test_wix_image_import_uses_package_site(tmp_path, monkeypatch):
    """The media-import step is a Wix side effect too — it must target site A."""

    _, _, draft = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)
    seen: dict = {}

    def fake_import(*, source_url, display_name, api_key, site_id):
        seen.update(site_id=site_id, api_key=api_key)
        return WixMediaAsset(file_id="wix-file-1")

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        if method == "POST" and "draft-posts" in url and "publish" not in url:
            return 201, {"draftPost": {"id": "draft-001"}}, ""
        if method == "GET" and "draft-posts" in url:
            return 200, {"draftPost": {
                "media": {"wixMedia": {"image": {"id": "wix-file-1"}}}
            }}, ""
        return 200, {"post": {"id": "post-001", "url": "https://nb.co/x"}}, ""

    with patch("src.publishing.wix.import_image", side_effect=fake_import):
        with patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            WixPublisher().publish(draft, "live")

    assert seen["site_id"] == SITE_A
    assert seen["site_id"] != SITE_B
    # …while the credential still comes from the environment.
    assert seen["api_key"] == API_KEY


def test_wix_without_package_target_fails_closed(tmp_path, monkeypatch):
    """A draft carrying no package target never falls back to the environment."""

    _, _, draft = _draft_from_packages(tmp_path)
    draft.wix_site_id = ""
    draft.wix_owner_member_id = ""
    _hijack_environment(monkeypatch)

    with patch("src.publishing.wix._fetch") as fetch:
        with patch("src.publishing.wix.import_image") as importer:
            result = WixPublisher().publish(draft, "live")

    assert result.status == PublishStatus.FAILED
    assert "package target identity" in result.error_message
    fetch.assert_not_called()
    importer.assert_not_called()


# ── LinkedIn target TOCTOU ───────────────────────────────────────────────────


def test_linkedin_posts_to_package_account_after_environment_moves(tmp_path, monkeypatch):
    _, _, draft = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)
    calls: list[dict] = []

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        calls.append({"url": url, "headers": dict(headers or {}), "body": body})
        return 201, {"post": {"_id": "zernio-post-1"}}, ""

    with patch("src.publishing.linkedin._fetch", side_effect=fake_fetch):
        result = LinkedInPublisher().publish(draft, "live")

    assert result.status == PublishStatus.PUBLISHED
    assert len(calls) == 1
    payload = json.loads(calls[0]["body"].decode())
    assert payload["platforms"][0]["accountId"] == ACCOUNT_A
    assert ACCOUNT_B not in json.dumps(payload)
    assert ACCOUNT_B not in json.dumps(calls[0]["headers"])


def test_linkedin_dry_run_reports_package_account(tmp_path, monkeypatch):
    _, _, draft = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)

    with patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(draft, "dry_run")

    assert result.status == PublishStatus.SKIPPED
    assert ACCOUNT_A in result.error_message
    assert ACCOUNT_B not in result.error_message
    fetch.assert_not_called()


def test_linkedin_without_package_target_fails_closed(tmp_path, monkeypatch):
    _, _, draft = _draft_from_packages(tmp_path)
    draft.linkedin_account_id = ""
    _hijack_environment(monkeypatch)

    with patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(draft, "live")

    assert result.status == PublishStatus.FAILED
    assert "package target identity" in result.error_message
    fetch.assert_not_called()


# ── Credential boundary ──────────────────────────────────────────────────────


def test_api_keys_are_read_from_environment_at_the_publisher_boundary(tmp_path, monkeypatch):
    """Credential readiness stays where it is (Issue #101 owns preflight)."""

    _, _, draft = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)

    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)
    with patch("src.publishing.wix._fetch") as fetch:
        wix_result = WixPublisher().publish(draft, "live")
    assert wix_result.status == PublishStatus.FAILED
    assert "NB_WIX_API_KEY" in wix_result.error_message
    fetch.assert_not_called()

    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    with patch("src.publishing.linkedin._fetch") as fetch:
        li_result = LinkedInPublisher().publish(draft, "live")
    assert li_result.status == PublishStatus.FAILED
    assert "NB_ZERNIO_API_KEY" in li_result.error_message
    fetch.assert_not_called()


def test_api_keys_never_enter_packages_or_the_target_boundary(tmp_path, monkeypatch):
    _hijack_environment(monkeypatch)
    wix_package, linkedin_package, draft = _draft_from_packages(tmp_path)

    for package in (wix_package, linkedin_package):
        dumped = package.model_dump_json()
        assert API_KEY not in dumped
        assert ZERNIO_KEY not in dumped

    boundary = json.dumps(
        {
            "wix_site_id": draft.wix_site_id,
            "wix_owner_member_id": draft.wix_owner_member_id,
            "linkedin_account_id": draft.linkedin_account_id,
            "metadata": draft.metadata,
            "blog_meta": draft.blog_meta,
        }
    )
    assert API_KEY not in boundary
    assert ZERNIO_KEY not in boundary
    # The non-secret target boundary carries identifiers, and only those.
    assert draft.wix_site_id == SITE_A
    assert draft.wix_owner_member_id == MEMBER_A
    assert draft.linkedin_account_id == ACCOUNT_A


def test_target_identity_survives_the_package_digest(tmp_path):
    """A different target is a different package — the digest binds the target."""

    wix_a, li_a, _ = _draft_from_packages(tmp_path)
    wix_b = _build_wix(
        tmp_path,
        target=WixPublicationTarget(
            site_id=SITE_B, owner_member_id=MEMBER_B, category_ids=("cat-1",),
        ),
    )
    li_b = _build_linkedin(
        tmp_path, target=LinkedInPublicationTarget(account_id=ACCOUNT_B)
    )
    assert wix_a.package_digest() != wix_b.package_digest()
    assert li_a.package_digest() != li_b.package_digest()
