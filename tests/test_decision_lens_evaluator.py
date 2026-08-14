"""Deterministic tests for the production Decision Lens evaluator boundary (Issue #59).

All scenarios use injected fake transports. No live providers are called.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.editorial.decision_contract import (
    DecisionDisposition,
    DecisionLensProfileIdentity,
)
from src.editorial.decision_lens_evaluator import (
    DecisionEvaluationFailureKind,
    DecisionLensEvaluationResult,
    DecisionLensEvaluator,
    DecisionLensInstructions,
    DecisionLensTransportTimeout,
    EvaluationOutcome,
    LlmChatDecisionLensTransport,
    production_evaluator,
)
from src.research.evidence import NormalizedResearchArtifact
from src.strategy.business_config import (
    AudienceSegment,
    BrandEditorialPolicy,
    BusinessIdentity,
    ContentStrategy,
    Positioning,
)
from src.strategy.execution_context import (
    AudienceSelection,
    ConfigurationIdentity,
    DecisionLensEditorialStrategyView,
)


UTC = timezone.utc
RUN_ID = "12345678-1234-4234-8234-123456789abc"


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
    return DecisionLensProfileIdentity(
        lens_profile_id="never-blank-editorial-lens",
        lens_profile_version="1.0",
    )


def _instructions() -> DecisionLensInstructions:
    return DecisionLensInstructions(
        instruction_id="never-blank-decision-lens",
        profile_id="never-blank-editorial-lens",
        profile_version="1.0",
        version="1.0",
        instructions="Judge the signal for the configured audience. Return JSON.",
    )


def _strategy_view() -> DecisionLensEditorialStrategyView:
    return DecisionLensEditorialStrategyView(
        identity=_identity(),
        business=BusinessIdentity(
            name="Never Blank",
            business_model="editorial-service",
            description="Research-driven owner-presence editorial system.",
        ),
        audiences=(
            AudienceSegment(
                audience_id="independent-service-owner",
                name="Independent service business owner",
                problems=("Deciding where constrained operating capacity creates value.",),
                default_problem="Deciding where constrained operating capacity creates value.",
                decision_factors=("cash flow", "capacity"),
                objections=("generic enterprise advice",),
            ),
        ),
        default_audience_id="independent-service-owner",
        positioning=Positioning(
            statement="Presence systems for independent owners.",
            expertise=("owner visibility",),
            value_propositions=("stay remembered between purchases",),
            proof_points=("worked with independent service firms",),
        ),
        content=ContentStrategy(
            objectives=("customer trust",),
            territories=("owner presence",),
        ),
        brand_editorial=BrandEditorialPolicy(
            voice=("plain",),
            editorial_principles=("evidence first",),
            preferred_claims=("presence compounds",),
            prohibited_claims=("guaranteed revenue",),
            legal_factual_reputational_restrictions=("no fabricated metrics",),
        ),
        calls_to_action=(),
        prompt_rule_references=(),
    )


def _research_payload() -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": "research-59",
        "run_id": RUN_ID,
        "assignment_id": "assignment-59",
        "signal_id": "signal-59",
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


def _model_output(*, disposition: str = "proceed") -> dict:
    non_success = disposition != "proceed"
    return {
        "disposition": disposition,
        "relevance": "direct",
        "evidence_sufficiency": "partial" if non_success else "sufficient",
        "why_signal_matters": "It changes a constrained operating decision now.",
        "business_value_connection": "The evidence connects capacity to owner economics.",
        "audience_problem_or_opportunity": "Choose work that fits finite delivery capacity.",
        "defensible_perspective": "Capacity allocation is a commercial choice.",
        "supported_editorial_angle": "How independent owners can price scarce capacity.",
        "source_ids": ["source-sba"],
        "evidence_ids": ["evidence-smb"],
        "relevance_bases": [{
            "basis_type": "direct_audience_evidence",
            "statement": "The cited evidence directly studies the configured audience.",
            "evidence_ids": ["evidence-smb"],
            "source_ids": ["source-sba"],
            "documented_direct_consequence": None,
        }],
        "criterion_results": [{
            "criterion_id": "nb-owner-presence",
            "assessment": "satisfied",
            "conclusion": "The evidence exposes a real owner presence decision.",
            "evidence_ids": ["evidence-smb"],
            "source_ids": ["source-sba"],
            "restrictions": [],
        }],
        "research_condition_handling": [],
        "restrictions": ["Do not generalize beyond independent service firms."],
        "disposition_reasons": ["Current-run evidence directly supports the angle."],
    }


class FakeTransport:
    """Deterministic fake returning a fixed payload; records the request."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls.append({"instructions": instructions, "request": request})
        if isinstance(self.payload, Exception):
            raise self.payload
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


