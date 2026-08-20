"""Release 1 Business Strategy Configuration contract and strict loader.

This module is the provider-neutral boundary for business meaning.  It does
not contain publisher credentials, provider payloads, or orchestration logic.
The legacy campaign ``Strategy`` model remains in ``src.strategy.models``
until Tasks #40 and #41 migrate the active Never Blank configuration and its
consumers to this contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)


DEFAULT_BUSINESS_STRATEGY_PATH = Path("strategy/current/business_strategy.json")

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonEmptyTextTuple = Annotated[tuple[NonBlankStr, ...], Field(min_length=1)]


class _ContractModel(BaseModel):
    """Strict, immutable base for every configuration section."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BusinessIdentity(_ContractModel):
    name: NonBlankStr
    business_model: NonBlankStr
    description: NonBlankStr


class ProductService(_ContractModel):
    product_id: NonBlankStr
    name: NonBlankStr
    description: NonBlankStr


class AudienceSegment(_ContractModel):
    audience_id: NonBlankStr
    name: NonBlankStr
    selection_terms: tuple[NonBlankStr, ...] = ()
    problems: NonEmptyTextTuple
    default_problem: NonBlankStr
    decision_factors: NonEmptyTextTuple
    objections: tuple[NonBlankStr, ...] = ()


class Positioning(_ContractModel):
    statement: NonBlankStr
    expertise: NonEmptyTextTuple
    value_propositions: NonEmptyTextTuple
    proof_points: NonEmptyTextTuple


class CommercialStrategy(_ContractModel):
    priorities: NonEmptyTextTuple


class ContentStrategy(_ContractModel):
    objectives: NonEmptyTextTuple
    territories: NonEmptyTextTuple


class BrandEditorialPolicy(_ContractModel):
    voice: NonEmptyTextTuple
    editorial_principles: NonEmptyTextTuple
    preferred_claims: NonEmptyTextTuple
    prohibited_claims: NonEmptyTextTuple
    legal_factual_reputational_restrictions: NonEmptyTextTuple


class CallToAction(_ContractModel):
    cta_id: NonBlankStr
    intent: NonBlankStr
    rules: NonEmptyTextTuple


class EditorialRole(_ContractModel):
    """One declared editorial role a run may be produced under (Issue #142).

    Generic by construction: the engine knows a role has an intent, a
    structure and a list of prohibitions. What any particular role means is
    the configured business's decision, so a different business declares
    different roles — or none — without changing this contract.
    """

    role_id: NonBlankStr
    intent: NonBlankStr
    structure: NonEmptyTextTuple
    forbidden: NonEmptyTextTuple
    #: What source material this role may be produced from (Issue #142).
    #: Empty means the role imposes no source-class restriction — the prior
    #: behaviour. The criteria are policy text the configured business owns;
    #: the engine only carries them to the judgment that applies them.
    eligibility_criteria: tuple[NonBlankStr, ...] = ()
    #: Surface-scoped additions a role may make to its own composition rules
    #: (Issue #142 review round 1). These belong to the ROLE, not to the
    #: shared channel configuration: a role-specific requirement placed on
    #: ``channels.*`` would silently change every other stream's output.
    wix_rules: tuple[NonBlankStr, ...] = ()
    linkedin_rules: tuple[NonBlankStr, ...] = ()
    #: When true, generated output is verified against the run's actual
    #: sources before any publisher is called (Issue #142 review round 2).
    #: The prompt asks for attribution; this makes ignoring the ask a
    #: fail-closed stop instead of a published article without provenance.
    require_source_transparency: bool = False
    #: Which decision policy governs the run between READY research and
    #: generation (Issue #152). "decision_lens" is today's behaviour for every
    #: role and for role-less runs: the canonical Decision Lens must return
    #: PROCEED. "role_bounded_r1" lets an explicitly configured role proceed
    #: on READY research alone — an R1 product decision recorded in run
    #: evidence, pending the R2 reconciliation in #151. Nothing downstream is
    #: relaxed: acceptance, source transparency, preflight and publishers are
    #: unchanged.
    decision_policy: Literal["decision_lens", "role_bounded_r1"] = "decision_lens"


class WixChannelRules(_ContractModel):
    article_rules: NonEmptyTextTuple
    metadata_rules: NonEmptyTextTuple
    link_rules: NonEmptyTextTuple
    cta_rules: NonEmptyTextTuple
    visual_rules: NonEmptyTextTuple


class LinkedInChannelRules(_ContractModel):
    opening_rules: NonEmptyTextTuple
    length_rules: NonEmptyTextTuple
    formatting_rules: NonEmptyTextTuple
    link_rules: NonEmptyTextTuple
    cta_rules: NonEmptyTextTuple
    visual_rules: NonEmptyTextTuple


