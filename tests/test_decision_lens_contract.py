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
    EditorialClaimMode,
    DecisionEvidenceSufficiency,
    DecisionLensDecisionArtifact,
    DecisionLensProfileIdentity,
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


def _lens_profile() -> DecisionLensProfileIdentity:
    """Never Blank is the first Release 1 lens profile; it is fixture data, not schema."""

    return DecisionLensProfileIdentity(
        lens_profile_id="never-blank-editorial-lens",
        lens_profile_version="1.0",
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
        "lens_profile": _lens_profile().model_dump(mode="json"),
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
            "criterion_results": [{
                "criterion_id": "nb-supported-mechanism",
                "assessment": "satisfied",
                "conclusion": "The evidence shows an owner-presence decision the audience must make.",
                "evidence_ids": ["evidence-smb"],
                "source_ids": ["source-sba"],
                "restrictions": [],
            }],
            "research_condition_handling": [],
            "restrictions": ["Do not generalize beyond independent service firms."],
            "disposition_reasons": ["Current-run evidence directly supports the angle."],
        },
        "disposition": disposition,
    }


def _validate(
    payload: dict | DecisionLensDecisionArtifact | None = None,
    *,
    research=None,
    audience=None,
    identity=None,
    lens_profile=None,
):
    return DecisionLensDecisionArtifact.validate_for_research(
        payload if payload is not None else _decision_payload(),
        research=research or _research(),
        audience=audience or _audience(),
        configuration_identity=identity or _identity(),
        lens_profile=lens_profile or _lens_profile(),
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
    with pytest.raises(ValidationError, match="direct configured-audience evidence"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["source_ids", "evidence_ids"])
def test_unknown_research_references_fail_external_validation(field):
    payload = _decision_payload()
    missing = "missing-source" if field == "source_ids" else "missing-evidence"
    payload[field] = [missing]
    payload["judgment"]["relevance_bases"][0][field] = [missing]
    payload["judgment"]["criterion_results"][0][field] = [missing]
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
        ("profile", "profile_definition"),
        ("criterion", "metadata"),
    ],
)
def test_extra_payload_prompt_and_metadata_escape_fields_are_rejected(target, field):
    payload = _decision_payload()
    selected = {
        "artifact": payload,
        "judgment": payload["judgment"],
        "basis": payload["judgment"]["relevance_bases"][0],
        "evaluator": payload["evaluator"],
        "profile": payload["lens_profile"],
        "criterion": payload["judgment"]["criterion_results"][0],
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
        artifact.lens_profile,
        artifact.evaluator,
        artifact.judgment,
        artifact.judgment.relevance_bases[0],
        artifact.judgment.criterion_results[0],
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
        lens_profile=_lens_profile(),
    )
    assert first == second == restored.canonical_bytes()
    assert restored == artifact
    dumped = json.loads(first)
    assert dumped == artifact.model_dump(mode="json")
    assert dumped["lens_profile"] == _lens_profile().model_dump(mode="json")
    assert dumped["judgment"]["criterion_results"][0]["criterion_id"] == "nb-supported-mechanism"


def test_strict_json_reload_cannot_bypass_proceed_invariants():
    payload = _decision_payload(basis_type="analogy_only")
    with pytest.raises(ValidationError, match="analogy-only"):
        DecisionLensDecisionArtifact.validate_json_for_research(
            json.dumps(payload),
            research=_research(),
            audience=_audience(),
            configuration_identity=_identity(),
            lens_profile=_lens_profile(),
        )


# --- Correction Authorization: lens profile identity ---


