"""Issue #105 / Story #18: Wix retry idempotency and truthful URL provenance.

Deterministic only. Nothing here proves a real Wix publication — live
verification against a real site remains on the deferred track. What these
prove is that a retry of an already-published accepted article creates no
second Wix post, that ambiguous history never manufactures that suppression,
and that a locally constructed URL is never reported as provider-confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.editorial.linkedin_composition import article_digest
from src.publishing.idempotency import (
    UNUSABLE_INCONSISTENT,
    UNUSABLE_MALFORMED_RESULTS,
    UNUSABLE_MISSING_CONTENT_ID,
    UNUSABLE_MISSING_PREFLIGHT,
    WixPublicationIdentity,
    find_prior_wix_publication,
)
from src.publishing.package import WixPublicationTarget
from src.publishing.preflight import (
    ChannelPreflightVerdict,
    FreshnessVerdict,
    PreflightDisposition,
    PreflightResult,
    ProvenanceVerdict,
    ReadinessVerdict,
)
from src.publishing.result import PublishStatus, UrlProvenance
from src.publishing.wix import WixPublisher, _resolve_post_url
from src.publishing.wix_media import WixMediaAsset
from tests.test_publication_package import (
    CONFIG,
    FOREIGN_CONFIG,
    RUN,
    SIG,
    _build_wix,
)
from tests.test_linkedin_composition import ARTICLE_BODY

SITE_A = "site-aaaa"
SITE_B = "site-bbbb"
PRIOR_RUN = "run-prior-0001"
POST_ID = "wix-post-777"
PROVIDER_URL = "https://neverblank.co/blog/the-month-you-went-quiet"


def _target(site_id=SITE_A, owner="member-1"):
    return WixPublicationTarget(site_id=site_id, owner_member_id=owner)


def _identity(tmp_path, *, site_id=SITE_A, owner="member-1", article=ARTICLE_BODY):
    package = _build_wix(
        tmp_path,
        target=_target(site_id, owner),
        generated=_generated(article=article),
    )
    return WixPublicationIdentity.from_package(package)


def _generated(*, article=ARTICLE_BODY, **overrides):
    from tests.test_publication_package import _generated as base

    data = base(**overrides)
    data["blog_article"] = article
    return data


def _write_prior_run(
    packages_dir: Path,
    *,
    run_id=PRIOR_RUN,
    status="PUBLISHED",
    post_id=POST_ID,
    url=PROVIDER_URL,
    url_provenance="provider_confirmed",
    site_id=SITE_A,
    owner="member-1",
    article=ARTICLE_BODY,
    with_preflight=True,
    preflight_disposition=PreflightDisposition.ALLOW,
    malformed_results=False,
    signal_id=SIG,
    configuration=CONFIG,
):
    """Materialize one prior run's canonical publication evidence."""

    run_dir = packages_dir / signal_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    gen_dir = packages_dir / signal_id / "runs" / f"{run_id}-gen"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "generated.json").write_text(
        json.dumps({"run_id": f"{run_id}-gen", "signal_id": signal_id,
                    "blog_article": article}),
        encoding="utf-8",
    )
    if malformed_results:
        (run_dir / "publication_results.json").write_text("{not json", encoding="utf-8")
    else:
        entry = {
            "platform": "wix", "status": status, "external_id": post_id,
            "url": url, "error_message": None, "run_id": run_id,
        }
        if url_provenance is not None:
            entry["url_provenance"] = url_provenance
        (run_dir / "publication_results.json").write_text(
            json.dumps({
                "run_id": run_id, "signal_id": signal_id,
                "generation_run_id": f"{run_id}-gen",
                "configuration_identity": configuration.model_dump(),
                "results": {"wix": entry},
                "completed": True, "errors": [],
            }),
            encoding="utf-8",
        )
    if with_preflight:
        verdict = PreflightResult(
            run_id=run_id,
            signal_id=signal_id,
            configuration_identity=configuration,
            evaluated_at="2026-08-16T00:00:00+00:00",
            override_state="none",
            provenance=ProvenanceVerdict(verified=True, run_kind="generation",
                                         stopped_after="publication"),
            readiness=ReadinessVerdict(verified=True),
            freshness=FreshnessVerdict(verified=True),
            configuration_consistent=True,
            run_disposition=PreflightDisposition.ALLOW,
            channels=(
                ChannelPreflightVerdict(
                    channel="wix",
                    package_digest="sha256:" + "b" * 64,
                    target=_target(site_id, owner),
                    package_valid=True,
                    credential_ready=True,
                    disposition=preflight_disposition,
                    blocking_reasons=()
                    if preflight_disposition is PreflightDisposition.ALLOW
                    else ("credential_missing",),
                ),
            ),
        )
        (run_dir / "preflight_result.json").write_text(
            verdict.model_dump_json(), encoding="utf-8"
        )
    return run_dir