class _Clock:
    def __init__(self) -> None:
        self._now = datetime(2026, 8, 14, 12, 0, 3, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._now
        self._now = self._now + timedelta(seconds=1)
        return value


def _evaluator(payload: object, **kwargs) -> tuple[DecisionLensEvaluator, FakeTransport]:
    transport = FakeTransport(payload)
    evaluator = DecisionLensEvaluator(
        transport=transport,
        instructions=kwargs.pop("instructions", _instructions()),
        evaluator_id="deterministic-test-evaluator",
        clock=_Clock(),
        id_factory=lambda: "87654321-4321-4321-8321-cba987654321",
        **kwargs,
    )
    return evaluator, transport


def _evaluate(evaluator: DecisionLensEvaluator, **overrides) -> DecisionLensEvaluationResult:
    args = {
        "research": _research(),
        "strategy_view": _strategy_view(),
        "audience": _audience(),
        "configuration_identity": _identity(),
        "lens_profile": _lens_profile(),
        "run_id": RUN_ID,
        "assignment_id": "assignment-59",
        "signal_id": "signal-59",
    }
    args.update(overrides)
    return evaluator.evaluate(**args)


def _expect_failure(result: DecisionLensEvaluationResult, kind: DecisionEvaluationFailureKind):
    assert result.outcome is EvaluationOutcome.FAILURE
    assert result.decision is None
    assert result.failure is not None and result.failure.kind is kind
    return result.failure


# --- canonical dispositions through the boundary ---


def test_valid_proceed_returns_canonically_validated_artifact():
    evaluator, transport = _evaluator(_model_output())
    result = _evaluate(evaluator)
    assert result.outcome is EvaluationOutcome.DECISION
    decision = result.decision
    assert decision is not None
    assert decision.disposition is DecisionDisposition.PROCEED
    assert decision.lens_profile == _lens_profile()
    assert decision.decision_lens_version == "never-blank-decision-lens/1.0"
    assert decision.judgment.relevance_bases[0].audience_id == _audience().audience_id
    assert decision.judgment.criterion_results[0].criterion_id == "nb-owner-presence"
    # the transport received boundaries, not fabricated evidence
    request = json.loads(transport.calls[0]["request"])
    assert request["strategy_boundaries"]["proof_points_boundaries_only"]
    assert request["research_evidence"][0]["evidence_id"] == "evidence-smb"


@pytest.mark.parametrize(
    "disposition", ["revise", "hold", "reject", "insufficient_evidence"]
)
def test_non_success_dispositions_survive_as_canonical_artifacts(disposition):
    evaluator, _ = _evaluator(_model_output(disposition=disposition))
    result = _evaluate(evaluator)
    assert result.outcome is EvaluationOutcome.DECISION
    assert result.decision.disposition.value == disposition


# --- fail-closed evaluator failures ---


def test_malformed_output_is_typed_failure_not_proceed():
    evaluator, _ = _evaluator("this is not json {")
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.MALFORMED_OUTPUT)


def test_non_object_json_output_is_malformed():
    evaluator, _ = _evaluator('["a", "list"]')
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.MALFORMED_OUTPUT)


def test_missing_required_fields_fail_schema_normalization():
    payload = _model_output()
    del payload["defensible_perspective"]
    evaluator, _ = _evaluator(payload)
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.MALFORMED_OUTPUT)


