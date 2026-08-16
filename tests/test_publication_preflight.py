"""Issue #101 / Story #17: fail-closed publication preflight.

Every test drives the real preflight contract with real canonical packages
and deterministic fake transports. The invariant under test is that no
external Wix/Zernio call can happen without a preserved ALLOW verdict bound
to the exact frozen package that crosses the boundary.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from pydantic import ValidationError

from src.artifacts import (
    ArtifactCollisionError,
    resolve_run_dir,
    write_preflight_result_json,
)
from src.artifacts.provenance import ProvenanceError
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.package import (
    LinkedInPublicationTarget,
    WixPublicationTarget,
)
from src.publishing.preflight import (
    BlockingReason,
    ChannelPreflightVerdict,
    FreshnessVerdict,
    OverrideState,
    PreflightDisposition,
    PreflightResult,
    ProvenanceVerdict,
    evaluate_publication_preflight,
)
from src.publishing.result import PublishStatus
from src.publishing.wix import WixPublisher
from src.publishing.wix_media import WixMediaAsset
from tests.test_publication_package import (
    CONFIG,
    FOREIGN_CONFIG,
    RUN,
    SIG,
    _build_linkedin,
    _build_wix,
)

FRESH = FreshnessVerdict(verified=True, rules=("configuration_identity_matches_active_strategy",))
STALE = FreshnessVerdict(
    verified=False,
    rules=("source_package_generated_at_not_before_strategy_start",),
    failure_reason="package generated before the active strategy started",
)


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("NB_WIX_API_KEY", "wix-secret")
    monkeypatch.setenv("NB_ZERNIO_API_KEY", "zernio-secret")


def _evaluate(tmp_path, *, provenance_ok=True, **overrides):
    """Evaluate preflight with real packages; provenance is stubbed per case."""

    kwargs = dict(
        packages_dir=tmp_path / "packages",
        run_id=RUN,
        signal_id=SIG,
        configuration_identity=CONFIG,
        wix_package=_build_wix(tmp_path),
        linkedin_package=_build_linkedin(tmp_path),
        override_attempted=False,
        freshness=FRESH,
    )
    kwargs.update(overrides)
    report = mock.MagicMock(run_kind="generation", stopped_after="publication")
    patch = mock.patch(
        "src.publishing.preflight.verify_run_provenance",
        return_value=report
        if provenance_ok
        else mock.DEFAULT,
        side_effect=None
        if provenance_ok
        else ProvenanceError("run evidence is corrupted"),
    )
    with patch:
        return evaluate_publication_preflight(**kwargs)


# ── Happy path ───────────────────────────────────────────────────────────────


def test_valid_run_allows_both_channels(tmp_path, credentials):
    result = _evaluate(tmp_path)
    assert result.run_disposition is PreflightDisposition.ALLOW
    assert result.allowed_channels() == ("wix", "linkedin")
    assert result.override_state is OverrideState.NONE
    assert result.provenance.verified is True
    assert result.run_blocking_reasons == ()
    for verdict in result.channels:
        assert verdict.disposition is PreflightDisposition.ALLOW
        assert verdict.credential_ready is True
        assert verdict.blocking_reasons == ()


def test_verdict_digest_is_the_digest_of_the_exact_package(tmp_path, credentials):
    wix = _build_wix(tmp_path)
    linkedin = _build_linkedin(tmp_path)
    result = _evaluate(tmp_path, wix_package=wix, linkedin_package=linkedin)
    assert result.verdict_for("wix").package_digest == wix.package_digest()
    assert result.verdict_for("linkedin").package_digest == linkedin.package_digest()
    assert result.verdict_for("wix").target == wix.target


# ── Run-level BLOCK ──────────────────────────────────────────────────────────


def test_provenance_failure_blocks_the_whole_run(tmp_path, credentials):
    result = _evaluate(tmp_path, provenance_ok=False)
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert BlockingReason.PROVENANCE_FAILED in result.run_blocking_reasons
    assert result.allowed_channels() == ()
    assert result.provenance.verified is False
    assert "ProvenanceError" in result.provenance.failure_reason
    for verdict in result.channels:
        assert BlockingReason.RUN_BLOCKED in verdict.blocking_reasons


def test_wrong_configuration_blocks_the_whole_run(tmp_path, credentials):
    result = _evaluate(tmp_path, configuration_identity=FOREIGN_CONFIG)
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert BlockingReason.CONFIGURATION_MISMATCH in result.run_blocking_reasons
    assert result.configuration_consistent is False
    assert result.allowed_channels() == ()


def test_existing_freshness_rule_failure_blocks_the_whole_run(tmp_path, credentials):
    result = _evaluate(tmp_path, freshness=STALE)
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert BlockingReason.FRESHNESS_FAILED in result.run_blocking_reasons
    assert result.freshness.failure_reason
    assert result.allowed_channels() == ()


def test_package_from_another_run_blocks_the_whole_run(tmp_path, credentials):
    result = _evaluate(tmp_path, run_id="run-different-999")
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert BlockingReason.RUN_BLOCKED in result.run_blocking_reasons


# ── Override ─────────────────────────────────────────────────────────────────


def test_override_never_converts_block_into_allow(tmp_path, credentials):
    result = _evaluate(tmp_path, provenance_ok=False, override_attempted=True)
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert result.override_state is OverrideState.ATTEMPTED_REJECTED
    assert (
        BlockingReason.OVERRIDE_ATTEMPTED_ON_BLOCKING_CONDITION
        in result.run_blocking_reasons
    )
    assert result.allowed_channels() == ()


def test_override_attempt_without_blocking_condition_is_recorded_truthfully(
    tmp_path, credentials
):
    result = _evaluate(tmp_path, override_attempted=True)
    assert result.run_disposition is PreflightDisposition.ALLOW
    assert result.override_state is OverrideState.ATTEMPTED_REJECTED


def test_preflight_never_claims_an_authorized_actor(tmp_path, credentials):
    result = _evaluate(tmp_path, override_attempted=True)
    serialized = json.loads(result.model_dump_json())
    flattened = json.dumps(serialized).lower()
    for claim in ("authorized_by", "approver", "approved_by", "actor", "user", "email"):
        assert claim not in flattened
    assert set(OverrideState) == {OverrideState.NONE, OverrideState.ATTEMPTED_REJECTED}


# ── Per-channel BLOCK ────────────────────────────────────────────────────────


def test_missing_wix_credential_blocks_only_wix(tmp_path, monkeypatch):
    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)
    monkeypatch.setenv("NB_ZERNIO_API_KEY", "zernio-secret")
    result = _evaluate(tmp_path)
    assert result.run_disposition is PreflightDisposition.ALLOW
    assert result.allowed_channels() == ("linkedin",)
    wix = result.verdict_for("wix")
    assert wix.credential_ready is False
    assert wix.blocking_reasons == (BlockingReason.CREDENTIAL_MISSING,)


def test_missing_linkedin_credential_blocks_only_linkedin(tmp_path, monkeypatch):
    monkeypatch.setenv("NB_WIX_API_KEY", "wix-secret")
    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    result = _evaluate(tmp_path)
    assert result.allowed_channels() == ("wix",)
    assert result.verdict_for("linkedin").blocking_reasons == (
        BlockingReason.CREDENTIAL_MISSING,
    )


def test_missing_both_credentials_blocks_both_channels(tmp_path, monkeypatch):
    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)
    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    result = _evaluate(tmp_path)
    # No shared failure: the run itself is fine, both channels are blocked.
    assert result.run_disposition is PreflightDisposition.ALLOW
    assert result.allowed_channels() == ()


def test_blank_credential_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("NB_WIX_API_KEY", "   ")
    monkeypatch.setenv("NB_ZERNIO_API_KEY", "zernio-secret")
    assert _evaluate(tmp_path).verdict_for("wix").credential_ready is False


def test_linkedin_text_only_package_may_be_allowed(tmp_path, credentials):
    """Story #15 semantics: a genuinely absent LinkedIn visual is valid."""

    from tests.test_publication_package import _visual

    linkedin = _build_linkedin(
        tmp_path, visual_record=_visual(tmp_path, with_linkedin=False)
    )
    assert linkedin.linkedin_image_url is None
    result = _evaluate(tmp_path, linkedin_package=linkedin)
    assert result.verdict_for("linkedin").disposition is PreflightDisposition.ALLOW


