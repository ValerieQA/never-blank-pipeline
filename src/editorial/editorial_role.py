"""Which editorial role produced a run (Issue #142).

A pipeline that publishes several kinds of article each week has to be able to
say which kind a given run was — and to say it from evidence, not from the
weekday the job happened to fire on. A stream re-run a day late is still the
same editorial role, and a run's own record is the only place that can be true.

The identity here is deliberately generic: a role id and the configuration
version that declared it. It carries no editorial meaning of its own. What a
role *asks for* — its structure, its prohibitions — is declared in the business
strategy configuration, so a different business can define entirely different
roles, or none, without this module changing.

The role is a property of the **run**, not of the source material. The same
business case could legitimately be produced under different roles, so this
lives on the run-scoped assignment record rather than on the intake contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.strategy.business_config import (
    BusinessStrategyConfiguration,
    EditorialRole,
)


class EditorialRoleError(RuntimeError):
    """The requested editorial role is not declared by the configuration."""


class EditorialRoleIdentity(BaseModel):
    """Names the declared role a run executed under, and where it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_id: str = Field(min_length=1, max_length=120)
    configuration_version: str = Field(min_length=1, max_length=80)
    #: The decision policy the run executed under (Issue #152). Persisted so a
    #: reviewer can see from assignment.json alone which policy governed the
    #: run — an R1 role policy is an auditable product decision, never a
    #: silent bypass. Defaults to the pre-existing behaviour so records
    #: written before this field reload unchanged.
    decision_policy: str = Field(
        default="decision_lens", min_length=1, max_length=40
    )


def resolve_editorial_role(
    configuration: BusinessStrategyConfiguration, role_id: str
) -> tuple[EditorialRoleIdentity, EditorialRole]:
    """Resolve a requested role id against the declared roles.

    Fails closed on an unknown id. A run asked to produce a role the
    configuration does not declare has no rules to follow, and silently
    producing a default article under a role name it never honoured would make
    the recorded identity a lie.
    """

    requested = (role_id or "").strip()
    if not requested:
        raise EditorialRoleError("an editorial role id is required")
    for role in configuration.editorial_roles:
        if role.role_id == requested:
            return (
                EditorialRoleIdentity(
                    role_id=role.role_id,
                    configuration_version=configuration.configuration_version,
                    decision_policy=role.decision_policy,
                ),
                role,
            )
    declared = ", ".join(role.role_id for role in configuration.editorial_roles)
    raise EditorialRoleError(
        f"editorial role {requested!r} is not declared by the configuration "
        f"(declared: {declared or 'none'})"
    )


def render_editorial_role_rules(
    role: EditorialRole, surface: str | None = None
) -> str:
    """Render a declared role as deterministic prompt text.

    Structure and prohibitions travel together: a structure without its
    prohibitions is an invitation to produce the shape the role exists to
    avoid. ``surface`` ("wix" or "linkedin") appends that surface's
    role-scoped rules — rules that belong to this role only, deliberately not
    written into the shared channel configuration where every other stream
    would inherit them.
    """

    lines = [
        "",
        f"EDITORIAL ROLE — {role.role_id}: {role.intent}",
        "",
        "Structure:",
    ]
    lines.extend(f"- {item}" for item in role.structure)
    lines.append("")
    lines.append("Never do any of the following:")
    lines.extend(f"- {item}" for item in role.forbidden)
    surface_rules = {
        "wix": role.wix_rules, "linkedin": role.linkedin_rules,
    }.get(surface or "", ())
    if surface_rules:
        lines.append("")
        lines.append("For this surface:")
        lines.extend(f"- {item}" for item in surface_rules)
    lines.append("")
    return "\n".join(lines)
