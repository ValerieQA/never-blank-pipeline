"""S-05 · Editorial Units: one unit, and the split not taken (Issue #302, SL-4).

The stage that decides how many units a signal becomes. Step 2 §1 gives it one
authority — "decide how many units the signal becomes. **With cap = 1 it
creates exactly one unit** and records whether a split would have qualified" —
and AD-03 gives it the cap: "the maximum starts at **1**. With cap = 1, S-05
evaluates rules 1–3 and records a ``split_candidate`` in the run trace, and
nothing else: **no additional unit is created, stored or deferred**".

So this module is two things, and the whole of its contract is that they stay
apart:

1. **one unit.** Exactly one E-10 over the boundary's full admissible set (§1
   Post), written to ``units/<unit_id>/unit.json``. Not "one unit unless the
   rules qualify a split": there is no split execution here to reach, and a
   cap other than 1 is refused rather than obeyed, because the behaviour such a
   number would ask for does not exist to be enabled by a number;
2. **an observation.** Rules 1 and 2 of AD-03, evaluated by code over the
   admissible set and recorded per interpretation pair, with the
   ``split_candidate`` flag they add up to. Rule 3 — standalone viability — is
   **not evaluated**: §1 says so because it needs anchor calls, and the trace
   records ``rule_3: not_evaluated`` rather than a verdict nobody reached.

The flag is the deliverable. "Splitting is observed before it is enabled", and
an observation is only worth having if the thing it observes cannot happen
while it is being observed — which is why the cap, the statuses only a split
can produce and the absent second unit are enforced here rather than left to a
caller's restraint.

**Production safety.** The stage makes no model call and no external call, and
nothing calls the stage: the run harness still executes S-05 as the SL-1
pass-through, and wiring the stages of SL-4 into it is a later slice. So the
shadow requirement is met by there being nothing to switch off — the only thing
that could change what production does is a caller, and this slice adds none.

What is deliberately absent
---------------------------
**A deferred-unit writer.** AD-03 §5 stores every unit but the strongest as
``deferred`` with an expiry, and Step 3 §3.2 gives that record a durable path
outside the 90-day workspace — and then says of it: "**No writer is enabled
while cap = 1**". There is none here, and the two statuses only a split can
produce (``deferred``, and the ``expired`` a deferral ends in) are refused at
construction, so the absence is a property of the type rather than of the code
paths that happen to exist today.

**A clock.** An expiry is "derived from the freshness of its evidence", and
nothing in the editorial core reads the clock (CE-1). Since no unit is
deferred, none needs one.

**``K-UNIT-01``.** The map's tier-3 record behind rules 1–2 is named by §1 and
not loaded: the decider is ``code`` and the stage makes no call (§1, Calls: 0),
so the record stands behind the rules rather than being consulted at run time.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-05);
``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md`` AD-03;
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (E-10);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3,
§3.2 and §3.3; ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §13
walkthrough D.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

# The repository's one path-component validator, reused rather than copied: a
# unit ID reaches a directory name, and two answers to "is this a safe
# component" would eventually be two different answers.
from src.artifacts import _validate_path_component
from src.editorial_core.evidence_core import EvidenceCore
from src.editorial_core.interpretation_boundary import (
    Interpretation,
    InterpretationBoundary,
)
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-05"

#: The entity it is the sole producer of (§1, Outputs).
UNIT_ENTITY_TYPE: Final[str] = "E-10"

#: Where a unit lives inside the run workspace (§2.2). ``units/*/unit.json``
#: belongs to S-05 in the §2.3 ownership table and to nothing else.
UNITS_DIRECTORY: Final[str] = "units"

#: AD-03, initial configuration: "The maximum starts at **1**." It is a
#: configuration value and it is also the only one this stage can honour, so it
#: is named here and checked rather than read and trusted.
SPLIT_CAP: Final[int] = 1


class UnitError(RuntimeError):
    """S-05 was asked to decide something its contract cannot decide."""


# ===========================================================================
# E-10 · Editorial Unit
# ===========================================================================


class UnitStatus(str, Enum):
    """E-10's ``status`` vocabulary (Step 1 §4).

    All five, because the vocabulary belongs to the entity and not to this
    stage — S-06 skips a unit, S-14 completes one — and two of them are
    unreachable while the cap is 1. ``deferred`` is what AD-03 §5 does with
    every unit of a split but the strongest, and ``expired`` is where a
    deferred unit ends. A signal that becomes one unit defers nothing, so
    nothing of it can expire either.
    """

    ACTIVE = "active"
    DEFERRED = "deferred"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    EXPIRED = "expired"


#: The two statuses only a split can produce. Refused by :class:`EditorialUnit`
#: while the cap is 1: Step 3 §3.2 enables no writer for a deferred unit, and a
#: status whose record nothing may write is not a weaker state — it is a unit
#: the engine believes it stored and did not.
_SPLIT_ONLY_STATUSES: Final[frozenset[UnitStatus]] = frozenset(
    {UnitStatus.DEFERRED, UnitStatus.EXPIRED}
)


class SplitRuleResult(str, Enum):
    """What one of AD-03's three rules made of this signal.

    Three values and not a boolean, for the reason §1 states rule 3 with:
    "the trace records ``rule_3: not_evaluated``". A rule that found nothing
    and a rule nobody evaluated are different facts, and the observation this
    stage exists to collect is worthless if the second can be read as the
    first.
    """

    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True, slots=True)
class InterpretationPair:
    """Two admissible interpretations, and what rules 1 and 2 made of them.

    Both facts are recorded for every pair, so the trace answers "which
    interpretation pairs qualified" (§1, Trace) and also why the others did
    not.
    """

    first: str
    second: str
    #: Rule 1: neither is a premise, consequence or restatement of the other.
    independent: bool
    #: Rule 2: each rests on at least one evidence claim the other does not
    #: use.
    separate_support: bool

    def __post_init__(self) -> None:
        if not self.first.strip() or not self.second.strip():
            raise UnitError("a pair is named by both the interpretations in it")
        if self.first == self.second:
            raise UnitError(
                f"{self.first} is paired with itself; rule 1 is a test on two "
                "readings, and no reading is independent of itself"
            )

    @property
    def qualified(self) -> bool:
        """Would these two have become two units, but for the cap?"""

        return self.independent and self.separate_support

    def as_entity(self) -> dict[str, Any]:
        return {
            "interpretation_refs": [self.first, self.second],
            "independent": self.independent,
            "separate_support": self.separate_support,
            "qualified": self.qualified,
        }


@dataclass(frozen=True, slots=True)
class SplitRecord:
    """E-10's ``split``: what the rules found, and what the cap did with it.

    Every result is **derived** from the pairs rather than stored beside them,
    so the flag and the reasons for it cannot disagree — the same reason E-09
    derives its two lists from its members instead of keeping them. Step 1's
    field list is honoured by what is here and by what is not: "with cap = 1
    (current), only the flag and the rule results are written; no sibling unit
    exists", so there are no sibling unit IDs to carry.
    """

    #: The configured maximum this record was produced under, so that a reader
    #: of the observation knows which configuration produced it.
    cap: int = SPLIT_CAP
    #: Every pair of admissible interpretations. Empty when the boundary admits
    #: fewer than two — which is rule 1 failing its first condition, not a rule
    #: that went unevaluated.
    pairs: tuple[InterpretationPair, ...] = ()

    def __post_init__(self) -> None:
        if self.cap != SPLIT_CAP:
            raise UnitError(
                f"a split record was produced under cap {self.cap}; AD-03 "
                f"starts the maximum at {SPLIT_CAP} and this engine implements "
                "no split execution, so a record claiming another cap describes "
                "behaviour that does not exist"
            )
        evaluated = {frozenset((pair.first, pair.second)) for pair in self.pairs}
        if len(evaluated) != len(self.pairs):
            raise UnitError(
                "one interpretation pair is recorded twice; each pair is "
                "evaluated once, and an observation counted over repeats is "
                "not the rate it claims to be"
            )

    @property
    def qualifying_pairs(self) -> tuple[InterpretationPair, ...]:
        """The pairs that passed both evaluated rules (§1, Trace)."""

        return tuple(pair for pair in self.pairs if pair.qualified)

    @property
    def rule_1(self) -> SplitRuleResult:
        """Independence: at least two admissible readings, neither resting on
        the other."""

        if any(pair.independent for pair in self.pairs):
            return SplitRuleResult.QUALIFIED
        return SplitRuleResult.NOT_QUALIFIED

    @property
    def rule_2(self) -> SplitRuleResult:
        """Separate support, read over the pairs rule 1 admitted.

        AD-03 states the rules as conditions that must **all** hold of the same
        two readings, so rule 2 is asked about an independent pair and about
        nothing else. When rule 1 admitted no pair there was nothing to ask it
        about, and that is ``not_evaluated``: the pairs still record what their
        supports look like, and none of them is a candidate anchor.
        """

        independent = [pair for pair in self.pairs if pair.independent]
        if not independent:
            return SplitRuleResult.NOT_EVALUATED
        if any(pair.separate_support for pair in independent):
            return SplitRuleResult.QUALIFIED
        return SplitRuleResult.NOT_QUALIFIED

    @property
    def rule_3(self) -> SplitRuleResult:
        """Standalone viability: **not evaluated** at cap = 1 (§1, Decider).

        A property returning one value rather than a field, because the value
        is not a result this stage could reach differently: the rule "needs
        anchor calls", S-05 makes none (§1, Calls: 0), and a stage that wrote a
        verdict here would be recording an answer to a question it never asked.
        """

        return SplitRuleResult.NOT_EVALUATED

    @property
    def split_candidate(self) -> bool:
        """The AD-03 observation: a signal that would have become two units.

        True exactly when some pair passed both evaluated rules — which is the
        same thing as rule 1 and rule 2 both qualifying, because rule 2 reads
        only the pairs rule 1 admitted.
        """

        return bool(self.qualifying_pairs)

    def as_entity(self) -> dict[str, Any]:
        return {
            "cap": self.cap,
            "split_candidate": self.split_candidate,
            "rule_1": self.rule_1.value,
            "rule_2": self.rule_2.value,
            "rule_3": self.rule_3.value,
            "pairs": [pair.as_entity() for pair in self.pairs],
        }


@dataclass(frozen=True, slots=True)
class EditorialUnit:
    """``E-10``: one story with one anchor (Step 1 §4).

    Two of E-10's fields are absent rather than present and empty, each by its
    own rule in Step 1's table. ``anchor_ref`` is required "after S-06", and
    this file is written once (§3, "Written once"), so the anchor is recorded
    in E-11 where S-06 writes it. ``expires_at`` is required "if deferred", and
    no unit here is deferred — a stored expiry of ``null`` is exactly the shape
    a later reader would take for "this one never expires".
    """

    unit_id: str
    signal_ids: tuple[str, ...]
    #: ``(core_id, version)``: the final core the boundary was built over.
    core_ref: tuple[str, int]
    #: ``(boundary_id, version)``: the exact E-09 snapshot the scope is taken
    #: from, so that a later invalidation is a comparison and not a guess
    #: (patch R2, boundary commit rule 6).
    boundary_ref: tuple[str, int]
    #: The admissible interpretation IDs this unit may use, as of the E-09
    #: version above. IDs and not (ID, version) pairs, because the scope names
    #: readings and does not judge them: whether one is still admissible is the
    #: newest boundary version's answer, and a re-entry that refuses a reading
    #: does not leave this list able to permit it (patch R2, F-4).
    interpretation_scope: tuple[str, ...]
    split: SplitRecord
    status: UnitStatus = UnitStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.unit_id.strip():
            raise UnitError("a unit is identified by its unit ID")
        if not self.signal_ids:
            raise UnitError(
                f"{self.unit_id} names no signal; AD-04 makes the reference a "
                "list of at least one, never an empty one"
            )
        if not self.interpretation_scope:
            raise UnitError(
                f"{self.unit_id} has an empty interpretation scope; §1 Post "
                "gives the unit the full admissible set, and a unit allowed to "
                "use no reading of its own boundary is not a unit"
            )
        scope = self.interpretation_scope
        duplicated = sorted({key for key in scope if scope.count(key) > 1})
        if duplicated:
            raise UnitError(
                f"{self.unit_id} lists {', '.join(duplicated)} twice in its "
                "interpretation scope; the scope is a set of the boundary's "
                "admissible readings, and one reading enters it once"
            )
        if self.status in _SPLIT_ONLY_STATUSES:
            raise UnitError(
                f"{self.unit_id} is recorded as {self.status.value}; only a "
                "split produces that status, no split executes while the cap "
                f"is {SPLIT_CAP} (AD-03), and Step 3 §3.2 enables no writer for "
                "a deferred unit — so nothing could make this one durable"
            )

    def as_entity(self) -> dict[str, Any]:
        """The E-10 body, written to ``units/<unit_id>/unit.json`` (§2.2)."""

        return {
            "entity_type": UNIT_ENTITY_TYPE,
            "entity_id": self.unit_id,
            "unit_id": self.unit_id,
            "signal_ids": list(self.signal_ids),
            "core_ref": {"core_id": self.core_ref[0], "version": self.core_ref[1]},
            "boundary_ref": {
                "boundary_id": self.boundary_ref[0],
                "version": self.boundary_ref[1],
            },
            "interpretation_scope": list(self.interpretation_scope),
            "status": self.status.value,
            "split": self.split.as_entity(),
        }


# ===========================================================================
# Identity and storage
# ===========================================================================


def unit_id(core_id: str) -> str:
    """The ``unit`` ID of the one unit over one core.

    Derived from the core rather than counted: at cap = 1 a signal becomes
    exactly one unit, and a second execution over the same core must name the
    same unit rather than a new one — the workspace writes each path once (P1),
    and an ID that counted executions would turn a repeat into a second unit.
    """

    return f"unit-{core_id}"


def unit_relative_path(identity: str) -> str:
    """``units/<unit_id>/unit.json`` (§2.2)."""

    _validate_path_component(identity, "unit_id")
    return f"{UNITS_DIRECTORY}/{identity}/unit.json"


def write_unit(workspace: RunWorkspace, unit: EditorialUnit) -> EntityIndexEntry:
    """Write the unit into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once and
    §2.3 write ownership hold: the path belongs to S-05 and to nothing else,
    and a second write of the same unit is refused rather than quietly
    replacing the first. The name carries no version because E-10 is written
    once (§3).

    It is also the **only** writer in this module. The durable deferred-unit
    record §3.2 describes — ``data/editorial/units/<client>/<unit_id>.json`` —
    has none anywhere in the engine, because "No writer is enabled while
    cap = 1", and a unit written here lives and dies with its 90-day run
    workspace.
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=unit_relative_path(unit.unit_id),
        entity_type=UNIT_ENTITY_TYPE,
        entity_id=unit.unit_id,
        payload=unit.as_entity(),
    )


