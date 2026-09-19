"""Invariant: every social derivative comes from the FINAL ACCEPTED article.

Never from the pre-review draft, its outline or narrative spine, its Echo or
CTA, or a composition made before Editorial Acceptance. Controlled live run
35383199073 broke it: the reviewer removed "total engagement numbers drop"
from the article as unsupported, and the Threads and Telegram texts — built
from the draft's structured fields before acceptance — still carried it.

Product Owner decisions (#259): Telegram and Threads are Engine/SPE platform
adaptations of the final accepted article — not deterministic excerpts — that
carry its headline/hook, observation, evidence, mechanism, implication and
Echo, never cut a sentence to meet a length target, and never add a fact.
Channel mechanics are the Engine's; how a client adapts is a future
onboarding decision, not Never Blank policy.

The regressions below run end to end through the real entrypoint, the REAL
acceptance boundary (reviewer + reviser transports), and the REAL derivation
seam and composer — with a fake model that writes only from what its prompt
contains, so any claim that reaches a prompt reaches the output.

No network, no model.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.content.output_guard import (
    split_threads_posts,
    validate_telegram_adaptation,
    validate_threads_adaptation,
)
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

PREVIEW_FORMATS = {"medium", "reading", "instagram", "telegram", "threads"}


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
        "cta_line": f"Ask us how {CLAIM}.",
        "echo_line": ECHO,
        "discovery": {"aha_setup": f"You notice {CLAIM}.",
                      "first_wrong_explanation": f"At first {CLAIM}."},
    })
    return article


class FaithfulComposer:
    """A fake composer model that writes ONLY from what its prompt contains.

    It restates the content it was handed — the canonical block and anything
    listed as a required element — so a claim reaching its prompt by any
    route reaches its output. It honours the format's mechanics (Threads
    posts separated by '---') and closes with whichever Echo it was given.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, *, system, user, **kwargs):
        self.prompts.append(user)
        format_key = re.search(r"^FORMAT: (\w+)$", user, re.MULTILINE).group(1)
        handed = user.split("FORMAT:", 1)[0]
        outline = user.split("REQUIRED ELEMENTS:", 1)[-1] if (
            "REQUIRED ELEMENTS:" in user) else user.split("STRUCTURED FIELDS:", 1)[-1]
        sentences = [
            line.strip() for line in (handed + "\n" + outline).splitlines()
            if line.strip() and not line.isupper() and "Never Blank" not in line
            and not line.startswith(("FINAL CANONICAL", "ECHO MODE", "Write the",
                                     "- echo", "TARGET", "FORMAT", "CTA"))
        ][:4]
        echo = re.search(r"^- echo \[[^\]]*\]: (.+)$", user, re.MULTILINE)
        closing = [f"**Never Blank:** {echo.group(1).strip()}"] if echo else []
        if format_key == "threads":
            body = "\n---\n".join([s[:440] for s in sentences] + closing)
        else:
            body = "\n\n".join(sentences + closing)
        return json.dumps({"body": body, "echo_included": True,
                           "title": TITLE if format_key == "long" else None})


def _run(tmp_path, *, draft=None, revised=FINAL_ARTICLE):
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]           # the REAL acceptance boundary
    del patches["recompose_platform"]                 # the REAL derivation seam
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    patches["generate_article"] = mock.MagicMock(return_value=draft or _draft())
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Remove the unsupported claim about total engagement."),
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
                    article_revisor=FakeRevisionTransport(revised))
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


# ===========================================================================
# The failure class: a claim revision removed reaches no social surface
# ===========================================================================


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
    formats = {re.search(r"^FORMAT: (\w+)$", p, re.MULTILINE).group(1) for p in derivations}
    assert formats == PREVIEW_FORMATS
    for prompt in derivations:
        assert CLAIM not in prompt                    # outline, spine, CTA, Echo
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
# The Echo and CTA come from the accepted article, never the draft
# ===========================================================================


ECHO_CLAIM = "Engagement fell by 90%, which proves the quiz works."


def test_a_claim_in_the_draft_echo_never_survives_revision(tmp_path):
    draft = _draft()
    draft["structured_article"]["echo_line"] = ECHO_CLAIM
    draft["platforms"]["long"]["body"] = DRAFT_ARTICLE.replace(
        f"**Never Blank:** {ECHO}", f"**Never Blank:** {ECHO_CLAIM}")

    code, _, composer, _, generated = _run(tmp_path, draft=draft)

    assert code == 0
    for surface, text in _social_outputs(generated).items():
        assert "90%" not in text, f"{surface} carried the draft Echo's claim"
    for prompt in composer.prompts:
        if "FINAL CANONICAL CONTENT" in prompt:
            assert ECHO_CLAIM not in prompt
    record = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/accepted_composition.json")).read_text())
    assert record["content"]["echo"] == ECHO


