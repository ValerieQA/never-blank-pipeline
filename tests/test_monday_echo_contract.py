"""Issue #191: the Echo IS the Never Blank perspective, and Sources follow it.

Live run 32611137648 died at the composer because three rules could not all
hold: the Monday role required "Sources section last", the source-transparency
block required the article to *close* with Sources, and the validator required
``body.endswith(echo)``. Only the echo rule was machine-enforced, so the model
was rejected for obeying the role.

The product decision resolves it by merging two editorial moments into one:
the Echo is the Never Blank perspective, rendered as an attributed block, with
Sources after it and no invitation at all. These scenarios prove the new
Monday contract, that no other role moved, and that a refused composition is
now preserved for diagnosis instead of dying with the runner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.artifacts import REJECTED_COMPOSITION_KIND, append_rejected_composition
from src.editorial import platform_composer
from src.editorial.editorial_role import render_editorial_role_rules, resolve_editorial_role
from src.editorial.pipeline import ArticleGenerationError, generate_article
from src.editorial.platform_composer import (
    CLOSING_BRANDED_ECHO_THEN_SOURCES,
    CLOSING_INVITATION_LAST,
    CompositionRejected,
    _compose_one,
)
from src.strategy.business_config import load_business_strategy_configuration
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider


CONFIG = Path("strategy/current/business_strategy.json")
MONDAY = "never-blank-monday-documented-case"
WEDNESDAY = "never-blank-wednesday-golden"
ECHO = "The ceiling is built from the same speed that opened the door."


def _role(role_id: str):
    return resolve_editorial_role(load_business_strategy_configuration(CONFIG), role_id)[1]


def _article(echo: str = ECHO) -> dict:
    return {"hook": "h", "discovery": {}, "echo_line": echo,
            "narrative_spine": "s", "cta_line": None}


def _research_with_one_source():
    from tests.test_decision_lens_evaluator import _research
    return _research()


def _identities() -> tuple:
    """The run's own citable identities, exactly as the pipeline derives them."""
    from src.editorial.sources_of_record import source_records

    return tuple(
        value
        for record in source_records(_research_with_one_source())
        for key in ("url", "publisher", "title")
        for value in (record.get(key),)
        if value
    )


#: One real rendered Sources entry, taken from the canonical renderer rather
#: than hand-invented, so the test validates what the run actually shows.
def _real_source_entry() -> str:
    from src.editorial.sources_of_record import render_sources_of_record

    rendered = render_sources_of_record(_research_with_one_source(), surface="wix")
    return next(l for l in rendered.splitlines() if l.startswith("- "))


def _compose(body: str, *, contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
             fmt="long", echo: str = ECHO, identities=None):
    """Drive the real validator against a body we control."""
    payload = json.dumps({"body": body, "echo_included": True, "title": "T"})
    with mock.patch.object(platform_composer, "chat", return_value=payload):
        return _compose_one(
            _article(echo), fmt, closing_contract=contract,
            source_identities=_identities() if identities is None else identities,
        )


def _body(*, echo_block: str = None, sources: str = None) -> str:
    """A full-length article with a controllable ending."""
    echo_block = echo_block if echo_block is not None else f"**Never Blank:** {ECHO}"
    tail = f"\n\n{sources}" if sources else ""
    return (
        "Opening paragraph that carries the tension.\n\n"
        + " ".join(f"word{i}" for i in range(430))
        + "\n\nWhat this means for another owner.\n\n"
        + echo_block + tail
    )


_REAL_SOURCES = "## Sources\n" + _real_source_entry()
_GOOD_WIX = _body(sources=_REAL_SOURCES)


# ===========================================================================
# 1–2, 4. Monday: one branded moment, no CTA, one Echo
# ===========================================================================


def test_monday_no_longer_requires_a_separate_perspective_plus_echo():
    rules = " ".join(_role(MONDAY).structure).lower()

    assert "never blank echo" in rules
    assert "is the never blank perspective on this story" in rules
    # the second branded moment is gone
    assert "never blank close" not in rules
    assert "a short never blank perspective" not in rules


def test_monday_no_longer_requires_a_cta_or_invitation():
    role = _role(MONDAY)
    joined = " ".join(role.structure + role.wix_rules + role.linkedin_rules).lower()

    assert role.cta_mode == "none"
    # the role no longer *requires* an invitation; it explicitly forbids one
    assert "website invitation: close with" not in joined
    assert "no website invitation" in joined
    assert "inneros.online" not in joined


