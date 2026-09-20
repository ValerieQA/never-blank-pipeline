"""#268: Monday's article structure is the client's, and it reaches the writers.

Editorial Policy v2 (#268, on the owner's source of truth in
``clients/never_blank/editorial/reference/12``) replaces the single fixed
eleven-step arc with three separable things: a frame that never changes, a
middle chosen per article from a library of patterns, and standing obligations
whose place in the text is free. The article ends on the Kicker/Echo with
nothing after it (#266), and "one deliberate deviation" becomes a moment of
authorial risk — editorial judgement, with no mechanical check.

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
#: The frame's opening, in the order the client fixed it.
OPENING = ("Dek", "Hook", "Stakes", "Concession")

#: The middle-pattern library: planning tools, never visible in the output.
PATTERNS = ("Finding", "Post-mortem", "Argument", "Explainer", "Teardown")

#: Present somewhere in every article, in no fixed place.
OBLIGATIONS = (
    "A portable noun of our own",
    "Something the reader can check or touch",
    "A working link inside the text",
    "A moment of authorial risk",
    "Subheads",
)


def _structure_text() -> str:
    return load_lens(STRUCTURE).text


def _normalised(value: str) -> str:
    return " ".join(value.split())


# ── the structure is the client's lens, exactly as the owner decided ────────


def test_the_frame_fixes_its_opening_in_order():
    text = _structure_text()

    positions = [text.index(f"{n}. **{element}") for n, element in enumerate(OPENING, start=1)]
    assert positions == sorted(positions)


def test_the_article_ends_on_the_kicker_with_nothing_after_it():
    """#266: the Echo is the last editorial line; the CTA moves inside the text."""
    text = _normalised(_structure_text())

    assert "This is the last editorial line of the article." in text
    assert ("Nothing follows it: no call to action, no \"what do you think?\", no banner, "
            "no sign-off.") in text
    assert "The working link belongs earlier in the text, as an ordinary inline link." in text
    # and the old fixed arc is gone, ending included
    for retired in ("Soft CTA", "11 visible sections", "Compound Presence Connection —"):
        assert retired not in text, retired


def test_the_middle_is_a_library_of_planning_tools_not_a_visible_template():
    text = _normalised(_structure_text())

    for pattern in PATTERNS:
        assert f"**{pattern}**" in text, pattern
    assert "Choose one pattern for the middle before writing" in text
    assert ("They must never be detectable in the output as a template, and their step "
            "names must never appear in the text.") in text
    # front-loading is the default; withholding must be earned
    assert "Front-loading is the default" in text
    assert "Withholding is available where the material earns it" in text
    # and the turn is conditional, not every article
    assert "The turn — the moment the reading flips — is conditional." in text


def test_the_standing_obligations_separate_what_is_owed_from_what_is_decided():
    """Two are always in the article; two are decided every time, and "none"
    is a real answer there — the portable-noun lens says the same (#268)."""
    text = _normalised(_structure_text())

    for obligation in OBLIGATIONS:
        assert obligation in text, obligation
    assert "**Always present**" in text
    assert ("Two are decided every time, and the decision may be that this article "
            "has none") in text
    assert "Never invent one to fill the slot." in text
    assert "Where the material gives the writer nothing to risk, write none" in text
    # the moment of authorial risk is judgement, never a mechanical check (#268)
    assert "This is editorial judgement and nothing checks it mechanically." in text
    assert "deliberate deviation" not in text.casefold()


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
