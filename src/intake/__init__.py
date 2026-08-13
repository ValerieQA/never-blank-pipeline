"""
Never Blank — Intake layer.

Exports the provider-neutral ContentAssignment contract and its JSONL adapter.
"""

from src.intake.content_assignment import (
    ContentAssignment,
    CorrelationMetadata,
    from_jsonl_signal,
)
from src.intake.adapter import (
    IntakeAdapter,
    IntakeAdapterError,
    JsonlIntakeAdapter,
    UnsupportedTransportAdapter,
)

__all__ = [
    "ContentAssignment",
    "CorrelationMetadata",
    "IntakeAdapter",
    "IntakeAdapterError",
    "JsonlIntakeAdapter",
    "UnsupportedTransportAdapter",
    "from_jsonl_signal",
]
