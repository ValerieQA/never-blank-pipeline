"""
Never Blank — RunContext and run ID factory (Task #25).

RunContext is the typed execution-identity record for one pipeline run.
It is created once at the start of a run from a validated ContentAssignment
and does not change between stages.

Design decisions
----------------
- run_id is a UUID v4 string generated exactly once by create_run_id().
  It does not embed signal IDs, timestamps, correlation IDs, or execution
  mode.  The YYYYMMDD_HHMMSS_<run_id> artifact-path pattern is a storage
  naming convention and is not part of run identity.
- execution_mode is a strict enum (ExecutionMode) — arbitrary strings are
  rejected at construction.
- started_at is always stored in UTC.  Any timezone-aware input is
  normalized; naive datetimes are rejected.
- schema_version is a fixed documented literal ("1.0") that identifies
  the shape of this contract.  It must be updated if the field set changes
  in a breaking way.
- RunContext contains no content fields from ContentAssignment (no topic,
  source_material, user_instruction, references, publishing_constraints).
  Only the three identity/provenance scalars are copied: assignment_id,
  strategy_ref, strategy_version.
- external_correlation_id comes from
  ContentAssignment.correlation.external_request_id.  conversation_id is
  not copied — it is a session concept, not a run-identity concept.

Canonical entry point
---------------------
Use RunContext.from_assignment(assignment, execution_mode) to create a
context.  from_assignment() always generates a fresh run_id; callers must
not supply run_id directly.

Field reference
---------------
run_id                  UUID v4 string.  Unique per invocation.
assignment_id           Copied from ContentAssignment.assignment_id.
external_correlation_id Optional str.  Copied from
                        ContentAssignment.correlation.external_request_id
                        when present.
started_at              UTC datetime.  Defaults to now(UTC) when not
                        supplied.
strategy_ref            Copied from ContentAssignment.strategy_ref.
strategy_version        Copied from ContentAssignment.strategy_version.
execution_mode          ExecutionMode enum value.
schema_version          Fixed "1.0" — identifies this contract version.
configuration_identity  Four-field validated business configuration identity;
                        required on the canonical R1 path.

Serialization
-------------
- to_dict() → JSON-compatible dict; started_at as ISO-8601 with UTC offset.
- from_dict() → RunContext; rejects unknown fields, rejects naive started_at,
  rejects invalid execution_mode strings.
- Round-trip: RunContext.from_dict(rc.to_dict()) reconstructs an equal instance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as _PydanticValidationError

from src.intake.content_assignment import ContentAssignment
from src.strategy.execution_context import ConfigurationIdentity

# Schema version for this contract shape.  Bump this string if fields are
# added or removed in a breaking way.
_SCHEMA_VERSION = "1.0"

_KNOWN_FIELDS = frozenset({
    "run_id",
    "assignment_id",
    "external_correlation_id",
    "started_at",
    "strategy_ref",
    "strategy_version",
    "execution_mode",
    "schema_version",
    "configuration_identity",
})


# ---------------------------------------------------------------------------
# ExecutionMode
# ---------------------------------------------------------------------------

class ExecutionMode(str, Enum):
    """Permitted execution modes for a pipeline run."""
    DRY_RUN         = "dry-run"
    CONTROLLED_LIVE = "controlled-live"


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def create_run_id() -> str:
    """
    Return a new UUID v4 string.

    The ID is opaque — it contains no signal ID, timestamp, correlation ID,
    or execution mode.  Call this function exactly once per run.
    """
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------

class RunContext(BaseModel):
    """
    Typed execution-identity record for one pipeline run.

    Create via RunContext.from_assignment().  Do not supply run_id directly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id:                  str
    assignment_id:           str = Field(..., min_length=1)
    external_correlation_id: Optional[str] = None
    started_at:              datetime
    strategy_ref:            str = Field(..., min_length=1)
    strategy_version:        str = Field(..., min_length=1)
    execution_mode:          ExecutionMode
    schema_version:          str
    configuration_identity:  Optional[ConfigurationIdentity] = None

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("run_id", mode="after")
    @classmethod
    def _run_id_is_uuid4(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("run_id must not be empty or whitespace-only")
        try:
            parsed = uuid.UUID(v, version=4)
        except ValueError:
            raise ValueError(
                f"run_id must be a valid UUID v4 string; got {v!r}"
            )
        if str(parsed) != v.lower():
            raise ValueError(
                f"run_id must be a canonical lowercase UUID v4 string; got {v!r}"
            )
        return v

    @field_validator(
        "assignment_id", "strategy_ref", "strategy_version", mode="after"
    )
    @classmethod
    def _no_whitespace_only(cls, v: str, info: Any) -> str:
        if not v.strip():
            raise ValueError(
                f"{info.field_name} must not be empty or whitespace-only"
            )
        return v

    @field_validator("external_correlation_id", mode="before")
    @classmethod
    def _correlation_id_str_or_none(cls, v: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError(
                "external_correlation_id must be a string or None; "
                f"got {type(v).__name__}"
            )
        if not v.strip():
            raise ValueError(
                "external_correlation_id must not be empty or whitespace-only"
            )
        return v

    @field_validator("started_at", mode="after")
    @classmethod
    def _normalize_to_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "started_at must be timezone-aware. "
                "Got a naive datetime. Use datetime(..., tzinfo=timezone.utc)."
            )
        return v.astimezone(timezone.utc)

    @field_validator("schema_version", mode="after")
    @classmethod
    def _schema_version_known(cls, v: str) -> str:
        if v != _SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {_SCHEMA_VERSION!r}; got {v!r}"
            )
        return v

    # ------------------------------------------------------------------
    # Canonical factory
    # ------------------------------------------------------------------

    @classmethod
    def from_assignment(
        cls,
        assignment: ContentAssignment,
        execution_mode: ExecutionMode,
        *,
        started_at: Optional[datetime] = None,
        configuration_identity: Optional[ConfigurationIdentity] = None,
    ) -> "RunContext":
        """
        Create a RunContext from a validated ContentAssignment.

        A fresh run_id is generated on every call.  The caller must not
        supply a run_id — run identity belongs to the system, not the caller.

        Parameters
        ----------
        assignment:     A validated ContentAssignment.
        execution_mode: ExecutionMode.DRY_RUN or ExecutionMode.CONTROLLED_LIVE.
        started_at:     Optional timezone-aware datetime.  Defaults to
                        datetime.now(UTC).  Normalized to UTC if another
                        timezone is supplied.  Naive datetimes are rejected.
        """
        if not isinstance(assignment, ContentAssignment):
            raise ValueError(
                "assignment must be a ContentAssignment instance; "
                f"got {type(assignment).__name__}"
            )

        if started_at is None:
            started_at = datetime.now(tz=timezone.utc)

        external_correlation_id: Optional[str] = None
        if assignment.correlation is not None:
            external_correlation_id = assignment.correlation.external_request_id

        return cls(
            run_id=create_run_id(),
            assignment_id=assignment.assignment_id,
            external_correlation_id=external_correlation_id,
            started_at=started_at,
            strategy_ref=assignment.strategy_ref,
            strategy_version=assignment.strategy_version,
            execution_mode=execution_mode,
            schema_version=_SCHEMA_VERSION,
            configuration_identity=configuration_identity,
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible dict. started_at uses ISO-8601 with UTC offset."""
        data = {
            "run_id":                  self.run_id,
            "assignment_id":           self.assignment_id,
            "external_correlation_id": self.external_correlation_id,
            "started_at":              self.started_at.isoformat(),
            "strategy_ref":            self.strategy_ref,
            "strategy_version":        self.strategy_version,
            "execution_mode":          self.execution_mode.value,
            "schema_version":          self.schema_version,
        }
        if self.configuration_identity is not None:
            data["configuration_identity"] = self.configuration_identity.model_dump()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunContext":
        """
        Deserialize from a dict (e.g. parsed JSON).

        Raises ValueError with an actionable English message on any
        missing, invalid, or unknown field.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"RunContext.from_dict expects a dict; got {type(data).__name__}"
            )

        unknown = set(data.keys()) - _KNOWN_FIELDS
        if unknown:
            raise ValueError(
                f"RunContext.from_dict received unknown field(s): "
                f"{sorted(unknown)}. "
                f"Allowed fields: {sorted(_KNOWN_FIELDS)}"
            )

        data = dict(data)

        raw_ts = data.get("started_at")
        if isinstance(raw_ts, str):
            try:
                data["started_at"] = datetime.fromisoformat(raw_ts)
            except ValueError as exc:
                raise ValueError(
                    f"started_at is not a valid ISO-8601 datetime: {raw_ts!r}. "
                    "Example: '2026-08-11T10:00:00+00:00'"
                ) from exc
        elif not isinstance(raw_ts, datetime):
            raise ValueError(
                "started_at must be an ISO-8601 datetime string with timezone; "
                f"got {type(raw_ts).__name__}"
            )

        try:
            return cls(**data)
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(
                f"RunContext field '{loc}': {first['msg']}"
            ) from exc