def test_the_monday_wix_ending_renders_one_branded_echo_then_sources():
    result = _compose(_GOOD_WIX)

    body = result["body"]
    assert body.count(ECHO) == 1
    assert f"**Never Blank:** {ECHO}" in body
    # Sources follow the branded Echo — the shape the old validator forbade
    assert body.index("## Sources") > body.index(ECHO)


def test_the_branded_echo_is_the_last_editorial_word_before_sources():
    lines = [l.strip() for l in _GOOD_WIX.splitlines() if l.strip()]
    echo_line = next(i for i, l in enumerate(lines) if ECHO in l)
    assert lines[echo_line].startswith("**Never Blank:**")
    assert lines[echo_line + 1].lower().lstrip("# ").startswith("sources")


# ===========================================================================
# 5–7. Sources after the Echo is now the accepted ordering
# ===========================================================================


def test_the_monday_role_states_the_new_order_on_both_surfaces():
    role = _role(MONDAY)
    wix = render_editorial_role_rules(role, surface="wix").lower()
    linkedin = render_editorial_role_rules(role, surface="linkedin").lower()

    assert "never blank echo" in wix and "then the sources section last" in wix
    assert "never blank echo" in linkedin and "then hashtags last" in linkedin
    for surface in (wix, linkedin):
        assert "inneros.online" not in surface


def test_source_transparency_remains_mandatory():
    assert _role(MONDAY).require_source_transparency is True


def test_the_new_ordering_validates_and_the_old_one_now_fails():
    _compose(_GOOD_WIX)                       # accepted

    echo_last = (
        "Body paragraph.\n\n" + " ".join(f"w{i}" for i in range(430))
        + "\n\n## Sources\n- Verified report\n\n"
        f"**Never Blank:** {ECHO}"
    )
    # Sources before the branded Echo is no longer the Monday shape: the Echo
    # must be the last editorial word, with only Sources after it
    with pytest.raises(CompositionRejected, match="must follow the Echo"):
        _compose(echo_last)


# ===========================================================================
# 8–9. Duplicate / missing Echo and missing attribution still fail
# ===========================================================================


def test_a_duplicated_echo_still_fails():
    body = _GOOD_WIX.replace("## Sources", f"{ECHO}\n\n## Sources")
    with pytest.raises(CompositionRejected, match="exactly once"):
        _compose(body)


def test_an_echo_outside_the_attribution_block_still_fails():
    body = _GOOD_WIX.replace(f"**Never Blank:** {ECHO}", ECHO)
    with pytest.raises(CompositionRejected, match="attribution block"):
        _compose(body)


def test_content_after_the_echo_that_is_not_sources_fails():
    body = _GOOD_WIX.replace(
        "## Sources", "Come and visit us for more insight.\n\n## Sources")
    with pytest.raises(CompositionRejected, match="only a Sources section may follow"):
        _compose(body)


def test_a_missing_echo_is_still_refused_by_the_engine():
    body = _GOOD_WIX.replace(f"**Never Blank:** {ECHO}\n\n", "")
    with pytest.raises(CompositionRejected):
        _compose(body)


# ===========================================================================
# 3. No other role moved
# ===========================================================================


def test_other_roles_keep_the_previous_closing_contract():
    wednesday = _role(WEDNESDAY)

    assert wednesday.closing_contract == CLOSING_INVITATION_LAST
    assert wednesday.cta_mode is None          # strategy CTA still governs
    assert _role(MONDAY).closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES


def test_the_default_contract_still_requires_the_echo_to_end_the_body():
    ends_with_echo = ("Body.\n\n" + " ".join(f"w{i}" for i in range(430))
                      + f"\n\n{ECHO}")
    _compose(ends_with_echo, contract=CLOSING_INVITATION_LAST)   # accepted

    with pytest.raises(CompositionRejected, match="exactly once at end"):
        _compose(_GOOD_WIX, contract=CLOSING_INVITATION_LAST)


def test_the_shared_channel_cta_rules_are_untouched():
    channels = json.loads(CONFIG.read_text())["channels"]
    wix_rules = " ".join(channels["wix"]["cta_rules"])

    # the destination and the invitation contract still exist for any role
    # whose CTA mode is not "none" — Monday simply switches itself off
    assert "inneros.online" in wix_rules
    assert "when cta mode is none" in wix_rules.lower()