def test_missing_or_blank_lens_profile_identity_is_rejected():
    payload = _decision_payload()
    del payload["lens_profile"]
    with pytest.raises(ValidationError):
        DecisionLensDecisionArtifact.model_validate(payload)
    payload = _decision_payload()
    payload["lens_profile"]["lens_profile_id"] = ""
    with pytest.raises(ValidationError):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_malformed_lens_profile_identity_rejects_embedded_profile_content():
    payload = _decision_payload()
    payload["lens_profile"]["prompt"] = "full profile prompt text"
    with pytest.raises(ValidationError):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_unexpected_lens_profile_identity_is_rejected_at_the_boundary():
    payload = _decision_payload()
    payload["lens_profile"] = {
        "lens_profile_id": "other-business-lens",
        "lens_profile_version": "1.0",
    }
    with pytest.raises(DecisionContractError, match="lens profile identity mismatch"):
        _validate(payload)


def test_lens_profile_drift_cannot_bypass_direct_construction_or_strict_reload():
    payload = _decision_payload()
    payload["lens_profile"]["lens_profile_version"] = "9.9"
    artifact = DecisionLensDecisionArtifact.model_validate(payload)
    with pytest.raises(DecisionContractError, match="lens profile identity mismatch"):
        _validate(artifact)
    with pytest.raises(DecisionContractError, match="lens profile identity mismatch"):
        DecisionLensDecisionArtifact.validate_json_for_research(
            artifact.canonical_json(),
            research=_research(),
            audience=_audience(),
            configuration_identity=_identity(),
            lens_profile=_lens_profile(),
        )


# --- Correction Authorization: profile-defined criterion results ---


def test_duplicate_criterion_ids_are_rejected():
    payload = _decision_payload()
    item = payload["judgment"]["criterion_results"][0]
    payload["judgment"]["criterion_results"] = [item, dict(item)]
    with pytest.raises(ValidationError, match="criterion result IDs must be unique"):
        DecisionLensDecisionArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["source_ids", "evidence_ids"])