def test_the_accepted_echo_rule():
    from scripts.generate_and_publish import _accepted_echo

    assert _accepted_echo(f"Body.\n\n**Never Blank:** {ECHO}", ECHO_CLAIM) == ECHO
    assert _accepted_echo(f"Body.\n\nNever Blank: {ECHO}", "") == ECHO
    # inside a sentence proves nothing; as the whole closing paragraph it stands
    assert _accepted_echo(f"Body ends with {ECHO_CLAIM}", ECHO_CLAIM) == ""
    assert _accepted_echo(f"Body.\n\n{ECHO_CLAIM}", ECHO_CLAIM) == ECHO_CLAIM
    assert _accepted_echo("Body without it.", ECHO_CLAIM) == ""


def test_a_negated_echo_is_not_rescued_by_substring():
    from scripts.generate_and_publish import _accepted_echo

    article = ("Opening paragraph that sets the scene.\n\n"
               "We cannot conclude that Every click is a buyer.")
    assert _accepted_echo(article, "Every click is a buyer.") == ""


def test_a_wrapped_attributed_echo_is_taken_whole():
    from scripts.generate_and_publish import _accepted_echo

    article = "Opening paragraph.\n\n**Never Blank:** Only purchases\nshow demand."
    assert _accepted_echo(article, "") == "Only purchases show demand."


def test_no_derivative_receives_the_draft_cta():
    from src.editorial.platform_composer import _build_user_prompt

    structured = {"hook": "h", "echo_line": ECHO,
                  "cta_line": "Request the system that doubles conversions."}
    for fmt in ("medium", "telegram", "threads"):
        prompt = _build_user_prompt(structured, fmt, "reflection",
                                    canonical_body=FINAL_ARTICLE)
        assert "doubles conversions" not in prompt, fmt
        assert ECHO in prompt


# ===========================================================================
# Every route derives after acceptance; reuse is lineage-gated
# ===========================================================================


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


# ===========================================================================
# Preview surfaces: rules, transparency, and no draft-era excerpts
# ===========================================================================


def _preview_with_stub_derivation(tmp_path, reading_body=FINAL_ARTICLE):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    article = copy.deepcopy(_draft())
    article["platforms"]["long"]["body"] = FINAL_ARTICLE
    article["platforms"]["reading"]["body"] = reading_body
    patches["generate_article"] = mock.MagicMock(return_value=article)

    def derive(structured, format_key, **kwargs):
        body = {"reading": reading_body,
                "threads": f"First post.\n---\n**Never Blank:** {ECHO}"}.get(
            format_key, f"A {format_key} derivation.\n\n**Never Blank:** {ECHO}")
        return {"body": body, "word_count": len(body.split()),
                "echo_included": True, "title": None}

    patches["recompose_platform"] = mock.MagicMock(side_effect=derive)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


def test_the_preview_hands_each_surface_its_role_rules(tmp_path):
    code, patches = _preview_with_stub_derivation(tmp_path)

    assert code == 0
    calls = {c.args[1]: c.kwargs for c in patches["recompose_platform"].call_args_list}
    assert set(calls) == PREVIEW_FORMATS
    for fmt in PREVIEW_FORMATS - {"medium"}:
        rules = calls[fmt]["editorial_role_rules"]
        assert isinstance(rules, dict) and set(rules) == {fmt}, fmt
        assert rules[fmt], f"{fmt} lost its role rules"
    assert "SOURCES OF RECORD" in calls["reading"]["editorial_role_rules"]["reading"]
    for fmt in PREVIEW_FORMATS:
        assert calls[fmt]["canonical_body"] == FINAL_ARTICLE, fmt


def test_an_unattributed_preview_facebook_post_blocks_the_preview(tmp_path):
    code, _ = _preview_with_stub_derivation(
        tmp_path, reading_body=f"A Facebook post that cites nothing.\n\n**Never Blank:** {ECHO}")

    assert code == 1
    assert not list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))


