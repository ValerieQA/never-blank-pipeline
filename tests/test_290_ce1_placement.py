"""Issue #290: the CE-1 placement rule, and what makes it fail.

The registry says there is one engine and the topology digest says which
engine a run executed. Neither stops a module from growing a second pipeline
inside the first, which is how the current engine acquired its weekday
branches. These scenarios plant both breaches CE-1 names — a weekday branch
and a destination-specific stage selection — prove the check fails on each,
prove it passes on the destination-specific *behaviour* that is legitimate,
and run it over the real editorial core, which is what puts it in CI.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ci.check_ce1_placement import (
    DEFAULT_ROOT,
    Violation,
    check_module,
    check_tree,
    main,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_ROOT = _REPO_ROOT / "src" / "editorial_core"

#: A weekday that decides which stages run: the breach CE-1 exists to forbid.
_WEEKDAY_PIPELINE = '''\
"""Planted breach: Monday gets a pipeline of its own."""

from datetime import datetime


def stages_for_signal(signal):
    if datetime.now().weekday() == 0:
        return ("S-00", "S-01", "S-08")
    return ("S-00", "S-01", "S-02")
'''

#: The same clock, renamed on the way in.
_ALIASED_CLOCK = '''\
from time import time as read_clock


def freshness(signal):
    if read_clock() > signal.seen_at:
        return "stale"
    return "fresh"
'''

#: A destination that decides which stages run.
_DESTINATION_PIPELINE = '''\
def stages_for_destination(destination):
    if destination == "telegram":
        return ("S-10", "S-12")
    return ("S-08", "S-09", "S-10", "S-11", "S-12", "S-13")
'''

#: The same destination pipeline, reaching the stages through a variable.
_DESTINATION_SLICE = '''\
def stages_for_destination(destination, stages):
    if destination == "telegram":
        return stages[:2]
    return stages
'''

#: The same breach naming no destination at all: the surface is a value, and
#: the branch cuts the canonical sequence per destination all the same.
_DESTINATION_MEMBERSHIP = '''\
def stages_for_destination(destination, enabled_destinations, stages):
    if destination in enabled_destinations:
        return stages[:2]
    return stages
'''

#: The same destination, renamed on the way through, as the clock can be.
_RENAMED_DESTINATION = '''\
def stages_for_destination(destination, stages):
    chosen = destination
    if chosen:
        return stages[:2]
    return stages
'''

#: The same breach as a table instead of a branch.
_DESTINATION_TABLE = '''\
_STAGES_BY_DESTINATION = {
    "wix": ("S-08", "S-09", "S-10", "S-11", "S-12", "S-13"),
    "instagram": ("S-10", "S-12"),
}
'''

#: Destination-specific behaviour, which is what adaptation is for.
_DESTINATION_KNOWLEDGE = '''\
def hashtag_policy(destination):
    if destination == "instagram":
        return ("#neverblank", "#evidence")
    if destination == "linkedin":
        return ()
    return ()
'''

#: A module that describes the rule it obeys.
_PROSE_ABOUT_THE_RULE = '''\
"""This module obeys CE-1.

