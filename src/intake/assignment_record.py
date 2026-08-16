"""Run-scoped canonical intake assignment record (Issue #98 / Story #16).

``assignment.json`` is the immutable record of what Never Blank was asked to
process in one particular run — the anchor of the run's provenance chain.

The authoritative assignment fields remain the existing canonical
``ContentAssignment`` (strict, frozen, ``extra="forbid"``). This module adds
only a minimal typed envelope binding that unchanged contract to the run and
configuration identity: the assignment is created *before* the ``RunContext``
exists, so it cannot carry run identity itself. No second intake schema, no
unrestricted mappings, no raw provider objects, credentials, prompts, or
arbitrary metadata are introduced.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.intake.content_assignment import ContentAssignment
from src.strategy.execution_context import ConfigurationIdentity


ASSIGNMENT_RECORD_SCHEMA_VERSION = "1.0"


class AssignmentRecord(BaseModel):
    """Minimal typed envelope: the canonical assignment bound to its run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ASSIGNMENT_RECORD_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    execution_mode: str = Field(min_length=1, max_length=40)
    configuration_identity: ConfigurationIdentity
    assignment: ContentAssignment

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != ASSIGNMENT_RECORD_SCHEMA_VERSION:
            raise ValueError(f"unsupported assignment schema_version: {value!r}")
        return value
