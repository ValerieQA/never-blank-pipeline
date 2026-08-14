"""Strict provider-neutral boundary for research retrieval.

The contracts in this module describe provider execution, not evidence quality.
Only :class:`NormalizedResearchArtifact` describes evidence readiness.  Provider
credentials, transports, raw responses, and exception objects are deliberately
absent from every public model.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.research.evidence import EvidenceReadiness, NormalizedResearchArtifact
from src.strategy.execution_context import ResearchStrategyView
from src.research.url_safety import require_safe_url_authority


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")
    return value


_SENSITIVE = re.compile(
    r"(?i)(?:authorization|cookie|set-cookie|x-api-key|"
    r"api[_-]?key|access[_-]?token|secret|password|bearer\s+\S+|"
    r"\bsk-[A-Za-z0-9_-]{8,})"
)


def _audit_safe(value: str) -> str:
    if _SENSITIVE.search(value):
        raise ValueError("credential-shaped or transport-sensitive text is forbidden")
    return value


def _uuid4(value: str, field_name: str) -> str:
    try:
        parsed = uuid.UUID(value, version=4)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a canonical UUID v4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{field_name} must be a canonical lowercase UUID v4")
    return value


class SourcePriority(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    DISCOVERY = "discovery"
    EXCLUDED = "excluded"


class SourceDirectiveKind(str, Enum):
    URL = "url"
    DOMAIN = "domain"
    FEED = "feed"
    QUERY = "query"


class SourceOrigin(str, Enum):
    CLIENT_SUPPLIED = "client_supplied"
    PROVIDER_DISCOVERED = "provider_discovered"


class ResearchOperationOutcome(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class RetrievalStatus(str, Enum):
    RETRIEVED = "retrieved"
    FAILED = "failed"


class ProviderFailureCode(str, Enum):
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    MALFORMED_RESPONSE = "malformed_response"
    EMPTY_RESULT = "empty_result"
    UNAVAILABLE = "unavailable"
    SOURCE_RETRIEVAL_FAILED = "source_retrieval_failed"


class SourceDirective(_ProviderModel):
    directive_id: str = Field(min_length=1, max_length=120)
    priority: SourcePriority
    kind: SourceDirectiveKind
    value: str = Field(min_length=1, max_length=2000)
    material: bool = True

    @field_validator("directive_id", "value")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _audit_safe(value)

    @model_validator(mode="after")
    def _valid_policy_shape(self) -> "SourceDirective":
        if self.priority is SourcePriority.REQUIRED and self.kind not in {
            SourceDirectiveKind.URL,
            SourceDirectiveKind.FEED,
        }:
            raise ValueError("REQUIRED directives must identify an exact URL or feed")
        if self.priority is SourcePriority.EXCLUDED and self.kind not in {
            SourceDirectiveKind.URL,
            SourceDirectiveKind.DOMAIN,
        }:
            raise ValueError("EXCLUDED directives must identify a URL or domain")
        if self.priority is SourcePriority.DISCOVERY and self.kind is not SourceDirectiveKind.QUERY:
            raise ValueError("DISCOVERY directives must contain a search query")
        if self.kind in {
            SourceDirectiveKind.URL,
            SourceDirectiveKind.FEED,
            SourceDirectiveKind.DOMAIN,
        }:
            require_safe_url_authority(
                self.value, allow_domain=self.kind is SourceDirectiveKind.DOMAIN
            )
        return self


class FreshnessRequirement(_ProviderModel):
    retrieved_not_before: datetime
    allow_open_discovery: bool

    @field_validator("retrieved_not_before")
    @classmethod
    def _strict_utc(cls, value: datetime) -> datetime:
        return _utc(value, "retrieved_not_before")


class ResearchProviderRequest(_ProviderModel):
    run_id: str
    assignment_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    strategy: ResearchStrategyView
    freshness: FreshnessRequirement
    source_directives: tuple[SourceDirective, ...] = Field(min_length=1, max_length=20)
    requested_at: datetime

    @field_validator("run_id")
    @classmethod
    def _run_uuid(cls, value: str) -> str:
        return _uuid4(value, "run_id")

    @field_validator("assignment_id", "signal_id")
    @classmethod
    def _safe_identity(cls, value: str) -> str:
        return _audit_safe(value)

    @field_validator("requested_at")
    @classmethod
    def _request_utc(cls, value: datetime) -> datetime:
        return _utc(value, "requested_at")

    @model_validator(mode="after")
    def _consistent_request(self) -> "ResearchProviderRequest":
        ids = tuple(item.directive_id for item in self.source_directives)
        if len(set(ids)) != len(ids):
            raise ValueError("source directive IDs must be unique")
        if self.freshness.retrieved_not_before > self.requested_at:
            raise ValueError("freshness boundary cannot be after request time")
        if (
            any(item.priority is SourcePriority.DISCOVERY for item in self.source_directives)
            and not self.freshness.allow_open_discovery
        ):
            raise ValueError("DISCOVERY directive requires allow_open_discovery")
        return self


class ProviderAttribution(_ProviderModel):
    provider_id: str = Field(min_length=1, max_length=80)
    adapter_id: str = Field(min_length=1, max_length=120)
    adapter_version: str = Field(min_length=1, max_length=40)
    invocation_id: str

    @field_validator("provider_id", "adapter_id", "adapter_version")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _audit_safe(value)

    @field_validator("invocation_id")
    @classmethod
    def _invocation_uuid(cls, value: str) -> str:
        return _uuid4(value, "invocation_id")


class ProviderInvocation(_ProviderModel):
    attribution: ProviderAttribution
    started_at: datetime
    completed_at: datetime
    attempt_count: int = Field(ge=1, le=20)

    @field_validator("started_at", "completed_at")
    @classmethod
    def _strict_utc(cls, value: datetime) -> datetime:
        return _utc(value, "provider invocation timestamp")

    @model_validator(mode="after")
    def _ordered(self) -> "ProviderInvocation":
        if self.completed_at < self.started_at:
            raise ValueError("provider completion cannot precede invocation start")
        return self


class ProviderFailure(_ProviderModel):
    code: ProviderFailureCode
    message: str = Field(min_length=1, max_length=300)
    retryable: bool
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86400)

    @field_validator("message")
    @classmethod
    def _safe_message(cls, value: str) -> str:
        return _audit_safe(value)

    @model_validator(mode="after")
    def _retry_fields_agree(self) -> "ProviderFailure":
        if self.retry_after_seconds is not None and not self.retryable:
            raise ValueError("retry delay requires retryable=true")
        return self


class SourceRetrievalOutcome(_ProviderModel):
    retrieval_id: str = Field(min_length=1, max_length=120)
    directive_id: str | None = Field(default=None, max_length=120)
    source_id: str | None = Field(default=None, max_length=120)
    origin: SourceOrigin
    locator: str = Field(min_length=1, max_length=2000)
    status: RetrievalStatus
    attempted_at: datetime
    retrieved_at: datetime | None = None
    failure: ProviderFailure | None = None

    @field_validator("retrieval_id", "directive_id", "source_id", "locator")
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        return None if value is None else _audit_safe(value)

    @field_validator("attempted_at", "retrieved_at")
    @classmethod
    def _retrieved_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value, "source retrieval timestamp")

    @model_validator(mode="after")
    def _status_shape(self) -> "SourceRetrievalOutcome":
        require_safe_url_authority(self.locator)
        if self.status is RetrievalStatus.RETRIEVED:
            if self.source_id is None or self.retrieved_at is None or self.failure is not None:
                raise ValueError("retrieved source requires source_id/time and no failure")
        elif self.retrieved_at is not None or self.failure is None or self.source_id is not None:
            raise ValueError("failed retrieval requires only a sanitized failure")
        if self.retrieved_at is not None and self.retrieved_at < self.attempted_at:
            raise ValueError("retrieval cannot precede its source attempt")
        return self


class _ResultBase(_ProviderModel):
    request_run_id: str
    request_assignment_id: str = Field(min_length=1)
    request_signal_id: str = Field(min_length=1)
    invocation: ProviderInvocation
    source_outcomes: tuple[SourceRetrievalOutcome, ...]

    @field_validator("request_run_id")
    @classmethod
    def _run_uuid(cls, value: str) -> str:
        return _uuid4(value, "request_run_id")

    @model_validator(mode="after")
    def _unique_retrievals(self) -> "_ResultBase":
        ids = tuple(item.retrieval_id for item in self.source_outcomes)
        if len(ids) != len(set(ids)):
            raise ValueError("source retrieval IDs must be unique")
        for item in self.source_outcomes:
            if item.attempted_at < self.invocation.started_at:
                raise ValueError("source attempt cannot precede invocation start")
            if item.attempted_at > self.invocation.completed_at:
                raise ValueError("source attempt cannot follow invocation completion")
            if item.retrieved_at is not None:
                if item.retrieved_at < self.invocation.started_at:
                    raise ValueError("retrieval cannot precede invocation start")
                if item.retrieved_at > self.invocation.completed_at:
                    raise ValueError("retrieval cannot follow invocation completion")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")


class CompleteResearchResult(_ResultBase):
    outcome: Literal[ResearchOperationOutcome.COMPLETE]
    artifact: NormalizedResearchArtifact
    operation_failure: None = None

    @model_validator(mode="after")
    def _complete_is_consistent(self) -> "CompleteResearchResult":
        if any(item.status is RetrievalStatus.FAILED for item in self.source_outcomes):
            raise ValueError("complete result cannot contain failed retrievals")
        _validate_artifact_link(self)
        return self


class PartialResearchResult(_ResultBase):
    outcome: Literal[ResearchOperationOutcome.PARTIAL]
    artifact: NormalizedResearchArtifact
    operation_failure: ProviderFailure

    @model_validator(mode="after")
    def _partial_is_consistent(self) -> "PartialResearchResult":
        if self.artifact.readiness is EvidenceReadiness.READY:
            raise ValueError("partial provider result cannot contain a READY artifact")
        if not any(item.status is RetrievalStatus.FAILED for item in self.source_outcomes):
            raise ValueError("partial result requires a failed source outcome")
        _validate_artifact_link(self)
        return self


class FailedResearchResult(_ResultBase):
    outcome: Literal[ResearchOperationOutcome.FAILED]
    artifact: None = None
    operation_failure: ProviderFailure

    @model_validator(mode="after")
    def _failed_is_consistent(self) -> "FailedResearchResult":
        if any(item.status is RetrievalStatus.RETRIEVED for item in self.source_outcomes):
            raise ValueError("failed result cannot discard retrieved sources")
        return self


ResearchAdapterResult: TypeAlias = Annotated[
    CompleteResearchResult | PartialResearchResult | FailedResearchResult,
    Field(discriminator="outcome"),
]


class ResearchResultEnvelope(_ProviderModel):
    """Serialization boundary used by Issue #52 without persistence here."""

    request: ResearchProviderRequest
    result: ResearchAdapterResult

    @model_validator(mode="after")
    def _request_and_result_agree(self) -> "ResearchResultEnvelope":
        if self.result.request_run_id != self.request.run_id:
            raise ValueError("result run identity does not match request")
        if self.result.request_assignment_id != self.request.assignment_id:
            raise ValueError("result assignment identity does not match request")
        if self.result.request_signal_id != self.request.signal_id:
            raise ValueError("result signal identity does not match request")
        if self.result.invocation.started_at < self.request.requested_at:
            raise ValueError("provider invocation cannot precede request time")
        directive_ids = {item.directive_id for item in self.request.source_directives}
        for outcome in self.result.source_outcomes:
            if outcome.directive_id is not None and outcome.directive_id not in directive_ids:
                raise ValueError("source outcome references an unknown directive")
            if (
                outcome.retrieved_at is not None
                and outcome.retrieved_at < self.request.freshness.retrieved_not_before
            ):
                raise ValueError("retrieval does not satisfy the declared freshness boundary")
        artifact = self.result.artifact
        if (
            artifact is not None
            and artifact.configuration_identity != self.request.strategy.identity
        ):
            raise ValueError("artifact configuration identity does not match strategy view")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


