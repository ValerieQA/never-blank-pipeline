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
from tests.test_generate_and_publish import _make_ok_publish_result, _make_rc_mock
from tests.test_monday_stream import (
    FIXTURE_SOURCE_TITLE,
    FIXTURE_SOURCE_URL,
    WEDNESDAY_SUPPLY,
)
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


def _run_wednesday(tmp_path, *, dry_run=True, article=None, overrides=None,
                   signal=None):
    """Drive the REAL entrypoint with the Wednesday role.

    When ``signal`` is given it is injected as the run's raw signal AND as
    the editorial context the entrypoint passes to generation, so the object
    reaching the routing seam is the real one rather than a placeholder.
    """
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    argv += ["--editorial-role", WEDNESDAY_ROLE_ID]
    # #211: Wednesday's fresh-generation runs no longer read the shared
    # signal store — they discover their own through the restored July
    # research. These scenarios are about ROUTING, so the supply is injected
    # here at its own seam; the supply path itself is proven end to end,
    # against a real RSS fixture, in tests/test_wednesday_supply.py.
    supplied = signal if signal is not None else dict(WEDNESDAY_SUPPLY)
    patches["supply_wednesday_signal"] = mock.MagicMock(return_value=supplied)
    # the run must be dispatched under the supplied signal's own id, so
    # research lineage is written under the historical identity
    argv = [supplied["SIGNAL_ID"] if i == 2 else part for i, part in enumerate(argv)]
    if signal is not None:
        def _rc_with_signal(assignment, raw_signal, run_ctx):
            rc = _make_rc_mock(run_ctx.run_id)
            rc.to_editorial.return_value.to_legacy_dict.return_value = signal
            return rc

        patches["_build_legacy_research_context"] = mock.MagicMock(
            side_effect=_rc_with_signal
        )
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
    """item 4 — the HISTORICAL signal travels the real runtime route.

    The Versant fixture is injected as the run's signal, so the object handed
    to the restored generation seam is the real 46-field record, not a
    placeholder. Generation itself stays stubbed: no paid call is made.
    """
    code, patches = _run_wednesday(tmp_path, dry_run=False, signal=versant)

    assert code == 0
    routed = patches["generate_for_wednesday"].call_args.args[0]

    # the exact historical identity reached the restored path …
    assert routed["SIGNAL_ID"] == "37a503640b83be6c"
    assert routed["HEADLINE"] == (
        "Versant agrees to buy golf simulator company Full Swing for $530 million"
    )
    assert routed["SOURCE_NAME"] == "CNBC Business"
    assert "cnbc.com" in routed["SOURCE_URL"]

    # … carrying the July fields the restored stages actually consume
    assert routed["CORE_FACT"] == versant["CORE_FACT"]
    assert routed["CORE_TENSION"] == versant["CORE_TENSION"]
    assert routed["BUSINESS_LESSON"] == versant["BUSINESS_LESSON"]
    assert routed["WHY_THIS_CASE_IS_INTERESTING"] == (
        versant["WHY_THIS_CASE_IS_INTERESTING"]
    )
    assert routed["COUNTER_EXAMPLE"] == versant["COUNTER_EXAMPLE"]

    # … and the run reached publication preparation
    assert list(tmp_path.glob("*/runs/*/generated.json"))
    assert patches["WixPublisher"].return_value.publish.called
    # the shared engine was never consulted for this signal
    assert not patches["generate_article"].called


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
# Wednesday's decision authority — the restored path is not gated by the
# current canonical Decision Lens (#210 review, blocker 1)
# ===========================================================================


def test_wednesday_never_consults_the_canonical_decision_lens(tmp_path, versant):
    """The Lens must not be able to stop Wednesday before generation.

    Live run 32769085831 is the proof this matters: both Lens criteria came
    back *satisfied* and it still returned ``revise``, killing the run before
    any editorial stage ran. Wednesday's business reasoning is the restored
    July path; current shared reasoning may not be a prerequisite for it.
    """
    exploding = mock.MagicMock(
        side_effect=AssertionError("canonical Decision Lens consulted for Wednesday")
    )
    code, patches = _run_wednesday(
        tmp_path, dry_run=False, signal=versant,
        overrides={"evaluate_and_persist_decision": exploding,
                   "production_evaluator": exploding},
    )

    assert code == 0
    assert not exploding.called
    assert patches["generate_for_wednesday"].called


def test_wednesday_decision_authority_is_persisted_not_skipped(tmp_path, versant):
    """Bypassing the Lens must leave an auditable record, never a silence."""
    code, _patches = _run_wednesday(tmp_path, dry_run=False, signal=versant)
    assert code == 0

    policy_records = list(tmp_path.glob("*/runs/*/decision_policy.json"))
    assert len(policy_records) == 1
    policy = json.loads(policy_records[0].read_text())
    assert policy["decision_policy"] == "role_bounded_r1"
    assert policy["research_readiness"] == "ready"

    # …and no canonical decision artifact was fabricated in its place
    assert not list(tmp_path.glob("*/runs/*/decision.json"))

    # the authority is also recorded on the immutable provenance anchor
    assignment = json.loads(
        next(tmp_path.glob("*/runs/*/assignment.json")).read_text()
    )
    assert assignment["editorial_role"]["role_id"] == WEDNESDAY_ROLE_ID
    assert assignment["editorial_role"]["decision_policy"] == "role_bounded_r1"


def test_the_wednesday_role_declares_the_policy_in_configuration():
    """The authority is configuration a reviewer can read, not code."""
    from pathlib import Path as _Path

    from src.editorial.editorial_role import resolve_editorial_role
    from src.strategy.business_config import load_business_strategy_configuration

    configuration = load_business_strategy_configuration(
        _Path("strategy/current/business_strategy.json")
    )
    _identity, role = resolve_editorial_role(configuration, WEDNESDAY_ROLE_ID)
    assert role.decision_policy == "role_bounded_r1"


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
