"""Invariant: every social derivative comes from the FINAL ACCEPTED article.

Never from the pre-review draft, its outline or narrative spine, or a
composition made before Editorial Acceptance. Controlled live run 35383199073
broke it: the reviewer removed "total engagement numbers drop" from the
article as unsupported, and the Threads and Telegram texts — built from the
draft's structured fields before acceptance — still carried it.

The regression below is exactly that failure class, end to end through the
real entrypoint, the REAL acceptance boundary (reviewer + reviser transports)
and the REAL derivation seam and composer (a fake model that writes only from
what its prompt contains). It runs as the owner-controlled full-content
preview, so every surface — LinkedIn, Facebook, Instagram, Threads, Telegram
— is produced and checked.

No network, no model.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_monday_stream import FIXTURE_SOURCE_TITLE, FIXTURE_SOURCE_URL, MONDAY_ROLE
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_visual_contract import _pimgs

SIG = legacy._SIGNAL_ID
TITLE = "Why Fewer Clicks on Your Ad Could Mean More Sales for Your Business"
ECHO = "The drop in clicks can be the first sign that your ad is finally working."

#: The unsupported claim, planted in every part of the draft.
CLAIM = "total engagement numbers dropped after the quiz was added"

_CITATION = f"Source: {FIXTURE_SOURCE_TITLE} ({FIXTURE_SOURCE_URL})."

DRAFT_ARTICLE = (
    "Every like and comment on your ad can disguise how few people are ready to buy.\n\n"
    f"In one documented case, {CLAIM}, while form submissions rose 28%. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)
FINAL_ARTICLE = (
    "Every like and comment on your ad can disguise how few people are ready to buy.\n\n"
    f"In one documented case, form submissions rose 28%. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)


def _draft() -> dict:
    article = copy.deepcopy(legacy._FAKE_ARTICLE)
    article["platforms"]["long"] = {"body": DRAFT_ARTICLE, "title": TITLE}
    # every draft surface and every outline field carries the claim
    for key in ("medium", "reading", "instagram"):
        article["platforms"][key] = {"body": f"Draft {key}: {CLAIM}. {ECHO}"}
    structured = article["structured_article"]
    structured.update({
        "hook": f"Draft hook: {CLAIM}.",
        "surviving_explanation": f"Because {CLAIM}.",
        "reframe": f"The reframe: {CLAIM}.",
        "business_translation": f"The consequence: {CLAIM}.",
        "narrative_spine": f"The spine: {CLAIM}.",
        "echo_line": ECHO,
        "discovery": {"aha_setup": f"You notice {CLAIM}.",
                      "first_wrong_explanation": f"At first {CLAIM}."},
    })
    return article


class FaithfulComposer:
    """A fake composer model that writes ONLY from what its prompt contains.

    It restates every sentence of the content it was handed. If a claim
    reaches its prompt by any route, it reaches the output: the fake is built
    to expose leakage, not to hide it.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, *, system, user, **kwargs):
        self.prompts.append(user)
        format_key = re.search(r"^FORMAT: (\w+)$", user, re.MULTILINE).group(1)
        handed = user.split("FORMAT:", 1)[0]          # the canonical content block
        outline = user.split("REQUIRED ELEMENTS:", 1)[-1] if (
            "REQUIRED ELEMENTS:" in user) else user.split("STRUCTURED FIELDS:", 1)[-1]
        sentences = [
            line.strip() for line in (handed + "\n" + outline).splitlines()
            if line.strip() and not line.isupper() and "Never Blank" not in line
            and not line.startswith(("FINAL CANONICAL", "ECHO MODE", "Write the",
                                     "- echo", "TARGET", "FORMAT", "CTA"))
        ]
        # the Echo it was handed — whichever one reached the prompt
        echo = re.search(r"^- echo \[[^\]]*\]: (.+)$", user, re.MULTILINE)
        body = "\n\n".join(sentences[:6] + (
            [f"**Never Blank:** {echo.group(1).strip()}"] if echo else []))
        return json.dumps({"body": body, "echo_included": True,
                           "title": TITLE if format_key == "long" else None})


