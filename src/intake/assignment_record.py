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

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.intake.content_assignment import ContentAssignment
from src.run.code_identity import CodeIdentity
from src.strategy.execution_context import ConfigurationIdentity


ASSIGNMENT_RECORD_SCHEMA_VERSION = "1.1"

#: Schema versions this contract can still read. ``1.1`` added the optional
#: code identity (Issue #114). Earlier records are immutable create-once
#: evidence and are never rewritten, so both shapes must stay loadable — and
#: the version keeps recording which shape was actually written.
KNOWN_ASSIGNMENT_RECORD_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})


class AssignmentRecord(BaseModel):
    """Minimal typed envelope: the canonical assignment bound to its run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ASSIGNMENT_RECORD_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    execution_mode: str = Field(min_length=1, max_length=40)
    configuration_identity: ConfigurationIdentity
    assignment: ContentAssignment

    #: Which code executed this run (Issue #114 / Story #21). Absent when the
    #: run could not resolve it — outside a Git checkout, or written before
    #: this contract existed. Absence is the honest answer: a run that cannot
    #: prove its code identity is not Story #21 acceptance evidence, and a
    #: fabricated identity would corrupt exactly the claim it supports.
    code_identity: Optional[CodeIdentity] = None

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value not in KNOWN_ASSIGNMENT_RECORD_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported assignment schema_version: {value!r}")
        return value