def test_the_engine_never_learns_what_this_role_means():
    for module in ("src/editorial/platform_composer.py",
                   "src/editorial/pipeline.py",
                   "src/strategy/business_config.py"):
        text = Path(module).read_text().lower()
        assert "monday" not in text
        assert "inneros.online" not in text


# ===========================================================================
# 10–11. Social attribution follows the researched platform capability
# ===========================================================================


def test_linkedin_attribution_is_plain_with_no_url_workaround():
    role = _role(MONDAY)
    linkedin = render_editorial_role_rules(role, surface="linkedin")

    # plain attribution, exactly as researched: the Zernio `content` field is
    # plain text, so arbitrary anchor text is impossible
    assert "'Never Blank: <echo>'" in linkedin
    # and no raw URL is introduced merely to create a link
    assert "inneros.online" not in linkedin
    assert "http" not in linkedin.split("End in this order")[1]


def test_the_publisher_bolding_helper_still_finds_the_attribution_line():
    from src.publishing.formatting import bold_signature_prefix

    body = f"Some post body.\n\nNever Blank: {ECHO}"
    bolded = bold_signature_prefix(body, "unicode")

    assert ECHO in bolded                      # the thought itself is plain
    assert "Never Blank:" not in bolded        # the brand name was substituted


# ===========================================================================
# 12–15. Rejected-composition evidence
# ===========================================================================


def test_both_rejected_attempts_are_preserved(tmp_path):
    append_rejected_composition(tmp_path, {
        "stage": "platform_composer", "format": "long", "attempt": 1,
        "validation_error": "first failure", "body": "FIRST BODY"})
    append_rejected_composition(tmp_path, {
        "stage": "platform_composer", "format": "long", "attempt": 2,
        "validation_error": "second failure", "body": "SECOND BODY"})

    record = json.loads((tmp_path / "rejected_composition.json").read_text())
    assert record["artifact_kind"] == REJECTED_COMPOSITION_KIND
    assert record["publishable"] is False
    assert [a["attempt"] for a in record["attempts"]] == [1, 2]
    assert record["attempts"][0]["body"] == "FIRST BODY"
    assert record["attempts"][1]["body"] == "SECOND BODY"


