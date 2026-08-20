"""Generic configured editorial-role identity and prompt rendering.

A role belongs to a run, not to a weekday or source. Its identity is persisted
as evidence and its business meaning is resolved from strict configuration.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.strategy.business_config import BusinessStrategyConfiguration, EditorialRole


class EditorialRoleError(RuntimeError):
    """The requested editorial role is not declared by the configuration."""


class EditorialRoleIdentity(BaseModel):
    """Names the configured role used by one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_id: str = Field(min_length=1, max_length=120)
    configuration_version: str = Field(min_length=1, max_length=80)


def resolve_editorial_role(
    configuration: BusinessStrategyConfiguration, role_id: str
) -> tuple[EditorialRoleIdentity, EditorialRole]:
    """Resolve an explicit role id or fail closed."""

    requested = (role_id or "").strip()
    if not requested:
        raise EditorialRoleError("an editorial role id is required")
    for role in configuration.editorial_roles:
        if role.role_id == requested:
            return (
                EditorialRoleIdentity(
                    role_id=role.role_id,
                    configuration_version=configuration.configuration_version,
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
    """Render deterministic role rules for one optional publication surface."""

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
        "wix": role.wix_rules,
        "linkedin": role.linkedin_rules,
    }.get(surface or "", ())
    if surface_rules:
        lines.append("")
        lines.append("For this surface:")
        lines.extend(f"- {item}" for item in surface_rules)
    lines.append("")
    return "\n".join(lines)
