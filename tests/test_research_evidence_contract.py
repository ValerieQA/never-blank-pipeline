"""Focused contract tests for Issue #50; intentionally no provider wiring."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.research.evidence import (
    Contradiction,
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    ModelInterpretation,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    ResolutionStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
    UncertaintyAssessment,
    UncertaintyLevel,
    UncertaintyMateriality,
)
from src.strategy.execution_context import ConfigurationIdentity


UTC = timezone.utc
RUN_ID = "12345678-1234-4234-8234-123456789abc"


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": "research-001",
        "run_id": RUN_ID,
        "assignment_id": "assignment-001",
        "signal_id": "signal-001",
        "configuration_identity": {
            "configuration_id": "never-blank-production",
            "configuration_version": "2.0",
            "schema_version": "1",
            "configuration_hash": "sha256:" + "a" * 64,
        },
        "created_at": "2026-08-13T20:00:00Z",
        "sources": [
            {
                "source_id": "source-a",
                "locator": {"kind": "url", "value": "https://example.test/a"},
                "title": "Published source",
                "publisher": "Example",
                "publication_time": {
                    "status": "known",
                    "value": "2026-08-12T09:30:00Z",
                },
                "retrieved_at": "2026-08-13T19:00:00Z",
            },
            {
                "source_id": "source-b",
                "locator": {"kind": "identifier", "value": "catalogue:b"},
                "title": "Undated source",
                "publisher": None,
                "publication_time": {"status": "unknown", "value": None},
                "retrieved_at": "2026-08-13T19:05:00Z",
            },
        ],
        "evidence": [
            {
                "evidence_id": "evidence-a",
                "claim": "The source reports a bounded observation.",
                "source_ids": ["source-a"],
                "support": [{
                    "source_id": "source-a",
                    "excerpt": "A bounded source-derived excerpt.",
                    "location": "section 2",
                }],
                "disposition": "qualified",
            },
            {
                "evidence_id": "evidence-b",
                "claim": "A second source reports a conflicting observation.",
                "source_ids": ["source-b"],
                "support": [{
                    "source_id": "source-b",
                    "excerpt": "A conflicting bounded excerpt.",
                    "location": None,
                }],
                "disposition": "conflicting",
            },
        ],
        "interpretations": [{
            "interpretation_id": "interpretation-a",
            "statement": "The model interprets the difference as context-dependent.",
            "evidence_ids": ["evidence-a", "evidence-b"],
        }],
        "uncertainties": [{
            "uncertainty_id": "uncertainty-a",
            "level": "medium",
            "materiality": "material",
            "resolution": "unresolved",
            "description": "The second source has no known publication time.",
            "evidence_ids": ["evidence-b"],
            "source_ids": ["source-b"],
        }],
        "contradictions": [{
            "contradiction_id": "contradiction-a",
            "resolution": "unresolved",
            "description": "The observations conflict.",
            "evidence_ids": ["evidence-a", "evidence-b"],
            "source_ids": [],
        }],
        "readiness": "needs_review",
    }


def _artifact() -> NormalizedResearchArtifact:
    return NormalizedResearchArtifact.model_validate(_payload())


def _ready_payload() -> dict:
    payload = _payload()
    payload["evidence"] = [payload["evidence"][0]]
    payload["evidence"][0]["disposition"] = "accepted"
    payload["interpretations"][0]["evidence_ids"] = ["evidence-a"]
    payload["uncertainties"] = []
    payload["contradictions"] = []
    payload["readiness"] = "ready"
    return payload


def test_valid_complete_artifact_preserves_complete_identity():
    artifact = _artifact()
    assert artifact.configuration_identity == ConfigurationIdentity(**_payload()["configuration_identity"])
    assert artifact.run_id == RUN_ID
    assert artifact.assignment_id == "assignment-001"
    assert artifact.signal_id == "signal-001"
    assert artifact.readiness is EvidenceReadiness.NEEDS_REVIEW


def test_all_contract_models_are_immutable():
    artifact = _artifact()
    models = [
        artifact,
        artifact.sources[0],
        artifact.sources[0].locator,
        artifact.sources[0].publication_time,
        artifact.evidence[0],
        artifact.evidence[0].support[0],
        artifact.interpretations[0],
        artifact.uncertainties[0],
        artifact.contradictions[0],
    ]
    for model in models:
        field = next(iter(type(model).model_fields))
        with pytest.raises(ValidationError):
            setattr(model, field, getattr(model, field))


@pytest.mark.parametrize("target", ["artifact", "source", "evidence", "interpretation"])
def test_extra_fields_are_rejected_at_every_boundary(target: str):
    payload = _payload()
    selected = {
        "artifact": payload,
        "source": payload["sources"][0],
        "evidence": payload["evidence"][0],
        "interpretation": payload["interpretations"][0],
    }[target]
    selected["raw_payload"] = {"provider": "forbidden"}
    with pytest.raises(ValidationError):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("sources", 0, "publication_time", "status"), "maybe"),
        (("evidence", 0, "disposition"), "useful"),
        (("uncertainties", 0, "level"), "guess"),
        (("uncertainties", 0, "materiality"), "possibly_material"),
        (("uncertainties", 0, "resolution"), "partly_resolved"),
        (("contradictions", 0, "resolution"), "ignored"),
        (("readiness",), "publish"),
    ],
)
def test_invalid_enum_status_is_rejected(path: tuple, invalid: str):
    payload = _payload()
    current = payload
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = invalid
    with pytest.raises(ValidationError):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["created_at", "retrieved_at", "publication_time"])
@pytest.mark.parametrize(
    "timestamp",
    [datetime(2026, 8, 13, 12), datetime(2026, 8, 13, 12, tzinfo=timezone(timedelta(hours=2)))],
)
def test_naive_and_non_utc_timestamps_are_rejected(field: str, timestamp: datetime):
    payload = _payload()
    if field == "created_at":
        payload[field] = timestamp
    elif field == "retrieved_at":
        payload["sources"][0][field] = timestamp
    else:
        payload["sources"][0]["publication_time"]["value"] = timestamp
    with pytest.raises(ValidationError):
        NormalizedResearchArtifact.model_validate(payload)


def test_missing_retrieval_timestamp_is_rejected():
    payload = _payload()
    del payload["sources"][0]["retrieved_at"]
    with pytest.raises(ValidationError):
        NormalizedResearchArtifact.model_validate(payload)


def test_unknown_not_collected_and_known_publication_states_are_distinct():
    known = PublicationTime(status="known", value=datetime(2026, 8, 13, tzinfo=UTC))
    unknown = PublicationTime(status="unknown")
    not_collected = PublicationTime(status="not_collected")
    assert len({known.status, unknown.status, not_collected.status}) == 3
    assert unknown.value is None and not_collected.value is None
    with pytest.raises(ValidationError):
        PublicationTime(status="known")
    with pytest.raises(ValidationError):
        PublicationTime(status="unknown", value=datetime(2026, 8, 13, tzinfo=UTC))


@pytest.mark.parametrize(
    ("collection", "id_field"),
    [
        ("sources", "source_id"),
        ("evidence", "evidence_id"),
        ("interpretations", "interpretation_id"),
        ("uncertainties", "uncertainty_id"),
        ("contradictions", "contradiction_id"),
    ],
)
def test_duplicate_ids_are_rejected(collection: str, id_field: str):
    payload = _payload()
    payload[collection].append(dict(payload[collection][0]))
    with pytest.raises(ValidationError, match="duplicate"):
        NormalizedResearchArtifact.model_validate(payload)


ENTITY_IDS = {
    "sources": "source_id",
    "evidence": "evidence_id",
    "interpretations": "interpretation_id",
    "uncertainties": "uncertainty_id",
    "contradictions": "contradiction_id",
}


@pytest.mark.parametrize(
    ("first_kind", "second_kind"),
    [
        ("sources", "evidence"),
        ("sources", "interpretations"),
        ("sources", "uncertainties"),
        ("sources", "contradictions"),
        ("evidence", "interpretations"),
        ("evidence", "uncertainties"),
        ("evidence", "contradictions"),
        ("interpretations", "uncertainties"),
        ("interpretations", "contradictions"),
        ("uncertainties", "contradictions"),
    ],
)
def test_cross_kind_id_collisions_are_rejected(first_kind: str, second_kind: str):
    payload = _payload()
    shared_id = payload[first_kind][0][ENTITY_IDS[first_kind]]
    payload[second_kind][0][ENTITY_IDS[second_kind]] = shared_id
    with pytest.raises(ValidationError, match="reused"):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("referenced_kind", "referenced_id"),
    [("evidence_ids", "evidence-a"), ("source_ids", "source-a")],
)
def test_contradiction_id_cannot_equal_a_referenced_entity(
    referenced_kind: str, referenced_id: str
):
    payload = _payload()
    contradiction = payload["contradictions"][0]
    contradiction["contradiction_id"] = referenced_id
    if referenced_kind == "source_ids":
        contradiction["source_ids"] = ["source-a"]
    with pytest.raises(ValidationError, match="reused"):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["evidence"][0].update(source_ids=["missing-source"]),
        lambda p: p["evidence"][0]["support"][0].update(source_id="missing-source"),
        lambda p: p["interpretations"][0].update(evidence_ids=["missing-evidence"]),
        lambda p: p["uncertainties"][0].update(source_ids=["missing-source"]),
    ],
)
def test_missing_source_or_evidence_references_are_rejected(mutation):
    payload = _payload()
    mutation(payload)
    with pytest.raises(ValidationError, match="missing|declared"):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize("field", ["evidence_ids", "source_ids"])
def test_contradictions_with_invalid_references_are_rejected(field: str):
    payload = _payload()
    payload["contradictions"][0][field] = ["missing", "also-missing"]
    with pytest.raises(ValidationError, match="missing"):
        NormalizedResearchArtifact.model_validate(payload)


def test_source_evidence_and_model_interpretation_are_structurally_separate():
    artifact = _artifact()
    assert isinstance(artifact.evidence[0], ExtractedEvidence)
    assert isinstance(artifact.interpretations[0], ModelInterpretation)
    assert "statement" not in ExtractedEvidence.model_fields
    assert "claim" not in ModelInterpretation.model_fields
    payload = _payload()
    payload["evidence"][0]["interpretation"] = "mixed"
    with pytest.raises(ValidationError):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize(
    "leak",
    [
        {"raw_payload": {"choices": []}},
        {"provider_response": object()},
        {"credentials": {"api_key": "secret"}},
    ],
)
def test_provider_payload_sdk_object_and_credential_fields_are_rejected(leak: dict):
    payload = _payload()
    payload.update(leak)
    with pytest.raises(ValidationError):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize(
    "credential_text",
    ["api_key=top-secret-value", "Authorization: Bearer token-value", "sk-abcdefghijklmnop"],
)
def test_credential_shaped_text_leakage_is_rejected(credential_text: str):
    payload = _payload()
    payload["evidence"][0]["support"][0]["excerpt"] = credential_text
    with pytest.raises(ValidationError, match="credential-shaped"):
        NormalizedResearchArtifact.model_validate(payload)


def test_deterministic_lossless_serialization_round_trip():
    artifact = _artifact()
    first = artifact.canonical_json()
    second = artifact.canonical_json()
    restored = NormalizedResearchArtifact.model_validate_json(first)
    assert first == second
    assert restored == artifact
    assert restored.canonical_bytes() == artifact.canonical_bytes()
    assert json.loads(first) == artifact.model_dump(mode="json")


def test_ready_requires_evidence():
    payload = _ready_payload()
    payload["evidence"] = []
    payload["interpretations"] = []
    with pytest.raises(ValidationError, match="READY requires"):
        NormalizedResearchArtifact.model_validate(payload)


@pytest.mark.parametrize("disposition", ["not_assessed", "conflicting", "rejected"])
def test_ready_rejects_blocking_evidence_dispositions(disposition: str):
    payload = _ready_payload()
    payload["evidence"][0]["disposition"] = disposition
    with pytest.raises(ValidationError, match="blocking evidence dispositions"):
        NormalizedResearchArtifact.model_validate(payload)


def test_ready_rejects_unresolved_contradiction():
    payload = _ready_payload()
    payload["contradictions"] = [{
        "contradiction_id": "contradiction-ready-blocker",
        "resolution": "unresolved",
        "description": "The source and extracted evidence remain inconsistent.",
        "evidence_ids": ["evidence-a"],
        "source_ids": ["source-b"],
    }]
    with pytest.raises(ValidationError, match="unresolved contradictions"):
        NormalizedResearchArtifact.model_validate(payload)


def test_ready_rejects_unresolved_material_uncertainty():
    payload = _ready_payload()
    payload["uncertainties"] = [{
        "uncertainty_id": "uncertainty-ready-blocker",
        "level": "high",
        "materiality": "material",
        "resolution": "unresolved",
        "description": "A material limitation remains unresolved.",
        "evidence_ids": ["evidence-a"],
        "source_ids": [],
    }]
    with pytest.raises(ValidationError, match="unresolved material uncertainties"):
        NormalizedResearchArtifact.model_validate(payload)


def test_partial_unassessed_research_is_accepted_only_as_non_ready():
    payload = _ready_payload()
    payload["evidence"][0]["disposition"] = "not_assessed"
    payload["readiness"] = "insufficient"
    artifact = NormalizedResearchArtifact.model_validate(payload)
    assert artifact.readiness is EvidenceReadiness.INSUFFICIENT
    assert artifact.evidence[0].disposition is EvidenceDisposition.NOT_ASSESSED


def test_conflicting_research_and_unresolved_contradiction_require_non_ready():
    artifact = _artifact()
    assert artifact.readiness is EvidenceReadiness.NEEDS_REVIEW
    assert artifact.evidence[1].disposition is EvidenceDisposition.CONFLICTING
    assert artifact.contradictions[0].resolution is ResolutionStatus.UNRESOLVED


@pytest.mark.parametrize(
    ("materiality", "resolution"),
    [("material", "resolved"), ("non_material", "unresolved")],
)
def test_resolved_or_explicitly_non_material_uncertainty_is_ready_compatible(
    materiality: str, resolution: str
):
    payload = _ready_payload()
    payload["uncertainties"] = [{
        "uncertainty_id": "uncertainty-ready-compatible",
        "level": "low",
        "materiality": materiality,
        "resolution": resolution,
        "description": "This limitation is explicitly classified.",
        "evidence_ids": ["evidence-a"],
        "source_ids": [],
    }]
    artifact = NormalizedResearchArtifact.model_validate(payload)
    assert artifact.readiness is EvidenceReadiness.READY


def test_resolved_contradiction_is_ready_compatible():
    payload = _ready_payload()
    payload["contradictions"] = [{
        "contradiction_id": "contradiction-resolved",
        "resolution": "resolved",
        "description": "The conflict was resolved by bounding the claim.",
        "evidence_ids": ["evidence-a"],
        "source_ids": ["source-b"],
    }]
    artifact = NormalizedResearchArtifact.model_validate(payload)
    assert artifact.readiness is EvidenceReadiness.READY


def test_valid_ready_artifact_has_acceptable_evidence_and_no_blockers():
    artifact = NormalizedResearchArtifact.model_validate(_ready_payload())
    assert artifact.readiness is EvidenceReadiness.READY
    assert artifact.evidence
    assert {item.disposition for item in artifact.evidence} == {
        EvidenceDisposition.ACCEPTED
    }


def test_individual_models_are_strict_and_typed():
    source = NormalizedSource(
        source_id="s",
        locator=SourceLocator(kind=SourceLocatorKind.IDENTIFIER, value="id:s"),
        title="Title",
        publication_time=PublicationTime(status=PublicationTimeStatus.NOT_COLLECTED),
        retrieved_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    evidence = ExtractedEvidence(
        evidence_id="e",
        claim="Fact",
        source_ids=("s",),
        support=(SupportReference(source_id="s", excerpt="Support"),),
        disposition=EvidenceDisposition.NOT_ASSESSED,
    )
    uncertainty = UncertaintyAssessment(
        uncertainty_id="u",
        level=UncertaintyLevel.UNKNOWN,
        materiality=UncertaintyMateriality.MATERIAL,
        resolution=ResolutionStatus.UNRESOLVED,
        description="Not assessed",
        source_ids=("s",),
    )
    contradiction = Contradiction(
        contradiction_id="c",
        resolution=ResolutionStatus.UNRESOLVED,
        description="Two records differ",
        source_ids=("s", "other"),
    )
    assert source.publication_time.status is PublicationTimeStatus.NOT_COLLECTED
    assert evidence.disposition is EvidenceDisposition.NOT_ASSESSED
    assert uncertainty.level is UncertaintyLevel.UNKNOWN
    assert contradiction.source_ids == ("s", "other")


def test_url_locator_rejects_non_url_identifier():
    with pytest.raises(ValidationError, match="absolute HTTP"):
        SourceLocator(kind="url", value="provider-record-123")