def _run(tmp_path):
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]           # the REAL acceptance boundary
    del patches["recompose_platform"]                 # the REAL derivation seam
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    patches["generate_article"] = mock.MagicMock(return_value=_draft())
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Remove the unsupported claim about total engagement."),
        _review_payload(),
    )
    revisor = FakeRevisionTransport(FINAL_ARTICLE)
    composer = FaithfulComposer()
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(platform_composer, "chat", side_effect=composer), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=reviewer, article_revisor=revisor)
    generated = next(tmp_path.glob(f"{SIG}/runs/*/generated.json"), None)
    return code, patches, composer, reviewer, (
        json.loads(generated.read_text()) if generated else None)


def _social_outputs(generated: dict) -> dict[str, str]:
    return {
        "linkedin": generated["linkedin_post"],
        "facebook": generated["facebook_post"],
        "instagram": generated["instagram_caption"],
        "threads": "\n".join(generated["threads_sequence"]),
        "telegram": generated["telegram_text"],
    }


def test_a_claim_removed_by_revision_reaches_no_social_surface(tmp_path):
    code, _, _, reviewer, generated = _run(tmp_path)

    assert code == 0
    # the scenario really happened: the draft carried the claim, the
    # reviewer demanded its removal, and the accepted article is without it
    assert CLAIM in DRAFT_ARTICLE
    assert len(reviewer.calls) == 2
    assert CLAIM not in generated["blog_article"]
    # and not one final social output carries it
    for surface, text in _social_outputs(generated).items():
        assert text.strip(), f"{surface} is empty — the preview produced nothing"
        assert CLAIM not in text, f"{surface} kept the claim revision removed"


def test_no_derivation_prompt_ever_saw_the_draft(tmp_path):
    _, _, composer, _, _ = _run(tmp_path)

    derivations = [p for p in composer.prompts if "FINAL CANONICAL CONTENT" in p]
    assert len(derivations) == 3                     # medium, reading, instagram
    for prompt in derivations:
        assert CLAIM not in prompt
        assert "NARRATIVE SPINE" not in prompt


def test_every_surface_leads_with_the_canonical_title(tmp_path):
    _, _, _, _, generated = _run(tmp_path)

    assert generated["title"] == TITLE
    for surface, text in _social_outputs(generated).items():
        first = next(line for line in text.splitlines() if line.strip())
        assert first.replace("*", "").strip().startswith(TITLE), surface


def test_nothing_is_published_or_consumed(tmp_path):
    code, patches, _, _, _ = _run(tmp_path)

    assert code == 0
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called


# ===========================================================================
# Threads and Telegram: accepted text only, whole sentences only
# ===========================================================================


def test_no_telegram_or_threads_line_ends_mid_sentence():
    from scripts.generate_and_publish import _build_telegram, _build_threads

    long_sentence = " ".join(f"word{i}" for i in range(40)) + " ends here."
    article = (f"{long_sentence}\n\nA short opening. A second short sentence.\n\n"
               f"**Never Blank:** {ECHO}")

    telegram = _build_telegram(TITLE, article, ECHO)
    threads = _build_threads(TITLE, article, ECHO)

    for line in telegram.splitlines() + threads:
        assert re.search(r"[.!?…]$", line.strip()) or line.strip() == TITLE, line
    # the over-long sentence is skipped, never cut to fit
    assert "word39" not in telegram
    assert "A short opening. A second short sentence." in telegram


def test_the_live_truncation_cannot_recur():
    """Run 35383199073: "…and follow through—making your." — a 34-word cut."""
    from scripts.generate_and_publish import _whole_sentences

    sentence = ("You launch a new ad with an embedded quiz and notice that, although "
                "total engagement numbers drop, the people who do respond are much "
                "more likely to leave their information and follow through—making "
                "your sales calls more productive.")
    assert _whole_sentences(sentence, 34) == ""        # skipped, never cut
    assert _whole_sentences(sentence, 60) == sentence


