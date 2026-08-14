"""Issue #60: decision.json persistence and Decision Lens disposition gating.

Covers the canonical lifecycle (evaluate once → atomic create-once persist →
strict reload → revalidate → PROCEED-only passage), every non-success
disposition, evaluator failures, collision/write failure, corrupt/cross-run
artifacts, real production ordering through the canonical entrypoint, and
``--from-package`` reuse. All Decision Lens calls use injected deterministic
fake transports; no live providers.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.artifacts import ArtifactCollisionError
from src.editorial.decision_contract import (
    DecisionDisposition,
    DecisionLensDecisionArtifact,
)
from src.editorial.decision_lens_evaluator import (
    DecisionLensEvaluator,
    DecisionLensInstructions,
)
from src.editorial.decision_lifecycle import (
    RELEASE1_LENS_PROFILE,
    DecisionGateError,
    evaluate_and_persist_decision,
    load_decision_artifact,
    require_proceed,
)
from src.intake import from_jsonl_signal
from src.run import ExecutionMode, RunContext
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext
from src.research.lifecycle import (
    build_research_request,
    execute_and_persist_research,
)
from tests import test_generate_and_publish as legacy
from tests.test_research_artifact_lifecycle import ReadyProvider


def _instructions() -> DecisionLensInstructions:
    return DecisionLensInstructions(
        instruction_id="never-blank-decision-lens",
        profile_id=RELEASE1_LENS_PROFILE.lens_profile_id,
        profile_version=RELEASE1_LENS_PROFILE.lens_profile_version,
        version="1.0",
        instructions="Judge the signal for the configured audience. Return JSON.",
    )


def _model_output(*, disposition: str = "proceed") -> dict:
    non_success = disposition != "proceed"
    return {
        "disposition": disposition,
        "relevance": "direct",
        "evidence_sufficiency": "partial" if non_success else "sufficient",
        "why_signal_matters": "It changes a constrained operating decision now.",
        "business_value_connection": "The evidence connects the pattern to owner economics.",
        "audience_problem_or_opportunity": "Decide where presence work fits delivery load.",
        "defensible_perspective": "Presence maintenance is a commercial choice.",
        "supported_editorial_angle": "How owners keep presence while delivering.",
        "source_ids": ["source-1"],
        "evidence_ids": ["evidence-1"],
        "relevance_bases": [{
            "basis_type": "direct_audience_evidence",
            "statement": "The cited evidence directly studies the configured audience.",
            "evidence_ids": ["evidence-1"],
            "source_ids": ["source-1"],
            "documented_direct_consequence": None,
        }],
        "criterion_results": [{
            "criterion_id": "nb-owner-presence",
            "assessment": "satisfied",
            "conclusion": "The evidence exposes a real owner presence decision.",
            "evidence_ids": ["evidence-1"],
            "source_ids": ["source-1"],
            "restrictions": [],
        }],
        "research_condition_handling": [],
        "restrictions": ["Do not generalize beyond the configured audience."],
        "disposition_reasons": ["Current-run evidence directly supports the angle."],
    }


class FakeTransport:
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


def _evaluator(payload: object) -> tuple[DecisionLensEvaluator, FakeTransport]:
    transport = FakeTransport(payload)
    return (
        DecisionLensEvaluator(transport=transport, instructions=_instructions()),
        transport,
    )


@pytest.fixture
def lifecycle(tmp_path):
    """Real strategy context + persisted READY research in a tmp run namespace."""

    strategy = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    signal = dict(legacy._RAW_SIGNAL)
    assignment = from_jsonl_signal(
        signal,
        strategy_ref=legacy._STRATEGY_STUB.strategy_id,
        strategy_version=legacy._STRATEGY_STUB.strategy_version,
        submitted_at=datetime.now(timezone.utc),
    )
    run = RunContext.from_assignment(
        assignment, ExecutionMode.DRY_RUN, configuration_identity=strategy.identity
    )
    request = build_research_request(
        run, assignment, signal, strategy.research, now=datetime.now(timezone.utc)
    )
    run_dir = tmp_path / assignment.assignment_id / "runs" / run.run_id
    research = execute_and_persist_research(
        ReadyProvider(), request, run_dir, identity=strategy.identity,
        run_started_at=run.started_at,
        clock=lambda: request.requested_at + timedelta(seconds=2),
    )
    audience = strategy.decision_lens_editorial.select_audience(
        assignment.target_audience
    )
    return tmp_path, strategy, assignment, run, run_dir, research, audience


def _gate_kwargs(lifecycle) -> dict:
    _, strategy, assignment, run, run_dir, research, audience = lifecycle
    return dict(
        research=research,
        strategy_view=strategy.decision_lens_editorial,
        audience=audience,
        configuration_identity=strategy.identity,
        lens_profile=RELEASE1_LENS_PROFILE,
        run_id=run.run_id,
        assignment_id=assignment.assignment_id,
        signal_id=assignment.assignment_id,
        run_dir=run_dir,
    )


def _reload_kwargs(lifecycle) -> dict:
    root, strategy, assignment, run, _, research, audience = lifecycle
    return dict(
        research=research,
        audience=audience,
        configuration_identity=strategy.identity,
        lens_profile=RELEASE1_LENS_PROFILE,
    )


# ===========================================================================
# Canonical persistence lifecycle
# ===========================================================================


def test_proceed_decision_is_persisted_canonically_and_reloaded(lifecycle):
    root, _, assignment, run, run_dir, *_ = lifecycle
    evaluator, transport = _evaluator(_model_output())
    artifact = evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    assert len(transport.calls) == 1  # the Decision Lens ran exactly once
    path = run_dir / "decision.json"
    assert path.read_bytes() == artifact.canonical_bytes()
    assert artifact.disposition is DecisionDisposition.PROCEED
    assert artifact.run_id == run.run_id
    assert artifact.lens_profile == RELEASE1_LENS_PROFILE
    require_proceed(artifact)  # does not raise
    reloaded = load_decision_artifact(
        root, assignment.assignment_id, run.run_id, **_reload_kwargs(lifecycle)
    )
    assert reloaded == artifact
    assert path.read_bytes() == artifact.canonical_bytes()  # reuse never rewrites


@pytest.mark.parametrize(
    "disposition", ["revise", "hold", "reject", "insufficient_evidence"]
)
def test_non_proceed_decisions_are_persisted_honestly_then_blocked(lifecycle, disposition):
    _, _, _, _, run_dir, *_ = lifecycle
    evaluator, _ = _evaluator(_model_output(disposition=disposition))
    artifact = evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    assert (run_dir / "decision.json").exists()
    assert artifact.disposition.value == disposition
    with pytest.raises(DecisionGateError, match=disposition):
        require_proceed(artifact)


def test_evaluator_failure_is_a_stop_with_no_synthetic_artifact(lifecycle):
    _, _, _, _, run_dir, *_ = lifecycle
    evaluator, _ = _evaluator("this is not json {")
    with pytest.raises(DecisionGateError, match="malformed_output"):
        evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    assert not (run_dir / "decision.json").exists()

    evaluator, _ = _evaluator(RuntimeError("provider blew up"))
    with pytest.raises(DecisionGateError, match="transport_error"):
        evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    assert not (run_dir / "decision.json").exists()


def test_existing_decision_is_never_overwritten(lifecycle):
    _, _, _, _, run_dir, *_ = lifecycle
    evaluator, _ = _evaluator(_model_output())
    evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    before = (run_dir / "decision.json").read_bytes()
    evaluator2, _ = _evaluator(_model_output())
    with pytest.raises(ArtifactCollisionError):
        evaluate_and_persist_decision(evaluator2, **_gate_kwargs(lifecycle))
    assert (run_dir / "decision.json").read_bytes() == before


def test_commit_failure_leaves_no_target_or_temp_file(lifecycle):
    _, _, _, _, run_dir, *_ = lifecycle
    evaluator, _ = _evaluator(_model_output())
    with mock.patch("src.artifacts.os.link", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    assert not (run_dir / "decision.json").exists()
    assert not list(run_dir.glob(".tmp_*.json"))


# ===========================================================================
# Strict reload and reuse validation
# ===========================================================================


def test_missing_decision_fails_closed(lifecycle):
    root, _, assignment, run, *_ = lifecycle
    with pytest.raises(DecisionGateError, match="No decision.json"):
        load_decision_artifact(
            root, assignment.assignment_id, run.run_id, **_reload_kwargs(lifecycle)
        )


def test_corrupt_and_noncanonical_decisions_are_rejected(lifecycle):
    root, _, assignment, run, run_dir, *_ = lifecycle
    path = run_dir / "decision.json"
    path.write_text('{"broken":')
    with pytest.raises(DecisionGateError, match="malformed"):
        load_decision_artifact(
            root, assignment.assignment_id, run.run_id, **_reload_kwargs(lifecycle)
        )

    path.unlink()
    evaluator, _ = _evaluator(_model_output())
    artifact = evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    path.unlink()
    path.write_text(json.dumps(json.loads(artifact.canonical_json()), indent=2))
    with pytest.raises(DecisionGateError, match="not canonical"):
        load_decision_artifact(
            root, assignment.assignment_id, run.run_id, **_reload_kwargs(lifecycle)
        )


def test_cross_run_decision_is_rejected(lifecycle, tmp_path):
    root, strategy, assignment, run, run_dir, research, audience = lifecycle
    evaluator, _ = _evaluator(_model_output())
    evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))

    # a second, different run of the same signal
    signal = dict(legacy._RAW_SIGNAL)
    assignment_b = from_jsonl_signal(
        signal, strategy_ref=legacy._STRATEGY_STUB.strategy_id,
        strategy_version=legacy._STRATEGY_STUB.strategy_version,
        submitted_at=datetime.now(timezone.utc),
    )
    run_b = RunContext.from_assignment(
        assignment_b, ExecutionMode.DRY_RUN, configuration_identity=strategy.identity
    )
    request_b = build_research_request(
        run_b, assignment_b, signal, strategy.research, now=datetime.now(timezone.utc)
    )
    run_dir_b = root / assignment_b.assignment_id / "runs" / run_b.run_id
    research_b = execute_and_persist_research(
        ReadyProvider(), request_b, run_dir_b, identity=strategy.identity,
        run_started_at=run_b.started_at,
        clock=lambda: request_b.requested_at + timedelta(seconds=2),
    )
    # copy run A's decision into run B's namespace: cross-run reuse must fail
    (run_dir_b / "decision.json").write_bytes((run_dir / "decision.json").read_bytes())
    with pytest.raises(DecisionGateError, match="revalidation|identity"):
        load_decision_artifact(
            root, assignment_b.assignment_id, run_b.run_id,
            research=research_b, audience=audience,
            configuration_identity=strategy.identity,
            lens_profile=RELEASE1_LENS_PROFILE,
        )


def test_lens_profile_mismatch_on_reload_fails_closed(lifecycle):
    root, strategy, assignment, run, _, research, audience = lifecycle
    evaluator, _ = _evaluator(_model_output())
    evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    other_profile = RELEASE1_LENS_PROFILE.model_copy(
        update={"lens_profile_version": "9.9"}
    )
    with pytest.raises(DecisionGateError, match="revalidation"):
        load_decision_artifact(
            root, assignment.assignment_id, run.run_id,
            research=research, audience=audience,
            configuration_identity=strategy.identity, lens_profile=other_profile,
        )


def test_audience_mismatch_on_reload_fails_closed(lifecycle):
    root, strategy, assignment, run, _, research, audience = lifecycle
    evaluator, _ = _evaluator(_model_output())
    evaluate_and_persist_decision(evaluator, **_gate_kwargs(lifecycle))
    other = audience.model_copy(update={"audience_id": "other-audience"})
    with pytest.raises(DecisionGateError, match="revalidation"):
        load_decision_artifact(
            root, assignment.assignment_id, run.run_id,
            research=research, audience=other,
            configuration_identity=strategy.identity,
            lens_profile=RELEASE1_LENS_PROFILE,
        )


# ===========================================================================
# Real production ordering through the canonical entrypoint
# ===========================================================================


def _entry_patches(tmp_path, *, dry_run=True, from_package=False):
    argv, patches = legacy._base_patches(dry_run=dry_run, from_package=from_package)
    patches["PACKAGES_DIR"] = tmp_path
    del patches["execute_and_persist_research"]
    del patches["evaluate_and_persist_decision"]
    del patches["load_decision_artifact"]
    return argv, patches


def test_canonical_main_gates_editorial_on_persisted_proceed_decision(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, transport = _evaluator(_model_output())
    generated = patches["generate_article"]

    def assert_decision_precedes_editorial(*args, **kwargs):
        decisions = list(tmp_path.glob("*/runs/*/decision.json"))
        assert len(decisions) == 1  # persisted before any editorial work
        artifact = DecisionLensDecisionArtifact.model_validate_json(
            decisions[0].read_bytes()
        )
        assert artifact.disposition is DecisionDisposition.PROCEED
        return legacy._FAKE_ARTICLE

    generated.side_effect = assert_decision_precedes_editorial
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0
    assert generated.called
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "disposition", ["revise", "hold", "reject", "insufficient_evidence"]
)
def test_non_proceed_blocks_every_downstream_stage(tmp_path, disposition):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output(disposition=disposition))
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1
    # the honest non-PROCEED decision is persisted…
    decisions = list(tmp_path.glob("*/runs/*/decision.json"))
    assert len(decisions) == 1
    # …and zero downstream stages ran
    assert not patches["generate_article"].called          # narrative/editorial
    assert not patches["_load_package_images"].called       # visual/image prep
    assert not patches["WixPublisher"].called               # publishers
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called     # package/history
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_evaluator_failure_blocks_without_synthetic_decision(tmp_path):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(RuntimeError("transport down"))
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1
    assert not list(tmp_path.glob("*/runs/*/decision.json"))
    assert not patches["generate_article"].called
    assert not patches["_load_package_images"].called
    assert not patches["WixPublisher"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_decision_collision_is_a_business_stop(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())

    real_persist = gap.evaluate_and_persist_decision

    def persist_with_preexisting_decision(*args, **kwargs):
        # simulate a collision: decision.json already exists in the run dir
        run_dir = kwargs["run_dir"]
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "decision.json").write_text("{}")
        return real_persist(*args, **kwargs)

    patches["evaluate_and_persist_decision"] = mock.MagicMock(
        side_effect=persist_with_preexisting_decision
    )
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1
    assert not patches["generate_article"].called


# ===========================================================================
# --from-package reuse
# ===========================================================================


def _build_source_run(tmp_path) -> str:
    """Produce one complete PROCEED generation run and return its run_id."""

    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0
    decisions = list(tmp_path.glob("*/runs/*/decision.json"))
    assert len(decisions) == 1
    return decisions[0].parent.name


def _reuse_patches(tmp_path, source_run_id):
    argv, patches = legacy._base_patches(dry_run=True, from_package=True)
    argv = ["prog", "--signal-id", legacy._SIGNAL_ID, "--dry-run",
            "--from-package", "--source-run-id", source_run_id]
    patches["PACKAGES_DIR"] = tmp_path
    del patches["load_research_envelope"]
    del patches["validate_research_envelope"]
    del patches["load_decision_artifact"]
    return argv, patches


def test_from_package_reuses_original_proceed_decision_without_reevaluation(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    decision_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision.json"))
    before = decision_path.read_bytes()

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    counting_evaluator, transport = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(decision_evaluator=counting_evaluator) == 0
    assert transport.calls == []                     # Decision Lens never re-ran
    assert decision_path.read_bytes() == before      # artifact never rewritten
    assert patches["generate_article"].called is False  # reuse skips generation


def test_from_package_fails_before_side_effects_when_decision_is_missing(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    decision_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision.json"))
    decision_path.unlink()

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 1
    assert not patches["_load_package_images"].called
    assert not patches["generate_article"].called


def test_from_package_fails_for_corrupt_decision(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    decision_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision.json"))
    decision_path.write_text('{"broken":')

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 1
    assert not patches["_load_package_images"].called


def test_from_package_fails_for_non_proceed_original_decision(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    decision_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision.json"))

    # Reconstruct an honest REVISE decision with the same run lineage and
    # substitute it for the original artifact (deliberate fixture surgery).
    strategy = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    from src.research.lifecycle import load_research_envelope, validate_research_envelope
    envelope = load_research_envelope(tmp_path, legacy._SIGNAL_ID, source_run_id)
    research = validate_research_envelope(
        envelope, run_id=source_run_id,
        assignment_id=legacy._SIGNAL_ID, signal_id=legacy._SIGNAL_ID,
        identity=strategy.identity,
        run_started_at=envelope.request.freshness.retrieved_not_before,
        now=datetime.now(timezone.utc),
    )
    audience = strategy.decision_lens_editorial.select_audience("agencies")
    evaluator, _ = _evaluator(_model_output(disposition="revise"))
    result = evaluator.evaluate(
        research=research, strategy_view=strategy.decision_lens_editorial,
        audience=audience, configuration_identity=strategy.identity,
        lens_profile=RELEASE1_LENS_PROFILE, run_id=source_run_id,
        assignment_id=legacy._SIGNAL_ID, signal_id=legacy._SIGNAL_ID,
    )
    assert result.decision is not None
    decision_path.unlink()
    decision_path.write_bytes(result.decision.canonical_bytes())

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 1
    assert not patches["_load_package_images"].called
    assert not patches["generate_article"].called
