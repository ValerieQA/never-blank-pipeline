"""Issue #260: what controlled live run 35417616416 destroyed on its way down.

The run reached Editorial Acceptance (REVISE → ACCEPT), composed LinkedIn and
Facebook from the final accepted article, then failed twice at Instagram.
Three defects, one live proof:

1. both Instagram attempts wrote the correct branded Echo *inline*, behind the
   last prose sentence, because the prompt asked for "the final line" while
   the validator requires a standalone attribution block. Prompt and validator
   now describe the same shape — and the inline form is still refused, never
   blessed to make a live run pass;
2. ``accepted_composition.json`` was written AFTER the preview surfaces, so a
   later adapter failure erased an article that had already reached ACCEPT. It
   is now written the moment the accepted article and its LinkedIn derivative
   exist — before any preview composition or image work — and the preview
   surfaces composed before a stop are preserved beside it;
3. the rejected Instagram attempts carried conditions and conclusions the
   accepted article did not state. The derivation prompt now says so
   explicitly, and a figure the accepted content does not contain is refused
   mechanically instead of being left to the model's good behaviour.

That the pre-review draft never reaches a derivation prompt at all is proven
in tests/test_social_derivation_invariant.py and is unchanged here.

No network, no model.
"""

from __future__ import annotations

import json
import re
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from src.editorial.pipeline import ArticleGenerationError, recompose_platform
from src.editorial.platform_composer import (
    CLOSING_BRANDED_ECHO_THEN_SOURCES,
    CompositionRejected,
    _build_user_prompt,
    _compose_one,
    _figures,
)
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_monday_stream import MONDAY_ROLE
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_social_derivation_invariant import (
    RecordingJudge,
    ECHO,
    FINAL_ARTICLE,
    TITLE,
    FaithfulComposer,
    _CITATION,
    _draft,
)
from tests.test_visual_contract import _pimgs

SIG = legacy._SIGNAL_ID


def _structured() -> dict:
    return {"hook": "h", "discovery": {}, "echo_line": ECHO,
            "narrative_spine": "s", "cta_line": None}


# ===========================================================================
# 1. The Instagram branded-Echo contract: prompt and validator agree
# ===========================================================================

#: The shape both live Instagram attempts produced: the right Echo, the right
#: attribution, sitting at the end of the closing prose sentence.
INLINE_ECHO = (
    "You watch the clicks fall and assume the ad stopped working.\n\n"
    "The people who stayed were the ones ready to buy.\n\n"
    f"That is the whole mechanism. Never Blank: {ECHO}"
)

#: The same content in the shape the contract asks for.
STANDALONE_ECHO = (
    "You watch the clicks fall and assume the ad stopped working.\n\n"
    "The people who stayed were the ones ready to buy.\n\n"
    "That is the whole mechanism.\n\n"
    f"Never Blank: {ECHO}"
)


def _compose_instagram(body: str, *, canonical_body: str = FINAL_ARTICLE) -> dict:
    """Drive the real Instagram derivation validators over a body we control."""
    payload = json.dumps({"body": body, "echo_included": True, "title": None})
    with mock.patch.object(platform_composer, "chat", return_value=payload):
        return _compose_one(
            _structured(), "instagram",
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
            canonical_body=canonical_body,
        )


def test_the_live_instagram_echo_behind_the_last_sentence_is_refused():
    """The exact failure class of run 35417616416, named as what it is."""
    with pytest.raises(CompositionRejected) as refused:
        _compose_instagram(INLINE_ECHO)

    message = str(refused.value)
    assert "appended to the end of a prose paragraph" in message
    assert "a closing line of its own" in message
    # the refused body is preserved for diagnosis, as every rejection is
    assert refused.value.body == INLINE_ECHO


def test_the_standalone_branded_echo_block_passes_on_instagram():
    result = _compose_instagram(STANDALONE_ECHO)

    assert result["body"].splitlines()[-1] == f"Never Blank: {ECHO}"


def test_the_instagram_prompt_asks_for_the_block_the_validator_requires():
    prompt = _build_user_prompt(
        _structured(), "instagram", "none",
        closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
        canonical_body=FINAL_ARTICLE,
    )

    # the instruction the live attempts satisfied while still failing — "the
    # final line" — now says which line, and what may share it
    assert "as its OWN closing block" in prompt
    assert "carrying nothing else" in prompt
    assert "never appended to the end of a sentence or of the last prose" in prompt
    assert "'Never Blank: <echo>'" in prompt


def test_the_branded_echo_is_still_a_distinct_block_not_a_relaxed_rule():
    """The product contract is unchanged: inline is refused on every surface
    that carries the branded closing, not only Instagram."""
    for format_key in ("medium", "instagram"):
        with pytest.raises(CompositionRejected, match="closing line of its own"):
            payload = json.dumps({"body": INLINE_ECHO, "echo_included": True,
                                  "title": None})
            with mock.patch.object(platform_composer, "chat", return_value=payload):
                _compose_one(
                    _structured(), format_key,
                    closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
                    canonical_body=FINAL_ARTICLE,
                )