# ── Trust boundary of the persisted verdict ──────────────────────────────────


def test_persisted_verdict_carries_no_secrets(tmp_path, monkeypatch):
    secret = "super-secret-api-key-value"
    monkeypatch.setenv("NB_WIX_API_KEY", secret)
    monkeypatch.setenv("NB_ZERNIO_API_KEY", secret)
    result = _evaluate(tmp_path)
    serialized = result.model_dump_json()
    assert secret not in serialized
    for token in ("api_key", "token", "password", "secret", "raw_response"):
        assert token not in serialized.lower()


def test_verdict_is_create_once_and_strictly_reloadable(tmp_path, credentials):
    result = _evaluate(tmp_path)
    run_dir = resolve_run_dir(tmp_path / "packages", SIG, RUN)
    run_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(result.model_dump_json())
    write_preflight_result_json(run_dir, data)
    with pytest.raises(ArtifactCollisionError):
        write_preflight_result_json(run_dir, data)
    reloaded = PreflightResult.model_validate_json(
        (run_dir / "preflight_result.json").read_bytes()
    )
    assert reloaded == result
    assert reloaded.verdict_for("wix").package_digest == result.verdict_for(
        "wix"
    ).package_digest


def test_result_model_is_frozen_and_strict(tmp_path, credentials):
    result = _evaluate(tmp_path)
    with pytest.raises(ValidationError):
        result.run_disposition = PreflightDisposition.BLOCK
    with pytest.raises(ValidationError):
        PreflightResult(**{**result.model_dump(), "authorized_by": "someone"})


