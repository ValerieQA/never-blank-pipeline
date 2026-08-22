"""Hard per-run budget for paid text-model calls (#171).

One canonical run must have a deterministic upper bound on the number of
logical text-model calls it can make. A bug, an unexpected queue, a retry
loop or a revision loop must never be able to create unbounded API spend —
the only thing that stopped the last runaway was the provider refusing
service.

What is counted: application-level calls through the shared text client
(``src.utils.llm_client``), charged before the transport is invoked. What is
not counted: deterministic work, SDK-internal HTTP retries (bounded
separately by ``NB_OPENAI_MAX_RETRIES``, #170), image generation (a separate
concern), and processes that never activate a budget (the pre-run
eligibility selector is bounded by ``--max-candidates`` plus the #170
provider circuit breaker).

The active budget lives in a ``contextvars.ContextVar`` — never a module
global — so two run contexts cannot share a counter and nothing leaks
between runs or tests. Exhaustion raises ``RunCallBudgetExceededError``,
which is deliberately NOT a ``ValueError``: the editorial ``_run_stage``
retry catches ``ValueError``, and retrying an exhausted budget would be a
guaranteed second refusal.

Release 1 ceiling — derived from the audited call graph, not guessed:
normal Monday ≈ 18 in-run calls, Wednesday ≈ 19, and the legitimate worst
case (every stage retried once, one authorized revision round, package
regeneration, both hashtag calls) is 34. The default and hard maximum is 40:
every legitimate run fits with headroom under 20%, and a runaway loop stops
within about twice a normal run's cost. Expected to drop as #174/#175/#176
land.
"""

from __future__ import annotations

import contextlib
import os
import threading
from contextvars import ContextVar


#: The hard upper bound on any configured ceiling. There is no unlimited
#: override: a value above this is a refused configuration, not a policy.
R1_MAX_CEILING = 40

#: Default when NB_RUN_TEXT_CALL_BUDGET is unset. See the module docstring
#: for the derivation.
DEFAULT_CEILING = 40


class CallBudgetConfigurationError(RuntimeError):
    """The configured ceiling is not a valid Release 1 value."""


class RunCallBudgetExceededError(RuntimeError):
    """The next text-model call would exceed this run's call budget.

    Raised BEFORE the transport is invoked: the refused call is never paid
    for. This is a cost-safety stop, not an editorial judgment — the run
    fails closed exactly as it would for any other infrastructure failure,
    and no gate downstream of the refusal is skipped, because nothing
    downstream of the refusal runs at all.
    """

    def __init__(self, *, used: int, limit: int) -> None:
        super().__init__(
            f"run text-model call budget exhausted: {used} of {limit} logical "
            "calls used; the next call was refused before any transport "
            "invocation. This bounds runaway spend — see Issue #171."
        )
        self.used = used
        self.limit = limit


def configured_run_call_ceiling() -> int:
    """The run ceiling from ``NB_RUN_TEXT_CALL_BUDGET``, strictly validated.

    Accepts only the canonical decimal representation of an integer in
    [1, R1_MAX_CEILING]. Unset means DEFAULT_CEILING. Anything else —
    zero, negatives, values above the hard maximum, floats, empty strings,
    whitespace, zero-padded or signed forms — is refused before any run
    work begins. Refused, never clamped: silently adjusting a configured
    value is how the NB_OPENAI_MAX_RETRIES=999999 mistake would come back.
    """
    raw = os.environ.get("NB_RUN_TEXT_CALL_BUDGET")
    if raw is None:
        return DEFAULT_CEILING
    if raw.isascii() and raw.isdigit() and str(int(raw)) == raw:
        value = int(raw)
        if 1 <= value <= R1_MAX_CEILING:
            return value
    raise CallBudgetConfigurationError(
        "NB_RUN_TEXT_CALL_BUDGET must be a canonical integer between 1 and "
        f"{R1_MAX_CEILING} for Release 1; got {raw!r}. Refusing to start a "
        "run with an invalid call-budget configuration."
    )


class RunCallBudget:
    """Run-scoped counter of logical text-model calls.

    ``spend()`` is called before each paid call; when the budget is
    exhausted it raises instead of counting. The counter is monotonic for
    the lifetime of one run and is never reused: each run constructs its
    own instance, so "reset" is construction, not mutation.
    """

    def __init__(self, limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise CallBudgetConfigurationError("call budget limit must be an integer")
        if not 1 <= limit <= R1_MAX_CEILING:
            raise CallBudgetConfigurationError(
                f"call budget limit must be between 1 and {R1_MAX_CEILING}; "
                f"got {limit!r}"
            )
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self._used)

    def spend(self) -> None:
        """Consume one logical call, or refuse before any spend occurs."""
        with self._lock:
            if self._used >= self.limit:
                raise RunCallBudgetExceededError(used=self._used, limit=self.limit)
            self._used += 1


_ACTIVE_BUDGET: ContextVar[RunCallBudget | None] = ContextVar(
    "nb_run_call_budget", default=None
)


@contextlib.contextmanager
def activate_call_budget(budget: RunCallBudget):
    """Make ``budget`` the active budget for this context, restoring on exit.

    Restoration happens in ``finally``, so budget state can never leak into
    a subsequent run even when the run raises.
    """
    token = _ACTIVE_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE_BUDGET.reset(token)


def active_call_budget() -> RunCallBudget | None:
    return _ACTIVE_BUDGET.get()


def charge_active_call_budget() -> None:
    """Charge one logical call against the active budget, if any.

    No active budget means no charge: processes that never activate one
    (daily research, the pre-run selector, legacy tools) are bounded by
    their own mechanisms and are out of #171's scope by design.
    """
    budget = _ACTIVE_BUDGET.get()
    if budget is not None:
        budget.spend()
