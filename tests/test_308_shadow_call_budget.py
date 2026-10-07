"""A dispatched shadow run may cap its own call budget (#308).

Run 1 spent 6 of 60 calls and stopped at S-04. Reading *why* needs that stage,
not the whole measurement — but `canonical_shadow.yml` had no way to say so:
`--call-budget` appeared nowhere in it, its dispatch inputs were `signal_id`
and `role`, and `NB_RUN_TEXT_CALL_BUDGET` is not read by the canonical path. A
diagnostic run therefore had to be paid for at the acceptance ceiling.

This holds the wiring that fixes it, and the five properties it must have:

1. a dispatch exposes `call_budget`;
2. omitting it leaves the ceiling at the canonical default;
3. an explicit smaller value reaches `--call-budget`;
4. an invalid or out-of-range value **fails closed** — never a quiet fallback;
5. a scheduled run is untouched.

The engine's budget implementation is not changed by any of this:
`RunCallBudget` and `GOLDEN_ENGINE_MAX_CEILING` are what they were, and the
last test here says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "canonical_shadow.yml"
SCRIPT = ROOT / "scripts" / "run_canonical_shadow.py"

RUN_STEP = "Run the canonical chain in shadow"


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict:
    spec = _spec()
    # PyYAML reads the bare `on:` key as the boolean True.
    return spec.get("on") or spec[True]


def _inputs() -> dict:
    return _triggers()["workflow_dispatch"]["inputs"]


def _run_step() -> dict:
    job = next(iter(_spec()["jobs"].values()))
    found = [step for step in job["steps"] if step.get("name") == RUN_STEP]
    assert len(found) == 1, f"expected one {RUN_STEP!r} step; got {len(found)}"
    return found[0]


# ===========================================================================
# 1 · a dispatch exposes it
# ===========================================================================


def test_a_dispatch_can_set_the_call_budget() -> None:
    declared = _inputs()

    assert "call_budget" in declared
    assert declared["call_budget"]["required"] is False
    # `workflow_dispatch` has no number type; the value is validated as digits
    # in the step and as a range by RunCallBudget.
    assert declared["call_budget"]["type"] == "string"
    # The inputs that were already there are untouched.
    assert "signal_id" in declared and "role" in declared


# ===========================================================================
# 2 · omitted means the canonical default, stated in exactly one place
# ===========================================================================


def test_the_default_is_the_canonical_ceiling() -> None:
    """And it is the *same* number, not a copy that can drift.

    The input's default is written in the workflow, so this asserts it equals
    the constant the engine owns. Change `GOLDEN_ENGINE_MAX_CEILING` and this
    fails — which is the point of asserting it rather than trusting it.
    """

    from src.run.call_budget import GOLDEN_ENGINE_MAX_CEILING

    assert _inputs()["call_budget"]["default"] == str(GOLDEN_ENGINE_MAX_CEILING)


def test_the_script_still_defaults_to_the_canonical_ceiling() -> None:
    """The other half: with no flag at all, the script's own default applies."""

    source = SCRIPT.read_text(encoding="utf-8")

    assert "--call-budget" in source
    assert "default=GOLDEN_ENGINE_MAX_CEILING" in source


# ===========================================================================
# 3 · an explicit value reaches the script
# ===========================================================================


def test_an_explicit_budget_reaches_the_call_budget_flag() -> None:
    step = _run_step()

    assert step["env"]["CALL_BUDGET"] == "${{ inputs.call_budget }}"
    assert "--call-budget ${CALL_BUDGET}" in step["run"]
    assert "${BUDGET}" in step["run"]


def test_the_input_is_never_interpolated_straight_into_the_shell() -> None:
    """How an input becomes a command, and why this one does not.

    The value arrives through the environment and is quoted at every use. A
    `${{ inputs.call_budget }}` inside the script body would be substituted by
    Actions before bash ever sees it, so `8; curl …` would run.
    """

    body = _run_step()["run"]

    assert "${{ inputs.call_budget }}" not in body
    assert "${{ github" not in body