# ── Contract self-consistency ────────────────────────────────────────────────


def test_allow_verdict_cannot_carry_blocking_reasons():
    with pytest.raises(ValidationError):
        ChannelPreflightVerdict(
            channel="wix",
            package_digest="sha256:" + "0" * 64,
            target=WixPublicationTarget(site_id="s", owner_member_id="m"),
            package_valid=True,
            credential_ready=True,
            disposition=PreflightDisposition.ALLOW,
            blocking_reasons=(BlockingReason.CREDENTIAL_MISSING,),
        )


def test_block_verdict_must_state_a_reason():
    with pytest.raises(ValidationError):
        ChannelPreflightVerdict(
            channel="linkedin",
            package_digest="sha256:" + "0" * 64,
            target=LinkedInPublicationTarget(account_id="a"),
            package_valid=True,
            credential_ready=True,
            disposition=PreflightDisposition.BLOCK,
        )


def test_run_block_cannot_leave_a_channel_allowed(tmp_path, credentials):
    result = _evaluate(tmp_path)
    allowed = result.verdict_for("wix")
    with pytest.raises(ValidationError):
        PreflightResult(
            **{
                **result.model_dump(),
                "run_disposition": PreflightDisposition.BLOCK,
                "run_blocking_reasons": (BlockingReason.PROVENANCE_FAILED,),
                "channels": (allowed.model_dump(),),
            }
        )


def test_provenance_verdict_must_be_truthful():
    with pytest.raises(ValidationError):
        ProvenanceVerdict(verified=True, failure_reason="but it failed")
    with pytest.raises(ValidationError):
        ProvenanceVerdict(verified=False)


# ── Publisher boundary: only an authorized package crosses it ────────────────


def _wix_transport(calls):
    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        calls.append({"url": url, "method": method, "body": body})
        if method == "POST" and "draft-posts" in url and "publish" not in url:
            return 201, {"draftPost": {"id": "draft-001"}}, ""
        if method == "GET" and "draft-posts" in url:
            return 200, {
                "draftPost": {"media": {"wixMedia": {"image": {"id": "wix-file-1"}}}}
            }, ""
        return 200, {"post": {"id": "post-1", "url": "https://neverblank.co/p"}}, ""

    return fake_fetch


def test_publishers_consume_only_the_frozen_package(tmp_path, credentials):
    """The adapters derive everything from the package they receive."""

    wix = _build_wix(tmp_path)
    linkedin = _build_linkedin(tmp_path)
    calls: list[dict] = []
    with mock.patch(
        "src.publishing.wix.import_image",
        return_value=WixMediaAsset(file_id="wix-file-1"),
    ), mock.patch("src.publishing.wix._fetch", side_effect=_wix_transport(calls)):
        wix_result = WixPublisher().publish(wix, "live")
    assert wix_result.status is PublishStatus.PUBLISHED
    create = next(c for c in calls if c["method"] == "POST" and "publish" not in c["url"])
    payload = json.loads(create["body"].decode())["draftPost"]
    assert payload["title"] == wix.title
    assert payload["slug"] == wix.slug
    assert payload["memberId"] == wix.target.owner_member_id

    li_calls: list[dict] = []

    def fake_li(url, *, method="GET", headers=None, body=None, timeout=20):
        li_calls.append(json.loads(body.decode()))
        return 201, {"post": {"_id": "li-1"}}, ""

    with mock.patch("src.publishing.linkedin._fetch", side_effect=fake_li):
        li_result = LinkedInPublisher().publish(linkedin, "live")
    assert li_result.status is PublishStatus.PUBLISHED
    assert li_calls[0]["content"] == linkedin.linkedin_body
    assert li_calls[0]["platforms"][0]["accountId"] == linkedin.target.account_id


