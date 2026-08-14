"""Adversarial production-boundary tests for Issue #51."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.research import (
    CompleteResearchResult,
    FailedResearchResult,
    FreshnessRequirement,
    PartialResearchResult,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    ResearchResultEnvelope,
    RetrievalStatus,
    SourceDirective,
    SourceDirectiveKind,
    SourceOrigin,
    SourcePriority,
    SourceRetrievalOutcome,
    execute_research,
)
from src.research.adapters.exa import (
    ExaAuthenticationError,
    ExaDocument,
    ExaMalformedResponse,
    ExaRateLimited,
    ExaResearchAdapter,
    ExaTimeout,
    ExaTransport,
    ExaUnavailable,
)
from src.research.adapters.fake import (
    DeterministicFakeResearchProvider,
    FakeResearchScenario,
)
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
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext


UTC = timezone.utc
NOW = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
RUN_ID = "12345678-1234-4234-8234-123456789abc"
CONFIG_PATH = Path("strategy/current/business_strategy.json")


def _strategy():
    return StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration(CONFIG_PATH)
    ).research


def _directive(
    directive_id: str = "required-client-source",
    priority: SourcePriority = SourcePriority.REQUIRED,
    kind: SourceDirectiveKind = SourceDirectiveKind.URL,
    value: str = "https://client.example.test/source",
    material: bool = True,
) -> SourceDirective:
    return SourceDirective(
        directive_id=directive_id,
        priority=priority,
        kind=kind,
        value=value,
        material=material,
    )


def _request(
    *directives: SourceDirective,
    allow_open_discovery: bool = True,
) -> ResearchProviderRequest:
    return ResearchProviderRequest(
        run_id=RUN_ID,
        assignment_id="assignment-51",
        signal_id="signal-51",
        strategy=_strategy(),
        freshness=FreshnessRequirement(
            retrieved_not_before=NOW - timedelta(hours=24),
            allow_open_discovery=allow_open_discovery,
        ),
        source_directives=directives or (_directive(),),
        requested_at=NOW,
    )


def _document(url: str = "https://client.example.test/source") -> ExaDocument:
    return ExaDocument(
        url=url,
        title="Auditable source",
        text="A bounded factual statement retrieved from the source.",
        publisher="Example publisher",
        published_at=NOW - timedelta(days=1),
    )


class RecordingTransport(ExaTransport):
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.content_results: dict[str, tuple[ExaDocument, ...] | Exception] = {}
        self.search_results: list[tuple[ExaDocument, ...] | Exception] = []

    def contents(self, urls):
        self.calls.append(("contents", tuple(urls)))
        result = self.content_results.get(urls[0], (_document(urls[0]),))
        if isinstance(result, Exception):
            raise result
        return result

    def search(self, query, *, include_domains=(), exclude_domains=()):
        self.calls.append(
            ("search", query, tuple(include_domains), tuple(exclude_domains))
        )
        result = self.search_results.pop(0) if self.search_results else (
            _document("https://discovery.example.test/result"),
        )
        if isinstance(result, Exception):
            raise result
        return result


class IncrementingClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self):
        current = self.value
        self.value += timedelta(milliseconds=1)
        return current


def _adapter(transport: RecordingTransport) -> ExaResearchAdapter:
    return ExaResearchAdapter(
        transport,
        clock=IncrementingClock(),
        uuid_factory=lambda: uuid.UUID("11111111-1111-4111-8111-111111111111"),
    )


@pytest.mark.parametrize(
    "model_factory",
    [
        lambda: FreshnessRequirement(
            retrieved_not_before=NOW, allow_open_discovery=False
        ),
        _directive,
        lambda: ProviderAttribution(
            provider_id="exa",
            adapter_id="exa-rest",
            adapter_version="1.0",
            invocation_id="11111111-1111-4111-8111-111111111111",
        ),
        lambda: ProviderFailure(
            code=ProviderFailureCode.TIMEOUT,
            message="Provider timed out",
            retryable=True,
        ),
        lambda: ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id="exa",
                adapter_id="exa-rest",
                adapter_version="1.0",
                invocation_id="11111111-1111-4111-8111-111111111111",
            ),
            started_at=NOW,
            completed_at=NOW,
            attempt_count=1,
        ),
    ],
)
def test_contract_models_are_frozen_and_forbid_extra(model_factory):
    model = model_factory()
    assert model.model_config["frozen"] is True
    assert model.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), "raw_payload": {}})
    with pytest.raises(ValidationError):
        model.__setattr__(next(iter(type(model).model_fields)), "changed")


def test_every_public_provider_model_is_strict_and_immutable():
    request = _request()
    complete = execute_research(DeterministicFakeResearchProvider(), request)
    partial = execute_research(
        DeterministicFakeResearchProvider(FakeResearchScenario.PARTIAL), request
    )
    failed = execute_research(
        DeterministicFakeResearchProvider(FakeResearchScenario.TIMEOUT), request
    )
    models = (
        request,
        request.freshness,
        request.source_directives[0],
        complete.invocation.attribution,
        complete.invocation,
        partial.operation_failure,
        complete.source_outcomes[0],
        complete,
        partial,
        failed,
        ResearchResultEnvelope(request=request, result=complete),
    )
    for model in models:
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
        with pytest.raises(ValidationError):
            type(model).model_validate({**model.model_dump(), "metadata": {}})


@pytest.mark.parametrize(
    "timestamp",
    [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=-6)))],
)
def test_request_and_freshness_reject_naive_and_non_utc(timestamp):
    with pytest.raises(ValidationError):
        FreshnessRequirement(
            retrieved_not_before=timestamp, allow_open_discovery=False
        )
    payload = _request().model_dump()
    payload["requested_at"] = timestamp
    with pytest.raises(ValidationError):
        ResearchProviderRequest.model_validate(payload)


def test_invocation_rejects_completion_before_start():
    with pytest.raises(ValidationError, match="cannot precede"):
        ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id="exa",
                adapter_id="exa-rest",
                adapter_version="1.0",
                invocation_id="11111111-1111-4111-8111-111111111111",
            ),
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
            attempt_count=1,
        )


@pytest.mark.parametrize(
    "timestamp",
    [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=2)))],
)
def test_source_attempt_and_retrieval_timestamps_require_strict_utc(timestamp):
    with pytest.raises(ValidationError, match="UTC"):
        SourceRetrievalOutcome(
            retrieval_id="retrieval-time",
            source_id="source-time",
            origin=SourceOrigin.PROVIDER_DISCOVERED,
            locator="https://example.test/time",
            status=RetrievalStatus.RETRIEVED,
            attempted_at=timestamp,
            retrieved_at=timestamp,
        )


def test_required_url_is_attempted_and_normalized_non_ready():
    transport = RecordingTransport()
    result = _adapter(transport).research(_request())
    assert isinstance(result, CompleteResearchResult)
    assert transport.calls[0] == (
        "contents",
        ("https://client.example.test/source",),
    )
    assert result.artifact.readiness is EvidenceReadiness.NEEDS_REVIEW
    assert result.artifact.evidence[0].disposition is EvidenceDisposition.NOT_ASSESSED
    assert result.source_outcomes[0].origin is SourceOrigin.CLIENT_SUPPLIED
    assert result.artifact.sources[0].retrieved_at == result.source_outcomes[0].retrieved_at


def test_preferred_exact_url_uses_contents_capability():
    transport = RecordingTransport()
    result = _adapter(transport).research(
        _request(
            _directive(
                "preferred-url",
                SourcePriority.PREFERRED,
                SourceDirectiveKind.URL,
                "https://preferred.example.test/article",
            )
        )
    )
    assert isinstance(result, CompleteResearchResult)
    assert transport.calls == [
        ("contents", ("https://preferred.example.test/article",))
    ]


def test_failed_material_required_source_forces_partial_and_non_ready():
    transport = RecordingTransport()
    transport.content_results["https://client.example.test/source"] = ExaUnavailable()
    request = _request(
        _directive(),
        _directive(
            "discovery",
            SourcePriority.DISCOVERY,
            SourceDirectiveKind.QUERY,
            "independent confirmation",
        ),
    )
    result = _adapter(transport).research(request)
    assert isinstance(result, PartialResearchResult)
    assert result.artifact.readiness is not EvidenceReadiness.READY
    assert any(item.status is RetrievalStatus.FAILED for item in result.source_outcomes)


def test_preferred_domain_search_precedes_open_discovery_and_uses_strategy():
    transport = RecordingTransport()
    request = _request(
        _directive(
            "preferred",
            SourcePriority.PREFERRED,
            SourceDirectiveKind.DOMAIN,
            "preferred.example.test",
        ),
        _directive(
            "discovery",
            SourcePriority.DISCOVERY,
            SourceDirectiveKind.QUERY,
            "fresh market evidence",
        ),
    )
    _adapter(transport).research(request)
    searches = [call for call in transport.calls if call[0] == "search"]
    assert searches[0][2] == ("preferred.example.test",)
    assert searches[1][2] == ()
    assert request.strategy.positioning.statement in searches[0][1]
    assert request.strategy.content.territories[0] in searches[0][1]


def test_excluded_domains_are_passed_to_search_and_filtered_from_results():
    transport = RecordingTransport()
    transport.search_results = [
        (
            _document("https://blocked.example.test/result"),
            _document("https://allowed.example.test/result"),
        )
    ]
    request = _request(
        _directive(
            "excluded",
            SourcePriority.EXCLUDED,
            SourceDirectiveKind.DOMAIN,
            "blocked.example.test",
        ),
        _directive(
            "discovery",
            SourcePriority.DISCOVERY,
            SourceDirectiveKind.QUERY,
            "market evidence",
        ),
    )
    result = _adapter(transport).research(request)
    assert transport.calls[0][3] == ("blocked.example.test",)
    assert [item.locator.value for item in result.artifact.sources] == [
        "https://allowed.example.test/result"
    ]


def test_open_discovery_is_rejected_when_not_allowed():
    with pytest.raises(ValidationError, match="allow_open_discovery"):
        _request(
            _directive(
                "discovery",
                SourcePriority.DISCOVERY,
                SourceDirectiveKind.QUERY,
                "market evidence",
            ),
            allow_open_discovery=False,
        )


def test_multiple_sources_have_unique_ids_and_exact_references():
    transport = RecordingTransport()
    transport.search_results = [
        (
            _document("https://one.example.test/a"),
            _document("https://two.example.test/b"),
        )
    ]
    result = _adapter(transport).research(
        _request(
            _directive(
                "discovery",
                SourcePriority.DISCOVERY,
                SourceDirectiveKind.QUERY,
                "evidence",
            )
        )
    )
    source_ids = {item.source_id for item in result.artifact.sources}
    evidence_ids = {item.evidence_id for item in result.artifact.evidence}
    assert len(source_ids) == len(evidence_ids) == 2
    assert all(set(item.source_ids) <= source_ids for item in result.artifact.evidence)


@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        (FakeResearchScenario.EMPTY, ProviderFailureCode.EMPTY_RESULT),
        (FakeResearchScenario.TIMEOUT, ProviderFailureCode.TIMEOUT),
        (FakeResearchScenario.AUTHENTICATION, ProviderFailureCode.AUTHENTICATION),
        (FakeResearchScenario.RATE_LIMITED, ProviderFailureCode.RATE_LIMITED),
        (FakeResearchScenario.MALFORMED, ProviderFailureCode.MALFORMED_RESPONSE),
        (FakeResearchScenario.UNAVAILABLE, ProviderFailureCode.UNAVAILABLE),
    ],
)
def test_fake_normalizes_fatal_outcome_without_artifact(scenario, code):
    result = execute_research(DeterministicFakeResearchProvider(scenario), _request())
    assert isinstance(result, FailedResearchResult)
    assert result.artifact is None
    assert result.operation_failure.code is code


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ExaTimeout(), ProviderFailureCode.TIMEOUT),
        (ExaAuthenticationError(), ProviderFailureCode.AUTHENTICATION),
        (ExaRateLimited(45), ProviderFailureCode.RATE_LIMITED),
        (ExaMalformedResponse(), ProviderFailureCode.MALFORMED_RESPONSE),
        (ExaUnavailable(), ProviderFailureCode.SOURCE_RETRIEVAL_FAILED),
    ],
)
def test_exa_exceptions_are_normalized_and_do_not_cross_boundary(error, code):
    transport = RecordingTransport()
    transport.content_results["https://client.example.test/source"] = error
    result = _adapter(transport).research(_request())
    assert isinstance(result, FailedResearchResult)
    assert result.operation_failure.code is code
    serialized = ResearchResultEnvelope(request=_request(), result=result).canonical_json()
    assert "Exa" not in serialized
    assert type(error).__name__ not in serialized


def test_individual_source_failure_retains_successful_sources():
    result = execute_research(
        DeterministicFakeResearchProvider(FakeResearchScenario.SOURCE_FAILURE),
        _request(),
    )
    assert isinstance(result, PartialResearchResult)
    assert len(result.artifact.sources) == 1
    assert {item.status for item in result.source_outcomes} == {
        RetrievalStatus.RETRIEVED,
        RetrievalStatus.FAILED,
    }
    assert result.artifact.readiness is EvidenceReadiness.INSUFFICIENT


def test_raw_payload_sdk_objects_and_credentials_are_rejected():
    payload = _request().model_dump()
    payload["raw_payload"] = object()
    with pytest.raises(ValidationError):
        ResearchProviderRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        ProviderFailure(
            code=ProviderFailureCode.AUTHENTICATION,
            message="Authorization: Bearer secret-token",
            retryable=False,
        )
    with pytest.raises(ValidationError):
        SourceRetrievalOutcome(
            retrieval_id="retrieval",
            origin=SourceOrigin.CLIENT_SUPPLIED,
            locator="api_key=secret-value",
            status=RetrievalStatus.FAILED,
            attempted_at=NOW,
            failure=ProviderFailure(
                code=ProviderFailureCode.AUTHENTICATION,
                message="Authentication failed",
                retryable=False,
            ),
        )


def test_fake_and_exa_are_replaceable_without_executor_branching():
    request = _request()
    fake_result = execute_research(DeterministicFakeResearchProvider(), request)
    exa_result = execute_research(_adapter(RecordingTransport()), request)
    assert fake_result.outcome is ResearchOperationOutcome.COMPLETE
    assert exa_result.outcome is ResearchOperationOutcome.COMPLETE


def test_false_ready_mapping_is_rejected_by_canonical_issue50_model():
    source = NormalizedSource(
        source_id="source",
        locator=SourceLocator(
            kind=SourceLocatorKind.URL, value="https://example.test/source"
        ),
        title="Source",
        publication_time=PublicationTime(status=PublicationTimeStatus.UNKNOWN),
        retrieved_at=NOW,
    )
    evidence = ExtractedEvidence(
        evidence_id="evidence",
        claim="Unassessed claim",
        source_ids=("source",),
        support=(SupportReference(source_id="source", excerpt="Support"),),
        disposition=EvidenceDisposition.NOT_ASSESSED,
    )
    payload = execute_research(DeterministicFakeResearchProvider(), _request()).artifact.model_dump()
    payload.update(sources=(source,), evidence=(evidence,), readiness="ready")
    with pytest.raises(ValidationError, match="blocking evidence"):
        NormalizedResearchArtifact.model_validate(payload)


def test_envelope_serialization_is_deterministic_strict_and_lossless():
    result = execute_research(DeterministicFakeResearchProvider(), _request())
    envelope = ResearchResultEnvelope(request=_request(), result=result)
    first = envelope.canonical_json()
    restored = ResearchResultEnvelope.model_validate_json(first)
    assert restored == envelope
    assert restored.canonical_json() == first
    assert json.loads(first)["result"]["invocation"]["attribution"]["provider_id"] == "deterministic-fake"
    assert restored.result.source_outcomes[0].origin is SourceOrigin.CLIENT_SUPPLIED


def test_result_rejects_retrieval_outside_invocation_window():
    result = execute_research(DeterministicFakeResearchProvider(), _request())
    payload = result.model_dump()
    payload["source_outcomes"][0]["retrieved_at"] = NOW - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="precede"):
        CompleteResearchResult.model_validate(payload)


def test_required_directive_cannot_be_arbitrary_query():
    with pytest.raises(ValidationError, match="exact URL or feed"):
        _directive(kind=SourceDirectiveKind.QUERY, value="anything")


def test_partial_result_cannot_carry_ready_artifact():
    complete = execute_research(DeterministicFakeResearchProvider(), _request())
    artifact_payload = complete.artifact.model_dump()
    artifact_payload["evidence"][0]["disposition"] = "accepted"
    artifact_payload["readiness"] = "ready"
    ready = NormalizedResearchArtifact.model_validate(artifact_payload)
    failed = SourceRetrievalOutcome(
        retrieval_id="failed",
        directive_id="required-client-source",
        origin=SourceOrigin.CLIENT_SUPPLIED,
        locator="https://failed.example.test",
        status=RetrievalStatus.FAILED,
        attempted_at=NOW,
        failure=ProviderFailure(
            code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
            message="Source retrieval failed",
            retryable=True,
        ),
    )
    with pytest.raises(ValidationError, match="cannot contain a READY"):
        PartialResearchResult(
            outcome=ResearchOperationOutcome.PARTIAL,
            request_run_id=complete.request_run_id,
            request_assignment_id=complete.request_assignment_id,
            request_signal_id=complete.request_signal_id,
            invocation=complete.invocation,
            source_outcomes=(*complete.source_outcomes, failed),
            artifact=ready,
            operation_failure=failed.failure,
        )
