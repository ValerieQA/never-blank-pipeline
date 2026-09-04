"""Issue #217: finite Wednesday-only text-model call budget.

The restored July path is intentionally expensive: ten candidate enrichments,
ten angle calls, and five initial platform compositions are historical product
behaviour.  These tests pin the executable call-graph arithmetic and prove the
larger finite ceiling is available only to the declared Wednesday role.
"""

from pathlib import Path
import sys

import pytest
import yaml

import scripts.generate_and_publish as entrypoint

from src.run.call_budget import (
    DEFAULT_CEILING,
    R1_MAX_CEILING,
    WEDNESDAY_MAX_CEILING,
    CallBudgetConfigurationError,
    RunCallBudget,
    RunCallBudgetExceededError,
    active_call_budget,
    configured_run_call_ceiling,
)


WEDNESDAY_ROLE = "never-blank-wednesday-golden"

# Current executable lifecycle, with July's top_n_to_enrich=10.
JULY_RESEARCH = 1 + 1 + 1 + 10 + 10
CURRENT_EVIDENCE = 1
JULY_SINGLE_CALL_GENERATION_STAGES = 7
JULY_PLATFORM_COMPOSITIONS = 5
INITIAL_ACCEPTANCE = 1
REVISION_AND_RECHECK = 2
LINKEDIN_RECOMPOSITION = 1

NO_REVISION = (
    JULY_RESEARCH
    + CURRENT_EVIDENCE
    + JULY_SINGLE_CALL_GENERATION_STAGES
    + JULY_PLATFORM_COMPOSITIONS
    + INITIAL_ACCEPTANCE
)
ONE_REVISION = NO_REVISION + REVISION_AND_RECHECK + LINKEDIN_RECOMPOSITION
MAX_NORMAL = (
    ONE_REVISION
    + JULY_SINGLE_CALL_GENERATION_STAGES
    + JULY_PLATFORM_COMPOSITIONS
    + LINKEDIN_RECOMPOSITION
)
SAFETY_MARGIN = WEDNESDAY_MAX_CEILING - MAX_NORMAL


def _steps(workflow: str) -> list[dict]:
    data = yaml.safe_load(Path(workflow).read_text())
    return next(iter(data["jobs"].values()))["steps"]


def _generation_environment(workflow: str, prefix: str) -> dict:
    return next(
        step["env"]
        for step in _steps(workflow)
        if str(step.get("name", "")).startswith(prefix)
    )


def test_current_wednesday_call_graph_derives_the_limit_not_the_reverse():
    assert NO_REVISION == 37
    assert ONE_REVISION == 40
    assert MAX_NORMAL == 53
    assert SAFETY_MARGIN == 3
    assert WEDNESDAY_MAX_CEILING == 56


def test_wednesday_workflow_configures_the_finite_role_scoped_limit():
    env = _generation_environment(
        ".github/workflows/wednesday_golden.yml",
        "Wednesday Golden — Generate + Publish",
    )
    assert env["NB_RUN_TEXT_CALL_BUDGET"] == "56"


def test_monday_workflow_budget_configuration_is_unchanged():
    env = _generation_environment(
        ".github/workflows/monday_publish.yml",
        "Monday — Generate + Publish",
    )
    assert "NB_RUN_TEXT_CALL_BUDGET" not in env


def test_default_and_roleless_limit_remain_exactly_40(monkeypatch):
    monkeypatch.delenv("NB_RUN_TEXT_CALL_BUDGET", raising=False)
    assert DEFAULT_CEILING == R1_MAX_CEILING == 40
    assert configured_run_call_ceiling() == 40
    assert configured_run_call_ceiling("never-blank-monday-documented-case") == 40


def test_only_the_declared_wednesday_role_can_configure_56(monkeypatch):
    monkeypatch.setenv("NB_RUN_TEXT_CALL_BUDGET", "56")
    assert configured_run_call_ceiling(WEDNESDAY_ROLE) == 56
    with pytest.raises(CallBudgetConfigurationError):
        configured_run_call_ceiling()
    with pytest.raises(CallBudgetConfigurationError):
        configured_run_call_ceiling("never-blank-monday-documented-case")


def test_canonical_entrypoint_activates_56_only_for_wednesday(monkeypatch):
    observed = []

    def fake_run(state, **kwargs):
        observed.append((active_call_budget().limit, kwargs))
        return 0

    monkeypatch.setenv("NB_RUN_TEXT_CALL_BUDGET", "56")
    monkeypatch.setattr(
        sys, "argv", ["generate_and_publish.py", "--editorial-role", WEDNESDAY_ROLE]
    )
    monkeypatch.setattr(entrypoint, "_run", fake_run)
    monkeypatch.setattr(entrypoint, "_emit_terminal_report", lambda *args: None)

    assert entrypoint.main() == 0
    assert observed and observed[0][0] == 56


def test_default_budget_constructor_still_refuses_any_limit_above_40():
    with pytest.raises(CallBudgetConfigurationError):
        RunCallBudget(limit=41)


def test_wednesday_budget_fails_closed_on_call_57():
    budget = RunCallBudget(limit=56, hard_max=WEDNESDAY_MAX_CEILING)
    for _ in range(56):
        budget.spend()
    with pytest.raises(RunCallBudgetExceededError) as info:
        budget.spend()
    assert (info.value.used, info.value.limit) == (56, 56)
    assert budget.used == 56


def test_no_retry_or_fallback_configuration_was_added_to_wednesday():
    env = _generation_environment(
        ".github/workflows/wednesday_golden.yml",
        "Wednesday Golden — Generate + Publish",
    )
    assert "NB_OPENAI_MAX_RETRIES" not in env
    assert "NB_OPENAI_CHAT_MODEL_FALLBACK" not in env
    assert "NB_FALLBACK_MODEL" not in env
