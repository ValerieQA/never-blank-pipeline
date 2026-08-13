from __future__ import annotations

from pathlib import Path

from src.strategy.business_config import load_business_strategy_configuration


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CONFIG = REPOSITORY_ROOT / "strategy/current/business_strategy.json"


def test_never_blank_production_configuration_is_complete_and_active():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)

    assert configuration.configuration_id == "never-blank"
    assert configuration.configuration_version == "1"
    assert configuration.schema_version == "1"
    assert configuration.status == "active"
    assert configuration.business.name == "Never Blank"
    assert len(configuration.products_services) >= 2
    assert {audience.audience_id for audience in configuration.audiences} == {
        "small-b2b-agencies",
        "independent-consultants",
        "managed-service-providers",
    }


def test_production_configuration_contains_no_placeholder_content():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)
    forbidden_values = {"", "todo", "tbd", "placeholder", "lorem ipsum"}

    def text_values(value):
        if isinstance(value, dict):
            for nested in value.values():
                yield from text_values(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from text_values(nested)
        elif isinstance(value, str):
            yield value.strip().lower()

    values = set(text_values(configuration.model_dump(mode="json")))
    assert values.isdisjoint(forbidden_values)
    assert not any("example.com" in value for value in values)


def test_claims_proof_and_restrictions_are_explicit_and_separate():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)

    assert len(configuration.positioning.proof_points) >= 3
    assert len(configuration.brand_editorial.preferred_claims) >= 3
    assert len(configuration.brand_editorial.prohibited_claims) >= 5
    assert len(
        configuration.brand_editorial.legal_factual_reputational_restrictions
    ) >= 5
    assert set(configuration.positioning.proof_points).isdisjoint(
        configuration.brand_editorial.preferred_claims
    )


def test_wix_and_linkedin_rules_are_complete_and_independently_addressable():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)
    wix = configuration.channels.wix
    linkedin = configuration.channels.linkedin

    assert wix.article_rules
    assert wix.metadata_rules
    assert wix.link_rules
    assert wix.cta_rules
    assert wix.visual_rules
    assert linkedin.opening_rules
    assert linkedin.length_rules
    assert linkedin.formatting_rules
    assert linkedin.link_rules
    assert linkedin.cta_rules
    assert linkedin.visual_rules
    assert wix.model_dump() != linkedin.model_dump()


def test_all_prompt_and_rule_references_resolve_inside_repository():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)

    for reference in configuration.prompt_rule_references:
        resolved = REPOSITORY_ROOT / reference.path
        assert resolved.is_file(), f"Missing reference: {reference.path}"
        assert resolved.resolve().is_relative_to(REPOSITORY_ROOT.resolve())


def test_release_one_configuration_requires_only_wix_and_linkedin_channels():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)
    channels = set(type(configuration.channels).model_fields)

    assert channels == {"wix", "linkedin"}


def test_configuration_contains_no_credentials_or_secret_shaped_fields():
    configuration = load_business_strategy_configuration(PRODUCTION_CONFIG)

    def all_keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key.lower()
                yield from all_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from all_keys(nested)

    keys = set(all_keys(configuration.model_dump(mode="json")))
    assert keys.isdisjoint(
        {"api_key", "access_token", "password", "secret", "credentials", "sdk_payload"}
    )
