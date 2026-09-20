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


class RecordingJudge:
    """A test fidelity judge: records every check and flags only the phrases it
    is told are unsupported, when a derivative contains them. The production
    judge is a model call; these suites prove the plumbing and the gate."""

    def __init__(self, flag: tuple[str, ...] = ()) -> None:
        self.flag = flag
        self.calls: list[dict] = []

    def unsupported(self, *, final_content, derivative, surface, removed_by_review=()):
        self.calls.append({"final_content": final_content, "derivative": derivative,
                           "surface": surface, "removed_by_review": removed_by_review})
        return [phrase for phrase in self.flag
                if phrase.casefold() in derivative.casefold()
                and phrase.casefold() not in final_content.casefold()]


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
        supplied = re.search(r"^- echo \[[^\]]*\]: (.+)$", user, re.MULTILINE)
        echo_text = supplied.group(1).strip() if supplied else ""
        sentences = [
            line.strip() for line in (handed + "\n" + outline).splitlines()
            if line.strip() and not line.isupper()
            and not (echo_text and echo_text in line)
            and not line.startswith(("FINAL CANONICAL", "ECHO MODE", "Write the",
                                     "- echo", "TARGET", "FORMAT", "CTA"))
        ][:4]
        echo = re.search(r"^- echo \[[^\]]*\]: (.+)$", user, re.MULTILINE)
        # close with the attribution THIS prompt instructs — the adapter's
        # client name or the shared composer's constant — never assume one
        named = re.search(r"'(?:\*\*)?([^'*:]+):(?:\*\*)? <echo>'", user)
        attribution = named.group(1).strip() if named else "Never Blank"
        closing = [f"{attribution}: {echo.group(1).strip()}"] if echo else []
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
                    article_revisor=FakeRevisionTransport(revised),
                    derivation_judge=RecordingJudge())
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

    assert _accepted_echo(f"Body.\n\n**Never Blank:** {ECHO}", ECHO_CLAIM, "Never Blank") == ECHO
    assert _accepted_echo(f"Body.\n\nNever Blank: {ECHO}", "", "Never Blank") == ECHO
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
    assert _accepted_echo(article, "", "Never Blank") == "Only purchases show demand."


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
                "threads": f"First post.\n---\nSecond post.\n---\n**Never Blank:** {ECHO}"}.get(
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
    for element in ("headline or opening hook", "central observation",
                    "concrete evidence", "explanation of why it happens",
                    "implications it draws", "closing line"):
        assert element in prompt, element
    assert "add no fact" in prompt
    assert FINAL_ARTICLE in prompt


def test_the_threads_adapter_rules_demand_evidence_not_the_opening():
    from src.editorial.platform_composer import _build_user_prompt

    prompt = _build_user_prompt({"echo_line": ECHO}, "threads", "none",
                                canonical_body=FINAL_ARTICLE)
    assert "not merely the opening of the content" in prompt
    assert "concrete evidence" in prompt and "explanation of why it happens" in prompt
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
        validate_threads_adaptation("x" * 501 + "\n---\nSecond.\n---\nThird.")
    with pytest.raises(ValueError, match="posts"):
        validate_threads_adaptation("Only one post.")
    # the contract is 3–6 (#259 review): two posts are not a thread
    with pytest.raises(ValueError, match="3–6"):
        validate_threads_adaptation("First post.\n---\nSecond post.")
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


# ===========================================================================
# #259 review (0df2a10): the adapter seam passes the Replace-the-client test
# ===========================================================================


_CLIENT_TERMS = ("never blank", "small-business", "small business", "owner",
                 "business implication", "compound presence", "customer trust")


@pytest.mark.parametrize("fmt", ["telegram", "threads"])
def test_an_adapter_knows_no_client(fmt):
    """Replace the client: with no client rules and no client closing
    contract, nothing in the adapter's full model input is Never Blank's."""
    captured: dict = {}

    def fake_chat(*, system, user, **kwargs):
        captured["message"] = f"{system}\n{user}"
        body = ("First post.\n---\nSecond post.\n---\nThird post." if fmt == "threads"
                else "An adaptation in complete sentences.")
        return json.dumps({"body": body, "echo_included": False, "title": None})

    neutral_content = "A retailer changed its checkout. Orders rose 12%. The change removed a step."
    with mock.patch.object(platform_composer, "chat", side_effect=fake_chat):
        platform_composer.compose_platforms(
            {"echo_line": None}, formats=(fmt,), canonical_body=neutral_content,
        )

    message = captured["message"].casefold()
    for term in _CLIENT_TERMS:
        assert term not in message, term
    assert neutral_content.casefold() in message


@pytest.mark.parametrize("fmt", ["telegram", "threads"])
def test_client_meaning_reaches_an_adapter_only_through_supplied_rules(fmt):
    captured: dict = {}

    def fake_chat(*, system, user, **kwargs):
        captured["system"], captured["user"] = system, user
        body = ("First post.\n---\nSecond post.\n---\nThird post." if fmt == "threads"
                else "An adaptation in complete sentences.")
        return json.dumps({"body": body, "echo_included": False, "title": None})

    rules = "CLIENT RULE: write for independent bakery owners."
    with mock.patch.object(platform_composer, "chat", side_effect=fake_chat):
        platform_composer.compose_platforms(
            {"echo_line": None}, formats=(fmt,), canonical_body="Content.",
            editorial_role_rules={fmt: rules},
        )

    assert rules in captured["user"]                 # the client's rules arrive…
    assert "bakery" not in captured["system"]        # …never baked into the Engine
    assert "Never Blank" not in captured["system"]


def test_the_shared_composer_prompt_is_unchanged_for_other_formats():
    """Bounded fix: only the new adapter seam moved; #255 owns the rest."""
    from src.editorial.platform_composer import _ADAPTER_SYSTEM_PROMPT, _SYSTEM_PROMPT

    assert _SYSTEM_PROMPT.startswith("You are the Platform Composer for Never Blank.")
    assert "Never Blank" not in _ADAPTER_SYSTEM_PROMPT


def test_a_thread_that_breaks_the_contract_after_the_title_lead_fails_closed(tmp_path):
    """A 6-post thread whose first post cannot take the title would become 7
    posts: the preview stops rather than trimming anything."""
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    article = copy.deepcopy(_draft())
    article["platforms"]["long"]["body"] = FINAL_ARTICLE
    article["platforms"]["reading"]["body"] = FINAL_ARTICLE
    patches["generate_article"] = mock.MagicMock(return_value=article)
    six_posts = "\n---\n".join(["y" * 450] + [f"Post {i}." for i in range(2, 6)]
                               + [f"**Never Blank:** {ECHO}"])

    def derive(structured, format_key, **kwargs):
        body = six_posts if format_key == "threads" else (
            FINAL_ARTICLE if format_key == "reading"
            else f"A {format_key} derivation.\n\n**Never Blank:** {ECHO}")
        return {"body": body, "word_count": len(body.split()),
                "echo_included": True, "title": None}

    patches["recompose_platform"] = mock.MagicMock(side_effect=derive)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1
    assert not list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))