def test_telegram_keeps_the_existing_contract():
    from scripts.generate_and_publish import _build_telegram
    from src.content.output_guard import validate_telegram

    text = _build_telegram(TITLE, FINAL_ARTICLE, ECHO)

    validate_telegram(text)                            # ≤3 lines, ≤90 words, no '#'
    assert text.splitlines() == [
        TITLE,
        "Every like and comment on your ad can disguise how few people are ready to buy.",
        ECHO,
    ]


# ===========================================================================
# #259 review round 2
# ===========================================================================


ECHO_CLAIM = "Engagement fell by 90%, which proves the quiz works."
REVISED_ECHO = "The drop in clicks can be the first sign that your ad is finally working."


def test_a_claim_in_the_draft_echo_never_survives_revision(tmp_path, monkeypatch):
    """The draft's Echo predates acceptance: the accepted article's Echo wins."""
    draft = _draft()
    draft["structured_article"]["echo_line"] = ECHO_CLAIM
    draft["platforms"]["long"]["body"] = DRAFT_ARTICLE.replace(
        f"**Never Blank:** {ECHO}", f"**Never Blank:** {ECHO_CLAIM}")

    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]
    del patches["recompose_platform"]
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    patches["generate_article"] = mock.MagicMock(return_value=draft)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="The Echo's 90% claim is unsupported."),
        _review_payload(),
    )
    composer = FaithfulComposer()
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(platform_composer, "chat", side_effect=composer), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=reviewer,
                    article_revisor=FakeRevisionTransport(FINAL_ARTICLE))

    assert code == 0
    generated = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/generated.json")).read_text())
    for surface, text in _social_outputs(generated).items():
        assert "90%" not in text, f"{surface} carried the draft Echo's claim"
    for prompt in composer.prompts:
        if "FINAL CANONICAL CONTENT" in prompt:
            assert ECHO_CLAIM not in prompt
    record = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/accepted_composition.json")).read_text())
    assert record["content"]["echo"] == REVISED_ECHO


def test_the_accepted_echo_rule():
    from scripts.generate_and_publish import _accepted_echo

    assert _accepted_echo(f"Body.\n\n**Never Blank:** {REVISED_ECHO}", ECHO_CLAIM) == REVISED_ECHO
    assert _accepted_echo(f"Body.\n\nNever Blank: {REVISED_ECHO}", "") == REVISED_ECHO
    # inside a sentence proves nothing; as the whole closing paragraph it stands
    assert _accepted_echo(f"Body ends with {ECHO_CLAIM}", ECHO_CLAIM) == ""
    assert _accepted_echo(f"Body.\n\n{ECHO_CLAIM}", ECHO_CLAIM) == ECHO_CLAIM
    assert _accepted_echo("Body without it.", ECHO_CLAIM) == ""       # never the draft's


def test_the_wednesday_route_also_derives_after_acceptance(tmp_path):
    """No route keeps a pre-acceptance composition, revised or not."""
    from tests.test_monday_stream import _run_with_role
    code, patches, _ = _run_with_role(tmp_path, "never-blank-wednesday-golden")

    assert code == 0
    derive = patches["recompose_platform"]
    assert derive.call_count == 1
    assert derive.call_args.args[1] == "medium"
    record = json.loads(next(tmp_path.glob("*/runs/*/accepted_composition.json")).read_text())
    assert record["editorial"]["revised"] is False
    assert record["social_recomposition"]["performed"] is True


def test_a_package_without_the_lineage_marker_is_never_republished(tmp_path):
    from tests.test_generate_and_publish import _base_patches, _valid_package, _write_package

    stale = _valid_package()
    stale.pop("social_derivation")
    _write_package(tmp_path, stale)
    argv, patches = _base_patches(dry_run=False, from_package=True)
    patches["PACKAGES_DIR"] = tmp_path
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 1

    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called


