"""Immutable, provider-neutral normalized research evidence contract.

This module is the sole canonical data model for Story #11 research artifacts.
It deliberately contains normalized facts only: no provider response objects,
raw payloads, credentials, SDK exceptions, persistence, or orchestration.

Canonical serialization is UTF-8 JSON with sorted keys, compact separators,
JSON-native enum values, and UTC timestamps.  It is deterministic for an equal
validated model and round-trips through :meth:`model_validate_json` without
loss.  Collection order is meaningful and is therefore preserved.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.strategy.execution_context import ConfigurationIdentity


RESEARCH_ARTIFACT_SCHEMA_VERSION = "1.0"


class ResearchContractError(ValueError):
    """Raised when normalized evidence violates cross-record invariants."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC, not a non-UTC offset")
    return value


_CREDENTIAL_SHAPE = re.compile(
    r"(?i)(?:authorization\s*:\s*bearer\s+|"
    r"(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password)"
    r"\s*[:=]\s*\S+|\bsk-[A-Za-z0-9_-]{12,})"
)


def _reject_credential_shape(value: str) -> str:
    if _CREDENTIAL_SHAPE.search(value):
        raise ValueError("credential-shaped content is forbidden in research artifacts")
    return value


class PublicationTimeStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_COLLECTED = "not_collected"


class SourceLocatorKind(str, Enum):
    URL = "url"
    IDENTIFIER = "identifier"


class UncertaintyLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class EvidenceDisposition(str, Enum):
    ACCEPTED = "accepted"
    QUALIFIED = "qualified"
    CONFLICTING = "conflicting"
    REJECTED = "rejected"
    NOT_ASSESSED = "not_assessed"


class EvidenceReadiness(str, Enum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    INSUFFICIENT = "insufficient"
    BLOCKED = "blocked"


class PublicationTime(_ContractModel):
    """Explicitly distinguish known, unknown, and not-collected publication time."""

    status: PublicationTimeStatus
    value: datetime | None = None

    @field_validator("value")
    @classmethod
    def _value_is_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc_timestamp(value, "publication_time.value")

    @model_validator(mode="after")
    def _status_matches_value(self) -> Self:
        if self.status is PublicationTimeStatus.KNOWN and self.value is None:
            raise ValueError("known publication time requires a value")
        if self.status is not PublicationTimeStatus.KNOWN and self.value is not None:
            raise ValueError("unknown/not_collected publication time must not have a value")
        return self


class SourceLocator(_ContractModel):
    kind: SourceLocatorKind
    value: str = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def _safe_value(cls, value: str) -> str:
        return _reject_credential_shape(value)

    @model_validator(mode="after")
    def _url_is_normalized_web_location(self) -> Self:
        if self.kind is SourceLocatorKind.URL:
            parsed = urlsplit(self.value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("URL source locator must be an absolute HTTP(S) URL")
        return self


class NormalizedSource(_ContractModel):
    source_id: str = Field(min_length=1)
    locator: SourceLocator
    title: str = Field(min_length=1)
    publisher: str | None = None
    publication_time: PublicationTime
    retrieved_at: datetime

    @field_validator("source_id", "title", "publisher")
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        return None if value is None else _reject_credential_shape(value)

    @field_validator("retrieved_at")
    @classmethod
    def _retrieved_at_utc(cls, value: datetime) -> datetime:
        return _utc_timestamp(value, "retrieved_at")


class SupportReference(_ContractModel):
    """Bounded source-derived support, never an unrestricted provider payload."""

    source_id: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=4000)
    location: str | None = Field(default=None, max_length=500)

    @field_validator("excerpt", "location")
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        return None if value is None else _reject_credential_shape(value)


class ExtractedEvidence(_ContractModel):
    """Source-derived factual evidence; never model interpretation."""

    evidence_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)
    support: tuple[SupportReference, ...] = Field(min_length=1)
    disposition: EvidenceDisposition

    @field_validator("claim")
    @classmethod
    def _safe_claim(cls, value: str) -> str:
        return _reject_credential_shape(value)

    @model_validator(mode="after")
    def _support_is_declared(self) -> Self:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("evidence source_ids must be unique")
        declared = set(self.source_ids)
        if any(item.source_id not in declared for item in self.support):
            raise ValueError("support must reference a source declared by the evidence")
        return self