# ===========================================================================
# 4 · invalid and out-of-range fail closed
# ===========================================================================


def test_a_non_numeric_budget_is_refused_by_the_step() -> None:
    body = _run_step()["run"]

    # The repository's own dispatch-guard shape: anything but digits exits 1.
    assert "(*[!0-9]*|\"\")" in body
    assert "exit 1" in body
    assert "call_budget must be digits" in body


@pytest.mark.parametrize("limit", [0, -1, 61, 100])
def test_an_out_of_range_budget_is_refused_by_the_engine(limit) -> None:
    """Range is the engine's to judge, and it refuses rather than clamping.

    A silent fallback to 60 would be the failure mode this whole wiring exists
    to avoid: a diagnostic run that quietly costs the acceptance ceiling.
    """

    from src.run.call_budget import (
        GOLDEN_ENGINE_MAX_CEILING,
        CallBudgetConfigurationError,
        RunCallBudget,
    )

    with pytest.raises(CallBudgetConfigurationError):
        RunCallBudget(limit, hard_max=GOLDEN_ENGINE_MAX_CEILING)


@pytest.mark.parametrize("limit", ["8", 8.0, True, None])
def test_a_budget_that_is_not_an_integer_is_refused(limit) -> None:
    from src.run.call_budget import (
        GOLDEN_ENGINE_MAX_CEILING,
        CallBudgetConfigurationError,
        RunCallBudget,
    )

    with pytest.raises(CallBudgetConfigurationError):
        RunCallBudget(limit, hard_max=GOLDEN_ENGINE_MAX_CEILING)


def test_the_budget_the_diagnostic_will_use_is_accepted() -> None:
    """8, the value the owner intends to dispatch. Checked, not assumed."""

    from src.run.call_budget import GOLDEN_ENGINE_MAX_CEILING, RunCallBudget

    budget = RunCallBudget(8, hard_max=GOLDEN_ENGINE_MAX_CEILING)

    assert budget.limit == 8
    assert budget.used == 0


# ===========================================================================
# 5 · a scheduled run is untouched
# ===========================================================================


def test_a_scheduled_run_passes_no_flag_and_keeps_the_canonical_default() -> None:
    """A cron carries no inputs, so `CALL_BUDGET` is empty and no flag is sent.

    That is why the acceptance path still takes its ceiling from the script:
    the workflow adds a way to *lower* it on a dispatch and no second source of
    truth for what it normally is.
    """

    body = _run_step()["run"]

    assert 'BUDGET=""' in body
    assert 'if [ -n "${CALL_BUDGET}" ]; then' in body


def test_the_schedule_itself_is_unchanged() -> None:
    assert _triggers()["schedule"] == [{"cron": "0 11 * * *"}]


def test_the_gate_still_decides_whether_anything_runs_at_all() -> None:
    """The cost gate is prior to the budget and was not relaxed."""

    job = next(iter(_spec()["jobs"].values()))
    gate = [step for step in job["steps"] if step.get("id") == "gate"]

    assert len(gate) == 1
    assert "CANONICAL_SHADOW_ENABLED" in str(gate[0]["env"])
    assert _run_step()["if"].startswith("steps.gate.outputs.run == 'true'")


# ===========================================================================
# The engine's budget implementation is not what changed
# ===========================================================================


def test_the_engine_budget_implementation_is_untouched() -> None:
    """This repair is wiring. The ceiling and its enforcement are unchanged."""

    import inspect

    from src.run.call_budget import (
        GOLDEN_ENGINE_MAX_CEILING,
        R1_MAX_CEILING,
        WEDNESDAY_MAX_CEILING,
        RunCallBudget,
    )

    assert (GOLDEN_ENGINE_MAX_CEILING, R1_MAX_CEILING, WEDNESDAY_MAX_CEILING) == (
        60, 40, 56,
    )
    signature = inspect.signature(RunCallBudget.__init__)
    assert list(signature.parameters) == ["self", "limit", "hard_max"]
    assert signature.parameters["hard_max"].default == R1_MAX_CEILING