# ===========================================================================
# #259 review (4ed7afd): a branded closing on an adapter names the CLIENT
# ===========================================================================


OTHER_CLIENT = "Acme Studio"


def _adapter_with_branded_closing(fmt, *, attribution, reply_attribution):
    """Compose one adapter under branded_echo_then_sources; return what the
    model saw and the result (or the raised error)."""
    from src.editorial.platform_composer import CLOSING_BRANDED_ECHO_THEN_SOURCES

    captured: dict = {}

    def fake_chat(*, system, user, **kwargs):
        captured["message"] = f"{system}\n{user}"
        closing = f"{reply_attribution}: {ECHO}"
        body = ("First post.\n---\nSecond post.\n---\n" + closing if fmt == "threads"
                else f"An adaptation in complete sentences.\n\n{closing}")
        return json.dumps({"body": body, "echo_included": True, "title": None})

    with mock.patch.object(platform_composer, "chat", side_effect=fake_chat):
        result = platform_composer.compose_platforms(
            {"echo_line": ECHO}, formats=(fmt,), canonical_body="Content. " + ECHO,
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
            closing_attribution=attribution,
        )
    return captured["message"], result


@pytest.mark.parametrize("fmt", ["telegram", "threads"])
def test_a_branded_adapter_closing_carries_the_clients_own_name(fmt):
    """Replace the client on the REAL Monday path: a branded/verbatim closing
    with another client's configured name uses that name, and 'Never Blank'
    appears nowhere the Engine could have put it."""
    message, result = _adapter_with_branded_closing(
        fmt, attribution=OTHER_CLIENT, reply_attribution=OTHER_CLIENT)

    assert f"'{OTHER_CLIENT}: <echo>'" in message
    assert f"as the {OTHER_CLIENT} perspective" in message
    assert "never blank" not in message.casefold()
    assert result[fmt]["body"].rstrip().endswith(f"{OTHER_CLIENT}: {ECHO}")


