"""
Never Blank — ContentAssignment intake contract.

ContentAssignment is the provider-neutral typed record that represents a
single content production request at the pipeline boundary.  It is created
once per run — by a JSONL adapter today, by future transport adapters
(API, UI, etc.) later — and consumed downstream without any transport
knowledge leaking into the core pipeline.

Field reference
---------------
assignment_id       Required. Stable, unique identifier for this assignment.
                    Normalised from signal_id when constructed from JSONL.
origin              Required. Where the assignment came from: "jsonl",
                    "api", "ui", etc.  Must be a non-empty string.
topic               Optional str.  The editorial topic or question being
                    addressed.  At least one of topic / source_material
                    must be present and non-whitespace.
source_material     Optional str.  Primary source text, URL, or reference
                    material the article will draw on.  Separate field from
                    topic — do not collapse.
submitted_at        Required.  Timezone-aware datetime (UTC preferred).
                    Naive datetimes are rejected.
user_instruction    Optional free-text instruction from the requestor.
target_audience     Optional segment label (e.g. "agencies, consultants").
publishing_constraints
                    Optional dict of channel-level flags, e.g.
                    {"linkedin": {"dry_run": true}}.  Must be a plain dict
                    with string keys and JSON-compatible values.
references          List of attached reference dicts, e.g.
                    [{"url": "https://…", "label": "primary source"}].
                    Each item must be a dict with string keys.
strategy_ref        Required.  Identifier of the active Business Strategy
                    Configuration, e.g. "never-blank-v1".
strategy_version    Required.  Semver-style version string, e.g. "1.0.0".
correlation         Optional CorrelationMetadata.  Narrow Release-1 contract
                    for correlating a run back to its origin.  See
                    CorrelationMetadata for field definitions.

Correlation metadata contract
------------------------------
Two explicit optional identifiers cover all Release-1 traceability needs:

  external_request_id   The ID assigned by the caller (API gateway, queue
                         message, webhook).  Enables cross-system lookups
                         without embedding transport-specific objects.
  conversation_id       Stable session token for multi-turn interactions
                         (e.g. a Slack thread or a chat session).  Optional
                         even in interactive flows.

Design choice: an unrestricted dict was rejected because it would allow
arbitrary transport payloads (Telegram Update objects, WhatsApp message
wrappers, raw HTTP headers) to leak into the core contract.  Explicit
optional strings are sufficient for Release 1 and keep the boundary clean.

Serialization
-------------
- to_dict() → JSON-compatible dict.  submitted_at serialised as ISO-8601
  with explicit UTC offset (e.g. "2026-08-11T10:00:00+00:00").
- from_dict() → ContentAssignment.  Validates on construction; raises
  ValueError with an actionable English message on any invalid field.
- Round-trip: from_dict(ca.to_dict()) is equal to the original instance.
- No secrets appear in serialised output — topic/source_material are
  user content, not credentials.

JSONL adapter
-------------
from_jsonl_signal(signal, *, strategy_ref, strategy_version, origin="jsonl")
maps the existing JSONL signal dict (keyed by uppercase SIGNAL_ID,
HEADLINE, CORE_FACT, etc.) to ContentAssignment.  The signal's CORE_FACT
becomes source_material; HEADLINE becomes topic.  Research logic is not
touched.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# CorrelationMetadata
# ---------------------------------------------------------------------------

class CorrelationMetadata:
    """
    Narrow correlation contract for Release 1.

    Attributes
    ----------
    external_request_id
        Identifier assigned by the external caller (API gateway, queue,
        webhook).  Enables cross-system lookups.  Optional.
    conversation_id
        Session token for multi-turn interactions.  Optional.
    """

    __slots__ = ("external_request_id", "conversation_id")

    def __init__(
        self,
        *,
        external_request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        if external_request_id is not None and not isinstance(external_request_id, str):
            raise ValueError(
                "correlation.external_request_id must be a string or None; "
                f"got {type(external_request_id).__name__}"
            )
        if conversation_id is not None and not isinstance(conversation_id, str):
            raise ValueError(
                "correlation.conversation_id must be a string or None; "
                f"got {type(conversation_id).__name__}"
            )
        self.external_request_id = external_request_id
        self.conversation_id = conversation_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "external_request_id": self.external_request_id,
            "conversation_id": self.conversation_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorrelationMetadata":
        if not isinstance(data, dict):
            raise ValueError(
                f"correlation must be a dict; got {type(data).__name__}"
            )
        allowed = {"external_request_id", "conversation_id"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise ValueError(
                f"correlation contains unknown fields: {sorted(unknown)}. "
                f"Allowed fields: {sorted(allowed)}"
            )
        return cls(
            external_request_id=data.get("external_request_id"),
            conversation_id=data.get("conversation_id"),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CorrelationMetadata):
            return NotImplemented
        return (
            self.external_request_id == other.external_request_id
            and self.conversation_id == other.conversation_id
        )

    def __repr__(self) -> str:
        return (
            f"CorrelationMetadata("
            f"external_request_id={self.external_request_id!r}, "
            f"conversation_id={self.conversation_id!r})"
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def _require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{field} must be a non-empty string; got {type(value).__name__}"
        )
    if not value.strip():
        raise ValueError(f"{field} must not be empty or whitespace-only")
    return value


def _require_tz_aware(dt: datetime, field: str) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(
            f"{field} must be timezone-aware; "
            f"got a naive datetime. "
            f"Wrap with e.g. datetime(..., tzinfo=timezone.utc)"
        )
    return dt


def _validate_dict_with_str_keys(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            f"{field} must be a dict; got {type(value).__name__}"
        )
    for k in value:
        if not isinstance(k, str):
            raise ValueError(
                f"{field} keys must be strings; found key of type {type(k).__name__}"
            )
    return value


def _validate_references(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(
            f"references must be a list; got {type(value).__name__}"
        )
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(
                f"references[{i}] must be a dict; got {type(item).__name__}"
            )
        for k in item:
            if not isinstance(k, str):
                raise ValueError(
                    f"references[{i}] keys must be strings; "
                    f"found key of type {type(k).__name__}"
                )
    return value


# ---------------------------------------------------------------------------
# ContentAssignment
# ---------------------------------------------------------------------------

class ContentAssignment:
    """
    Provider-neutral typed intake record for one content production run.

    Construct via ContentAssignment(...) or from_dict().
    Adapt from JSONL signals via from_jsonl_signal().
    """

    __slots__ = (
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
    )

    def __init__(
        self,
        *,
        assignment_id: str,
        origin: str,
        topic: Optional[str] = None,
        source_material: Optional[str] = None,
        submitted_at: datetime,
        user_instruction: Optional[str] = None,
        target_audience: Optional[str] = None,
        publishing_constraints: Optional[Dict[str, Any]] = None,
        references: Optional[List[Dict[str, Any]]] = None,
        strategy_ref: str,
        strategy_version: str,
        correlation: Optional[CorrelationMetadata] = None,
    ) -> None:
        self.assignment_id = _require_nonempty_str(assignment_id, "assignment_id")
        self.origin = _require_nonempty_str(origin, "origin")

        # topic / source_material: at least one required and non-whitespace
        topic_ok = isinstance(topic, str) and topic.strip()
        source_ok = isinstance(source_material, str) and source_material.strip()
        if not topic_ok and not source_ok:
            raise ValueError(
                "At least one of 'topic' or 'source_material' must be present "
                "and non-empty. Both are missing or whitespace-only."
            )
        self.topic = topic
        self.source_material = source_material

        if not isinstance(submitted_at, datetime):
            raise ValueError(
                f"submitted_at must be a datetime; got {type(submitted_at).__name__}"
            )
        self.submitted_at = _require_tz_aware(submitted_at, "submitted_at")

        self.user_instruction = user_instruction
        self.target_audience = target_audience

        self.publishing_constraints = _validate_dict_with_str_keys(
            publishing_constraints if publishing_constraints is not None else {},
            "publishing_constraints",
        )
        self.references = _validate_references(
            references if references is not None else []
        )

        self.strategy_ref = _require_nonempty_str(strategy_ref, "strategy_ref")

        if not isinstance(strategy_version, str) or not strategy_version.strip():
            raise ValueError(
                "strategy_version must be a non-empty string (e.g. '1.0.0')"
            )
        self.strategy_version = strategy_version

        if correlation is not None and not isinstance(correlation, CorrelationMetadata):
            raise ValueError(
                "correlation must be a CorrelationMetadata instance or None; "
                f"got {type(correlation).__name__}"
            )
        self.correlation = correlation

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible dict.  submitted_at uses ISO-8601 with UTC offset."""
        return {
            "assignment_id": self.assignment_id,
            "origin": self.origin,
            "topic": self.topic,
            "source_material": self.source_material,
            "submitted_at": self.submitted_at.isoformat(),
            "user_instruction": self.user_instruction,
            "target_audience": self.target_audience,
            "publishing_constraints": self.publishing_constraints,
            "references": self.references,
            "strategy_ref": self.strategy_ref,
            "strategy_version": self.strategy_version,
            "correlation": self.correlation.to_dict() if self.correlation else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContentAssignment":
        """
        Deserialize from a dict (e.g. parsed JSON).

        Raises ValueError with an actionable English message on any
        missing or invalid field.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"ContentAssignment.from_dict expects a dict; got {type(data).__name__}"
            )

        # submitted_at: parse ISO-8601 string
        raw_ts = data.get("submitted_at")
        if not isinstance(raw_ts, str):
            raise ValueError(
                "submitted_at must be an ISO-8601 datetime string with timezone; "
                f"got {type(raw_ts).__name__}"
            )
        try:
            submitted_at = datetime.fromisoformat(raw_ts)
        except ValueError as exc:
            raise ValueError(
                f"submitted_at is not a valid ISO-8601 datetime: {raw_ts!r}. "
                f"Example: '2026-08-11T10:00:00+00:00'"
            ) from exc

        correlation_raw = data.get("correlation")
        correlation: Optional[CorrelationMetadata] = None
        if correlation_raw is not None:
            correlation = CorrelationMetadata.from_dict(correlation_raw)

        return cls(
            assignment_id=data.get("assignment_id", ""),
            origin=data.get("origin", ""),
            topic=data.get("topic"),
            source_material=data.get("source_material"),
            submitted_at=submitted_at,
            user_instruction=data.get("user_instruction"),
            target_audience=data.get("target_audience"),
            publishing_constraints=data.get("publishing_constraints"),
            references=data.get("references"),
            strategy_ref=data.get("strategy_ref", ""),
            strategy_version=data.get("strategy_version", ""),
            correlation=correlation,
        )

    # ------------------------------------------------------------------
    # Equality / repr
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ContentAssignment):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        return (
            f"ContentAssignment("
            f"assignment_id={self.assignment_id!r}, "
            f"origin={self.origin!r}, "
            f"topic={self.topic!r}, "
            f"strategy_ref={self.strategy_ref!r})"
        )


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

    Mapping
    -------
    SIGNAL_ID     → assignment_id
    HEADLINE      → topic
    CORE_FACT     → source_material
    TARGET_AUDIENCE → target_audience (if not supplied as kwarg)

    All other JSONL fields pass through to the downstream pipeline
    unchanged — this adapter operates only at the intake boundary.

    submitted_at defaults to the current time in UTC when not provided.
    The caller should supply it from a real intake timestamp when available.
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
        publishing_constraints=publishing_constraints,
        references=references,
        strategy_ref=strategy_ref,
        strategy_version=strategy_version,
        correlation=correlation,
    )