def test_transport_timeout_is_typed_timeout_failure():
    evaluator, _ = _evaluator(DecisionLensTransportTimeout("provider timed out"))
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.TRANSPORT_TIMEOUT)


def test_transport_error_is_typed_failure_without_raw_exception():
    evaluator, _ = _evaluator(RuntimeError("secret api_key=sk-abcdefghijklmnop leaked"))
    failure = _expect_failure(
        _evaluate(evaluator), DecisionEvaluationFailureKind.TRANSPORT_ERROR
    )
    # only the exception class name crosses the boundary, never its message
    assert "RuntimeError" in failure.detail
    assert "sk-abcdefghijklmnop" not in failure.detail
    assert "secret" not in failure.detail


def test_unknown_evidence_citation_is_invalid_citation():
    payload = _model_output()
    payload["evidence_ids"] = ["evidence-invented"]
    payload["relevance_bases"][0]["evidence_ids"] = ["evidence-invented"]
    payload["criterion_results"][0]["evidence_ids"] = ["evidence-invented"]
    evaluator, _ = _evaluator(payload)
    failure = _expect_failure(
        _evaluate(evaluator), DecisionEvaluationFailureKind.INVALID_CITATION
    )
    assert "evidence-invented" in failure.detail


def test_unknown_source_citation_is_invalid_citation():
    payload = _model_output()
    payload["source_ids"] = ["source-invented"]
    evaluator, _ = _evaluator(payload)
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.INVALID_CITATION)


def test_source_evidence_mismatch_is_invalid_citation():
    # source-sba exists in research but the model claims evidence with no sources
    payload = _model_output()
    payload["relevance_bases"][0]["source_ids"] = []
    evaluator, _ = _evaluator(payload)
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.INVALID_CITATION)


def test_unsupported_factual_claim_cannot_proceed():
    # an angle with zero cited evidence: vacuous support for PROCEED
    payload = _model_output()
    payload["evidence_ids"] = []
    payload["source_ids"] = []
    payload["relevance_bases"][0]["evidence_ids"] = []
    payload["relevance_bases"][0]["source_ids"] = []
    payload["criterion_results"] = []
    evaluator, _ = _evaluator(payload)
    result = _evaluate(evaluator)
    assert result.outcome is EvaluationOutcome.FAILURE
    assert result.decision is None


def test_blocked_evidence_citation_is_contract_violation_not_proceed():
    research_payload = _research_payload()
    research_payload["readiness"] = "needs_review"
    research_payload["evidence"][0]["disposition"] = "rejected"
    research = NormalizedResearchArtifact.model_validate(research_payload)
    evaluator, _ = _evaluator(_model_output())
    result = _evaluate(evaluator, research=research)
    _expect_failure(result, DecisionEvaluationFailureKind.CONTRACT_VIOLATION)


# --- context and profile boundaries ---


def test_profile_mismatch_fails_before_transport():
    evaluator, transport = _evaluator(_model_output())
    other = DecisionLensProfileIdentity(
        lens_profile_id="clinical-quality-lens", lens_profile_version="1.0"
    )
    _expect_failure(
        _evaluate(evaluator, lens_profile=other),
        DecisionEvaluationFailureKind.PROFILE_MISMATCH,
    )
    assert transport.calls == []


def test_correct_profile_id_with_wrong_version_fails_before_transport():
    evaluator, transport = _evaluator(_model_output())
    wrong_version = DecisionLensProfileIdentity(
        lens_profile_id="never-blank-editorial-lens", lens_profile_version="9.9"
    )
    _expect_failure(
        _evaluate(evaluator, lens_profile=wrong_version),
        DecisionEvaluationFailureKind.PROFILE_MISMATCH,
    )
    assert transport.calls == []


def test_complete_profile_identity_succeeds_and_is_preserved_in_the_artifact():
    evaluator, _ = _evaluator(_model_output())
    result = _evaluate(evaluator)
    assert result.outcome is EvaluationOutcome.DECISION
    assert result.decision.lens_profile == _lens_profile()
    assert result.decision.lens_profile.lens_profile_version == "1.0"


