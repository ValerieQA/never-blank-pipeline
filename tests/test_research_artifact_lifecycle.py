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
    Contradiction, EvidenceAssessorIdentity, EvidenceDisposition,
    EvidenceReadiness, ExtractedEvidence,
    ModelInterpretation,
    NormalizedResearchArtifact, NormalizedSource, PublicationTime,
    PublicationTimeStatus, ResolutionStatus, SourceLocator, SourceLocatorKind,
    SupportReference, UncertaintyAssessment, UncertaintyLevel,
    UncertaintyMateriality,
)
from src.research.lifecycle import (
    ResearchGateError, build_research_request, build_source_directives,
    execute_and_persist_research, load_research_envelope, validate_research_envelope,
    MissingCredentialResearchProvider,
)
from src.research.adapters.fake import (
    DeterministicFakeResearchProvider, FakeResearchScenario,
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
from tests import test_research_provider_adapter as provider_tests


pytestmark = pytest.mark.story11


class RejectingJudgment:
    """Issue #125 fixture adaptation: a typed verdict without a live model.

    These tests supply `not_assessed` evidence, which now reaches the
    assessor. Rejecting keeps each test's original premise — the artifact
    stays non-ready and downstream effects stay blocked — while exercising the
    real assessment path rather than skipping it.
    """

    def __init__(self, disposition="rejected"):
        self.disposition = disposition
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        import json as _json

        self.calls += 1
        payload = _json.loads(request)
        return _json.dumps({"verdicts": [
            {"evidence_id": item["evidence_id"], "disposition": self.disposition,
             "rationale": "Fixture verdict for the assessment path."}
            for item in payload["evidence"]
        ]})


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
            title="Verified report", publication_time=PublicationTime(
                status=PublicationTimeStatus.KNOWN,
                value=started - timedelta(days=1),
            ),
            retrieved_at=started,
        )
        evidence = ExtractedEvidence(
            evidence_id="evidence-1", claim="A verified claim", source_ids=("source-1",),
            support=(SupportReference(source_id="source-1", excerpt="A verified claim"),),
            disposition=self.disposition,
            # Issue #125 fixture adaptation: a READY artifact reaching the
            # canonical gate must now name its assessor and say why each
            # record was assessed as it was. The lineage guarantees these
            # tests exist to protect are unchanged.
            assessment_rationale="The cited excerpt states the claim verbatim.",
        )
        artifact = NormalizedResearchArtifact(
            artifact_id="artifact-1", run_id=request.run_id,
            assignment_id=request.assignment_id, signal_id=request.signal_id,
            configuration_identity=request.strategy.identity, created_at=completed,
            assessor=EvidenceAssessorIdentity(assessor_id="test-assessor", version="1.0"),
            sources=(source,), evidence=(evidence,),
            interpretations=(ModelInterpretation(
                interpretation_id="interpretation-1",
                statement="The verified claim is relevant to the assignment.",
                evidence_ids=("evidence-1",),
            ),),
            uncertainties=(UncertaintyAssessment(
                uncertainty_id="uncertainty-1", level=UncertaintyLevel.LOW,
                materiality=UncertaintyMateriality.NON_MATERIAL,
                resolution=ResolutionStatus.UNRESOLVED,
                description="A non-material detail remains uncertain.",
                evidence_ids=("evidence-1",),
            ),),
            contradictions=(Contradiction(
                contradiction_id="contradiction-1",
                resolution=ResolutionStatus.RESOLVED,
                description="The apparent wording difference was resolved.",
                evidence_ids=("evidence-1",), source_ids=("source-1",),
            ),),
            readiness=self.readiness,
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
    assert artifact.sources[0].publication_time.status is PublicationTimeStatus.KNOWN
    assert artifact.sources[0].publication_time.value is not None
    assert artifact.sources[0].retrieved_at >= run.started_at
    assert artifact.interpretations[0].evidence_ids == (artifact.evidence[0].evidence_id,)
    assert artifact.uncertainties[0].level is UncertaintyLevel.LOW
    assert artifact.contradictions[0].resolution is ResolutionStatus.RESOLVED
    assert artifact.configuration_identity == strategy.identity


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
            judgment_transport=RejectingJudgment(),
            clock=lambda: request.requested_at + timedelta(seconds=2),
        )
    persisted = load_research_envelope(root, assignment.assignment_id, run.run_id)
    # Issue #125: assessment may lower a provider's readiness — rejecting the
    # only evidence makes NEEDS_REVIEW honestly INSUFFICIENT. The guarantee
    # this test protects is that the persisted artifact stays non-ready and
    # the gate blocks, not that the provider's label survives assessment.
    assert persisted.result.artifact.readiness is not EvidenceReadiness.READY


