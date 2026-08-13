"""Transport-neutral intake adapter boundary for Release 1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from src.intake.content_assignment import ContentAssignment, from_jsonl_signal


class IntakeAdapterError(RuntimeError):
    """Controlled failure raised when an intake adapter cannot produce an assignment."""


@runtime_checkable
class IntakeAdapter(Protocol):
    """Convert one transport payload into the provider-neutral core contract."""

    def adapt(
        self,
        payload: Any,
        *,
        strategy_ref: str,
        strategy_version: str,
        submitted_at: datetime,
    ) -> ContentAssignment:
        """Return a validated assignment or raise a controlled exception."""


class JsonlIntakeAdapter:
    """Release 1 adapter for the approved project JSONL signal source."""

    def adapt(
        self,
        payload: Any,
        *,
        strategy_ref: str,
        strategy_version: str,
        submitted_at: datetime,
    ) -> ContentAssignment:
        try:
            return from_jsonl_signal(
                payload,
                strategy_ref=strategy_ref,
                strategy_version=strategy_version,
                submitted_at=submitted_at,
            )
        except (TypeError, ValueError) as exc:
            raise IntakeAdapterError(f"JSONL intake rejected the payload: {exc}") from exc


class UnsupportedTransportAdapter:
    """Non-production stub for transports owned by later stories.

    It intentionally cannot return an assignment. Telegram, WhatsApp, API,
    and portal integrations must replace this stub in their owning story.
    """

    def __init__(self, transport_name: str) -> None:
        self.transport_name = transport_name

    def adapt(
        self,
        payload: Any,
        *,
        strategy_ref: str,
        strategy_version: str,
        submitted_at: datetime,
    ) -> ContentAssignment:
        raise IntakeAdapterError(
            f"Intake transport {self.transport_name!r} is not implemented for Release 1"
        )
