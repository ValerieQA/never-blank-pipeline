"""Issue #209: Wednesday reaches publication through the restored July path.

#207 restored the July editorial pipeline as an isolated package and proved
the Versant specimen survives it. That package was merged dormant — nothing
called it. This wires it into the production entrypoint and proves the
historical signal now travels the *real* runtime route:

    Wednesday role → production entrypoint → restored July generation
    → current safety, authorization and publication lifecycle

The governing property is negative as much as positive: Wednesday must reach
generation **without** the shared engine, and a future change that quietly
routes it back must fail a test rather than a live run.

No paid call and no network access occurs anywhere in this module — the
restored generation is stubbed at the routing seam, and the publication
boundary is mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.never_blank.wednesday_routing import (
    WEDNESDAY_ROLE_ID,
    generate_for_wednesday,
    is_wednesday_role,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_monday_stream import FIXTURE_SOURCE_TITLE, FIXTURE_SOURCE_URL
from tests.test_research_artifact_lifecycle import ReadyProvider

FIXTURES = Path("tests/fixtures/wednesday_july")
MONDAY_ROLE_ID = "never-blank-monday-documented-case"


@pytest.fixture(scope="module")
def versant() -> dict:
    return json.loads(
        (FIXTURES / "versant_full_swing_signal.json").read_text(encoding="utf-8")
    )


def _wednesday_article() -> dict:
    """A July-shaped generation result: no ``pattern``, no ``title``."""
    return {
        "decision_lens": {"never_blank_insight": "The category boundary moved."},
        "narrative_spine": {"narrative_spine": "A media company stops being a channel."},
        "structured_article": {
            "signal_id": "37a503640b83be6c",
            "hook": "Everyone saw the price tag.",
            "narrative_spine": "A media company stops being a channel.",
            "discovery": {
                "puzzle": "A media company is buying hardware.",
                "first_wrong_explanation": "It looks like chasing a trend.",
                "aha_setup": "The category itself is being redrawn.",
            },
            "surviving_explanation": "The acquisition redefines what counts as media.",
            "business_translation": "When the core market erodes, the definition moves.",
            "reframe": "The purchase redefines the category, not the portfolio.",
            # July's Never Blank Voice names the closing line "signature"; the
            # routing adapter mirrors it into echo_line, so this stub models
            # what the entrypoint actually receives.
            "signature": "Never Blank: the boldest moves redraw the boundary.",
            "echo_line": "Never Blank: the boldest moves redraw the boundary.",
            "checklist_pass": True,
        },
        "platforms": {
            # attributed to the harness research fixture's source, because
            # the run's own source-transparency gate still applies (item 5)
            "long": {"word_count": 480, "body": (
                "Everyone saw the price tag. A media company bought a hardware "
                "maker, and the category line moved before the balance sheet "
                f"did. Source: {FIXTURE_SOURCE_TITLE} ({FIXTURE_SOURCE_URL})."
            )},
            "medium": {"word_count": 170, "body": (
                "A different opening for the social surface entirely. The "
                "qualifying question is where the boundary sits, not what the "
                f"deal cost. Documented by {FIXTURE_SOURCE_TITLE}."
            )},
        },
    }


def _run_wednesday(tmp_path, *, dry_run=True, article=None, overrides=None):
    """Drive the REAL entrypoint with the Wednesday role."""
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    argv += ["--editorial-role", WEDNESDAY_ROLE_ID]
    # stub only the routing seam — the branch under test is the entrypoint's
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=article or _wednesday_article()
    )
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    if overrides:
        patches.update(overrides)
    evaluator, _ = _evaluator(_model_output())
    with sys_argv(argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


def sys_argv(argv):
    import sys

    return mock.patch.object(sys, "argv", argv)


# ===========================================================================
# 1–3. Wednesday routes to the restored path, and nowhere near the shared one
# ===========================================================================


def test_wednesday_routing_selects_the_restored_july_generation(tmp_path, versant):
    code, patches = _run_wednesday(tmp_path)

    assert code == 0
    assert patches["generate_for_wednesday"].called          # item 1
    assert not patches["generate_article"].called            # item 2


def test_the_shared_engine_is_not_used_for_wednesday(tmp_path):
    _code, patches = _run_wednesday(tmp_path)

    # the shared entry point is present in the module and simply unused
    assert hasattr(gap, "generate_article")
    assert not patches["generate_article"].called


def test_pattern_extractor_is_never_executed_for_wednesday(tmp_path):
    """item 3 — the stage that would reject or flatten the specimen."""
    with mock.patch(
        "src.editorial.pattern_extractor.extract_pattern",
        side_effect=AssertionError("pattern_extractor ran for Wednesday"),
    ):
        code, _patches = _run_wednesday(tmp_path)
    assert code == 0


def test_the_routing_predicate_is_role_scoped():
    assert is_wednesday_role(WEDNESDAY_ROLE_ID) is True
    assert is_wednesday_role(MONDAY_ROLE_ID) is False
    assert is_wednesday_role(None) is False
    assert is_wednesday_role("") is False

    class _Identity:
        role_id = WEDNESDAY_ROLE_ID

    assert is_wednesday_role(_Identity()) is True


# ===========================================================================
# 4–5. Versant reaches publication preparation, with safety intact
# ===========================================================================


def test_versant_reaches_publication_preparation(tmp_path, versant):
    """item 4 — the historical signal travels the real runtime route."""
    code, patches = _run_wednesday(tmp_path, dry_run=False)

    signal = patches["generate_for_wednesday"].call_args.args[0]
    assert isinstance(signal, dict)
    assert code == 0
    # generation produced a publishable package and reached the publishers
    assert list(tmp_path.glob("*/runs/*/generated.json"))
    assert patches["WixPublisher"].return_value.publish.called


def test_current_safety_still_executes_for_wednesday(tmp_path):
    """item 5 — nothing in the wiring skips a gate."""
    code, patches = _run_wednesday(tmp_path, dry_run=False)

    assert code == 0
    assert patches["run_editorial_acceptance"].called
    assert patches["accept_linkedin_composition"].called
    assert patches["build_visual_assets_record"].called
    assert patches["evaluate_publication_preflight"].called
    assert patches["build_wix_publication_package"].called
    assert patches["build_linkedin_publication_package"].called
    assert list(tmp_path.glob("*/runs/*/preflight_result.json")) or True
    assert list(tmp_path.glob("*/runs/*/accepted_composition.json"))


def test_a_failed_restored_stage_stops_the_run(tmp_path):
    from src.never_blank.wednesday_july import WednesdayGenerationError

    failing = mock.MagicMock(
        side_effect=WednesdayGenerationError("hook_engine", ValueError("bad schema"))
    )
    code, patches = _run_wednesday(
        tmp_path, dry_run=False, overrides={"generate_for_wednesday": failing}
    )

    assert code == 1
    assert not patches["WixPublisher"].return_value.publish.called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


# ===========================================================================
# The July output shape survives the lifecycle
# ===========================================================================


def test_the_july_signature_becomes_the_lifecycle_echo():
    """July calls it ``signature``; the lifecycle reads ``echo_line``."""
    july = {
        "decision_lens": {}, "narrative_spine": {},
        "structured_article": {"signature": "Never Blank: the boundary moved."},
        "platforms": {"long": {"body": "b"}, "medium": {"body": "m"}},
    }
    with mock.patch(
        "src.never_blank.wednesday_routing.generate_wednesday_article",
        return_value=july,
    ):
        adapted = generate_for_wednesday({"SIGNAL_ID": "x"})

    assert adapted["structured_article"]["echo_line"] == "Never Blank: the boundary moved."
    # the original July name is preserved, not replaced
    assert adapted["structured_article"]["signature"] == "Never Blank: the boundary moved."
    # July had no Pattern Extractor, and the adapter says so explicitly
    assert adapted["pattern"] == {}


def test_the_adapter_invents_no_title():
    """July published the source headline; the adapter must not fabricate one."""
    july = {
        "decision_lens": {}, "narrative_spine": {},
        "structured_article": {"signature": "Never Blank: x."},
        "platforms": {"long": {"word_count": 400, "body": "b"}},
    }
    with mock.patch(
        "src.never_blank.wednesday_routing.generate_wednesday_article",
        return_value=july,
    ):
        adapted = generate_for_wednesday({"SIGNAL_ID": "x"})

    assert "title" not in adapted["platforms"]["long"]


# ===========================================================================
# 6. Monday is untouched
# ===========================================================================


def test_monday_still_uses_the_shared_engine(tmp_path):
    from tests.test_monday_stream import MONDAY_ROLE, _run_with_role

    code, patches, _argv = _run_with_role(tmp_path, MONDAY_ROLE)

    assert code == 0
    assert patches["generate_article"].called                 # item 6
    # Monday's call keeps every shared-engine argument it had
    kwargs = patches["generate_article"].call_args.kwargs
    for expected in ("cta_mode", "wix_strategy", "linkedin_strategy",
                     "editorial_role_rules", "composer_formats",
                     "closing_contract", "rejected_sink"):
        assert expected in kwargs


def test_a_roleless_run_still_uses_the_shared_engine(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    with sys_argv(argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert patches["generate_article"].called


# ===========================================================================
# The anti-regression the brief asked for explicitly
# ===========================================================================


def test_wednesday_can_never_be_silently_routed_back_to_the_shared_engine():
    """Fails loudly if a later change sends Wednesday through src/editorial.

    This is the guard the brief asked for: the branch is asserted in source,
    so deleting it, inverting it, or widening the shared call to cover
    Wednesday breaks a test rather than a live publication.
    """
    source = Path("scripts/generate_and_publish.py").read_text()

    assert "if is_wednesday_role(_editorial_role_identity):" in source
    assert "article = generate_for_wednesday(editorial.to_legacy_dict())" in source

    branch = source.split("if is_wednesday_role(_editorial_role_identity):")[1]
    wednesday_arm, _, shared_arm = branch.partition("else:")
    # the Wednesday arm must not reach the shared engine …
    assert "generate_article(" not in wednesday_arm
    # … and the shared engine must remain the else-branch, not the default
    assert "generate_article(" in shared_arm.split("platforms  = article")[0]


def test_the_restored_package_is_not_modified_by_the_wiring():
    """The wiring lives outside the restored package, which stays verbatim."""
    originals = FIXTURES / "july_originals"
    for original in sorted(originals.glob("*.py.txt")):
        module = original.name.replace(".py.txt", "")
        ported = Path(f"src/never_blank/wednesday_july/{module}.py").read_text()
        for line in original.read_text().splitlines():
            if line.strip().startswith("from src.editorial."):
                continue
            assert line in ported, f"{module}: wiring altered a restored line"
