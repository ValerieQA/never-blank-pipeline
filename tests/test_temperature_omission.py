"""A model that refuses ``temperature`` is asked once, not on every call.

Acceptance run 1 (`37460768845`) made 6 `chat()` calls and logged 6 "rejected
temperature" retries — a 100% rate on `gpt-6.1-sol`. Each rejection charges a
second `RunCallBudget` unit (#171) for a request the provider refuses *before*
inference: billed nothing, counted twice. Over the ~50-call six-destination
cascade that halves the effective ceiling, and 60 — the maximum
`GOLDEN_ENGINE_MAX_CEILING` permits — stopped being enough to reach S-14.

So the provider's refusal is now remembered per model, and the parameter is
omitted from the next call onward. The list is **learned, never configured**: a
hard-coded set of model names would be an invented configuration, and an
unreadable one, since the name arrives from a secret.

What must not change, and is asserted here:

* a real retry is still charged — the counter exists to bound work that
  actually happens, and this change removes the *need* for the retry, not the
  accounting of it;
* the first call to an unknown model still sends ``temperature``;
* a model that accepts it is unaffected, forever;
* a ``BadRequestError`` that is not about temperature still propagates;
* the budget still refuses when exhausted.

No test here reaches a provider. The client is a double in every case.
"""

from __future__ import annotations

from typing import Any

import pytest
from openai import BadRequestError

import src.utils.llm_client as llm
from src.run.call_budget import (
    RunCallBudget,
    RunCallBudgetExceededError,
    activate_call_budget,
)

ACCEPTS = "model-that-accepts"
REFUSES = "model-that-refuses"


class TemperatureRejected(BadRequestError):
    """The provider's own answer, in the shape the code matches on."""

    def __init__(self, message: str = "Unsupported parameter: 'temperature'") -> None:
        Exception.__init__(self, message)


class OtherBadRequest(BadRequestError):
    def __init__(self, message: str = "Unsupported parameter: 'seed'") -> None:
        Exception.__init__(self, message)


