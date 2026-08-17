"""Issue #108 / Story #19: the LinkedIn adapter contract.

The Wix adapter has had a dedicated contract suite for a long time; LinkedIn
had none, and all of its coverage was incidental to other suites. This is that
suite.

Every test drives a fake transport. `src.publishing.linkedin._fetch` is
patched in each case, so nothing here can reach Zernio or publish anything —
the only network seam the adapter has is the one being replaced.

What it pins down is the truthfulness of the result: the adapter never invents
a publication identifier, never presents the generic LinkedIn feed as the
created post's URL, and never reports a provider duplicate as a publication.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from src.publishing.linkedin import LinkedInPublisher
from src.publishing.package import LinkedInPublicationTarget
from src.publishing.result import PublishStatus, UrlProvenance
from tests.test_publication_package import _build_linkedin

ACCOUNT = "zernio-account-contract"
API_KEY = "zernio-secret-key-never-leaked"
POST_ID = "zernio-post-1234"
POST_URL = "https://www.linkedin.com/feed/update/urn:li:share:1234"
FEED_URL = "https://www.linkedin.com/feed/"


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("NB_ZERNIO_API_KEY", API_KEY)


def _package(tmp_path, **overrides):
    return _build_linkedin(
        tmp_path,
        target=LinkedInPublicationTarget(account_id=ACCOUNT),
        **overrides,
    )


def _transport(code, payload, calls=None):
    """A fake Zernio transport that records what it was asked to send."""

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        if calls is not None:
            calls.append({"url": url, "method": method,
                          "headers": dict(headers or {}), "body": body})
        return code, payload, ""

    return fake_fetch


def _publish(tmp_path, code, payload, *, calls=None, package=None):
    with mock.patch("src.publishing.linkedin._fetch",
                    side_effect=_transport(code, payload, calls)):
        return LinkedInPublisher().publish(package or _package(tmp_path), "live")


# ── A publication must be identifiable ───────────────────────────────────────


def test_success_with_id_and_url_is_provider_confirmed(tmp_path, credentials):
    result = _publish(
        tmp_path, 201,
        {"post": {"_id": POST_ID,
                  "platforms": [{"platform": "linkedin", "url": POST_URL}]}},
    )
    assert result.status is PublishStatus.PUBLISHED
    assert result.external_id == POST_ID
    assert result.url == POST_URL
    assert result.url_provenance is UrlProvenance.PROVIDER_CONFIRMED


def test_success_without_url_stays_published_but_url_is_unavailable(
    tmp_path, credentials
):
    """A real publication with no returned URL is still a real publication."""

    result = _publish(tmp_path, 201, {"post": {"_id": POST_ID}})
    assert result.status is PublishStatus.PUBLISHED
    assert result.external_id == POST_ID
    assert result.url_provenance is UrlProvenance.UNAVAILABLE
    # the generic feed is never presented as the created post's URL
    serialized = json.dumps(result.to_dict())
    assert FEED_URL not in serialized
    assert "linkedin.com/feed" not in serialized


def test_two_xx_without_publication_id_fails_closed(tmp_path, credentials):
    """No identifier is invented for a response that identifies no post."""

    result = _publish(tmp_path, 200, {"post": {"platforms": []}})
    assert result.status is PublishStatus.FAILED
    assert result.external_id is None
    serialized = json.dumps(result.to_dict())
    assert "unknown" not in serialized
    assert result.ok() is False and result.completed() is False


def test_blank_publication_id_is_also_not_a_publication(tmp_path, credentials):
    result = _publish(tmp_path, 201, {"post": {"_id": "   "}})
    assert result.status is PublishStatus.FAILED
    assert "unknown" not in json.dumps(result.to_dict())


def test_alternative_id_field_is_accepted(tmp_path, credentials):
    """Zernio's response shape varies; a real id under `id` still counts."""

    result = _publish(tmp_path, 201, {"post": {"id": POST_ID}})
    assert result.status is PublishStatus.PUBLISHED
    assert result.external_id == POST_ID


