"""Issue #52: canonical research execution, persistence, gating, and reuse."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.artifacts import ArtifactCollisionError
from src.intake import from_jsonl_signal
from src.research.evidence import (
    EvidenceDisposition, EvidenceReadiness, ExtractedEvidence,
    NormalizedResearchArtifact, NormalizedSource, PublicationTime,
    PublicationTimeStatus, SourceLocator, SourceLocatorKind, SupportReference,
)
from src.research.lifecycle import (
    ResearchGateError, build_research_request, build_source_directives,
    execute_and_persist_research, load_research_envelope, validate_research_envelope,
    MissingCredentialResearchProvider,
)
from src.research.provider import (
    CompleteResearchResult, PartialResearchResult, ProviderAttribution,
    ProviderFailure, ProviderFailureCode, ProviderInvocation,
    ResearchOperationOutcome, ResearchResultEnvelope, RetrievalStatus,
    SourceOrigin, SourcePriority, SourceRetrievalOutcome,
)
from src.run import ExecutionMode, RunContext
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext
from tests import test_generate_and_publish as legacy


class ReadyProvider:
    def __init__(self, *, readiness=EvidenceReadiness.READY,
                 disposition=EvidenceDisposition.ACCEPTED, partial=False):
        self.readiness, self.disposition, self.partial = readiness, disposition, partial
        self.requests = []

    def research(self, request):
        self.requests.append(request)
        started = request.requested_at
        completed = started + timedelta(seconds=1)
        source = NormalizedSource(
            source_id="source-1",
            locator=SourceLocator(kind=SourceLocatorKind.URL, value="https://source.example/report"),
            title="Verified report", publication_time=PublicationTime(status=PublicationTimeStatus.UNKNOWN),
            retrieved_at=started,
        )
        evidence = ExtractedEvidence(
            evidence_id="evidence-1", claim="A verified claim", source_ids=("source-1",),
            support=(SupportReference(source_id="source-1", excerpt="A verified claim"),),
            disposition=self.disposition,
        )
        artifact = NormalizedResearchArtifact(
            artifact_id="artifact-1", run_id=request.run_id,
            assignment_id=request.assignment_id, signal_id=request.signal_id,
            configuration_identity=request.strategy.identity, created_at=completed,
            sources=(source,), evidence=(evidence,), readiness=self.readiness,
        )
        invocation = ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id="preassessed-test", adapter_id="ready-test", adapter_version="1",
                invocation_id="22222222-2222-4222-8222-222222222222",
            ), started_at=started, completed_at=completed, attempt_count=1,
        )
        retrieved = SourceRetrievalOutcome(
            retrieval_id="retrieval-1", directive_id=request.source_directives[0].directive_id,
            source_id="source-1", origin=SourceOrigin.CLIENT_SUPPLIED,
            locator="https://source.example/report", status=RetrievalStatus.RETRIEVED,
            attempted_at=started, retrieved_at=started,
        )
        base = dict(
            request_run_id=request.run_id, request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id, invocation=invocation,
        )
        if self.partial:
            failure = ProviderFailure(code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
                                      message="one source failed", retryable=True)
            failed = SourceRetrievalOutcome(
                retrieval_id="retrieval-2", origin=SourceOrigin.CLIENT_SUPPLIED,
                locator="https://failed.example/report", status=RetrievalStatus.FAILED,
                attempted_at=started, failure=failure,
            )
            return PartialResearchResult(
                outcome=ResearchOperationOutcome.PARTIAL, source_outcomes=(retrieved, failed),
                artifact=artifact, operation_failure=failure, **base,
            )
        return CompleteResearchResult(
            outcome=ResearchOperationOutcome.COMPLETE, source_outcomes=(retrieved,),
            artifact=artifact, operation_failure=None, **base,
        )


@pytest.fixture
def lifecycle(tmp_path):
    strategy = StrategyExecutionContext.from_configuration(load_business_strategy_configuration())
    signal = dict(legacy._RAW_SIGNAL)
    assignment = from_jsonl_signal(
        signal, strategy_ref=legacy._STRATEGY_STUB.strategy_id,
        strategy_version=legacy._STRATEGY_STUB.strategy_version,
        submitted_at=datetime.now(timezone.utc),
    )
    run = RunContext.from_assignment(
        assignment, ExecutionMode.DRY_RUN, configuration_identity=strategy.identity
    )
    request = build_research_request(
        run, assignment, signal, strategy.research, now=datetime.now(timezone.utc)
    )
    return tmp_path, strategy, signal, assignment, run, request


def test_source_priority_is_deterministic_and_typed(lifecycle):
    _, _, signal, *_ = lifecycle
    signal.update(PREFERRED_SOURCES="preferred.example", ALLOW_OPEN_DISCOVERY="true",
                  EXCLUDED_SOURCES="blocked.example")
    assert [d.priority for d in build_source_directives(signal)] == [
        SourcePriority.REQUIRED, SourcePriority.PREFERRED,
        SourcePriority.DISCOVERY, SourcePriority.EXCLUDED,
    ]


def test_ready_envelope_is_persisted_canonically_and_strictly_reloaded(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    artifact = execute_and_persist_research(
        ReadyProvider(), request, run_dir, identity=strategy.identity,
        run_started_at=run.started_at, clock=lambda: request.requested_at + timedelta(seconds=2),
    )
    path = run_dir / "research.json"
    envelope = load_research_envelope(root, assignment.assignment_id, run.run_id)
    assert path.read_bytes() == envelope.canonical_json().encode()
    assert envelope.result.artifact == artifact


@pytest.mark.parametrize("readiness", [
    EvidenceReadiness.NEEDS_REVIEW, EvidenceReadiness.INSUFFICIENT,
    EvidenceReadiness.BLOCKED,
])
def test_non_ready_complete_result_is_persisted_honestly_then_blocked(lifecycle, readiness):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    with pytest.raises(ResearchGateError, match="not ready"):
        execute_and_persist_research(
            ReadyProvider(readiness=readiness, disposition=EvidenceDisposition.NOT_ASSESSED),
            request, run_dir, identity=strategy.identity, run_started_at=run.started_at,
            clock=lambda: request.requested_at + timedelta(seconds=2),
        )
    persisted = load_research_envelope(root, assignment.assignment_id, run.run_id)
    assert persisted.result.artifact.readiness is readiness


def test_partial_result_with_artifact_is_persisted_then_blocked(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    with pytest.raises(ResearchGateError, match="partial"):
        execute_and_persist_research(
            ReadyProvider(readiness=EvidenceReadiness.NEEDS_REVIEW,
                          disposition=EvidenceDisposition.NOT_ASSESSED, partial=True),
            request, run_dir, identity=strategy.identity, run_started_at=run.started_at,
            clock=lambda: request.requested_at + timedelta(seconds=2),
        )
    assert (run_dir / "research.json").exists()


def test_missing_credentials_are_a_typed_persisted_failure(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    with pytest.raises(ResearchGateError, match="failed"):
        execute_and_persist_research(
            MissingCredentialResearchProvider(), request, run_dir,
            identity=strategy.identity, run_started_at=run.started_at,
            clock=lambda: request.requested_at + timedelta(seconds=1),
        )
    envelope = load_research_envelope(root, assignment.assignment_id, run.run_id)
    assert envelope.result.operation_failure.code is ProviderFailureCode.AUTHENTICATION


def test_existing_research_artifact_is_never_overwritten(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    kwargs = dict(identity=strategy.identity, run_started_at=run.started_at,
                  clock=lambda: request.requested_at + timedelta(seconds=2))
    execute_and_persist_research(ReadyProvider(), request, run_dir, **kwargs)
    before = (run_dir / "research.json").read_bytes()
    with pytest.raises(ArtifactCollisionError):
        execute_and_persist_research(ReadyProvider(), request, run_dir, **kwargs)
    assert (run_dir / "research.json").read_bytes() == before


def test_simulated_commit_failure_leaves_no_target_or_temp_file(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    with mock.patch("src.artifacts.os.link", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            execute_and_persist_research(
                ReadyProvider(), request, run_dir, identity=strategy.identity,
                run_started_at=run.started_at,
                clock=lambda: request.requested_at + timedelta(seconds=2),
            )
    assert not (run_dir / "research.json").exists()
    assert not list(run_dir.glob(".tmp_*.json"))


def test_corrupt_and_noncanonical_research_are_rejected(lifecycle):
    root, _, _, assignment, run, _ = lifecycle
    path = root / assignment.assignment_id / "runs" / run.run_id / "research.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"broken":')
    with pytest.raises(ResearchGateError, match="malformed"):
        load_research_envelope(root, assignment.assignment_id, run.run_id)


def test_current_run_identity_and_configuration_mismatch_fail_closed(lifecycle):
    _, strategy, _, assignment, run, request = lifecycle
    result = ReadyProvider().research(request)
    envelope = ResearchResultEnvelope(request=request, result=result)
    with pytest.raises(ResearchGateError, match="current run"):
        validate_research_envelope(
            envelope, run_id="11111111-1111-4111-8111-111111111111",
            assignment_id=assignment.assignment_id, signal_id=assignment.assignment_id,
            identity=strategy.identity, run_started_at=run.started_at,
            now=request.requested_at + timedelta(seconds=2),
        )


def test_future_invalid_provider_timing_fails_closed(lifecycle):
    _, strategy, _, assignment, run, request = lifecycle
    result = ReadyProvider().research(request)
    envelope = ResearchResultEnvelope(request=request, result=result)
    with pytest.raises(ResearchGateError, match="clock skew"):
        validate_research_envelope(
            envelope, run_id=run.run_id, assignment_id=assignment.assignment_id,
            signal_id=assignment.assignment_id, identity=strategy.identity,
            run_started_at=run.started_at, now=request.requested_at - timedelta(minutes=10),
        )


def test_provider_invocation_before_current_run_is_rejected(lifecycle):
    _, strategy, _, assignment, run, request = lifecycle
    result = ReadyProvider().research(request)
    envelope = ResearchResultEnvelope(request=request, result=result)
    with pytest.raises(ResearchGateError, match="predates"):
        validate_research_envelope(
            envelope, run_id=run.run_id, assignment_id=assignment.assignment_id,
            signal_id=assignment.assignment_id, identity=strategy.identity,
            run_started_at=request.requested_at + timedelta(milliseconds=1),
            now=request.requested_at + timedelta(seconds=2),
        )


def test_source_run_reuse_loads_without_rewriting_bytes(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    execute_and_persist_research(
        ReadyProvider(), request, run_dir, identity=strategy.identity,
        run_started_at=run.started_at,
        clock=lambda: request.requested_at + timedelta(seconds=2),
    )
    before = (run_dir / "research.json").read_bytes()
    envelope = load_research_envelope(root, assignment.assignment_id, run.run_id)
    artifact = validate_research_envelope(
        envelope, run_id=run.run_id, assignment_id=assignment.assignment_id,
        signal_id=assignment.assignment_id, identity=strategy.identity,
        run_started_at=envelope.request.freshness.retrieved_not_before,
        now=request.requested_at + timedelta(seconds=2),
    )
    assert artifact.readiness is EvidenceReadiness.READY
    assert (run_dir / "research.json").read_bytes() == before


def test_canonical_main_persists_ready_research_before_editorial(tmp_path):
    argv, patches = legacy._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    del patches["execute_and_persist_research"]
    generated = patches["generate_article"]

    def assert_research_precedes_editorial(*args, **kwargs):
        files = list(tmp_path.glob("*/runs/*/research.json"))
        assert len(files) == 1
        assert isinstance(kwargs["research_artifact"], NormalizedResearchArtifact)
        return legacy._FAKE_ARTICLE

    generated.side_effect = assert_research_precedes_editorial
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider()) == 0


def test_canonical_main_blocks_nonready_before_all_downstream_effects(tmp_path):
    argv, patches = legacy._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    del patches["execute_and_persist_research"]
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(
            readiness=EvidenceReadiness.NEEDS_REVIEW,
            disposition=EvidenceDisposition.NOT_ASSESSED,
        )) == 1
    patches["generate_article"].assert_not_called()
    assert list(tmp_path.glob("*/runs/*/research.json"))
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
