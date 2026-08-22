"""Issue #171: one run has a deterministic ceiling on paid text-model calls.

The ceiling is derived from the audited canonical call graph (normal Monday
~18 in-run calls, Wednesday ~19, legitimate worst case with every stage
retry and one revision round = 34; default and hard maximum 40). These
scenarios prove the legitimate shapes fit, the call after the ceiling is
refused before any transport is invoked, budget state cannot leak between
runs or contexts, the configuration refuses invalid ceilings rather than
clamping them, and a mid-run exhaustion through the real canonical
entrypoint consumes nothing and reaches no publisher.
"""

from __future__ import annotations

import contextvars
import json
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.run.call_budget import (
    DEFAULT_CEILING,
    R1_MAX_CEILING,
    CallBudgetConfigurationError,
    RunCallBudget,
    RunCallBudgetExceededError,
    activate_call_budget,
    active_call_budget,
    charge_active_call_budget,
    configured_run_call_ceiling,
)
from src.utils import llm_client
from tests import test_generate_and_publish as legacy
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output


# ===========================================================================
# 1–3. The audited legitimate shapes fit under the ceiling
# ===========================================================================

# In-run call counts from the Issue #171 derivation (the pre-run eligibility
# selector is a separate process with its own bounds and is not budgeted).
MONDAY_NORMAL = 1 + 8 + 5 + 1 + 2            # evidence, engine, composer, accept, hashtags = 17
MONDAY_WITH_PACKAGE = MONDAY_NORMAL + 1       # + content-package chat = 18
WEDNESDAY_NORMAL = MONDAY_WITH_PACKAGE + 1    # + Decision Lens evaluator = 19
REVISION_ROUND = 2                            # revision + recheck
WORST_LEGITIMATE = 1 + 1 + 1 + 16 + 10 + 1 + REVISION_ROUND + 2   # = 34


@pytest.mark.parametrize(
    "calls",
    [MONDAY_NORMAL, MONDAY_WITH_PACKAGE, WEDNESDAY_NORMAL,
     WEDNESDAY_NORMAL + REVISION_ROUND, WORST_LEGITIMATE],
    ids=["monday-normal", "monday-with-package", "wednesday-normal",
         "wednesday-with-revision", "worst-legitimate-all-retries"],
)
def test_every_legitimate_canonical_shape_fits_the_default_ceiling(calls):
    budget = RunCallBudget(limit=DEFAULT_CEILING)
    for _ in range(calls):
        budget.spend()
    assert budget.used == calls
    assert budget.remaining == DEFAULT_CEILING - calls
    assert budget.remaining > 0  # headroom, not exact fit


def test_the_derivation_arithmetic_is_what_the_module_documents():
    assert WORST_LEGITIMATE == 34
    assert DEFAULT_CEILING == R1_MAX_CEILING == 40
    assert WORST_LEGITIMATE < DEFAULT_CEILING


# ===========================================================================
# 4–6. The ceiling boundary: N runs, N+1 is refused before transport
# ===========================================================================


def test_call_n_at_the_ceiling_executes_and_n_plus_one_is_refused():
    budget = RunCallBudget(limit=3)
    for _ in range(3):
        budget.spend()          # calls 1..N all execute
    with pytest.raises(RunCallBudgetExceededError) as info:
        budget.spend()          # call N+1 refused
    assert info.value.used == 3
    assert info.value.limit == 3
    assert budget.used == 3     # the refusal did not count as spend


def test_refusal_happens_before_any_transport_is_invoked(monkeypatch):
    constructed, requested = [], []

    class FakeCompletions:
        def create(self, **kwargs):
            requested.append(kwargs)
            class _Msg:  # minimal response shape
                content = "{}"
            class _Choice:
                message = _Msg()
            class _Resp:
                choices = [_Choice()]
            return _Resp()

    class FakeClient:
        def __init__(self):
            self.chat = type("C", (), {"completions": FakeCompletions()})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client, "_client", FakeClient())
    monkeypatch.setenv("NB_OPENAI_API_KEY", "test-key-never-used")

    budget = RunCallBudget(limit=1)
    with activate_call_budget(budget):
        llm_client.chat("system", "user", json_mode=True)   # call N: allowed
        assert len(requested) == 1
        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat("system", "user")               # call N+1
    # the refused call made NO transport request and constructed NO client
    assert len(requested) == 1
    assert constructed == []
    monkeypatch.setattr(llm_client, "_client", None)


def test_all_three_chat_functions_charge_the_budget(monkeypatch):
    class FakeClient:  # any attribute access explodes if reached
        def __getattr__(self, name):
            raise AssertionError("transport must not be reached")

    monkeypatch.setattr(llm_client, "_client", FakeClient())
    exhausted = RunCallBudget(limit=1)
    exhausted.spend()

    with activate_call_budget(exhausted):
        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat("s", "u")
        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat_qc("s", "u")
        from pydantic import BaseModel

        class _Shape(BaseModel):
            value: str

        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat_parsed("s", "u", response_model=_Shape)
    monkeypatch.setattr(llm_client, "_client", None)


