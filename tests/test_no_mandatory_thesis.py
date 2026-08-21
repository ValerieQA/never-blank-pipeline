"""No universal Never Blank thesis is injected into generation (#157).

The deterministic keyword gate was only the last enforcement point. The
generation prompts themselves required every article to resolve to Compound
Presence — the composer demanded it "must be semantically present", the voice
checklist failed an article without it, and the extractor, lens, spine, hook
and story stages all instructed the model to find a *visibility* pattern
whatever the evidence showed. An article about pricing or regulation could not
survive that path, whatever the role configuration said.

These tests assert the *semantics* are gone rather than one exact phrase, and
that what replaced them is evidence-led rather than a second house doctrine.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.editorial import (
    decision_lens_lite,
    hook_engine,
    narrative_spine,
    never_blank_voice,
    pattern_extractor,
    platform_composer,
    story_assembly,
)
from src.editorial.platform_composer import _build_user_prompt

#: Every generation stage whose prompt could carry a universal thesis.
GENERATION_STAGES = (
    pattern_extractor, decision_lens_lite, narrative_spine, hook_engine,
    story_assembly, never_blank_voice, platform_composer,
)

#: Mandatory-thesis semantics, not a single phrase: any of these in a prompt
#: means the model is being told what the article must conclude.
MANDATORY_SEMANTICS = (
    "compound presence",
    "must be semantically present",
    "visibility pattern",
    "presence system",
    "owner's presence",
)


def _module_prompts(module) -> str:
    """Every prompt-ish constant and instruction string a stage carries."""

    text = Path(module.__file__).read_text(encoding="utf-8")
    return text.lower()


@pytest.mark.parametrize(
    "module", GENERATION_STAGES, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
@pytest.mark.parametrize("mandate", MANDATORY_SEMANTICS)
def test_no_generation_stage_mandates_a_thesis(module, mandate):
    assert mandate not in _module_prompts(module)


def test_the_composer_arc_no_longer_contains_a_mandatory_connection():
    prompt = platform_composer._SYSTEM_PROMPT  # noqa: SLF001

    assert "Compound Presence Connection" not in prompt
    # and the arc is intact otherwise
    for beat in ("Hook", "Recognition", "Tension", "Mechanism",
                 "Business Consequence", "Reframe", "Echo"):
        assert beat in prompt


def test_the_replacement_is_evidence_led_not_a_second_doctrine():
    # the prompt is hard-wrapped, so compare on normalized whitespace
    prompt = " ".join(platform_composer._SYSTEM_PROMPT.lower().split())  # noqa: SLF001

    assert "whichever one the evidence for this run most strongly supports" in prompt
    assert "do not substitute a house thesis" in prompt
    assert "the configured editorial role decides what this article argues" in prompt
    # the alternatives are named so no single mechanism is privileged
    for mechanism in ("pricing", "capacity", "supply", "regulation",
                      "distribution", "operations", "presence"):
        assert mechanism in prompt


def test_the_voice_checklist_no_longer_fails_an_article_without_the_thesis():
    prompt = never_blank_voice._SYSTEM_PROMPT.lower()  # noqa: SLF001

    assert "compound presence" not in prompt
    assert "resolves the mechanism it revealed into a consequence" in prompt
    # house voice rules that never depended on the thesis are preserved
    assert "echo" in prompt


def test_the_extractor_asks_what_happened_not_what_visibility_pattern():
    prompt = pattern_extractor._SYSTEM_PROMPT  # noqa: SLF001

    assert "What happened here that a small business owner would recognize" in prompt
    assert "Do not force the material into a presence or visibility frame" in prompt
    # the downstream field contract is deliberately unchanged
    assert '"visibility_pattern": "string"' in prompt
    # structural purpose preserved: the gate still rejects unusable signals
    assert "signal_fit" in prompt and "reject" in prompt
    assert "article_protagonist" in prompt


def test_the_extractor_examples_span_more_than_one_mechanism():
    prompt = pattern_extractor._SYSTEM_PROMPT.lower()  # noqa: SLF001

    assert "price rations the constraint" in prompt
    assert "capacity added ahead of demand" in prompt
    # a presence example remains available, not privileged
    assert "visibility work is displaced by urgent delivery work" in prompt


# ---------------------------------------------------------------------------
# The five required end-to-end regressions, through the real prompt builder
# ---------------------------------------------------------------------------

def _role_rules(role_id: str, surface: str) -> str:
    from src.editorial.editorial_role import (
        render_editorial_role_rules,
        resolve_editorial_role,
    )
    from src.strategy.business_config import load_business_strategy_configuration

    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    _, role = resolve_editorial_role(configuration, role_id)
    return render_editorial_role_rules(role, surface=surface)


def _composed_prompt(article: dict, role_id: str, surface: str, format_key: str) -> str:
    return _build_user_prompt(
        article, format_key, "reflection", (),
        editorial_role_rules=_role_rules(role_id, surface),
    )


PRICING_CASE = {
    "hook": "The bakery raised prices twice and lost no orders.",
    "narrative_spine": "Price was rationing the wrong constraint.",
    "surviving_explanation": "Oven capacity, not demand, set the ceiling.",
    "reframe": "The queue was a capacity signal read as a demand signal.",
    "business_translation": "Price for the binding constraint.",
    "discovery": {}, "echo_line": "A queue is not always demand.",
}

REGULATION_CASE = {
    "hook": "A licensing change rewrote who could bid.",
    "narrative_spine": "The rule moved the market, not the marketing.",
    "surviving_explanation": "Compliance cost became the entry barrier.",
    "reframe": "The obvious reading was competition; the mechanism was regulation.",
    "business_translation": "Check which rule sets your addressable work.",
    "discovery": {}, "echo_line": "Rules pick winners before markets do.",
}

PRESENCE_CASE = {
    "hook": "The busiest month was the quietest month publicly.",
    "narrative_spine": "Delivery displaced visibility.",
    "surviving_explanation": "Presence work is non-urgent until it is missing.",
    "reframe": "Silence read as unavailability.",
    "business_translation": "Consistent presence accumulates into recognition.",
    "discovery": {}, "echo_line": "Customers rarely decide to forget you.",
}


@pytest.mark.parametrize("format_key,surface", [("long", "wix"), ("medium", "linkedin")])
def test_A_monday_pricing_case_reaches_composition_with_no_thesis_injected(
    format_key, surface
):
    prompt = _composed_prompt(
        PRICING_CASE, "never-blank-monday-documented-case", surface, format_key
    ).lower()

    for mandate in MANDATORY_SEMANTICS:
        assert mandate not in prompt or "only where the material earns it" in prompt
    assert "must be semantically present" not in prompt
    # the run's own material, not a house conclusion
    assert "oven capacity" in prompt


@pytest.mark.parametrize("format_key,surface", [("long", "wix"), ("medium", "linkedin")])
def test_B_wednesday_regulation_case_reaches_composition_under_its_movement(
    format_key, surface
):
    prompt = _composed_prompt(
        REGULATION_CASE, "never-blank-wednesday-golden", surface, format_key
    ).lower()

    assert "must be semantically present" not in prompt
    assert "compliance cost" in prompt
    # the Golden contract still governs the article
    assert "golden" in prompt or "overlooked" in prompt or "one mechanism" in prompt


def test_C_a_presence_supported_case_can_still_use_the_lens():
    prompt = _composed_prompt(
        PRESENCE_CASE, "never-blank-monday-documented-case", "wix", "long"
    ).lower()

    # the material's own presence language survives untouched…
    assert "consistent presence accumulates into recognition" in prompt
    # …and the role still offers the lens as available, not required
    assert "only where the material earns it" in prompt


def test_D_role_specific_rules_still_reach_the_real_prompts():
    monday = _composed_prompt(
        PRICING_CASE, "never-blank-monday-documented-case", "wix", "long"
    )
    wednesday = _composed_prompt(
        REGULATION_CASE, "never-blank-wednesday-golden", "wix", "long"
    )

    assert "never-blank-monday-documented-case" in monday
    assert "never-blank-wednesday-golden" in wednesday
    assert "https://www.inneros.online" in monday
    # each role's own rules, not a shared house thesis
    assert "never-blank-wednesday-golden" not in monday
    assert "never-blank-monday-documented-case" not in wednesday


def test_E_evidence_transparency_acceptance_and_publish_validation_are_intact():
    from src.editorial.editorial_acceptance import EditorialAcceptanceRubric
    from src.editorial.source_transparency import validate_source_transparency
    from src.strategy.business_config import load_business_strategy_configuration
    from src.strategy.validators import validate_article_for_publish

    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    roles = {role.role_id: role for role in configuration.editorial_roles}

    # Monday still requires source transparency; Wednesday still has its rubric
    assert roles["never-blank-monday-documented-case"].require_source_transparency
    assert (
        roles["never-blank-wednesday-golden"].acceptance_rubric_identity
        == "never-blank-golden-wednesday-acceptance/1.0"
    )
    assert EditorialAcceptanceRubric.load().identity == (
        "never-blank-editorial-acceptance/1.0"
    )
    # the transparency validator still refuses unattributed prose
    from tests import test_decision_lens_evaluator as evaluator_fixtures
    from src.editorial.source_transparency import SourceTransparencyError

    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body="An article that cites nothing.",
            linkedin_body="Nor does this.",
            research=evaluator_fixtures._research(),  # noqa: SLF001
        )
    # deterministic publish validation still fails on empty prose
    with pytest.raises(ValueError):
        validate_article_for_publish("", platform="blog")


def test_wednesday_evidence_and_mechanism_guarantees_survive():
    from src.never_blank.wednesday_golden import WednesdayGoldenProfile

    policy = WednesdayGoldenProfile.load().source_policy

    assert policy.require_evidence_supporting_y is True
    assert policy.require_overlooked_y is True
    assert policy.required_primary_mechanisms == 1
    assert policy.required_transfer_mode.value == "bounded_business_question"
