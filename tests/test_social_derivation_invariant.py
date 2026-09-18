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
        body = "\n\n".join(sentences[:6] + [f"**Never Blank:** {ECHO}"])
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
