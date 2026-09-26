"""S-11 · Plan check and exemplars: every check before any prose.

The stage that decides whether a draft plan may become a text. Step 2 §3 gives
it the checks and forbids it the repair: "check each plan before any prose
(V-P01, V-P02, V-P04, V-P05), then check the unit's plans together (V-P03,
barrier B1). Select exemplars. **It must not repair plans**."

Two scopes in one stage
-----------------------
:func:`check_plan` is the per-destination half: four checks, at most one model
call, and — when every hard one passes — the approved version of the plan, with
its exemplars. :func:`run_barrier` is the unit half: V-P03 at barrier B1, one
call per round, comparing the unit's plans against the anchor and against each
other. B1 is declared in the topology registry, evaluated here and blocking
S-12, so "no text is written before B1 passes" is a property of the graph and
not a promise this module makes.

A failure names the destination that deviated, and only that one goes back:
"V-P03 failure → ``REPLAN`` → S-08 **only for the destination(s) that deviated**
from the anchor; the others keep their approval."

A check that did not run is not a check that passed
---------------------------------------------------
:class:`CheckOutcome` has three members and not two. A hard check whose model
half could not be made or could not be read is ``not_answered``, which is never
read as a pass: a verdict is ``pass`` only where every hard check is ``pass``,
and a plan whose checks nobody ran ends the destination with
``plan_check_unavailable`` rather than proceeding on a comparison nobody made.
The same rule runs the other way for I-12: a soft check can neither fail nor
carry a route, so V-P05 is a hint and is structurally incapable of becoming a
threshold.

The Reference Library is the one input that may be missing
----------------------------------------------------------
§3 lists it among the Inputs and it is the only one an execution can do
without: exemplars are material the plan carries to the Writer (I-11), not
authority a check rests on. An absent library therefore approves the plan
without examples and records ``reference_library_unavailable`` as a
``DEGRADE``, while a library that was read and holds nothing for this
destination and format records nothing at all. The two are different facts, and
only one of them is a run executing on less than it was configured with.

A verdict keeps no authority a commit has taken away
----------------------------------------------------
PlanVerdict records ``boundary_ref`` — the E-09 version the plan was checked
against — which is defect F-4's fix: "the S-12 precondition requires it to equal
the current version. On a new boundary version, S-11's code checks (V-P02,
chain) re-run on every approved plan of the unit (0 model calls)".
:func:`approval_holds` is that precondition, and
:func:`recheck_after_boundary_commit` is that re-run. An approval made against
an older boundary does not carry forward; it is re-established or it is gone.

Sealed, not reopened
--------------------
Approval produces a **new** version of the plan (``v2``, ``approved``,
superseding the draft). Nothing here mutates a draft, a verdict or an approved
plan: every record is frozen, every re-check writes a new verdict version, and a
destination the barrier sends back re-enters at S-08 with a plan ID of its own.
There is no public path that turns an approved plan back into a draft.

**Production safety.** At most one model call per destination per plan version
and one per unit per barrier round, no external call, and nothing calls this
stage: the run harness still executes S-11 as the SL-1 pass-through, and wiring
the stages of SL-5 into it is a later slice.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2
(barrier B1), §3 (S-11), §5.3 and §5.4 (F-4);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (PlanVerdict,
CheckResult, fix F-2) and §6 (I-04, I-05, I-06, I-07, I-12);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3;
``knowledge/checks/V-P01.md`` … ``V-P05.md``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.artifacts import _validate_path_component
from src.editorial_core.anchor import Anchor
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    KnowledgeStatus,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.candidate_strategies import EditorialStrategy, RevealKind
from src.editorial_core.destinations import (
    DESTINATIONS_DIRECTORY,
    Destination,
    destination_scope_key,
)
from src.editorial_core.editorial_units import UNITS_DIRECTORY
from src.editorial_core.evidence_core import EvidenceCore
from src.editorial_core.executable_plan import (
    AdaptationContract,
    DestinationRules,
    Exemplar,
    ExecutablePlan,
    ForbiddenKind,
    PlanFormat,
    PlanStage,
    PlatformRule,
    uncarried_moves,
    write_plan,
)
from src.editorial_core.interpretation_boundary import InterpretationBoundary
from src.editorial_core.signal_selection import CallBudget
from src.editorial_core.strategy_selection import promised_points
from src.knowledge.loader import KnowledgeBase, LoadedCheck
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace
from src.strategy.reference_library import ReferenceLibrary

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-11"

#: What it is the sole producer of (§3, Outputs). Not an E-number: Step 1 §4
#: gives PlanVerdict its own name beside E-14, exactly as fix F-2 asks.
VERDICT_ENTITY_TYPE: Final[str] = "PlanVerdict"

#: The unit-scope record of one barrier round (§2.2, ``b1/round_<k>.json``).
BARRIER_ENTITY_TYPE: Final[str] = "B1Round"

#: Where the two live inside the run workspace (§2.2).
VERDICTS_DIRECTORY: Final[str] = "verdicts"
BARRIER_DIRECTORY: Final[str] = "b1"

#: The barrier this stage evaluates, as the topology registry names it.
BARRIER_ID: Final[str] = "B1"

#: The counter both routes spend (§0.3).
STRATEGY_COUNTER: Final[str] = "L_strategy"

#: The two routes, as the topology registry declares them.
CHECK_FAILED_CAUSE: Final[str] = "plan_check_failed"
DEVIATION_CAUSE: Final[str] = "plan_deviates_from_the_unit"

#: The checks of one plan, in the order they are applied and recorded. V-P03 is
#: absent: it is the unit's, at the barrier, and a per-destination verdict that
#: claimed it would be one destination answering for its siblings.
PLAN_CHECKS: Final[tuple[str, ...]] = ("V-P01", "V-P02", "V-P04", "V-P05")

#: The unit check, at barrier B1.
BARRIER_CHECK: Final[str] = "V-P03"

#: Every check record S-11 needs loaded before it may approve anything.
REQUIRED_CHECKS: Final[tuple[str, ...]] = (*PLAN_CHECKS, BARRIER_CHECK)

#: Which state code each failing hard check is recorded under. V-P02 keeps the
#: map §6.2 row written for it — "the plan's promise is wider than the boundary
#: (e.g. '3 things' with two interpretations)" — because the skip rate is read
#: by reason, and folding it into a general plan failure would lose the one
#: reason the map named. V-P01 and V-P04 have no row of their own and share the
#: state Step 2 §5.3 gives their route.
_CHECK_STATES: Mapping[str, StateCode] = {
    "V-P01": StateCode.PLAN_CHECK_FAILED,
    "V-P02": StateCode.PROMISE_WIDER_THAN_BOUNDARY,
    "V-P04": StateCode.PLAN_CHECK_FAILED,
}


class PlanCheckError(RuntimeError):
    """S-11 was asked to decide something its contract cannot decide."""


# ===========================================================================
# CheckResult (Step 1 §4, shared with TextVerdict)
# ===========================================================================


class CheckClass(str, Enum):
    """A check record's ``class`` (Step 4 §3): hard, or soft."""

    HARD = "H"
    SOFT = "S"


class CheckMethod(str, Enum):
    """How a check was answered (Step 4 §3, and Step 1's CheckResult).

    Recorded as the method the run actually used, not as the method the record
    declares: a ``code+model`` check whose model half was never asked is not a
    ``code+model`` answer, and a trace that said it was would hide the one fact
    a reader of a re-check needs.
    """

    CODE = "code"
    MODEL_EXPLICIT_CRITERION = "model-explicit-criterion"
    CODE_AND_MODEL = "code+model"


class CheckOutcome(str, Enum):
    """What a check found. Three members, and the third is the point.

    ``not_answered`` is a check that did not run or whose answer could not be
    read. It is neither a pass nor a fail, and it is never read as the first:
    every place that asks "did this pass" asks for ``PASS`` by name.
    """

    PASS = "pass"
    FAIL = "fail"
    NOT_ANSWERED = "not_answered"


