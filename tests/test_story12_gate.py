"""Story #12 acceptance gate (Issue #61).

Proves, through the real Release 1 production entrypoint, that the system
behaves as one coherent business process:

    current research → Decision Lens evaluation → canonical immutable decision
    → persisted/reloaded business gate → downstream work only for PROCEED.

The gate reuses the production behavior delivered by Issues #58/#59/#60 and
the shared entrypoint harness — no parallel Story #12 orchestration path, no
reimplemented Decision Lens logic, no live LLM/network/publication calls.

Run with: python3 -m pytest -m story12
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial.decision_contract import (
    DecisionDisposition,
    DecisionLensDecisionArtifact,
)
from src.editorial.decision_lens_evaluator import DecisionLensTransportTimeout
from src.editorial.decision_lifecycle import (
    RELEASE1_LENS_PROFILE,
    DecisionGateError,
    load_decision_artifact,
)
from src.research.evidence import EvidenceDisposition, NormalizedResearchArtifact
from src.research.lifecycle import (
    load_research_envelope,
    validate_research_envelope,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import (
    _entry_patches,
    _evaluator,
    _model_output,
    _build_source_run,
    _reuse_patches,
)
from tests.test_research_artifact_lifecycle import ReadyProvider


pytestmark = pytest.mark.story12


def _run_main(tmp_path, *, evaluator, provider=None, dry_run=True, argv=None,
              patches_hook=None):
    argv_default, patches = _entry_patches(tmp_path, dry_run=dry_run)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    if patches_hook is not None:
        patches_hook(patches)
    with mock.patch.object(sys, "argv", argv or argv_default), \
            mock.patch.multiple(gap, **patches):
        code = main(
            research_provider=provider or ReadyProvider(),
            decision_evaluator=evaluator,
        )
    return code, patches


def _assert_zero_downstream(tmp_path, patches):
    """No narrative/editorial, visual, package, publisher, or history effects."""

    assert not patches["generate_article"].called          # narrative/editorial/hook/story/voice
    assert not patches["_load_package_images"].called       # visual/platform image preparation
    assert not patches["WixPublisher"].called               # Wix publisher
    assert not patches["LinkedInPublisher"].called          # LinkedIn publisher
    assert not patches["append_published_entry"].called     # publication/history effects
    assert not list(tmp_path.glob("*/runs/*/generated.json"))  # generated package
    assert not list(tmp_path.glob("*/runs/*/publication_results.json"))


def _current_context():
    strategy = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    audience = strategy.decision_lens_editorial.select_audience("agencies")
    return strategy, audience


def _source_research(tmp_path, source_run_id) -> NormalizedResearchArtifact:
    strategy, _ = _current_context()
    envelope = load_research_envelope(tmp_path, legacy._SIGNAL_ID, source_run_id)
    return validate_research_envelope(
        envelope, run_id=source_run_id,
        assignment_id=legacy._SIGNAL_ID, signal_id=legacy._SIGNAL_ID,
        identity=strategy.identity,
        run_started_at=envelope.request.freshness.retrieved_not_before,
        now=datetime.now(timezone.utc),
    )


# ===========================================================================
# S12-1. Valid continuation: the complete PROCEED lifecycle
# ===========================================================================


def test_s12_proceed_lifecycle_authorizes_downstream_through_production_path(tmp_path):
    evaluator, transport = _evaluator(_model_output())
    generated = None

    def hook(patches):
        nonlocal generated
        generated = patches["generate_article"]

        def decision_precedes_editorial(*args, **kwargs):
            decisions = list(tmp_path.glob("*/runs/*/decision.json"))
            assert len(decisions) == 1  # persisted before any editorial work
            artifact = DecisionLensDecisionArtifact.model_validate_json(
                decisions[0].read_bytes()
            )
            assert artifact.disposition is DecisionDisposition.PROCEED
            return legacy._FAKE_ARTICLE

        generated.side_effect = decision_precedes_editorial

    code, patches = _run_main(tmp_path, evaluator=evaluator, patches_hook=hook)
    assert code == 0
    assert generated.called

    # the actual production Decision Lens boundary was reached exactly once,
    # with the exact trusted research/strategy/audience/execution context
    assert len(transport.calls) == 1
    request = json.loads(transport.calls[0]["request"])
    strategy, audience = _current_context()
    assert request["audience"]["audience_id"] == audience.audience_id
    assert request["strategy_boundaries"]["positioning"] == (
        strategy.decision_lens_editorial.positioning.statement
    )
    assert request["research_evidence"][0]["evidence_id"] == "evidence-1"
    decision_path = next(tmp_path.glob("*/runs/*/decision.json"))
    run_id = decision_path.parent.name
    assert request["execution"]["run_id"] == run_id

    # the persisted artifact strict-reloads and revalidates through the
    # production reuse boundary against the same immutable research lineage
    research = _source_research(tmp_path, run_id)
    reloaded = load_decision_artifact(
        tmp_path, legacy._SIGNAL_ID, run_id,
        research=research, audience=audience,
        configuration_identity=strategy.identity,
        lens_profile=RELEASE1_LENS_PROFILE,
    )
    assert reloaded.disposition is DecisionDisposition.PROCEED
    assert reloaded.canonical_bytes() == decision_path.read_bytes()
    # downstream continuation happened only after that PROCEED
    assert list(tmp_path.glob("*/runs/*/generated.json"))


def test_s12_two_runs_cannot_share_or_overwrite_decision_json(tmp_path):
    first_run = _build_source_run(tmp_path)
    first_path = next(tmp_path.glob(f"*/runs/{first_run}/decision.json"))
    first_bytes = first_path.read_bytes()

    second_run = None
    evaluator, _ = _evaluator(_model_output())
    code, _ = _run_main(tmp_path, evaluator=evaluator)
    assert code == 0
    decisions = sorted(tmp_path.glob("*/runs/*/decision.json"))
    assert len(decisions) == 2  # two runs, two immutable decisions
    run_ids = {p.parent.name for p in decisions}
    assert len(run_ids) == 2
    assert first_path.read_bytes() == first_bytes  # first artifact untouched
    artifacts = [
        DecisionLensDecisionArtifact.model_validate_json(p.read_bytes())
        for p in decisions
    ]
    assert artifacts[0].decision_artifact_id != artifacts[1].decision_artifact_id


# ===========================================================================
# S12-2. Independent execution identities end to end
# ===========================================================================


def test_s12_independent_identities_preserved_research_to_reload(tmp_path):
    """run_id (A), assignment_id (B), signal_id (C) deliberately all differ."""

    from src.research.lifecycle import build_research_request as real_build

    distinct_signal = "distinct-signal-c"
    argv = ["prog", "--signal-id", distinct_signal, "--dry-run"]
    evaluator, transport = _evaluator(_model_output())

    def hook(patches):
        def build_with_distinct_signal(run, assignment, signal, strategy, *, now):
            request = real_build(run, assignment, signal, strategy, now=now)
            return request.model_copy(update={"signal_id": distinct_signal})

        patches["build_research_request"] = mock.MagicMock(
            side_effect=build_with_distinct_signal
        )

    code, _ = _run_main(tmp_path, evaluator=evaluator, argv=argv, patches_hook=hook)
    assert code == 0

    decision_path = next(tmp_path.glob("*/runs/*/decision.json"))
    run_id = decision_path.parent.name  # A
    # research carries C independently of B
    envelope = load_research_envelope(tmp_path, distinct_signal, run_id)
    assert envelope.request.signal_id == distinct_signal
    assert envelope.request.assignment_id == legacy._SIGNAL_ID
    # evaluator input carried A/B/C
    request = json.loads(transport.calls[0]["request"])
    assert request["execution"] == {
        "run_id": run_id,
        "assignment_id": legacy._SIGNAL_ID,
        "signal_id": distinct_signal,
    }
    # persisted decision carries A/B/C
    artifact = DecisionLensDecisionArtifact.model_validate_json(
        decision_path.read_bytes()
    )
    assert (artifact.run_id, artifact.assignment_id, artifact.signal_id) == (
        run_id, legacy._SIGNAL_ID, distinct_signal,
    )
    assert len({artifact.run_id, artifact.assignment_id, artifact.signal_id}) == 3
    # strict reload preserves the same three identities
    strategy, audience = _current_context()
    research = validate_research_envelope(
        envelope, run_id=run_id, assignment_id=legacy._SIGNAL_ID,
        signal_id=distinct_signal, identity=strategy.identity,
        run_started_at=envelope.request.freshness.retrieved_not_before,
        now=datetime.now(timezone.utc),
    )
    reloaded = load_decision_artifact(
        tmp_path, distinct_signal, run_id,
        research=research, audience=audience,
        configuration_identity=strategy.identity,
        lens_profile=RELEASE1_LENS_PROFILE,
    )
    assert (reloaded.run_id, reloaded.assignment_id, reloaded.signal_id) == (
        run_id, legacy._SIGNAL_ID, distinct_signal,
    )


# ===========================================================================
# S12-3. Business stops: canonical non-success dispositions
# ===========================================================================


@pytest.mark.parametrize(
    "disposition", ["revise", "hold", "reject", "insufficient_evidence"]
)
def test_s12_non_success_disposition_is_a_business_stop(tmp_path, disposition):
    evaluator, _ = _evaluator(_model_output(disposition=disposition))
    code, patches = _run_main(tmp_path, evaluator=evaluator, dry_run=False)
    assert code == 1
    # the honest canonical business decision is persisted…
    decisions = list(tmp_path.glob("*/runs/*/decision.json"))
    assert len(decisions) == 1
    artifact = DecisionLensDecisionArtifact.model_validate_json(
        decisions[0].read_bytes()
    )
    assert artifact.disposition.value == disposition
    # …with zero downstream effects
    _assert_zero_downstream(tmp_path, patches)


# ===========================================================================
# S12-4. Fail-closed invalid and system outcomes
# ===========================================================================


def test_s12_blocked_evidence_contract_violation_stops(tmp_path):
    """PROCEED citing rejected research evidence cannot continue."""

    provider = ReadyProvider(disposition=EvidenceDisposition.REJECTED)
    evaluator, _ = _evaluator(_model_output())
    code, patches = _run_main(
        tmp_path, evaluator=evaluator, provider=provider, dry_run=False
    )
    assert code == 1
    assert not list(tmp_path.glob("*/runs/*/decision.json"))
    _assert_zero_downstream(tmp_path, patches)


def test_s12_unsupported_claim_cannot_proceed(tmp_path):
    output = _model_output()
    output["evidence_ids"] = []
    output["source_ids"] = []
    output["relevance_bases"][0]["evidence_ids"] = []
    output["relevance_bases"][0]["source_ids"] = []
    output["criterion_results"] = []
    evaluator, _ = _evaluator(output)
    code, patches = _run_main(tmp_path, evaluator=evaluator, dry_run=False)
    assert code == 1
    _assert_zero_downstream(tmp_path, patches)


def test_s12_invalid_citation_stops(tmp_path):
    output = _model_output()
    output["evidence_ids"] = ["evidence-invented"]
    output["relevance_bases"][0]["evidence_ids"] = ["evidence-invented"]
    output["criterion_results"][0]["evidence_ids"] = ["evidence-invented"]
    evaluator, _ = _evaluator(output)
    code, patches = _run_main(tmp_path, evaluator=evaluator, dry_run=False)
    assert code == 1
    assert not list(tmp_path.glob("*/runs/*/decision.json"))
    _assert_zero_downstream(tmp_path, patches)


@pytest.mark.parametrize(
    "payload",
    [
        "this is not json {",
        RuntimeError("provider exploded"),
        DecisionLensTransportTimeout("no response"),
    ],
    ids=["malformed-output", "transport-error", "transport-timeout"],
)
def test_s12_malformed_output_and_evaluator_failure_stop(tmp_path, payload):
    evaluator, _ = _evaluator(payload)
    code, patches = _run_main(tmp_path, evaluator=evaluator, dry_run=False)
    assert code == 1
    # evaluator/system failure never produces a synthetic decision artifact
    assert not list(tmp_path.glob("*/runs/*/decision.json"))
    _assert_zero_downstream(tmp_path, patches)


def test_s12_lineage_mismatches_fail_closed_at_the_production_boundary(tmp_path):
    """Cross-run, digest, audience, configuration, and profile mismatch."""

    source_run_id = _build_source_run(tmp_path)
    strategy, audience = _current_context()
    research = _source_research(tmp_path, source_run_id)

    # audience mismatch
    with pytest.raises(DecisionGateError):
        load_decision_artifact(
            tmp_path, legacy._SIGNAL_ID, source_run_id,
            research=research,
            audience=audience.model_copy(update={"audience_id": "other-audience"}),
            configuration_identity=strategy.identity,
            lens_profile=RELEASE1_LENS_PROFILE,
        )
    # configuration mismatch
    with pytest.raises(DecisionGateError):
        load_decision_artifact(
            tmp_path, legacy._SIGNAL_ID, source_run_id,
            research=research, audience=audience,
            configuration_identity=strategy.identity.model_copy(
                update={"configuration_hash": "sha256:" + "b" * 64}
            ),
            lens_profile=RELEASE1_LENS_PROFILE,
        )
    # lens profile mismatch
    with pytest.raises(DecisionGateError):
        load_decision_artifact(
            tmp_path, legacy._SIGNAL_ID, source_run_id,
            research=research, audience=audience,
            configuration_identity=strategy.identity,
            lens_profile=RELEASE1_LENS_PROFILE.model_copy(
                update={"lens_profile_version": "9.9"}
            ),
        )
    # cross-run / research-digest mismatch: a second run's research cannot
    # revalidate the first run's decision
    evaluator, _ = _evaluator(_model_output())
    code, _ = _run_main(tmp_path, evaluator=evaluator)
    assert code == 0
    other_run_id = next(
        p.parent.name
        for p in tmp_path.glob("*/runs/*/decision.json")
        if p.parent.name != source_run_id
    )
    other_research = _source_research(tmp_path, other_run_id)
    with pytest.raises(DecisionGateError):
        load_decision_artifact(
            tmp_path, legacy._SIGNAL_ID, source_run_id,
            research=other_research, audience=audience,
            configuration_identity=strategy.identity,
            lens_profile=RELEASE1_LENS_PROFILE,
        )


# ===========================================================================
# S12-5. --from-package reuse acceptance
# ===========================================================================


def test_s12_reuse_preserves_original_decision_without_reevaluation(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    decision_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision.json"))
    research_path = next(tmp_path.glob(f"*/runs/{source_run_id}/research.json"))
    decision_before = decision_path.read_bytes()
    research_before = research_path.read_bytes()

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    counting_evaluator, transport = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(decision_evaluator=counting_evaluator) == 0
    assert transport.calls == []                      # Decision Lens never re-ran
    assert decision_path.read_bytes() == decision_before   # never rewritten
    assert research_path.read_bytes() == research_before


@pytest.mark.parametrize("corruption", ["missing", "corrupt", "non_canonical"])
def test_s12_invalid_source_decision_blocks_reuse_before_side_effects(
    tmp_path, corruption
):
    source_run_id = _build_source_run(tmp_path)
    decision_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision.json"))
    if corruption == "missing":
        decision_path.unlink()
    elif corruption == "corrupt":
        decision_path.write_text('{"broken":')
    else:
        artifact = DecisionLensDecisionArtifact.model_validate_json(
            decision_path.read_bytes()
        )
        decision_path.write_text(
            json.dumps(json.loads(artifact.canonical_json()), indent=2)
        )

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 1
    assert not patches["_load_package_images"].called
    assert not patches["generate_article"].called
    assert not patches["append_published_entry"].called


# ===========================================================================
# S12-6. Security / trust: nothing raw enters persisted artifacts
# ===========================================================================


def test_s12_no_prompts_secrets_or_provider_objects_in_persisted_artifacts(tmp_path):
    evaluator, transport = _evaluator(_model_output())
    code, _ = _run_main(tmp_path, evaluator=evaluator)
    assert code == 0
    decision_text = next(tmp_path.glob("*/runs/*/decision.json")).read_text()
    # the maintained instruction text never enters the artifact
    instruction_text = transport.calls[0]["instructions"]
    assert instruction_text not in decision_text
    # no provider/raw/secret shapes in the persisted canonical artifact
    for forbidden in ("raw_provider", "api_key", "sk-", "Authorization",
                      "model_response", "prompt"):
        assert forbidden not in decision_text
    # canonical schema only: strict reload succeeds byte-for-byte
    artifact = DecisionLensDecisionArtifact.model_validate_json(decision_text)
    assert artifact.canonical_json() == decision_text


def test_s12_credentialed_evaluator_failure_leaks_nothing(tmp_path):
    evaluator, _ = _evaluator(RuntimeError("api_key=sk-abcdefghijklmnop leaked"))
    code, patches = _run_main(tmp_path, evaluator=evaluator, dry_run=False)
    assert code == 1
    # nothing persisted anywhere in the run namespace carries the secret
    for path in tmp_path.rglob("*.json"):
        assert "sk-abcdefghijklmnop" not in path.read_text()
    _assert_zero_downstream(tmp_path, patches)