def test_partial_retrieval_with_unusable_evidence_is_persisted_then_blocked(lifecycle):
    """Intentional contract change (Issue #125).

    This previously asserted that a PARTIAL result is blocked *because* it is
    partial. It is now blocked on the merits of its evidence: the surviving
    records are rejected, so readiness is INSUFFICIENT and the gate declines
    it. The retrieval outcome is no longer the reason.
    """

    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    with pytest.raises(ResearchGateError, match="not ready"):
        execute_and_persist_research(
            ReadyProvider(readiness=EvidenceReadiness.NEEDS_REVIEW,
                          disposition=EvidenceDisposition.NOT_ASSESSED, partial=True),
            request, run_dir, identity=strategy.identity, run_started_at=run.started_at,
            clock=lambda: request.requested_at + timedelta(seconds=2),
            judgment_transport=RejectingJudgment(),
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

    valid = ResearchResultEnvelope(
        request=lifecycle[-1], result=ReadyProvider().research(lifecycle[-1])
    )
    path.write_text(json.dumps(valid.model_dump(mode="json"), indent=2))
    with pytest.raises(ResearchGateError, match="not canonical"):
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
        artifact = kwargs["research_artifact"]
        assert isinstance(artifact, NormalizedResearchArtifact)
        assert artifact.evidence[0].claim == "A verified claim"
        assert artifact.interpretations[0].statement != artifact.evidence[0].claim
        assert artifact.uncertainties and artifact.contradictions
        return legacy._FAKE_ARTICLE

    generated.side_effect = assert_research_precedes_editorial
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider()) == 0


def test_canonical_main_blocks_nonready_before_all_downstream_effects(tmp_path):
    argv, patches = legacy._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    del patches["execute_and_persist_research"]
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(
            research_provider=ReadyProvider(
                readiness=EvidenceReadiness.NEEDS_REVIEW,
                disposition=EvidenceDisposition.NOT_ASSESSED,
            ),
            evidence_judgment=RejectingJudgment(),
        ) == 1
    patches["generate_article"].assert_not_called()
    assert list(tmp_path.glob("*/runs/*/research.json"))
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


@pytest.mark.parametrize(
    ("unsafe_url", "secrets"),
    [
        ("https://alice:hunter2@example.com/report", ("alice", "hunter2")),
        ("https://alice@example.com/report", ("alice",)),
        ("https://alice:@example.com/report", ("alice",)),
        ("https://a%6cice@example.com/report", ("a%6cice", "alice")),
        ("https://alice:hunt%65r2@example.com/report", ("alice", "hunt%65r2", "hunter2")),
        ("HTTPS://a%253Alice:h%2540x@example.com/report", ("a%253Alice", "h%2540x")),
        ("https://alice%40example.com/report", ("alice%40example.com",)),
    ],
)
def test_canonical_entrypoint_rejects_client_userinfo_before_provider_or_side_effects(
    tmp_path, capsys, unsafe_url, secrets
):
    argv, patches = legacy._base_patches(dry_run=True)
    signal = dict(legacy._RAW_SIGNAL, SOURCE_URL=unsafe_url)
    patches["_load_signal"] = mock.MagicMock(return_value=signal)
    patches["PACKAGES_DIR"] = tmp_path
    provider = mock.MagicMock()
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(
            research_provider=provider, evidence_judgment=RejectingJudgment()
        ) == 1
    provider.research.assert_not_called()
    patches["generate_article"].assert_not_called()
    patches["_load_package_images"].assert_not_called()
    assert not list(tmp_path.glob("*/runs/*/research.json"))
    assert not list(tmp_path.glob("*/runs/*/.tmp_*.json"))
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    output = capsys.readouterr().out
    assert unsafe_url not in output
    for secret in secrets:
        assert secret not in output


