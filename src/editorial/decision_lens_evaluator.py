"""Production Decision Lens evaluator boundary (Issue #59).

Consumes strict typed inputs — the validated current-run research artifact, the
Decision Lens editorial strategy view, the selected audience, the expected lens
profile identity, and exact run/assignment/signal identity — invokes a narrow
injectable evaluator transport, and normalizes the transport output into the
canonical Issue #58 ``DecisionLensDecisionArtifact``.

Every returned decision has passed the canonical contextual validation boundary
(``DecisionLensDecisionArtifact.validate_for_research``); no caller can receive
an evaluator result that bypassed #58 validation. Every failure — transport
error or timeout, malformed output, invalid or mismatched citations, contract
violations — is normalized into an explicit typed non-success result and can
never silently become ``PROCEED``.

Raw provider responses, SDK objects, prompts, credentials, headers, and raw
exceptions stay internal: typed failures carry only bounded evaluator-authored
detail text (never transport output or exception messages).

The maintained Decision Lens instructions are externalized to a versioned
artifact under ``config/prompts/decision_lens/``; the instruction version is
recorded in the canonical ``decision_lens_version`` field. Never Blank is the
Release 1 lens profile; a Release 2 profile registry/loader is out of scope.

The legacy ``decision_lens_lite`` dictionary path remains unchanged for
non-canonical callers and is not used by this boundary.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.editorial.decision_contract import (
    DecisionContractError,
    DecisionLensDecisionArtifact,
    DecisionLensProfileIdentity,
    research_artifact_digest,
)
from src.research.evidence import NormalizedResearchArtifact
from src.strategy.execution_context import (
    AudienceSelection,
    ConfigurationIdentity,
    DecisionLensEditorialStrategyView,
)


DEFAULT_INSTRUCTIONS_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "prompts"
    / "decision_lens"
    / "never_blank.yaml"
)

_MAX_DETAIL_LENGTH = 500


class _EvaluatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionLensTransportError(RuntimeError):
    """The evaluator transport failed to produce a response."""


class DecisionLensTransportTimeout(DecisionLensTransportError):
    """The evaluator transport did not respond in time."""


class DecisionLensTransport(Protocol):
    """Narrow injectable boundary between the evaluator and any LLM provider.

    Implementations receive the maintained instruction text and the bounded
    evaluation request and return the raw model text. They must keep provider
    SDK objects, credentials, and raw responses internal.
    """

    def complete(self, *, instructions: str, request: str) -> str: ...


class DecisionEvaluationFailureKind(str, Enum):
    TRANSPORT_ERROR = "transport_error"
    TRANSPORT_TIMEOUT = "transport_timeout"
    MALFORMED_OUTPUT = "malformed_output"
    INVALID_CITATION = "invalid_citation"
    CONTEXT_MISMATCH = "context_mismatch"
    PROFILE_MISMATCH = "profile_mismatch"
    CONTRACT_VIOLATION = "contract_violation"


class DecisionEvaluationFailure(_EvaluatorModel):
    """Typed non-success outcome. Never carries provider output or exceptions."""

    kind: DecisionEvaluationFailureKind
    detail: str = Field(min_length=1, max_length=_MAX_DETAIL_LENGTH)


class EvaluationOutcome(str, Enum):
    DECISION = "decision"
    FAILURE = "failure"


class DecisionLensEvaluationResult(_EvaluatorModel):
    """Either one canonical validated decision artifact or one typed failure."""

    outcome: EvaluationOutcome
    decision: DecisionLensDecisionArtifact | None = None
    failure: DecisionEvaluationFailure | None = None

    @model_validator(mode="after")
    def _exactly_one_payload(self) -> Self:
        if self.outcome is EvaluationOutcome.DECISION:
            if self.decision is None or self.failure is not None:
                raise ValueError("a decision result carries exactly the decision artifact")
        else:
            if self.failure is None or self.decision is not None:
                raise ValueError("a failure result carries exactly the typed failure")
        return self


class DecisionLensInstructions(_EvaluatorModel):
    """Versioned maintained Decision Lens instruction artifact."""

    instruction_id: str = Field(min_length=1, max_length=120)
    profile_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    instructions: str = Field(min_length=1)

    @property
    def decision_lens_version(self) -> str:
        return f"{self.instruction_id}/{self.version}"

    @classmethod
    def load(cls, path: Path | str = DEFAULT_INSTRUCTIONS_PATH) -> "DecisionLensInstructions":
        raw = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f"instruction artifact {path} is not a mapping")
        return cls.model_validate(data)


def _failure(kind: DecisionEvaluationFailureKind, detail: str) -> DecisionLensEvaluationResult:
    return DecisionLensEvaluationResult(
        outcome=EvaluationOutcome.FAILURE,
        failure=DecisionEvaluationFailure(kind=kind, detail=detail[:_MAX_DETAIL_LENGTH]),
    )


class DecisionLensEvaluator:
    """Release 1 production Decision Lens evaluator boundary.

    The transport is injected; the evaluator contains no provider branching, so
    replacing the transport never changes evaluator behavior. There are no
    retries at this boundary: a failed evaluation stays a typed failure.
    """

    def __init__(
        self,
        transport: DecisionLensTransport,
        instructions: DecisionLensInstructions,
        *,
        evaluator_id: str = "decision-lens-evaluator",
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._transport = transport
        self._instructions = instructions
        self._evaluator_id = evaluator_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def evaluate(
        self,
        *,
        research: NormalizedResearchArtifact,
        strategy_view: DecisionLensEditorialStrategyView,
        audience: AudienceSelection,
        configuration_identity: ConfigurationIdentity,
        lens_profile: DecisionLensProfileIdentity,
        run_id: str,
        assignment_id: str,
        signal_id: str,
        signal: dict | None = None,
    ) -> DecisionLensEvaluationResult:
        precheck = self._check_context(
            research=research,
            strategy_view=strategy_view,
            configuration_identity=configuration_identity,
            lens_profile=lens_profile,
            run_id=run_id,
            assignment_id=assignment_id,
            signal_id=signal_id,
        )
        if precheck is not None:
            return precheck
        audience_check = self._check_audience(audience, strategy_view)
        if audience_check is not None:
            return audience_check

        request = self._build_request(
            research=research,
            strategy_view=strategy_view,
            audience=audience,
            run_id=run_id,
            assignment_id=assignment_id,
            signal_id=signal_id,
            signal=signal or {},
        )

        started_at = self._clock()
        try:
            raw = self._transport.complete(
                instructions=self._instructions.instructions, request=request
            )
        except DecisionLensTransportTimeout:
            return _failure(
                DecisionEvaluationFailureKind.TRANSPORT_TIMEOUT,
                "evaluator transport timed out before returning a response",
            )
        except TimeoutError:
            return _failure(
                DecisionEvaluationFailureKind.TRANSPORT_TIMEOUT,
                "evaluator transport timed out before returning a response",
            )
        except Exception as exc:  # noqa: BLE001 — boundary normalizes all transport errors
            return _failure(
                DecisionEvaluationFailureKind.TRANSPORT_ERROR,
                f"evaluator transport failed ({type(exc).__name__})",
            )

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return _failure(
                DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                "evaluator output is not valid JSON",
            )
        if not isinstance(data, dict):
            return _failure(
                DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                "evaluator output is not a JSON object",
            )

        shape_error = self._check_output_shape(data)
        if shape_error is not None:
            return shape_error

        citation_error = self._check_citations(data, research)
        if citation_error is not None:
            return citation_error

        payload = self._assemble_payload(
            data=data,
            research=research,
            audience=audience,
            configuration_identity=configuration_identity,
            lens_profile=lens_profile,
            run_id=run_id,
            assignment_id=assignment_id,
            signal_id=signal_id,
            started_at=started_at,
        )

        try:
            artifact = DecisionLensDecisionArtifact.validate_for_research(
                payload,
                research=research,
                audience=audience,
                configuration_identity=configuration_identity,
                lens_profile=lens_profile,
            )
        except DecisionContractError as exc:
            return _failure(
                DecisionEvaluationFailureKind.CONTRACT_VIOLATION,
                f"canonical decision validation rejected the evaluation: {exc}",
            )
        except ValidationError as exc:
            # Invariant violations raised inside canonical model validators are
            # wrapped by pydantic as "value_error"; structural problems surface
            # as other error types (missing, enum, extra_forbidden, ...).
            error_types = {error["type"] for error in exc.errors()}
            if error_types <= {"value_error"}:
                return _failure(
                    DecisionEvaluationFailureKind.CONTRACT_VIOLATION,
                    "canonical decision invariants rejected the evaluation",
                )
            return _failure(
                DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                "evaluator output does not satisfy the canonical decision schema",
            )

        return DecisionLensEvaluationResult(
            outcome=EvaluationOutcome.DECISION, decision=artifact
        )

    # -- internal steps -------------------------------------------------

    def _check_context(
        self,
        *,
        research: NormalizedResearchArtifact,
        strategy_view: DecisionLensEditorialStrategyView,
        configuration_identity: ConfigurationIdentity,
        lens_profile: DecisionLensProfileIdentity,
        run_id: str,
        assignment_id: str,
        signal_id: str,
    ) -> DecisionLensEvaluationResult | None:
        if lens_profile.lens_profile_id != self._instructions.profile_id:
            return _failure(
                DecisionEvaluationFailureKind.PROFILE_MISMATCH,
                "expected lens profile does not match the loaded instruction profile",
            )
        if strategy_view.identity != configuration_identity:
            return _failure(
                DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
                "strategy view configuration identity does not match the supplied identity",
            )
        if research.configuration_identity != configuration_identity:
            return _failure(
                DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
                "research configuration identity does not match the supplied identity",
            )
        if (research.run_id, research.assignment_id, research.signal_id) != (
            run_id,
            assignment_id,
            signal_id,
        ):
            return _failure(
                DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
                "research execution identity does not match the supplied run/assignment/signal",
            )
        return None

    def _check_audience(
        self,
        audience: AudienceSelection,
        strategy_view: DecisionLensEditorialStrategyView,
    ) -> DecisionLensEvaluationResult | None:
        declared = {segment.audience_id for segment in strategy_view.audiences}
        if audience.audience_id not in declared:
            return _failure(
                DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
                "selected audience is not declared by the supplied strategy view",
            )
        return None

    def _build_request(
        self,
        *,
        research: NormalizedResearchArtifact,
        strategy_view: DecisionLensEditorialStrategyView,
        audience: AudienceSelection,
        run_id: str,
        assignment_id: str,
        signal_id: str,
        signal: dict,
    ) -> str:
        editorial = strategy_view.brand_editorial
        evidence_boundary = [
            {
                "evidence_id": item.evidence_id,
                "claim": item.claim,
                "source_ids": list(item.source_ids),
                "disposition": item.disposition.value,
            }
            for item in research.evidence
        ]
        conditions = {
            "uncertainties": [
                {
                    "uncertainty_id": item.uncertainty_id,
                    "materiality": item.materiality.value,
                    "resolution": item.resolution.value,
                    "description": item.description,
                }
                for item in research.uncertainties
            ],
            "contradictions": [
                {
                    "contradiction_id": item.contradiction_id,
                    "resolution": item.resolution.value,
                    "description": item.description,
                }
                for item in research.contradictions
            ],
        }
        request = {
            "execution": {
                "run_id": run_id,
                "assignment_id": assignment_id,
                "signal_id": signal_id,
            },
            "audience": {
                "audience_id": audience.audience_id,
                "audience_name": audience.audience_name,
                "selected_problem": audience.selected_problem,
                "decision_factors": list(audience.decision_factors),
                "objections": list(audience.objections),
            },
            "strategy_boundaries": {
                "positioning": strategy_view.positioning.statement,
                "proof_points_boundaries_only": list(strategy_view.positioning.proof_points),
                "preferred_claims": list(editorial.preferred_claims),
                "prohibited_claims": list(editorial.prohibited_claims),
                "restrictions": list(editorial.legal_factual_reputational_restrictions),
                "content_objectives": list(strategy_view.content.objectives),
                "content_territories": list(strategy_view.content.territories),
                "note": (
                    "Strategy proof points, preferred claims, and positioning are "
                    "decision boundaries only. They are never factual evidence. "
                    "Every factual claim must cite the normalized research evidence."
                ),
            },
            "signal": signal,
            "research_evidence": evidence_boundary,
            "research_conditions": conditions,
            "research_readiness": research.readiness.value,
        }
        return json.dumps(request, ensure_ascii=False, sort_keys=True)

    _ALLOWED_OUTPUT_KEYS = frozenset({
        "disposition",
        "relevance",
        "evidence_sufficiency",
        "why_signal_matters",
        "business_value_connection",
        "audience_problem_or_opportunity",
        "defensible_perspective",
        "supported_editorial_angle",
        "source_ids",
        "evidence_ids",
        "relevance_bases",
        "criterion_results",
        "research_condition_handling",
        "restrictions",
        "disposition_reasons",
    })
    _ALLOWED_BASIS_KEYS = frozenset({
        "basis_type",
        "statement",
        "evidence_ids",
        "source_ids",
        "documented_direct_consequence",
    })
    _ALLOWED_CRITERION_KEYS = frozenset({
        "criterion_id",
        "assessment",
        "conclusion",
        "evidence_ids",
        "source_ids",
        "restrictions",
    })

    def _check_output_shape(self, data: dict) -> DecisionLensEvaluationResult | None:
        """Reject unknown output keys instead of silently dropping them.

        Silent normalization would let raw provider payloads, lineage
        overrides, or metadata escape attempts vanish unnoticed; failing
        closed keeps the evaluator honest about what the model returned.
        """

        unknown = sorted(set(data) - self._ALLOWED_OUTPUT_KEYS)
        if unknown:
            return _failure(
                DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                "evaluator output contains unknown fields: " + ", ".join(unknown),
            )
        for group, allowed in (
            ("relevance_bases", self._ALLOWED_BASIS_KEYS),
            ("criterion_results", self._ALLOWED_CRITERION_KEYS),
        ):
            items = data.get(group, [])
            if not isinstance(items, list):
                return _failure(
                    DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                    f"evaluator output field {group} is not a list",
                )
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    return _failure(
                        DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                        f"evaluator output {group}[{index}] is not an object",
                    )
                unknown = sorted(set(item) - allowed)
                if unknown:
                    return _failure(
                        DecisionEvaluationFailureKind.MALFORMED_OUTPUT,
                        f"evaluator output {group}[{index}] contains unknown fields: "
                        + ", ".join(unknown),
                    )
        return None

    def _check_citations(
        self, data: dict, research: NormalizedResearchArtifact
    ) -> DecisionLensEvaluationResult | None:
        known_evidence = {item.evidence_id: item for item in research.evidence}
        known_sources = {item.source_id for item in research.sources}

        def collect(container: object, key: str) -> list[str]:
            if not isinstance(container, dict):
                return []
            value = container.get(key, [])
            return [str(item) for item in value] if isinstance(value, list) else []

        scopes: list[tuple[str, list[str], list[str]]] = [
            ("decision", collect(data, "evidence_ids"), collect(data, "source_ids")),
        ]
        for group in ("relevance_bases", "criterion_results"):
            items = data.get(group, [])
            if isinstance(items, list):
                for index, item in enumerate(items):
                    scopes.append(
                        (
                            f"{group}[{index}]",
                            collect(item, "evidence_ids"),
                            collect(item, "source_ids"),
                        )
                    )

        for scope, evidence_ids, source_ids in scopes:
            unknown_evidence = sorted(set(evidence_ids) - set(known_evidence))
            if unknown_evidence:
                return _failure(
                    DecisionEvaluationFailureKind.INVALID_CITATION,
                    f"{scope} cites evidence absent from current-run research: "
                    + ", ".join(unknown_evidence),
                )
            unknown_sources = sorted(set(source_ids) - known_sources)
            if unknown_sources:
                return _failure(
                    DecisionEvaluationFailureKind.INVALID_CITATION,
                    f"{scope} cites sources absent from current-run research: "
                    + ", ".join(unknown_sources),
                )
            supporting = {
                source_id
                for evidence_id in evidence_ids
                for source_id in known_evidence[evidence_id].source_ids
            }
            if set(source_ids) != supporting:
                return _failure(
                    DecisionEvaluationFailureKind.INVALID_CITATION,
                    f"{scope} source citations do not exactly match the sources "
                    "supporting its cited evidence",
                )
        return None

    def _assemble_payload(
        self,
        *,
        data: dict,
        research: NormalizedResearchArtifact,
        audience: AudienceSelection,
        configuration_identity: ConfigurationIdentity,
        lens_profile: DecisionLensProfileIdentity,
        run_id: str,
        assignment_id: str,
        signal_id: str,
        started_at: datetime,
    ) -> dict:
        """Assemble the canonical payload. Lineage fields come only from trusted inputs."""

        bases = []
        for item in data.get("relevance_bases", []) or []:
            if not isinstance(item, dict):
                continue
            bases.append(
                {
                    "basis_type": item.get("basis_type"),
                    "audience_id": audience.audience_id,
                    "statement": item.get("statement"),
                    "evidence_ids": item.get("evidence_ids"),
                    "source_ids": item.get("source_ids"),
                    "documented_direct_consequence": item.get(
                        "documented_direct_consequence"
                    ),
                }
            )
        criteria = []
        for item in data.get("criterion_results", []) or []:
            if not isinstance(item, dict):
                continue
            criteria.append(
                {
                    "criterion_id": item.get("criterion_id"),
                    "assessment": item.get("assessment"),
                    "conclusion": item.get("conclusion"),
                    "evidence_ids": item.get("evidence_ids", []),
                    "source_ids": item.get("source_ids", []),
                    "restrictions": item.get("restrictions", []),
                }
            )

        return {
            "decision_artifact_id": self._id_factory(),
            "run_id": run_id,
            "assignment_id": assignment_id,
            "signal_id": signal_id,
            "configuration_identity": configuration_identity.model_dump(mode="json"),
            "audience_selection": audience.model_dump(mode="json"),
            "lens_profile": lens_profile.model_dump(mode="json"),
            "research_digest": research_artifact_digest(research),
            "decision_lens_version": self._instructions.decision_lens_version,
            "evaluator": {
                "evaluator_id": self._evaluator_id,
                "evaluator_version": self._instructions.version,
                "kind": "declared_model",
            },
            "evaluation_started_at": started_at,
            "created_at": self._clock(),
            "source_ids": data.get("source_ids", []),
            "evidence_ids": data.get("evidence_ids", []),
            "judgment": {
                "relevance": data.get("relevance"),
                "evidence_sufficiency": data.get("evidence_sufficiency"),
                "why_signal_matters": data.get("why_signal_matters"),
                "business_value_connection": data.get("business_value_connection"),
                "audience_problem_or_opportunity": data.get(
                    "audience_problem_or_opportunity"
                ),
                "defensible_perspective": data.get("defensible_perspective"),
                "supported_editorial_angle": data.get("supported_editorial_angle"),
                "relevance_bases": bases,
                "criterion_results": criteria,
                "research_condition_handling": data.get(
                    "research_condition_handling", []
                ),
                "restrictions": data.get("restrictions", []),
                "disposition_reasons": data.get("disposition_reasons", []),
            },
            "disposition": data.get("disposition"),
        }


class LlmChatDecisionLensTransport:
    """Production transport backed by the repository LLM client.

    Keeps the provider SDK internal. Never constructed by deterministic tests.
    """

    def complete(self, *, instructions: str, request: str) -> str:
        from src.utils.llm_client import chat, model_enrich

        return chat(system=instructions, user=request, json_mode=True, model=model_enrich())


def production_evaluator(
    instructions_path: Path | str = DEFAULT_INSTRUCTIONS_PATH,
) -> DecisionLensEvaluator:
    """Build the Release 1 production evaluator with the maintained instructions."""

    instructions = DecisionLensInstructions.load(instructions_path)
    return DecisionLensEvaluator(
        transport=LlmChatDecisionLensTransport(),
        instructions=instructions,
        evaluator_id="never-blank-decision-lens-evaluator",
    )