class VerdictResult(str, Enum):
    """PlanVerdict's ``result``: "``pass`` / ``fail``" (Step 1 §4)."""

    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a check found, with the references that show it.

    ``rule_ref`` and ``tier`` are present where a rule made the finding — every
    V-P04 finding has both, because the tier decides the route — and absent
    where the check is the run's own records disagreeing with each other.
    """

    detail: str
    refs: tuple[str, ...] = ()
    rule_ref: Optional[str] = None
    tier: Optional[KnowledgeTier] = None

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise PlanCheckError(
                "a finding says what was found; §3's Trace column asks for every "
                "CheckResult with its rule status, and one with no detail "
                "records that something happened and nothing else"
            )
        if (self.tier is not None) and self.rule_ref is None:
            raise PlanCheckError(
                f"a finding records tier {self.tier.value} and names no rule; the "
                "tier belongs to whoever wrote the rule, and a tier without one "
                "is authority from nowhere"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "refs": list(self.refs),
            "rule_ref": self.rule_ref,
            "tier": None if self.tier is None else self.tier.value,
        }


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One check, as it was run (Step 1 §4, shared by PlanVerdict/TextVerdict).

    "Check ID; rule status and class at the time of the run; method (code /
    model against an explicit criterion); pass / fail; findings with references;
    route taken." The status and class are the record's as the loader read it,
    which is what makes a verdict readable a year later: a check that was a
    candidate when it ran did not become an invariant because somebody approved
    it afterwards.
    """

    check_id: str
    check_class: CheckClass
    rule_status: KnowledgeStatus
    method: CheckMethod
    result: CheckOutcome
    findings: tuple[Finding, ...] = ()
    #: The route the finding took, by the cause the topology declares. Only a
    #: failing hard check takes one.
    route: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise PlanCheckError("a check result names the check it is the result of")
        if self.result is not CheckOutcome.PASS and not self.findings:
            raise PlanCheckError(
                f"{self.check_id} is recorded as {self.result.value} with no "
                "finding; a failure and a question nobody answered are both "
                "things a reader has to be told the shape of"
            )
        if (
            self.check_class is CheckClass.HARD
            and self.result is CheckOutcome.PASS
            and self.findings
        ):
            raise PlanCheckError(
                f"{self.check_id} is a hard check recorded as passing with "
                f"{len(self.findings)} finding(s); a hard check that found "
                "something did not pass, and recording both is how a finding "
                "stops routing anywhere"
            )
        if self.check_class is CheckClass.SOFT:
            self._soft_signal_is_only_a_signal()
            return
        if self.route is not None and self.result is not CheckOutcome.FAIL:
            raise PlanCheckError(
                f"{self.check_id} is {self.result.value} and records route "
                f"{self.route!r}; a route is taken by a finding, and a check "
                "that found nothing — or was never answered — took none"
            )

    def _soft_signal_is_only_a_signal(self) -> None:
        """I-12, as a shape: a soft check cannot block and cannot route."""

        if self.result is CheckOutcome.FAIL:
            raise PlanCheckError(
                f"{self.check_id} is a soft check recorded as a failure; map §9.1 "
                "makes a soft signal 'a soft signal only, recorded, never blocks' "
                "(I-12), and a soft check that can fail is a threshold nobody "
                "approved"
            )
        if self.route is not None:
            raise PlanCheckError(
                f"{self.check_id} is a soft check recording route {self.route!r}; "
                "a signal that routes is a rule, and I-12 keeps the two apart"
            )

    @property
    def passed(self) -> bool:
        """Did this check pass? ``not_answered`` is not a pass."""

        return self.result is CheckOutcome.PASS

    @property
    def blocks(self) -> bool:
        """Does this result stop a plan being approved?

        Every hard result that is not a pass. A soft check never blocks, which
        is not a decision taken here — :meth:`_soft_signal_is_only_a_signal`
        already refuses to build one that could.
        """

        return self.check_class is CheckClass.HARD and not self.passed

    def as_entity(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "class": self.check_class.value,
            "rule_status": self.rule_status.value,
            "method": self.method.value,
            "result": self.result.value,
            "findings": [item.as_entity() for item in self.findings],
            "route": self.route,
        }


# ===========================================================================
# The I-04 chain (§3, Invariants)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One reading of the plan's thesis, resolved down to its observations."""

    interpretation_ref: str
    evidence_claim_refs: tuple[str, ...]
    observation_refs: tuple[str, ...]

    def as_entity(self) -> dict[str, Any]:
        return {
            "interpretation_ref": self.interpretation_ref,
            "evidence_claim_refs": list(self.evidence_claim_refs),
            "observation_refs": list(self.observation_refs),
        }


@dataclass(frozen=True, slots=True)
class PlanChain:
    """I-04 resolved for one plan: thesis → interpretations → claims → observations.

    Recorded on the verdict rather than recomputed by a reader, because "each
    approved plan has a resolvable chain" is the thing SL-5 has to be able to
    show. A chain that only ever existed as a boolean would leave a client
    reading the trace with the check's opinion and none of its working.
    """

    thesis_ref: str
    links: tuple[ChainLink, ...]

    def __post_init__(self) -> None:
        if not self.links:
            raise PlanCheckError(
                f"the chain of {self.thesis_ref} has no link; I-04 runs thesis → "
                "interpretations → evidence claims → observations, and a thesis "
                "resting on no reading is where it breaks"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "thesis_ref": self.thesis_ref,
            "links": [link.as_entity() for link in self.links],
        }


def resolve_chain(
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
) -> tuple[Optional[PlanChain], tuple[Finding, ...]]:
    """Resolve I-04 for one plan's strategy, against the records in front of S-11.

    Every reading the thesis rests on must be admissible in **this** boundary
    version, rest on at least one usable evidence claim of **this** core, and
    each of those claims must resolve to at least one observation the core
    holds. A chain that resolves is returned; a chain that does not is returned
    as ``None`` with the findings that say where it broke, and the plan is not
    approved.
    """

    claims = {claim.evidence_claim_id: claim for claim in core.usable_claims}
    observations = {item.observation_id for item in core.observations}
    findings: list[Finding] = []
    links: list[ChainLink] = []
    for identity in strategy.interpretation_refs:
        member = boundary.member(identity)
        if member is None or not member.admissible:
            findings.append(
                Finding(
                    detail=(
                        f"the thesis rests on {identity}, which boundary version "
                        f"{boundary.version} does not admit; the chain I-04 asks "
                        "for starts at a reading this run still holds"
                    ),
                    refs=(identity,),
                )
            )
            continue
        supporting = tuple(
            ref for ref in member.support_refs if ref in claims
        )
        if not supporting:
            findings.append(
                Finding(
                    detail=(
                        f"{identity} rests on no usable evidence claim of core "
                        f"version {core.version}; the middle link of I-04 is the "
                        "claim, and a reading with none is an assertion"
                    ),
                    refs=(identity,),
                )
            )
            continue
        observed = tuple(
            dict.fromkeys(
                ref
                for claim in supporting
                for ref in claims[claim].observation_refs
                if ref in observations
            )
        )
        if not observed:
            findings.append(
                Finding(
                    detail=(
                        f"the claims under {identity} resolve to no observation "
                        "this core holds; I-04 ends at the observation, and a "
                        "claim that reaches none is where a text stops being "
                        "checkable"
                    ),
                    refs=supporting,
                )
            )
            continue
        links.append(
            ChainLink(
                interpretation_ref=identity,
                evidence_claim_refs=supporting,
                observation_refs=observed,
            )
        )
    if findings or not links:
        return None, tuple(findings) or (
            Finding(
                detail=(
                    f"{strategy.strategy_id} resolves to no chain at all; I-04 "
                    "runs thesis → interpretations → evidence claims → "
                    "observations, and a plan with none of it cannot be written "
                    "from"
                ),
                refs=(strategy.strategy_id,),
            ),
        )
    return PlanChain(thesis_ref=strategy.strategy_id, links=tuple(links)), ()


