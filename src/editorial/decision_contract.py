"""Immutable canonical contract for one Decision Lens judgment.

The contract stores bounded judgment meaning and references one canonical
current-run research artifact by digest. It contains no prompt, model response,
provider payload, persistence behavior, or orchestration.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedResearchArtifact,
    ResolutionStatus,
    UncertaintyMateriality,
)
from src.strategy.execution_context import AudienceSelection, ConfigurationIdentity


DECISION_LENS_SCHEMA_VERSION = "1.0"
DECISION_RESEARCH_DIGEST_ALGORITHM = "sha256"


class DecisionContractError(ValueError):
    """A decision is inconsistent with its declared meaning or research lineage."""


class _DecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")
    return value


_CREDENTIAL_SHAPE = re.compile(
    r"(?i)(?:authorization\s*:\s*bearer\s+|"
    r"(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password)"
    r"\s*[:=]\s*\S+|\bsk-[A-Za-z0-9_-]{12,})"
)


def _bounded_text(value: str) -> str:
    if _CREDENTIAL_SHAPE.search(value):
        raise ValueError("credential-shaped content is forbidden in decision artifacts")
    return value


class DecisionDisposition(str, Enum):
    PROCEED = "proceed"
    REVISE = "revise"
    HOLD = "hold"
    REJECT = "reject"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class BusinessAudienceRelevance(str, Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    IRRELEVANT = "irrelevant"


class DecisionEvidenceSufficiency(str, Enum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class AudienceRelevanceBasisType(str, Enum):
    DIRECT_AUDIENCE_EVIDENCE = "direct_audience_evidence"
    CLIENT_FIRST_PARTY_EVIDENCE = "client_first_party_evidence"
    DOCUMENTED_DIRECT_IMPACT = "documented_direct_impact"
    CREDIBLE_SECTOR_EVIDENCE = "credible_sector_evidence"
    ANALOGY_ONLY = "analogy_only"


class CriterionAssessment(str, Enum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNCERTAIN = "uncertain"


class EvaluatorKind(str, Enum):
    DECLARED_MODEL = "declared_model"
    DETERMINISTIC_RULE = "deterministic_rule"
    HUMAN_REVIEW = "human_review"


class ResearchConditionKind(str, Enum):
    UNCERTAINTY = "uncertainty"
    CONTRADICTION = "contradiction"


class DecisionConditionTreatment(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    BOUNDED = "bounded"
    RESOLVED = "resolved"
    EXCLUDED_FROM_ANGLE = "excluded_from_angle"


class DecisionEvaluatorAttribution(_DecisionModel):
    evaluator_id: str = Field(min_length=1, max_length=120)
    evaluator_version: str = Field(min_length=1, max_length=80)
    kind: EvaluatorKind

    @field_validator("evaluator_id", "evaluator_version")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _bounded_text(value)


class DecisionLensProfileIdentity(_DecisionModel):
    """Identity of the lens profile whose semantics produced this judgment.

    Profile identity is separate from configuration identity, audience selection,
    evaluator attribution, and the decision artifact schema version. The complete
    profile definition and its prompts are never stored in the artifact.
    """

    lens_profile_id: str = Field(min_length=1, max_length=120)
    lens_profile_version: str = Field(min_length=1, max_length=80)

    @field_validator("lens_profile_id", "lens_profile_version")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _bounded_text(value)


class AudienceRelevanceBasis(_DecisionModel):
    """A typed claim about why cited research directly concerns the configured audience."""

    basis_type: AudienceRelevanceBasisType
    audience_id: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    documented_direct_consequence: str | None = Field(default=None, max_length=1200)

    @field_validator("audience_id", "statement", "documented_direct_consequence")
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        return None if value is None else _bounded_text(value)

    @model_validator(mode="after")
    def _basis_is_structured(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("relevance evidence IDs must be unique")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("relevance source IDs must be unique")
        if (
            self.basis_type is AudienceRelevanceBasisType.DOCUMENTED_DIRECT_IMPACT
            and not self.documented_direct_consequence
        ):
            raise ValueError("documented direct impact requires the direct consequence")
        if (
            self.basis_type is AudienceRelevanceBasisType.ANALOGY_ONLY
            and self.documented_direct_consequence is not None
        ):
            raise ValueError("analogy-only relevance cannot claim a documented direct consequence")
        return self


class DecisionCriterionResult(_DecisionModel):
    """One profile-defined criterion conclusion grounded in cited research.

    Criterion IDs are defined by the applied lens profile, not by this schema.
    The universal contract never enumerates any business's criterion IDs.
    """

    criterion_id: str = Field(min_length=1, max_length=120)
    assessment: CriterionAssessment
    conclusion: str = Field(min_length=1, max_length=2000)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=30)
    source_ids: tuple[str, ...] = Field(default=(), max_length=30)
    restrictions: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("criterion_id", "conclusion")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _bounded_text(value)

    @field_validator("restrictions")
    @classmethod
    def _safe_collection(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("criterion restrictions must be unique")
        return tuple(_bounded_text(value) for value in values)

    @model_validator(mode="after")
    def _criterion_is_structured(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("criterion evidence IDs must be unique")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("criterion source IDs must be unique")
        if self.assessment is CriterionAssessment.SATISFIED and not self.evidence_ids:
            raise ValueError("a satisfied criterion requires cited evidence")
        if self.evidence_ids and not self.source_ids:
            raise ValueError("a criterion citing evidence must cite its supporting sources")
        if self.source_ids and not self.evidence_ids:
            raise ValueError("a criterion citing sources must cite the evidence they support")
        return self


class DecisionResearchConditionHandling(_DecisionModel):
    condition_id: str = Field(min_length=1, max_length=200)
    kind: ResearchConditionKind
    treatment: DecisionConditionTreatment
    explanation: str = Field(min_length=1, max_length=1600)

    @field_validator("condition_id", "explanation")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _bounded_text(value)


class DecisionLensJudgment(_DecisionModel):
    relevance: BusinessAudienceRelevance
    evidence_sufficiency: DecisionEvidenceSufficiency
    why_signal_matters: str = Field(min_length=1, max_length=2000)
    business_value_connection: str = Field(min_length=1, max_length=2000)
    audience_problem_or_opportunity: str = Field(min_length=1, max_length=2000)
    defensible_perspective: str = Field(min_length=1, max_length=3000)
    supported_editorial_angle: str = Field(min_length=1, max_length=2000)
    relevance_bases: tuple[AudienceRelevanceBasis, ...] = Field(
        min_length=1, max_length=12
    )
    criterion_results: tuple[DecisionCriterionResult, ...] = Field(
        default=(), max_length=40
    )
    research_condition_handling: tuple[DecisionResearchConditionHandling, ...] = Field(
        default=(), max_length=30
    )
    restrictions: tuple[str, ...] = Field(default=(), max_length=30)
    disposition_reasons: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator(
        "why_signal_matters",
        "business_value_connection",
        "audience_problem_or_opportunity",
        "defensible_perspective",
        "supported_editorial_angle",
    )
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _bounded_text(value)

    @field_validator("restrictions", "disposition_reasons")
    @classmethod
    def _safe_collection(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("bounded decision text collections must be unique")
        return tuple(_bounded_text(value) for value in values)

    @model_validator(mode="after")
    def _bounded_ids_are_unique(self) -> Self:
        condition_ids = tuple(item.condition_id for item in self.research_condition_handling)
        if len(set(condition_ids)) != len(condition_ids):
            raise ValueError("research condition handling IDs must be unique")
        criterion_ids = tuple(item.criterion_id for item in self.criterion_results)
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("criterion result IDs must be unique")
        return self


class DecisionLensDecisionArtifact(_DecisionModel):
    """Canonical judgment for exactly one run, audience, and research artifact."""

    schema_version: str = DECISION_LENS_SCHEMA_VERSION
    decision_artifact_id: str
    run_id: str
    assignment_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    configuration_identity: ConfigurationIdentity
    audience_selection: AudienceSelection
    lens_profile: DecisionLensProfileIdentity
    research_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision_lens_version: str = Field(min_length=1, max_length=80)
    evaluator: DecisionEvaluatorAttribution
    evaluation_started_at: datetime
    created_at: datetime
    source_ids: tuple[str, ...] = Field(default=(), max_length=100)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)
    judgment: DecisionLensJudgment
    disposition: DecisionDisposition

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != DECISION_LENS_SCHEMA_VERSION:
            raise ValueError(f"unsupported decision schema_version: {value!r}")
        return value

    @field_validator("decision_artifact_id", "run_id")
    @classmethod
    def _uuid4(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(value, version=4)
        except (ValueError, AttributeError) as exc:
            raise ValueError("decision and run IDs must be canonical UUID v4") from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("decision and run IDs must be canonical lowercase UUID v4")
        return value

    @field_validator("assignment_id", "signal_id", "decision_lens_version")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _bounded_text(value)

    @field_validator("evaluation_started_at", "created_at")
    @classmethod
    def _strict_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decision timestamp")

    @model_validator(mode="after")
    def _internal_invariants(self) -> Self:
        if self.created_at < self.evaluation_started_at:
            raise DecisionContractError("decision creation cannot precede evaluation start")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise DecisionContractError("decision source IDs must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DecisionContractError("decision evidence IDs must be unique")
        if set(self.source_ids) & set(self.evidence_ids):
            raise DecisionContractError("source and evidence IDs share one decision namespace")
        for basis in self.judgment.relevance_bases:
            if basis.audience_id != self.audience_selection.audience_id:
                raise DecisionContractError("relevance basis audience does not match selection")
            if not set(basis.source_ids) <= set(self.source_ids):
                raise DecisionContractError("relevance basis cites undeclared decision sources")
            if not set(basis.evidence_ids) <= set(self.evidence_ids):
                raise DecisionContractError("relevance basis cites undeclared decision evidence")
        for criterion in self.judgment.criterion_results:
            if not set(criterion.source_ids) <= set(self.source_ids):
                raise DecisionContractError("criterion result cites undeclared decision sources")
            if not set(criterion.evidence_ids) <= set(self.evidence_ids):
                raise DecisionContractError("criterion result cites undeclared decision evidence")
        if self.disposition is DecisionDisposition.PROCEED:
            if self.judgment.relevance is not BusinessAudienceRelevance.DIRECT:
                raise DecisionContractError("PROCEED requires direct audience relevance")
            if self.judgment.evidence_sufficiency is not DecisionEvidenceSufficiency.SUFFICIENT:
                raise DecisionContractError("PROCEED requires sufficient evidence")
            if not self.source_ids or not self.evidence_ids:
                raise DecisionContractError("PROCEED requires cited source and evidence IDs")
            if all(
                basis.basis_type is AudienceRelevanceBasisType.ANALOGY_ONLY
                for basis in self.judgment.relevance_bases
            ):
                raise DecisionContractError(
                    "PROCEED requires direct configured-audience evidence, "
                    "not analogy-only relevance"
                )
        return self

    @classmethod
    def validate_for_research(
        cls,
        value: "DecisionLensDecisionArtifact | dict",
        *,
        research: NormalizedResearchArtifact,
        audience: AudienceSelection,
        configuration_identity: ConfigurationIdentity,
        lens_profile: DecisionLensProfileIdentity,
    ) -> "DecisionLensDecisionArtifact":
        artifact = value if isinstance(value, cls) else cls.model_validate(value)
        artifact._validate_external_lineage(
            research, audience, configuration_identity, lens_profile
        )
        return artifact

    @classmethod
    def validate_json_for_research(
        cls,
        value: str | bytes,
        *,
        research: NormalizedResearchArtifact,
        audience: AudienceSelection,
        configuration_identity: ConfigurationIdentity,
        lens_profile: DecisionLensProfileIdentity,
    ) -> "DecisionLensDecisionArtifact":
        artifact = cls.model_validate_json(value)
        artifact._validate_external_lineage(
            research, audience, configuration_identity, lens_profile
        )
        return artifact

    def _validate_external_lineage(
        self,
        research: NormalizedResearchArtifact,
        audience: AudienceSelection,
        configuration_identity: ConfigurationIdentity,
        lens_profile: DecisionLensProfileIdentity,
    ) -> None:
        if self.configuration_identity != configuration_identity:
            raise DecisionContractError("decision configuration identity mismatch")
        if self.audience_selection != audience:
            raise DecisionContractError("decision audience selection mismatch")
        if self.lens_profile != lens_profile:
            raise DecisionContractError("decision lens profile identity mismatch")
        if research.configuration_identity != configuration_identity:
            raise DecisionContractError("research configuration identity mismatch")
        if (self.run_id, self.assignment_id, self.signal_id) != (
            research.run_id,
            research.assignment_id,
            research.signal_id,
        ):
            raise DecisionContractError("decision and research execution identity mismatch")
        if self.research_digest != research_artifact_digest(research):
            raise DecisionContractError("decision research digest mismatch")

        sources = {item.source_id for item in research.sources}
        evidence = {item.evidence_id: item for item in research.evidence}
        if not set(self.source_ids) <= sources:
            raise DecisionContractError("decision references unknown research source IDs")
        if not set(self.evidence_ids) <= set(evidence):
            raise DecisionContractError("decision references unknown research evidence IDs")
        evidence_source_ids = {
            source_id
            for evidence_id in self.evidence_ids
            for source_id in evidence[evidence_id].source_ids
        }
        if set(self.source_ids) != evidence_source_ids:
            raise DecisionContractError(
                "decision source IDs must exactly match the cited evidence sources"
            )
        for criterion in self.judgment.criterion_results:
            criterion_evidence_sources = {
                source_id
                for evidence_id in criterion.evidence_ids
                for source_id in evidence[evidence_id].source_ids
            }
            if set(criterion.source_ids) != criterion_evidence_sources:
                raise DecisionContractError(
                    "criterion source IDs must exactly match the sources supporting "
                    "its cited evidence"
                )
        uncertainty_ids = {item.uncertainty_id for item in research.uncertainties}
        contradiction_ids = {item.contradiction_id for item in research.contradictions}
        for handling in self.judgment.research_condition_handling:
            known = (
                uncertainty_ids
                if handling.kind is ResearchConditionKind.UNCERTAINTY
                else contradiction_ids
            )
            if handling.condition_id not in known:
                raise DecisionContractError(
                    "decision handling references an unknown research condition"
                )

        if self.disposition is DecisionDisposition.PROCEED:
            if research.readiness is not EvidenceReadiness.READY:
                raise DecisionContractError("PROCEED requires READY research")
            blockers = {
                EvidenceDisposition.NOT_ASSESSED,
                EvidenceDisposition.CONFLICTING,
                EvidenceDisposition.REJECTED,
            }
            if any(evidence[item].disposition in blockers for item in self.evidence_ids):
                raise DecisionContractError("PROCEED cites blocked research evidence")
            if any(
                item.resolution is ResolutionStatus.UNRESOLVED
                for item in research.contradictions
            ):
                raise DecisionContractError("PROCEED cannot ignore unresolved contradictions")
            if any(
                item.materiality is UncertaintyMateriality.MATERIAL
                and item.resolution is ResolutionStatus.UNRESOLVED
                for item in research.uncertainties
            ):
                raise DecisionContractError("PROCEED cannot ignore material uncertainty")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")


def research_artifact_digest(research: NormalizedResearchArtifact) -> str:
    """Digest the exact canonical research artifact meaning referenced by a decision."""

    digest = hashlib.sha256(research.canonical_bytes()).hexdigest()
    return f"{DECISION_RESEARCH_DIGEST_ALGORITHM}:{digest}"