def _scan(tmp_path, **identity_kwargs):
    return find_prior_wix_publication(
        tmp_path, _identity(tmp_path, **identity_kwargs), current_run_id="run-current"
    )


# ── Proven prior publication suppresses a duplicate ──────────────────────────


def test_proven_prior_publication_is_found(tmp_path):
    _write_prior_run(tmp_path)
    scan = _scan(tmp_path)
    assert scan.match is not None
    assert scan.match.run_id == PRIOR_RUN
    assert scan.match.post_id == POST_ID
    assert scan.match.url == PROVIDER_URL
    assert scan.match.url_provenance is UrlProvenance.PROVIDER_CONFIRMED
    assert scan.unusable_count == 0


def test_different_run_id_still_matches(tmp_path):
    """The retry identity deliberately excludes run_id."""
    _write_prior_run(tmp_path, run_id="run-some-older-attempt")
    assert _scan(tmp_path).match is not None


def test_different_configuration_still_matches(tmp_path):
    """Configuration is provenance, not a republish switch."""
    _write_prior_run(tmp_path, configuration=FOREIGN_CONFIG)
    scan = _scan(tmp_path)
    assert scan.match is not None, "a configuration change must not authorize a duplicate"


def test_different_owner_member_id_still_matches(tmp_path):
    """Author metadata is not the destination — it cannot unlock a duplicate."""
    _write_prior_run(tmp_path, owner="member-someone-else")
    assert _scan(tmp_path, owner="member-1").match is not None


# ── Legitimately different publications are not suppressed ───────────────────


def test_different_site_publishes_independently(tmp_path):
    _write_prior_run(tmp_path, site_id=SITE_B)
    scan = _scan(tmp_path, site_id=SITE_A)
    assert scan.match is None
    assert scan.unusable_count == 0          # a different destination is not "unusable"


def test_different_article_publishes_independently(tmp_path):
    other = ARTICLE_BODY + "\n\nA later paragraph changes the accepted article."
    _write_prior_run(tmp_path, article=other)
    scan = _scan(tmp_path, article=ARTICLE_BODY)
    assert scan.match is None
    assert scan.unusable_count == 0


@pytest.mark.parametrize("status", ["DRAFT_CREATED", "FAILED", "BLOCKED", "SKIPPED", "REUSED"])
def test_non_published_prior_status_never_suppresses(tmp_path, status):
    """Only a proven live publication counts — a draft is not a publication."""
    _write_prior_run(tmp_path, status=status)
    scan = _scan(tmp_path)
    assert scan.match is None
    assert scan.unusable_count == 0


# ── Ambiguity never manufactures idempotency ─────────────────────────────────


def test_malformed_prior_results_do_not_suppress(tmp_path):
    _write_prior_run(tmp_path, malformed_results=True)
    scan = _scan(tmp_path)
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MALFORMED_RESULTS,)


def test_missing_prior_preflight_does_not_suppress(tmp_path):
    _write_prior_run(tmp_path, with_preflight=False)
    scan = _scan(tmp_path)
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MISSING_PREFLIGHT,)


def test_missing_prior_content_id_does_not_suppress(tmp_path):
    _write_prior_run(tmp_path, post_id="")
    scan = _scan(tmp_path)
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MISSING_CONTENT_ID,)


def test_prior_preflight_blocking_wix_is_inconsistent_evidence(tmp_path):
    _write_prior_run(tmp_path, preflight_disposition=PreflightDisposition.BLOCK)
    scan = _scan(tmp_path)
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_INCONSISTENT,)


def test_unreadable_prior_article_evidence_does_not_suppress(tmp_path):
    run_dir = _write_prior_run(tmp_path)
    (tmp_path / SIG / "runs" / f"{PRIOR_RUN}-gen" / "generated.json").unlink()
    scan = _scan(tmp_path)
    assert scan.match is None
    assert scan.unusable_count == 1
    assert run_dir.exists()


def test_unusable_evidence_note_is_sanitized(tmp_path):
    _write_prior_run(tmp_path, malformed_results=True, run_id="run-a")
    _write_prior_run(tmp_path, with_preflight=False, run_id="run-b")
    note = _scan(tmp_path).evidence_note()
    assert note == {
        "count": 2,
        "reasons": sorted({UNUSABLE_MALFORMED_RESULTS, UNUSABLE_MISSING_PREFLIGHT}),
    }
    # typed reason codes only — no raw artifact content
    assert "not json" not in json.dumps(note)