@pytest.mark.parametrize("fmt", ["telegram", "threads"])
def test_an_adapter_closing_under_another_brand_is_rejected(fmt):
    """The validator follows the client's name too: the Engine's old constant
    is not an acceptable closing for another client."""
    from src.editorial.platform_composer import CompositionRejected

    with pytest.raises(CompositionRejected, match=OTHER_CLIENT):
        _adapter_with_branded_closing(
            fmt, attribution=OTHER_CLIENT, reply_attribution="Never Blank")


@pytest.mark.parametrize("fmt", ["telegram", "threads"])
def test_a_branded_adapter_closing_without_a_client_name_is_refused(fmt):
    with pytest.raises(ValueError, match="client's attribution"):
        _adapter_with_branded_closing(fmt, attribution=None, reply_attribution="X")


def test_never_blank_reaches_its_adapters_only_from_its_own_configuration(tmp_path):
    """The Monday path: the name comes from the client's configuration
    (business.name), is handed to the adapters and only to them."""
    from src.strategy.business_config import load_business_strategy_configuration

    configured = load_business_strategy_configuration().business.name
    code, patches = _preview_with_stub_derivation(tmp_path)

    assert code == 0
    calls = {c.args[1]: c.kwargs for c in patches["recompose_platform"].call_args_list}
    for fmt in ("telegram", "threads"):
        assert calls[fmt]["closing_attribution"] == configured, fmt
    for fmt in ("medium", "reading", "instagram"):
        assert "closing_attribution" not in calls[fmt], fmt


def test_the_shared_formats_keep_their_existing_closing_unchanged():
    """Bounded fix: the shared LinkedIn/Facebook/Instagram/article composer is
    #255's — its branded closing text is byte-for-byte what it was."""
    from src.editorial.platform_composer import (
        CLOSING_BRANDED_ECHO_THEN_SOURCES,
        _build_user_prompt,
    )

    prompt = _build_user_prompt({"echo_line": ECHO}, "medium", "none",
                                closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES)
    assert "ECHO MODE: verbatim, as the Never Blank perspective — the" in prompt
    assert "'Never Blank: <echo>'" in prompt


# ===========================================================================
# #259 review (15e316c): Replace the client, end to end
# ===========================================================================