class ModelInterpretation(_ContractModel):
    """Model-authored analysis, structurally separate from extracted evidence."""

    interpretation_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def _safe_statement(cls, value: str) -> str:
        return _reject_credential_shape(value)


class UncertaintyAssessment(_ContractModel):
    uncertainty_id: str = Field(min_length=1)
    level: UncertaintyLevel
    description: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

    @field_validator("description")
    @classmethod
    def _safe_description(cls, value: str) -> str:
        return _reject_credential_shape(value)

    @model_validator(mode="after")
    def _has_subject(self) -> Self:
        if not self.evidence_ids and not self.source_ids:
            raise ValueError("uncertainty must reference evidence or sources")
        return self


class Contradiction(_ContractModel):
    contradiction_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

    @field_validator("description")
    @classmethod
    def _safe_description(cls, value: str) -> str:
        return _reject_credential_shape(value)

    @model_validator(mode="after")
    def _compares_multiple_records(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("contradiction evidence_ids must be unique")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("contradiction source_ids must be unique")
        if len(self.evidence_ids) + len(self.source_ids) < 2:
            raise ValueError("contradiction must compare at least two evidence/source records")
        return self


class NormalizedResearchArtifact(_ContractModel):
    """Complete immutable normalized research artifact for one canonical run."""

    schema_version: str = RESEARCH_ARTIFACT_SCHEMA_VERSION
    artifact_id: str = Field(min_length=1)
    run_id: str
    assignment_id: str = Field(min_length=1)
    signal_id: str = Field(min_length=1)
    configuration_identity: ConfigurationIdentity
    created_at: datetime
    sources: tuple[NormalizedSource, ...] = Field(min_length=1)
    evidence: tuple[ExtractedEvidence, ...] = ()
    interpretations: tuple[ModelInterpretation, ...] = ()
    uncertainties: tuple[UncertaintyAssessment, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()
    readiness: EvidenceReadiness

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != RESEARCH_ARTIFACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported research artifact schema_version: {value!r}")
        return value

    @field_validator("run_id")
    @classmethod
    def _canonical_uuid4(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(value, version=4)
        except (ValueError, AttributeError):
            raise ValueError("run_id must be a canonical UUID v4")
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("run_id must be a canonical lowercase UUID v4")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        return _utc_timestamp(value, "created_at")

    @model_validator(mode="before")
    @classmethod
    def _reject_non_contract_objects(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("research artifact input must be a plain mapping")
        return value

    @model_validator(mode="after")
    def _referential_integrity(self) -> Self:
        source_ids = _unique_ids("source", (item.source_id for item in self.sources))
        evidence_ids = _unique_ids("evidence", (item.evidence_id for item in self.evidence))
        _unique_ids("interpretation", (item.interpretation_id for item in self.interpretations))
        _unique_ids("uncertainty", (item.uncertainty_id for item in self.uncertainties))
        _unique_ids("contradiction", (item.contradiction_id for item in self.contradictions))

        for item in self.evidence:
            _require_subset(f"evidence {item.evidence_id!r} sources", item.source_ids, source_ids)
            _require_subset(
                f"evidence {item.evidence_id!r} support sources",
                (support.source_id for support in item.support),
                source_ids,
            )
        for item in self.interpretations:
            _require_subset(
                f"interpretation {item.interpretation_id!r} evidence",
                item.evidence_ids,
                evidence_ids,
            )
        for item in self.uncertainties:
            _require_subset(f"uncertainty {item.uncertainty_id!r} evidence", item.evidence_ids, evidence_ids)
            _require_subset(f"uncertainty {item.uncertainty_id!r} sources", item.source_ids, source_ids)
        for item in self.contradictions:
            _require_subset(f"contradiction {item.contradiction_id!r} evidence", item.evidence_ids, evidence_ids)
            _require_subset(f"contradiction {item.contradiction_id!r} sources", item.source_ids, source_ids)
        return self

    def canonical_json(self) -> str:
        """Return documented deterministic, lossless canonical JSON."""

        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")


def _unique_ids(kind: str, values: Any) -> set[str]:
    collected = tuple(values)
    if len(set(collected)) != len(collected):
        raise ResearchContractError(f"duplicate {kind} IDs are forbidden")
    return set(collected)


def _require_subset(label: str, references: Any, known: set[str]) -> None:
    missing = set(references) - known
    if missing:
        raise ResearchContractError(f"{label} reference missing IDs: {sorted(missing)!r}")
