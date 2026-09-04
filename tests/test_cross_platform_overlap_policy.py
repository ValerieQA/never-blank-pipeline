"""Issue #221: Wix↔LinkedIn sentence overlap is allowed.

CONTROLLED_LIVE run 33913287027 produced an article that passed editorial
acceptance and source transparency, then was blocked by:

    LinkedIn opening copies the Wix article opening — not channel-native

The product owner has withdrawn that requirement globally. LinkedIn is a
shorter channel version of the same article: a strong hook may open both
surfaces, sentences may recur, and the Never Blank Echo is expected to. A
reader arriving from LinkedIn is helped, not confused, by recognising the
opening they clicked, and weakening a hook to manufacture cross-channel
novelty made the product worse.

The meaningful failure this guard exists for — publishing the whole Wix
article as the LinkedIn body — stays fail-closed. These scenarios pin both
halves, and pin that the withdrawn rule is not re-enforced anywhere else in
the Never Blank publication path.

No paid calls and no network calls.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.content.generator import _validate_cross_platform_outputs
from src.content.output_guard import repeated_cross_platform_phrases

#: The exact sentence that blocked run 33913287027.
LIVE_HOOK = ("Investors cheered not because ChargePoint promised more growth, "
             "but because it finally slowed down.")
ECHO = ("Never Blank: Sometimes, the most compelling growth story is about "
        "knowing when to hit the brakes.")


def _outputs(**overrides):
    base = {
        "blog": "The article develops the full argument about operational proof. "
                "It runs on at length through the mechanism and its consequences.",
        "linkedin": "A shorter take on the very same idea for the feed. "
                    "It lands the point in far fewer words than the article does.",
        "instagram": "A distinct caption written for the grid and nothing else here.",
        "facebook": "A distinct reading-surface body written only for that channel.",
        "threads": ["A distinct threads post written only for that channel here."],
        "telegram": "A distinct telegram body written only for that channel here.",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Allowed: Wix and LinkedIn may share sentences
# ===========================================================================


def test_a_shared_hook_between_blog_and_linkedin_is_allowed():
    outputs = _outputs()
    outputs["blog"] = LIVE_HOOK + " " + outputs["blog"]
    outputs["linkedin"] = LIVE_HOOK + " " + outputs["linkedin"]

    _validate_cross_platform_outputs(**outputs)      # must not raise


def test_a_shared_echo_between_blog_and_linkedin_is_allowed():
    outputs = _outputs()
    outputs["blog"] = outputs["blog"] + " " + ECHO
    outputs["linkedin"] = outputs["linkedin"] + " " + ECHO

    _validate_cross_platform_outputs(**outputs)


def test_several_shared_sentences_between_blog_and_linkedin_are_allowed():
    shared = ("Investors rewarded the discipline rather than the ambition on "
              "display in that quarter's numbers.")
    outputs = _outputs()
    outputs["blog"] = f"{LIVE_HOOK} {outputs['blog']} {shared} {ECHO}"
    outputs["linkedin"] = f"{LIVE_HOOK} {outputs['linkedin']} {shared} {ECHO}"

    _validate_cross_platform_outputs(**outputs)


# ===========================================================================
# Still refused: every other channel pair, and whole-surface copying
# ===========================================================================


def test_a_sentence_shared_with_instagram_is_still_refused():
    """The decision covers Wix↔LinkedIn, not every pair."""
    shared = ("A business whose presence depends entirely on the owner will be "
              "least visible when it most needs attention.")
    outputs = _outputs()
    outputs["blog"] = outputs["blog"] + " " + shared
    outputs["instagram"] = outputs["instagram"] + " " + shared

    with pytest.raises(ValueError, match="Cross-platform copy detected"):
        _validate_cross_platform_outputs(**outputs)


def test_a_sentence_shared_between_linkedin_and_telegram_is_still_refused():
    shared = ("The mechanism was capacity all along, and the numbers only "
              "made that visible after the fact.")
    outputs = _outputs()
    outputs["linkedin"] = outputs["linkedin"] + " " + shared
    outputs["telegram"] = outputs["telegram"] + " " + shared

    with pytest.raises(ValueError, match="Cross-platform copy detected"):
        _validate_cross_platform_outputs(**outputs)


def test_a_sentence_shared_across_three_channels_is_still_refused():
    shared = ("Every channel repeating one sentence means the platform layer "
              "collapsed back into copy-and-paste.")
    outputs = _outputs()
    for channel in ("blog", "linkedin", "instagram"):
        outputs[channel] = outputs[channel] + " " + shared

    with pytest.raises(ValueError, match="Cross-platform copy detected"):
        _validate_cross_platform_outputs(**outputs)


# ===========================================================================
# The withdrawn rule is not enforced anywhere in the publication path
# ===========================================================================


def test_linkedin_acceptance_no_longer_reaches_the_phrase_check():
    source = Path("src/editorial/linkedin_composition.py").read_text()
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert "repeated_cross_platform_phrases" not in names
    assert "_first_sentence" not in names


def test_no_module_claims_the_withdrawn_rule_as_a_requirement():
    """Item 6: no comment may still say LinkedIn must not share the opening."""
    claims = (
        "distinct opening",
        "no shared sentence-length phrase",
        "copies the Wix article opening",
        "copies sentence-length prose",
    )
    for path in list(Path("src").rglob("*.py")) + [
        Path("scripts/generate_and_publish.py")
    ]:
        text = path.read_text()
        for claim in claims:
            assert claim not in text, f"{path}: still claims {claim!r}"


def test_the_shared_utility_itself_is_untouched():
    """It is a generic detector; other pairs still legitimately use it."""
    findings = repeated_cross_platform_phrases({
        "instagram": "One shared sentence appears in both of these two bodies here.",
        "telegram": "One shared sentence appears in both of these two bodies here.",
    })
    assert findings and findings[0]["platforms"] == ["instagram", "telegram"]


def test_the_three_channel_publish_guard_is_untouched():
    """`publish_packages` refuses ≥3 channels sharing a sentence, as before."""
    source = Path("scripts/research/publish_packages.py").read_text()
    assert "repeated_cross_platform_phrases" in source
    assert 'len(d.get("platforms", [])) >= 3' in source
