"""#254 D4: Monday's article structure is the client's, and it reaches the writers.

Product Owner decision D4 (#254): the current 11-step arc is CLIENT: NEVER_BLANK's
editorial structure — a narrative framework, not 11 visible sections — and step 9,
Compound Presence Connection, is conditional: never manufactured to satisfy the
structure. #252 is the future editorial refinement with Sveta.

Under D12 (#240) the structure is client policy, so it lives in the client's
writing lens ``clients/never_blank/lenses/structure.md``, and the Engine's own
composer prompt no longer carries an arc of its own. These tests prove both
halves, and that the lens reaches the exact composer messages for both published
surfaces — through the real entrypoint and through the real composer.

No network, no model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from src.editorial.editorial_role import render_editorial_role_rules, resolve_editorial_role
from src.editorial.platform_composer import compose_platforms
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.client_contracts import contracts_for_role, load_lens
from tests.test_decision_lifecycle import _evaluator, _model_output
from tests.test_monday_stream import MONDAY_ROLE, _attributed_article, _entry_patches
from tests.test_research_artifact_lifecycle import ReadyProvider

STRUCTURE = Path("clients/never_blank/lenses/structure.md")
STEPS = (
    "Hook", "Recognition", "Tension", "Market Observation", "Investigation",
    "Mechanism", "Business Consequence", "Reframe", "Compound Presence Connection",
    "Echo", "Soft CTA",
)


def _structure_text() -> str:
    return load_lens(STRUCTURE).text


def _normalised(value: str) -> str:
    return " ".join(value.split())


# ── the structure is the client's lens, exactly as the owner decided ────────


def test_the_structure_lens_names_the_eleven_steps_in_order():
    text = _structure_text()

    positions = [text.index(f"{number}. {step}") for number, step in enumerate(STEPS, start=1)]
    assert positions == sorted(positions)


def test_the_structure_is_a_narrative_framework_not_visible_sections():
    assert "this is a narrative framework, not a requirement to manufacture 11 visible sections" in (
        _normalised(_structure_text())
    )


def test_step_nine_is_conditional_and_never_manufactured():
    text = _normalised(_structure_text())

    assert "Compound Presence Connection — conditional." in text
    assert "Include it only when the article genuinely supports a meaningful connection" in text
    assert ("If that connection would be artificial, generic, promotional, or require "
            "changing the actual lesson of the signal, omit it.") in text
    assert ("Never manufacture a Compound Presence connection merely to satisfy the "
            "structure.") in text
    assert "Steps 1–8, 10 and 11 form the normal narrative arc." in text


def test_the_structure_reaches_the_writers_and_nothing_else():
    lens = load_lens(STRUCTURE)
    contracts = contracts_for_role(MONDAY_ROLE)

    assert lens.stages == ("writing",)
    assert lens.text in contracts.for_stage("writing")
    assert lens.text not in contracts.selection_requirements
    assert lens.text not in contracts.for_stage("revision")


# ── the Engine no longer carries an arc of its own ──────────────────────────


def test_the_composer_prompt_carries_no_arc_of_its_own():
    """Two arcs would contradict each other; the Engine's was the client's (#240 D12)."""
    prompt = platform_composer._SYSTEM_PROMPT  # noqa: SLF001

    assert "Hook → Recognition" not in prompt
    assert "Soft CTA" not in prompt
    assert "Compound Presence" not in prompt
    assert "client lenses" in prompt


# ── it reaches the exact composer messages for both published surfaces ──────


def test_the_entrypoint_hands_the_structure_to_both_published_surfaces(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    generated = mock.MagicMock(return_value=_attributed_article())
    patches["generate_article"] = generated
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    rules = generated.call_args.kwargs["editorial_role_rules"]
    for format_key in ("long", "medium"):
        assert _structure_text() in rules[format_key], format_key


def test_the_structure_reaches_the_composer_model_message(monkeypatch):
    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    _, role = resolve_editorial_role(configuration, MONDAY_ROLE)
    writing = contracts_for_role(MONDAY_ROLE).for_stage("writing")
    rules = {
        "long": render_editorial_role_rules(role, surface="wix", lenses=writing),
        "medium": render_editorial_role_rules(role, surface="linkedin", lenses=writing),
    }
    seen: dict[str, str] = {}

    def fake_chat(*, system, user, **kwargs):
        format_key = next(
            line.split(":", 1)[1].strip() for line in user.splitlines()
            if line.startswith("FORMAT:")
        )
        seen[format_key] = f"{system}\n{user}"
        return json.dumps({"body": "Body. Echo line.", "echo_included": True,
                           "title": "T" if format_key == "long" else None})

    monkeypatch.setattr(platform_composer, "chat", fake_chat)
    compose_platforms(
        {"hook": "h", "discovery": {}, "echo_line": "Echo line."},
        cta_mode="none", editorial_role_rules=rules, formats=("long", "medium"),
    )

    for format_key in ("long", "medium"):
        message = seen[format_key]
        assert _structure_text() in message, format_key
        assert "Hook → Recognition" not in message, "the Engine's own arc leaked back"