def test_another_clients_accepted_echo_reaches_telegram_and_threads_under_its_name(
    tmp_path, monkeypatch
):
    """End to end on the real Monday route with the client replaced: the
    configuration names "Acme Studio", the client's rules are Acme's, and
    the accepted article closes "Acme Studio: <echo>". The accepted Echo is
    recognised under that name and reaches Telegram and Threads as
    "Acme Studio: <echo>" — and no Engine code puts "Never Blank" into the
    adapters' model input or output."""
    from src.strategy.business_config import load_business_strategy_configuration

    # the client is replaced whole: Acme's configuration AND Acme's documents.
    # Leaving Never Blank's documents in place would run one client's contract
    # under another's name, and its editorial policy would reach the prompts
    # (#268 gave that contract a plan).
    acme_client = tmp_path / "acme_client"
    (acme_client / "streams").mkdir(parents=True)
    (acme_client / "streams" / "weekly.md").write_text(
        "---\n"
        "stream_id: acme-weekly\n"
        'version: "1"\n'
        f"role_id: {MONDAY_ROLE}\n"
        "selection: first_valid\n"
        "---\n\n"
        "## Purpose\n\n"
        "Help independent bakeries decide what to bake this week.\n\n"
        "## Selection\n\n"
        "### Useful\n\n"
        "- The signal concerns a bakery's own costs or customers.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NB_CLIENT_DIR", str(acme_client))

    real = load_business_strategy_configuration()
    acme = real.model_copy(update={
        "business": real.business.model_copy(update={"name": OTHER_CLIENT})})
    acme_article = FINAL_ARTICLE.replace("**Never Blank:**", f"**{OTHER_CLIENT}:**")
    draft = _draft()
    draft["platforms"]["long"]["body"] = acme_article

    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]
    del patches["recompose_platform"]
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    patches["generate_article"] = mock.MagicMock(return_value=draft)
    patches["load_business_strategy_configuration"] = mock.MagicMock(return_value=acme)
    # the client's own rules — Acme's, carrying no Never Blank text
    patches["render_editorial_role_rules"] = mock.MagicMock(
        return_value="CLIENT RULES: Acme Studio writes for independent bakeries.")
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    composer = FaithfulComposer()
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(platform_composer, "chat", side_effect=composer), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=FakeReviewTransport(_review_payload()),
                    article_revisor=FakeRevisionTransport(acme_article),
                    derivation_judge=RecordingJudge())

    assert code == 0
    generated = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/generated.json")).read_text())
    record = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/accepted_composition.json")).read_text())
    # the accepted Echo was recognised under the client's own name
    assert record["content"]["echo"] == ECHO
    # and reaches both adapters as "<client>: <echo>"
    telegram = generated["telegram_text"]
    threads = generated["threads_sequence"]
    assert telegram.rstrip().endswith(f"{OTHER_CLIENT}: {ECHO}")
    assert threads[-1].strip() == f"{OTHER_CLIENT}: {ECHO}"
    for text in (telegram, *threads):
        assert "never blank" not in text.casefold()
    # nothing the Engine wrote into the adapters' model input names Never Blank
    adapter_prompts = [p for p in composer.prompts
                       if re.search(r"^FORMAT: (telegram|threads)$", p, re.MULTILINE)]
    assert len(adapter_prompts) == 2
    for prompt in adapter_prompts:
        assert "never blank" not in prompt.casefold()
        assert f"'{OTHER_CLIENT}: <echo>'" in prompt


def test_the_accepted_echo_helper_knows_no_brand_of_its_own():
    from scripts.generate_and_publish import _accepted_echo

    acme_article = f"Body.\n\n**{OTHER_CLIENT}:** {ECHO}"
    assert _accepted_echo(acme_article, "", OTHER_CLIENT) == ECHO
    # a name the client did not configure is not an attribution
    assert _accepted_echo(acme_article, "", "Never Blank") == ""
    assert _accepted_echo(f"Body.\n\nNever Blank: {ECHO}", "", OTHER_CLIENT) == ""
    # and with no configured name nothing counts as attributed
    assert _accepted_echo(acme_article, "", "") == ""
    source = Path("scripts/generate_and_publish.py").read_text()
    helper = source[source.index("def _accepted_echo("):source.index("def _lead_with_canonical_title(")]
    assert "Never Blank" not in helper.split('"""', 2)[2]      # no literal in the code