def test_every_fresh_run_records_the_lineage_marker(tmp_path):
    _, _, _, _, generated = _run(tmp_path)

    assert generated["social_derivation"] == gap.SOCIAL_DERIVATION_LINEAGE


@pytest.mark.parametrize("text,limit,expected", [
    ("We consulted Dr. Smith about the campaign results in detail this week.", 5, ""),
    ("We consulted Dr. Smith about it. Then we acted.", 7,
     "We consulted Dr. Smith about it."),
    ("Acme Inc. grew. Sales rose.", 5, "Acme Inc. grew. Sales rose."),
    ("Acme Inc. grew. Sales rose.", 4, "Acme Inc. grew."),
    ("J. Doe ran the test. It worked.", 5, "J. Doe ran the test."),
], ids=["dr-too-long", "dr-fits", "inc", "inc-partial", "initial"])
def test_abbreviations_never_end_a_sentence(text, limit, expected):
    from scripts.generate_and_publish import _whole_sentences

    assert _whole_sentences(text, limit) == expected


def test_the_preview_hands_each_surface_its_role_rules(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    article = copy.deepcopy(_draft())
    article["platforms"]["long"]["body"] = FINAL_ARTICLE
    article["platforms"]["reading"]["body"] = FINAL_ARTICLE
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0

    calls = {c.args[1]: c.kwargs for c in patches["recompose_platform"].call_args_list}
    assert set(calls) == {"medium", "reading", "instagram"}
    for fmt in ("reading", "instagram"):
        rules = calls[fmt]["editorial_role_rules"]
        assert isinstance(rules, dict) and set(rules) == {fmt}, fmt
        assert rules[fmt], f"{fmt} lost its role rules"
    # the Facebook derivation gets the rules that carry the sources of record
    assert "SOURCES OF RECORD" in calls["reading"]["editorial_role_rules"]["reading"]


def test_an_unattributed_preview_facebook_post_blocks_the_preview(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    article = copy.deepcopy(_draft())
    article["platforms"]["long"]["body"] = FINAL_ARTICLE
    article["platforms"]["reading"]["body"] = "A Facebook post that cites nothing."
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: []):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1

    assert not list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))


# ===========================================================================
# #259 review round 3
# ===========================================================================


def test_a_negated_echo_is_not_rescued_by_substring():
    from scripts.generate_and_publish import _accepted_echo, _build_telegram

    article = ("Opening paragraph that sets the scene.\n\n"
               "We cannot conclude that Every click is a buyer.")
    assert _accepted_echo(article, "Every click is a buyer.") == ""
    assert "Every click is a buyer." not in _build_telegram(
        TITLE, article, _accepted_echo(article, "Every click is a buyer."))


def test_the_draft_echo_survives_only_as_the_whole_closing_paragraph():
    from scripts.generate_and_publish import _accepted_echo

    article = "Opening paragraph.\n\nEvery click is a buyer."
    assert _accepted_echo(article, "Every click is a buyer.") == "Every click is a buyer."


def test_a_wrapped_attributed_echo_is_taken_whole():
    from scripts.generate_and_publish import _accepted_echo, _build_telegram

    article = "Opening paragraph.\n\n**Never Blank:** Only purchases\nshow demand."
    echo = _accepted_echo(article, "")
    assert echo == "Only purchases show demand."
    assert _build_telegram(TITLE, article, echo).splitlines()[-1] == echo


def test_no_derivative_receives_the_draft_cta():
    from src.editorial.platform_composer import _build_user_prompt

    structured = {"hook": "h", "echo_line": ECHO,
                  "cta_line": "Request the system that doubles conversions."}
    prompt = _build_user_prompt(structured, "medium", "reflection",
                                canonical_body=FINAL_ARTICLE)
    assert "doubles conversions" not in prompt
    assert ECHO in prompt


