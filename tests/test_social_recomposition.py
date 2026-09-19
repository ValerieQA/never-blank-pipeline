"""Issue #197: after an editorial revision, the social derivative follows.

The canonical content model is: final canonical article → channel lens →
social derivative. Live run 32725156081 proved the missing operation — the
article was revised at acceptance, the pre-revision LinkedIn body became
stale, and the Story #13 guard (correctly) killed the run with no path
forward. These scenarios prove the re-composition seam: nothing happens on
the plain ACCEPT path; on REVISE→ACCEPT exactly one composition stage runs
again, from the FINAL accepted article, through the same channel lens and
validators; the stale body can never reach publication and is never a
fallback; and the preserved accepted pair is internally consistent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial.pipeline import ArticleGenerationError, recompose_platform
from src.editorial.platform_composer import (
    CLOSING_BRANDED_ECHO_THEN_SOURCES,
    _build_user_prompt,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_research_artifact_lifecycle import ReadyProvider

REVISED_BODY = "Sharpened revised article body."
RECOMPOSED_BODY = (
    "Re-composed social body derived from the final accepted article."
)


def _accepting_reviewer():
    return FakeReviewTransport(_review_payload())


def _revising_reviewer():
    return FakeReviewTransport(
        _review_payload(disposition="revise", failed=["generic-filler"],
                        guidance="Cut the filler."),
        _review_payload(),
    )


def _run(tmp_path, *, reviewer, dry_run=True, patch_overrides=None):
    """Drive the real entrypoint with the REAL acceptance boundary."""

    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    del patches["run_editorial_acceptance"]          # exercise the real gate
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    if patch_overrides:
        patches.update(patch_overrides)
    provider = ReadyProvider()
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(
            research_provider=provider,
            decision_evaluator=evaluator,
            editorial_reviewer=reviewer,
            article_revisor=FakeRevisionTransport(REVISED_BODY),
        )
    return code, patches, provider


def _generated(tmp_path) -> dict:
    return json.loads(next(tmp_path.glob("*/runs/*/generated.json")).read_text())


def _accepted(tmp_path) -> dict:
    return json.loads(
        next(tmp_path.glob("*/runs/*/accepted_composition.json")).read_text()
    )


# ===========================================================================
# Path A — ACCEPT without revision. Superseded by the Monday preview-
# readiness invariant: the canonical route composes NO social body before
# acceptance, so even an unrevised article gets its derivative afterwards,
# from the accepted text — exactly one derivation either way.
# ===========================================================================


def test_accept_without_revision_derives_once_from_the_accepted_article(tmp_path):
    code, patches, provider = _run(tmp_path, reviewer=_accepting_reviewer())

    assert code == 0
    derive = patches["recompose_platform"]
    assert derive.call_count == 1
    assert derive.call_args.args[1] == "medium"
    # derived from the accepted article (here unrevised: the draft body)
    assert derive.call_args.kwargs["canonical_body"] == _generated(tmp_path)["blog_article"]
    record = _accepted(tmp_path)
    assert record["social_recomposition"]["performed"] is True
    assert "final accepted article" in record["social_recomposition"]["reason"]
    # the accepted pair holds the derivation's body: the harness derivation of
    # an unrevised article is the body the test composed for it
    assert record["content"]["linkedin_body"] == "LinkedIn post text."
    assert derive.call_args.kwargs["canonical_body"] == record["content"]["article_body"]


# ===========================================================================
# Path B — REVISE → ACCEPT: exactly one re-composition from Article B
# (items 3, 4, 5, 7, 9, 15, 16, 17)
# ===========================================================================


def test_revision_recomposes_exactly_once_from_the_final_article(tmp_path):
    code, patches, provider = _run(tmp_path, reviewer=_revising_reviewer())

    assert code == 0
    recompose = patches["recompose_platform"]
    assert recompose.call_count == 1                             # item 3
    assert recompose.call_args.args[1] == "medium"
    # derived from the FINAL accepted Article B, not the original  item 7
    assert recompose.call_args.kwargs["canonical_body"] == REVISED_BODY
    # nothing else regenerated                                     items 4, 5
    assert patches["generate_article"].call_count == 1
    assert len(provider.requests) == 1
    # the re-composed body replaces the stale one downstream       item 15
    assert _generated(tmp_path)["linkedin_post"] == RECOMPOSED_BODY
    assert _generated(tmp_path)["blog_article"] == REVISED_BODY
    # the canonical title is whatever the long composition named   item 9
    # (the recompose stand-in returns title=None and it is ignored)
    assert _generated(tmp_path)["headline"]


def test_the_preserved_pair_is_article_b_plus_linkedin_b(tmp_path):
    _run(tmp_path, reviewer=_revising_reviewer())

    record = _accepted(tmp_path)
    assert record["editorial"]["revised"] is True
    assert record["content"]["article_body"] == REVISED_BODY     # item 16
    assert record["content"]["linkedin_body"] == RECOMPOSED_BODY
    meta = record["social_recomposition"]
    assert meta["performed"] is True
    # the stale body survives ONLY as explicitly-discarded evidence — the
    # accepted pair itself is internally consistent                 item 17
    assert meta["stale_composition_discarded"] == "LinkedIn post text."
    assert record["content"]["linkedin_body"] != meta["stale_composition_discarded"]


def test_the_stale_body_cannot_reach_publication(tmp_path):
    # item 8: after a revision the pre-revision body appears in no
    # publication input — generated.json carries only the re-composed body,
    # and the untouched Story #13 guard still refuses any stale body
    code, patches, _ = _run(tmp_path, reviewer=_revising_reviewer(), dry_run=False)

    generated = _generated(tmp_path)
    assert "LinkedIn post text." not in json.dumps(
        {k: v for k, v in generated.items() if k != "threads_sequence"}
    )
    from src.editorial.linkedin_composition import (
        LinkedInCompositionError,
        accept_linkedin_composition,
    )
    from src.strategy.execution_context import ConfigurationIdentity

    with pytest.raises(LinkedInCompositionError):                # item 24
        accept_linkedin_composition(
            linkedin_body="LinkedIn post text.",
            article_body=REVISED_BODY,
            article_revised=True,
            run_id="r", signal_id="s",
            configuration_identity=mock.MagicMock(spec=ConfigurationIdentity),
            strategy_id="st", strategy_version="1",
        )


def test_the_entrypoint_wires_the_staleness_flag_truthfully():
    # item 24: the guard input means "revised AFTER this body was composed" —
    # a freshly re-composed body is not stale, and a path that skipped
    # re-composition still fails closed
    source = Path("scripts/generate_and_publish.py").read_text()
    assert "article_revised=_acceptance.revised and not _social_recomposed" in source


# ===========================================================================
# Failure behavior (items 6, 13, 14)
# ===========================================================================


def test_recomposition_failure_blocks_the_run_before_any_side_effect(tmp_path):
    failing = mock.MagicMock(
        side_effect=ArticleGenerationError(
            "platform_recomposer", RuntimeError("provider down")
        )
    )
    with mock.patch(
        "scripts.research.prepare_content.prepare_content_packages",
        side_effect=AssertionError("paid image generation was reached"),
    ):                                                            # item 6
        code, patches, _ = _run(
            tmp_path, reviewer=_revising_reviewer(), dry_run=False,
            patch_overrides={"recompose_platform": failing},
        )

    assert code == 1                                              # item 13
    assert not patches["WixPublisher"].return_value.publish.called
    assert not patches["LinkedInPublisher"].return_value.publish.called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_recomposition_failure_never_falls_back_to_the_stale_body(tmp_path):
    failing = mock.MagicMock(
        side_effect=ArticleGenerationError(
            "platform_recomposer", RuntimeError("provider down")
        )
    )
    _run(tmp_path, reviewer=_revising_reviewer(),
         patch_overrides={"recompose_platform": failing})

    record = _accepted(tmp_path)                                  # item 14
    assert record["content"]["article_body"] == REVISED_BODY   # B preserved
    assert record["content"]["linkedin_body"] is None          # no fallback
    meta = record["social_recomposition"]
    assert meta["performed"] is False
    assert "provider down" in meta["error"]
    assert meta["stale_composition_discarded"] == "LinkedIn post text."


# ===========================================================================
# The seam itself (items 7, 10, 11, 12, 23) — real composer, fake transport
# ===========================================================================

_ECHO = "The owner's limits set the ceiling before the market does."


def _structured() -> dict:
    return {
        "hook": "A hook.", "observation": "An observation.",
        "recognition": "A recognition.", "explanation": "An explanation.",
        "reframe": "A reframe.", "business_meaning": "A meaning.",
        "narrative_spine": "X turns toward Y", "discovery": {},
        "echo_line": _ECHO,
    }


def _seam_chat_capture(body_lines: str):
    calls = []

    def fake_chat(*, system, user, json_mode=False, model=None):
        calls.append(user)
        return json.dumps({"body": body_lines, "echo_included": True,
                           "title": None})

    return calls, fake_chat


# ===========================================================================
# Prompt contract: the copying rule and the verbatim-Echo rule must be
# simultaneously obeyable (PR #198 review round 1)
#
# #191 and #193 were both live failures of the same class: two individually
# reasonable instructions that no output could satisfy at once. Here the
# canonical-content block says "do not reuse the article's sentences" while
# the ECHO MODE line says "reproduce the supplied Echo exactly" — and under
# this contract the article itself ends with that Echo. The prohibition must
# therefore carry its own exception, in the same breath, or the two rules
# cannot both be followed.
# ===========================================================================


def _canonical_prompt() -> str:
    """A prompt with BOTH conditions live: canonical body + verbatim Echo."""
    from src.editorial.platform_composer import _effective_echo_mode

    assert _effective_echo_mode("medium", CLOSING_BRANDED_ECHO_THEN_SOURCES) == (
        "verbatim_final"
    )
    return _build_user_prompt(
        _structured(), "medium", "none",
        closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
        canonical_body=f"Long-form prose about the case.\n\nNever Blank: {_ECHO}",
    )


def test_the_copying_rule_is_scoped_to_ordinary_prose():
    prompt = _canonical_prompt()

    # the derive-don't-republish principle is stated …
    assert "rather than reproducing the long-form wholesale" in prompt
    # … and it is explicitly limited to ordinary prose, not stated absolutely
    assert "This rule governs ORDINARY PROSE ONLY" in prompt
    # the unqualified form that could not coexist with a verbatim Echo is gone
    assert "Derive, never copy" not in prompt
    assert "reusing its sentences verbatim is rejected" not in prompt
    # #221: and it is no longer stated at sentence level either — a shared
    # hook is a product decision, so the rule now names the whole-body copy
    assert "copying its paragraphs or sentences wholesale" not in prompt
    assert "sentences MAY recur where they earn it" in prompt


def test_contract_required_verbatim_content_is_explicitly_exempt():
    prompt = _canonical_prompt()

    # the exemption names the mechanism (an instruction below requiring
    # verbatim reproduction), gives the concrete instance, and rules out
    # reading it as a conflict
    assert (
        "any element an instruction below requires to appear verbatim "
        "(the ECHO MODE line, for example) must still be reproduced exactly "
        "as supplied, even when the same wording also appears in the content "
        "above"
    ) in prompt
    assert "exceptions to this one, never conflicts with it" in prompt


def test_the_exception_travels_with_the_prohibition():
    # a model reading the prohibition must meet its exception in the same
    # block — an exemption stranded elsewhere in the prompt would not
    # resolve the contradiction at the point of reading
    prompt = _canonical_prompt()
    block = prompt.split("FINAL CANONICAL CONTENT")[1].split(_ECHO)[0]

    prohibition = block.index("rather than reproducing the long-form wholesale")
    exemption = block.index("This rule governs ORDINARY PROSE ONLY")
    assert prohibition < exemption


def test_both_rules_are_present_and_jointly_satisfiable():
    prompt = _canonical_prompt()

    # the ECHO MODE instruction still demands the exact supplied Echo …
    assert "word for word" in prompt
    assert "never adapted" in prompt
    # … the Echo is supplied …
    assert _ECHO in prompt
    # … and a body that copies ONLY the Echo satisfies both rules: the
    # validator accepts it, which is the behaviour the prompt now asks for
    from src.editorial.platform_composer import _validate_branded_echo_final

    _validate_branded_echo_final(
        f"A wholly different channel-native opening.\n\nNever Blank: {_ECHO}",
        _ECHO, "medium",
    )


def test_the_prompt_contract_holds_without_a_canonical_body_too():
    # the ordinary composition path never had the copying rule at all; the
    # exemption must not leak into it
    prompt = _build_user_prompt(
        _structured(), "medium", "none",
        closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
    )
    assert "ORDINARY PROSE ONLY" not in prompt
    assert "word for word" in prompt          # the Echo rule is unchanged


def test_the_seam_makes_exactly_one_model_call_with_the_final_content():
    body = f"A channel-native derivative.\n\nNever Blank: {_ECHO}"
    calls, fake_chat = _seam_chat_capture(body)
    with mock.patch("src.editorial.platform_composer.chat", side_effect=fake_chat):
        result = recompose_platform(
            _structured(), "medium",
            canonical_body="The final accepted article body.",
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
        )

    assert len(calls) == 1                                        # item 23
    assert result["body"] == body
    prompt = calls[0]
    # the final content leads the prompt as the ONLY authority      item 7
    assert "FINAL CANONICAL CONTENT" in prompt
    assert "The final accepted article body." in prompt
    assert "use nothing that is not in it" in prompt
    # and the pre-review outline is not supplied at all (preview-readiness
    # invariant): no narrative spine, no structured narrative fields
    assert "NARRATIVE SPINE" not in prompt
    assert "STRUCTURED FIELDS" not in prompt
    # no title regeneration for the social format                   item 10
    assert result["title"] is None


def test_the_seam_keeps_the_channel_lens_active():
    from src.strategy.execution_context import StrategyExecutionContext

    from tests.test_monday_stream import _configuration

    execution = StrategyExecutionContext.from_configuration(_configuration())
    body = f"A derivative.\n\nNever Blank: {_ECHO}"
    calls, fake_chat = _seam_chat_capture(body)
    with mock.patch("src.editorial.platform_composer.chat", side_effect=fake_chat):
        recompose_platform(
            _structured(), "medium",
            canonical_body="The final accepted article body.",
            linkedin_strategy=execution.linkedin,
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
        )

    assert "CONFIGURED CHANNEL RULES:" in calls[0]                # item 12


def test_the_recomposed_echo_must_still_be_verbatim():
    # item 11: the same #196 structural validator judges the re-composed
    # body — an adapted echo is rejected, the exact echo passes
    from src.editorial.platform_composer import CompositionRejected

    adapted = "Adapted: owner limits are the real ceiling."
    calls, fake_chat = _seam_chat_capture(
        f"A derivative.\n\nNever Blank: {adapted}"
    )
    with mock.patch("src.editorial.platform_composer.chat", side_effect=fake_chat):
        with pytest.raises(ArticleGenerationError):
            recompose_platform(
                _structured(), "medium",
                canonical_body="The final accepted article body.",
                closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
            )

    verbatim_calls, fake_chat2 = _seam_chat_capture(
        f"A derivative.\n\nNever Blank: {_ECHO}"
    )
    with mock.patch("src.editorial.platform_composer.chat", side_effect=fake_chat2):
        result = recompose_platform(
            _structured(), "medium",
            canonical_body="The final accepted article body.",
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
        )
    assert _ECHO in result["body"]


def test_a_provider_failure_makes_exactly_one_attempt_and_fails_closed():
    # honest ceiling (research Q13): _run_stage retries only ValueError-class
    # rejections — a provider failure is one attempt, one charge, wrapped
    # into the seam's single typed fail-closed boundary
    attempts = []

    def failing_chat(*, system, user, json_mode=False, model=None):
        attempts.append(1)
        raise RuntimeError("provider down")

    with mock.patch("src.editorial.platform_composer.chat", side_effect=failing_chat):
        with pytest.raises(ArticleGenerationError):
            recompose_platform(
                _structured(), "medium",
                canonical_body="The final accepted article body.",
            )
    assert len(attempts) == 1


def test_an_exhausted_call_budget_propagates_as_a_run_stop():
    from src.run.call_budget import RunCallBudgetExceededError

    def budget_exceeded(*, system, user, json_mode=False, model=None):
        raise RunCallBudgetExceededError(used=40, limit=40)

    with mock.patch("src.editorial.platform_composer.chat", side_effect=budget_exceeded):
        with pytest.raises(RunCallBudgetExceededError):
            recompose_platform(
                _structured(), "medium",
                canonical_body="The final accepted article body.",
            )


def test_the_seam_refuses_an_empty_canonical_body():
    with pytest.raises(ArticleGenerationError):
        recompose_platform(_structured(), "medium", canonical_body="   ")


def test_a_rejected_recomposition_is_preserved_for_diagnosis():
    sink: list = []
    calls, fake_chat = _seam_chat_capture("A body with no echo at all.")
    with mock.patch("src.editorial.platform_composer.chat", side_effect=fake_chat):
        with pytest.raises(ArticleGenerationError):
            recompose_platform(
                _structured(), "medium",
                canonical_body="The final accepted article body.",
                closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
                rejected_sink=sink,
            )
    assert len(sink) == 2               # both attempts, #191 pattern
    assert all(item["stage"] == "platform_recomposer" for item in sink)


def test_the_prompt_without_canonical_body_is_unchanged():
    # absent canonical_body, the first-composition prompt keeps its outline
    structured = _structured()
    before = _build_user_prompt(structured, "medium", "none")
    assert "FINAL CANONICAL CONTENT" not in before
    assert "NARRATIVE SPINE" in before and "STRUCTURED FIELDS:" in before


def test_a_derivative_prompt_carries_none_of_the_pre_review_outline():
    """Every narrative field of the draft is withheld from a derivative; only
    the verbatim Echo travels (preview-readiness invariant)."""
    structured = _structured()
    with_body = _build_user_prompt(
        structured, "medium", "none",
        canonical_body="The final accepted article body.",
    )
    for field in ("hook", "reframe", "surviving_explanation", "narrative_spine"):
        value = structured.get(field)
        if isinstance(value, str) and value.strip():
            assert value not in with_body, field
    for value in (structured.get("discovery") or {}).values():
        if isinstance(value, str) and value.strip():
            assert value not in with_body
    assert "REQUIRED ELEMENTS:" in with_body


# ===========================================================================
# Lifecycle ordering pins (items 18, 19, 20, 21)
# ===========================================================================


def test_recomposition_sits_between_acceptance_and_every_later_gate():
    source = Path("scripts/generate_and_publish.py").read_text()
    accept = source.index("blog_body = _acceptance.final_article_body")
    recompose = source.index("recompose_platform(\n")
    preserved = source.index("  ✓  accepted compositions preserved")
    # the canonical article's gate (the preview's Facebook check precedes it)
    transparency = source.index(
        "validate_source_transparency(\n                    article_body=blog_body")
    image = source.index("Image preparation (fresh-gen path")
    # acceptance → re-composition → preservation → transparency → images
    assert accept < recompose < preserved < transparency < image  # items 18, 6
    # transparency judges blog_body, which IS the final accepted article
    assert "article_body=blog_body" in source[transparency:transparency + 200]


def test_196_sequencing_is_untouched():
    source = Path("scripts/generate_and_publish.py").read_text()
    # Wix gates LinkedIn; deterministic enrichment; final exact-package ALLOW
    # #200 strengthened this gate from "a URL exists" to "a VERIFIED
    # provider-sourced canonical URL exists"; the sequencing it enforces is
    # unchanged
    assert 'if name == "linkedin" and not _canonical_verdict_ok(' in source  # item 19
    # #200: the bound URL is now the VERIFIED canonical one
    assert "bind_canonical_article_url(_package, _canonical_url)" in source  # item 20
    assert "write_linkedin_final_preflight_json(" in source       # item 21
    gate = source.index('if name == "linkedin" and not _canonical_verdict_ok(')
    bind = source.index("bind_canonical_article_url(_package, _canonical_url)")
    allow = source.index("write_linkedin_final_preflight_json(")
    publish = source.index("_r1_cls[name]().publish(")
    assert gate < bind < allow < publish
