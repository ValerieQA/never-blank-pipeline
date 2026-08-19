"""Semantic consumption gates for the corrected Task #41 implementation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from scripts.research.prepare_content import _generate_content_package
from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.never_blank_voice import finalize_article
from src.strategy.business_config import BusinessStrategyConfiguration
from src.strategy.execution_context import StrategyExecutionContext, StrategyExecutionError

import test_generate_and_publish as harness


CONFIG_PATH = Path("strategy/current/business_strategy.json")


def _execution(raw: dict | None = None) -> StrategyExecutionContext:
    data = raw or json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return StrategyExecutionContext.from_configuration(
        BusinessStrategyConfiguration.model_validate(data)
    )


def _lens_output() -> str:
    return json.dumps({
        "core_pattern": "pattern",
        "owner_system_objective": "objective",
        "delivery_vs_presence_conflict": "conflict",
        "customer_memory_consequence": "consequence",
        "structural_cause": "cause",
        "never_blank_insight": "insight",
    })


def _voice_output(cta: str | None = None) -> str:
    return json.dumps({
        "echo_candidates": ["earned echo"], "echo_line": "earned echo",
        "cta_line": cta, "checklist_pass": True, "checklist_notes": "",
    })


def test_proof_point_change_changes_decision_lens_input():
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    first = _execution(raw)
    changed = copy.deepcopy(raw)
    changed["positioning"]["proof_points"][0] = "A materially different proof boundary"
    second = _execution(changed)
    captured: list[str] = []

    def chat(**kwargs):
        captured.append(kwargs["user"])
        return _lens_output()

    with mock.patch("src.editorial.decision_lens_lite.chat", side_effect=chat):
        for execution in (first, second):
            audience = execution.decision_lens_editorial.select_audience("agencies")
            generate_decision_lens({}, execution.decision_lens_editorial, audience)

    assert captured[0] != captured[1]
    assert "available_as_evidence_boundaries_only" in captured[1]
    assert "not permission to invent outcomes" in captured[1]


def test_decision_lens_consumes_claim_boundaries_and_selected_audience():
    execution = _execution()
    audience = execution.decision_lens_editorial.select_audience("consultants")
    with mock.patch(
        "src.editorial.decision_lens_lite.chat", return_value=_lens_output()
    ) as chat:
        generate_decision_lens({}, execution.decision_lens_editorial, audience)
    prompt = chat.call_args.kwargs["user"]
    assert audience.audience_id in prompt and audience.selected_problem in prompt
    assert execution.decision_lens_editorial.positioning.proof_points[0] in prompt
    assert execution.decision_lens_editorial.brand_editorial.preferred_claims[0] in prompt
    assert execution.decision_lens_editorial.brand_editorial.prohibited_claims[0] in prompt
    assert execution.decision_lens_editorial.brand_editorial.legal_factual_reputational_restrictions[0] in prompt
    assert execution.decision_lens_editorial.content.objectives[0] in prompt
    assert execution.decision_lens_editorial.content.territories[0] in prompt


def test_editorial_consumes_voice_principles_claims_restrictions_and_cta_rules():
    execution = _execution()
    view = execution.decision_lens_editorial
    audience = view.select_audience(None)
    cta = view.cta("diagnostic")
    with mock.patch(
        "src.editorial.never_blank_voice.chat", return_value=_voice_output("diagnose it")
    ) as chat:
        result = finalize_article({}, None, {}, {}, {}, {}, {}, "diagnostic", view, audience, cta)
    prompt = chat.call_args.kwargs["user"]
    for value in (
        view.brand_editorial.voice[0],
        view.brand_editorial.editorial_principles[0],
        view.brand_editorial.preferred_claims[0],
        view.brand_editorial.prohibited_claims[0],
        view.brand_editorial.legal_factual_reputational_restrictions[0],
        cta.intent,
        cta.rules[0],
    ):
        assert value in prompt
    assert result["strategy_audience"]["audience_id"] == audience.audience_id
    assert result["strategy_audience"]["selected_problem"] == audience.selected_problem
    assert result["configured_cta"]["rules"] == list(cta.rules)


def test_changing_cta_mode_passes_corresponding_rules_without_discarding_them():
    execution = _execution()
    view = execution.decision_lens_editorial
    audience = view.select_audience(None)
    prompts = []
    with mock.patch(
        "src.editorial.never_blank_voice.chat",
        side_effect=lambda **kwargs: (prompts.append(kwargs["user"]), _voice_output())[1],
    ):
        for mode in ("reflection", "example_request"):
            finalize_article({}, None, {}, {}, {}, {}, {}, mode, view, audience, view.cta(mode))
    assert view.cta("reflection").rules[0] in prompts[0]
    assert view.cta("example_request").rules[0] in prompts[1]
    assert prompts[0] != prompts[1]


def test_exact_normalized_prohibited_claim_fails_closed():
    execution = _execution()
    view = execution.decision_lens_editorial
    audience = view.select_audience(None)
    prohibited = view.brand_editorial.prohibited_claims[0].upper() + "!!!"
    with mock.patch(
        "src.editorial.never_blank_voice.chat", return_value=_voice_output(prohibited)
    ), pytest.raises(ValueError, match="exact prohibited claim"):
        finalize_article({}, None, {}, {}, {}, {}, {}, "reflection", view, audience, view.cta("reflection"))


def test_research_framing_reads_declared_typed_view():
    execution = _execution()
    audience = execution.research.select_audience("msps")
    with mock.patch(
        "scripts.research.prepare_content.chat", return_value="{}"
    ) as chat:
        _generate_content_package({}, execution.research, audience)
    prompt = chat.call_args.args[1]
    assert execution.research.positioning.statement in prompt
    assert execution.research.content.territories[0] in prompt
    assert execution.research.preferred_claims[0] in prompt
    assert execution.research.restrictions[0] in prompt
    assert audience.audience_id in prompt and audience.selected_problem in prompt


def test_audience_selection_uses_declared_alias_and_configured_default():
    execution = _execution()
    supplied = execution.decision_lens_editorial.select_audience("consultants")
    defaulted = execution.decision_lens_editorial.select_audience(None)
    assert supplied.audience_id == "independent-consultants"
    assert supplied.selection_source == "assignment"
    assert defaulted.audience_id == "small-b2b-agencies"
    assert defaulted.selection_source == "configured-default"
    assert supplied.selected_problem and defaulted.selected_problem


def test_unknown_and_ambiguous_audience_fail_closed():
    execution = _execution()
    with pytest.raises(StrategyExecutionError, match="unknown target audience"):
        execution.decision_lens_editorial.select_audience("not configured")

    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["audiences"][1]["selection_terms"].append("shared")
    raw["audiences"][2]["selection_terms"].append("shared")
    ambiguous = _execution(raw)
    with pytest.raises(StrategyExecutionError, match="ambiguous target audience"):
        ambiguous.decision_lens_editorial.select_audience("shared")


def _newest_run_dir(packages_dir):
    runs = [p for p in packages_dir.rglob("runs/*") if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime)


def test_a_research_audience_label_no_longer_blocks_the_canonical_path(tmp_path, capsys):
    """Issue #121 moved this boundary, and the move is the point.

    A discovery label naming no configured audience used to end the run at
    intake — before any research artifact, decision or reasoning existed, so a
    documented mechanism and an irrelevant corporate case were rejected
    identically. The label is source metadata; whether the evidence supports a
    bounded claim for the configured audience is Decision Lens's judgment, and
    the accepted #58 rules still govern it.

    The strict guarantee this test originally protected survives where it
    still applies: an *explicit* unknown or ambiguous audience request still
    fails closed (`tests/test_audience_routing.py`, case D).
    """

    argv, patches = harness._base_patches(dry_run=False)
    patches["PACKAGES_DIR"] = tmp_path
    signal = dict(harness._RAW_SIGNAL, TARGET_AUDIENCE="not configured")
    patches["_load_signal"] = mock.MagicMock(return_value=signal)
    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches):
        main()
    output = capsys.readouterr().out

    # the load-bearing change: the label no longer ends the run at intake
    assert "unknown target audience" not in output

    # and it is preserved as source metadata, never recorded as the selected
    # configured audience
    record = json.loads((_newest_run_dir(tmp_path) / "assignment.json").read_text())
    assert record["assignment"]["target_audience"] == "not configured"
