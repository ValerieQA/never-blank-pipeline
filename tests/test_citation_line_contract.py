"""The citation the composer is handed is the exact line it must write.

Controlled live run 35375812835 stopped at ``platform_composer``: the run's
only source record had ``publisher: null``, the prompt listed its title and URL
under field labels and offered a "Publisher · Title · URL" example, and the
model — twice — wrote ``HubSpot · <title> · <url>``. The validator rejected it
correctly: "HubSpot" is not in the source record.

The repair is on the prompt side only. The validator is not loosened: a
citation is still grounded solely in the canonical source record's fields. What
changed is that the model is handed the finished citation line, derived from
that record — ``publisher · title · URL`` when a publisher exists, ``title ·
URL`` when it does not — and told to copy it, never to add a publisher.

No network, no model.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from src.editorial import platform_composer
from src.editorial.platform_composer import (
    CLOSING_BRANDED_ECHO_THEN_SOURCES,
    CompositionRejected,
    _compose_one,
)
from src.editorial.sources_of_record import (
    canonical_source_entries,
    render_sources_of_record,
    source_citation_values,
)
from tests.test_monday_echo_contract import ECHO, _article, _body, _research_with

#: The live run's source record, exactly as persisted in its research.json.
LIVE_TITLE = ("Running TikTok campaigns with impact — missed opportunities "
              "that make all the difference")
LIVE_URL = "https://blog.hubspot.com/marketing/running-tiktok-campaigns-with-impact"
LIVE_LOCATOR = {"kind": "url", "value": LIVE_URL}

#: What the model wrote in both attempts of run 35375812835.
LIVE_MODEL_LINE = f"HubSpot · {LIVE_TITLE} · {LIVE_URL}"


def _with_publisher():
    return _research_with(publisher="HubSpot Marketing Blog", title=LIVE_TITLE,
                          locator=LIVE_LOCATOR)


def _without_publisher():
    return _research_with(publisher=None, title=LIVE_TITLE, locator=LIVE_LOCATOR)


def _compose(body: str, research, *, rules: str | None = None):
    """The real composer and its real validator, against a body we control."""
    seen: dict = {}

    def fake_chat(*, system, user, **kwargs):
        seen["message"] = f"{system}\n{user}"
        return json.dumps({"body": body, "echo_included": True, "title": "T"})

    with mock.patch.object(platform_composer, "chat", side_effect=fake_chat):
        result = _compose_one(
            _article(ECHO), "long",
            closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
            source_identities=source_citation_values(research),
            editorial_role_rules=rules,
        )
    return result, seen["message"]


def _handed_line(research) -> str:
    rendered = render_sources_of_record(research, surface="wix")
    lines = [line[2:] for line in rendered.splitlines() if line.startswith("- ")]
    assert len(lines) == 1
    return lines[0]


# ===========================================================================
# 1. Publisher present: publisher · title · URL
# ===========================================================================


def test_a_record_with_a_publisher_is_handed_publisher_title_url():
    research = _with_publisher()
    expected = f"HubSpot Marketing Blog · {LIVE_TITLE} · {LIVE_URL}"

    assert canonical_source_entries(research) == (expected,)
    assert _handed_line(research) == expected


def test_the_handed_line_with_a_publisher_passes_the_validator():
    research = _with_publisher()

    result, _ = _compose(_body(sources=f"Sources\n{_handed_line(research)}"), research)

    assert _handed_line(research) in result["body"]


# ===========================================================================
# 2. Publisher null: title · URL, and nothing manufactured
# ===========================================================================


@pytest.mark.parametrize("publisher", [None, "", "   "], ids=["null", "empty", "blank"])
def test_a_record_without_a_publisher_is_handed_title_url_only(publisher):
    research = _research_with(publisher=publisher, title=LIVE_TITLE, locator=LIVE_LOCATOR)
    expected = f"{LIVE_TITLE} · {LIVE_URL}"

    assert canonical_source_entries(research) == (expected,)
    assert _handed_line(research) == expected
    # nothing inferred — not from the domain, not from brand familiarity
    rendered = render_sources_of_record(research, surface="wix")
    assert "HubSpot ·" not in rendered and "hubspot.com ·" not in rendered.casefold()


def test_the_prompt_forbids_adding_a_publisher_and_offers_no_template():
    rendered = render_sources_of_record(_without_publisher(), surface="wix")

    assert "copy each line character for character" in rendered
    assert "never add a publisher, brand or site name" in rendered
    assert "A line without a publisher is complete as it is." in rendered
    assert "Publisher · Title · URL" not in rendered
    assert "publisher: " not in rendered


def test_the_exact_line_reaches_the_composer_model_message():
    """Through the real composer: the model sees the line it must copy, and
    the closing instruction points at it rather than at labelled fields."""
    research = _without_publisher()
    rules = render_sources_of_record(research, surface="wix")

    _, message = _compose(_body(sources=f"Sources\n{_handed_line(research)}"),
                          research, rules=rules)

    assert f"- {LIVE_TITLE} · {LIVE_URL}" in message
    assert "one of the supplied SOURCES OF RECORD lines, copied exactly" in message
    assert "labels above are only there" not in message


# ===========================================================================
# 3. A model-added publisher is still rejected — the live failure
# ===========================================================================


def test_the_live_model_line_is_still_rejected_when_the_record_has_no_publisher():
    with pytest.raises(CompositionRejected, match="must cite one of this run's sources"):
        _compose(_body(sources=f"Sources\n{LIVE_MODEL_LINE}"), _without_publisher())


@pytest.mark.parametrize("invented", [
    "HubSpot", "HubSpot Marketing Blog", "blog.hubspot.com",
], ids=["brand", "brand-long", "domain"])
def test_any_invented_publisher_is_rejected(invented):
    line = f"{invented} · {LIVE_TITLE} · {LIVE_URL}"

    with pytest.raises(CompositionRejected, match="must cite one of this run's sources"):
        _compose(_body(sources=f"Sources\n{line}"), _without_publisher())


# ===========================================================================
# 4. A valid publisher-less citation passes
# ===========================================================================


@pytest.mark.parametrize("marker", ["", "- "], ids=["bare", "list-marker"])
def test_the_publisher_less_handed_line_passes(marker):
    research = _without_publisher()
    line = _handed_line(research)

    result, _ = _compose(_body(sources=f"Sources\n{marker}{line}"), research)

    assert line in result["body"]


# ===========================================================================
# 5. Source integrity is otherwise unchanged
# ===========================================================================


def test_the_citable_values_the_validator_checks_are_unchanged():
    assert source_citation_values(_with_publisher()) == (
        ("HubSpot Marketing Blog", LIVE_TITLE, LIVE_URL),
    )
    assert source_citation_values(_without_publisher()) == ((LIVE_TITLE, LIVE_URL),)


@pytest.mark.parametrize("line", [
    f"{LIVE_TITLE}",                                   # URL missing
    f"{LIVE_URL}",                                     # title missing
    f"HubSpot Marketing Blog · {LIVE_URL}",           # publisher record: title missing
    f"{LIVE_TITLE} · {LIVE_URL} · read it now",        # extra prose
], ids=["no-url", "no-title", "no-title-with-publisher", "extra-words"])
def test_an_incomplete_or_embellished_citation_is_still_rejected(line):
    research = _with_publisher() if "Marketing Blog" in line else _without_publisher()

    with pytest.raises(CompositionRejected, match="must cite one of this run's sources"):
        _compose(_body(sources=f"Sources\n{line}"), research)


def test_the_optional_field_labels_are_still_accepted():
    """The validator was not tightened either: labels stay optional."""
    research = _with_publisher()
    line = f"publisher: HubSpot Marketing Blog · title: {LIVE_TITLE} · url: {LIVE_URL}"

    _compose(_body(sources=f"Sources\n{line}"), research)


def test_the_social_surface_rendering_is_unchanged():
    rendered = render_sources_of_record(_with_publisher(), surface="linkedin")

    assert f"- HubSpot Marketing Blog · {LIVE_TITLE}" in rendered
    assert LIVE_URL not in rendered