def test_no_prior_runs_at_all(tmp_path):
    scan = _scan(tmp_path)
    assert scan.match is None and scan.unusable_count == 0
    assert scan.evidence_note() is None


def test_the_current_run_never_matches_itself(tmp_path):
    _write_prior_run(tmp_path, run_id="run-current")
    scan = find_prior_wix_publication(
        tmp_path, _identity(tmp_path), current_run_id="run-current"
    )
    assert scan.match is None


def test_prior_record_without_provenance_is_not_promoted(tmp_path):
    """A URL whose origin was never recorded is never called provider-confirmed."""
    _write_prior_run(tmp_path, url_provenance=None)
    scan = _scan(tmp_path)
    assert scan.match is not None
    assert scan.match.url == PROVIDER_URL
    assert scan.match.url_provenance is UrlProvenance.UNAVAILABLE


# ── URL provenance at the adapter boundary ───────────────────────────────────


def test_provider_returned_url_is_provider_confirmed():
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"slug": "the-slug", "url": PROVIDER_URL}}, ""
    )):
        url, provenance = _resolve_post_url("post-1", {})
    assert url == PROVIDER_URL
    assert provenance is UrlProvenance.PROVIDER_CONFIRMED


def test_local_fallback_is_locally_derived(monkeypatch):
    monkeypatch.setenv("NB_WIX_SITE_BASE_URL", "https://neverblank.co/")
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"slug": "the-slug"}}, ""
    )):
        url, provenance = _resolve_post_url("post-1", {})
    assert url == "https://neverblank.co/blog/the-slug"
    assert provenance is UrlProvenance.LOCALLY_DERIVED


def test_no_usable_url_is_unavailable(monkeypatch):
    monkeypatch.delenv("NB_WIX_SITE_BASE_URL", raising=False)
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"slug": "the-slug"}}, ""
    )):
        url, provenance = _resolve_post_url("post-1", {})
    assert url == ""
    assert provenance is UrlProvenance.UNAVAILABLE

    with mock.patch("src.publishing.wix._fetch", return_value=(404, {}, "")):
        url, provenance = _resolve_post_url("post-1", {})
    assert (url, provenance) == ("", UrlProvenance.UNAVAILABLE)


def test_publish_carries_url_provenance(tmp_path, monkeypatch):
    """A live publish records where its URL came from."""
    monkeypatch.setenv("NB_WIX_API_KEY", "secret")
    package = _build_wix(tmp_path, target=_target())

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        if method == "POST" and "draft-posts" in url and "publish" not in url:
            return 201, {"draftPost": {"id": "draft-1"}}, ""
        if method == "GET" and "draft-posts" in url:
            return 200, {"draftPost": {
                "media": {"wixMedia": {"image": {"id": "file-1"}}}
            }}, ""
        if "publish" in url:
            return 200, {"post": {"id": POST_ID, "url": PROVIDER_URL}}, ""
        return 200, {}, ""

    with mock.patch("src.publishing.wix.import_image",
                    return_value=WixMediaAsset(file_id="file-1")):
        with mock.patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(package, "live")

    assert result.status is PublishStatus.PUBLISHED
    assert result.external_id == POST_ID
    assert result.url_provenance is UrlProvenance.PROVIDER_CONFIRMED
    assert result.to_dict()["url_provenance"] == "provider_confirmed"


# ── End-to-end through the canonical entrypoint ──────────────────────────────
#
# These run the real idempotency check inside main(), with the real #101
# preflight, to prove the side-effect placement: a proven prior publication
# suppresses the Wix call entirely (no media import, no draft, no publish),
# while everything ambiguous still publishes.

import sys  # noqa: E402

import scripts.generate_and_publish as gap  # noqa: E402
from scripts.generate_and_publish import main  # noqa: E402
from tests import test_generate_and_publish as legacy  # noqa: E402
from tests.test_publication_preflight import _live_run, _target_env  # noqa: E402


def _prior_for_live_run(tmp_path, monkeypatch, **overrides):
    """Write prior evidence matching what the live harness run will produce."""

    from tests.test_linkedin_composition import ARTICLE_BODY as LIVE_ARTICLE

    _target_env(monkeypatch)
    monkeypatch.setenv("NB_WIX_SITE_ID", SITE_A)
    monkeypatch.setenv("NB_WIX_POST_OWNER_ID", "member-live")
    defaults = dict(
        signal_id=legacy._SIGNAL_ID,
        site_id=SITE_A,
        owner="member-live",
        article=LIVE_ARTICLE,
    )
    defaults.update(overrides)
    return _write_prior_run(tmp_path, **defaults)


