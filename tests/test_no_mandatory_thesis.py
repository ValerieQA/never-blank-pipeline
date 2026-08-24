"""Canonical semantic regressions for the Issue #157 product decision.

The real editorial pipeline runs with validated production strategy and declared
role rules. Only provider transports are deterministic fakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.editorial import (
    decision_lens_lite,
    discovery_builder,
    hook_engine,
    narrative_spine,
    never_blank_voice,
    pattern_extractor,
    platform_composer,
    reader_context,
    story_assembly,
)
from src.editorial.decision_lens_evaluator import DecisionLensInstructions
from src.editorial.editorial_role import render_editorial_role_rules, resolve_editorial_role
from src.editorial.pipeline import generate_article
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext


FORCED_DOCTRINE = (
    "the owner-level visibility/presence pattern",
    "the specific tension between client work and visibility work",
    "what happens to customer memory specifically",
    "uncomfortable truth about visibility",
    "what this visibility pattern means",
    "connect every mechanism to consistent presence",
    "consistent presence is what turns attention",
    "nb-owner-presence",
    "nb-customer-memory",
)


CASES = (
    pytest.param(
        "never-blank-monday-documented-case",
        "pricing",
        "Price is rationing scarce capacity rather than measuring demand.",
        id="monday-pricing",
    ),
    pytest.param(
        "never-blank-wednesday-golden",
        "regulation",
        "A licensing threshold changed access before competitors changed strategy.",
        id="wednesday-regulation",
    ),
)


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _assert_no_forced_doctrine(value: str) -> None:
    prompt = _normalized(value)
    for mandate in FORCED_DOCTRINE:
        assert mandate not in prompt


def _chat_capture(calls: dict[str, list[str]], stage: str, payload: dict):
    def fake(*args, **kwargs):
        system = kwargs.get("system", args[0] if args else "")
        user = kwargs.get("user", args[1] if len(args) > 1 else "")
        calls.setdefault(stage, []).append(f"SYSTEM:\n{system}\nUSER:\n{user}")
        return json.dumps(payload)

    return fake


def _platform_chat(calls: dict[str, list[str]], echo: str):
    def fake(*args, **kwargs):
        system = kwargs.get("system", args[0] if args else "")
        user = kwargs.get("user", args[1] if len(args) > 1 else "")
        calls.setdefault("platform_composer", []).append(
            f"SYSTEM:\n{system}\nUSER:\n{user}"
        )
        format_key = next(
            line.split(":", 1)[1].strip()
            for line in user.splitlines()
            if line.startswith("FORMAT:")
        )
        counts = {"long": 260, "reading": 220, "medium": 120, "instagram": 80, "short": 30}
        body = "Evidence-led opening. " + " ".join(
            f"{format_key}{index}" for index in range(counts[format_key])
        )
        if format_key in {"long", "reading"}:
            body = f"{body}\n\n{echo}"
        return json.dumps(
            {
                "body": body,
                "echo_included": True,
                "title": "The Constraint Hidden Inside the Queue" if format_key == "long" else None,
            }
        )

    return fake


def _run_real_prompt_path(monkeypatch, role_id: str, mechanism: str, pattern: str):
    calls: dict[str, list[str]] = {}
    echo = f"The {mechanism} constraint was visible before it was named."

    monkeypatch.setattr(
        pattern_extractor,
        "chat",
        _chat_capture(calls, "pattern_extractor", {
            "visibility_pattern": pattern,
            "founder_scenario": f"An owner sees {mechanism} reshape the next decision.",
            "mechanism": mechanism,
            "business_consequence": f"The {mechanism} constraint changes commercial choices.",
            "company_as_evidence_of": f"The documented case demonstrates the {mechanism} constraint.",
            "evidence_limit": "The external outcome is not asserted for another business.",
            "article_protagonist": "owner",
            "signal_fit": "use",
            "rejection_reason": None,
        }),
    )
    monkeypatch.setattr(
        decision_lens_lite,
        "chat",
        _chat_capture(calls, "decision_lens_lite", {
            "core_pattern": pattern,
            "owner_system_objective": f"The system optimizes around {mechanism}.",
            "delivery_vs_presence_conflict": f"The primary tension is governed by {mechanism}.",
            "customer_memory_consequence": f"The supported commercial consequence follows from {mechanism}.",
            "structural_cause": f"The {mechanism} constraint repeats under the documented conditions.",
            "never_blank_insight": f"The obvious reading concealed the {mechanism} constraint.",
        }),
    )
    monkeypatch.setattr(
        narrative_spine,
        "chat",
        _chat_capture(calls, "narrative_spine", {
            "core_pattern": pattern,
            "narrative_spine": f"The apparent demand story was a {mechanism} story.",
            "target_feeling": "reframe",
            "pattern_as_evidence_of": f"The evidence reveals a {mechanism} mechanism.",
        }),
    )
    hooks = [
        {"type": kind, "text": f"Hook {index} names the {mechanism} tension."}
        for index, kind in enumerate(
            ("hidden_cost", "invisible_pattern", "false_comfort", "timing_contradiction", "accumulated_effect"),
            start=1,
        )
    ]
    monkeypatch.setattr(
        hook_engine,
        "chat",
        _chat_capture(calls, "hook_engine", {
            "hook_candidates": hooks,
            "selected_hook": hooks[0]["text"],
        }),
    )
    monkeypatch.setattr(
        reader_context,
        "chat",
        _chat_capture(calls, "reader_context", {
            "context_line": "The company operates in a documented commercial market."
        }),
    )
    monkeypatch.setattr(
        discovery_builder,
        "chat",
        _chat_capture(calls, "discovery_builder", {
            "first_wrong_explanation": "The obvious reading was demand.",
            "puzzle": f"The documented facts instead point to {mechanism}.",
            "investigation_sequence": [
                "The case establishes the observable event.",
                f"The evidence identifies {mechanism} as the primary mechanism.",
            ],
            "aha_setup": f"An owner can examine where {mechanism} governs the same decision.",
        }),
    )
    monkeypatch.setattr(
        story_assembly,
        "chat",
        _chat_capture(calls, "story_assembly", {
            "surviving_explanation": f"The supported explanation is {mechanism}.",
            "reframe": f"The event was misread until the {mechanism} constraint was isolated.",
            "remaining_uncertainty": "The evidence does not establish the same outcome elsewhere.",
            "business_translation": f"Another owner can examine where {mechanism} shapes the decision.",
        }),
    )
    monkeypatch.setattr(
        never_blank_voice,
        "chat",
        _chat_capture(calls, "never_blank_voice", {
            "echo_candidates": [echo],
            "echo_line": echo,
            "cta_line": "Examine the mechanism in your own business at https://www.inneros.online.",
            "checklist_pass": True,
            "checklist_notes": "",
        }),
    )
    monkeypatch.setattr(platform_composer, "chat", _platform_chat(calls, echo))

    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    strategy = StrategyExecutionContext.from_configuration(configuration)
    audience = strategy.decision_lens_editorial.select_audience(None)
    _, role = resolve_editorial_role(configuration, role_id)
    role_rules = {
        "long": render_editorial_role_rules(role, surface="wix"),
        "medium": render_editorial_role_rules(role, surface="linkedin"),
    }
    result = generate_article(
        {
            "SIGNAL_ID": f"signal-{mechanism}",
            "HEADLINE": f"A documented {mechanism} case",
            "CORE_FACT": pattern,
            "CORE_TENSION": f"The public reading obscured {mechanism}.",
            "REAL_COMPANY_EXAMPLE": "Documented Company",
            "NEVER_BLANK_ANGLE": f"Test whether {mechanism} is the supported interpretation.",
            "TARGET_AUDIENCE": audience.audience_name,
        },
        cta_mode="reflection",
        strategy_context=strategy.decision_lens_editorial,
        wix_strategy=strategy.wix,
        linkedin_strategy=strategy.linkedin,
        audience_selection=audience,
        editorial_role_rules=role_rules,
    )
    return calls, result


def test_maintained_decision_lens_profile_is_mechanism_neutral_and_versioned():
    instructions = DecisionLensInstructions.load()
    prompt = _normalized(instructions.instructions)

    assert instructions.profile_version == "1.2"
    assert instructions.version == "1.2"
    assert "nb-supported-mechanism" in prompt
    assert "nb-supported-business-consequence" in prompt
    assert "none is required by this profile" in prompt
    _assert_no_forced_doctrine(prompt)


@pytest.mark.parametrize("role_id,mechanism,pattern", CASES)
def test_real_canonical_prompt_path_uses_run_mechanism_and_actual_strategy_rules(
    monkeypatch, role_id, mechanism, pattern
):
    calls, result = _run_real_prompt_path(monkeypatch, role_id, mechanism, pattern)

    assert result["pattern"]["mechanism"] == mechanism
    assert result["structured_article"]["surviving_explanation"] == (
        f"The supported explanation is {mechanism}."
    )
    for stage in (
        "pattern_extractor", "decision_lens_lite", "narrative_spine",
        "hook_engine", "discovery_builder", "story_assembly",
        "never_blank_voice", "platform_composer",
    ):
        prompt = "\n".join(calls[stage])
        assert mechanism in prompt.casefold()
        _assert_no_forced_doctrine(prompt)

    composition = "\n".join(calls["platform_composer"])
    assert "CONFIGURED CHANNEL RULES:" in composition
    assert "https://www.inneros.online" in composition
    assert role_id in composition
    if role_id == "never-blank-wednesday-golden":
        assert "one primary mechanism" in composition.casefold()
        assert "overlooked y" in composition.casefold()


def test_presence_supported_case_remains_available_without_becoming_a_mandate(monkeypatch):
    calls, result = _run_real_prompt_path(
        monkeypatch,
        "never-blank-monday-documented-case",
        "presence",
        "Delivery displaced an evidence-supported communication cadence.",
    )

    assert result["pattern"]["mechanism"] == "presence"
    assert "presence" in "\n".join(calls["platform_composer"]).casefold()
    for prompts in calls.values():
        _assert_no_forced_doctrine("\n".join(prompts))


def test_safety_and_wednesday_golden_boundaries_remain_intact():
    from src.editorial.editorial_acceptance import EditorialAcceptanceRubric
    from src.editorial.source_transparency import SourceTransparencyError, validate_source_transparency
    from src.never_blank.wednesday_golden import WednesdayGoldenProfile
    from src.strategy.validators import validate_article_for_publish
    from tests import test_decision_lens_evaluator as evaluator_fixtures

    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    roles = {role.role_id: role for role in configuration.editorial_roles}
    policy = WednesdayGoldenProfile.load().source_policy

    assert roles["never-blank-monday-documented-case"].require_source_transparency
    assert roles["never-blank-wednesday-golden"].require_source_transparency
    assert policy.require_evidence_supporting_y is True
    assert policy.require_overlooked_y is True
    assert policy.required_primary_mechanisms == 1
    assert policy.required_transfer_mode.value == "bounded_business_question"
    assert EditorialAcceptanceRubric.load().identity == "never-blank-editorial-acceptance/1.0"
    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body="An article that cites nothing.",
            research=evaluator_fixtures._research(),  # noqa: SLF001
        )
    with pytest.raises(ValueError):
        validate_article_for_publish("", platform="blog")
