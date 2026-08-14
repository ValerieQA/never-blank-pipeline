"""Adversarial production-model tests for Issue #58."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.editorial.decision_contract import (
    BusinessAudienceRelevance,
    DecisionContractError,
    DecisionDisposition,
    DecisionEvidenceSufficiency,
    DecisionLensDecisionArtifact,
    RelevanceBasisType,
    research_artifact_digest,
)
from src.research.evidence import NormalizedResearchArtifact
from src.strategy.execution_context import AudienceSelection, ConfigurationIdentity


UTC = timezone.utc
RUN_ID = "12345678-1234-4234-8234-123456789abc"
DECISION_ID = "87654321-4321-4321-8321-cba987654321"


def _identity() -> ConfigurationIdentity:
    return ConfigurationIdentity(
        schema_version="1",
        configuration_id="never-blank-production",
        configuration_version="2.0",
        configuration_hash="sha256:" + "a" * 64,
    )


def _audience() -> AudienceSelection:
    return AudienceSelection(
        audience_id="independent-service-owner",
        audience_name="Independent service business owner",
        selected_problem="Deciding where constrained operating capacity creates value.",
        decision_factors=("cash flow", "capacity"),
        objections=("generic enterprise advice",),
        selection_source="configured-default",
    )


def _research_payload() -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": "research-58",
        "run_id": RUN_ID,
        "assignment_id": "assignment-58",
        "signal_id": "signal-58",
        "configuration_identity": _identity().model_dump(mode="json"),
        "created_at": "2026-08-14T12:00:02Z",
        "sources": [{
            "source_id": "source-sba",
            "locator": {"kind": "url", "value": "https://advocacy.sba.gov/report"},
            "title": "Small-business operating constraints",
            "publisher": "SBA Office of Advocacy",
            "publication_time": {"status": "known", "value": "2026-08-01T12:00:00Z"},
            "retrieved_at": "2026-08-14T12:00:01Z",
        }],
        "evidence": [{
            "evidence_id": "evidence-smb",
            "claim": "Independent service firms report capacity as a material decision constraint.",
            "source_ids": ["source-sba"],
            "support": [{
                "source_id": "source-sba",
                "excerpt": "Capacity is a documented constraint for surveyed small firms.",
                "location": "table 3",
            }],
            "disposition": "accepted",
        }],
        "interpretations": [],
        "uncertainties": [],
        "contradictions": [],
        "readiness": "ready",
    }


def _research() -> NormalizedResearchArtifact:
    return NormalizedResearchArtifact.model_validate(_research_payload())


def _decision_payload(
    *,
    disposition: str = "proceed",
    basis_type: str = "direct_audience_evidence",
) -> dict:
    research = _research()
    direct_consequence = (
        "The documented change alters customer acquisition cost for the selected owners."
        if basis_type == "documented_direct_impact"
        else None
    )
    return {
        "schema_version": "1.0",
        "decision_artifact_id": DECISION_ID,
        "run_id": RUN_ID,
        "assignment_id": "assignment-58",
        "signal_id": "signal-58",
        "configuration_identity": _identity().model_dump(mode="json"),
        "audience_selection": _audience().model_dump(mode="json"),
        "research_digest": research_artifact_digest(research),
        "decision_lens_version": "decision-lens-rules-v1",
        "evaluator": {
            "evaluator_id": "declared-decision-evaluator",
            "evaluator_version": "1.0",
            "kind": "declared_model",
        },
        "evaluation_started_at": "2026-08-14T12:00:03Z",
        "created_at": "2026-08-14T12:00:04Z",
        "source_ids": ["source-sba"],
        "evidence_ids": ["evidence-smb"],
        "judgment": {
            "relevance": "direct",
            "evidence_sufficiency": "sufficient",
            "why_signal_matters": "It changes a constrained operating decision now.",
            "business_value_connection": "The evidence connects capacity to owner economics.",
            "audience_problem_or_opportunity": "Choose work that fits finite delivery capacity.",
            "defensible_perspective": "Capacity allocation is a commercial choice, not scheduling trivia.",
            "supported_editorial_angle": "How independent owners can price scarce delivery capacity.",
            "relevance_bases": [{
                "basis_type": basis_type,
                "audience_id": _audience().audience_id,
                "statement": "The cited evidence directly studies the configured audience.",
                "evidence_ids": ["evidence-smb"],
                "source_ids": ["source-sba"],
                "documented_direct_consequence": direct_consequence,
            }],
            "research_condition_handling": [],
            "restrictions": ["Do not generalize beyond independent service firms."],
            "disposition_reasons": ["Current-run evidence directly supports the angle."],
        },
        "disposition": disposition,
    }


def _validate(payload: dict | None = None, *, research=None, audience=None, identity=None):
    return DecisionLensDecisionArtifact.validate_for_research(
        payload or _decision_payload(),
        research=research or _research(),
        audience=audience or _audience(),
        configuration_identity=identity or _identity(),
    )


def test_valid_proceed_preserves_complete_lineage_and_structured_judgment():
    decision = _validate()
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.configuration_identity == _identity()
    assert decision.audience_selection == _audience()
    assert decision.research_digest == research_artifact_digest(_research())
    assert decision.judgment.relevance is BusinessAudienceRelevance.DIRECT
    assert decision.judgment.evidence_sufficiency is DecisionEvidenceSufficiency.SUFFICIENT


@pytest.mark.parametrize(
    "disposition",
    ["proceed", "revise", "hold", "reject", "insufficient_evidence"],
)
def test_every_declared_disposition_is_representable(disposition):
    payload = _decision_payload(disposition=disposition)
    if disposition != "proceed":
        payload["judgment"]["evidence_sufficiency"] = "partial"
    decision = _validate(payload)
    assert decision.disposition.value == disposition


def test_non_proceed_preserves_bounded_reasons_without_parallel_success_flag():
    payload = _decision_payload(disposition="hold")
    payload["judgment"]["evidence_sufficiency"] = "partial"
    decision = _validate(payload)
    assert decision.judgment.disposition_reasons
    assert "ready" not in DecisionLensDecisionArtifact.model_fields
    assert "success" not in DecisionLensDecisionArtifact.model_fields


@pytest.mark.parametrize("field", ["source_ids", "evidence_ids"])
def test_zero_support_cannot_proceed(field):
    payload = _decision_payload()
    payload[field] = []
    with pytest.raises(ValidationError, match="requires cited|undeclared"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("relevance", "irrelevant", "direct audience relevance"),
        ("evidence_sufficiency", "insufficient", "sufficient evidence"),
    ],
)
def test_false_proceed_judgment_combinations_are_rejected(field, value, message):
    payload = _decision_payload()
    payload["judgment"][field] = value
    with pytest.raises(ValidationError, match=message):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["defensible_perspective", "supported_editorial_angle"])
def test_proceed_rejects_empty_perspective_or_angle(field):
    payload = _decision_payload()
    payload["judgment"][field] = ""
    with pytest.raises(ValidationError):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_unrelated_large_company_analogy_cannot_proceed():
    payload = _decision_payload(basis_type="analogy_only")
    payload["judgment"]["why_signal_matters"] = "Toyota made an interesting strategy choice."
    payload["judgment"]["relevance_bases"][0]["statement"] = (
        "A small firm might face something thematically similar."
    )
    with pytest.raises(ValidationError, match="analogy-only"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize(
    "basis_type",
    [
        "direct_audience_evidence",
        "client_first_party_evidence",
        "credible_sector_evidence",
    ],
)
def test_direct_small_business_or_client_evidence_can_support_proceed(basis_type):
    decision = _validate(_decision_payload(basis_type=basis_type))
    assert decision.judgment.relevance_bases[0].basis_type.value == basis_type


def test_large_company_action_requires_documented_direct_audience_impact():
    valid = _validate(_decision_payload(basis_type="documented_direct_impact"))
    assert valid.judgment.relevance_bases[0].documented_direct_consequence

    payload = _decision_payload(basis_type="documented_direct_impact")
    payload["judgment"]["relevance_bases"][0]["documented_direct_consequence"] = None
    with pytest.raises(ValidationError, match="requires the direct consequence"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_generic_this_matters_assertion_without_direct_basis_cannot_proceed():
    payload = _decision_payload(basis_type="analogy_only")
    payload["judgment"]["relevance_bases"][0]["statement"] = "This matters to small business."
    with pytest.raises(ValidationError, match="direct small-business evidence"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["source_ids", "evidence_ids"])
def test_unknown_research_references_fail_external_validation(field):
    payload = _decision_payload()
    missing = "missing-source" if field == "source_ids" else "missing-evidence"
    payload[field] = [missing]
    payload["judgment"]["relevance_bases"][0][field] = [missing]
    with pytest.raises(DecisionContractError, match="unknown research"):
        _validate(payload)


def test_decision_sources_must_exactly_support_cited_evidence():
    research_payload = _research_payload()
    research_payload["sources"].append({
        "source_id": "source-unrelated",
        "locator": {"kind": "url", "value": "https://example.test/unrelated"},
        "title": "Unrelated corporate case",
        "publisher": "Example",
        "publication_time": {"status": "unknown", "value": None},
        "retrieved_at": "2026-08-14T12:00:01Z",
    })
    research = NormalizedResearchArtifact.model_validate(research_payload)
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    payload["source_ids"].append("source-unrelated")
    payload["judgment"]["relevance_bases"][0]["source_ids"].append(
        "source-unrelated"
    )
    with pytest.raises(DecisionContractError, match="exactly match"):
        _validate(payload, research=research)


@pytest.mark.parametrize("field", ["source_ids", "evidence_ids"])
def test_duplicate_decision_references_are_rejected(field):
    payload = _decision_payload()
    payload[field] = payload[field] * 2
    with pytest.raises(ValidationError, match="must be unique"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_cross_kind_decision_id_collision_is_rejected():
    payload = _decision_payload()
    payload["evidence_ids"] = [payload["source_ids"][0]]
    payload["judgment"]["relevance_bases"][0]["evidence_ids"] = payload["evidence_ids"]
    with pytest.raises(ValidationError, match="share one decision namespace"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize("disposition", ["not_assessed", "conflicting", "rejected"])
def test_proceed_cannot_cite_blocked_evidence(disposition):
    research_payload = _research_payload()
    research_payload["readiness"] = "needs_review"
    research_payload["evidence"][0]["disposition"] = disposition
    research = NormalizedResearchArtifact.model_validate(research_payload)
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    with pytest.raises(DecisionContractError, match="READY|blocked"):
        _validate(payload, research=research)


@pytest.mark.parametrize("blocker", ["contradiction", "material_uncertainty"])
def test_proceed_cannot_ignore_unresolved_research_blocker(blocker):
    research_payload = _research_payload()
    research_payload["readiness"] = "needs_review"
    if blocker == "contradiction":
        research_payload["contradictions"] = [{
            "contradiction_id": "contradiction-58",
            "resolution": "unresolved",
            "description": "The cited records remain inconsistent.",
            "evidence_ids": ["evidence-smb"],
            "source_ids": ["source-sba"],
        }]
    else:
        research_payload["uncertainties"] = [{
            "uncertainty_id": "uncertainty-58",
            "level": "high",
            "materiality": "material",
            "resolution": "unresolved",
            "description": "A material limitation remains unresolved.",
            "evidence_ids": ["evidence-smb"],
            "source_ids": [],
        }]
    research = NormalizedResearchArtifact.model_validate(research_payload)
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    with pytest.raises(DecisionContractError, match="READY|unresolved|material"):
        _validate(payload, research=research)


def test_resolved_contradiction_and_nonmaterial_uncertainty_allow_proceed():
    research_payload = _research_payload()
    research_payload["contradictions"] = [{
        "contradiction_id": "contradiction-resolved",
        "resolution": "resolved",
        "description": "The apparent conflict was bounded and resolved.",
        "evidence_ids": ["evidence-smb"],
        "source_ids": ["source-sba"],
    }]
    research_payload["uncertainties"] = [{
        "uncertainty_id": "uncertainty-nonmaterial",
        "level": "low",
        "materiality": "non_material",
        "resolution": "unresolved",
        "description": "A non-material sampling limitation remains.",
        "evidence_ids": ["evidence-smb"],
        "source_ids": [],
    }]
    research = NormalizedResearchArtifact.model_validate(research_payload)
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    payload["judgment"]["research_condition_handling"] = [
        {
            "condition_id": "contradiction-resolved",
            "kind": "contradiction",
            "treatment": "resolved",
            "explanation": "The decision uses the bounded resolution recorded by research.",
        },
        {
            "condition_id": "uncertainty-nonmaterial",
            "kind": "uncertainty",
            "treatment": "acknowledged",
            "explanation": "The sampling limitation is explicit and non-material.",
        },
    ]
    decision = _validate(payload, research=research)
    assert decision.disposition is DecisionDisposition.PROCEED
    assert len(decision.judgment.research_condition_handling) == 2


def test_unknown_or_wrong_kind_research_condition_reference_is_rejected():
    payload = _decision_payload()
    payload["judgment"]["research_condition_handling"] = [{
        "condition_id": "missing-condition",
        "kind": "uncertainty",
        "treatment": "acknowledged",
        "explanation": "A nonexistent limitation cannot be claimed as handled.",
    }]
    with pytest.raises(DecisionContractError, match="unknown research condition"):
        _validate(payload)


def test_duplicate_research_condition_handling_is_rejected():
    payload = _decision_payload()
    item = {
        "condition_id": "condition-duplicate",
        "kind": "uncertainty",
        "treatment": "bounded",
        "explanation": "Bounded condition.",
    }
    payload["judgment"]["research_condition_handling"] = [item, dict(item)]
    with pytest.raises(ValidationError, match="must be unique"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["run_id", "assignment_id", "signal_id"])
def test_execution_identity_mismatch_is_rejected(field):
    payload = _decision_payload()
    payload[field] = (
        "11111111-1111-4111-8111-111111111111" if field == "run_id" else "other"
    )
    with pytest.raises(DecisionContractError, match="execution identity"):
        _validate(payload)


def test_configuration_mismatch_is_rejected():
    other = ConfigurationIdentity(
        **{**_identity().model_dump(), "configuration_hash": "sha256:" + "b" * 64}
    )
    with pytest.raises(DecisionContractError, match="configuration identity mismatch"):
        _validate(identity=other)


def test_audience_mismatch_invalidates_relevance_basis():
    other = AudienceSelection(
        **{**_audience().model_dump(), "audience_id": "local-retail-owner"}
    )
    with pytest.raises(DecisionContractError, match="audience selection mismatch"):
        _validate(audience=other)


def test_research_digest_mismatch_is_rejected():
    payload = _decision_payload()
    payload["research_digest"] = "sha256:" + "0" * 64
    with pytest.raises(DecisionContractError, match="research digest mismatch"):
        _validate(payload)


def test_malformed_digest_and_schema_are_rejected():
    payload = _decision_payload()
    payload["research_digest"] = "md5:bad"
    with pytest.raises(ValidationError):
        DecisionLensDecisionArtifact.model_validate(payload)
    payload = _decision_payload()
    payload["schema_version"] = "2.0"
    with pytest.raises(ValidationError, match="unsupported"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize(
    "timestamp",
    [datetime(2026, 8, 14, 12), datetime(2026, 8, 14, 12, tzinfo=timezone(timedelta(hours=2)))],
)
@pytest.mark.parametrize("field", ["evaluation_started_at", "created_at"])
def test_decision_timestamps_require_strict_utc(field, timestamp):
    payload = _decision_payload()
    payload[field] = timestamp
    with pytest.raises(ValidationError, match="UTC"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_completion_before_start_is_rejected():
    payload = _decision_payload()
    payload["created_at"] = "2026-08-14T11:59:00Z"
    with pytest.raises(ValidationError, match="cannot precede"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("artifact", "raw_provider_payload"),
        ("judgment", "prompt"),
        ("basis", "metadata"),
        ("evaluator", "model_response"),
    ],
)
def test_extra_payload_prompt_and_metadata_escape_fields_are_rejected(target, field):
    payload = _decision_payload()
    selected = {
        "artifact": payload,
        "judgment": payload["judgment"],
        "basis": payload["judgment"]["relevance_bases"][0],
        "evaluator": payload["evaluator"],
    }[target]
    selected[field] = {"forbidden": object()}
    with pytest.raises(ValidationError):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize(
    "credential",
    ["api_key=top-secret", "Authorization: Bearer secret-token", "sk-abcdefghijklmnop"],
)
def test_credential_shaped_text_is_rejected(credential):
    payload = _decision_payload()
    payload["evaluator"]["evaluator_id"] = credential
    with pytest.raises(ValidationError, match="credential-shaped"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_all_canonical_models_are_frozen_and_forbid_extra():
    artifact = _validate()
    models = [
        artifact,
        artifact.configuration_identity,
        artifact.audience_selection,
        artifact.evaluator,
        artifact.judgment,
        artifact.judgment.relevance_bases[0],
    ]
    for model in models:
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
        with pytest.raises(ValidationError):
            setattr(model, next(iter(type(model).model_fields)), "changed")


def test_deterministic_bytes_and_strict_contextual_round_trip():
    artifact = _validate()
    first = artifact.canonical_bytes()
    second = artifact.canonical_bytes()
    restored = DecisionLensDecisionArtifact.validate_json_for_research(
        first,
        research=_research(),
        audience=_audience(),
        configuration_identity=_identity(),
    )
    assert first == second == restored.canonical_bytes()
    assert restored == artifact
    assert json.loads(first) == artifact.model_dump(mode="json")


def test_strict_json_reload_cannot_bypass_proceed_invariants():
    payload = _decision_payload(basis_type="analogy_only")
    with pytest.raises(ValidationError, match="analogy-only"):
        DecisionLensDecisionArtifact.validate_json_for_research(
            json.dumps(payload),
            research=_research(),
            audience=_audience(),
            configuration_identity=_identity(),
        )