# ===========================================================================
# PlanVerdict (Step 1 §4, fix F-2)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class PlanVerdict:
    """One plan version, checked (Step 1 §4, sole producer S-11).

    "``plan_ref`` (draft ID and version); ``boundary_ref`` (the E-09 version
    checked against); CheckResults V-P01…V-P05; result ``pass`` / ``fail``;
    route and counter; ``approved_plan_ref`` when it passed. Check results and
    pass/fail are **not** stored on E-14."

    ``outcome`` carries the route and the counter and is present for a failure
    only: a plan that passed left no §6.2 state unresolved, and an OutcomeRecord
    invented for it is one the indicators count (``run_summary.ScopeOutcome``).
    """

    verdict_id: str
    version: int
    unit_id: str
    destination: Destination
    plan_ref: tuple[str, int]
    boundary_ref: tuple[str, int]
    checks: tuple[CheckResult, ...]
    result: VerdictResult
    approved_plan_ref: Optional[tuple[str, int]] = None
    chain: Optional[PlanChain] = None
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if not self.verdict_id.strip() or not self.unit_id.strip():
            raise PlanCheckError(
                "a verdict is identified by its own ID and the unit whose plan it "
                "is a verdict on"
            )
        if self.version < 1:
            raise PlanCheckError(
                f"{self.verdict_id} is at version {self.version}; the first "
                "verdict on a plan is version 1, and a re-check after a boundary "
                "commit is the versions after it"
            )
        if not self.checks:
            raise PlanCheckError(
                f"{self.verdict_id} records no check; a verdict is what the "
                "checks found, and one with none is an approval by assertion"
            )
        recorded = [item.check_id for item in self.checks]
        repeated = sorted({item for item in recorded if recorded.count(item) > 1})
        if repeated:
            raise PlanCheckError(
                f"{self.verdict_id} records "
                + ", ".join(repeated)
                + " twice; one check has one result, and two are no result"
            )
        self._result_follows_the_checks()

    def _result_follows_the_checks(self) -> None:
        blocking = [item for item in self.checks if item.blocks]
        if self.result is VerdictResult.PASS:
            if blocking:
                raise PlanCheckError(
                    f"{self.verdict_id} passes with "
                    + ", ".join(sorted(item.check_id for item in blocking))
                    + " not passed; a verdict passes where every hard check "
                    "passed, and a check nobody answered is not one of them"
                )
            if self.approved_plan_ref is None:
                raise PlanCheckError(
                    f"{self.verdict_id} passes and names no approved plan; Step 1 "
                    "§4 records the approved version on the verdict that "
                    "approved it"
                )
            if self.chain is None:
                raise PlanCheckError(
                    f"{self.verdict_id} passes and resolves no chain; §3 makes "
                    "I-04 in the plan what this stage enforces, and an approval "
                    "that cannot show the chain has not shown it"
                )
            if self.outcome is not None:
                raise PlanCheckError(
                    f"{self.verdict_id} passes and records a "
                    f"{self.outcome.outcome.value}; an approved plan left no §6.2 "
                    "state unresolved, and a state invented here is one the "
                    "indicators count"
                )
            return
        if not blocking:
            raise PlanCheckError(
                f"{self.verdict_id} fails and every hard check passed; a verdict "
                "is what the checks found, and a failure none of them found is "
                "this stage repairing or refusing a plan on its own authority"
            )
        if self.approved_plan_ref is not None:
            raise PlanCheckError(
                f"{self.verdict_id} fails and names the approved plan "
                f"{self.approved_plan_ref!r}; only a plan that passed is approved, "
                "and I-08 makes the approved version the gate S-12 opens on"
            )
        if self.outcome is None or self.outcome.outcome is ArpOutcome.RESOLVE:
            raise PlanCheckError(
                f"{self.verdict_id} fails and records {self.outcome!r}; a failed "
                "check is a REPLAN to S-08 while L_strategy allows and a SKIP of "
                "the destination once it does not, and never a run that waits"
            )

    @property
    def scope_key(self) -> str:
        """The destination scope key this verdict was made under (§4.2)."""

        return destination_scope_key(self.unit_id, self.destination)

    def check(self, check_id: str) -> Optional[CheckResult]:
        """The result of one check, or ``None`` if this verdict has none."""

        for item in self.checks:
            if item.check_id == check_id:
                return item
        return None

    def as_entity(self) -> dict[str, Any]:
        """The body written to ``verdicts/plan_<plan_id>.v<n>.json`` (§2.2)."""

        plan_identity, plan_version = self.plan_ref
        boundary_identity, boundary_version = self.boundary_ref
        return {
            "entity_type": VERDICT_ENTITY_TYPE,
            "entity_id": self.verdict_id,
            "verdict_id": self.verdict_id,
            "version": self.version,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "plan_ref": {"plan_id": plan_identity, "version": plan_version},
            "boundary_ref": {
                "boundary_id": boundary_identity,
                "version": boundary_version,
            },
            "checks": [item.as_entity() for item in self.checks],
            "result": self.result.value,
            "approved_plan_ref": (
                None
                if self.approved_plan_ref is None
                else {
                    "plan_id": self.approved_plan_ref[0],
                    "version": self.approved_plan_ref[1],
                }
            ),
            "chain": None if self.chain is None else self.chain.as_entity(),
            "outcome": (
                None if self.outcome is None else self.outcome.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class PlanCheckDecision:
    """What one per-destination S-11 execution made of one plan.

    The verdict is absent only where nothing was checked: the call budget
    refused before any check could be recorded. Every other case writes one,
    including the case that routes back to S-08 — the findings are the trace §3
    asks for, and losing them would leave the reason a destination went back
    recorded nowhere but in the counter.
    """

    unit_id: str
    destination: Destination
    verdict: Optional[PlanVerdict] = None
    approved: Optional[ExecutablePlan] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0

    @property
    def passed(self) -> bool:
        """Did this plan come out approved?"""

        return (
            self.verdict is not None
            and self.verdict.result is VerdictResult.PASS
            and self.approved is not None
        )


@dataclass(frozen=True, slots=True)
class ExemplarSelection:
    """What the exemplar lookup made of one plan and one Reference Library.

    Two fields and not one, because "no exemplar was attached" has two causes
    that must not be counted as each other: a library that was read and holds
    nothing for this surface, which is a fact about the shelf, and a library
    that was not there, which is the soft input degrading. Only the second
    carries an outcome.
    """

    exemplars: tuple[Exemplar, ...] = ()
    #: The ``DEGRADE`` the absent library is recorded as. ``None`` whenever the
    #: library was read, however many items it offered this plan.
    degraded: Optional[OutcomeRecord] = None


# ===========================================================================
# Barrier B1 (§0.2)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class BarrierRound:
    """One round of barrier B1 over one unit's plans (§2.2, §3 Trace).

    ``deviating`` is the destinations V-P03 sent back; the others keep their
    approval, which is why the round records both the set it compared and the
    subset that failed. ``passed`` is the gate S-12 opens on, and it is false
    whenever the check did not pass — including the round nobody could answer.
    """

    unit_id: str
    round_index: int
    destinations: tuple[Destination, ...]
    check: CheckResult
    deviating: tuple[Destination, ...] = ()
    outcomes: tuple[OutcomeRecord, ...] = ()
    calls: int = 0

    def __post_init__(self) -> None:
        if not self.unit_id.strip():
            raise PlanCheckError("a barrier round is evaluated for one unit, named")
        if self.round_index < 1:
            raise PlanCheckError(
                f"{self.unit_id} records barrier round {self.round_index}; the "
                "first round is round 1"
            )
        if not self.destinations:
            raise PlanCheckError(
                f"{self.unit_id} ran a barrier round over no destination; V-P03 "
                "compares the unit's plans, and a round over none compared "
                "nothing and cannot have passed"
            )
        outside = sorted(
            item.value for item in set(self.deviating) - set(self.destinations)
        )
        if outside:
            raise PlanCheckError(
                f"{self.unit_id} records "
                + ", ".join(outside)
                + " as deviating in a round that did not compare them; only a "
                "destination whose plan was in the round can have deviated from "
                "the unit"
            )
        if self.deviating and self.check.result is not CheckOutcome.FAIL:
            raise PlanCheckError(
                f"{self.unit_id} names a deviating destination and records V-P03 "
                f"as {self.check.result.value}; a deviation is a finding, and a "
                "finding is a failed check"
            )

    @property
    def passed(self) -> bool:
        """Has B1 passed for this unit? Only a passing V-P03 does it.

        A round nobody could answer does not pass. §0.2 is "no text is written
        before B1 passes", and a barrier that opened because the check could not
        be run would be the barrier not existing on exactly the runs it matters
        on.
        """

        return self.check.result is CheckOutcome.PASS and not self.deviating

    def as_entity(self) -> dict[str, Any]:
        """The body written to ``units/<unit>/b1/round_<k>.json`` (§2.2)."""

        return {
            "entity_type": BARRIER_ENTITY_TYPE,
            "entity_id": barrier_round_id(self.unit_id, self.round_index),
            "barrier_id": BARRIER_ID,
            "unit_id": self.unit_id,
            "round": self.round_index,
            "destinations": [item.value for item in self.destinations],
            "check": self.check.as_entity(),
            "deviating": [item.value for item in self.deviating],
            "passed": self.passed,
            "outcomes": [item.model_dump(mode="json") for item in self.outcomes],
        }


# ===========================================================================
# What the stage is handed
#
# The Reference Library is handed in as
# :class:`~src.strategy.reference_library.ReferenceLibrary`, which lives with
# the loader that reads it: it is a client document like the Client Contract
# and the Audience Profile, and the core reads no file (CE-1).
# ===========================================================================


@dataclass(frozen=True, slots=True)
class PlanFingerprint:
    """A prior E-16 as V-P05 counts it (§3, Inputs: Portfolio Memory).

    A narrow view of the fingerprint rather than the entity itself, for the
    reason S-07's and S-09's are: the fields below are all the soft check
    compares, and which fingerprints count as recent is a question about the day
    the run happens on — a scheduling input the core is handed rather than one
    it reads (CE-1).
    """

    fingerprint_id: str
    destination: Destination
    format: Optional[PlanFormat] = None
    first_line_mechanics: Optional[str] = None
    segment_count: Optional[int] = None


def plan_check_records(knowledge: KnowledgeBase) -> Mapping[str, LoadedCheck]:
    """The five check records S-11 applies, by ID (§3, Knowledge / config).

    Read from the register rather than written down here, because a CheckResult
    records "rule status and class **at the time of the run**": a stage that
    carried its own copy of a check's class would keep recording ``candidate``
    after a keeper approved the rule.

    A missing record is a refusal and not a warning. A plan approved without
    V-P02 having been applied is not an approved plan, and continuing with four
    checks because the fifth file was not there is exactly the fail-open the
    register exists to prevent.
    """

    loaded = {check.identity: check for check in knowledge.checks}
    missing = sorted(set(REQUIRED_CHECKS) - set(loaded))
    if missing:
        raise PlanCheckError(
            "the register holds no check record for "
            + ", ".join(missing)
            + f"; {STAGE} applies V-P01…V-P05 and cannot approve a plan against "
            "a rule nobody loaded"
        )
    return {identity: loaded[identity] for identity in REQUIRED_CHECKS}


# ===========================================================================
# Identity and storage
# ===========================================================================


def verdict_id(plan_identity: str) -> str:
    """The ID of the verdicts on one plan."""

    if not plan_identity.strip():
        raise PlanCheckError("a verdict is named for the plan it is a verdict on")
    return f"pv-{plan_identity}"


def verdict_relative_path(
    unit: str, destination: Destination, plan_identity: str, version: int
) -> str:
    """``units/<unit>/destinations/<dst>/verdicts/plan_<plan_id>.v<n>.json`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    _validate_path_component(plan_identity, "plan_id")
    if version < 1:
        raise PlanCheckError(f"a verdict version is numbered from 1; got {version}")
    return (
        f"{UNITS_DIRECTORY}/{unit}/{DESTINATIONS_DIRECTORY}/{destination.value}/"
        f"{VERDICTS_DIRECTORY}/plan_{plan_identity}.v{version}.json"
    )


def barrier_round_id(unit: str, round_index: int) -> str:
    """The ID of one barrier round of one unit."""

    if round_index < 1:
        raise PlanCheckError(
            f"a barrier round is numbered from 1; got {round_index}"
        )
    return f"b1-{unit}-r{round_index}"


def barrier_round_relative_path(unit: str, round_index: int) -> str:
    """``units/<unit_id>/b1/round_<k>.json`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    if round_index < 1:
        raise PlanCheckError(
            f"a barrier round is numbered from 1; got {round_index}"
        )
    return f"{UNITS_DIRECTORY}/{unit}/{BARRIER_DIRECTORY}/round_{round_index}.json"


def write_plan_verdict(
    workspace: RunWorkspace, verdict: PlanVerdict
) -> EntityIndexEntry:
    """Write one PlanVerdict into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once (P1)
    and §2.3 write ownership hold: ``verdicts/plan_*`` belongs to S-11 and to
    nothing else. A re-check after a boundary commit is a new version with a
    path of its own, never an overwrite of the verdict it supersedes — which is
    what keeps the record of an approval that no longer holds.
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=verdict_relative_path(
            verdict.unit_id,
            verdict.destination,
            verdict.plan_ref[0],
            verdict.version,
        ),
        entity_type=VERDICT_ENTITY_TYPE,
        entity_id=verdict.verdict_id,
        payload=verdict.as_entity(),
        version=verdict.version,
    )


def write_barrier_round(
    workspace: RunWorkspace, barrier: BarrierRound
) -> EntityIndexEntry:
    """Write one B1 round into the run workspace, and index it (§2.2, §2.3)."""

    return workspace.write_entity(
        stage=STAGE,
        relative_path=barrier_round_relative_path(
            barrier.unit_id, barrier.round_index
        ),
        entity_type=BARRIER_ENTITY_TYPE,
        entity_id=barrier_round_id(barrier.unit_id, barrier.round_index),
        payload=barrier.as_entity(),
    )


def write_approved_plan(
    workspace: RunWorkspace, plan: ExecutablePlan
) -> EntityIndexEntry:
    """Write the approved version of a plan (§2.3 gives it to this stage).

    A thin name over :func:`~src.editorial_core.executable_plan.write_plan`,
    which derives the writing stage from the version's own
    ``stage_of_version``: the entity says which stage made it, and the caller
    does not get to say otherwise.
    """

    if plan.stage_of_version is not PlanStage.APPROVED:
        raise PlanCheckError(
            f"{plan.plan_id} v{plan.version} is "
            f"{plan.stage_of_version.value} and is being written as approved; "
            "§2.3 gives the draft to S-10, and a draft written here would be "
            "this stage claiming an approval it did not make"
        )
    return write_plan(workspace, plan)


# ===========================================================================
# The two calls
# ===========================================================================


class PlanCheckTransport(Protocol):
    """The per-destination call: V-P01's semantic half and V-P04's constructions."""

    def complete(self, *, instructions: str, request: str) -> str: ...


class BarrierTransport(Protocol):
    """The one call per unit per barrier round: V-P03."""

    def complete(self, *, instructions: str, request: str) -> str: ...


PLAN_CHECK_INSTRUCTIONS = """\
You answer two explicit questions about ONE already-written plan for ONE
destination. You do not repair the plan, do not rewrite it, and do not suggest
what it should have been.

1. `fields_hold`: taking the fields as written — the thesis, the focal subject,
   the reader path, the opening, the reveal, the concession, the ending
   intention, the format, the length target and the segmentation — is there a
   text that satisfies all of them at once? Answer false only when two named
   fields cannot both hold, and then say which two and why. Do not read a label,
   a category or a name for the type of the entry into any field; there is none.

2. `forbidden_constructions`: does any segment execute a construction type the
   contract forbids, however it is worded? The request lists the forbidden
   construction types with their rule references. Report one entry per segment
   that executes one, naming the `rule_ref` exactly as the request spells it and
   the segment by name. Report nothing for a forbidden phrase — phrases are
   matched by code, and are not your question.

Return ONLY one valid JSON object, no text outside it:

{"fields_hold": true, "conflict": null, "forbidden_constructions": []}

or, when two fields cannot both hold:

{"fields_hold": false, "conflict": {"first_field": "reveal",
 "second_field": "length_target", "detail": "..."},
 "forbidden_constructions": [{"rule_ref": "...", "segment": "...",
 "detail": "..."}]}
"""

BARRIER_INSTRUCTIONS = """\
You compare the plans of ONE editorial unit's destinations, at the plan barrier,
before any of them has been written as prose. You answer two explicit questions
and nothing else. You never compare a plan against another destination's text,
and you never make one plan the source of another: they are siblings over one
anchor.

1. Per plan: is the unit's anchor interpretation the thing this plan asks the
   reader to believe, or has the plan drifted to a different reading? Answer for
   every destination in the request, exactly once each.

2. Across plans: does any pair assert facts or consequences that cannot both be
   true? For each such pair, name the destinations involved and the ONE of them
   that deviated from the anchor — only that destination goes back.

Return ONLY one valid JSON object, no text outside it:

{"plans": [{"destination": "wix", "carries_anchor": true, "detail": null}],
 "contradictions": [{"destinations": ["wix", "linkedin"],
 "deviating": "linkedin", "detail": "..."}]}
"""


class _CheckModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FieldConflict(_CheckModel):
    first_field: str = Field(min_length=1)
    second_field: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ConstructionFinding(_CheckModel):
    rule_ref: str = Field(min_length=1)
    segment: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class PlanCheckAnswer(_CheckModel):
    fields_hold: bool
    conflict: Optional[FieldConflict] = None
    forbidden_constructions: tuple[ConstructionFinding, ...] = ()


class PlanJudgment(_CheckModel):
    destination: Destination
    carries_anchor: bool
    detail: Optional[str] = None


class Contradiction(_CheckModel):
    destinations: tuple[Destination, ...] = ()
    deviating: Destination
    detail: str = Field(min_length=1)


class BarrierAnswer(_CheckModel):
    plans: tuple[PlanJudgment, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()


# ===========================================================================
# The stage · per destination
# ===========================================================================


def check_plan(
    *,
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    rules: DestinationRules,
    contract: AdaptationContract,
    checks: Mapping[str, LoadedCheck],
    counters: AttemptCounterLedger,
    transport: PlanCheckTransport,
    library: Optional[ReferenceLibrary] = None,
    portfolio: Sequence[PlanFingerprint] = (),
    budget: Optional[CallBudget] = None,
) -> PlanCheckDecision:
    """Check one draft plan, and approve it or route it (V-P01, V-P02, V-P04, V-P05).

    Returns a :class:`PlanCheckDecision` in every case the protocol has an
    outcome for, including the failures that route back to S-08. The stage's
    preconditions still raise.

    The code halves run first and the call is made only if they all passed.
    That is §3's Calls column read honestly — "1 per destination per plan
    version" is a maximum, not a quota — and it is the direction that fails
    closed: a plan a deterministic check already refused is not repaired by
    asking a model a second question, and the checks whose model half was
    therefore never asked are recorded as ``not_answered`` rather than as
    anything that could be read as a pass.

    ``library`` is the one input of this stage that may be missing: §3 lists the
    Reference Library among the Inputs, and an absent one degrades rather than
    blocking — the plan is approved on its checks, and the examples are material
    the Writer would have been handed and not authority any check rests on.
    ``None`` is a caller that read no library, and it reaches the same
    :data:`~src.editorial_core.arp.StateCode.REFERENCE_LIBRARY_UNAVAILABLE`
    record as a library that was looked for and was not there, because they are
    the same fact about this run.
    """

    _precondition(
        plan=plan, strategy=strategy, boundary=boundary, core=core, rules=rules
    )
    scope_key = plan.scope_key
    chain, chain_findings = resolve_chain(strategy, boundary, core)
    code_findings = {
        "V-P01": (*chain_findings, *_v_p01_code(plan, strategy, rules)),
        "V-P02": _v_p02(strategy, plan, boundary),
    }
    platform_findings, terminal = _v_p04_code(plan, rules, contract)
    code_findings["V-P04"] = platform_findings
    soft = _v_p05(checks["V-P05"], plan, portfolio)

    if any(code_findings.values()):
        return _refused(
            plan=plan,
            boundary=boundary,
            checks=checks,
            code_findings=code_findings,
            soft=soft,
            counters=counters,
            scope_key=scope_key,
            terminal=terminal,
            calls=0,
        )

    refusal = _spend(budget, scope_key)
    if refusal is not None:
        return PlanCheckDecision(
            unit_id=plan.unit_id,
            destination=plan.destination,
            outcomes=(refusal,),
        )

    answer = _plan_answer(
        transport, _plan_request(plan=plan, strategy=strategy, contract=contract)
    )
    judged = None if answer is None else _judged(answer, plan, contract)
    if judged is None:
        return _unanswered(
            plan=plan,
            boundary=boundary,
            checks=checks,
            soft=soft,
            scope_key=scope_key,
        )
    model_findings, construction_findings = judged
    code_findings["V-P01"] = model_findings
    code_findings["V-P04"] = construction_findings
    if any(code_findings.values()):
        return _refused(
            plan=plan,
            boundary=boundary,
            checks=checks,
            code_findings=code_findings,
            soft=soft,
            counters=counters,
            scope_key=scope_key,
            terminal=False,
            calls=1,
        )

    assert chain is not None  # a chain with findings would have refused above
    selection = select_exemplars(plan, library)
    approved = plan.approved_with(selection.exemplars)
    results = (
        _passed(checks["V-P01"], CheckMethod.CODE_AND_MODEL),
        _passed(checks["V-P02"], CheckMethod.CODE),
        _passed(checks["V-P04"], CheckMethod.CODE_AND_MODEL),
        soft,
    )
    return PlanCheckDecision(
        unit_id=plan.unit_id,
        destination=plan.destination,
        verdict=PlanVerdict(
            verdict_id=verdict_id(plan.plan_id),
            version=1,
            unit_id=plan.unit_id,
            destination=plan.destination,
            plan_ref=plan.plan_ref,
            boundary_ref=(boundary.boundary_id, boundary.version),
            checks=results,
            result=VerdictResult.PASS,
            approved_plan_ref=approved.plan_ref,
            chain=chain,
        ),
        approved=approved,
        outcomes=() if selection.degraded is None else (selection.degraded,),
        calls=1,
    )


def select_exemplars(
    plan: ExecutablePlan, library: Optional[ReferenceLibrary]
) -> ExemplarSelection:
    """The exemplar lookup (§3, Decider: ``code``).

    Items of this destination in this format, in the order the library offers
    them. A lookup and not a judgment: choosing an example on how well it fits
    the material would be a second editorial decision taken after the plan was
    approved, and the take / do-not-copy notes travel with the item rather than
    being written here.

    A library that was read and offers this surface nothing returns no exemplar
    and no outcome: the shelf answered, and the answer was none. A library that
    was not there returns the same empty list and a ``DEGRADE``, because the
    question was never put to anything — the distinction the whole soft-input
    rule rests on, and the one an empty tuple on its own cannot carry.
    """

    if library is None or not library.available:
        return ExemplarSelection(
            degraded=OutcomeRecord(
                outcome=ArpOutcome.DEGRADE,
                state_code=StateCode.REFERENCE_LIBRARY_UNAVAILABLE,
                scope=OutcomeScope.DESTINATION,
                scope_key=plan.scope_key,
                reason=(
                    f"{plan.plan_id} is approved with no exemplar: "
                    + (
                        "no Reference Library was supplied to the stage"
                        if library is None
                        else str(library.unavailable_reason)
                    )
                ),
            )
        )
    return ExemplarSelection(
        exemplars=tuple(
            item.as_exemplar()
            for item in library.items
            if item.destination is plan.destination and item.format is plan.format
        )
    )


def approval_holds(
    verdict: PlanVerdict, boundary: InterpretationBoundary
) -> bool:
    """Does this approval still stand against this boundary version (F-4)?

    The S-12 precondition, and the one that stops the drift defect F-4 names:
    "plans approved against the older boundary version could reach S-12". A
    verdict passed against E-09 v2 says nothing about v3 — the readings it
    checked may have been reclassified since — so the comparison is made rather
    than inherited, and a stale verdict loses the authority it had instead of
    keeping it until somebody notices.
    """

    return (
        verdict.result is VerdictResult.PASS
        and verdict.approved_plan_ref is not None
        and verdict.boundary_ref == (boundary.boundary_id, boundary.version)
    )


def recheck_after_boundary_commit(
    *,
    verdict: PlanVerdict,
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    checks: Mapping[str, LoadedCheck],
    counters: AttemptCounterLedger,
) -> PlanVerdict:
    """Re-establish one approval against a newer boundary version (F-4).

    "On a new boundary version, S-11's code checks (V-P02, chain) re-run on
    every approved plan of the unit (**0 model calls**)." So exactly those two
    run, the method recorded is ``code`` because that is what was asked, and the
    result is a **new verdict version** — the old one is not edited and does not
    become current again if this one fails.

    An approval that survives is recorded against the new version and
    :func:`approval_holds` starts answering ``True`` for it. One that does not
    routes back to S-08 like any other failed hard check.
    """

    if verdict.result is not VerdictResult.PASS or (
        verdict.approved_plan_ref is None
    ):
        raise PlanCheckError(
            f"{verdict.verdict_id} is {verdict.result.value} and is being "
            "re-checked against a newer boundary version; F-4 re-runs the code "
            "checks on an approval that held, and a verdict that never approved "
            "anything has nothing to re-establish"
        )
    if boundary.boundary_id != verdict.boundary_ref[0]:
        raise PlanCheckError(
            f"{verdict.verdict_id} was checked against boundary "
            f"{verdict.boundary_ref[0]!r} and is being re-checked against "
            f"{boundary.boundary_id!r}; a re-check is the same unit's boundary, "
            "one commit later"
        )
    if boundary.version <= verdict.boundary_ref[1]:
        raise PlanCheckError(
            f"{verdict.verdict_id} was checked against version "
            f"{verdict.boundary_ref[1]} and is being re-checked against version "
            f"{boundary.version}; a boundary version only moves forward, and a "
            "re-check against an older snapshot would restore readings a commit "
            "refused"
        )
    if verdict.approved_plan_ref != plan.plan_ref:
        raise PlanCheckError(
            f"{verdict.verdict_id} approved {verdict.approved_plan_ref!r} and is "
            f"being re-checked over {plan.plan_ref!r}; the plan a verdict "
            "re-establishes is the one it approved"
        )
    chain, chain_findings = resolve_chain(strategy, boundary, core)
    promise = _v_p02(strategy, plan, boundary)
    version = verdict.version + 1
    if not chain_findings and not promise:
        assert chain is not None
        return PlanVerdict(
            verdict_id=verdict.verdict_id,
            version=version,
            unit_id=plan.unit_id,
            destination=plan.destination,
            plan_ref=verdict.plan_ref,
            boundary_ref=(boundary.boundary_id, boundary.version),
            checks=(
                _passed(checks["V-P01"], CheckMethod.CODE),
                _passed(checks["V-P02"], CheckMethod.CODE),
            ),
            result=VerdictResult.PASS,
            approved_plan_ref=verdict.approved_plan_ref,
            chain=chain,
        )
    failing = "V-P01" if chain_findings else "V-P02"
    findings = chain_findings or promise
    route = counters.route(
        source=STAGE,
        cause=CHECK_FAILED_CAUSE,
        scope_key=plan.scope_key,
        state_code=_CHECK_STATES[failing],
        reason=(
            f"{failing} no longer holds for {plan.plan_id} against boundary "
            f"version {boundary.version}: {findings[0].detail}"
        ),
    )
    return PlanVerdict(
        verdict_id=verdict.verdict_id,
        version=version,
        unit_id=plan.unit_id,
        destination=plan.destination,
        plan_ref=verdict.plan_ref,
        boundary_ref=(boundary.boundary_id, boundary.version),
        checks=tuple(
            _result(
                checks[identity],
                CheckMethod.CODE,
                CheckOutcome.FAIL if identity == failing else CheckOutcome.PASS,
                findings if identity == failing else (),
                route=CHECK_FAILED_CAUSE if identity == failing else None,
            )
            for identity in ("V-P01", "V-P02")
        ),
        result=VerdictResult.FAIL,
        outcome=route,
    )


# ===========================================================================
# The stage · barrier B1 (V-P03)
# ===========================================================================


def run_barrier(
    *,
    unit_id: str,
    anchor: Anchor,
    expected_destinations: frozenset[Destination],
    plans: Sequence[ExecutablePlan],
    verdicts: Sequence[PlanVerdict],
    boundary: InterpretationBoundary,
    checks: Mapping[str, LoadedCheck],
    counters: AttemptCounterLedger,
    transport: BarrierTransport,
    round_index: int = 1,
    budget: Optional[CallBudget] = None,
) -> BarrierRound:
    """One round of barrier B1: V-P03 over the unit's approved plans.

    ``expected_destinations`` is the unit's current non-skipped destinations for
    this round, **declared by the run harness** rather than worked out here. The
    harness makes no editorial decision in supplying it: it assembles the set
    deterministically from lifecycle state already established upstream, and
    S-11 neither infers eligibility nor reads the set off ``plans``. This stage
    then holds the barrier's precondition as a real check — "it runs only when
    every destination that has not been skipped holds a plan that has passed its
    per-destination checks" — by requiring the plans to represent exactly that
    set, before any budget is spent and before the V-P03 call.

    A destination that was skipped is simply absent from both — "if B1 can never
    pass (the deviating destination is skipped), B1 re-evaluates without it" — so
    a later round is this function called again with the shorter expected set,
    the matching plans, and the next ``round_index``.

    A failure sends back **only** the destinations the answer names as
    deviating. The rest keep their approval, and nothing here touches their
    verdicts.
    """

    _barrier_precondition(
        unit_id=unit_id,
        anchor=anchor,
        expected_destinations=expected_destinations,
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        round_index=round_index,
    )
    compared = tuple(plan.destination for plan in plans)
    refusal = _spend_unit(budget, unit_id)
    if refusal is not None:
        return BarrierRound(
            unit_id=unit_id,
            round_index=round_index,
            destinations=compared,
            check=_result(
                checks[BARRIER_CHECK],
                CheckMethod.MODEL_EXPLICIT_CRITERION,
                CheckOutcome.NOT_ANSWERED,
                (
                    Finding(
                        detail=(
                            "the run's allowance was gone before the barrier "
                            "round was asked; B1 has not passed, and no text is "
                            "written for this unit"
                        ),
                        refs=(unit_id,),
                    ),
                ),
            ),
            outcomes=(refusal,),
        )

    answer = _barrier_answer(
        transport, _barrier_request(anchor=anchor, plans=plans, boundary=boundary)
    )
    deviating = None if answer is None else _deviating(answer, compared)
    if deviating is None:
        return BarrierRound(
            unit_id=unit_id,
            round_index=round_index,
            destinations=compared,
            check=_result(
                checks[BARRIER_CHECK],
                CheckMethod.MODEL_EXPLICIT_CRITERION,
                CheckOutcome.NOT_ANSWERED,
                (
                    Finding(
                        detail=(
                            "the barrier round produced no answer this stage may "
                            "read; B1 has not passed, and I-07 is not established "
                            "by a comparison nobody made"
                        ),
                        refs=(unit_id,),
                    ),
                ),
            ),
            outcomes=(
                OutcomeRecord(
                    outcome=ArpOutcome.SKIP,
                    state_code=StateCode.PLAN_CHECK_UNAVAILABLE,
                    scope=OutcomeScope.UNIT,
                    scope_key=unit_id,
                    reason=(
                        "V-P03 produced no answer, so barrier B1 cannot pass for "
                        "this unit and no destination of it may be written"
                    ),
                ),
            ),
            calls=1,
        )
    named, findings = deviating
    if not named:
        return BarrierRound(
            unit_id=unit_id,
            round_index=round_index,
            destinations=compared,
            check=_passed(
                checks[BARRIER_CHECK], CheckMethod.MODEL_EXPLICIT_CRITERION
            ),
            calls=1,
        )
    routes = tuple(
        counters.route(
            source=STAGE,
            cause=DEVIATION_CAUSE,
            scope_key=destination_scope_key(unit_id, destination),
            state_code=StateCode.DESTINATIONS_CONTRADICT,
            reason=(
                f"{destination.value} deviated from the anchor of {unit_id} at "
                f"barrier round {round_index}; the unit's other destinations keep "
                "their approval"
            ),
        )
        for destination in named
    )
    return BarrierRound(
        unit_id=unit_id,
        round_index=round_index,
        destinations=compared,
        check=_result(
            checks[BARRIER_CHECK],
            CheckMethod.MODEL_EXPLICIT_CRITERION,
            CheckOutcome.FAIL,
            findings,
            route=DEVIATION_CAUSE,
        ),
        deviating=named,
        outcomes=routes,
        calls=1,
    )


# ===========================================================================
# The checks
# ===========================================================================


def _v_p01_code(
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    rules: DestinationRules,
) -> tuple[Finding, ...]:
    """V-P01's code half: the parts of the record that are lookups.

    "Is the opening's figure in the Evidence Core, is the second interpretation
    admissible, does the length target allow the declared reveal." The first two
    are the chain's, resolved beside this one; what is left here is the third
    and the post-condition it rests on — every move carried, and a delayed
    reveal that the segmentation actually delays.
    """

    findings: list[Finding] = []
    missing = uncarried_moves(plan, strategy)
    if missing:
        findings.append(
            Finding(
                detail=(
                    "move(s) "
                    + ", ".join(str(index) for index in missing)
                    + " of the reader path are carried by no segment; a plan that "
                    "drops a move the strategy decided is not the strategy "
                    "adapted, and no text can execute both"
                ),
                refs=(strategy.strategy_id, plan.plan_id),
            )
        )
    if strategy.reveal.kind is RevealKind.DELAYED:
        until = strategy.reveal.until_move
        assert until is not None  # E-13 refuses a delayed reveal without one
        earliest = next(
            (
                position
                for position, segment in enumerate(plan.segments, 1)
                if until in segment.move_indices
            ),
            None,
        )
        if earliest == 1:
            findings.append(
                Finding(
                    detail=(
                        f"the reveal is delayed until move {until} and the "
                        f"segmentation carries that move in the first of "
                        f"{len(plan.segments)} segment(s); the reveal and the "
                        f"{rules.format.value}'s shape cannot both hold"
                    ),
                    refs=(strategy.strategy_id, plan.plan_id),
                )
            )
    return tuple(findings)


def _v_p02(
    strategy: EditorialStrategy,
    plan: ExecutablePlan,
    boundary: InterpretationBoundary,
) -> tuple[Finding, ...]:
    """V-P02, by code alone: the promise against the boundary in front of S-11.

    The check record's own criterion: "every point the plan promises resolves to
    an interpretation id in the current E-09 version's ``admissible`` set, and
    the count of promised points is no greater than the count of that set".

    The count is :func:`~src.editorial_core.strategy_selection.promised_points`
    and not a second arithmetic: adaptation may not change an E-13 field, so the
    points a plan promises are the points its strategy promised, and two
    spellings of the same count would eventually disagree about the Ramp "3
    things" case they both exist for.
    """

    findings: list[Finding] = []
    for identity in strategy.interpretation_refs:
        member = boundary.member(identity)
        if member is None or not member.admissible:
            findings.append(
                Finding(
                    detail=(
                        f"the plan carries {identity}, which boundary version "
                        f"{boundary.version} records as inadmissible or does not "
                        "hold at all; I-05 lets a plan carry only the admissible "
                        "set"
                    ),
                    refs=(identity,),
                )
            )
    link = plan.cross_destination_link
    if link is not None:
        member = boundary.member(link.interpretation_ref)
        if member is None or not member.admissible:
            findings.append(
                Finding(
                    detail=(
                        f"the link to {link.target.value} promises "
                        f"{link.interpretation_ref}, which boundary version "
                        f"{boundary.version} does not admit; a link promises a "
                        "reading, and a promise outside the boundary is one no "
                        "text may deliver"
                    ),
                    refs=(link.interpretation_ref,),
                )
            )
    promised = promised_points(strategy)
    admitted = len(boundary.admissible)
    if promised > admitted:
        findings.append(
            Finding(
                detail=(
                    f"the plan promises {promised} point(s) where boundary "
                    f"version {boundary.version} admits {admitted} reading(s); a "
                    "text cannot promise more meanings than the evidence was "
                    "shown to carry"
                ),
                refs=(plan.plan_id,),
            )
        )
    return tuple(findings)


def _v_p04_code(
    plan: ExecutablePlan,
    rules: DestinationRules,
    contract: AdaptationContract,
) -> tuple[tuple[Finding, ...], bool]:
    """V-P04's code half, and whether any finding ends the destination.

    "Code applies the rules that are lookups: forbidden phrases, fixed slots the
    contract decides, length and hashtag policy, and each tier-1 ``K-DST-*``
    rule for this destination." Each finding names the rule and its tier,
    because the tier decides the route — and the second half of the return value
    is the one thing the tier alone does not decide: a tier-1 rule ends the
    destination only "with no compliant variant", which is the rule's own
    property and never this stage's opinion.
    """

    findings: list[Finding] = []
    terminal = False
    if plan.format is not rules.format:
        findings.append(
            Finding(
                detail=(
                    f"the plan is a {plan.format.value} and "
                    f"{rules.destination.value} takes {rules.format.value}"
                ),
                refs=(plan.plan_id,),
                rule_ref=rules.format_rule.rule_id,
                tier=rules.format_rule.tier,
            )
        )
        terminal = terminal or _ends_it(rules.format_rule)
    if not plan.length_target.within(rules.length):
        findings.append(
            Finding(
                detail=(
                    f"the plan targets {plan.length_target.minimum}–"
                    f"{plan.length_target.maximum} "
                    f"{plan.length_target.unit.value} and "
                    f"{rules.destination.value} allows {rules.length.minimum}–"
                    f"{rules.length.maximum} {rules.length.unit.value}; both ends "
                    "of the range are the rule"
                ),
                refs=(plan.plan_id,),
                rule_ref=rules.length_rule.rule_id,
                tier=rules.length_rule.tier,
            )
        )
        terminal = terminal or _ends_it(rules.length_rule)
    stated = None if plan.hashtags is None else plan.hashtags.policy
    if stated is not rules.hashtags:
        findings.append(
            Finding(
                detail=(
                    f"the plan records hashtag policy {stated!r} and "
                    f"{rules.destination.value} states {rules.hashtags.value}"
                ),
                refs=(plan.plan_id,),
                rule_ref=rules.hashtag_rule.rule_id,
                tier=rules.hashtag_rule.tier,
            )
        )
        terminal = terminal or _ends_it(rules.hashtag_rule)
    findings.extend(_contract_findings(plan, contract))
    return tuple(findings), terminal


def _ends_it(rule: PlatformRule) -> bool:
    """Does breaking this rule end the destination (V-P04's route table)?

    "A tier-1 hard platform rule is violated with no compliant variant →
    terminal". Both halves, because either alone is the wrong answer: a tier-2
    client rule is replanned around however absolute it sounds, and a tier-1
    rule that admits a compliant variant is replanned around too.
    """

    return bool(rule.is_hard) and not bool(rule.compliant_variant)


def _contract_findings(
    plan: ExecutablePlan, contract: AdaptationContract
) -> tuple[Finding, ...]:
    """The tier-2 half of V-P04: the contract's own rules, as lookups.

    The forbidden list and the fixed slots are compared with what the contract
    holds rather than merely inspected: §3's Post column for S-10 is "``forbidden``
    is resolved", and a plan that quietly resolved a shorter list than the
    contract in force would pass every phrase check by not carrying the rule.
    """

    findings: list[Finding] = []
    resolved = {(item.kind, item.value) for item in plan.forbidden}
    for item in contract.forbidden:
        if (item.kind, item.value) not in resolved:
            findings.append(
                Finding(
                    detail=(
                        f"the contract forbids {item.value!r} and the plan does "
                        "not carry the entry; a forbidden list the plan resolved "
                        "without a rule in force is a rule nobody will check "
                        "against"
                    ),
                    refs=(plan.plan_id,),
                    rule_ref=item.rule_ref,
                    tier=item.tier,
                )
            )
    fixed = {(slot.name, slot.value) for slot in plan.fixed_slots}
    for slot in contract.fixed_slots:
        if (slot.name, slot.value) not in fixed:
            findings.append(
                Finding(
                    detail=(
                        f"the contract fixes {slot.name} at {slot.value!r} and the "
                        "plan does not carry that value; a fixed slot is a "
                        "constraint, not a default"
                    ),
                    refs=(plan.plan_id,),
                    rule_ref=slot.rule_ref,
                    tier=KnowledgeTier.APPROVED_CLIENT_RULE,
                )
            )
    for item in plan.forbidden:
        for text in plan.texts():
            if item.matches(text):
                findings.append(
                    Finding(
                        detail=(
                            f"the plan's own surface carries the forbidden phrase "
                            f"{item.value!r}: {text!r}"
                        ),
                        refs=(plan.plan_id,),
                        rule_ref=item.rule_ref,
                        tier=item.tier,
                    )
                )
                break
    return tuple(findings)


def _v_p05(
    check: LoadedCheck,
    plan: ExecutablePlan,
    portfolio: Sequence[PlanFingerprint],
) -> CheckResult:
    """V-P05: portfolio pressure, recorded and never acted on (I-12).

    "Code compares the plan's fields with the fingerprints of this client's
    recent publications on this destination and records what it found … No
    threshold decides anything (I-12)." So the result is always a pass carrying
    hints, and :class:`CheckResult` refuses to build a soft check that could be
    anything else — the check cannot become a threshold by somebody deciding to
    read it as one.
    """

    hints: list[Finding] = []
    for entry in portfolio:
        if entry.destination is not plan.destination:
            continue
        repeated: list[str] = []
        if entry.format is not None and entry.format is plan.format:
            repeated.append("format")
        if entry.first_line_mechanics is not None and (
            entry.first_line_mechanics == plan.first_line_mechanics
        ):
            repeated.append("first-line mechanics")
        if entry.segment_count is not None and (
            entry.segment_count == len(plan.segments)
        ):
            repeated.append("segment count")
        if repeated:
            hints.append(
                Finding(
                    detail=(
                        f"{entry.fingerprint_id} on {plan.destination.value} "
                        "repeats this plan's "
                        + ", ".join(repeated)
                        + "; a hint, and never a reason to block, edit or replan "
                        "anything"
                    ),
                    refs=(entry.fingerprint_id,),
                )
            )
    if not hints:
        hints.append(
            Finding(
                detail=(
                    f"no recent publication on {plan.destination.value} repeats "
                    "this plan's shape; the comparison was made and found nothing"
                ),
                refs=(plan.plan_id,),
            )
        )
    return _result(check, CheckMethod.CODE, CheckOutcome.PASS, tuple(hints))


# ===========================================================================
# Verdicts, requests and answers
# ===========================================================================


def _precondition(
    *,
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    rules: DestinationRules,
) -> None:
    """§3's Pre column: a plan draft exists, and everything describes one thing."""

    if plan.stage_of_version is not PlanStage.DRAFT:
        raise PlanCheckError(
            f"{plan.plan_id} v{plan.version} is {plan.stage_of_version.value} and "
            f"reached {STAGE}; §3 Pre asks for a plan draft, and re-checking an "
            "approved version would be this stage approving its own work"
        )
    if plan.strategy_ref != strategy.strategy_id:
        raise PlanCheckError(
            f"{plan.plan_id} adapts {plan.strategy_ref} and {strategy.strategy_id} "
            f"reached {STAGE}; every check resolves the plan through its own "
            "strategy, and another one answers about another plan"
        )
    if plan.unit_id != strategy.unit_id or plan.destination is not (
        strategy.destination
    ):
        raise PlanCheckError(
            f"{plan.plan_id} belongs to {plan.unit_id}/{plan.destination.value} "
            f"and {strategy.strategy_id} to "
            f"{strategy.unit_id}/{strategy.destination.value}; a plan and the "
            "strategy it adapted are one destination's"
        )
    if rules.destination is not plan.destination:
        raise PlanCheckError(
            f"the rules offered are {rules.destination.value}'s and "
            f"{plan.plan_id} is {plan.destination.value}'s; V-P04 compares a plan "
            "with its own destination's rules"
        )
    if boundary.core_ref != (core.core_id, core.version):
        raise PlanCheckError(
            f"{plan.plan_id} reached {STAGE} with a boundary over "
            f"{boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); the chain runs through both, "
            "and two that describe different material cannot both be right"
        )
    if strategy.boundary_ref[0] != boundary.boundary_id:
        raise PlanCheckError(
            f"{strategy.strategy_id} was written against boundary "
            f"{strategy.boundary_ref[0]!r} and reached {STAGE} with "
            f"{boundary.boundary_id!r}; a plan is checked inside its own unit's "
            "boundary"
        )
    if strategy.boundary_ref[1] > boundary.version:
        raise PlanCheckError(
            f"{strategy.strategy_id} was written against boundary version "
            f"{strategy.boundary_ref[1]} and reached {STAGE} with version "
            f"{boundary.version}; a version only ever moves forward, and a check "
            "against an older snapshot than the plan is the drift F-4 names"
        )


def _barrier_precondition(
    *,
    unit_id: str,
    anchor: Anchor,
    expected_destinations: frozenset[Destination],
    plans: Sequence[ExecutablePlan],
    verdicts: Sequence[PlanVerdict],
    boundary: InterpretationBoundary,
    round_index: int,
) -> None:
    """§3's Pre for V-P03: every non-skipped destination holds a passed plan.

    A precondition and not a judgment: a barrier that concluded anything from
    the plans it happened to be shown would be a barrier a caller can open by
    passing fewer of them. So the round's participants are **declared** rather
    than inferred here: ``expected_destinations`` is the harness's assembly of
    the unit's current non-skipped destinations for this round, and this stage
    refuses any round whose plans do not represent exactly that set. S-11 does
    not decide eligibility and does not derive the set from ``plans``, which
    would be the same assumption wearing a check's clothes.

    Both directions are refused, and both before anything is spent: a missing
    destination is a barrier opened over a subset, and an unexpected one is a
    plan the round was never assembled to compare.
    """

    if not unit_id.strip():
        raise PlanCheckError("a barrier round is evaluated for one unit, named")
    if round_index < 1:
        raise PlanCheckError(
            f"{unit_id} entered barrier round {round_index}; the first is round 1"
        )
    if not plans:
        raise PlanCheckError(
            f"{unit_id} entered barrier {BARRIER_ID} with no plan; V-P03 compares "
            "the unit's plans against the anchor, and a barrier over none has "
            "nothing to compare and nothing to pass"
        )
    if anchor.unit_id != unit_id:
        raise PlanCheckError(
            f"anchor {anchor.anchor_id} is the anchor of {anchor.unit_id!r} and "
            f"entered barrier {BARRIER_ID} for {unit_id!r}; I-07 gives a unit "
            "exactly one"
        )
    named = [plan.destination for plan in plans]
    duplicated = sorted({item.value for item in named if named.count(item) > 1})
    if duplicated:
        raise PlanCheckError(
            f"{unit_id} entered barrier {BARRIER_ID} with two plans for "
            + ", ".join(duplicated)
            + "; one round holds one plan per destination"
        )
    if not expected_destinations:
        raise PlanCheckError(
            f"{unit_id} entered barrier {BARRIER_ID} with no expected "
            "destination; the round's participants are the harness's to declare, "
            "and a barrier over an undeclared set is the assumption B1 exists to "
            "refuse"
        )
    represented = frozenset(named)
    if represented != expected_destinations:
        missing = sorted(item.value for item in expected_destinations - represented)
        unexpected = sorted(item.value for item in represented - expected_destinations)
        raise PlanCheckError(
            f"{unit_id} entered barrier {BARRIER_ID} round {round_index} with "
            + (f"no plan for {', '.join(missing)}" if missing else "")
            + ("; and " if missing and unexpected else "")
            + (f"a plan for {', '.join(unexpected)}, which this round does not "
               "expect" if unexpected else "")
            + f"; §0.2 runs V-P03 only when every destination that has not been "
            "skipped holds a passed plan, so a round that compares a subset has "
            "not established I-07 for the unit and a round that compares a "
            "stranger did not compare this unit"
        )
    by_plan = {verdict.approved_plan_ref: verdict for verdict in verdicts}
    for plan in plans:
        if plan.unit_id != unit_id:
            raise PlanCheckError(
                f"{plan.plan_id} belongs to {plan.unit_id!r} and entered the "
                f"barrier of {unit_id!r}; V-P03 is about one unit's destinations"
            )
        if plan.stage_of_version is not PlanStage.APPROVED:
            raise PlanCheckError(
                f"{plan.plan_id} is {plan.stage_of_version.value} and entered "
                f"barrier {BARRIER_ID}; §0.2 runs V-P03 only when every "
                "destination that has not been skipped holds a plan that has "
                "passed its per-destination checks"
            )
        verdict = by_plan.get(plan.plan_ref)
        if verdict is None:
            raise PlanCheckError(
                f"{plan.plan_id} entered barrier {BARRIER_ID} with no verdict "
                "approving it; an approved plan without the verdict that "
                "approved it is an approval nobody can read back"
            )
        if not approval_holds(verdict, boundary):
            raise PlanCheckError(
                f"{verdict.verdict_id} approved {plan.plan_id} against "
                f"{verdict.boundary_ref!r} and the barrier is running against "
                f"({boundary.boundary_id!r}, {boundary.version}); F-4 re-runs the "
                "code checks on a new boundary version, and comparing plans whose "
                "approval no longer holds would carry a stale one past the "
                "barrier"
            )


def _refused(
    *,
    plan: ExecutablePlan,
    boundary: InterpretationBoundary,
    checks: Mapping[str, LoadedCheck],
    code_findings: Mapping[str, tuple[Finding, ...]],
    soft: CheckResult,
    counters: AttemptCounterLedger,
    scope_key: str,
    terminal: bool,
    calls: int,
) -> PlanCheckDecision:
    """The verdict for a plan a hard check refused, and the route it takes.

    The route belongs to the **first** failing check in the order V-P01, V-P02,
    V-P04: one failure is one route, and a plan two checks refused goes back for
    the first reason a reader of the check records would meet. The state code is
    that check's, so V-P02 keeps the map's own row and the skip rate stays
    readable by reason.

    ``terminal`` overrides the order, and only it does: a tier-1 hard platform
    rule with no compliant variant ends the destination whatever else was found,
    because there is no plan S-08 could come back with. Nothing is routed then —
    ``L_strategy`` buys attempts, and an attempt that cannot comply is not one.
    """

    failing = [
        identity for identity in PLAN_CHECKS if code_findings.get(identity)
    ]
    first = failing[0]
    if terminal:
        outcome = OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.HARD_PLATFORM_POLICY_FORBIDS,
            scope=OutcomeScope.DESTINATION,
            scope_key=scope_key,
            reason=(
                f"V-P04 found a tier-1 hard platform rule {plan.plan_id} violates "
                "with no compliant variant; the destination ends here rather than "
                "returning to S-08 for a plan no adaptation could make compliant"
            ),
        )
    else:
        outcome = counters.route(
            source=STAGE,
            cause=CHECK_FAILED_CAUSE,
            scope_key=scope_key,
            state_code=_CHECK_STATES[first],
            reason=(
                f"{first} refused {plan.plan_id}: "
                f"{code_findings[first][0].detail}"
            ),
        )
    results: list[CheckResult] = []
    for identity in PLAN_CHECKS:
        if identity == "V-P05":
            results.append(soft)
            continue
        findings = code_findings.get(identity, ())
        method = (
            CheckMethod.CODE
            if identity == "V-P02" or calls == 0
            else CheckMethod.CODE_AND_MODEL
        )
        if findings:
            results.append(
                _result(
                    checks[identity],
                    method,
                    CheckOutcome.FAIL,
                    findings,
                    route=None if terminal else CHECK_FAILED_CAUSE,
                )
            )
            continue
        if calls == 0 and identity != "V-P02":
            results.append(
                _result(
                    checks[identity],
                    CheckMethod.CODE,
                    CheckOutcome.NOT_ANSWERED,
                    (
                        Finding(
                            detail=(
                                f"{identity}'s code half found nothing and its "
                                "model half was not asked: a hard check had "
                                "already refused this plan version, and §3 makes "
                                "one call per plan version at most"
                            ),
                            refs=(plan.plan_id,),
                        ),
                    ),
                )
            )
            continue
        results.append(_passed(checks[identity], method))
    return PlanCheckDecision(
        unit_id=plan.unit_id,
        destination=plan.destination,
        verdict=PlanVerdict(
            verdict_id=verdict_id(plan.plan_id),
            version=1,
            unit_id=plan.unit_id,
            destination=plan.destination,
            plan_ref=plan.plan_ref,
            boundary_ref=(boundary.boundary_id, boundary.version),
            checks=tuple(results),
            result=VerdictResult.FAIL,
            outcome=outcome,
        ),
        outcomes=(outcome,),
        calls=calls,
    )


def _unanswered(
    *,
    plan: ExecutablePlan,
    boundary: InterpretationBoundary,
    checks: Mapping[str, LoadedCheck],
    soft: CheckResult,
    scope_key: str,
) -> PlanCheckDecision:
    """The verdict for a plan whose one call produced nothing readable.

    Every code half passed and the two checks that also have a model half were
    never answered. That is a ``fail`` — a verdict passes where every hard check
    **passed** — and a ``SKIP`` rather than a route back to S-08: nothing was
    found wrong with the plan, so sending it back would spend ``L_strategy`` on
    a provider outage and eventually skip the destination for a reason that was
    never about the material.
    """

    reason = Finding(
        detail=(
            "the plan check call produced no answer this stage may read; the "
            "check did not run, which is not the same as the check finding "
            "nothing"
        ),
        refs=(plan.plan_id,),
    )
    outcome = OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=StateCode.PLAN_CHECK_UNAVAILABLE,
        scope=OutcomeScope.DESTINATION,
        scope_key=scope_key,
        reason=(
            f"V-P01 and V-P04 could not be answered for {plan.plan_id}, so no "
            "approved plan exists for this destination"
        ),
    )
    return PlanCheckDecision(
        unit_id=plan.unit_id,
        destination=plan.destination,
        verdict=PlanVerdict(
            verdict_id=verdict_id(plan.plan_id),
            version=1,
            unit_id=plan.unit_id,
            destination=plan.destination,
            plan_ref=plan.plan_ref,
            boundary_ref=(boundary.boundary_id, boundary.version),
            checks=(
                _result(
                    checks["V-P01"],
                    CheckMethod.CODE,
                    CheckOutcome.NOT_ANSWERED,
                    (reason,),
                ),
                _passed(checks["V-P02"], CheckMethod.CODE),
                _result(
                    checks["V-P04"],
                    CheckMethod.CODE,
                    CheckOutcome.NOT_ANSWERED,
                    (reason,),
                ),
                soft,
            ),
            result=VerdictResult.FAIL,
            outcome=outcome,
        ),
        outcomes=(outcome,),
        calls=1,
    )


def _passed(check: LoadedCheck, method: CheckMethod) -> CheckResult:
    return _result(check, method, CheckOutcome.PASS, ())


def _result(
    check: LoadedCheck,
    method: CheckMethod,
    outcome: CheckOutcome,
    findings: tuple[Finding, ...],
    *,
    route: Optional[str] = None,
) -> CheckResult:
    """One CheckResult, with the record's class and status as the loader read them."""

    record = check.check
    if record.check_class is None or record.rule_status is None:
        raise PlanCheckError(
            f"{check.identity} states no class or no rule status; a CheckResult "
            "records both 'at the time of the run', and a check whose own record "
            "does not say what it is cannot be applied"
        )
    try:
        check_class = CheckClass(record.check_class)
        rule_status = KnowledgeStatus(record.rule_status)
    except ValueError as unknown:
        raise PlanCheckError(
            f"{check.identity} states class {record.check_class!r} and status "
            f"{record.rule_status!r}, which Step 4 §2.3 and §3 do not define: "
            f"{unknown}"
        ) from None
    return CheckResult(
        check_id=check.identity,
        check_class=check_class,
        rule_status=rule_status,
        method=method,
        result=outcome,
        findings=findings,
        route=route,
    )


def _judged(
    answer: PlanCheckAnswer,
    plan: ExecutablePlan,
    contract: AdaptationContract,
) -> Optional[tuple[tuple[Finding, ...], tuple[Finding, ...]]]:
    """V-P01's and V-P04's model halves, as findings — or ``None`` if unreadable.

    An answer that says two fields cannot both hold and names neither, or that
    reports a construction against a rule the contract does not forbid, has not
    answered the question it was asked. It is refused rather than partly used:
    a finding nobody can route by rule is a finding that would be routed by
    whoever read it.
    """

    if answer.fields_hold == (answer.conflict is not None):
        return None
    forbidden = {
        item.rule_ref: item
        for item in contract.forbidden
        if item.kind is ForbiddenKind.CONSTRUCTION
    }
    segments = {segment.name for segment in plan.segments}
    construction: list[Finding] = []
    for reported in answer.forbidden_constructions:
        rule = forbidden.get(reported.rule_ref)
        if rule is None or reported.segment not in segments:
            return None
        construction.append(
            Finding(
                detail=(
                    f"the segment {reported.segment!r} executes a construction "
                    f"the contract forbids: {reported.detail}"
                ),
                refs=(plan.plan_id,),
                rule_ref=rule.rule_ref,
                tier=rule.tier,
            )
        )
    fields: tuple[Finding, ...] = ()
    if answer.conflict is not None:
        fields = (
            Finding(
                detail=(
                    f"{answer.conflict.first_field} and "
                    f"{answer.conflict.second_field} cannot both hold: "
                    f"{answer.conflict.detail}"
                ),
                refs=(plan.plan_id,),
            ),
        )
    return fields, tuple(construction)


def _deviating(
    answer: BarrierAnswer, compared: Sequence[Destination]
) -> Optional[tuple[tuple[Destination, ...], tuple[Finding, ...]]]:
    """Which destinations V-P03 sends back, or ``None`` if the answer is not one.

    Coverage is the whole readability check, for the reason S-06's anchor call
    is checked for it: a round that judged four of five plans has not compared
    the unit, and reading its silence about the fifth as "it carries the anchor"
    is how an unasked question passes as a verdict.
    """

    expected = list(compared)
    judged = [row.destination for row in answer.plans]
    if sorted(item.value for item in judged) != sorted(
        item.value for item in expected
    ):
        return None
    if len(set(judged)) != len(judged):
        return None
    named: list[Destination] = []
    findings: list[Finding] = []
    for row in answer.plans:
        if row.carries_anchor:
            continue
        if row.detail is None or not row.detail.strip():
            return None
        named.append(row.destination)
        findings.append(
            Finding(
                detail=(
                    f"the plan for {row.destination.value} does not carry the "
                    f"unit's anchor: {row.detail}"
                ),
                refs=(row.destination.value,),
            )
        )
    for pair in answer.contradictions:
        involved = set(pair.destinations)
        if not involved or not involved.issubset(set(expected)):
            return None
        if pair.deviating not in involved:
            return None
        findings.append(
            Finding(
                detail=(
                    "the plans for "
                    + ", ".join(sorted(item.value for item in involved))
                    + " assert things that cannot both hold; "
                    f"{pair.deviating.value} is the one that deviated: "
                    f"{pair.detail}"
                ),
                refs=tuple(sorted(item.value for item in involved)),
            )
        )
        if pair.deviating not in named:
            named.append(pair.deviating)
    return tuple(named), tuple(findings)


def _plan_request(
    *,
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    contract: AdaptationContract,
) -> str:
    """What the per-destination call sees: one plan, and the two questions.

    No sibling's plan and no sibling's text: comparing destinations is V-P03's
    at the barrier, and a request that carried a sibling here would make one
    destination's check an answer about another (I-06).
    """

    return json.dumps({
        "destination": plan.destination.value,
        "plan": {
            "plan_id": plan.plan_id,
            "format": plan.format.value,
            "length_target": plan.length_target.as_entity(),
            "first_line_mechanics": plan.first_line_mechanics,
            "segments": [segment.as_entity() for segment in plan.segments],
            "subheadings": plan.subheadings,
            "hashtags": (
                None if plan.hashtags is None else plan.hashtags.as_entity()
            ),
            "citations": list(plan.citations),
        },
        "strategy": {
            "strategy_id": strategy.strategy_id,
            "thesis": strategy.editorial_thesis.text,
            "focal_subject": strategy.focal_subject.text,
            "reader_path": [
                {"index": index, **move.as_entity()}
                for index, move in enumerate(strategy.reader_path, 1)
            ],
            "opening": strategy.opening.as_entity(),
            "reveal": strategy.reveal.as_entity(),
            "concession": strategy.concession.as_entity(),
            "ending_intention": strategy.ending_intention,
        },
        "forbidden_constructions": [
            {
                "rule_ref": item.rule_ref,
                "value": item.value,
                "tier": item.tier.value,
            }
            for item in contract.forbidden
            if item.kind is ForbiddenKind.CONSTRUCTION
        ],
    })


def _barrier_request(
    *,
    anchor: Anchor,
    plans: Sequence[ExecutablePlan],
    boundary: InterpretationBoundary,
) -> str:
    """What the barrier call sees: the anchor, and every plan of the unit.

    The plans and not the texts, because there are none yet — that is what the
    barrier is for — and the anchor's statement, because V-P03's first question
    is whether each plan still asks the reader to believe it.
    """

    member = boundary.member(anchor.interpretation_id)
    return json.dumps({
        "unit_id": anchor.unit_id,
        "anchor": {
            "interpretation_id": anchor.interpretation_id,
            "statement": None if member is None else member.statement,
        },
        "plans": [
            {
                "destination": plan.destination.value,
                "plan_id": plan.plan_id,
                "format": plan.format.value,
                "first_line_mechanics": plan.first_line_mechanics,
                "segments": [segment.as_entity() for segment in plan.segments],
                "citations": list(plan.citations),
            }
            for plan in plans
        ],
    })


def _plan_answer(
    transport: PlanCheckTransport, request: str
) -> Optional[PlanCheckAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(
            instructions=PLAN_CHECK_INSTRUCTIONS, request=request
        )
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return PlanCheckAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _barrier_answer(
    transport: BarrierTransport, request: str
) -> Optional[BarrierAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(instructions=BARRIER_INSTRUCTIONS, request=request)
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return BarrierAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _spend(budget: Optional[CallBudget], scope_key: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.DESTINATION, scope_key=scope_key)


def _spend_unit(budget: Optional[CallBudget], unit_id: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.UNIT, scope_key=unit_id)