def test_dangling_criterion_references_are_rejected(field):
    payload = _decision_payload()
    payload["judgment"]["criterion_results"][0][field] = ["missing-reference"]
    with pytest.raises(ValidationError, match="undeclared decision"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_cross_kind_criterion_reference_collision_is_rejected():
    payload = _decision_payload()
    payload["judgment"]["criterion_results"][0]["evidence_ids"] = ["source-sba"]
    with pytest.raises(ValidationError, match="undeclared decision evidence"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_criterion_cannot_cite_research_ids_outside_the_declared_decision_set():
    research_payload = _research_payload()
    research_payload["sources"].append({
        "source_id": "source-extra",
        "locator": {"kind": "url", "value": "https://example.test/extra"},
        "title": "Additional current-run source",
        "publisher": "Example",
        "publication_time": {"status": "unknown", "value": None},
        "retrieved_at": "2026-08-14T12:00:01Z",
    })
    research_payload["evidence"].append({
        "evidence_id": "evidence-extra",
        "claim": "An additional accepted claim exists in the current run.",
        "source_ids": ["source-extra"],
        "support": [{
            "source_id": "source-extra",
            "excerpt": "Additional supporting excerpt.",
            "location": "page 2",
        }],
        "disposition": "accepted",
    })
    research = NormalizedResearchArtifact.model_validate(research_payload)
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    payload["judgment"]["criterion_results"][0]["evidence_ids"] = [
        "evidence-smb",
        "evidence-extra",
    ]
    with pytest.raises(ValidationError, match="undeclared decision evidence"):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_satisfied_criterion_requires_cited_evidence():
    payload = _decision_payload()
    payload["judgment"]["criterion_results"][0]["evidence_ids"] = []
    payload["judgment"]["criterion_results"][0]["source_ids"] = []
    with pytest.raises(ValidationError, match="satisfied criterion requires cited evidence"):
        DecisionLensDecisionArtifact.model_validate(payload)


# --- Correction Authorization: one schema, many business profiles ---


def _contrasting_profile_payloads():
    """A non-small-business lens profile expressed through the same canonical schema."""

    audience = AudienceSelection(
        audience_id="hospital-quality-director",
        audience_name="Hospital quality and safety director",
        selected_problem="Prioritizing safety interventions under regulatory scrutiny.",
        decision_factors=("patient outcomes", "compliance exposure"),
        objections=("generic consulting frameworks",),
        selection_source="configured-default",
    )
    identity = ConfigurationIdentity(
        schema_version="1",
        configuration_id="clinical-quality-production",
        configuration_version="1.0",
        configuration_hash="sha256:" + "c" * 64,
    )
    profile = DecisionLensProfileIdentity(
        lens_profile_id="clinical-quality-lens",
        lens_profile_version="1.0",
    )
    research_payload = _research_payload()
    research_payload["configuration_identity"] = identity.model_dump(mode="json")
    research_payload["sources"][0].update({
        "source_id": "source-outcomes",
        "locator": {"kind": "url", "value": "https://outcomes.example/report"},
        "title": "Hospital safety intervention outcomes",
        "publisher": "Clinical outcomes research group",
    })
    research_payload["evidence"][0].update({
        "evidence_id": "evidence-clinical",
        "claim": "Quality directors report intervention prioritization as a material constraint.",
        "source_ids": ["source-outcomes"],
    })
    research_payload["evidence"][0]["support"][0]["source_id"] = "source-outcomes"
    research = NormalizedResearchArtifact.model_validate(research_payload)

    payload = _decision_payload()
    payload["configuration_identity"] = identity.model_dump(mode="json")
    payload["audience_selection"] = audience.model_dump(mode="json")
    payload["lens_profile"] = profile.model_dump(mode="json")
    payload["research_digest"] = research_artifact_digest(research)
    payload["source_ids"] = ["source-outcomes"]
    payload["evidence_ids"] = ["evidence-clinical"]
    judgment = payload["judgment"]
    judgment["audience_problem_or_opportunity"] = (
        "Choose the safety intervention with the strongest outcome evidence."
    )
    judgment["relevance_bases"] = [{
        "basis_type": "direct_audience_evidence",
        "audience_id": audience.audience_id,
        "statement": "The cited outcomes research directly concerns hospital quality directors.",
        "evidence_ids": ["evidence-clinical"],
        "source_ids": ["source-outcomes"],
        "documented_direct_consequence": None,
    }]
    judgment["criterion_results"] = [{
        "criterion_id": "clinical-outcome-support",
        "assessment": "satisfied",
        "conclusion": "The cited research supports a defensible intervention priority.",
        "evidence_ids": ["evidence-clinical"],
        "source_ids": ["source-outcomes"],
        "restrictions": [],
    }]
    return payload, research, audience, identity, profile


def test_non_small_business_audience_with_direct_evidence_can_proceed():
    payload, research, audience, identity, profile = _contrasting_profile_payloads()
    decision = _validate(
        payload,
        research=research,
        audience=audience,
        identity=identity,
        lens_profile=profile,
    )
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.lens_profile == profile


def test_profiles_use_different_criterion_ids_through_one_schema():
    never_blank = _validate()
    payload, research, audience, identity, profile = _contrasting_profile_payloads()
    contrasting = _validate(
        payload,
        research=research,
        audience=audience,
        identity=identity,
        lens_profile=profile,
    )
    nb_ids = {item.criterion_id for item in never_blank.judgment.criterion_results}
    other_ids = {item.criterion_id for item in contrasting.judgment.criterion_results}
    assert nb_ids and other_ids and not (nb_ids & other_ids)
    assert type(never_blank) is type(contrasting)
    assert set(type(never_blank).model_fields) == set(type(contrasting).model_fields)


def test_universal_contract_has_no_business_specific_names():
    import inspect

    import src.editorial.decision_contract as module

    source = inspect.getsource(module).lower()
    forbidden_terms = (
        "small business",
        "small-business",
        "small_business",
        "smallbusiness",
        "never blank",
        "never_blank",
        "neverblank",
        "sba",
        "census",
        "toyota",
        "nike",
        "owner presence",
        "owner_presence",
        "customer memory",
        "customer_memory",
        "compound presence",
        "compound_presence",
    )
    for term in forbidden_terms:
        assert term not in source, f"business-specific term {term!r} in universal contract"


# --- Review follow-up: exact criterion source/evidence citation integrity ---


def test_satisfied_criterion_with_evidence_but_no_sources_is_rejected():
    payload = _decision_payload()
    payload["judgment"]["criterion_results"][0]["source_ids"] = []
    with pytest.raises(
        ValidationError, match="citing evidence must cite its supporting sources"
    ):
        DecisionLensDecisionArtifact.model_validate(payload)


def test_criterion_source_declared_in_artifact_but_not_supporting_its_evidence_is_rejected():
    research_payload = _research_payload()
    research_payload["sources"].append({
        "source_id": "source-extra",
        "locator": {"kind": "url", "value": "https://example.test/extra"},
        "title": "Additional current-run source",
        "publisher": "Example",
        "publication_time": {"status": "unknown", "value": None},
        "retrieved_at": "2026-08-14T12:00:01Z",
    })
    research_payload["evidence"].append({
        "evidence_id": "evidence-extra",
        "claim": "An additional accepted claim exists in the current run.",
        "source_ids": ["source-extra"],
        "support": [{
            "source_id": "source-extra",
            "excerpt": "Additional supporting excerpt.",
            "location": "page 2",
        }],
        "disposition": "accepted",
    })
    research = NormalizedResearchArtifact.model_validate(research_payload)
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    payload["source_ids"] = ["source-sba", "source-extra"]
    payload["evidence_ids"] = ["evidence-smb", "evidence-extra"]
    # The criterion cites only evidence-smb (supported by source-sba alone) but
    # borrows source-extra, which is declared at the artifact level yet does not
    # support the criterion's cited evidence.
    payload["judgment"]["criterion_results"][0]["source_ids"] = [
        "source-sba",
        "source-extra",
    ]
    with pytest.raises(
        DecisionContractError,
        match="criterion source IDs must exactly match the sources supporting",
    ):
        _validate(payload, research=research)


def test_criterion_sources_without_cited_evidence_are_rejected():
    payload = _decision_payload()
    payload["judgment"]["criterion_results"][0]["assessment"] = "uncertain"
    payload["judgment"]["criterion_results"][0]["evidence_ids"] = []
    with pytest.raises(
        ValidationError, match="citing sources must cite the evidence they support"
    ):
        DecisionLensDecisionArtifact.model_validate(payload)


# --- Final correction: exact relevance-basis source/evidence lineage ---


def _two_source_research() -> NormalizedResearchArtifact:
    """Profile-neutral research with two independent evidence/source pairs."""

    research_payload = _research_payload()
    research_payload["sources"].append({
        "source_id": "source-second",
        "locator": {"kind": "url", "value": "https://example.test/second"},
        "title": "Second independent current-run source",
        "publisher": "Example",
        "publication_time": {"status": "unknown", "value": None},
        "retrieved_at": "2026-08-14T12:00:01Z",
    })
    research_payload["evidence"].append({
        "evidence_id": "evidence-second",
        "claim": "A second accepted claim supported only by the second source.",
        "source_ids": ["source-second"],
        "support": [{
            "source_id": "source-second",
            "excerpt": "Second supporting excerpt.",
            "location": "page 4",
        }],
        "disposition": "accepted",
    })
    return NormalizedResearchArtifact.model_validate(research_payload)


def _two_source_decision_payload(research: NormalizedResearchArtifact) -> dict:
    payload = _decision_payload()
    payload["research_digest"] = research_artifact_digest(research)
    payload["source_ids"] = ["source-sba", "source-second"]
    payload["evidence_ids"] = ["evidence-smb", "evidence-second"]
    payload["judgment"]["criterion_results"][0]["evidence_ids"] = [
        "evidence-smb",
        "evidence-second",
    ]
    payload["judgment"]["criterion_results"][0]["source_ids"] = [
        "source-sba",
        "source-second",
    ]
    return payload


def test_relevance_basis_borrowing_declared_but_unsupporting_source_is_rejected():
    research = _two_source_research()
    payload = _two_source_decision_payload(research)
    # The basis cites only evidence-smb (supported by source-sba alone) but
    # borrows source-second, which the artifact legitimately declares yet which
    # does not support the basis's cited evidence.
    payload["judgment"]["relevance_bases"][0]["evidence_ids"] = ["evidence-smb"]
    payload["judgment"]["relevance_bases"][0]["source_ids"] = [
        "source-sba",
        "source-second",
    ]
    with pytest.raises(
        DecisionContractError,
        match="relevance basis source IDs must exactly match the sources supporting",
    ):
        _validate(payload, research=research)


def test_relevance_basis_with_exactly_supporting_sources_passes():
    research = _two_source_research()
    payload = _two_source_decision_payload(research)
    # The artifact declares two sources, but the basis cites one evidence record
    # and exactly the one source supporting it — per-basis exactness, not
    # artifact-wide subset membership.
    payload["judgment"]["relevance_bases"][0]["evidence_ids"] = ["evidence-smb"]
    payload["judgment"]["relevance_bases"][0]["source_ids"] = ["source-sba"]
    decision = _validate(payload, research=research)
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.judgment.relevance_bases[0].source_ids == ("source-sba",)


def test_strict_json_reload_cannot_bypass_relevance_basis_exact_match():
    research = _two_source_research()
    payload = _two_source_decision_payload(research)
    payload["judgment"]["relevance_bases"][0]["evidence_ids"] = ["evidence-smb"]
    payload["judgment"]["relevance_bases"][0]["source_ids"] = [
        "source-sba",
        "source-second",
    ]
    with pytest.raises(
        DecisionContractError,
        match="relevance basis source IDs must exactly match the sources supporting",
    ):
        DecisionLensDecisionArtifact.validate_json_for_research(
            json.dumps(payload),
            research=research,
            audience=_audience(),
            configuration_identity=_identity(),
            lens_profile=_lens_profile(),
        )


# ── Issue #127: the editorial claim mode ─────────────────────────────────────
#
# The contract judged how relevant the evidence is to the audience, and could
# not express how the article intends to speak about them. An honest piece —
# reporting a verified external case, saying plainly it does not transfer, and
# asking the audience a bounded question — was indistinguishable from one
# asserting the outcome as theirs, so it could never PROCEED.
#
# Declaring the mode separates those. It grants nothing on its own: it relaxes
# only the relevance requirement, and every evidence guarantee holds in both.


def _bounded_payload(*, relevance="indirect", basis_type="documented_direct_impact",
                     disposition="proceed") -> dict:
    """An Invisalign-shaped case: external facts, bounded audience treatment."""

    payload = _decision_payload(disposition=disposition, basis_type=basis_type)
    j = payload["judgment"]
    j["claim_mode"] = "bounded_external_case"
    j["relevance"] = relevance
    j["why_signal_matters"] = (
        "A documented campaign mechanism raises a presence question for the audience."
    )
    j["supported_editorial_angle"] = (
        "The cited case reports its own result; it does not establish the same "
        "outcome for the configured audience. It raises a bounded question about "
        "the distance between attention and a first meaningful action."
    )
    j["relevance_bases"][0]["statement"] = (
        "The cited evidence documents a mechanism in another organization's "
        "context. It is not evidence about the configured audience."
    )
    j["restrictions"] = [
        "Do not assert that the external outcome transfers to the configured audience."
    ]
    return payload


# A. direct evidence + direct mode — unchanged

def test_case_a_direct_claim_with_direct_relevance_still_proceeds():
    decision = _validate(_decision_payload())
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.judgment.claim_mode is EditorialClaimMode.DIRECT_AUDIENCE_CLAIM
    assert decision.judgment.relevance is BusinessAudienceRelevance.DIRECT


# B. external case + bounded mode — the newly reachable path

def test_case_b_bounded_external_case_may_proceed_on_indirect_relevance():
    decision = _validate(_bounded_payload())
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.judgment.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE
    assert decision.judgment.relevance is BusinessAudienceRelevance.INDIRECT
    # the external context is preserved and the transfer explicitly refused
    assert "does not establish" in decision.judgment.supported_editorial_angle
    assert decision.judgment.restrictions


# C. same evidence, direct mode — must not proceed

def test_case_c_the_same_external_evidence_cannot_proceed_as_a_direct_claim():
    payload = _bounded_payload()
    payload["judgment"]["claim_mode"] = "direct_audience_claim"
    with pytest.raises(ValidationError, match="direct audience relevance"):
        _validate(payload)


# D. analogy alone — non-qualifying in BOTH modes

def test_case_d_analogy_alone_cannot_proceed_even_in_bounded_mode():
    payload = _bounded_payload(basis_type="analogy_only")
    with pytest.raises(ValidationError, match="analogy-only"):
        _validate(payload)


def test_case_d_analogy_alone_still_cannot_proceed_in_direct_mode():
    payload = _decision_payload(basis_type="analogy_only")
    with pytest.raises(ValidationError):
        _validate(payload)


# E. irrelevant evidence — never, in either mode

def test_case_e_irrelevant_evidence_cannot_proceed_in_bounded_mode():
    payload = _bounded_payload(relevance="irrelevant")
    with pytest.raises(ValidationError, match="relevant to the configured audience"):
        _validate(payload)


def test_case_e_irrelevant_evidence_cannot_proceed_in_direct_mode():
    payload = _decision_payload()
    payload["judgment"]["relevance"] = "irrelevant"
    with pytest.raises(ValidationError, match="direct audience relevance"):
        _validate(payload)


# F. unsupported interpretation — citation rules unchanged by the mode

def test_case_f_bounded_mode_does_not_relax_citation_requirements():
    payload = _bounded_payload()
    payload["evidence_ids"] = []
    with pytest.raises(ValidationError):
        _validate(payload)


def test_case_f_bounded_mode_cannot_cite_undeclared_evidence():
    payload = _bounded_payload()
    payload["judgment"]["relevance_bases"][0]["evidence_ids"] = ["evidence-invented"]
    with pytest.raises(ValidationError):
        _validate(payload)


# G. serialization, reload, provenance

def test_case_g_bounded_mode_survives_strict_serialization_and_reload():
    decision = _validate(_bounded_payload())
    raw = decision.model_dump_json()
    assert '"claim_mode":"bounded_external_case"' in raw.replace(" ", "")
    back = DecisionLensDecisionArtifact.model_validate_json(raw)
    assert back.judgment.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE
    assert back.judgment.relevance is BusinessAudienceRelevance.INDIRECT
    assert back.model_dump_json() == raw


# H. artifacts predating the field keep their meaning

def test_case_h_a_judgment_without_a_claim_mode_defaults_to_direct():
    payload = _decision_payload()
    payload["judgment"].pop("claim_mode", None)
    decision = _validate(payload)
    assert decision.judgment.claim_mode is EditorialClaimMode.DIRECT_AUDIENCE_CLAIM


def test_case_h_a_pre_existing_indirect_judgment_still_cannot_proceed():
    """The default must not quietly widen what old artifacts were allowed."""

    payload = _decision_payload()
    payload["judgment"].pop("claim_mode", None)
    payload["judgment"]["relevance"] = "indirect"
    with pytest.raises(ValidationError, match="direct audience relevance"):
        _validate(payload)


# I. the mode is profile-agnostic

def test_case_i_a_contrasting_profile_uses_the_same_mode_without_code_changes():
    other = DecisionLensProfileIdentity(
        lens_profile_id="clinical-quality-lens", lens_profile_version="2.0"
    )
    payload = _bounded_payload()
    payload["lens_profile"] = other.model_dump(mode="json")
    decision = _validate(payload, lens_profile=other)
    assert decision.judgment.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE
    assert decision.lens_profile == other


# ── blocking review: the bounded promise must be collected on ────────────────
#
# Bounded mode trades the DIRECT-relevance requirement for a promise about how
# the article will speak about the audience. The first implementation declared
# that promise and never collected on it: selecting the mode was enough, so a
# judgment could assert outright transfer in prose, carry no restrictions, and
# still PROCEED at INDIRECT relevance — the exact form the authorization
# forbade.
#
# The contract cannot read prose, and does not try to. It requires the
# judgment to record the boundary it binds itself to, which is auditable
# afterwards. Whether the generated article honours that boundary is
# editorial acceptance's question, not this one.


def test_bounded_mode_without_restrictions_cannot_proceed():
    payload = _bounded_payload()
    payload["judgment"]["restrictions"] = []
    with pytest.raises(ValidationError, match="explicit restriction"):
        _validate(payload)


@pytest.mark.parametrize("blank", [[""], ["   "], ["\t"], ["", "  "]])
def test_bounded_mode_with_blank_restrictions_cannot_proceed(blank):
    """A restriction that says nothing is not a boundary."""

    payload = _bounded_payload()
    payload["judgment"]["restrictions"] = blank
    with pytest.raises(ValidationError):
        _validate(payload)


def test_the_forbidden_transfer_form_no_longer_proceeds():
    """The blocking review's reproduction, held closed.

    An angle asserting that the external outcome applies to the audience,
    with no recorded boundary, previously validated as PROCEED.
    """

    payload = _bounded_payload()
    payload["judgment"]["supported_editorial_angle"] = (
        "The external case documents a 30% lift, therefore the configured "
        "audience will improve conversion by doing the same."
    )
    payload["judgment"]["restrictions"] = []
    with pytest.raises(ValidationError, match="explicit restriction"):
        _validate(payload)


def test_bounded_mode_with_an_explicit_restriction_may_proceed():
    payload = _bounded_payload()
    payload["judgment"]["restrictions"] = [
        "Do not assert that the external outcome transfers to the configured audience."
    ]
    decision = _validate(payload)
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.judgment.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE
    assert decision.judgment.relevance is BusinessAudienceRelevance.INDIRECT
    assert any(r.strip() for r in decision.judgment.restrictions)


def test_the_recorded_boundary_survives_strict_reload():
    """The boundary must be auditable after the fact, not only at validation."""

    decision = _validate(_bounded_payload())
    back = DecisionLensDecisionArtifact.model_validate_json(decision.model_dump_json())
    assert any(r.strip() for r in back.judgment.restrictions)
    assert back.judgment.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE


def test_direct_mode_does_not_acquire_a_restriction_requirement():
    """The new requirement belongs to bounded mode alone."""

    payload = _decision_payload()
    payload["judgment"]["restrictions"] = []
    decision = _validate(payload)
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.judgment.claim_mode is EditorialClaimMode.DIRECT_AUDIENCE_CLAIM


def test_a_legacy_judgment_without_claim_mode_needs_no_restrictions():
    payload = _decision_payload()
    payload["judgment"].pop("claim_mode", None)
    payload["judgment"]["restrictions"] = []
    assert _validate(payload).disposition is DecisionDisposition.PROCEED


def test_a_restriction_cannot_rescue_analogy_only_in_bounded_mode():
    """The boundary is not a substitute for a documented mechanism."""

    payload = _bounded_payload(basis_type="analogy_only")
    payload["judgment"]["restrictions"] = ["Do not assert transfer."]
    with pytest.raises(ValidationError, match="analogy-only"):
        _validate(payload)


def test_a_restriction_cannot_rescue_irrelevant_evidence():
    payload = _bounded_payload(relevance="irrelevant")
    payload["judgment"]["restrictions"] = ["Do not assert transfer."]
    with pytest.raises(ValidationError, match="relevant to the configured audience"):
        _validate(payload)


def test_a_restriction_cannot_rescue_missing_citations():
    payload = _bounded_payload()
    payload["judgment"]["restrictions"] = ["Do not assert transfer."]
    payload["evidence_ids"] = []
    with pytest.raises(ValidationError):
        _validate(payload)
