"""Independent deterministic provider used for offline contract tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from enum import Enum

from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
)
from src.research.provider import (
    CompleteResearchResult,
    FailedResearchResult,
    PartialResearchResult,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    ResearchAdapterResult,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    RetrievalStatus,
    SourceOrigin,
    SourcePriority,
    SourceRetrievalOutcome,
)


class FakeResearchScenario(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    SOURCE_FAILURE = "source_failure"


class DeterministicFakeResearchProvider:
    """Deterministic implementation of the real provider-neutral protocol."""

    def __init__(self, scenario: FakeResearchScenario = FakeResearchScenario.COMPLETE) -> None:
        self.scenario = scenario
        self.requests: list[ResearchProviderRequest] = []

    def research(self, request: ResearchProviderRequest) -> ResearchAdapterResult:
        self.requests.append(request)
        started = request.requested_at
        completed = started + timedelta(seconds=1)
        invocation = ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id="deterministic-fake",
                adapter_id="never-blank-fake",
                adapter_version="1.0",
                invocation_id="22222222-2222-4222-8222-222222222222",
            ),
            started_at=started,
            completed_at=completed,
            attempt_count=1,
        )
        base = dict(
            request_run_id=request.run_id,
            request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id,
            invocation=invocation,
        )
        fatal_codes = {
            FakeResearchScenario.EMPTY: ProviderFailureCode.EMPTY_RESULT,
            FakeResearchScenario.MALFORMED: ProviderFailureCode.MALFORMED_RESPONSE,
            FakeResearchScenario.TIMEOUT: ProviderFailureCode.TIMEOUT,
            FakeResearchScenario.AUTHENTICATION: ProviderFailureCode.AUTHENTICATION,
            FakeResearchScenario.RATE_LIMITED: ProviderFailureCode.RATE_LIMITED,
            FakeResearchScenario.UNAVAILABLE: ProviderFailureCode.UNAVAILABLE,
            FakeResearchScenario.SOURCE_FAILURE: ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
        }
        if self.scenario in fatal_codes and self.scenario is not FakeResearchScenario.SOURCE_FAILURE:
            failure = _failure(fatal_codes[self.scenario])
            return FailedResearchResult(
                outcome=ResearchOperationOutcome.FAILED,
                source_outcomes=(),
                operation_failure=failure,
                **base,
            )

        directive = next(
            item
            for item in request.source_directives
            if item.priority is not SourcePriority.EXCLUDED
        )
        url = directive.value if "://" in directive.value else "https://example.test/research"
        source_id = f"source-{_digest(url)}"
        retrieved = SourceRetrievalOutcome(
            retrieval_id=f"retrieval-{_digest(url)}",
            directive_id=directive.directive_id,
            source_id=source_id,
            origin=(
                SourceOrigin.CLIENT_SUPPLIED
                if directive.priority in {SourcePriority.REQUIRED, SourcePriority.PREFERRED}
                else SourceOrigin.PROVIDER_DISCOVERED
            ),
            locator=url,
            status=RetrievalStatus.RETRIEVED,
            attempted_at=started,
            retrieved_at=started,
        )
        artifact = _artifact(request, source_id, url, started, completed)
        if self.scenario in {FakeResearchScenario.PARTIAL, FakeResearchScenario.SOURCE_FAILURE}:
            failure = _failure(ProviderFailureCode.SOURCE_RETRIEVAL_FAILED)
            failed = SourceRetrievalOutcome(
                retrieval_id="retrieval-failed-source",
                directive_id=None,
                source_id=None,
                origin=SourceOrigin.CLIENT_SUPPLIED,
                locator="https://failed.example.test/source",
                status=RetrievalStatus.FAILED,
                attempted_at=started,
                failure=failure,
            )
            return PartialResearchResult(
                outcome=ResearchOperationOutcome.PARTIAL,
                source_outcomes=(retrieved, failed),
                artifact=artifact,
                operation_failure=failure,
                **base,
            )
        return CompleteResearchResult(
            outcome=ResearchOperationOutcome.COMPLETE,
            source_outcomes=(retrieved,),
            artifact=artifact,
            operation_failure=None,
            **base,
        )


def _failure(code: ProviderFailureCode) -> ProviderFailure:
    retryable = code in {
        ProviderFailureCode.TIMEOUT,
        ProviderFailureCode.RATE_LIMITED,
        ProviderFailureCode.UNAVAILABLE,
        ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
    }
    return ProviderFailure(
        code=code,
        message=f"Deterministic provider outcome: {code.value}",
        retryable=retryable,
        retry_after_seconds=(30 if code is ProviderFailureCode.RATE_LIMITED else None),
    )


def _artifact(
    request: ResearchProviderRequest,
    source_id: str,
    url: str,
    retrieved_at: datetime,
    created_at: datetime,
) -> NormalizedResearchArtifact:
    evidence_id = f"evidence-{_digest(url)}"
    excerpt = "Deterministic source evidence for adapter contract tests."
    return NormalizedResearchArtifact(
        artifact_id=f"research-{request.run_id}",
        run_id=request.run_id,
        assignment_id=request.assignment_id,
        signal_id=request.signal_id,
        configuration_identity=request.strategy.identity,
        created_at=created_at,
        sources=(
            NormalizedSource(
                source_id=source_id,
                locator=SourceLocator(kind=SourceLocatorKind.URL, value=url),
                title="Deterministic research source",
                publisher="Never Blank test provider",
                publication_time=PublicationTime(
                    status=PublicationTimeStatus.NOT_COLLECTED
                ),
                retrieved_at=retrieved_at,
            ),
        ),
        evidence=(
            ExtractedEvidence(
                evidence_id=evidence_id,
                claim=excerpt,
                source_ids=(source_id,),
                support=(SupportReference(source_id=source_id, excerpt=excerpt),),
                disposition=EvidenceDisposition.NOT_ASSESSED,
            ),
        ),
        readiness=EvidenceReadiness.INSUFFICIENT,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