def test_provider_userinfo_is_persisted_only_as_sanitized_failed_envelope(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    unsafe = "https://alice:hunter2@gartner.com/report"
    transport = provider_tests.RecordingTransport()
    transport.content_results[request.source_directives[0].value] = (
        provider_tests._document(unsafe),
    )
    adapter = provider_tests.ExaResearchAdapter(
        transport,
        clock=lambda: request.requested_at,
        uuid_factory=lambda: "11111111-1111-4111-8111-111111111111",
    )
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    with pytest.raises(ResearchGateError, match="failed"):
        execute_and_persist_research(
            adapter, request, run_dir, identity=strategy.identity,
            run_started_at=run.started_at,
            clock=lambda: request.requested_at + timedelta(seconds=2),
        )
    raw = (run_dir / "research.json").read_text()
    assert "unsafe source locator" in raw
    for forbidden in (unsafe, "alice", "hunter2"):
        assert forbidden not in raw


def test_canonical_main_holds_honest_exa_retrieval_before_editorial(tmp_path):
    argv, patches = legacy._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    del patches["execute_and_persist_research"]
    transport = provider_tests.RecordingTransport()
    provider = provider_tests.ExaResearchAdapter(
        transport,
        clock=lambda: datetime.now(timezone.utc),
        uuid_factory=lambda: "11111111-1111-4111-8111-111111111111",
    )

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=provider) == 1

    patches["generate_article"].assert_not_called()
    patches["_load_package_images"].assert_not_called()
    research_path = next(tmp_path.glob("*/runs/*/research.json"))
    envelope = ResearchResultEnvelope.model_validate_json(research_path.read_bytes())
    assert envelope.result.outcome is ResearchOperationOutcome.COMPLETE
    assert envelope.result.artifact.readiness is EvidenceReadiness.NEEDS_REVIEW
    assert all(
        item.disposition is EvidenceDisposition.NOT_ASSESSED
        for item in envelope.result.artifact.evidence
    )
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


@pytest.mark.parametrize("scenario", [
    FakeResearchScenario.EMPTY,
    FakeResearchScenario.TIMEOUT,
    FakeResearchScenario.AUTHENTICATION,
    FakeResearchScenario.RATE_LIMITED,
    FakeResearchScenario.MALFORMED,
    FakeResearchScenario.UNAVAILABLE,
])
def test_canonical_main_persists_typed_provider_failure_before_side_effects(
    tmp_path, scenario
):
    argv, patches = legacy._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    del patches["execute_and_persist_research"]
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=DeterministicFakeResearchProvider(scenario)) == 1

    patches["generate_article"].assert_not_called()
    patches["_load_package_images"].assert_not_called()
    envelope = ResearchResultEnvelope.model_validate_json(
        next(tmp_path.glob("*/runs/*/research.json")).read_bytes()
    )
    assert envelope.result.outcome is ResearchOperationOutcome.FAILED
    assert envelope.result.artifact is None
    assert envelope.result.operation_failure is not None
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_two_generation_runs_keep_distinct_immutable_research_artifacts(tmp_path):
    paths = []
    for _ in range(2):
        argv, patches = legacy._base_patches(dry_run=True)
        patches["PACKAGES_DIR"] = tmp_path
        del patches["execute_and_persist_research"]
        with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
            assert main(research_provider=ReadyProvider()) == 0
        paths = sorted(tmp_path.glob("*/runs/*/research.json"))
    assert len(paths) == 2
    envelopes = [ResearchResultEnvelope.model_validate_json(path.read_bytes()) for path in paths]
    assert envelopes[0].request.run_id != envelopes[1].request.run_id
    assert paths[0].read_bytes() == envelopes[0].canonical_json().encode()
    assert paths[1].read_bytes() == envelopes[1].canonical_json().encode()