# ===========================================================================
# The stage
# ===========================================================================


def create_unit(
    *,
    core: EvidenceCore,
    boundary: InterpretationBoundary,
    cap: int = SPLIT_CAP,
) -> EditorialUnit:
    """The signal becomes one unit, and the rules say whether it looked like two.

    Returns the unit, and has no return shape for a second one: "exactly one
    unit" is not a count this stage arrives at and could arrive at differently
    — it is what the signature can express. Nothing here fails, which is what
    §1's ARP column means by "cannot fail once S-04 passed", so the stage
    records no outcome; what it cannot do is run out of contract, and a
    precondition the caller broke raises rather than producing a unit over a
    boundary that does not answer for it.
    """

    signal_id = core.signal_ids[0]
    if cap != SPLIT_CAP:
        raise UnitError(
            f"{signal_id} reached {STAGE} with a split cap of {cap}; AD-03 "
            "starts the maximum at 1 and says that raising it is 'a "
            "configuration change plus an explicit decision', so a cap this "
            "engine has no split execution for is refused rather than obeyed"
        )
    if boundary.core_ref != (core.core_id, core.version):
        raise UnitError(
            f"{signal_id} reached {STAGE} with a boundary over "
            f"{boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); a unit states both refs, and "
            "two that do not describe the same material cannot both be right"
        )
    admissible = boundary.admissible
    if not admissible:
        raise UnitError(
            f"{signal_id} reached {STAGE} with a boundary admitting no "
            "interpretation; §1 Pre asks for at least one, and S-04 ends a "
            "boundary with none in a SKIP that never reaches this stage"
        )

    scope = tuple(member.interpretation_id for member in admissible)
    return EditorialUnit(
        unit_id=unit_id(core.core_id),
        signal_ids=core.signal_ids,
        core_ref=(core.core_id, core.version),
        boundary_ref=(boundary.boundary_id, boundary.version),
        interpretation_scope=scope,
        split=SplitRecord(cap=cap, pairs=_pairs(boundary)),
    )