class ChannelRules(_ContractModel):
    wix: WixChannelRules
    linkedin: LinkedInChannelRules


class PromptRuleReference(_ContractModel):
    reference_id: NonBlankStr
    path: NonBlankStr
    version: NonBlankStr


class BusinessStrategyConfiguration(_ContractModel):
    """Complete provider-neutral Business Strategy Configuration for R1."""

    schema_version: NonBlankStr
    configuration_id: NonBlankStr
    configuration_version: NonBlankStr
    status: Literal["active", "inactive", "retired"]
    business: BusinessIdentity
    products_services: tuple[ProductService, ...]
    default_audience_id: NonBlankStr
    audiences: tuple[AudienceSegment, ...]
    positioning: Positioning
    commercial: CommercialStrategy
    content: ContentStrategy
    brand_editorial: BrandEditorialPolicy
    calls_to_action: tuple[CallToAction, ...]
    channels: ChannelRules
    prompt_rule_references: tuple[PromptRuleReference, ...]
    #: Declared editorial roles (Issue #142). Optional and empty by default:
    #: a configuration that declares none keeps its exact prior behaviour, and
    #: a run simply has no role to record.
    editorial_roles: tuple[EditorialRole, ...] = ()

    @model_validator(mode="after")
    def _validate_required_collections_and_ids(self) -> "BusinessStrategyConfiguration":
        required_collections = {
            "products_services": self.products_services,
            "audiences": self.audiences,
            "calls_to_action": self.calls_to_action,
            "prompt_rule_references": self.prompt_rule_references,
        }
        for name, values in required_collections.items():
            if not values:
                raise ValueError(f"{name} must contain at least one item")
        role_ids = [role.role_id for role in self.editorial_roles]
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("editorial role IDs must be unique")

        self._require_unique("product_id", self.products_services)
        self._require_unique("audience_id", self.audiences)
        self._require_unique("cta_id", self.calls_to_action)
        self._require_unique("reference_id", self.prompt_rule_references)
        audience_ids = {item.audience_id for item in self.audiences}
        if self.default_audience_id not in audience_ids:
            raise ValueError("default_audience_id must reference a configured audience")
        for audience in self.audiences:
            if audience.default_problem not in audience.problems:
                raise ValueError(
                    f"default_problem for {audience.audience_id!r} must be one of its problems"
                )
        return self

    @staticmethod
    def _require_unique(field_name: str, values: tuple[_ContractModel, ...]) -> None:
        identifiers = [getattr(value, field_name) for value in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"duplicate {field_name} values are not allowed")


class BusinessStrategyConfigurationError(RuntimeError):
    """Base error for strict Business Strategy Configuration loading."""


class BusinessStrategyConfigurationNotFound(BusinessStrategyConfigurationError):
    """The configured production file does not exist."""


class BusinessStrategyConfigurationParseError(BusinessStrategyConfigurationError):
    """The configured file is not valid JSON."""


class BusinessStrategyConfigurationValidationError(BusinessStrategyConfigurationError):
    """JSON does not satisfy the Business Strategy Configuration contract."""


class BusinessStrategyConfigurationInactiveError(BusinessStrategyConfigurationError):
    """A non-active configuration was selected for production execution."""


def load_business_strategy_configuration(
    path: Path = DEFAULT_BUSINESS_STRATEGY_PATH,
    *,
    require_active: bool = True,
) -> BusinessStrategyConfiguration:
    """Load one validated configuration or raise a typed, fail-closed error.

    This production loader never returns ``None`` and never supplies defaults.
    Tests may pass an explicit fixture path; runtime callers should use the
    configured production path.
    """

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BusinessStrategyConfigurationNotFound(
            f"Business Strategy Configuration not found: {path}"
        ) from exc
    except OSError as exc:
        raise BusinessStrategyConfigurationError(
            f"Business Strategy Configuration could not be read: {path}"
        ) from exc

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BusinessStrategyConfigurationParseError(
            f"Business Strategy Configuration is not valid JSON: {path}"
        ) from exc

    try:
        configuration = BusinessStrategyConfiguration.model_validate(data)
    except ValidationError as exc:
        raise BusinessStrategyConfigurationValidationError(
            f"Business Strategy Configuration failed validation: {path}"
        ) from exc

    if require_active and configuration.status != "active":
        raise BusinessStrategyConfigurationInactiveError(
            f"Business Strategy Configuration is not active: {configuration.configuration_id}"
        )
    return configuration