def test_a_failing_composition_preserves_what_the_model_wrote(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    rejected_body = "A body that never carries the required attribution block."

    def failing_generate(*args, **kwargs):
        sink = kwargs.get("rejected_sink")
        for attempt in (1, 2):
            sink.append({"stage": "platform_composer", "format": "long",
                         "attempt": attempt,
                         "validation_error": "Echo must be the Never Blank attribution block",
                         "body": f"{rejected_body} (attempt {attempt})"})
        raise ArticleGenerationError("platform_composer", ValueError("rejected"))

    patches["generate_article"].side_effect = failing_generate
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1
    record = json.loads(
        next(tmp_path.glob("*/runs/*/rejected_composition.json")).read_text())
    assert len(record["attempts"]) == 2
    assert rejected_body in record["attempts"][0]["body"]
    assert record["publishable"] is False
    # and the run produced no publishable artifact
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_rejected_output_can_never_enter_publishing_or_from_package(tmp_path):
    from src.artifacts import load_run_generated
    from src.reporting.run_report import CANONICAL_ARTIFACTS

    append_rejected_composition(tmp_path, {
        "stage": "platform_composer", "format": "long", "attempt": 1,
        "validation_error": "e", "body": "REJECTED"})

    # not canonical evidence, and --from-package reads generated.json only
    assert "rejected_composition.json" not in CANONICAL_ARTIFACTS
    with pytest.raises(FileNotFoundError):
        load_run_generated(tmp_path.parent, tmp_path.name, tmp_path.name)


def test_a_successful_run_writes_no_rejected_evidence(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert not list(tmp_path.glob("*/runs/*/rejected_composition.json"))


def test_the_record_carries_no_provider_or_secret_material(tmp_path):
    append_rejected_composition(tmp_path, {
        "stage": "platform_composer", "format": "long", "attempt": 1,
        "validation_error": "Echo must appear exactly once", "body": "Generated text."})

    flat = json.dumps(json.loads((tmp_path / "rejected_composition.json").read_text()))
    for forbidden in ("Authorization", "Bearer", "api_key", "sk-", "headers",
                      "x-request-id", "response"):
        assert forbidden not in flat


# ===========================================================================
# 16. Containment/budget/provider contracts unaffected
# ===========================================================================


def test_cost_and_containment_contracts_are_unaffected():
    import os
    from src.editorial.source_eligibility import SourceEligibilityError
    from src.run.call_budget import DEFAULT_CEILING
    from src.utils.llm_client import max_retries

    assert SourceEligibilityError("x").scope == "candidate"     # #170
    assert max_retries() == 1                                   # #170
    assert DEFAULT_CEILING == 40                                # #171
    assert os.environ.get("NB_OPENAI_API_KEY") is None          # #172
    # #191's rejection type stays a ValueError so the single-retry seam and
    # the budget accounting behave exactly as before
    assert issubclass(CompositionRejected, ValueError)


# ===========================================================================
# Review round 2: the WHOLE post-Echo tail is proven, not just its first line
# ===========================================================================


def test_a_cta_appended_below_the_source_list_is_rejected():
    """The exact shape the previous validator could not see.

    Its first trailing line was a Sources heading and its second carried a
    list marker, so a call to action underneath a genuine citation passed
    both earlier rules.
    """
    body = _body(sources=(
        "## Sources\n"
        "- SBA Office of Advocacy — https://advocacy.sba.gov/report\n"
        "- Visit Never Blank today!"
    ))
    with pytest.raises(CompositionRejected, match="must name one of this run's sources"):
        _compose(body)


def test_a_second_perspective_appended_below_the_source_list_is_rejected():
    body = _body(sources=(
        "## Sources\n"
        "- SBA Office of Advocacy — https://advocacy.sba.gov/report\n"
        "- Never Blank believes every founder should publish consistently."
    ))
    with pytest.raises(CompositionRejected, match="must name one of this run's sources"):
        _compose(body)


def test_numbered_prose_disguised_as_a_source_is_rejected():
    body = _body(sources=(
        "## Sources\n"
        "1. https://advocacy.sba.gov/report\n"
        "2. Sign up for Never Blank today."
    ))
    with pytest.raises(CompositionRejected, match="must name one of this run's sources"):
        _compose(body)


def test_the_intended_shape_still_passes():
    result = _compose(_body(sources=_REAL_SOURCES))
    assert result["body"].rstrip().endswith(_real_source_entry())


@pytest.mark.parametrize(
    "entry",
    ["- SBA Office of Advocacy — https://advocacy.sba.gov/report",
     "* Small-business operating constraints",
     "1. https://advocacy.sba.gov/report",
     "2) SBA Office of Advocacy",
     "https://advocacy.sba.gov/report"],
    ids=["dash-url", "asterisk-title", "numbered-url", "numbered-publisher",
         "bare-url"],
)
def test_legitimate_source_formats_are_accepted(entry):
    """Any layout is fine — what matters is that it names a real source.

    Includes a title-only and a publisher-only entry, because
    ``source_records`` treats a source as citable when it has a URL OR a
    publisher OR a title: a URL-only rule would reject legitimate sources.
    """
    _compose(_body(sources=f"## Sources\n{entry}"))


def test_the_real_rendered_sources_block_passes():
    """The canonical renderer's own output, not a hand-invented lookalike."""
    result = _compose(_body(sources=_REAL_SOURCES))

    assert _real_source_entry() in result["body"]
    assert "publisher: SBA Office of Advocacy" in result["body"]


# ---------------------------------------------------------------------------
# The empty-tail case: structurally valid here, authoritatively judged there
# ---------------------------------------------------------------------------


def test_an_echo_with_nothing_after_it_is_structurally_valid():
    body = ("Body paragraph.\n\n" + " ".join(f"w{i}" for i in range(430))
            + f"\n\n**Never Blank:** {ECHO}")
    _compose(body)          # the composer does not own attribution


def test_missing_attribution_is_rejected_by_the_authoritative_gate():
    """Where a body with no Sources is actually stopped (#142/#155).

    The role permits "a visible Sources section and/or appropriate inline
    source links", so the composer must not demand a heading. The run-level
    gate sees the real sources and fails closed before any publisher.
    """
    from src.editorial.source_transparency import (
        SourceTransparencyError, validate_source_transparency,
    )

    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body=f"An article that cites nothing.\n\n**Never Blank:** {ECHO}",
            linkedin_body="Nor does this.",
            research=_research_with_one_source(),
        )
    # and the role that publishes this contract demands that gate
    assert _role(MONDAY).require_source_transparency is True