def run_split_candidate(units: Sequence[EditorialUnit]) -> bool:
    """The flag one run's RunSummary carries (Step 3 §3.3).

    The summary holds one flag and a run may hold several units, so the run's
    flag is true when any unit of it would have split. A run that created no
    unit observed no signal that looked like two stories, which is false rather
    than unknown: the flag counts signals that reached S-05 and qualified, and
    a signal that never reached it is not one of them.
    """

    return any(unit.split.split_candidate for unit in units)


# ===========================================================================
# Rules 1 and 2 (AD-03), by code
# ===========================================================================


def _pairs(boundary: InterpretationBoundary) -> tuple[InterpretationPair, ...]:
    """Both evaluated rules over every pair of admissible interpretations.

    Every pair, and not only the first that qualifies: the observation is a
    rate, and "which interpretation pairs qualified" is a trace row per pair
    (§1, Trace).
    """

    admissible = boundary.admissible
    rests_on = _rests_on(boundary.members)
    listed = frozenset(member.interpretation_id for member in boundary.members)
    return tuple(
        InterpretationPair(
            first=first.interpretation_id,
            second=second.interpretation_id,
            independent=_independent(first, second, rests_on=rests_on, listed=listed),
            separate_support=_separately_supported(first, second),
        )
        for index, first in enumerate(admissible)
        for second in admissible[index + 1 :]
    )