def test_publisher_rejects_a_mutable_stand_in_for_the_package(tmp_path, credentials):
    """A mutable object can no longer masquerade as an authorized package."""

    from types import SimpleNamespace

    impostor = SimpleNamespace(title="x", body_markdown="y")
    with mock.patch("src.publishing.wix._fetch") as fetch:
        with pytest.raises(AttributeError):
            WixPublisher().publish(impostor, "live")
    fetch.assert_not_called()


def test_a_different_package_cannot_reuse_another_verdict(tmp_path, credentials):
    """Digest binding: package B's digest never matches package A's verdict."""

    package_a = _build_wix(tmp_path)
    package_b = _build_wix(
        tmp_path,
        target=WixPublicationTarget(site_id="other-site", owner_member_id="other-member"),
    )
    result = _evaluate(tmp_path, wix_package=package_a)
    verdict = result.verdict_for("wix")
    assert verdict.package_digest == package_a.package_digest()
    assert verdict.package_digest != package_b.package_digest()


# ── End-to-end through the canonical entrypoint ──────────────────────────────
#
# These drive the real preflight gate inside `main()` with real gates for
# research/decision/editorial/LinkedIn/visual, and deterministic publisher
# mocks, to prove the side-effect placement: a BLOCK means zero external calls
# and no fabricated success, and an ALLOW means the verdict artifact already
# exists on disk before the first call.

import sys  # noqa: E402

import scripts.generate_and_publish as gap  # noqa: E402
from scripts.generate_and_publish import main  # noqa: E402
from tests import test_generate_and_publish as legacy  # noqa: E402
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output  # noqa: E402
from tests.test_research_artifact_lifecycle import ReadyProvider  # noqa: E402
from tests.test_visual_contract import _pimgs  # noqa: E402


def _publish_result(platform, external_id, url):
    """Real result object: the entrypoint injects run_id into it."""

    from src.publishing.result import PublishResult

    return PublishResult(
        platform=platform,
        status=PublishStatus.PUBLISHED,
        external_id=external_id,
        url=url,
    )


