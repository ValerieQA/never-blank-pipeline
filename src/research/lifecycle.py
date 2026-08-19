"""Canonical orchestration boundary for run-scoped research evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from src.artifacts import load_research_json, write_research_json
from src.intake import ContentAssignment
from src.research.evidence import EvidenceReadiness, NormalizedResearchArtifact
from src.research.assessment import (
    EvidenceAssessmentError,
    EvidenceJudgmentTransport,
    LlmChatEvidenceJudgmentTransport,
    assess_artifact,
)
from src.research.provider import (
    CompleteResearchResult,
    FreshnessRequirement,
    ResearchOperationOutcome,
    ResearchProvider,
    ResearchProviderRequest,
    ResearchResultEnvelope,
    SourceDirective,
    SourceDirectiveKind,
    SourcePriority,
    FailedResearchResult,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    execute_research,
)
from src.run import RunContext
from src.strategy.execution_context import ConfigurationIdentity, ResearchStrategyView


MAX_CLOCK_SKEW = timedelta(minutes=5)


class ResearchGateError(RuntimeError):
    """Research cannot cross into strategic or editorial generation."""


class MissingCredentialResearchProvider:
    """Typed fail-closed provider selected only by the production composition root."""

    def research(self, request: ResearchProviderRequest) -> FailedResearchResult:
        timestamp = request.requested_at
        return FailedResearchResult(
            outcome=ResearchOperationOutcome.FAILED,
            request_run_id=request.run_id,
            request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id,
            invocation=ProviderInvocation(
                attribution=ProviderAttribution(
                    provider_id="exa", adapter_id="never-blank-exa-rest",
                    adapter_version="1.0",
                    invocation_id="00000000-0000-4000-8000-000000000052",
                ),
                started_at=timestamp, completed_at=timestamp, attempt_count=1,
            ),
            source_outcomes=(),
            operation_failure=ProviderFailure(
                code=ProviderFailureCode.AUTHENTICATION,
                message="Research provider credentials are unavailable",
                retryable=False,
            ),
        )


def build_source_directives(signal: dict) -> tuple[SourceDirective, ...]:
    """Translate legacy signal fields into deterministic typed source priority."""
    directives: list[SourceDirective] = []
    source_url = str(signal.get("SOURCE_URL") or "").strip()
    if source_url:
        directives.append(SourceDirective(
            directive_id="required-source-1", priority=SourcePriority.REQUIRED,
            kind=SourceDirectiveKind.URL, value=source_url, material=True,
        ))
    preferred = signal.get("PREFERRED_SOURCES") or ()
    if isinstance(preferred, str):
        preferred = [item.strip() for item in preferred.split(",") if item.strip()]
    for index, value in enumerate(preferred, 1):
        kind = SourceDirectiveKind.URL if "://" in str(value) else SourceDirectiveKind.DOMAIN
        directives.append(SourceDirective(
            directive_id=f"preferred-source-{index}", priority=SourcePriority.PREFERRED,
            kind=kind, value=str(value), material=False,
        ))
    if str(signal.get("ALLOW_OPEN_DISCOVERY", "")).strip().casefold() in {"1", "true", "yes"}:
        query = str(signal.get("HEADLINE") or signal.get("CORE_FACT") or "").strip()
        if query:
            directives.append(SourceDirective(
                directive_id="discovery-query-1", priority=SourcePriority.DISCOVERY,
                kind=SourceDirectiveKind.QUERY, value=query, material=False,
            ))
    excluded = signal.get("EXCLUDED_SOURCES") or ()
    if isinstance(excluded, str):
        excluded = [item.strip() for item in excluded.split(",") if item.strip()]
    for index, value in enumerate(excluded, 1):
        kind = SourceDirectiveKind.URL if "://" in str(value) else SourceDirectiveKind.DOMAIN
        directives.append(SourceDirective(
            directive_id=f"excluded-source-{index}", priority=SourcePriority.EXCLUDED,
            kind=kind, value=str(value), material=True,
        ))
    if not any(item.priority is not SourcePriority.EXCLUDED for item in directives):
        raise ResearchGateError("research requires at least one required, preferred, or discovery source")
    order = {SourcePriority.REQUIRED: 0, SourcePriority.PREFERRED: 1,
             SourcePriority.DISCOVERY: 2, SourcePriority.EXCLUDED: 3}
    return tuple(sorted(directives, key=lambda item: order[item.priority]))


def build_research_request(
    run: RunContext, assignment: ContentAssignment, signal: dict,
    strategy: ResearchStrategyView, *, now: datetime,
) -> ResearchProviderRequest:
    directives = build_source_directives(signal)
    return ResearchProviderRequest(
        run_id=run.run_id, assignment_id=assignment.assignment_id,
        signal_id=assignment.assignment_id, strategy=strategy,
        freshness=FreshnessRequirement(
            retrieved_not_before=run.started_at,
            allow_open_discovery=any(d.priority is SourcePriority.DISCOVERY for d in directives),
        ),
        source_directives=directives, requested_at=now,
    )


def validate_research_envelope(
    envelope: ResearchResultEnvelope, *, run_id: str, assignment_id: str,
    signal_id: str, identity: ConfigurationIdentity, run_started_at: datetime,
    now: datetime,
) -> NormalizedResearchArtifact:
    request, result = envelope.request, envelope.result
    if (request.run_id, request.assignment_id, request.signal_id) != (run_id, assignment_id, signal_id):
        raise ResearchGateError("research request identity does not match current run")
    if request.strategy.identity != identity:
        raise ResearchGateError("research configuration identity does not match current run")
    if request.requested_at < run_started_at or result.invocation.started_at < run_started_at:
        raise ResearchGateError("provider invocation predates current run")
    if result.invocation.completed_at > now + MAX_CLOCK_SKEW:
        raise ResearchGateError("provider timestamps exceed the permitted five-minute clock skew")
    if not isinstance(result, CompleteResearchResult) or result.outcome is not ResearchOperationOutcome.COMPLETE:
        raise ResearchGateError(f"research provider outcome is {result.outcome.value}, not complete")
    artifact = result.artifact
    if artifact.configuration_identity != identity:
        raise ResearchGateError("research artifact configuration identity mismatch")
    if artifact.readiness is not EvidenceReadiness.READY:
        raise ResearchGateError(f"research evidence is {artifact.readiness.value}, not ready")
    # READY asserts that evidence was assessed, and the canonical path holds
    # it to that. Without a named assessor and a stated reason per record the
    # assertion is unfalsifiable afterwards, and retrieval alone could wear
    # the appearance of assessment. The artifact contract itself is unchanged:
    # this is the production gate declining an unassessed READY, not a new
    # meaning for READY.
    if artifact.assessor is None:
        raise ResearchGateError("research evidence is ready but names no assessor")
    unexplained = tuple(
        item.evidence_id
        for item in artifact.evidence
        if not (item.assessment_rationale or "").strip()
    )
    if unexplained:
        raise ResearchGateError(
            f"research evidence is ready but unexplained: {unexplained!r}"
        )
    return artifact


def execute_and_persist_research(
    provider: ResearchProvider, request: ResearchProviderRequest, run_dir: Path,
    *, identity: ConfigurationIdentity, run_started_at: datetime,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    judgment_transport: "EvidenceJudgmentTransport | None" = None,
) -> NormalizedResearchArtifact:
    result = execute_research(provider, request)
    # Issue #125: assessment happens here — after retrieval, before the
    # create-once artifact is written — so research.json records the assessed
    # evidence the rest of the run actually reasons from, rather than being
    # amended afterwards. A result carrying no artifact (a failed operation)
    # has nothing to assess and is passed through untouched.
    if getattr(result, "artifact", None) is not None:
        try:
            assessed = assess_artifact(
                result.artifact,
                transport=judgment_transport or LlmChatEvidenceJudgmentTransport(),
                # The canonical outcome, not a provider-specific check: only a
                # COMPLETE operation retrieved everything it was asked for. A
                # partial result keeps its readiness, so no invalid
                # partial-plus-READY object is ever constructed and the
                # retrieved evidence is persisted normally.
                retrieval_complete=(
                    result.outcome is ResearchOperationOutcome.COMPLETE
                ),
            )
        except EvidenceAssessmentError:
            # Losing the retrieval because the assessment failed would destroy
            # real evidence and misreport a working provider. The unassessed
            # artifact is persisted exactly as retrieved — every record still
            # `not_assessed`, readiness untouched — so the run has a truthful
            # account, and then the failure propagates. Nothing is promoted.
            unassessed = ResearchResultEnvelope(request=request, result=result)
            write_research_json(run_dir, unassessed.canonical_json().encode("utf-8"))
            raise
        result = result.model_copy(update={"artifact": assessed})
    envelope = ResearchResultEnvelope(request=request, result=result)
    write_research_json(run_dir, envelope.canonical_json().encode("utf-8"))
    persisted = load_research_envelope(run_dir.parent.parent.parent, request.signal_id, request.run_id)
    return validate_research_envelope(
        persisted, run_id=request.run_id, assignment_id=request.assignment_id,
        signal_id=request.signal_id, identity=identity, run_started_at=run_started_at,
        now=clock(),
    )


def load_research_envelope(packages_dir: Path, signal_id: str, source_run_id: str) -> ResearchResultEnvelope:
    raw = load_research_json(packages_dir, signal_id, source_run_id)
    try:
        envelope = ResearchResultEnvelope.model_validate_json(raw)
    except Exception as exc:
        raise ResearchGateError("research.json is malformed or violates the strict contract") from exc
    if raw != envelope.canonical_json().encode("utf-8"):
        raise ResearchGateError("research.json is not canonical")
    return envelope