def _rests_on(members: Sequence[Interpretation]) -> Mapping[str, frozenset[str]]:
    """What each interpretation rests on, directly or along a chain.

    Rule 1 asks that neither reading is "a premise, consequence or restatement
    of the other", and a premise of a premise is still a premise: a reading
    resting on B, which rests on A, is not independent of A, and comparing only
    the ``depends_on`` lists would call it so. The walk covers every member,
    admissible or not — a chain through a refused reading is still a chain —
    and it terminates because each step adds an ID to a finite set.
    """

    direct = {item.interpretation_id: tuple(item.depends_on) for item in members}
    closure: dict[str, frozenset[str]] = {}
    for identity, refs in direct.items():
        reached: set[str] = set()
        frontier = list(refs)
        while frontier:
            ref = frontier.pop()
            if ref in reached:
                continue
            reached.add(ref)
            frontier.extend(direct.get(ref, ()))
        closure[identity] = frozenset(reached)
    return closure


def _independent(
    first: Interpretation,
    second: Interpretation,
    *,
    rests_on: Mapping[str, frozenset[str]],
    listed: frozenset[str],
) -> bool:
    """Rule 1, over the dependency graph the boundary states.

    Fails closed on a dependency the boundary does not list: S-04's reference
    rule refuses a reading whose ``depends_on`` names something the boundary
    does not hold, so such a reference arriving here means the boundary did not
    come through it — and a premise no reader can resolve is not evidence that
    two readings stand apart.
    """

    for member in (first, second):
        if any(ref not in listed for ref in rests_on[member.interpretation_id]):
            return False
    return (
        second.interpretation_id not in rests_on[first.interpretation_id]
        and first.interpretation_id not in rests_on[second.interpretation_id]
    )


def _separately_supported(first: Interpretation, second: Interpretation) -> bool:
    """Rule 2: "each candidate anchor rests on at least one evidence claim that
    the other does not use".

    Both ways round, and not one: where one reading's supports are a subset of
    the other's, the pair holds a unit that can say nothing the other unit
    could not have said with the same evidence.
    """

    supports_first = set(first.support_refs)
    supports_second = set(second.support_refs)
    return bool(supports_first - supports_second) and bool(
        supports_second - supports_first
    )
