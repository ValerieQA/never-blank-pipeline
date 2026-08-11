"""
Never Blank — ContentAssignment intake contract.

ContentAssignment is the provider-neutral typed record that represents a
single content production request at the pipeline boundary.  It is created
once per run — by a JSONL adapter today, by future transport adapters
(API, UI, etc.) later — and consumed downstream without any transport
knowledge leaking into the core pipeline.

Field reference
---------------
assignment_id       Required str.  Stable unique identifier for this
                    assignment.  Normalised from SIGNAL_ID when built from
                    JSONL.  Must be non-empty and non-whitespace.
origin              Required str.  Where the assignment came from: "jsonl",
                    "api", "ui", etc.  Must be non-empty and non-whitespace.
topic               Optional str or None.  The editorial topic or question
                    being addressed.  At least one of topic / source_material
                    must be a non-whitespace string.
source_material     Optional str or None.  Primary source text, URL, or
                    reference material the article will draw on.  Separate
                    field from topic — do not collapse.
submitted_at        Required timezone-aware datetime.  Naive datetimes are
                    rejected.
user_instruction    Optional str or None.  Free-text instruction from the
                    requestor.
target_audience     Optional str or None.  Segment label, e.g.
                    "agencies, consultants".
publishing_constraints
                    dict[str, JsonValue].  Channel-level flags, e.g.
                    {"linkedin": {"dry_run": true}}.  All keys must be
                    strings.  All values must be JSON-compatible (no
                    datetimes, sets, or custom objects).
references          list[dict[str, JsonValue]].  Attached reference records.
                    Each element must be a dict with string keys and
                    JSON-compatible values.
strategy_ref        Required str.  Identifier of the active Business
                    Strategy Configuration, e.g. "never-blank-v1".
strategy_version    Required str.  Version string, e.g. "1.0.0".
correlation         Optional CorrelationMetadata.  Narrow Release-1 contract.
                    See CorrelationMetadata for field definitions.

Correlation metadata contract
------------------------------
Two explicit optional non-empty string identifiers cover all Release-1
traceability needs:

  external_request_id   The ID assigned by the caller (API gateway, queue
                         message, webhook).  Enables cross-system lookups
                         without embedding transport-specific objects.
  conversation_id       Stable session token for multi-turn interactions
                         (e.g. a Slack thread or a chat session).

Design choice: an unrestricted dict was rejected because it would allow
arbitrary transport payloads (Telegram Update objects, WhatsApp message
wrappers, raw HTTP headers) to leak into the core contract.  Two explicit
optional strings are sufficient for Release 1 and keep the boundary clean.

Empty-string and whitespace-only values are rejected — a blank ID is not a
valid correlation handle.

Serialization
-------------
- model_dump() / .to_dict() → JSON-compatible dict.  submitted_at
  serialised as ISO-8601 with explicit UTC offset (e.g.
  "2026-08-11T10:00:00+00:00").
- from_dict() → ContentAssignment.  Validates on construction; raises
  ValueError with an actionable English message on any invalid field.
  Unknown top-level keys are rejected.
- Round-trip: from_dict(ca.to_dict()) is equal to the original instance.
- No secrets appear in serialised output.

JSONL adapter
-------------
from_jsonl_signal(signal, *, strategy_ref, strategy_version, origin="jsonl")
maps the existing JSONL signal dict (keyed by uppercase SIGNAL_ID,
HEADLINE, CORE_FACT, etc.) to ContentAssignment.  The signal's CORE_FACT
becomes source_material; HEADLINE becomes topic.  Research logic is not
touched.  The input dict is never mutated.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as _PydanticValidationError


# ---------------------------------------------------------------------------
# JSON-compatibility helper
# ---------------------------------------------------------------------------

def _assert_json_compatible(value: Any, path: str) -> None:
    """
    Recursively verify that *value* can be serialized by json.dumps().

    Raises ValueError with an actionable message that includes the field
    path and the offending type on the first non-serializable node found.
    """
    try:
        _json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{path} contains a non-JSON-serializable value: {exc}. "
            f"Only str, int, float, bool, None, list, and dict are allowed."
        ) from exc


# ---------------------------------------------------------------------------
# CorrelationMetadata
# ---------------------------------------------------------------------------

class CorrelationMetadata(BaseModel):
    """
    Narrow correlation contract for Release 1.

    Both fields are optional, but when supplied they must be non-empty,
    non-whitespace strings.  Unknown fields are rejected.

    Attributes
    ----------
    external_request_id
        Identifier assigned by the external caller (API gateway, queue,
        webhook).  Enables cross-system lookups without transport objects.
    conversation_id
        Session token for multi-turn interactions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_request_id: Optional[str] = None
    conversation_id: Optional[str] = None

    @field_validator("external_request_id", "conversation_id", mode="before")
    @classmethod
    def _reject_blank(cls, v: Any, info: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError(
                f"correlation.{info.field_name} must be a string or None; "
                f"got {type(v).__name__}"
            )
        if not v.strip():
            raise ValueError(
                f"correlation.{info.field_name} must not be empty or "
                f"whitespace-only when provided"
            )
        return v

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# ContentAssignment
# ---------------------------------------------------------------------------

_KNOWN_FIELDS = frozenset({
    "assignment_id",
    "origin",
    "topic",
    "source_material",
    "submitted_at",
    "user_instruction",
    "target_audience",
    "publishing_constraints",
    "references",
    "strategy_ref",
    "strategy_version",
    "correlation",
})


class ContentAssignment(BaseModel):
    """
    Provider-neutral typed intake record for one content production run.

    Construct via ContentAssignment(**kwargs) or from_dict().
    Adapt from JSONL signals via from_jsonl_signal().
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- Required identifiers -----------------------------------------------
    assignment_id: str = Field(..., min_length=1)
    origin: str = Field(..., min_length=1)

    # --- Content fields (at least one required) ------------------------------
    topic: Optional[str] = None
    source_material: Optional[str] = None

    # --- Submission timestamp ------------------------------------------------
    submitted_at: datetime

    # --- Optional context ----------------------------------------------------
    user_instruction: Optional[str] = None
    target_audience: Optional[str] = None

    # --- Constraints and references -----------------------------------------
    publishing_constraints: Dict[str, Any] = Field(default_factory=dict)
    references: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Strategy provenance -------------------------------------------------
    strategy_ref: str = Field(..., min_length=1)
    strategy_version: str = Field(..., min_length=1)

    # --- Correlation ---------------------------------------------------------
    correlation: Optional[CorrelationMetadata] = None

    # ------------------------------------------------------------------
    # Field-level validators
    # ------------------------------------------------------------------

    @field_validator("assignment_id", "origin", "strategy_ref", "strategy_version", mode="after")
    @classmethod
    def _no_whitespace_only(cls, v: str, info: Any) -> str:
        if not v.strip():
            raise ValueError(
                f"{info.field_name} must not be empty or whitespace-only"
            )
        return v

    @field_validator("topic", "source_material", mode="before")
    @classmethod
    def _topic_source_must_be_str_or_none(cls, v: Any, info: Any) -> Any:
        if v is not None and not isinstance(v, str):
            raise ValueError(
                f"{info.field_name} must be a string or None; "
                f"got {type(v).__name__}"
            )
        return v

    @field_validator("user_instruction", "target_audience", mode="before")
    @classmethod
    def _optional_str_type(cls, v: Any, info: Any) -> Any:
        if v is not None and not isinstance(v, str):
            raise ValueError(
                f"{info.field_name} must be a string or None; "
                f"got {type(v).__name__}"
            )
        return v

    @field_validator("submitted_at", mode="after")
    @classmethod
    def _must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "submitted_at must be timezone-aware. "
                "Got a naive datetime. "
                "Wrap with e.g. datetime(..., tzinfo=timezone.utc)"
            )
        return v

    @field_validator("publishing_constraints", mode="after")
    @classmethod
    def _constraints_json_compatible(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        _assert_json_compatible(v, "publishing_constraints")
        return v

    @field_validator("references", mode="after")
    @classmethod
    def _references_json_compatible(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        _assert_json_compatible(v, "references")
        return v

    @field_validator("correlation", mode="before")
    @classmethod
    def _correlation_must_be_model(cls, v: Any) -> Any:
        if v is not None and not isinstance(v, CorrelationMetadata):
            raise ValueError(
                "correlation must be a CorrelationMetadata instance or None; "
                f"got {type(v).__name__}. "
                "Use CorrelationMetadata(...) to construct it — raw dicts and "
                "transport payload objects are not accepted."
            )
        return v

    # ------------------------------------------------------------------
    # Cross-field validator
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _at_least_one_content_field(self) -> "ContentAssignment":
        topic_ok = isinstance(self.topic, str) and self.topic.strip()
        source_ok = isinstance(self.source_material, str) and self.source_material.strip()
        if not topic_ok and not source_ok:
            raise ValueError(
                "At least one of 'topic' or 'source_material' must be present "
                "and non-empty. Both are missing or whitespace-only."
            )
        return self

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible dict. submitted_at uses ISO-8601 with UTC offset."""
        raw = self.model_dump()
        raw["submitted_at"] = self.submitted_at.isoformat()
        if self.correlation is not None:
            raw["correlation"] = self.correlation.to_dict()
        return raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContentAssignment":
        """
        Deserialize from a dict (e.g. parsed JSON).

        Raises ValueError with an actionable English message on any
        missing, invalid, or unknown field.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"ContentAssignment.from_dict expects a dict; "
                f"got {type(data).__name__}"
            )

        unknown = set(data.keys()) - _KNOWN_FIELDS
        if unknown:
            raise ValueError(
                f"ContentAssignment.from_dict received unknown field(s): "
                f"{sorted(unknown)}. "
                f"Allowed fields: {sorted(_KNOWN_FIELDS)}"
            )

        data = dict(data)

        # submitted_at: parse ISO-8601 string → datetime
        raw_ts = data.get("submitted_at")
        if isinstance(raw_ts, str):
            try:
                data["submitted_at"] = datetime.fromisoformat(raw_ts)
            except ValueError as exc:
                raise ValueError(
                    f"submitted_at is not a valid ISO-8601 datetime: {raw_ts!r}. "
                    f"Example: '2026-08-11T10:00:00+00:00'"
                ) from exc
        elif not isinstance(raw_ts, datetime):
            raise ValueError(
                "submitted_at must be an ISO-8601 datetime string with timezone; "
                f"got {type(raw_ts).__name__}"
            )

        # correlation: dict → CorrelationMetadata
        if "correlation" in data and isinstance(data["correlation"], dict):
            try:
                data["correlation"] = CorrelationMetadata(**data["correlation"])
            except _PydanticValidationError as exc:
                raise ValueError(
                    f"correlation is invalid: {exc}"
                ) from exc

        try:
            return cls(**data)
        except _PydanticValidationError as exc:
            # Surface the first Pydantic error as a plain ValueError so callers
            # get an actionable English message without importing Pydantic.
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(
                f"ContentAssignment field '{loc}': {first['msg']}"
            ) from exc


# ---------------------------------------------------------------------------
# JSONL adapter
# ---------------------------------------------------------------------------

def from_jsonl_signal(
    signal: Dict[str, Any],
    *,
    strategy_ref: str,
    strategy_version: str,
    origin: str = "jsonl",
    submitted_at: Optional[datetime] = None,
    user_instruction: Optional[str] = None,
    target_audience: Optional[str] = None,
    publishing_constraints: Optional[Dict[str, Any]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
    correlation: Optional[CorrelationMetadata] = None,
) -> ContentAssignment:
    """
    Adapt an existing JSONL signal dict into a ContentAssignment.

    Mapped fields
    -------------
    SIGNAL_ID       → assignment_id
    HEADLINE        → topic
    CORE_FACT       → source_material
    TARGET_AUDIENCE → target_audience (overridable by the kwarg of the same name)

    Unmapped fields
    ---------------
    All other JSONL keys (REGION, INDUSTRY, SOURCE_URL, scores, angles,
    etc.) are not represented in ContentAssignment.  They remain in the
    original signal dict and are consumed by downstream pipeline stages
    (ResearchContext, editorial pipeline) directly from that dict, which
    this adapter never modifies.

    submitted_at defaults to the current UTC time when not provided by
    the caller.
    """
    if not isinstance(signal, dict):
        raise ValueError(
            f"from_jsonl_signal expects a dict; got {type(signal).__name__}"
        )

    assignment_id = signal.get("SIGNAL_ID", "")
    if not isinstance(assignment_id, str) or not assignment_id.strip():
        raise ValueError(
            "JSONL signal is missing a non-empty SIGNAL_ID field. "
            "Every signal must have a unique SIGNAL_ID."
        )

    topic = signal.get("HEADLINE") or None
    source_material = signal.get("CORE_FACT") or None

    if submitted_at is None:
        submitted_at = datetime.now(tz=timezone.utc)

    if target_audience is None:
        target_audience = signal.get("TARGET_AUDIENCE") or None

    return ContentAssignment(
        assignment_id=assignment_id.strip(),
        origin=origin,
        topic=topic,
        source_material=source_material,
        submitted_at=submitted_at,
        user_instruction=user_instruction,
        target_audience=target_audience,
        publishing_constraints=publishing_constraints if publishing_constraints is not None else {},
        references=references if references is not None else [],
        strategy_ref=strategy_ref,
        strategy_version=strategy_version,
        correlation=correlation,
    )