class _Completions:
    """Records every request, and refuses `temperature` for one model."""

    def __init__(self, refuse_for: str, error: type[BadRequestError]) -> None:
        self.calls: list[dict] = []
        self._refuse_for = refuse_for
        self._error = error

    def _respond(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("model") == self._refuse_for and "temperature" in kwargs:
            raise self._error()
        return _Response()

    create = _respond
    parse = _respond


class _Response:
    class _Message:
        content = '{"ok": true}'
        parsed = "parsed-object"

    class _Choice:
        message = _Response._Message() if False else None  # set below

    choices: list = []
    usage = None

    def __init__(self) -> None:
        choice = type("C", (), {"message": _Response._Message()})()
        self.choices = [choice]


class _Client:
    def __init__(self, refuse_for: str = REFUSES,
                 error: type[BadRequestError] = TemperatureRejected) -> None:
        self.completions = _Completions(refuse_for, error)
        self.chat = type("Chat", (), {"completions": self.completions})()
        self.beta = type(
            "Beta", (), {"chat": type("C", (), {"completions": self.completions})()}
        )()


@pytest.fixture(autouse=True)
def _clean_memo_and_client(monkeypatch):
    """A fresh memo per test — it is process-local module state."""

    llm._TEMPERATURE_UNSUPPORTED.clear()
    client = _Client()
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(llm, "observe_request", lambda *a, **k: None)
    monkeypatch.setattr(llm, "observe_usage", lambda *a, **k: None)
    yield client
    llm._TEMPERATURE_UNSUPPORTED.clear()


def _temps(client: _Client) -> list[bool]:
    """Whether each recorded request carried `temperature`."""

    return ["temperature" in c for c in client.completions.calls]


# ═══════════════════════════════ chat() ════════════════════════════════════


def test_the_first_call_still_sends_temperature(_clean_memo_and_client) -> None:
    client = _clean_memo_and_client
    llm.chat("s", "u", model=ACCEPTS)

    assert _temps(client) == [True]


def test_a_refusal_is_retried_and_both_attempts_are_charged(
    _clean_memo_and_client,
) -> None:
    """The accounting this change must not weaken: a retry that really happens
    still costs a unit."""

    client = _clean_memo_and_client
    budget = RunCallBudget(10, hard_max=40)

    with activate_call_budget(budget):
        llm.chat("s", "u", model=REFUSES)

    assert _temps(client) == [True, False], "sent, refused, retried without it"
    assert budget.used == 2, "a real retry is still charged"


def test_the_next_call_omits_temperature_and_costs_one_unit(
    _clean_memo_and_client,
) -> None:
    """The whole point: the refusal is learned, so it is not repeated."""

    client = _clean_memo_and_client
    budget = RunCallBudget(10, hard_max=40)

    with activate_call_budget(budget):
        llm.chat("s", "u", model=REFUSES)   # learns: 2 units
        before = budget.used
        llm.chat("s", "u", model=REFUSES)   # omits: 1 unit

    assert _temps(client) == [True, False, False]
    assert budget.used - before == 1


def test_fifty_calls_cost_fifty_one_units_not_a_hundred(
    _clean_memo_and_client,
) -> None:
    """The arithmetic that unblocked the ceiling, asserted rather than claimed.

    Before: 50 logical calls spent 100 units against a maximum of 60, so a
    six-destination cascade (~50 calls, Step 2 §6 normal ~61) could not finish.
    """

    budget = RunCallBudget(60, hard_max=60)

    with activate_call_budget(budget):
        for _ in range(50):
            llm.chat("s", "u", model=REFUSES)

    assert budget.used == 51
    assert budget.used <= budget.limit


def test_a_model_that_accepts_temperature_is_never_affected(
    _clean_memo_and_client,
) -> None:
    client = _clean_memo_and_client
    budget = RunCallBudget(10, hard_max=40)

    with activate_call_budget(budget):
        llm.chat("s", "u", model=REFUSES)   # teaches the memo about REFUSES
        llm.chat("s", "u", model=ACCEPTS)
        llm.chat("s", "u", model=ACCEPTS)

    assert _temps(client) == [True, False, True, True]
    assert llm._TEMPERATURE_UNSUPPORTED == {REFUSES}


def test_a_different_bad_request_still_propagates(monkeypatch) -> None:
    """Only a temperature refusal is handled; everything else is a real error,
    and it must not be memoised."""

    client = _Client(refuse_for=REFUSES, error=OtherBadRequest)
    monkeypatch.setattr(llm, "_get_client", lambda: client)

    with pytest.raises(BadRequestError):
        llm.chat("s", "u", model=REFUSES)

    assert llm._TEMPERATURE_UNSUPPORTED == set()


def test_the_budget_still_refuses_when_exhausted(_clean_memo_and_client) -> None:
    """A safety limit this change must leave exactly as it was."""

    budget = RunCallBudget(1, hard_max=40)

    with activate_call_budget(budget):
        llm.chat("s", "u", model=ACCEPTS)
        with pytest.raises(RunCallBudgetExceededError):
            llm.chat("s", "u", model=ACCEPTS)


def test_a_refusal_cannot_exceed_the_budget_on_its_retry(
    _clean_memo_and_client,
) -> None:
    """The retry is charged *before* its transport, so a budget with one unit
    left refuses the second attempt rather than paying for it."""

    budget = RunCallBudget(1, hard_max=40)

    with activate_call_budget(budget):
        with pytest.raises(RunCallBudgetExceededError):
            llm.chat("s", "u", model=REFUSES)


# ══════════════════════════════ chat_qc() ══════════════════════════════════


def test_chat_qc_learns_the_same_refusal(_clean_memo_and_client) -> None:
    client = _clean_memo_and_client
    budget = RunCallBudget(10, hard_max=40)

    with activate_call_budget(budget):
        llm.chat_qc("s", "u", model=REFUSES)
        llm.chat_qc("s", "u", model=REFUSES)

    assert _temps(client) == [True, False, False]
    assert budget.used == 3, "2 for the learning call, 1 for the next"


def test_chat_qc_keeps_its_own_temperature_for_an_accepting_model(
    _clean_memo_and_client, monkeypatch
) -> None:
    """`chat_qc` sends `_qc_temperature`, not `_temperature` — the omission
    must not quietly change which value an unaffected model receives."""

    client = _clean_memo_and_client
    monkeypatch.setenv("NB_OPENAI_QC_TEMPERATURE", "0.11")

    llm.chat_qc("s", "u", model=ACCEPTS)

    assert client.completions.calls[0]["temperature"] == pytest.approx(0.11)


# ═════════════════════════════ chat_parsed() ═══════════════════════════════


class _Model:
    """Stands in for a Pydantic response model; never instantiated here."""


def test_chat_parsed_learns_the_same_refusal(_clean_memo_and_client) -> None:
    client = _clean_memo_and_client
    budget = RunCallBudget(10, hard_max=40)

    with activate_call_budget(budget):
        llm.chat_parsed("s", "u", _Model, model=REFUSES)
        llm.chat_parsed("s", "u", _Model, model=REFUSES)

    assert _temps(client) == [True, False, False]
    assert budget.used == 3


def test_chat_parsed_still_sends_the_schema_on_the_retry(
    _clean_memo_and_client,
) -> None:
    """The retry used to restate its arguments by hand; it now reuses one
    dict, so the schema cannot be lost from the second attempt."""

    client = _clean_memo_and_client

    llm.chat_parsed("s", "u", _Model, model=REFUSES)

    retry = client.completions.calls[1]
    assert retry["response_format"] is _Model
    assert retry["messages"][0]["content"] == "s"
    assert "temperature" not in retry


# ════════════════════════ the memo itself ══════════════════════════════════


def test_the_memo_is_learned_and_starts_empty() -> None:
    """Not a configured list of model names: nothing here names a model, and
    the names arrive from a secret this code cannot read."""

    import ast
    import inspect

    tree = ast.parse(inspect.getsource(llm))
    for node in ast.walk(tree):
        # The declaration is annotated (`: set[str] = set()`), so it is an
        # `AnnAssign`; a later plain assignment would be an `Assign`. Accept
        # either, and refuse both if a model name appears in the initialiser.
        target = getattr(node, "target", None) if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
        if getattr(target, "id", "") != "_TEMPERATURE_UNSUPPORTED":
            continue
        assert isinstance(node.value, ast.Call), "not a literal set of names"
        assert node.value.func.id == "set"
        assert not node.value.args, "starts empty, holds no model name"
        return
    raise AssertionError("_TEMPERATURE_UNSUPPORTED not found")


def test_all_three_entry_points_consult_the_memo() -> None:
    """A fourth caller added later would be the obvious place to forget it."""

    import inspect

    for fn in (llm.chat, llm.chat_qc, llm.chat_parsed):
        source = inspect.getsource(fn)
        assert "_supports_temperature(model)" in source, fn.__name__
        assert "_temperature_rejected(model)" in source, fn.__name__
