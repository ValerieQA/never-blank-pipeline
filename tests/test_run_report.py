"""Issue #112 / Story #20: the authoritative per-run report.

Every terminal run gets one persisted account of what happened, assembled
from evidence that already exists. These prove that the account is truthful:
it never invents artifacts a stopped run did not produce, never promotes a
partial run to success, never collapses the two channels into one flag, and
is never written at all over evidence that contradicts itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from src.artifacts import ArtifactCollisionError, resolve_run_dir, write_run_report_json
from src.publishing.linkedin import LinkedInPublisher
from src.reporting.run_report import (
    CANONICAL_ARTIFACTS,
    RunReport,
    RunReportError,
    TerminalDisposition,
    TerminalStage,
    build_run_report,
)
from tests import test_generate_and_publish as legacy
from tests.test_publication_preflight import _live_run, _target_env

SIG = legacy._SIGNAL_ID


# ── Helpers: runs are real canonical runs through main() ─────────────────────


def _report_of(run_dir: Path) -> dict:
    return json.loads((run_dir / "run_report.json").read_text())


def _reports(tmp_path) -> list[Path]:
    return sorted(tmp_path.glob(f"{SIG}/runs/*/run_report.json"))


def _newest_run(tmp_path) -> Path:
    runs = [p for p in (tmp_path / SIG / "runs").iterdir() if p.is_dir()]
    return max(runs, key=lambda path: path.stat().st_mtime)


def _live(tmp_path, monkeypatch, **overrides):
    _target_env(monkeypatch)
    return _live_run(tmp_path, **overrides)


# ── Legitimate terminal reports ──────────────────────────────────────────────


def test_full_success_produces_exactly_one_report(tmp_path, monkeypatch):
    code, wix_mock, li_mock, _ = _live(tmp_path, monkeypatch)
    assert code == 0

    reports = _reports(tmp_path)
    assert len(reports) == 1
    report = RunReport.model_validate_json(reports[0].read_bytes())
    assert report.terminal_stage is TerminalStage.PUBLICATION
    assert report.terminal_disposition is TerminalDisposition.COMPLETED
    assert report.completed is True
    assert {c.channel for c in report.channels} == {"wix", "linkedin"}
    assert all(c.status == "PUBLISHED" for c in report.channels)


def test_wix_success_with_linkedin_failure_is_not_full_success(
    tmp_path, monkeypatch
):
    _target_env(monkeypatch)
    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)   # LinkedIn blocked
    code, wix_mock, li_mock, _ = _live_run(tmp_path)

    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    assert report.completed is False
    assert report.terminal_disposition is not TerminalDisposition.COMPLETED
    assert report.channel("wix").status == "PUBLISHED"
    assert report.channel("linkedin").status == "BLOCKED"
    # the two channels stay independent — no common "success"
    assert report.channel("wix").status != report.channel("linkedin").status


def test_linkedin_reuse_is_reported_as_reuse_not_a_fresh_publish(
    tmp_path, monkeypatch
):
    from tests.test_linkedin_idempotency import _seed_prior_run, POST_ID
    from src.publishing.idempotency import find_prior_linkedin_publication

    prior = _seed_prior_run(tmp_path, monkeypatch)
    with mock.patch("src.publishing.linkedin._fetch"):
        _live_run(
            tmp_path,
            LinkedInPublisher=LinkedInPublisher,
            find_prior_linkedin_publication=find_prior_linkedin_publication,
        )

    report = RunReport.model_validate_json(
        (_newest_run(tmp_path) / "run_report.json").read_bytes()
    )
    linkedin = report.channel("linkedin")
    assert linkedin.status == "REUSED"
    assert linkedin.status != "PUBLISHED"
    assert linkedin.external_id == POST_ID
    assert linkedin.reused_from_run_id == prior.name


def test_provider_duplicate_remains_incomplete(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    monkeypatch.setenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", "acct-dup")

    def duplicate(url, *, method="GET", headers=None, body=None, timeout=20):
        return 409, {"message": "duplicate content"}, ""

    with mock.patch("src.publishing.linkedin._fetch", side_effect=duplicate):
        code = _live_run(tmp_path, LinkedInPublisher=LinkedInPublisher)[0]

    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    assert report.channel("linkedin").status == "PROVIDER_DUPLICATE"
    assert report.completed is False
    assert code == 1


def test_preflight_block_reports_with_zero_publisher_effects(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)
    monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    code, wix_mock, li_mock, _ = _live_run(tmp_path)

    wix_mock.publish.assert_not_called()
    li_mock.publish.assert_not_called()
    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    assert report.completed is False
    assert all(c.status == "BLOCKED" for c in report.channels)


# ── Partial terminal runs are legitimate, not corruption ─────────────────────


def _stopped_run(tmp_path, monkeypatch, **patches):
    """A run that terminates before publication, through the real gates."""

    _target_env(monkeypatch)
    return _live_run(tmp_path, **patches)


def test_editorial_rejection_is_a_valid_partial_terminal_report(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    def rejected(**kwargs):
        review = SimpleNamespace(
            disposition=SimpleNamespace(value="reject"),
            failed_criterion_ids=("evidence-support",),
            rationale="not publishable as written",
        )
        return SimpleNamespace(
            accepted=False, revised=False, final_review=review,
            initial_review=review,
            final_article_body=kwargs["article_body"],
            audit={"accepted": False, "final_disposition": "reject"},
        )

    code = _stopped_run(
        tmp_path, monkeypatch,
        run_editorial_acceptance=mock.MagicMock(side_effect=rejected),
    )[0]
    assert code == 1

    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    assert report.terminal_stage is TerminalStage.EDITORIAL
    assert report.terminal_disposition is TerminalDisposition.BLOCKED
    assert report.completed is False
    # a stopped run never gets channels or fabricated downstream artifacts
    assert report.channels == ()
    names = {a.name for a in report.artifacts}
    assert "publication_results.json" not in names
    assert "assignment.json" in names


def test_decision_stop_is_a_valid_partial_terminal_report(tmp_path, monkeypatch):
    from tests.test_decision_lifecycle import _evaluator, _model_output
    from tests.test_research_artifact_lifecycle import ReadyProvider
    import sys
    import scripts.generate_and_publish as gap
    from tests.test_decision_lifecycle import _entry_patches

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    evaluator, _ = _evaluator(_model_output(disposition="hold"))
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = gap.main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    assert code == 1

    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    assert report.terminal_stage is TerminalStage.DECISION
    assert report.terminal_disposition is TerminalDisposition.STOPPED
    assert report.completed is False
    assert report.channels == ()
    names = {a.name for a in report.artifacts}
    assert "decision.json" in names and "generated.json" not in names


def test_research_failure_is_a_valid_partial_terminal_report(tmp_path, monkeypatch):
    import sys
    import scripts.generate_and_publish as gap
    from tests.test_decision_lifecycle import _entry_patches
    from src.research.lifecycle import ResearchGateError

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["execute_and_persist_research"] = mock.MagicMock(
        side_effect=ResearchGateError("provider unavailable")
    )
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = gap.main()
    assert code == 1

    reports = _reports(tmp_path)
    if reports:      # canonical evidence exists only once the namespace is written
        report = RunReport.model_validate_json(reports[0].read_bytes())
        assert report.terminal_stage is TerminalStage.RESEARCH
        assert report.completed is False
        assert report.channels == ()


# ── The report indexes evidence, it does not copy it ─────────────────────────


def test_report_references_artifacts_without_copying_payloads(
    tmp_path, monkeypatch
):
    _live(tmp_path, monkeypatch)
    raw = _reports(tmp_path)[0].read_text()
    data = json.loads(raw)

    referenced = {item["name"] for item in data["artifacts"]}
    assert "publication_results.json" in referenced
    assert referenced <= set(CANONICAL_ARTIFACTS)

    # the payloads of those artifacts are not reproduced
    run_dir = _reports(tmp_path)[0].parent
    generated = json.loads((run_dir / "generated.json").read_text())
    assert generated["blog_article"] not in raw
    assert generated["linkedin_post"] not in raw
    for key in ("blog_article", "linkedin_post", "results", "derivatives"):
        assert f'"{key}"' not in raw or key == "results"


def test_publication_result_is_bound_to_the_authorized_package(
    tmp_path, monkeypatch
):
    """Each channel outcome carries the digest preflight actually authorized."""

    _live(tmp_path, monkeypatch)
    run_dir = _reports(tmp_path)[0].parent
    verdict = json.loads((run_dir / "preflight_result.json").read_text())
    authorized = {
        c["channel"]: c["package_digest"] for c in verdict["channels"]
    }

    report = RunReport.model_validate_json((run_dir / "run_report.json").read_bytes())
    for channel in report.channels:
        assert channel.authorized_package_digest == authorized[channel.channel]
        assert channel.authorized_package_digest.startswith("sha256:")


# ── Corrupt evidence yields no authoritative report ──────────────────────────


def test_corrupt_evidence_produces_no_report(tmp_path, monkeypatch):
    """Provenance decides; a contradictory chain gets no account at all."""

    _live(tmp_path, monkeypatch)
    run_dir = _reports(tmp_path)[0].parent
    (run_dir / "run_report.json").unlink()

    # publication claiming another run than its own namespace
    path = run_dir / "publication_results.json"
    data = json.loads(path.read_text())
    data["run_id"] = "run-claimed-elsewhere"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RunReportError):
        build_run_report(
            tmp_path,
            run_id=run_dir.name,
            signal_id=SIG,
            execution_mode="controlled-live",
            terminal_stage=TerminalStage.PUBLICATION,
            terminal_disposition=TerminalDisposition.COMPLETED,
        )
    assert not (run_dir / "run_report.json").exists()


@pytest.mark.parametrize("mutation", ["configuration", "generation", "signal"])
def test_tampered_lineage_cannot_produce_a_trusted_report(
    tmp_path, monkeypatch, mutation
):
    from tests.test_publication_package import FOREIGN_CONFIG

    _live(tmp_path, monkeypatch)
    run_dir = _reports(tmp_path)[0].parent
    (run_dir / "run_report.json").unlink()
    path = run_dir / "publication_results.json"
    data = json.loads(path.read_text())
    if mutation == "configuration":
        data["configuration_identity"] = FOREIGN_CONFIG.model_dump()
    elif mutation == "generation":
        data["generation_run_id"] = "run-forged"
    else:
        data["signal_id"] = "sig-somewhere-else"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RunReportError):
        build_run_report(
            tmp_path, run_id=run_dir.name, signal_id=SIG,
            execution_mode="controlled-live",
            terminal_stage=TerminalStage.PUBLICATION,
            terminal_disposition=TerminalDisposition.COMPLETED,
        )


def test_missing_run_namespace_produces_no_report(tmp_path):
    with pytest.raises(RunReportError):
        build_run_report(
            tmp_path, run_id="run-that-never-ran", signal_id=SIG,
            execution_mode="controlled-live",
            terminal_stage=TerminalStage.INTAKE,
            terminal_disposition=TerminalDisposition.FAILED,
        )


# ── Create-once and trust boundary ───────────────────────────────────────────


def test_report_is_create_once_and_never_overwritten(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    run_dir = _reports(tmp_path)[0].parent
    original = (run_dir / "run_report.json").read_text()

    with pytest.raises(ArtifactCollisionError):
        write_run_report_json(run_dir, {"schema_version": "1.0"})
    assert (run_dir / "run_report.json").read_text() == original


def test_report_carries_no_credentials_or_provider_payloads(
    tmp_path, monkeypatch
):
    secret = "sk-live-credential-shaped-value-0001"
    for var in ("NB_WIX_API_KEY", "NB_ZERNIO_API_KEY", "NB_WIX_SITE_ID"):
        monkeypatch.setenv(var, secret)
    _live(tmp_path, monkeypatch)

    raw = _reports(tmp_path)[0].read_text()
    assert secret not in raw
    for token in ("api_key", "token", "password", "prompt", "raw_response",
                  "traceback", "Traceback"):
        assert token not in raw


def test_report_rejects_unknown_fields_and_foreign_artifacts(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())

    with pytest.raises(ValidationError):
        RunReport(**{**report.model_dump(), "raw_provider_response": {}})
    with pytest.raises(ValidationError):
        RunReport(
            **{**report.model_dump(),
               "artifacts": [{"name": "secrets.json"}]}
        )


def test_report_is_frozen(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    with pytest.raises(ValidationError):
        report.completed = True


# ── Truthfulness rules in the model itself ───────────────────────────────────


def test_a_stopped_stage_cannot_carry_channel_outcomes(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    with pytest.raises(ValidationError):
        RunReport(
            **{**report.model_dump(), "terminal_stage": TerminalStage.DECISION}
        )


def test_completed_requires_the_completed_disposition(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    with pytest.raises(ValidationError):
        RunReport(
            **{**report.model_dump(),
               "terminal_disposition": TerminalDisposition.FAILED}
        )


def test_unusable_evidence_note_must_be_the_sanitized_shape(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    report = RunReport.model_validate_json(_reports(tmp_path)[0].read_bytes())
    with pytest.raises(ValidationError):
        RunReport(
            **{**report.model_dump(),
               "unusable_prior_evidence": {"raw": "traceback ..."}}
        )
