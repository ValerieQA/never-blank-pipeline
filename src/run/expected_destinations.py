"""Seam 11: the harness's declaration of who is in a barrier round (#351).

``run_barrier`` takes ``expected_destinations`` as a required argument and
refuses any round whose plans do not represent exactly that set, in both
directions and before anything is spent. #305 made it required and said why:
"a barrier that concluded anything from the plans it happened to be shown would
be a barrier a caller can open by passing fewer of them". Nothing supplied it.
This module is that supply.

It declares; it does not decide
-------------------------------
The set is assembled deterministically from lifecycle state already
established upstream — S-07's ``DestinationDecisionSet``, minus the
destinations a recorded ``SKIP`` has since removed — and no editorial judgment
is made here. That is the whole reason the argument exists rather than being
derived inside S-11: eligibility is S-07's answer, skipping is ARP's, and the
harness's job is to state which of them still stand for this round rather than
to re-establish either.

``mode`` is deliberately not consulted. A ``generate_only`` destination is an
eligible destination that today's deployment does not publish (AD-02 §3), and
Principle B keeps it in the run: it gets a plan, it is compared against the
anchor, and it gets a text. A barrier that dropped it would compare a subset
and still report that I-07 held for the unit.

Two refusals, and why both are refusals
---------------------------------------
A ``skipped`` destination that was never eligible is refused rather than
ignored. Ignoring it is harmless to the set and fatal to the bookkeeping: the
one thing a caller uses this function to be sure of is that its own record of
what has been skipped matches S-07's record of what there was, and a mismatch
that produces the right answer today produces a silently short round the next
time the two lists differ for a real reason.

An empty result is refused for the opposite reason. ``run_barrier`` raises on
an empty expected set, so returning one would only move the same failure one
frame later and label it S-11's. Every eligible destination of the unit having
been skipped is not a barrier round with no participants — it is a unit with
nowhere left to go, and the caller owes it a ``SKIP`` of the unit before B1 is
reached at all.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2
(barrier B1) and §3 (S-11); ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md``
AD-02 §3.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.editorial_core.destinations import (
    Destination,
    DestinationDecisionSet,
)


class ExpectedDestinationsError(ValueError):
    """The round's participants cannot honestly be declared."""


def expected_destinations(
    decisions: DestinationDecisionSet,
    *,
    skipped: Iterable[Destination] = (),
) -> frozenset[Destination]:
    """The unit's current non-skipped destinations, for one barrier round.

    ``skipped`` is what the run has recorded a terminal destination-scoped
    outcome for since S-07 decided — a plan check that exhausted ``L_strategy``,
    an adaptation that could not meet a hard constraint, a prior barrier round
    that sent a destination back and found the counter gone. A later round is
    this function called again with the longer ``skipped`` list, and the round
    after that with a longer one still, which is what §0.2's "B1 re-evaluates
    without it" is on the harness's side.
    """

    eligible = frozenset(
        decision.destination for decision in decisions.eligible
    )
    removed = frozenset(skipped)
    strangers = removed - eligible
    if strangers:
        raise ExpectedDestinationsError(
            f"{decisions.unit_id} reports "
            + ", ".join(sorted(item.value for item in strangers))
            + " as skipped, and S-07 made no such destination eligible for "
            "this unit; the round's participants are the harness's to declare, "
            "so a "
            "skip of a destination the unit never had is a record of the run "
            "that has stopped matching the record of the unit"
        )
    remaining = eligible - removed
    if not remaining:
        raise ExpectedDestinationsError(
            f"every eligible destination of {decisions.unit_id} has been "
            "skipped, so there is no barrier round to run. A unit with nowhere "
            "left to go is skipped as a unit before B1 is reached; a round "
            "declared over nobody would be the assumption B1 exists to refuse"
        )
    return remaining