# ===========================================================================
# 2. An accepted article survives a later preview failure
# ===========================================================================

def _instagram_failure() -> ArticleGenerationError:
    """What the live Instagram adapter raised, twice, in run 35417616416."""
    return ArticleGenerationError(
        "platform_recomposer",
        CompositionRejected(
            "Platform Composer (instagram): the Echo must be the Never Blank "
            "attribution block",
            format_key="instagram", body=INLINE_ECHO,
        ),
    )


def _run_until_instagram_fails(tmp_path, *, seen: dict | None = None):
    """The live shape: ACCEPT, LinkedIn and Facebook composed, Instagram fails."""
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]           # the REAL acceptance boundary
    patches["generate_article"] = mock.MagicMock(return_value=_draft())
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()

    def derive(structured, format_key, **kwargs):
        if seen is not None:
            seen[format_key] = bool(
                list(tmp_path.glob(f"{SIG}/runs/*/accepted_composition.json")))
        if format_key == "instagram":
            raise _instagram_failure()
        body = (FINAL_ARTICLE if format_key == "reading"
                else f"A {format_key} derivation.\n\n**Never Blank:** {ECHO}")
        return {"body": body, "word_count": len(body.split()),
                "echo_included": True, "title": None}

    patches["recompose_platform"] = mock.MagicMock(side_effect=derive)
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Remove the unsupported claim."),
        _review_payload(),
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=reviewer,
                    article_revisor=FakeRevisionTransport(FINAL_ARTICLE),
                    derivation_judge=RecordingJudge())
    return code, patches


def _artifact(tmp_path, name: str) -> dict:
    return json.loads(next(tmp_path.glob(f"{SIG}/runs/*/{name}")).read_text())


def test_the_accepted_article_survives_a_later_instagram_failure(tmp_path):
    code, _ = _run_until_instagram_fails(tmp_path)

    assert code == 1
    record = _artifact(tmp_path, "accepted_composition.json")
    # the article that reached ACCEPT — the revised one — with its title and
    # its Echo, all still readable after the adapter that stopped the run
    assert record["content"]["article_body"] == FINAL_ARTICLE
    assert record["content"]["title"] == TITLE
    assert record["content"]["echo"] == ECHO
    assert record["content"]["linkedin_body"]
    assert record["editorial"]["revised"] is True


def test_the_accepted_article_is_written_before_any_preview_composition(tmp_path):
    seen: dict[str, bool] = {}
    _run_until_instagram_fails(tmp_path, seen=seen)

    # the LinkedIn derivative belongs to the record, so it precedes the write…
    assert seen["medium"] is False
    # …and every preview surface is composed after the article is safe
    assert seen["reading"] is True
    assert seen["instagram"] is True


def test_the_preview_surfaces_composed_before_the_stop_are_preserved(tmp_path):
    code, _ = _run_until_instagram_fails(tmp_path)

    assert code == 1
    record = _artifact(tmp_path, "preview_compositions.json")
    assert record["stopped_at"] == "composition:instagram"
    assert record["surfaces"]["facebook"] == FINAL_ARTICLE
    # the surfaces the run never reached say so by being empty, not by lying
    assert record["surfaces"]["instagram"] == ""
    assert record["surfaces"]["telegram"] == ""
    assert record["surfaces"]["threads"] == []


def test_the_failed_preview_publishes_nothing_and_consumes_nothing(tmp_path):
    code, patches = _run_until_instagram_fails(tmp_path)

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))
    assert not list(tmp_path.glob(f"{SIG}/runs/*/publication_results.json"))


def test_the_preserved_records_are_evidence_never_publication_inputs(tmp_path):
    from src.reporting.run_report import CANONICAL_ARTIFACTS

    _run_until_instagram_fails(tmp_path)

    for name in ("accepted_composition.json", "preview_compositions.json"):
        assert name not in CANONICAL_ARTIFACTS
        assert _artifact(tmp_path, name)["publishable"] is False


# ===========================================================================
# 3. Faithful derivation from the FINAL ACCEPTED ARTICLE
# ===========================================================================

#: The claim Editorial Revision removes below, carrying its own figure.
REMOVED_CLAIM = "Total engagement fell 41% after the quiz was added."