def test_the_budget_error_is_not_retryable_as_a_stage_value_error():
    # _run_stage retries ValueError once; retrying an exhausted budget would
    # be a guaranteed second refusal, so the error must not be a ValueError
    assert not issubclass(RunCallBudgetExceededError, ValueError)


# ===========================================================================
# 7–8. No leakage between runs or contexts
# ===========================================================================


def test_budget_state_does_not_leak_into_the_next_run():
    first = RunCallBudget(limit=2)
    with activate_call_budget(first):
        first.spend()
        first.spend()
        with pytest.raises(RunCallBudgetExceededError):
            charge_active_call_budget()
    assert active_call_budget() is None       # deactivated on exit

    second = RunCallBudget(limit=2)           # a new run constructs its own
    with activate_call_budget(second):
        assert active_call_budget() is second
        charge_active_call_budget()           # fresh counter — not exhausted
    assert second.used == 1
    assert first.used == 2                    # and the old one is untouched


def test_deactivation_survives_an_exception():
    budget = RunCallBudget(limit=1)
    with pytest.raises(RuntimeError, match="boom"):
        with activate_call_budget(budget):
            raise RuntimeError("boom")
    assert active_call_budget() is None


def test_two_independent_contexts_do_not_share_counters():
    outcomes = {}

    def run_in_context(name, budget, spends):
        def _inner():
            with activate_call_budget(budget):
                for _ in range(spends):
                    charge_active_call_budget()
                outcomes[name] = active_call_budget().used
        contextvars.copy_context().run(_inner)

    a, b = RunCallBudget(limit=5), RunCallBudget(limit=5)
    run_in_context("a", a, 4)
    run_in_context("b", b, 1)

    assert outcomes == {"a": 4, "b": 1}
    assert (a.used, b.used) == (4, 1)         # no cross-talk
    assert active_call_budget() is None       # and nothing bled outward


# ===========================================================================
# 9. Configuration: bounded, refused not clamped
# ===========================================================================


def test_ceiling_configuration_accepts_the_bounded_range(monkeypatch):
    monkeypatch.delenv("NB_RUN_TEXT_CALL_BUDGET", raising=False)
    assert configured_run_call_ceiling() == DEFAULT_CEILING
    monkeypatch.setenv("NB_RUN_TEXT_CALL_BUDGET", "1")
    assert configured_run_call_ceiling() == 1
    monkeypatch.setenv("NB_RUN_TEXT_CALL_BUDGET", "20")
    assert configured_run_call_ceiling() == 20
    monkeypatch.setenv("NB_RUN_TEXT_CALL_BUDGET", "40")
    assert configured_run_call_ceiling() == 40


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "41", "999999", "1.0", "", " ", " 20", "20 ", "twenty",
     "+20", "020", "0x14"],
    ids=["zero", "negative", "over-max", "unlimited-attempt", "float",
         "empty", "whitespace", "leading-space", "trailing-space", "word",
         "plus-sign", "zero-padded", "hex"],
)
def test_invalid_ceilings_are_refused_never_clamped(monkeypatch, value):
    monkeypatch.setenv("NB_RUN_TEXT_CALL_BUDGET", value)
    with pytest.raises(CallBudgetConfigurationError, match="NB_RUN_TEXT_CALL_BUDGET"):
        configured_run_call_ceiling()


def test_budget_construction_rejects_out_of_range_limits():
    for bad in (0, -1, 41, 10**6, True, "20", 20.0, None):
        with pytest.raises(CallBudgetConfigurationError):
            RunCallBudget(limit=bad)


# ===========================================================================
# 10. The #170 provider circuit breaker is untouched
# ===========================================================================


def test_the_circuit_breaker_suite_still_holds():
    # #170's own regressions run in the same suite; here we pin the two
    # contracts' independence: an exhausted budget is not a provider error,
    # and the eligibility boundary's scope field is unaffected by #171.
    from src.editorial.source_eligibility import SourceEligibilityError

    assert not issubclass(RunCallBudgetExceededError, SourceEligibilityError)
    exc = SourceEligibilityError("x")
    assert exc.scope == "candidate"


# ===========================================================================
# 5, 6, 11, 12 — end to end: exhaustion through the real canonical entrypoint
# ===========================================================================


def _exhaustion_entry(tmp_path):
    """Run the real entrypoint; generation charges the budget until refused."""

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output())
    charges = {"attempted": 0}

    def spend_like_a_runaway_engine(*args, **kwargs):
        # a defective generation loop that keeps calling the model: every
        # charge below goes through the same seam llm_client charges
        while True:
            charges["attempted"] += 1
            charge_active_call_budget()

    patches["generate_article"].side_effect = spend_like_a_runaway_engine
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches, charges