def _live_run(tmp_path, **overrides):
    """One live canonical run with the real preflight gate wired in."""

    from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    for real_gate in (
        "evaluate_publication_preflight",   # the gate under test
        "write_preflight_result_json",
        "build_visual_assets_record",
        "write_visual_assets_json",
        "accept_linkedin_composition",
        "write_linkedin_composition_json",
        "build_wix_publication_package",
        "build_linkedin_publication_package",
        "WixPublicationTarget",
        "LinkedInPublicationTarget",
    ):
        patches.pop(real_gate, None)
    patches["_load_package_images"] = mock.MagicMock(return_value=_pimgs(tmp_path))
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = ARTICLE_BODY
    article["platforms"]["medium"]["body"] = _native_linkedin_body()
    patches["generate_article"] = mock.MagicMock(return_value=article)
    wix_mock, li_mock = mock.MagicMock(), mock.MagicMock()
    wix_mock.publish.return_value = _publish_result("wix", "w-1", "https://nb.co/p")
    li_mock.publish.return_value = _publish_result("linkedin", "l-1", "https://li.co/p")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix_mock)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li_mock)
    patches.update(overrides)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    verdicts = sorted(tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/preflight_result.json"))
    return code, wix_mock, li_mock, verdicts


def _target_env(monkeypatch, *, wix_key=True, linkedin_key=True):
    monkeypatch.setenv("NB_WIX_SITE_ID", "site-live")
    monkeypatch.setenv("NB_WIX_POST_OWNER_ID", "member-live")
    monkeypatch.setenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", "account-live")
    for present, var in ((wix_key, "NB_WIX_API_KEY"), (linkedin_key, "NB_ZERNIO_API_KEY")):
        if present:
            monkeypatch.setenv(var, "secret")
        else:
            monkeypatch.delenv(var, raising=False)


def test_entrypoint_persists_the_verdict_before_publishing(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    seen_when_publishing: list[bool] = []

    def record_then_publish(*args, **kwargs):
        seen_when_publishing.append(
            bool(list(tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/preflight_result.json")))
        )
        return _publish_result("wix", "w-1", "https://nb.co/p")

    wix_mock = mock.MagicMock()
    wix_mock.publish.side_effect = record_then_publish
    code, _, li_mock, verdicts = _live_run(
        tmp_path, WixPublisher=mock.MagicMock(return_value=wix_mock)
    )
    assert code == 0
    assert len(verdicts) == 1
    # the artifact already existed at the moment of the first external call
    assert seen_when_publishing == [True]
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    assert result.run_disposition is PreflightDisposition.ALLOW
    assert set(result.allowed_channels()) == {"wix", "linkedin"}
    assert li_mock.publish.called


def test_recorded_digest_equals_the_package_handed_to_the_publisher(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    code, wix_mock, li_mock, verdicts = _live_run(tmp_path)
    assert code == 0
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    for channel, publisher in (("wix", wix_mock), ("linkedin", li_mock)):
        package = publisher.publish.call_args.args[0]
        assert package.package_digest() == result.verdict_for(channel).package_digest


def test_missing_wix_credential_blocks_wix_only_end_to_end(tmp_path, monkeypatch):
    _target_env(monkeypatch, wix_key=False)
    code, wix_mock, li_mock, verdicts = _live_run(tmp_path)
    wix_mock.publish.assert_not_called()
    assert li_mock.publish.called
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    assert result.allowed_channels() == ("linkedin",)
    assert code == 1          # the run is not complete while a channel is blocked
    published = json.loads(
        next(tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/publication_results.json")).read_text()
    )
    assert published["results"]["wix"]["status"] == "BLOCKED"
    assert published["completed"] is False


def test_missing_linkedin_credential_blocks_linkedin_only_end_to_end(tmp_path, monkeypatch):
    _target_env(monkeypatch, linkedin_key=False)
    code, wix_mock, li_mock, verdicts = _live_run(tmp_path)
    li_mock.publish.assert_not_called()
    assert wix_mock.publish.called
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    assert result.allowed_channels() == ("wix",)


def test_missing_both_credentials_makes_zero_external_calls(tmp_path, monkeypatch):
    _target_env(monkeypatch, wix_key=False, linkedin_key=False)
    code, wix_mock, li_mock, verdicts = _live_run(tmp_path)
    wix_mock.publish.assert_not_called()
    li_mock.publish.assert_not_called()
    assert code == 1
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    assert result.allowed_channels() == ()


def test_corrupted_provenance_blocks_every_channel_end_to_end(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    with mock.patch(
        "src.publishing.preflight.verify_run_provenance",
        side_effect=ProvenanceError("assignment.json is missing"),
    ):
        code, wix_mock, li_mock, verdicts = _live_run(tmp_path)
    assert code == 1
    wix_mock.publish.assert_not_called()
    li_mock.publish.assert_not_called()
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert BlockingReason.PROVENANCE_FAILED in result.run_blocking_reasons
    # no publication evidence and no history are fabricated for a blocked run
    assert not list(tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/publication_results.json"))


def test_override_attempt_cannot_unblock_the_run_end_to_end(tmp_path, monkeypatch):
    _target_env(monkeypatch)

    def overriding_rc(assignment, raw_signal, run_ctx):
        rc = legacy._make_rc_mock(run_ctx.run_id)
        rc.force_override = True
        return rc

    with mock.patch(
        "src.publishing.preflight.verify_run_provenance",
        side_effect=ProvenanceError("run evidence is corrupted"),
    ):
        code, wix_mock, li_mock, verdicts = _live_run(
            tmp_path,
            _build_legacy_research_context=mock.MagicMock(side_effect=overriding_rc),
        )
    assert code == 1
    wix_mock.publish.assert_not_called()
    li_mock.publish.assert_not_called()
    result = PreflightResult.model_validate_json(verdicts[0].read_bytes())
    assert result.override_state is OverrideState.ATTEMPTED_REJECTED
    assert result.run_disposition is PreflightDisposition.BLOCK
    assert (
        BlockingReason.OVERRIDE_ATTEMPTED_ON_BLOCKING_CONDITION
        in result.run_blocking_reasons
    )


def test_unready_signal_is_never_rescued_by_an_override(tmp_path, monkeypatch):
    """Issue #101: the old silent readiness bypass no longer exists."""

    _target_env(monkeypatch)

    def unready_rc(assignment, raw_signal, run_ctx):
        rc = legacy._make_rc_mock(run_ctx.run_id)
        rc.article_ready = False
        rc.force_override = True
        return rc

    code, wix_mock, li_mock, _ = _live_run(
        tmp_path, _build_legacy_research_context=mock.MagicMock(side_effect=unready_rc)
    )
    assert code == 1
    wix_mock.publish.assert_not_called()
    li_mock.publish.assert_not_called()
