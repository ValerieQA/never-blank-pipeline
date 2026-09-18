"""#233 F-10: prove configured rules reach the model, not merely the repository.

The audit found four tests reporting a contract as met that production does not
meet. Each proved the weakest thing that is easy to assert — a file exists, an
argument was passed to a patched function, a constructor works in isolation, a
symbol is absent — and production moved underneath three of them without a test
turning red. Nothing in the repository spanned an entrypoint to the messages a
model actually receives.

These tests close that gap for the Monday text path, which is the path a
controlled text-only proof runs. Each one drives the **real** stage function or
the **production** transport, captures the exact ``system`` and ``user`` message,
and asserts the configured text is in it. Every expected value is read from
``strategy/current/business_strategy.json`` and the rubric YAML at test time, so
the test follows the configuration instead of restating it: change the file and
these tests change with it; disconnect the file and they fail.

Patching note, the reason this is easy to get wrong: every pipeline stage binds
``chat`` by name (``from src.utils.llm_client import chat``), so patching
``src.utils.llm_client.chat`` intercepts nothing there — the patch must go into
each stage module's own namespace. The two acceptance transports and the
eligibility transport import ``chat`` inside the call instead, so for those the
client module is the correct patch point. Both forms are used below, each where
it is the real one.

No network, no model, no paid call: every transport is patched before use.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.utils.llm_client as llm_client
from src.editorial import editorial_acceptance, platform_composer
from src.editorial.editorial_acceptance import (
    EditorialAcceptanceRubric,
    LlmChatArticleRevisionTransport,
    LlmChatEditorialReviewTransport,
    RevisionContext,
    run_editorial_acceptance,
)
from src.editorial.editorial_role import render_editorial_role_rules, resolve_editorial_role
from src.editorial.source_eligibility import (
    LlmChatSourceEligibilityTransport,
    judge_source_eligibility,
)
from src.strategy.business_config import load_business_strategy_configuration
from tests.test_decision_lens_contract import _research
from tests.test_no_mandatory_thesis import _run_real_prompt_path

CONFIG_PATH = Path("strategy/current/business_strategy.json")
MONDAY_ROLE = "never-blank-monday-documented-case"
RUBRIC_PATH = Path("config/prompts/editorial_acceptance/never_blank.yaml")


def _configuration():
    return load_business_strategy_configuration(CONFIG_PATH)


def _monday_role():
    return resolve_editorial_role(_configuration(), MONDAY_ROLE)[1]


def _normalised(value: str) -> str:
    return " ".join(value.casefold().split())


@pytest.fixture(scope="module")
def monday_messages():
    """Every message the Monday pipeline sends, keyed by stage."""
    with pytest.MonkeyPatch.context() as patch:
        calls, _ = _run_real_prompt_path(
            patch, MONDAY_ROLE, "pricing", "A documented pricing constraint."
        )
    return {stage: [_normalised(message) for message in messages]
            for stage, messages in calls.items()}


# ── the configured strategy reaches the stages that are given it ────────────


def test_the_configured_positioning_and_audience_reach_the_decision_lens_message(
    monday_messages,
):
    configuration = _configuration()
    positioning = configuration.positioning.statement
    audience = configuration.audiences[0]

    lens = monday_messages["decision_lens_lite"]

    assert lens, "the Decision Lens stage sent no message"
    assert any(_normalised(positioning) in message for message in lens)
    assert any(_normalised(audience.default_problem) in message for message in lens)


def test_every_configured_prohibited_claim_reaches_the_voice_message(monday_messages):
    prohibited = list(_configuration().brand_editorial.prohibited_claims)

    voice = monday_messages["never_blank_voice"]

    assert prohibited, "the configuration declares no prohibited claims to prove"
    assert voice, "the Never Blank Voice stage sent no message"
    for claim in prohibited:
        assert any(_normalised(claim) in message for message in voice), claim


def test_the_configured_voice_and_principles_reach_the_voice_message(monday_messages):
    editorial = _configuration().brand_editorial
    voice = monday_messages["never_blank_voice"]

    for sentence in editorial.voice:
        assert any(_normalised(sentence) in message for message in voice), sentence
    for principle in editorial.editorial_principles:
        assert any(_normalised(principle) in message for message in voice), principle


# ── the Monday role reaches the two published surfaces, in the right one ────


def test_the_role_structure_and_prohibitions_reach_the_composer_messages(
    monday_messages,
):
    role = _monday_role()
    composer = monday_messages["platform_composer"]

    carrying = [m for m in composer if _normalised(f"EDITORIAL ROLE — {MONDAY_ROLE}") in m]
    assert len(carrying) == 2, "exactly the two published surfaces carry the role"
    for rule in (*role.structure, *role.forbidden):
        assert any(_normalised(rule) in message for message in carrying), rule


def _composer_message_for(format_key: str, messages: list[str]) -> str:
    matching = [m for m in messages if f"format: {format_key}" in m]
    assert len(matching) == 1, f"expected one composer message for {format_key}"
    return matching[0]


def test_each_surface_receives_all_of_its_own_channel_rules_and_none_of_the_other(
    monday_messages,
):
    role = _monday_role()
    composer = monday_messages["platform_composer"]
    article = _composer_message_for("long", composer)     # the Wix article
    linkedin = _composer_message_for("medium", composer)  # the LinkedIn post

    assert role.wix_rules and role.linkedin_rules
    for rule in role.wix_rules:
        assert _normalised(rule) in article, rule
        assert _normalised(rule) not in linkedin, rule
    for rule in role.linkedin_rules:
        assert _normalised(rule) in linkedin, rule
        assert _normalised(rule) not in article, rule


# ── the role's eligibility criteria reach the selection model ───────────────


def test_every_configured_eligibility_criterion_reaches_the_selection_message(
    monkeypatch,
):
    seen: list[dict] = []

    def fake_chat(*, system, user, **kwargs):
        seen.append({"system": system, "request": json.loads(user)})
        return json.dumps({"eligible": False, "reason": "Scale is not established."})

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    role = _monday_role()

    judge_source_eligibility(
        {"SIGNAL_ID": "sig-1", "HEADLINE": "A documented case",
         "CORE_FACT": "An owner-led business changed its pricing."},
        role,
        LlmChatSourceEligibilityTransport(),
    )

    assert len(seen) == 1, "one candidate is one judgment call"
    assert role.eligibility_criteria, "the role declares no criteria to prove"
    # every criterion, exactly and in order — including multi-line client lenses
    assert seen[0]["request"]["eligibility_criteria"] == list(role.eligibility_criteria)


# ── the acceptance rubric reaches the reviewer, and the revision the reviser ─


def _acceptance_messages(monkeypatch, article_body: str, research, revision_context=None):
    messages: dict[str, list[str]] = {}
    verdicts = iter(
        [
            json.dumps({"disposition": "revise", "failed_criterion_ids": ["voice"],
                        "rationale": "The voice is not yet the configured one.",
                        "revision_guidance": "Rewrite the close in the configured voice."}),
            "A revised article body that still carries the documented mechanism.",
            json.dumps({"disposition": "accept", "failed_criterion_ids": [],
                        "rationale": "The revision satisfies every criterion."}),
        ]
    )

    def fake_chat(*, system, user, **kwargs):
        stage = "reviser" if kwargs.get("json_mode") is not True else "reviewer"
        messages.setdefault(stage, []).append(_normalised(f"{system}\n{user}"))
        return next(verdicts)

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    run_editorial_acceptance(
        article_body=article_body,
        research=research,
        run_id="run-1",
        rubric=EditorialAcceptanceRubric.load(RUBRIC_PATH),
        reviewer=LlmChatEditorialReviewTransport(),
        revisor=LlmChatArticleRevisionTransport(),
        revision_context=revision_context,
    )
    return messages


def test_every_rubric_criterion_reaches_the_reviewer_message(monkeypatch):
    rubric = EditorialAcceptanceRubric.load(RUBRIC_PATH)

    messages = _acceptance_messages(
        monkeypatch, "A documented article body about one mechanism.", _research()
    )

    reviewer = messages["reviewer"]
    assert reviewer, "the reviewer received no message"
    for criterion in rubric.criteria:
        assert any(_normalised(criterion.description) in m for m in reviewer), criterion.criterion_id


def test_the_configured_revision_instructions_reach_the_reviser_message(monkeypatch):
    raw = RUBRIC_PATH.read_text(encoding="utf-8")

    messages = _acceptance_messages(
        monkeypatch, "A documented article body about one mechanism.", _research()
    )

    reviser = messages["reviser"]
    assert reviser, "the reviser received no message"
    # a distinctive sentence of the configured revision instructions, read from
    # the rubric file rather than restated here
    assert "do not write content for any other channel" in raw.casefold()
    assert any("do not write content for any other channel" in m for m in reviser)


def test_role_and_voice_reach_the_reviser_message(monkeypatch):
    """#254 D10 (temporary contract, until #253): the reviser inherits both.

    This test replaced the characterisation it grew from, which recorded that
    the reviser received the rubric alone. The owner decided in #253 that it
    must receive the applicable role and the configured voice; this now proves
    they reach the exact message the reviser model receives.
    """
    role = _monday_role()
    editorial = _configuration().brand_editorial
    context = RevisionContext(
        role_rules=render_editorial_role_rules(role, surface="wix"),
        voice=editorial.voice,
    )

    messages = _acceptance_messages(
        monkeypatch, "A documented article body about one mechanism.", _research(),
        revision_context=context,
    )

    reviser = " ".join(messages["reviser"])
    assert _normalised(f"EDITORIAL ROLE — {MONDAY_ROLE}") in reviser
    for rule in role.structure:
        assert _normalised(rule) in reviser, rule
    for sentence in editorial.voice:
        assert _normalised(sentence) in reviser, sentence


# ── the composer is the real one, not a constructor in isolation ────────────


def test_the_captured_composer_messages_come_from_the_production_module(monday_messages):
    """F-10's third finding was a test of a constructor production had left.

    The Monday capture above patches ``src.editorial.platform_composer.chat``,
    which only intercepts anything if production still composes through that
    module. If Monday ever moves to another composer, as Wednesday did at #210,
    these messages disappear and every assertion above fails instead of quietly
    testing an abandoned path.
    """
    assert platform_composer.compose_platforms.__module__ == "src.editorial.platform_composer"
    assert monday_messages["platform_composer"], "no composer message was captured"
    assert editorial_acceptance.run_editorial_acceptance.__module__ == (
        "src.editorial.editorial_acceptance"
    )