def test_from_package_reuses_original_ready_lineage_without_provider_or_rewrite(tmp_path):
    generation_argv, generation_patches = legacy._base_patches(dry_run=True)
    generation_patches["PACKAGES_DIR"] = tmp_path
    del generation_patches["execute_and_persist_research"]
    del generation_patches["_save_generated"]
    with mock.patch.object(sys, "argv", generation_argv), mock.patch.multiple(
        gap, **generation_patches
    ):
        assert main(research_provider=ReadyProvider()) == 0

    research_path = next(tmp_path.glob("*/runs/*/research.json"))
    source_run_id = research_path.parent.name
    source_bytes = research_path.read_bytes()
    package_path = research_path.with_name("generated.json")
    package_bytes = package_path.read_bytes()

    reuse_argv, reuse_patches = legacy._base_patches(dry_run=True, from_package=True)
    reuse_argv[-1] = source_run_id
    reuse_patches["PACKAGES_DIR"] = tmp_path
    del reuse_patches["load_research_envelope"]
    del reuse_patches["validate_research_envelope"]
    provider = mock.MagicMock()
    with mock.patch.object(sys, "argv", reuse_argv), mock.patch.multiple(
        gap, **reuse_patches
    ):
        assert main(research_provider=provider) == 0

    provider.research.assert_not_called()
    assert research_path.read_bytes() == source_bytes
    assert package_path.read_bytes() == package_bytes
    # Since Issue #96 the reuse path derives publication visuals from the
    # source run's immutable visual passport only — the legacy signal-scoped
    # image mapping is no longer consulted (origin is never inferred from
    # signal_id).
    reuse_patches["_load_package_images"].assert_not_called()


@pytest.mark.parametrize("damage", [
    "missing", "corrupt", "noncanonical", "nonready", "cross_run",
    "assignment", "signal", "configuration",
])
def test_from_package_rejects_invalid_research_lineage_before_side_effects(tmp_path, damage):
    generation_argv, generation_patches = legacy._base_patches(dry_run=True)
    generation_patches["PACKAGES_DIR"] = tmp_path
    del generation_patches["execute_and_persist_research"]
    del generation_patches["_save_generated"]
    with mock.patch.object(sys, "argv", generation_argv), mock.patch.multiple(
        gap, **generation_patches
    ):
        assert main(research_provider=ReadyProvider()) == 0

    research_path = next(tmp_path.glob("*/runs/*/research.json"))
    source_run_id = research_path.parent.name
    if damage == "missing":
        research_path.unlink()
    elif damage == "corrupt":
        research_path.write_text('{"truncated":')
    else:
        envelope = ResearchResultEnvelope.model_validate_json(research_path.read_bytes())
        payload = envelope.model_dump(mode="json")
        if damage == "nonready":
            payload["result"]["artifact"]["readiness"] = "needs_review"
            payload["result"]["artifact"]["evidence"][0]["disposition"] = "not_assessed"
        elif damage == "cross_run":
            replacement = "11111111-1111-4111-8111-111111111111"
            payload["request"]["run_id"] = replacement
            payload["result"]["request_run_id"] = replacement
            payload["result"]["artifact"]["run_id"] = replacement
        elif damage == "assignment":
            payload["request"]["assignment_id"] = "other-assignment"
            payload["result"]["request_assignment_id"] = "other-assignment"
            payload["result"]["artifact"]["assignment_id"] = "other-assignment"
        elif damage == "signal":
            payload["request"]["signal_id"] = "other-signal"
            payload["result"]["request_signal_id"] = "other-signal"
            payload["result"]["artifact"]["signal_id"] = "other-signal"
        elif damage == "configuration":
            for identity in (
                payload["request"]["strategy"]["identity"],
                payload["result"]["artifact"]["configuration_identity"],
            ):
                identity["configuration_hash"] = "sha256:" + "0" * 64
        if damage == "noncanonical":
            research_path.write_text(json.dumps(payload, indent=2))
        else:
            repaired = ResearchResultEnvelope.model_validate(payload)
            research_path.write_text(repaired.canonical_json())

    reuse_argv, reuse_patches = legacy._base_patches(dry_run=True, from_package=True)
    reuse_argv[-1] = source_run_id
    reuse_patches["PACKAGES_DIR"] = tmp_path
    del reuse_patches["load_research_envelope"]
    del reuse_patches["validate_research_envelope"]
    with mock.patch.object(sys, "argv", reuse_argv), mock.patch.multiple(
        gap, **reuse_patches
    ):
        assert main(research_provider=mock.MagicMock()) == 1

    reuse_patches["_load_package_images"].assert_not_called()
    reuse_patches["generate_article"].assert_not_called()