def test_a_normal_run_writes_no_draft_era_telegram_or_threads(tmp_path):
    """The deterministic excerpts are gone: outside the preview, the non-R1
    adaptations are simply not composed (#175) — never approximated."""
    from tests.test_monday_stream import _run_with_role

    code, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE)

    assert code == 0
    generated = json.loads(next(tmp_path.glob("*/runs/*/generated.json")).read_text())
    assert generated["telegram_text"] == ""
    assert generated["threads_sequence"] == []
    formats = [c.args[1] for c in patches["recompose_platform"].call_args_list]
    assert formats == ["medium"]
    source = Path("scripts/generate_and_publish.py").read_text()
    for gone in ("def _build_telegram", "def _build_threads", "max_words: int = 34"):
        assert gone not in source


# ===========================================================================
# Telegram and Threads are Engine platform adapters (PO decision)
# ===========================================================================


@pytest.mark.parametrize("fmt", ["telegram", "threads"])
def test_an_adapter_cannot_be_composed_without_the_final_article(fmt):
    from src.editorial.platform_composer import ALL_FORMATS, compose_platforms

    assert fmt not in ALL_FORMATS                     # never a first composition
    with pytest.raises(ValueError, match="final accepted article"):
        compose_platforms({"hook": "h", "echo_line": ECHO}, formats=(fmt,))


def test_the_telegram_adapter_rules_carry_the_whole_argument():
    from src.editorial.platform_composer import _WORD_RANGE, _build_user_prompt

    prompt = _build_user_prompt({"echo_line": ECHO}, "telegram", "none",
                                canonical_body=FINAL_ARTICLE)
    assert _WORD_RANGE["telegram"] == (180, 300)
    assert "TARGET LENGTH: 180-300 words" in prompt
    for element in ("headline/hook", "core observation", "concrete evidence",
                    "mechanism", "practical business implication", "final Echo"):
        assert element in prompt, element
    assert "add no fact" in prompt
    assert FINAL_ARTICLE in prompt


def test_the_threads_adapter_rules_demand_evidence_not_the_opening():
    from src.editorial.platform_composer import _build_user_prompt

    prompt = _build_user_prompt({"echo_line": ECHO}, "threads", "none",
                                canonical_body=FINAL_ARTICLE)
    assert "not merely the opening of the article" in prompt
    assert "evidence" in prompt and "mechanism" in prompt
    assert "---" in prompt and "Add no fact" in prompt


def test_a_long_telegram_adaptation_is_never_cut():
    """The target is a target: a 300-word, many-paragraph post passes intact."""
    paragraphs = ["This is one complete sentence of the adaptation, "
                  "written in full with no cut at all." for _ in range(20)]
    text = "\n\n".join(paragraphs)
    assert len(text.split()) > 250

    validate_telegram_adaptation(text)                # no line or word cap


@pytest.mark.parametrize("text,match", [
    ("x" * 4097, "4096"),
    ("A post with #hashtags.", "hashtags"),
    ("Read more on the blog.", "teaser"),
    ("   ", "empty"),
])
def test_the_telegram_adapter_keeps_telegrams_own_mechanics(text, match):
    with pytest.raises(ValueError, match=match):
        validate_telegram_adaptation(text)


def test_the_legacy_telegram_signal_contract_is_untouched():
    from src.content.output_guard import validate_telegram

    with pytest.raises(ValueError, match="maximum is 3"):
        validate_telegram("one\ntwo\nthree\nfour")


def test_threads_mechanics():
    ok = "First post.\n---\nSecond post.\n---\nThird post."
    assert split_threads_posts(ok) == ["First post.", "Second post.", "Third post."]
    validate_threads_adaptation(ok)
    with pytest.raises(ValueError, match="500"):
        validate_threads_adaptation("x" * 501 + "\n---\nSecond.")
    with pytest.raises(ValueError, match="posts"):
        validate_threads_adaptation("Only one post.")
    with pytest.raises(ValueError, match="posts"):
        validate_threads_adaptation("\n---\n".join(f"Post {i}." for i in range(7)))


def test_a_thread_leads_with_the_title_without_breaking_the_post_limit():
    from scripts.generate_and_publish import _lead_thread_with_canonical_title

    assert _lead_thread_with_canonical_title(["Hook.", "Echo."], TITLE)[0] == (
        f"{TITLE}\n\nHook.")
    long_first = "y" * 480
    assert _lead_thread_with_canonical_title([long_first, "Echo."], TITLE) == [
        TITLE, long_first, "Echo."]
    assert _lead_thread_with_canonical_title(["Hook."], None) == ["Hook."]