DRAFT_WITH_CLAIM = (
    "Every like and comment on your ad can disguise how few people are "
    "ready to buy.\n\n"
    f"{REMOVED_CLAIM} Form submissions still rose. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from "
    "buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)
ACCEPTED_WITHOUT_CLAIM = (
    "Every like and comment on your ad can disguise how few people are "
    "ready to buy.\n\n"
    f"Form submissions still rose. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from "
    "buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)


def test_the_derivation_prompt_forbids_restoring_and_inferring():
    prompt = _build_user_prompt(
        _structured(), "instagram", "none",
        canonical_body=ACCEPTED_WITHOUT_CLAIM,
    )

    assert "It is the FINAL version" in prompt
    assert "was removed deliberately, so never restore it" in prompt
    assert (
        "never add a conclusion, a generalization, a condition or an "
        "implication the content does not itself state"
    ) in prompt
    assert "Every figure you write must appear in the content above" in prompt


def test_a_derivative_that_invents_a_figure_is_refused():
    body = (f"{REMOVED_CLAIM} The quiz still filtered the browsers out.\n\n"
            f"Never Blank: {ECHO}")
    payload = json.dumps({"body": body, "echo_included": True, "title": None})

    with mock.patch.object(platform_composer, "chat", return_value=payload):
        with pytest.raises(ArticleGenerationError) as refused:
            recompose_platform(
                _structured(), "instagram",
                canonical_body=ACCEPTED_WITHOUT_CLAIM,
                closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
            )

    assert "41" in str(refused.value.original)


def test_a_derivative_that_restates_the_articles_own_figures_passes():
    body = (f"{REMOVED_CLAIM} The quiz still filtered the browsers out.\n\n"
            f"Never Blank: {ECHO}")
    payload = json.dumps({"body": body, "echo_included": True, "title": None})

    with mock.patch.object(platform_composer, "chat", return_value=payload):
        result = recompose_platform(
            _structured(), "instagram",
            canonical_body=DRAFT_WITH_CLAIM,          # this article DOES say it
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
        )

    assert result["body"] == body


def test_a_first_composition_has_no_source_to_be_faithful_to():
    """The guard judges derivations only: a first composition has no final
    accepted content behind it, and its figures are the article's own."""
    body = ("An article body that states 41% and 1,200 on its own "
            f"authority.\n\n{ECHO}")
    payload = json.dumps({"body": body, "echo_included": True, "title": "T"})

    with mock.patch.object(platform_composer, "chat", return_value=payload):
        result = _compose_one(_structured(), "long")

    assert result["body"] == body


@pytest.mark.parametrize("written,source,invented", [
    ("1,200 owners", "1200 owners", False),      # separators are layout
    ("28.0%", "28%", False),                     # so are trailing zeros
    ("rose 28%", "rose 29%", True),
    ("in 2026", "in 2025", True),
])
def test_figures_are_compared_by_value_not_by_spelling(written, source, invented):
    assert bool(_figures(written) - _figures(source)) is invented


# ---------------------------------------------------------------------------
# End to end, through the REAL acceptance boundary and derivation seam
# ---------------------------------------------------------------------------


def _run_with_composer(tmp_path, composer):
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]           # the REAL acceptance boundary
    del patches["recompose_platform"]                 # the REAL derivation seam
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    draft = _draft()
    draft["platforms"]["long"] = {"body": DRAFT_WITH_CLAIM, "title": TITLE}
    patches["generate_article"] = mock.MagicMock(return_value=draft)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Remove the unsupported engagement claim."),
        _review_payload(),
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(platform_composer, "chat", side_effect=composer), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=reviewer,
                    article_revisor=FakeRevisionTransport(ACCEPTED_WITHOUT_CLAIM),
                    derivation_judge=RecordingJudge())
    generated = next(tmp_path.glob(f"{SIG}/runs/*/generated.json"), None)
    return code, patches, json.loads(generated.read_text()) if generated else None


class RestoringComposer(FaithfulComposer):
    """Faithful on every surface except Instagram, where it puts back the
    claim Editorial Revision removed — the invention class run 35417616416
    showed on exactly that surface."""

    def __call__(self, *, system, user, **kwargs):
        raw = super().__call__(system=system, user=user, **kwargs)
        if not re.search(r"^FORMAT: instagram$", user, re.MULTILINE):
            return raw
        data = json.loads(raw)
        opening, _, rest = data["body"].partition("\n")
        data["body"] = f"{opening} {REMOVED_CLAIM}\n{rest}"
        return json.dumps(data)


def test_a_claim_revision_removed_reaches_no_social_surface(tmp_path):
    """The invariant, end to end: draft states it, revision removes it, and
    every derivative composed from the final article is free of it."""
    code, _, generated = _run_with_composer(tmp_path, FaithfulComposer())

    assert code == 0
    assert REMOVED_CLAIM in DRAFT_WITH_CLAIM
    assert "41%" not in generated["blog_article"]
    for surface in ("linkedin_post", "facebook_post", "instagram_caption",
                    "telegram_text"):
        assert generated[surface].strip(), surface
        assert "41%" not in generated[surface], surface
    assert "41%" not in "\n".join(generated["threads_sequence"])


def test_an_instagram_derivation_that_restores_the_claim_stops_the_run(tmp_path):
    code, _, generated = _run_with_composer(tmp_path, RestoringComposer())

    assert code == 1
    assert generated is None                       # nothing publishable exists
    # and the accepted article is still there to read, without the claim
    record = _artifact(tmp_path, "accepted_composition.json")
    assert record["content"]["article_body"] == ACCEPTED_WITHOUT_CLAIM
    assert "41%" not in record["content"]["article_body"]
    # both refused attempts are preserved, and both carried the restored claim
    attempts = _artifact(tmp_path, "rejected_composition.json")["attempts"]
    assert len(attempts) == 2
    assert all(REMOVED_CLAIM in attempt["body"] for attempt in attempts)