def test_unwrapped_response_shape_is_accepted(tmp_path, credentials):
    result = _publish(tmp_path, 201, {"_id": POST_ID})
    assert result.status is PublishStatus.PUBLISHED
    assert result.external_id == POST_ID


# ── Provider duplicate is neither success nor reuse ──────────────────────────


def test_provider_duplicate_is_its_own_state(tmp_path, credentials):
    """A 409 proves a duplicate exists, never which post exists."""

    result = _publish(tmp_path, 409, {"message": "duplicate content"})
    assert result.status is PublishStatus.PROVIDER_DUPLICATE
    assert result.external_id is None
    assert result.url is None
    assert result.url_provenance is UrlProvenance.UNAVAILABLE
    # neither a successful publication nor a completed channel
    assert result.ok() is False
    assert result.completed() is False
    assert result.status is not PublishStatus.REUSED


def test_provider_duplicate_carries_no_proof_of_a_publication(tmp_path, credentials):
    """The state a future reuse check would have to read carries no proof.

    Issue #108 can assert the *contract* of the persisted evidence: a
    provider-duplicate result is neither a publication nor a reuse, and it
    carries no external ID and no URL — the two things any suppression
    decision would need. It deliberately does **not** assert behavioral
    non-suppression, because no LinkedIn idempotency scan exists yet:
    Issue #109 owns that machinery and will prove non-suppression against
    the real LinkedIn scan when it is built. Reaching for the Wix scan here
    would prove something about Wix, not about LinkedIn.
    """

    result = _publish(tmp_path, 409, {"message": "duplicate content"})

    assert result.status is PublishStatus.PROVIDER_DUPLICATE
    assert result.status is not PublishStatus.PUBLISHED
    assert result.status is not PublishStatus.REUSED
    assert result.ok() is False
    assert result.completed() is False
    # nothing a suppression decision could ever key on
    assert result.external_id is None
    assert result.url is None
    assert result.url_provenance is UrlProvenance.UNAVAILABLE
    assert result.reused_from_run_id is None

    persisted = result.to_dict()
    assert persisted["status"] == "PROVIDER_DUPLICATE"
    assert persisted["external_id"] is None
    assert persisted["url"] is None


def test_provider_duplicate_is_excluded_from_run_status_sets():
    """It must count as neither successful nor completed in the entrypoint."""

    import scripts.generate_and_publish as gap

    assert PublishStatus.PROVIDER_DUPLICATE.value not in gap._OK_STATUSES
    assert PublishStatus.PROVIDER_DUPLICATE.value not in gap._COMPLETED_STATUSES


def test_provider_duplicate_is_persisted_truthfully_by_a_real_run(
    tmp_path, monkeypatch
):
    """Behavioral proof at the persisted-evidence boundary (Issue #108 scope).

    A real canonical run whose Zernio call answers 409 must record the
    provider-duplicate state in its own ``publication_results.json`` — never
    as a success — leave the run incomplete, and append no LinkedIn
    publication-history entry. This is the evidence a future LinkedIn
    idempotency scan (#109) will read, so recording it truthfully is what
    #108 can and does guarantee.
    """

    from tests.test_publication_preflight import _live_run, _target_env
    from tests import test_generate_and_publish as legacy

    _target_env(monkeypatch)
    monkeypatch.setenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", ACCOUNT)
    history = mock.MagicMock()

    # the real adapter, with the provider answering 409
    with mock.patch("src.publishing.linkedin._fetch",
                    side_effect=_transport(409, {"message": "duplicate content"})):
        code, wix_mock, _, _ = _live_run(
            tmp_path,
            LinkedInPublisher=LinkedInPublisher,
            append_published_entry=history,
        )

    published = json.loads(
        max(
            tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/publication_results.json"),
            key=lambda path: path.stat().st_mtime,
        ).read_text()
    )
    linkedin = published["results"]["linkedin"]
    assert linkedin["status"] == "PROVIDER_DUPLICATE"
    assert linkedin["external_id"] is None
    assert linkedin["url"] is None
    assert linkedin["url_provenance"] == "unavailable"

    # the run is not complete, and the channel is not history-recorded
    assert published["completed"] is False
    assert code == 1
    assert "linkedin" not in history.call_args.args[0].publications
    # the other channel is unaffected
    assert wix_mock.publish.called
    assert published["results"]["wix"]["status"] == "PUBLISHED"


