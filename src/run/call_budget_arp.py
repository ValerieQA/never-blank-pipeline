"""Budget exhaustion as ARP outcomes: the R-3 wrap (Issue #292, slice SL-1).

``RunCallBudget`` (#171) bounds what one run may spend and refuses the call
that would exceed it **before** the transport is invoked. The refused call is
never paid for, and that property is not negotiable — it is the only thing that
stopped the last runaway.

What the target changes is what happens *after* the refusal. The current engine
raises and fails the run closed, which throws away work that is already paid
for and already accepted. Step 2 §0.4 keeps the refusal and turns the stop into
ARP outcomes (refinement R-3):

1. the call that would exceed the budget is not made;
2. the unit of work that needed it ends in ``SKIP`` with state
   ``budget_exhausted`` — the destination when the call was destination-scoped,
   otherwise the unit or the signal;
3. destinations not yet started end in ``SKIP`` (``budget_exhausted``), in
   **reverse** destination order (§0.2), so that under a tight budget the
   destinations processed first — the ones others link to, and the ones that
   are actually published — are the last to be given up;
4. texts already accepted at S-13 continue to S-14, which makes no model calls.

This module is that wrap and nothing more. It does not touch
``RunCallBudget``: the current engine keeps failing closed exactly as it does
today, because the shadow canonical engine is the only caller here and
production behaviour must not change under it.

**Destination order is an input, not a judgment.** §0.2 derives it from the
Client Contract's ``publication_dependencies`` and its listed order, which live
in the E-12 destination decisions S-07 produces — a later slice. The wrap
consumes the order it is handed and reverses it; it never invents one, and it
refuses a list that names a destination twice, because "reverse order" of an
ambiguous list is not an order at all.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2, §0.4
and §7 (R-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.editorial_core.arp import (
    RUN_CALL_BUDGET_COUNTER,
    ArpOutcome,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.run.call_budget import RunCallBudget, RunCallBudgetExceededError


class ArpCallBudgetError(RuntimeError):
    """The wrap was asked for an answer its contract does not have."""


class DestinationState(str, Enum):
    """How far one destination of a unit got before the budget ran out.

    Only the three states §0.4 distinguishes. ``IN_PROGRESS`` is neither
    skipped nor preserved by the exhaustion rule: a destination that is mid-way
    through planning or writing will ask for its next call and be refused
    there, with the ``SKIP`` recorded against the scope that asked.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    TEXT_ACCEPTED = "text_accepted"


class DestinationProgress(BaseModel):
    """One destination of the unit, and how far it got."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    destination: str = Field(min_length=1)
    state: DestinationState


class ArpCallBudget:
    """``RunCallBudget``, refusing before it pays and reporting a ``SKIP``.

    One instance per run, wrapping that run's budget. It owns no counter of its
    own: ``used`` and ``limit`` are the wrapped budget's, so a stage that spends
    through the wrap and one that spends through the budget directly are
    counted once each and against the same ceiling.
    """

    def __init__(self, budget: RunCallBudget) -> None:
        if not isinstance(budget, RunCallBudget):
            raise ArpCallBudgetError(
                "the wrap needs the run's own RunCallBudget; got "
                f"{type(budget).__name__}"
            )
        self._budget = budget

    @property
    def used(self) -> int:
        return self._budget.used

    @property
    def limit(self) -> int:
        return self._budget.limit

    @property
    def remaining(self) -> int:
        return self._budget.remaining

    @property
    def exhausted(self) -> bool:
        """Is there nothing left to spend?"""

        return self._budget.remaining <= 0

    def spend(self, *, scope: OutcomeScope, scope_key: str) -> Optional[OutcomeRecord]:
        """Charge one model call, or refuse it and say what that costs.

        ``None`` means the call is paid for and may be made. An OutcomeRecord
        means the call was **not** made and is the ``SKIP`` of the unit of work
        that needed it: the caller records it and stops that work, rather than
        catching an error and deciding for itself what to abandon.
        """

        try:
            self._budget.spend()
        except RunCallBudgetExceededError:
            return self._skip(scope, scope_key)
        return None

    def exhaustion_outcomes(
        self, progress: Sequence[DestinationProgress]
    ) -> tuple[OutcomeRecord, ...]:
        """The ``SKIP`` of every destination that was never started (§0.4.3).

        In reverse destination order, and only for the destinations that had not
        started: one that holds an accepted text keeps it (§0.4.4), and one
        mid-flight is skipped where its next call is refused, by
        :meth:`spend`. Each outcome names its destination as its scope key,
        because these are the one case where a stage records outcomes for
        scopes other than the one it is executing.

        Asking this while calls remain is refused. Skipping a destination the
        budget could still have served would be this wrap causing the loss it
        exists to limit.
        """

        if not self.exhausted:
            raise ArpCallBudgetError(
                f"the budget has {self.remaining} of {self.limit} calls left, "
                "so nothing is skipped for exhaustion yet; a destination the "
                "run can still serve is not the wrap's to give up"
            )
        return tuple(
            self._skip(OutcomeScope.DESTINATION, entry.destination)
            for entry in reversed(_ordered(progress))
            if entry.state is DestinationState.NOT_STARTED
        )

    @staticmethod
    def preserved_destinations(
        progress: Sequence[DestinationProgress],
    ) -> tuple[str, ...]:
        """The destinations whose accepted texts continue to S-14 (§0.4.4).

        In destination order, because that is the order publication needs
        (§0.2). They are preserved by having no outcome at all: an accepted text
        is finished editorial work, and the budget running out afterwards is not
        a reason to throw it away.
        """

        return tuple(
            entry.destination
            for entry in _ordered(progress)
            if entry.state is DestinationState.TEXT_ACCEPTED
        )

    def _skip(self, scope: OutcomeScope, scope_key: str) -> OutcomeRecord:
        return OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.BUDGET_EXHAUSTED,
            scope=scope,
            scope_key=scope_key,
            reason=(
                "the next model call would have exceeded the run's budget of "
                f"{self.limit} calls; it was refused before any transport "
                "invocation"
            ),
            counter=RUN_CALL_BUDGET_COUNTER,
            attempt=self.used,
            limit=self.limit,
        )


def _ordered(
    progress: Sequence[DestinationProgress],
) -> tuple[DestinationProgress, ...]:
    """The destinations as handed over, once each."""

    entries = tuple(progress)
    names = [entry.destination for entry in entries]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ArpCallBudgetError(
            "destination progress names "
            + ", ".join(duplicated)
            + " more than once; each destination of the unit has one state, and "
            "the order this list carries is the destination order (§0.2)"
        )
    return entries