class AcceptingJudgment(RejectingJudgment):
    """A verdict that would promote — used to prove it cannot."""

    def __init__(self):
        super().__init__(disposition="accepted")


def test_partial_retrieval_with_sufficient_evidence_passes_with_failures_visible(lifecycle):
    """The shape that once lost its evidence entirely, now passing honestly.

    Assessing a partial retrieval's surviving evidence produced READY, which
    built an invalid partial-plus-READY object; `model_copy` does not
    revalidate, so it was rejected a line later as a raw ValidationError,
    before `write_research_json` ran, and the retrieval was lost.

    Both halves are fixed: the combination is now legitimate (Issue #125), and
    nothing invalid is constructed on the way. What must stay visible is the
    retrieval truth — a reviewer sees PARTIAL, the failed source outcome, and
    READY evidence side by side.
    """

    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    judgment = AcceptingJudgment()

    artifact = execute_and_persist_research(
        ReadyProvider(readiness=EvidenceReadiness.NEEDS_REVIEW,
                      disposition=EvidenceDisposition.NOT_ASSESSED, partial=True),
        request, run_dir, identity=strategy.identity, run_started_at=run.started_at,
        clock=lambda: request.requested_at + timedelta(seconds=2),
        judgment_transport=judgment,
    )

    assert (run_dir / "research.json").exists()
    assert artifact.readiness is EvidenceReadiness.READY
    assert artifact.evidence[0].disposition is EvidenceDisposition.ACCEPTED
    assert artifact.evidence[0].assessment_rationale
    assert judgment.calls == 1

    # retrieval truth is untouched and remains inspectable beside the verdict
    persisted = load_research_envelope(root, assignment.assignment_id, run.run_id)
    assert persisted.result.outcome is ResearchOperationOutcome.PARTIAL
    assert persisted.result.operation_failure is not None
    assert any(o.status.value == "failed" for o in persisted.result.source_outcomes)
    assert persisted.result.artifact.readiness is EvidenceReadiness.READY


# ── Issue #125: the two dimensions, proven independent ───────────────────────
#
# Cases A–H from the authorized contract correction. Each asserts the retrieval
# outcome and the evidence readiness separately, because the whole point is
# that neither one determines the other.


