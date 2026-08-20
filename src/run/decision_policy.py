"""The strict canonical decision-policy authority record (Issue #152).

``decision_policy.json`` is one of exactly two decision authorities a run may
carry — the other being the canonical Decision Lens artifact. An authority
that is a loose dictionary is no authority at all: it could carry extra
fields, a foreign identity, or a policy the configuration never declared, and
nothing would notice. This contract holds the policy record to the same basic
integrity standard as every other canonical artifact: strict, versioned,
frozen, canonically serializable, and strict-reloadable.

The record proves five things and nothing else: which run it belongs to, which
role produced it under which configuration, which policy authorized
continuation, and that the research the policy acted on was READY. It never
carries secrets, prompts, or provider payloads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.strategy.execution_context import ConfigurationIdentity


DECISION_POLICY_SCHEMA_VERSION = "1.0"

#: Schema versions this contract can read. The record is create-once evidence;
#: any future shape change is a new version, never a rewrite.
KNOWN_DECISION_POLICY_SCHEMA_VERSIONS = frozenset({"1.0"})


class DecisionPolicyError(RuntimeError):
    """The policy record is not a trustworthy decision authority."""


class DecisionPolicyRecord(BaseModel):
    """Strict typed authority for a run that proceeded on a role's policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = DECISION_POLICY_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    assignment_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    role_id: str = Field(min_length=1, max_length=120)
    configuration_version: str = Field(min_length=1, max_length=80)
    configuration_identity: ConfigurationIdentity
    #: The only policy this authority may attest. A record claiming any other
    #: value is invalid by construction — "decision_lens" runs carry a
    #: decision.json, never this record.
    decision_policy: Literal["role_bounded_r1"]
    #: Only READY research authorizes generation under the policy. Anything
    #: else recorded here is a contradiction, not a variant.
    research_readiness: Literal["ready"]
    #: The R2 reconciliation this policy is debt against.
    reconciliation: Literal["#151"] = "#151"

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value not in KNOWN_DECISION_POLICY_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported decision policy schema_version: {value!r}")
        return value

    def canonical_json(self) -> str:
        return self.model_dump_json()


def verify_decision_policy_record(
    record: DecisionPolicyRecord,
    *,
    run_id: str,
    assignment_id: str,
    signal_id: str,
    role_id: str,
    configuration_version: str,
    configuration_identity: ConfigurationIdentity,
    research_readiness: str,
) -> None:
    """Bind a reloaded record to the run that claims it, field by field.

    Raises ``DecisionPolicyError`` on the first mismatch. Every check is
    against independently known values — the run context, the resolved role,
    the configuration, the research artifact — never against the record's own
    claims about itself.
    """

    expected = {
        "run_id": run_id,
        "assignment_id": assignment_id,
        "signal_id": signal_id,
        "role_id": role_id,
        "configuration_version": configuration_version,
        "research_readiness": research_readiness,
    }
    for field, value in expected.items():
        actual = getattr(record, field)
        if actual != value:
            raise DecisionPolicyError(
                f"decision policy record {field} does not match the run "
                f"(record={actual!r}, expected={value!r})"
            )
    if record.configuration_identity != configuration_identity:
        raise DecisionPolicyError(
            "decision policy record configuration identity does not match "
            "the run's authoritative configuration"
        )