def _validate_artifact_link(result: CompleteResearchResult | PartialResearchResult) -> None:
    artifact = result.artifact
    if artifact.run_id != result.request_run_id:
        raise ValueError("artifact run identity does not match request")
    if artifact.assignment_id != result.request_assignment_id:
        raise ValueError("artifact assignment identity does not match request")
    if artifact.signal_id != result.request_signal_id:
        raise ValueError("artifact signal identity does not match request")
    successful = {
        item.source_id: item.retrieved_at
        for item in result.source_outcomes
        if item.status is RetrievalStatus.RETRIEVED
    }
    artifact_sources = {item.source_id: item.retrieved_at for item in artifact.sources}
    if successful != artifact_sources:
        raise ValueError("artifact sources must exactly match successful retrieval outcomes")
    if not (
        result.invocation.started_at
        <= artifact.created_at
        <= result.invocation.completed_at
    ):
        raise ValueError("artifact creation must occur during provider invocation")


class ResearchProvider(Protocol):
    def research(self, request: ResearchProviderRequest) -> ResearchAdapterResult:
        """Retrieve and normalize research without leaking provider details."""


def execute_research(
    provider: ResearchProvider, request: ResearchProviderRequest
) -> ResearchAdapterResult:
    """Provider-neutral executor; contains no concrete-provider branching."""

    result = provider.research(request)
    ResearchResultEnvelope(request=request, result=result)
    return result
