"""Release 1 text-product contract: one idea, a real hook, an earned close.

The last blocked run produced a 1247-word article carrying five loosely joined
arguments under a title that named its subject instead of giving a reason to
read. These tests pin the configuration and wiring that now ask for something
narrower — they verify the *instructions and length contract* the generator
receives, and deliberately do not pretend a deterministic test can judge prose.

What a test can prove: the rules reach the model, the length target is bounded,
the title comes from the article rather than the source feed, and the LinkedIn
artifact expresses the same single idea.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.editorial.platform_composer import (
    _FORMAT_CONSTRAINTS,
    _WORD_RANGE,
    _build_user_prompt,
    _linkedin_rules,
    _wix_rules,
    compose_platforms,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext


CONFIG_PATH = Path("strategy/current/business_strategy.json")
SITE = "https://www.inneros.online"


@pytest.fixture(scope="module")
def channels() -> dict:
    return json.loads(CONFIG_PATH.read_text())["channels"]


@pytest.fixture(scope="module")
def wix_text(channels) -> str:
    wix = channels["wix"]
    return " ".join(
        wix["article_rules"] + wix["metadata_rules"] + wix["cta_rules"]
    ).lower()


@pytest.fixture(scope="module")
def linkedin_text(channels) -> str:
    li = channels["linkedin"]
    return " ".join(
        li["opening_rules"] + li["length_rules"] + li["formatting_rules"] + li["cta_rules"]
    ).lower()


# ===========================================================================
# The website article: one idea, bounded length
# ===========================================================================


def test_the_article_length_target_is_bounded_and_close_to_the_linkedin_artifact():
    lo, hi = _WORD_RANGE["long"]
    li_lo, li_hi = _WORD_RANGE["medium"]

    assert (lo, hi) == (400, 600)
    # the website article stays within roughly 2x LinkedIn — the same thought at
    # two lengths, not two different products
    assert hi <= li_hi * 3
    assert hi - lo <= 250  # a target, not a licence to wander


def test_the_configuration_asks_for_one_idea_and_one_mechanism(wix_text):
    assert "one central idea" in wix_text
    assert "one primary mechanism" in wix_text
    assert "400–600 words" in wix_text
    # several angles are several articles
    assert "leave the rest for other" in wix_text or "future articles" in wix_text


def test_the_configuration_forbids_the_listicle_shape(wix_text):
    assert "never structure the article as a list of lessons" in wix_text
    # and names the arc it wants instead
    for beat in ("observation", "tension", "mechanism", "evidence", "reframe"):
        assert beat in wix_text


def test_the_format_constraint_carries_the_same_instruction_to_the_composer():
    long_rule = _FORMAT_CONSTRAINTS["long"].lower()

    assert "one central" in long_rule
    assert "never write a list of lessons" in long_rule
    assert "choose the strongest" in long_rule


def test_padding_to_length_is_explicitly_refused(wix_text):
    assert "padding an argument to reach a length is not" in wix_text


# ===========================================================================
# The title must be a hook, and must be the article's own
# ===========================================================================


def test_the_configuration_requires_a_hook_not_a_subject_label(wix_text):
    assert "creates a real reason to read" in wix_text
    assert "without giving away the reframe" in wix_text
    assert "merely names the subject is not a hook" in wix_text
    # a hook, not manufactured drama
    assert "without manufactured drama" in wix_text


def test_the_composed_blog_title_replaces_the_source_headline():
    composed = _compose({"body": _body(), "echo_included": True, "title": "The Hooked Title"})

    assert composed["long"]["title"] == "The Hooked Title"


@pytest.mark.parametrize("value", [None, "", "   ", 7, {"t": "x"}])
def test_an_unusable_title_falls_back_instead_of_inventing_one(value):
    composed = _compose({"body": _body(), "echo_included": True, "title": value})

    assert composed["long"]["title"] is None


def test_metadata_is_never_body_text(wix_text):
    assert "metadata is never body text" in wix_text
    for label in ("slug:", "tags:", "category:", "cover metadata:"):
        assert label in wix_text  # named explicitly, so the model cannot guess


# ===========================================================================
# The Never Blank close and the canonical destination
# ===========================================================================


def test_both_surfaces_require_a_contextual_never_blank_close(wix_text, linkedin_text):
    for surface in (wix_text, linkedin_text):
        assert "never blank" in surface
        assert "perspective" in surface
        assert "evidence-supported mechanism" in surface
    # Never Blank is the publisher perspective, not a mandatory conclusion.
    assert "standard house thesis" in wix_text


def test_both_surfaces_name_the_canonical_destination_and_no_other(wix_text, linkedin_text):
    assert SITE.lower() in wix_text
    assert SITE.lower() in linkedin_text
    assert "no other url" in wix_text

    # and the CTA the voice stage receives names it too
    reflection = next(
        cta for cta in json.loads(CONFIG_PATH.read_text())["calls_to_action"]
        if cta["cta_id"] == "reflection"
    )
    joined = " ".join(reflection["rules"])
    assert SITE in joined
    assert "contextual Never Blank perspective" in joined
    assert "evidence-supported mechanism" in joined


def test_the_cta_stays_an_invitation_not_a_sales_ask():
    reflection = next(
        cta for cta in json.loads(CONFIG_PATH.read_text())["calls_to_action"]
        if cta["cta_id"] == "reflection"
    )

    joined = " ".join(reflection["rules"]).lower()
    assert "do not request a call, form submission, or purchase" in joined
    assert "soft and specific" in joined


# ===========================================================================
# LinkedIn: the same idea, compressed
# ===========================================================================


def test_linkedin_expresses_the_same_single_idea(linkedin_text):
    assert "same single idea" in linkedin_text
    assert "never a second argument" in linkedin_text
    assert "never a list of takeaways" in linkedin_text


def test_linkedin_keeps_its_native_composition_and_shape(linkedin_text):
    assert "not truncated from the wix article" in linkedin_text
    assert "hook, tension, mechanism or reframe" in linkedin_text


# ===========================================================================
# The rules actually reach the model
# ===========================================================================


def test_the_configured_rules_reach_the_composer_prompt_for_both_surfaces():
    execution = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration(CONFIG_PATH)
    )
    article = {"hook": "h", "narrative_spine": "s", "surviving_explanation": "e",
               "reframe": "r", "business_translation": "b", "discovery": {},
               "echo_line": "Echo line.", "cta_line": "cta"}

    blog_prompt = _build_user_prompt(article, "long", "reflection", _wix_rules(execution.wix))
    li_prompt = _build_user_prompt(
        article, "medium", "reflection", _linkedin_rules(execution.linkedin)
    )

    assert "TARGET LENGTH: 400-600 words" in blog_prompt
    for prompt in (blog_prompt, li_prompt):
        assert "CONFIGURED CHANNEL RULES:" in prompt
        assert SITE in prompt
        assert "Never Blank" in prompt
        assert "perspective" in prompt
        assert "evidence-supported mechanism" in prompt
    assert "one central idea" in blog_prompt.lower()
    assert "same single idea" in li_prompt.lower()


# ===========================================================================
# helpers
# ===========================================================================


def _body() -> str:
    return "A composed body that ends with the echo. Echo line."


def _compose(payload: dict) -> dict:
    article = {"hook": "h", "narrative_spine": "s", "surviving_explanation": "e",
               "reframe": "r", "business_translation": "b", "discovery": {},
               "echo_line": "Echo line."}
    with mock.patch(
        "src.editorial.platform_composer.chat", return_value=json.dumps(payload)
    ):
        return compose_platforms(article, cta_mode="none")


# ===========================================================================
# Evidence framing (#139): the reviewer's three recurring objections
# ===========================================================================
#
# Four live runs were refused on `evidence-use` and `unsupported-claims`. By
# the last one the reviewer's objections had narrowed to framing: the source
# was credited to the platform the case was about rather than to the article
# the evidence came from; reader scenarios were written as reported market
# behaviour; and the closing invitation claimed a capability. These rules
# answer those three, and nothing about the rubric changed to meet them.


def test_external_facts_must_be_credited_to_the_recorded_source(wix_text):
    assert "attribute every external fact to the exact source recorded" in wix_text
    # naming the subject company as the reporter is the exact error observed
    assert "never credit the company or platform the case is about as the" in wix_text


def test_the_evidence_supports_a_principle_not_a_promised_result(wix_text):
    assert "never as a proven result for the reader" in wix_text


def test_reader_scenarios_must_read_as_hypothetical_not_as_market_fact(wix_text, linkedin_text):
    assert "hypothetical scenario addressed to the reader" in wix_text
    assert "never as reported market behaviour" in wix_text
    assert "only the accepted evidence may be stated as fact" in wix_text
    # LinkedIn carries the same separation
    assert "only the accepted evidence may be stated as fact" in linkedin_text
    assert "hypothetical scenario or the author" in linkedin_text


def test_the_invitation_claims_no_capability(wix_text, linkedin_text):
    assert "makes no claim about what never blank can do" in wix_text
    assert "makes no claim about what never blank can do or achieve" in linkedin_text

    reflection = next(
        cta for cta in json.loads(CONFIG_PATH.read_text())["calls_to_action"]
        if cta["cta_id"] == "reflection"
    )
    joined = " ".join(reflection["rules"]).lower()
    assert "invite; never assert a capability" in joined
    assert "no promised outcome" in joined


def test_the_canonical_destination_survives_the_framing_rules(wix_text, linkedin_text):
    # the CTA rules were rewritten; the destination must not have been lost
    assert SITE.lower() in wix_text
    assert SITE.lower() in linkedin_text
    assert wix_text.count(SITE.lower()) == 1  # one destination, named once


def test_the_framing_rules_reach_the_real_prompts():
    execution = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration(CONFIG_PATH)
    )
    article = {"hook": "h", "discovery": {}, "echo_line": "Echo line.", "cta_line": "cta"}

    blog = _build_user_prompt(article, "long", "reflection", _wix_rules(execution.wix)).lower()
    li = _build_user_prompt(
        article, "medium", "reflection", _linkedin_rules(execution.linkedin)
    ).lower()

    assert "attribute every external fact" in blog
    assert "never as reported market behaviour" in blog
    assert "makes no claim about what never blank can do" in blog
    assert "only the accepted evidence may be stated as fact" in li