def _run_case(lifecycle, *, partial, verdict):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    provider = ReadyProvider(readiness=EvidenceReadiness.NEEDS_REVIEW,
                             disposition=EvidenceDisposition.NOT_ASSESSED, partial=partial)
    judgment = RejectingJudgment(disposition=verdict)
    try:
        artifact = execute_and_persist_research(
            provider, request, run_dir, identity=strategy.identity,
            run_started_at=run.started_at,
            clock=lambda: request.requested_at + timedelta(seconds=2),
            judgment_transport=judgment,
        )
        blocked = None
    except ResearchGateError as exc:
        artifact, blocked = None, exc
    persisted = load_research_envelope(root, assignment.assignment_id, run.run_id)
    return persisted, artifact, blocked


def test_case_a_partial_retrieval_with_sufficient_evidence_passes(lifecycle):
    persisted, artifact, blocked = _run_case(lifecycle, partial=True, verdict="accepted")
    assert blocked is None
    assert persisted.result.outcome is ResearchOperationOutcome.PARTIAL
    assert artifact.readiness is EvidenceReadiness.READY


def test_case_b_partial_retrieval_with_insufficient_evidence_blocks(lifecycle):
    persisted, _, blocked = _run_case(lifecycle, partial=True, verdict="rejected")
    assert isinstance(blocked, ResearchGateError)
    assert persisted.result.outcome is ResearchOperationOutcome.PARTIAL
    assert persisted.result.artifact.readiness is not EvidenceReadiness.READY


def test_case_c_complete_retrieval_with_insufficient_evidence_blocks(lifecycle):
    persisted, _, blocked = _run_case(lifecycle, partial=False, verdict="rejected")
    assert isinstance(blocked, ResearchGateError)
    assert persisted.result.outcome is ResearchOperationOutcome.COMPLETE
    assert persisted.result.artifact.readiness is not EvidenceReadiness.READY


def test_case_d_complete_retrieval_with_sufficient_evidence_passes(lifecycle):
    persisted, artifact, blocked = _run_case(lifecycle, partial=False, verdict="accepted")
    assert blocked is None
    assert persisted.result.outcome is ResearchOperationOutcome.COMPLETE
    assert artifact.readiness is EvidenceReadiness.READY


def test_case_e_a_single_qualified_source_can_pass_with_its_limitation_kept(lifecycle):
    root, strategy, _, assignment, run, request = lifecycle
    run_dir = root / assignment.assignment_id / "runs" / run.run_id
    judgment = RejectingJudgment(disposition="qualified")
    artifact = execute_and_persist_research(
        ReadyProvider(readiness=EvidenceReadiness.NEEDS_REVIEW,
                      disposition=EvidenceDisposition.NOT_ASSESSED),
        request, run_dir, identity=strategy.identity, run_started_at=run.started_at,
        clock=lambda: request.requested_at + timedelta(seconds=2),
        judgment_transport=judgment,
    )
    assert len(artifact.sources) == 1
    assert artifact.evidence[0].disposition is EvidenceDisposition.QUALIFIED
    assert artifact.evidence[0].assessment_rationale
    assert artifact.readiness is EvidenceReadiness.READY


def test_case_g_retrieval_failures_stay_visible_when_partial_passes(lifecycle):
    persisted, artifact, blocked = _run_case(lifecycle, partial=True, verdict="accepted")
    assert blocked is None and artifact.readiness is EvidenceReadiness.READY
    # both dimensions readable side by side, from the persisted artifact alone
    assert persisted.result.outcome is ResearchOperationOutcome.PARTIAL
    assert persisted.result.operation_failure is not None
    assert any(o.status is RetrievalStatus.FAILED for o in persisted.result.source_outcomes)


def test_case_h_serialization_and_strict_reload_keep_both_dimensions(lifecycle):
    persisted, _, _ = _run_case(lifecycle, partial=True, verdict="accepted")
    raw = persisted.canonical_json()
    back = ResearchResultEnvelope.model_validate_json(raw)
    assert back.result.outcome is ResearchOperationOutcome.PARTIAL
    assert back.result.artifact.readiness is EvidenceReadiness.READY
    assert back.result.operation_failure is not None
    assert back.canonical_json() == raw