def test_configuration_mismatch_fails_before_transport():
    evaluator, transport = _evaluator(_model_output())
    other = ConfigurationIdentity(
        **{**_identity().model_dump(), "configuration_hash": "sha256:" + "b" * 64}
    )
    _expect_failure(
        _evaluate(evaluator, configuration_identity=other),
        DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
    )
    assert transport.calls == []


def test_execution_identity_mismatch_fails_before_transport():
    evaluator, transport = _evaluator(_model_output())
    _expect_failure(
        _evaluate(evaluator, signal_id="signal-other"),
        DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
    )
    assert transport.calls == []


def test_undeclared_audience_fails_before_transport():
    evaluator, transport = _evaluator(_model_output())
    other = AudienceSelection(
        **{**_audience().model_dump(), "audience_id": "local-retail-owner"}
    )
    _expect_failure(
        _evaluate(evaluator, audience=other),
        DecisionEvaluationFailureKind.CONTEXT_MISMATCH,
    )
    assert transport.calls == []


# --- canonical validation cannot be bypassed ---


def test_model_cannot_bypass_canonical_validation_with_own_lineage():
    # hostile output tries to smuggle its own lineage/digest/profile fields;
    # unknown output keys are rejected outright rather than silently dropped
    payload = _model_output()
    payload["run_id"] = "99999999-9999-4999-8999-999999999999"
    payload["research_digest"] = "sha256:" + "f" * 64
    payload["lens_profile"] = {
        "lens_profile_id": "attacker-lens",
        "lens_profile_version": "6.6",
    }
    payload["schema_version"] = "9.9"
    evaluator, _ = _evaluator(payload)
    failure = _expect_failure(
        _evaluate(evaluator), DecisionEvaluationFailureKind.MALFORMED_OUTPUT
    )
    assert "lens_profile" in failure.detail

    # a clean output always carries the trusted lineage, never model-authored lineage
    clean_eval, _ = _evaluator(_model_output())
    result = _evaluate(clean_eval)
    assert result.outcome is EvaluationOutcome.DECISION
    assert result.decision.run_id == RUN_ID
    assert result.decision.lens_profile == _lens_profile()
    assert result.decision.schema_version == "1.0"


def test_false_proceed_is_rejected_by_canonical_invariants():
    payload = _model_output()
    payload["evidence_sufficiency"] = "insufficient"
    evaluator, _ = _evaluator(payload)
    result = _evaluate(evaluator)
    _expect_failure(result, DecisionEvaluationFailureKind.CONTRACT_VIOLATION)


def test_analogy_only_relevance_cannot_proceed_through_the_evaluator():
    payload = _model_output()
    payload["relevance_bases"][0]["basis_type"] = "analogy_only"
    evaluator, _ = _evaluator(payload)
    _expect_failure(_evaluate(evaluator), DecisionEvaluationFailureKind.CONTRACT_VIOLATION)


# --- secret and provider isolation ---


def test_raw_provider_payload_escape_attempt_is_rejected():
    payload = _model_output()
    payload["raw_provider_payload"] = {"secret": "sk-abcdefghijklmnop"}
    evaluator, _ = _evaluator(payload)
    failure = _expect_failure(
        _evaluate(evaluator), DecisionEvaluationFailureKind.MALFORMED_OUTPUT
    )
    # the failure names the field but never carries the payload value
    assert "raw_provider_payload" in failure.detail
    assert "sk-abcdefghijklmnop" not in failure.detail


def test_nested_metadata_escape_attempt_is_rejected():
    payload = _model_output()
    payload["criterion_results"][0]["metadata"] = {"raw": "provider-object"}
    evaluator, _ = _evaluator(payload)
    failure = _expect_failure(
        _evaluate(evaluator), DecisionEvaluationFailureKind.MALFORMED_OUTPUT
    )
    assert "criterion_results[0]" in failure.detail


