"""Typed strategy views for controlled Release 1 execution.

The complete :class:`BusinessStrategyConfiguration` is loaded once.  This
module then exposes immutable, consumer-specific views so orchestration does
not pass a mutable catch-all dictionary or provider credentials downstream.

Configuration hashing and run-scoped snapshots deliberately belong to Task
#42 and are not implemented here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.strategy.business_config import (
    AudienceSegment,
    BrandEditorialPolicy,
    BusinessIdentity,
    BusinessStrategyConfiguration,
    CallToAction,
    CommercialStrategy,
    ContentStrategy,
    LinkedInChannelRules,
    Positioning,
    ProductService,
    PromptRuleReference,
    WixChannelRules,
)


class StrategyExecutionError(RuntimeError):
    """A required configuration view or identity is unavailable or stale."""


class _ImmutableView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfigurationIdentity(_ImmutableView):
    schema_version: str
    configuration_id: str
    configuration_version: str

    @classmethod
    def from_configuration(
        cls, configuration: BusinessStrategyConfiguration
    ) -> "ConfigurationIdentity":
        return cls(
            schema_version=configuration.schema_version,
            configuration_id=configuration.configuration_id,
            configuration_version=configuration.configuration_version,
        )


class ResearchStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    business: BusinessIdentity
    products_services: tuple[ProductService, ...]
    audiences: tuple[AudienceSegment, ...]
    positioning: Positioning
    commercial: CommercialStrategy
    content: ContentStrategy
    restrictions: tuple[str, ...]
    prompt_rule_references: tuple[PromptRuleReference, ...]


class DecisionLensEditorialStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    business: BusinessIdentity
    audiences: tuple[AudienceSegment, ...]
    positioning: Positioning
    content: ContentStrategy
    brand_editorial: BrandEditorialPolicy
    calls_to_action: tuple[CallToAction, ...]
    prompt_rule_references: tuple[PromptRuleReference, ...]

    def cta(self, cta_id: str) -> CallToAction:
        for item in self.calls_to_action:
            if item.cta_id == cta_id:
                return item
        raise StrategyExecutionError(
            f"CTA {cta_id!r} is not declared by configuration "
            f"{self.identity.configuration_id!r}"
        )

    def legacy_prompt_values(self) -> dict[str, str]:
        """Map configured meaning into the existing Editorial Engine boundary.

        The scalar key names are a compatibility adapter for current prompts;
        the business meaning itself comes exclusively from configuration.
        """

        first_audience = self.audiences[0]
        return {
            "primary_message": self.positioning.statement,
            "selected_problem": first_audience.problems[0],
            "desired_reader_realization": self.content.objectives[0],
            "compound_presence_role": self.positioning.value_propositions[0],
            "strategy_id": self.identity.configuration_id,
        }


class WixStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    rules: WixChannelRules


class LinkedInStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    rules: LinkedInChannelRules


class VisualStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    wix_rules: tuple[str, ...]
    linkedin_rules: tuple[str, ...]


class StrategyExecutionContext(_ImmutableView):
    """One immutable set of declared views for a controlled R1 execution."""

    identity: ConfigurationIdentity
    research: ResearchStrategyView
    decision_lens_editorial: DecisionLensEditorialStrategyView
    wix: WixStrategyView
    linkedin: LinkedInStrategyView
    visual: VisualStrategyView

    @classmethod
    def from_configuration(
        cls, configuration: BusinessStrategyConfiguration
    ) -> "StrategyExecutionContext":
        if configuration.status != "active":
            raise StrategyExecutionError(
                f"Business Strategy Configuration is not active: "
                f"{configuration.configuration_id}"
            )

        identity = ConfigurationIdentity.from_configuration(configuration)
        research = ResearchStrategyView(
            identity=identity,
            business=configuration.business,
            products_services=configuration.products_services,
            audiences=configuration.audiences,
            positioning=configuration.positioning,
            commercial=configuration.commercial,
            content=configuration.content,
            restrictions=(
                *configuration.brand_editorial.prohibited_claims,
                *configuration.brand_editorial.legal_factual_reputational_restrictions,
            ),
            prompt_rule_references=configuration.prompt_rule_references,
        )
        editorial = DecisionLensEditorialStrategyView(
            identity=identity,
            business=configuration.business,
            audiences=configuration.audiences,
            positioning=configuration.positioning,
            content=configuration.content,
            brand_editorial=configuration.brand_editorial,
            calls_to_action=configuration.calls_to_action,
            prompt_rule_references=configuration.prompt_rule_references,
        )
        wix = WixStrategyView(identity=identity, rules=configuration.channels.wix)
        linkedin = LinkedInStrategyView(
            identity=identity, rules=configuration.channels.linkedin
        )
        visual = VisualStrategyView(
            identity=identity,
            wix_rules=configuration.channels.wix.visual_rules,
            linkedin_rules=configuration.channels.linkedin.visual_rules,
        )
        return cls(
            identity=identity,
            research=research,
            decision_lens_editorial=editorial,
            wix=wix,
            linkedin=linkedin,
            visual=visual,
        )

    def assert_consistent(self) -> None:
        for boundary, view in (
            ("research", self.research),
            ("decision-lens/editorial", self.decision_lens_editorial),
            ("wix", self.wix),
            ("linkedin", self.linkedin),
            ("visual", self.visual),
        ):
            require_configuration_identity(self.identity, view.identity, boundary)


def require_configuration_identity(
    expected: ConfigurationIdentity,
    actual: ConfigurationIdentity,
    boundary: str,
) -> None:
    """Fail closed when a consumer receives a different configuration."""

    if actual != expected:
        raise StrategyExecutionError(
            f"configuration identity mismatch at {boundary}: "
            f"expected {expected.model_dump()}, got {actual.model_dump()}"
        )


def identity_from_mapping(data: object, *, boundary: str) -> ConfigurationIdentity:
    """Read exact identity from a generated/package mapping without defaults."""

    if not isinstance(data, dict):
        raise StrategyExecutionError(
            f"configuration identity missing at {boundary}"
        )
    try:
        return ConfigurationIdentity.model_validate(data)
    except Exception as exc:
        raise StrategyExecutionError(
            f"configuration identity missing or invalid at {boundary}"
        ) from exc


def assert_campaign_reference(
    configuration: BusinessStrategyConfiguration,
    *,
    campaign_version: str,
) -> None:
    """Ensure the selected campaign is the one declared by business config."""

    references = {
        item.reference_id: item for item in configuration.prompt_rule_references
    }
    reference = references.get("active-campaign-strategy")
    if reference is None:
        raise StrategyExecutionError(
            "required active-campaign-strategy reference is missing"
        )
    if reference.version != campaign_version:
        raise StrategyExecutionError(
            "active campaign version does not match Business Strategy "
            f"Configuration: expected {reference.version!r}, got {campaign_version!r}"
        )