def _real_scan_run(tmp_path, **overrides):
    """`_live_run` with the real idempotency scan wired back in."""

    overrides.setdefault("find_prior_wix_publication", find_prior_wix_publication)
    return _live_run(tmp_path, **overrides)


def _current_publication(tmp_path):
    """The publication evidence of the run under test, not of the seeded prior."""

    paths = [
        path
        for path in tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/publication_results.json")
        if not path.parent.name.startswith("run-")   # seeded prior runs
    ]
    assert len(paths) == 1, f"expected one current publication record, got {paths}"
    return json.loads(paths[0].read_text())


def test_sequential_retry_reuses_and_calls_no_wix_endpoint(tmp_path, monkeypatch):
    _prior_for_live_run(tmp_path, monkeypatch)
    with mock.patch("src.publishing.wix.import_image") as media, \
         mock.patch("src.publishing.wix._fetch") as fetch:
        code, wix_mock, li_mock, verdicts = _real_scan_run(tmp_path)

    # the publisher class was never asked to publish…
    wix_mock.publish.assert_not_called()
    # …and no Wix network work happened at all
    media.assert_not_called()
    fetch.assert_not_called()
    assert li_mock.publish.called          # the other channel is unaffected

    published = _current_publication(tmp_path)
    wix = published["results"]["wix"]
    assert wix["status"] == "REUSED"
    assert wix["external_id"] == POST_ID
    assert wix["url"] == PROVIDER_URL
    assert wix["url_provenance"] == "provider_confirmed"
    assert wix["reused_from_run_id"] == PRIOR_RUN
    assert published["wix_reused_from_run_id"] == PRIOR_RUN
    assert wix["run_id"] and wix["run_id"] != PRIOR_RUN    # current identity kept apart
    assert published["completed"] is True                  # a reuse is not a failure
    assert code == 0


def test_reused_run_does_not_append_a_second_history_entry(tmp_path, monkeypatch):
    _prior_for_live_run(tmp_path, monkeypatch)
    history = mock.MagicMock()
    with mock.patch("src.publishing.wix.import_image"), \
         mock.patch("src.publishing.wix._fetch"):
        _real_scan_run(tmp_path, append_published_entry=history)
    entry = history.call_args.args[0]
    assert "wix" not in entry.publications, (
        "a retry must not be recorded as a second freshly published Wix post"
    )


def test_first_publication_publishes_exactly_once(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    code, wix_mock, li_mock, verdicts = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1
    published = _current_publication(tmp_path)
    assert published["results"]["wix"]["status"] == "PUBLISHED"
    assert published["wix_reused_from_run_id"] is None
    assert published["unusable_prior_publication_evidence"] is None


def test_prior_draft_does_not_suppress_live_publication(tmp_path, monkeypatch):
    _prior_for_live_run(tmp_path, monkeypatch, status="DRAFT_CREATED")
    code, wix_mock, _, _ = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1


@pytest.mark.parametrize("status", ["FAILED", "BLOCKED", "SKIPPED"])
def test_prior_unsuccessful_result_does_not_suppress(tmp_path, monkeypatch, status):
    _prior_for_live_run(tmp_path, monkeypatch, status=status)
    code, wix_mock, _, _ = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1


def test_unusable_prior_evidence_is_recorded_and_publication_proceeds(
    tmp_path, monkeypatch
):
    _prior_for_live_run(tmp_path, monkeypatch, malformed_results=True)
    code, wix_mock, _, _ = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1
    published = _current_publication(tmp_path)
    note = published["unusable_prior_publication_evidence"]
    assert note == {"count": 1, "reasons": [UNUSABLE_MALFORMED_RESULTS]}
    assert published["results"]["wix"]["status"] == "PUBLISHED"


def test_preflight_block_is_never_bypassed_by_idempotency(tmp_path, monkeypatch):
    """A blocked channel never reaches the idempotency check at all."""

    _prior_for_live_run(tmp_path, monkeypatch)
    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)   # Wix credential missing
    with mock.patch("src.publishing.wix.import_image") as media, \
         mock.patch("src.publishing.wix._fetch") as fetch:
        code, wix_mock, li_mock, verdicts = _real_scan_run(tmp_path)

    wix_mock.publish.assert_not_called()
    media.assert_not_called()
    fetch.assert_not_called()
    published = _current_publication(tmp_path)
    # blocked, never reused — the prior publication cannot rescue a blocked run
    assert published["results"]["wix"]["status"] == "BLOCKED"
    assert published["wix_reused_from_run_id"] is None