# ── Error normalization and the credential boundary ──────────────────────────


def test_provider_error_is_normalized_without_secrets(tmp_path, credentials):
    result = _publish(tmp_path, 500, {"message": "upstream exploded"})
    assert result.status is PublishStatus.FAILED
    assert "500" in result.error_message
    assert API_KEY not in json.dumps(result.to_dict())


def test_missing_credential_fails_before_any_call(tmp_path, monkeypatch):
    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    with mock.patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(_package(tmp_path), "live")
    assert result.status is PublishStatus.FAILED
    assert "NB_ZERNIO_API_KEY" in result.error_message
    fetch.assert_not_called()


def test_api_key_never_appears_in_any_result(tmp_path, credentials):
    for code, payload in (
        (201, {"post": {"_id": POST_ID}}),
        (409, {"message": "duplicate"}),
        (500, {"message": "boom"}),
        (200, {"post": {}}),
    ):
        result = _publish(tmp_path, code, payload)
        assert API_KEY not in json.dumps(result.to_dict())
        assert API_KEY not in (result.error_message or "")


# ── The payload is derived only from the authorized package ──────────────────


def test_payload_carries_exactly_the_package_body_and_account(tmp_path, credentials):
    calls: list[dict] = []
    package = _package(tmp_path)
    result = _publish(tmp_path, 201, {"post": {"_id": POST_ID}},
                      calls=calls, package=package)
    assert result.status is PublishStatus.PUBLISHED
    assert len(calls) == 1
    payload = json.loads(calls[0]["body"].decode())
    assert payload["content"] == package.linkedin_body
    assert payload["platforms"] == [
        {"platform": "linkedin", "accountId": package.target.account_id}
    ]
    assert payload["publishNow"] is True


def test_media_item_appears_only_when_the_package_carries_a_visual(
    tmp_path, credentials
):
    from tests.test_publication_package import _visual

    with_visual = _package(tmp_path)
    assert with_visual.linkedin_image_url
    calls: list[dict] = []
    _publish(tmp_path, 201, {"post": {"_id": POST_ID}}, calls=calls,
             package=with_visual)
    payload = json.loads(calls[0]["body"].decode())
    assert payload["mediaItems"] == [
        {"type": "image", "url": with_visual.linkedin_image_url}
    ]

    text_only = _build_linkedin(
        tmp_path,
        target=LinkedInPublicationTarget(account_id=ACCOUNT),
        visual_record=_visual(tmp_path, with_linkedin=False),
    )
    assert text_only.linkedin_image_url is None
    calls.clear()
    _publish(tmp_path, 201, {"post": {"_id": POST_ID}}, calls=calls,
             package=text_only)
    assert "mediaItems" not in json.loads(calls[0]["body"].decode())


def test_configuration_mismatch_with_the_strategy_view_fails(tmp_path, credentials):
    from tests.test_publication_package import FOREIGN_CONFIG

    view = mock.MagicMock(identity=FOREIGN_CONFIG)
    with mock.patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(
            _package(tmp_path), "live", strategy_view=view
        )
    assert result.status is PublishStatus.FAILED
    fetch.assert_not_called()


# ── Non-live modes never reach the network ───────────────────────────────────


def test_dry_run_makes_no_call_and_reports_the_package_account(tmp_path, credentials):
    with mock.patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(_package(tmp_path), "dry_run")
    assert result.status is PublishStatus.SKIPPED
    assert ACCOUNT in result.error_message
    fetch.assert_not_called()


def test_draft_only_is_skipped_without_calling_the_provider(tmp_path, credentials):
    with mock.patch("src.publishing.linkedin._fetch") as fetch:
        result = LinkedInPublisher().publish(_package(tmp_path), "draft_only")
    assert result.status is PublishStatus.SKIPPED
    fetch.assert_not_called()
