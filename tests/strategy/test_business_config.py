from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.strategy.business_config import (
    BusinessStrategyConfiguration,
    BusinessStrategyConfigurationInactiveError,
    BusinessStrategyConfigurationNotFound,
    BusinessStrategyConfigurationParseError,
    BusinessStrategyConfigurationValidationError,
    load_business_strategy_configuration,
)


def _valid_config() -> dict:
    return {
        "schema_version": "1",
        "configuration_id": "fictional-r1-business",
        "configuration_version": "1",
        "status": "active",
        "business": {
            "name": "Fictional Advisory",
            "business_model": "B2B advisory",
            "description": "A fictional contract-test business.",
        },
        "products_services": [
            {
                "product_id": "advisory",
                "name": "Advisory",
                "description": "Structured advisory engagements.",
            }
        ],
        "audiences": [
            {
                "audience_id": "operators",
                "name": "Operations leaders",
                "problems": ["Unclear operating decisions"],
                "decision_factors": ["Evidence", "Implementation fit"],
                "objections": ["Change cost"],
            }
        ],
        "positioning": {
            "statement": "Evidence-led operating decisions.",
            "expertise": ["Operations"],
            "value_propositions": ["Clearer decisions"],
            "proof_points": ["Documented case evidence"],
        },
        "commercial": {"priorities": ["Qualified advisory conversations"]},
        "content": {
            "objectives": ["Teach a defensible operating method"],
            "territories": ["Decision quality"],
        },
        "brand_editorial": {
            "voice": ["Precise", "Direct"],
            "editorial_principles": ["Separate evidence from interpretation"],
            "preferred_claims": ["Use claims supported by cited evidence"],
            "prohibited_claims": ["Guaranteed outcomes"],
            "legal_factual_reputational_restrictions": [
                "Do not identify clients without documented permission"
            ],
        },
        "calls_to_action": [
            {
                "cta_id": "reflection",
                "intent": "Invite self-assessment",
                "rules": ["Do not manufacture urgency"],
            }
        ],
        "channels": {
            "wix": {
                "article_rules": ["Use a complete argument"],
                "metadata_rules": ["Provide a descriptive title"],
                "link_rules": ["Cite primary sources"],
                "cta_rules": ["Use an approved CTA"],
                "visual_rules": ["Use an approved cover image"],
            },
            "linkedin": {
                "opening_rules": ["Lead with the decision tension"],
                "length_rules": ["Remain within the configured limit"],
                "formatting_rules": ["Use readable paragraphs"],
                "link_rules": ["Place links according to channel policy"],
                "cta_rules": ["Use an approved CTA"],
                "visual_rules": ["Use the approved LinkedIn asset"],
            },
        },
        "prompt_rule_references": [
            {
                "reference_id": "editorial-rules",
                "path": "prompts/editorial.yaml",
                "version": "1",
            }
        ],
    }


def _write_config(tmp_path, data: dict):
    path = tmp_path / "business_strategy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_complete_contract_is_strict_immutable_and_serializable():
    configuration = BusinessStrategyConfiguration.model_validate(_valid_config())

    assert configuration.configuration_id == "fictional-r1-business"
    assert configuration.channels.wix != configuration.channels.linkedin
    assert configuration.model_dump(mode="json") == _valid_config()
    with pytest.raises(ValidationError):
        configuration.configuration_version = "2"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("business"),
        lambda data: data.update({"unknown": "rejected"}),
        lambda data: data.update({"configuration_id": "   "}),
        lambda data: data.update({"products_services": []}),
        lambda data: data["channels"].pop("linkedin"),
        lambda data: data["business"].update({"name": "   "}),
        lambda data: data["audiences"][0].update({"problems": []}),
        lambda data: data["brand_editorial"].update({"prohibited_claims": []}),
        lambda data: data["channels"]["wix"].update({"article_rules": []}),
        lambda data: data["channels"]["linkedin"].update({"opening_rules": [" "]}),
    ],
)
def test_incomplete_unknown_blank_or_invalid_contract_is_rejected(mutation):
    data = _valid_config()
    mutation(data)
    with pytest.raises(ValidationError):
        BusinessStrategyConfiguration.model_validate(data)


@pytest.mark.parametrize(
    ("collection", "id_field"),
    [
        ("products_services", "product_id"),
        ("audiences", "audience_id"),
        ("calls_to_action", "cta_id"),
        ("prompt_rule_references", "reference_id"),
    ],
)
def test_duplicate_section_identifiers_are_rejected(collection, id_field):
    data = _valid_config()
    duplicate = dict(data[collection][0])
    assert duplicate[id_field]
    data[collection].append(duplicate)

    with pytest.raises(ValidationError, match=f"duplicate {id_field}"):
        BusinessStrategyConfiguration.model_validate(data)


def test_strict_loader_returns_valid_active_configuration(tmp_path):
    path = _write_config(tmp_path, _valid_config())

    configuration = load_business_strategy_configuration(path)

    assert configuration.status == "active"
    assert configuration.business.name == "Fictional Advisory"


def test_strict_loader_never_falls_back_for_missing_file(tmp_path):
    with pytest.raises(BusinessStrategyConfigurationNotFound):
        load_business_strategy_configuration(tmp_path / "missing.json")


def test_strict_loader_rejects_invalid_json(tmp_path):
    path = tmp_path / "business_strategy.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(BusinessStrategyConfigurationParseError):
        load_business_strategy_configuration(path)


def test_strict_loader_rejects_schema_invalid_json(tmp_path):
    path = _write_config(tmp_path, {"configuration_id": "incomplete"})

    with pytest.raises(BusinessStrategyConfigurationValidationError):
        load_business_strategy_configuration(path)


@pytest.mark.parametrize("status", ["inactive", "retired"])
def test_strict_production_loader_rejects_non_active_config(tmp_path, status):
    data = _valid_config()
    data["status"] = status
    path = _write_config(tmp_path, data)

    with pytest.raises(BusinessStrategyConfigurationInactiveError):
        load_business_strategy_configuration(path)


def test_explicit_nonproduction_read_may_inspect_inactive_config(tmp_path):
    data = _valid_config()
    data["status"] = "inactive"
    path = _write_config(tmp_path, data)

    configuration = load_business_strategy_configuration(path, require_active=False)

    assert configuration.status == "inactive"


def test_provider_credentials_and_payloads_are_not_contract_fields():
    data = _valid_config()
    data["credentials"] = {"api_key": "secret"}

    with pytest.raises(ValidationError, match="credentials"):
        BusinessStrategyConfiguration.model_validate(data)
