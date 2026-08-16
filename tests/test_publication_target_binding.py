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

from pydantic import ValidationError

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
    """Build the canonical packages — after Issue #101 they ARE the boundary.

    The publisher receives the frozen package directly and derives its
    internal representation from it, so there is no mutable object between
    the authorized package and the external call.
    """

    wix_package = _build_wix(
        tmp_path,
        target=WixPublicationTarget(
            site_id=SITE_A, owner_member_id=MEMBER_A, category_ids=("cat-1",),
        ),
    )
    linkedin_package = _build_linkedin(
        tmp_path, target=LinkedInPublicationTarget(account_id=ACCOUNT_A)
    )
    draft = DraftPackage.from_wix_package(wix_package)
    draft.linkedin_account_id = linkedin_package.target.account_id
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
    wix_package, _, _ = _draft_from_packages(tmp_path)
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
            result = WixPublisher().publish(wix_package, "live")

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

    wix_package, _, _ = _draft_from_packages(tmp_path)
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
            WixPublisher().publish(wix_package, "live")

    assert seen["site_id"] == SITE_A
    assert seen["site_id"] != SITE_B
    # …while the credential still comes from the environment.
    assert seen["api_key"] == API_KEY


def test_wix_target_cannot_be_emptied_after_construction(tmp_path, monkeypatch):
    """The frozen package is the boundary: an absent target is unconstructible,
    and the authorized package cannot be emptied on the way to the publisher."""

    wix_package, _, _ = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)

    with pytest.raises(ValidationError):
        WixPublicationTarget(site_id="", owner_member_id=MEMBER_A)
    with pytest.raises(ValidationError):
        wix_package.target = WixPublicationTarget(
            site_id=SITE_B, owner_member_id=MEMBER_B
        )
    # …and the derived internal representation still carries target A.
    derived = DraftPackage.from_wix_package(wix_package)
    assert derived.wix_site_id == SITE_A
    assert derived.wix_owner_member_id == MEMBER_A


# ── LinkedIn target TOCTOU ───────────────────────────────────────────────────


def test_linkedin_posts_to_package_account_after_environment_moves(tmp_path, monkeypatch):
    _, linkedin_package, _ = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)
    calls: list[dict] = []

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        calls.append({"url": url, "headers": dict(headers or {}), "body": body})
        return 201, {"post": {"_id": "zernio-post-1"}}, ""

    with patch("src.publishing.linkedin._fetch", side_effect=fake_fetch):
        result = LinkedInPublisher().publish(linkedin_package, "live")

    assert result.status == PublishStatus.PUBLISHED
    assert len(calls) == 1
    payload = json.loads(calls[0]["body"].decode())
    assert payload["platforms"][0]["accountId"] == ACCOUNT_A
    assert ACCOUNT_B not in json.dumps(payload)
    assert ACCOUNT_B not in json.dumps(calls[0]["headers"])


def test_linkedin_dry_run_reports_package_account(tmp_path, monkeypatch):
    _, linkedin_package, _ = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)

    with patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(linkedin_package, "dry_run")

    assert result.status == PublishStatus.SKIPPED
    assert ACCOUNT_A in result.error_message
    assert ACCOUNT_B not in result.error_message
    fetch.assert_not_called()


def test_linkedin_target_cannot_be_emptied_after_construction(tmp_path, monkeypatch):
    _, linkedin_package, _ = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)

    with pytest.raises(ValidationError):
        LinkedInPublicationTarget(account_id="")
    with pytest.raises(ValidationError):
        linkedin_package.target = LinkedInPublicationTarget(account_id=ACCOUNT_B)
    derived = DraftPackage.from_linkedin_package(linkedin_package)
    assert derived.linkedin_account_id == ACCOUNT_A


# ── Credential boundary ──────────────────────────────────────────────────────


def test_api_keys_are_read_from_environment_at_the_publisher_boundary(tmp_path, monkeypatch):
    """Credential readiness stays where it is (Issue #101 owns preflight)."""

    wix_package, linkedin_package, _ = _draft_from_packages(tmp_path)
    _hijack_environment(monkeypatch)

    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)
    with patch("src.publishing.wix._fetch") as fetch:
        wix_result = WixPublisher().publish(wix_package, "live")
    assert wix_result.status == PublishStatus.FAILED
    assert "NB_WIX_API_KEY" in wix_result.error_message
    fetch.assert_not_called()

    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    with patch("src.publishing.linkedin._fetch") as fetch:
        li_result = LinkedInPublisher().publish(linkedin_package, "live")
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