def test_credential_shaped_model_text_is_rejected():
    payload = _model_output()
    payload["disposition_reasons"] = ["api_key=sk-abcdefghijklmnop"]
    evaluator, _ = _evaluator(payload)
    result = _evaluate(evaluator)
    assert result.outcome is EvaluationOutcome.FAILURE


def test_failure_results_never_carry_artifacts_and_vice_versa():
    with pytest.raises(Exception):
        DecisionLensEvaluationResult(outcome=EvaluationOutcome.FAILURE)
    with pytest.raises(Exception):
        DecisionLensEvaluationResult(outcome=EvaluationOutcome.DECISION)


# --- transport replacement without provider branching ---


def test_transport_replacement_produces_identical_decisions():
    class OtherFakeTransport:
        def complete(self, *, instructions: str, request: str) -> str:
            return json.dumps(_model_output())

    first_eval, _ = _evaluator(_model_output())
    second = DecisionLensEvaluator(
        transport=OtherFakeTransport(),
        instructions=_instructions(),
        evaluator_id="deterministic-test-evaluator",
        clock=_Clock(),
        id_factory=lambda: "87654321-4321-4321-8321-cba987654321",
    )
    a = _evaluate(first_eval)
    b = _evaluate(second)
    assert a.outcome is EvaluationOutcome.DECISION
    assert b.outcome is EvaluationOutcome.DECISION
    assert a.decision.canonical_bytes() == b.decision.canonical_bytes()


def test_evaluator_source_contains_no_provider_branching():
    import inspect

    import src.editorial.decision_lens_evaluator as module

    source = inspect.getsource(module.DecisionLensEvaluator)
    for provider_term in ("openai", "anthropic", "gpt-", "claude"):
        assert provider_term not in source.lower()


# --- strict typed public boundary: no unrestricted signal mapping ---


def test_arbitrary_signal_metadata_cannot_pass_the_canonical_api():
    evaluator, _ = _evaluator(_model_output())
    with pytest.raises(TypeError):
        _evaluate(evaluator, signal={"arbitrary": {"nested": "metadata"}})


def test_credential_shaped_signal_payload_cannot_reach_the_transport():
    evaluator, transport = _evaluator(_model_output())
    with pytest.raises(TypeError):
        _evaluate(
            evaluator,
            signal={"headers": {"Authorization": "Bearer sk-abcdefghijklmnop"}},
        )
    assert transport.calls == []


def test_request_carries_exact_trusted_identity_and_only_known_sections():
    evaluator, transport = _evaluator(_model_output())
    result = _evaluate(evaluator)
    assert result.outcome is EvaluationOutcome.DECISION
    request = json.loads(transport.calls[0]["request"])
    assert request["execution"] == {
        "run_id": RUN_ID,
        "assignment_id": "assignment-59",
        "signal_id": "signal-59",
    }
    assert set(request) == {
        "execution",
        "audience",
        "strategy_boundaries",
        "research_evidence",
        "research_conditions",
        "research_readiness",
    }
    assert "sk-" not in transport.calls[0]["request"]


# --- maintained instruction artifact ---


def test_production_instruction_artifact_loads_with_stable_version():
    instructions = DecisionLensInstructions.load()
    assert instructions.instruction_id == "never-blank-decision-lens"
    assert instructions.profile_id == "never-blank-editorial-lens"
    assert instructions.profile_version == "1.0"
    assert instructions.version == "1.0"
    assert instructions.decision_lens_version == "never-blank-decision-lens/1.0"
    assert instructions.profile_identity == _lens_profile()
    assert "evidence" in instructions.instructions.lower()


def test_production_evaluator_wires_maintained_instructions_without_live_calls():
    evaluator = production_evaluator()
    assert isinstance(evaluator._transport, LlmChatDecisionLensTransport)  # noqa: SLF001
    # constructing the production evaluator performs no provider calls; the
    # decision version comes from the maintained artifact
    assert evaluator._instructions.decision_lens_version == (  # noqa: SLF001
        "never-blank-decision-lens/1.0"
    )
