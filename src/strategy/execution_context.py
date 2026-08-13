"""Typed strategy views for controlled Release 1 execution.

The complete :class:`BusinessStrategyConfiguration` is loaded once.  This
module then exposes immutable, consumer-specific views so orchestration does
not pass a mutable catch-all dictionary or provider credentials downstream.

Configuration identity includes the deterministic content hash introduced by
Task #42.  The hash is derived from the validated model, never the source file.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

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
    configuration_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @classmethod
    def from_configuration(
        cls, configuration: BusinessStrategyConfiguration
    ) -> "ConfigurationIdentity":
        return cls(
            schema_version=configuration.schema_version,
            configuration_id=configuration.configuration_id,
            configuration_version=configuration.configuration_version,
            configuration_hash=configuration_hash(configuration),
        )


CANONICAL_CONFIGURATION_SERIALIZATION = "business-strategy-json-v1"
CONFIGURATION_HASH_ALGORITHM = "sha256"


def canonical_configuration_bytes(
    configuration: BusinessStrategyConfiguration,
) -> bytes:
    """Serialize validated configuration meaning for stable content hashing.

    ``business-strategy-json-v1`` is UTF-8 JSON of ``model_dump(mode='json')``
    with keys sorted, no insignificant whitespace, JSON booleans/null, and
    non-ASCII characters preserved.  Source formatting and paths are absent.
    """

    if not isinstance(configuration, BusinessStrategyConfiguration):
        raise TypeError("configuration must be a validated BusinessStrategyConfiguration")
    return json.dumps(
        configuration.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def configuration_hash(configuration: BusinessStrategyConfiguration) -> str:
    """Return the versioned deterministic identity hash of validated meaning."""

    digest = hashlib.sha256(canonical_configuration_bytes(configuration)).hexdigest()
    return f"{CONFIGURATION_HASH_ALGORITHM}:{digest}"


class ResearchStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    business: BusinessIdentity
    products_services: tuple[ProductService, ...]
    audiences: tuple[AudienceSegment, ...]
    default_audience_id: str
    positioning: Positioning
    commercial: CommercialStrategy
    content: ContentStrategy
    restrictions: tuple[str, ...]
    preferred_claims: tuple[str, ...]
    prompt_rule_references: tuple[PromptRuleReference, ...]

    def select_audience(self, requested: str | None) -> "AudienceSelection":
        return _select_audience(self.audiences, self.default_audience_id, requested)


class DecisionLensEditorialStrategyView(_ImmutableView):
    identity: ConfigurationIdentity
    business: BusinessIdentity
    audiences: tuple[AudienceSegment, ...]
    default_audience_id: str
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

    def select_audience(self, requested: str | None) -> "AudienceSelection":
        return _select_audience(self.audiences, self.default_audience_id, requested)


class AudienceSelection(_ImmutableView):
    audience_id: str
    audience_name: str
    selected_problem: str
    decision_factors: tuple[str, ...]
    objections: tuple[str, ...]
    selection_source: str


def _normalise_selector(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())


def _select_audience(
    audiences: tuple[AudienceSegment, ...],
    default_audience_id: str,
    requested: str | None,
) -> AudienceSelection:
    selector = requested or default_audience_id
    normalised = _normalise_selector(selector)
    matches = []
    for audience in audiences:
        declared = (audience.audience_id, audience.name, *audience.selection_terms)
        if normalised in {_normalise_selector(value) for value in declared}:
            matches.append(audience)
    if len(matches) != 1:
        reason = "unknown" if not matches else "ambiguous"
        raise StrategyExecutionError(
            f"{reason} target audience {selector!r}; expected exactly one configured audience"
        )
    audience = matches[0]
    return AudienceSelection(
        audience_id=audience.audience_id,
        audience_name=audience.name,
        selected_problem=audience.default_problem,
        decision_factors=audience.decision_factors,
        objections=audience.objections,
        selection_source="assignment" if requested else "configured-default",
    )


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
            default_audience_id=configuration.default_audience_id,
            positioning=configuration.positioning,
            commercial=configuration.commercial,
            content=configuration.content,
            restrictions=(
                *configuration.brand_editorial.prohibited_claims,
                *configuration.brand_editorial.legal_factual_reputational_restrictions,
            ),
            preferred_claims=configuration.brand_editorial.preferred_claims,
            prompt_rule_references=configuration.prompt_rule_references,
        )
        editorial = DecisionLensEditorialStrategyView(
            identity=identity,
            business=configuration.business,
            audiences=configuration.audiences,
            default_audience_id=configuration.default_audience_id,
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