@pytest.mark.parametrize("text", [
    "We spoke to Assoc. Prof. Smith about the campaign results before approving any spending.",
    "Gov. Lee said the rule changes in March for every small shop in the state.",
    "The U.K. regulator approved it after a long review of the whole market.",
])
def test_unlisted_abbreviations_never_produce_a_cut(text):
    from scripts.generate_and_publish import _whole_sentences

    for limit in range(1, len(text.split()) + 1):
        result = _whole_sentences(text, limit)
        assert result in ("", text), (limit, result)


def test_a_period_followed_by_lowercase_never_ends_a_sentence():
    """#259 review round 4: "30 min. before …" is one sentence."""
    from scripts.generate_and_publish import _build_telegram, _whole_sentences

    sentence = ("The team waited 30 min. before reviewing the campaign results and "
                "checking whether the new checkout design had changed the number of "
                "completed purchases among customers who arrived through the paid "
                "social advertisements that morning.")
    for limit in range(1, 40):
        assert _whole_sentences(sentence, limit) in ("", sentence), limit
    telegram = _build_telegram(TITLE, f"{sentence}\n\nA short second paragraph.", "")
    assert "30 min." not in telegram
    assert telegram.splitlines()[-1] == "A short second paragraph."


def test_a_numbered_list_marker_never_ends_a_sentence():
    """#259 review round 5: "steps: 1. Review …" is not "…steps: 1."."""
    from scripts.generate_and_publish import _build_telegram, _whole_sentences

    text = ("The checklist has three steps: 1. Review every campaign result against "
            "the purchases it produced, and compare them with the previous month "
            "before deciding whether the new ad format should replace the old one "
            "for every product line.")
    for limit in range(1, 45):
        assert _whole_sentences(text, limit) in ("", text), limit
    telegram = _build_telegram("Campaign review", text, "")
    assert telegram == "Campaign review"                 # skipped, never cut


@pytest.mark.parametrize("text", [
    "The team tested “Ready to buy? Compare all available plans and choose the one "
    "that best fits your business before you enter your payment details and complete "
    "your first purchase with us today” against its original checkout message.",
    'The team tested "Ready to buy? Compare all available plans and choose the one '
    'that best fits your business before you enter your payment details today" '
    "against its original checkout message.",
    "The owner (who asked. Twice. about refunds before signing the contract with the "
    "new supplier that quarter) finally switched vendors.",
], ids=["curly-quotes", "straight-quotes", "parentheses"])
def test_a_boundary_inside_an_open_quote_never_ends_the_sentence(text):
    """#259 review round 6."""
    from scripts.generate_and_publish import _build_telegram, _whole_sentences

    for limit in range(1, 50):
        assert _whole_sentences(text, limit) in ("", text), limit
    # Telegram carries the whole sentence when it fits, and nothing otherwise
    assert _build_telegram("Checkout test", text, "") in (
        "Checkout test", f"Checkout test\n{text}")


@pytest.mark.parametrize("text", [
    "The team tested ‘Ready to buy? Compare all available plans and choose the one that "
    "best fits your business before you enter your payment details and complete your "
    "first purchase with us today’ against its original checkout message.",
    "The team tested 'Ready to buy? Compare all available plans and choose the one that "
    "best fits your business before you enter your payment details and complete your "
    "first purchase with us today' against its original checkout message.",
], ids=["curly-single", "straight-single"])
def test_single_quoted_speech_never_ends_the_outer_sentence(text):
    """#259 review round 7."""
    from scripts.generate_and_publish import _build_telegram, _whole_sentences

    for limit in range(1, 50):
        assert _whole_sentences(text, limit) in ("", text), limit
    assert _build_telegram("Checkout test", text, "") in (
        "Checkout test", f"Checkout test\n{text}")


@pytest.mark.parametrize("text", [
    "Owners don’t read every report. They skim the numbers.",
    "Owners don't read every report. They skim the numbers.",
    "The customers’ orders doubled. The team noticed.",
])
def test_apostrophes_are_not_quotes(text):
    from scripts.generate_and_publish import _sentences

    assert len(_sentences(text)) == 2
