"""
Never Blank — Intake layer.

Exports the provider-neutral ContentAssignment contract and its JSONL adapter.
"""

from src.intake.content_assignment import (
    ContentAssignment,
    CorrelationMetadata,
    from_jsonl_signal,
)

__all__ = ["ContentAssignment", "CorrelationMetadata", "from_jsonl_signal"]