def test_mid_run_exhaustion_stops_the_run_consumes_nothing_reaches_no_publisher(
    tmp_path, capsys
):
    code, patches, charges = _exhaustion_entry(tmp_path)

    assert code == 1
    # the runaway loop was stopped at exactly the ceiling: the refused call
    # (attempt N+1) charged nothing and ended the run
    assert charges["attempted"] == DEFAULT_CEILING + 1
    # distinct, understandable error, with used/limit accounting
    out = capsys.readouterr().out
    assert "call budget exhausted" in out
    assert f"{DEFAULT_CEILING} used / {DEFAULT_CEILING} limit / 0 remaining" in out
    # no publisher was reached, nothing was packaged, nothing consumed
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    assert not list(tmp_path.glob("*/runs/*/publication_results.json"))


def test_exhaustion_is_honestly_accounted_in_the_run_report(tmp_path):
    _exhaustion_entry(tmp_path)

    reports = list(tmp_path.glob("*/runs/*/run_report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["completed"] is False
    assert report["terminal_disposition"] == "stopped"
    assert any("call budget exhausted" in e for e in report["errors"])
    assert report["channels"] == []


def test_a_normal_run_reports_its_budget_usage(tmp_path, capsys):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    out = capsys.readouterr().out
    # used/limit/remaining are reported; the harness fakes transports, so
    # used stays 0 — the accounting line itself is the contract here
    assert f"/ {DEFAULT_CEILING} limit /" in out
    assert "text-model call budget:" in out


# ===========================================================================
# Correction round: the temperature-fallback transport is charged too
# ===========================================================================


def _temperature_rejection() -> BaseException:
    import openai

    exc = openai.BadRequestError.__new__(openai.BadRequestError)
    Exception.__init__(exc, "Unsupported value: 'temperature'")
    exc.message = "Unsupported value: 'temperature'"
    return exc


class _FallbackClient:
    """First create/parse rejects temperature; every later one succeeds."""

    def __init__(self):
        self.requests = 0
        outer = self

        class _Response:
            class _Choice:
                class _Msg:
                    content = "{}"
                    parsed = {"value": "x"}
                message = _Msg()
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                outer.requests += 1
                if outer.requests == 1:
                    raise _temperature_rejection()
                return _Response()

            def parse(self, **kwargs):
                return self.create(**kwargs)

        chat_ns = type("Chat", (), {"completions": _Completions()})()
        self.chat = chat_ns
        self.beta = type("Beta", (), {"chat": chat_ns})()


def _shape_model():
    from pydantic import BaseModel

    class _Shape(BaseModel):
        value: str

    return _Shape


@pytest.mark.parametrize("fn_name", ["chat", "chat_qc", "chat_parsed"])
def test_the_temperature_fallback_is_charged_as_a_second_call(monkeypatch, fn_name):
    monkeypatch.setattr(llm_client, "_client", _FallbackClient())
    budget = RunCallBudget(limit=2)

    with activate_call_budget(budget):
        if fn_name == "chat_parsed":
            llm_client.chat_parsed("s", "u", response_model=_shape_model())
        else:
            getattr(llm_client, fn_name)("s", "u")

    # one logical call, two application-level transports, two charges
    assert llm_client._client.requests == 2
    assert budget.used == 2
    monkeypatch.setattr(llm_client, "_client", None)


@pytest.mark.parametrize("fn_name", ["chat", "chat_qc", "chat_parsed"])
def test_an_exhausted_budget_refuses_the_fallback_transport(monkeypatch, fn_name):
    client = _FallbackClient()
    monkeypatch.setattr(llm_client, "_client", client)
    budget = RunCallBudget(limit=1)

    with activate_call_budget(budget):
        with pytest.raises(RunCallBudgetExceededError):
            if fn_name == "chat_parsed":
                llm_client.chat_parsed("s", "u", response_model=_shape_model())
            else:
                getattr(llm_client, fn_name)("s", "u")

    # the first transport ran (and was charged); the fallback never executed
    assert client.requests == 1
    assert budget.used == 1
    monkeypatch.setattr(llm_client, "_client", None)


def test_non_temperature_bad_requests_still_raise_without_extra_charges(monkeypatch):
    import openai

    class _AlwaysBad:
        def __init__(self):
            self.requests = 0
            outer = self

            class _Completions:
                def create(self, **kwargs):
                    outer.requests += 1
                    exc = openai.BadRequestError.__new__(openai.BadRequestError)
                    Exception.__init__(exc, "Invalid request shape")
                    exc.message = "Invalid request shape"
                    raise exc

            self.chat = type("Chat", (), {"completions": _Completions()})()

    client = _AlwaysBad()
    monkeypatch.setattr(llm_client, "_client", client)
    budget = RunCallBudget(limit=5)

    with activate_call_budget(budget):
        with pytest.raises(openai.BadRequestError):
            llm_client.chat("s", "u")

    # #170 semantics preserved: no fallback for non-temperature errors,
    # exactly one transport, exactly one charge
    assert client.requests == 1
    assert budget.used == 1
    monkeypatch.setattr(llm_client, "_client", None)