It never reads the weekday and never selects stages by destination: Monday
and Wednesday reach it through the same topology.
"""


def run(signal):
    return signal
'''


def _planted(tmp_path: Path, name: str, source: str) -> list[Violation]:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return check_module(path)


def _rules(violations: list[Violation]) -> set[str]:
    return {violation.rule for violation in violations}


# ===========================================================================
# The planted breaches fail
# ===========================================================================


def test_a_planted_weekday_branch_fails_the_check(tmp_path):
    violations = _planted(tmp_path, "weekday_pipeline.py", _WEEKDAY_PIPELINE)

    assert _rules(violations) == {"CE1-CLOCK"}
    assert any("weekday" in violation.message for violation in violations)


def test_a_planted_destination_specific_stage_selection_fails_the_check(tmp_path):
    violations = _planted(tmp_path, "destination_pipeline.py", _DESTINATION_PIPELINE)

    assert _rules(violations) == {"CE1-DESTINATION"}
    assert any("telegram" in violation.message for violation in violations)


def test_a_stage_table_keyed_by_destination_fails_the_check(tmp_path):
    violations = _planted(tmp_path, "destination_table.py", _DESTINATION_TABLE)

    assert _rules(violations) == {"CE1-DESTINATION"}


def test_a_renamed_clock_is_still_the_clock(tmp_path):
    # the call site spells it read_clock(); the import says what it is
    violations = _planted(tmp_path, "aliased_clock.py", _ALIASED_CLOCK)

    assert _rules(violations) == {"CE1-CLOCK"}
    assert any("time()" in violation.message for violation in violations)


def test_stages_reached_through_a_variable_are_still_selected(tmp_path):
    # no stage identifier appears in the branch, and it still cuts the
    # canonical sequence down to a destination's own pipeline
    violations = _planted(tmp_path, "destination_slice.py", _DESTINATION_SLICE)

    assert _rules(violations) == {"CE1-DESTINATION"}
    assert any("telegram" in violation.message for violation in violations)


def test_a_branch_on_a_destination_value_is_still_a_destination_pipeline(tmp_path):
    # neither a surface nor a stage is written out, and this is still one
    # pipeline per destination — the plainest way to write the breach
    violations = _planted(
        tmp_path, "destination_membership.py", _DESTINATION_MEMBERSHIP)

    assert _rules(violations) == {"CE1-DESTINATION"}
    assert any("'destination'" in violation.message for violation in violations)


def test_a_renamed_destination_is_still_the_destination(tmp_path):
    # the branch spells it chosen(); the binding says what it holds
    violations = _planted(tmp_path, "renamed_destination.py", _RENAMED_DESTINATION)

    assert _rules(violations) == {"CE1-DESTINATION"}
    assert any("'chosen'" in violation.message for violation in violations)


# ===========================================================================
# What the rule deliberately leaves alone
# ===========================================================================


def test_destination_specific_behaviour_is_not_a_destination_pipeline(tmp_path):
    # adaptation (S-10) differs per destination by contract; only choosing
    # *stages* by destination is forbidden
    assert _planted(tmp_path, "adaptation.py", _DESTINATION_KNOWLEDGE) == []


def test_prose_about_the_rule_is_not_a_breach_of_it(tmp_path):
    assert _planted(tmp_path, "documented.py", _PROSE_ABOUT_THE_RULE) == []


def test_the_rule_is_scoped_to_the_core_not_the_run_harness():
    # RunContext stamps started_at from the clock. That is the harness's job,
    # and the default root is what keeps the rule off it.
    harness = check_module(_REPO_ROOT / "src" / "run" / "run_context.py")

    assert any(violation.rule == "CE1-CLOCK" for violation in harness)
    assert DEFAULT_ROOT == Path("src/editorial_core")


# ===========================================================================
# The real editorial core, and the CI entry point
# ===========================================================================


def test_the_editorial_core_obeys_the_placement_rule():
    assert check_tree(_CORE_ROOT) == []


def test_the_check_reports_success_over_the_canonical_core(capsys):
    assert main(["--root", str(_CORE_ROOT)]) == 0
    assert "no weekday or destination pipeline" in capsys.readouterr().out


def test_the_check_fails_ci_on_a_planted_breach(tmp_path, capsys):
    (tmp_path / "weekday_pipeline.py").write_text(_WEEKDAY_PIPELINE, encoding="utf-8")
    (tmp_path / "destination_pipeline.py").write_text(
        _DESTINATION_PIPELINE, encoding="utf-8")

    assert main(["--root", str(tmp_path)]) == 1

    output = capsys.readouterr().out
    assert "CE-1 PLACEMENT VIOLATION" in output
    assert "CE1-CLOCK" in output
    assert "CE1-DESTINATION" in output


def test_a_missing_root_fails_closed(tmp_path, capsys):
    assert main(["--root", str(tmp_path / "nowhere")]) == 1
    assert "NOT CHECKED" in capsys.readouterr().out
