"""Issue #305: an approved, checked plan per destination before any prose.

SL-5's acceptance evidence for S-10 and S-11, on the same walkthrough B material
as #304 (map §13, "Ramp Launches Instant Stablecoin Payments with Stripe's New
Technology") — the case V-P02 was written against, where the boundary held two
admissible readings and a short-form candidate promised "3 things".

The issue's three acceptance criteria, and the tests that are them:

1. **the Ramp "3 things" candidate is excluded by V-P02** —
   ``test_the_three_things_plan_is_excluded_by_v_p02``, with the boundary that
   admits it in ``test_a_promise_the_boundary_admits_passes_v_p02`` and the
   version drift in ``test_v_p02_is_re_run_against_the_boundary_in_front_of_s11``;
2. **V-P03 re-plans only the deviating destination** —
   ``test_v_p03_replans_only_the_deviating_destination``, with
   ``test_a_barrier_round_that_passes_routes_nothing`` and
   ``test_a_barrier_round_nobody_could_answer_does_not_pass`` for the two ways
   it must not fire;
3. **every approved plan has a resolvable chain thesis → interpretation →
   evidence claim → observation (I-04)** —
   ``test_every_approved_plan_carries_a_resolvable_chain``, with
   ``test_a_chain_that_does_not_resolve_is_not_approved``.

And the properties they rest on: no E-13 field on E-14 (the
decision-vs-adaptation criterion), citations computed from the core, a
cross-destination link that is always conditional (R-2), the structural route
out of S-10, a check that could not be answered never read as a pass, I-12 for
V-P05, the tier that decides V-P04's route, and an approval that does not
survive a boundary commit (F-4).
"""

from __future__ import annotations

import ast
import dataclasses
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from scripts.ci.check_ce1_placement import check_module
from src.editorial_core.anchor import (
    Anchor,
    AnchorCandidate,
    LeadingItem,
    LeadingMaterialKind,
    anchor_id,
)
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    KnowledgeRef,
    KnowledgeStatus,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
    permitted_outcomes,
)
from src.editorial_core.candidate_strategies import (
    STRATEGY_FIELDS,
    Concession,
    EditorialStrategy,
    FieldJustification,
    FocalSubject,
    FocalSubjectKind,
    Move,
    Opening,
    Reveal,
    RevealKind,
    Thesis,
    candidate_set_id,
    strategy_id,
)
from src.editorial_core.destinations import (
    Destination,
    DestinationDecision,
    DestinationMode,
    Eligibility,
    ModeRule,
    PublicationDependency,
    decision_id,
    destination_scope_key,
)
from src.editorial_core.editorial_units import EditorialUnit, create_unit
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
)
from src.editorial_core.executable_plan import (
    ADAPTATION_CAUSE,
    APPROVED_VERSION,
    DRAFT_VERSION,
    STAGE as PLAN_STAGE,
    STRATEGY_COUNTER,
    AdaptationContract,
    DestinationRules,
    ExecutablePlan,
    FixedSlot,
    ForbiddenItem,
    ForbiddenKind,
    Hashtags,
    HashtagPolicy,
    LengthTarget,
    LengthUnit,
    PlanError,
    PlanFormat,
    PlanStage,
    PlatformRule,
    adapt_strategy,
    citations_from_core,
    plan_id,
    plan_relative_path,
    write_plan,
)
from src.editorial_core.interpretation_boundary import (
    InadmissibleReason,
    Interpretation,
    InterpretationBoundary,
    InterpretationKind,
    Justification,
    Limitation,
    ProbeApplication,
    ProbeFinding,
    ReaderConnection,
    boundary_id,
)
from src.editorial_core.plan_check import (
    BARRIER_CHECK,
    BARRIER_ID,
    CHECK_FAILED_CAUSE,
    DEVIATION_CAUSE,
    PLAN_CHECKS,
    STAGE as CHECK_STAGE,
    BarrierRound,
    CheckClass,
    CheckMethod,
    CheckOutcome,
    CheckResult,
    Finding,
    PlanCheckError,
    PlanFingerprint,
    PlanVerdict,
    ReferenceItem,
    VerdictResult,
    approval_holds,
    barrier_round_relative_path,
    check_plan,
    plan_check_records,
    recheck_after_boundary_commit,
    resolve_chain,
    run_barrier,
    verdict_relative_path,
    write_approved_plan,
    write_barrier_round,
    write_plan_verdict,
)
from src.editorial_core.relevance_screen import AudienceTransfer, DecisionRef
from src.editorial_core.strategy_selection import StrategySelection, selection_id
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.knowledge.loader import load_register
from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
)
from src.run.boundary_commit import Admissibility
from src.run.run_context import create_run_id
from src.run.run_summary import ReasonCategory, reason_category
from src.run.run_workspace import RunWorkspace, owner_of

_REPO_ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 24)

LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

SIGNAL = "signal-305-ramp"
CORE = "core-305-ramp"

CLAIMS: dict[str, str] = {
    "ev-1": "The vendor states the payment settles in minutes rather than days.",
    "ev-2": "The filing records the settlement network the payment runs over.",
    "ev-3": "A trade report puts the prior settlement time at two days.",
}

MECHANISM = "int-305-mechanism"
TIMELINE = "int-305-timeline"
REFUSED = "int-305-refused"

VOICE = "voice-doc-v3"


# ===========================================================================
# Fixtures
# ===========================================================================


def _core() -> EvidenceCore:
    observations = tuple(
        SourceObservation(
            observation_id=f"obs-{identity}",
            signal_id=SIGNAL,
            source_ref="src-1",
            kind=ObservationKind.QUOTE,
            excerpt=statement,
            attribution=f"Example Press reports: {statement}",
            is_third_party_assertion=False,
        )
        for identity, statement in CLAIMS.items()
    )
    claims = tuple(
        EvidenceClaim(
            evidence_claim_id=identity,
            statement=statement,
            observation_refs=(f"obs-{identity}",),
            source_refs=("src-1",),
            verdict=EvidenceDisposition.ACCEPTED,
            verdict_rationale="The cited excerpt states it.",
            scope="One named vendor, as reported.",
            strength=LADDER.at(2),
            ceiling=LADDER.at(2),
        )
        for identity, statement in CLAIMS.items()
    )
    return EvidenceCore(
        core_id=CORE,
        version=1,
        signal_ids=(SIGNAL,),
        research_artifact_refs=(("artifact-305", "sha256:" + "d" * 64),),
        sources=(
            NormalizedSource(
                source_id="src-1",
                locator=SourceLocator(
                    kind=SourceLocatorKind.URL, value="https://example.test/item"
                ),
                title="Recorded report",
                publisher="Example Press",
                publication_time=PublicationTime(
                    status=PublicationTimeStatus.KNOWN, value=NOW
                ),
                retrieved_at=NOW,
            ),
        ),
        observations=observations,
        evidence_claims=claims,
        readiness=EvidenceReadiness.READY,
    )


def _interpretation(
    identity: str,
    statement: str,
    *,
    supports: Sequence[str],
    admissible: bool = True,
    kind: InterpretationKind = InterpretationKind.MECHANISM,
) -> Interpretation:
    return Interpretation(
        interpretation_id=identity,
        version=1,
        statement=statement,
        kind=kind,
        support_refs=tuple(supports),
        audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
        strength=LADDER.at(2),
        ceiling=LADDER.at(2),
        admissibility=(
            Admissibility.ADMISSIBLE if admissible else Admissibility.INADMISSIBLE
        ),
        rationale=Justification(
            text="The cited claims state it.", refs=tuple(supports[:1])
        ),
        inadmissible_reason=None if admissible else InadmissibleReason.UNSUPPORTED,
        temptation_note=None if admissible else "It reads as the bigger story.",
    )


def _boundary(
    members: Sequence[Interpretation], *, version: int = 1
) -> InterpretationBoundary:
    return InterpretationBoundary(
        boundary_id=boundary_id(CORE),
        version=version,
        core_ref=(CORE, 1),
        relevance_ref=DecisionRef(
            path="reports/content_packages/signal-305/decision.json",
            digest="sha256:" + "e" * 64,
        ),
        members=tuple(members),
        probes=(
            ProbeApplication(
                record_id="K-TEMPT-01",
                finding=ProbeFinding.NONE_FOUND,
                note="No inflated benefit was proposed.",
            ),
        ),
        outcome=OutcomeRecord(
            outcome=ArpOutcome.RESOLVE,
            state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
            scope=OutcomeScope.SIGNAL,
            scope_key=SIGNAL,
            reason="the boundary admits the readings the evidence supports",
        ),
        reader_connection=ReaderConnection(
            text="The reader moves money and waits for it to settle.",
            refs=("ev-1",),
        ),
        limits=(
            Limitation(
                text="The material says nothing about the cost of switching.",
                refs=("ev-3",),
            ),
        ),
    )


def _two_readings() -> InterpretationBoundary:
    """The boundary S-10 normally meets: two admissible readings, one refused."""

    return _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
            ),
            _interpretation(
                TIMELINE,
                "The wait fell from two days to minutes.",
                supports=("ev-1", "ev-3"),
                kind=InterpretationKind.COMPARISON,
            ),
            _interpretation(
                REFUSED,
                "Every business that switches will pay less.",
                supports=(),
                admissible=False,
                kind=InterpretationKind.GENERALIZATION,
            ),
        )
    )


def _one_reading() -> InterpretationBoundary:
    """Version 2: a commit has made the comparison inadmissible."""

    return _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
            ),
            _interpretation(
                TIMELINE,
                "The wait fell from two days to minutes.",
                supports=("ev-1", "ev-3"),
                admissible=False,
                kind=InterpretationKind.COMPARISON,
            ),
        ),
        version=2,
    )


def _unit(boundary: Optional[InterpretationBoundary] = None) -> EditorialUnit:
    return create_unit(core=_core(), boundary=boundary or _two_readings())


def _anchor(
    unit: EditorialUnit, boundary: Optional[InterpretationBoundary] = None
) -> Anchor:
    snapshot = boundary or _two_readings()
    return Anchor(
        anchor_id=anchor_id(unit.unit_id),
        version=1,
        unit_id=unit.unit_id,
        interpretation_ref=(MECHANISM, 1),
        boundary_ref=(snapshot.boundary_id, snapshot.version),
        strength_used=LADDER.at(2),
        leading_material=(
            LeadingItem(ref="ev-1", kind=LeadingMaterialKind.EVIDENCE_CLAIM),
        ),
        candidates=(
            AnchorCandidate(
                interpretation_id=MECHANISM,
                chosen=True,
                reason="the mechanism is what the filing records",
            ),
            AnchorCandidate(
                interpretation_id=TIMELINE,
                chosen=False,
                reason="the comparison rests on one trade report",
            ),
        ),
        ambiguity_touches_anchor=False,
        outcome=OutcomeRecord(
            outcome=ArpOutcome.RESOLVE,
            state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
            scope=OutcomeScope.UNIT,
            scope_key=unit.unit_id,
            reason="the mechanism is the unit's anchor",
        ),
    )


def _decision(
    unit: EditorialUnit,
    destination: Destination = Destination.LINKEDIN,
    *,
    dependencies: Sequence[PublicationDependency] = (),
    dropped: Sequence[Destination] = (),
) -> DestinationDecision:
    return DestinationDecision(
        destination_decision_id=decision_id(unit.unit_id, destination),
        unit_id=unit.unit_id,
        destination=destination,
        eligibility=Eligibility.ELIGIBLE,
        rule_ref=f"CR-DST-{destination.value.upper()}",
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        mode=DestinationMode.PUBLISH,
        mode_rule=ModeRule.PUBLISHES,
        publication_dependencies=tuple(dependencies),
        dropped_dependencies=tuple(dropped),
    )


_TWO_MOVES: tuple[Move, ...] = (
    Move(
        text="Name the settlement network.",
        purpose="establish the reading",
        refs=(MECHANISM,),
    ),
    Move(
        text="Show what the vendor states about the wait.",
        purpose="carry the reading on the leading material",
        refs=("ev-1",),
    ),
)

#: The "3 things" shape of map §13 B: three moves, each promising a meaning.
#: Every one of them references a reading the thesis rests on, which is what
#: `promised_points` counts — a move that only carries a fact promises no
#: second meaning, so a path whose middle move cited an observation would be
#: two points wearing three headings.
_THREE_POINTS: tuple[Move, ...] = (
    Move(
        text="Point one: the network.",
        purpose="promise a meaning",
        refs=(MECHANISM,),
    ),
    Move(
        text="Point two: the timeline.",
        purpose="promise a second meaning",
        refs=(TIMELINE,),
    ),
    Move(
        text="Point three: what the mechanism means for you.",
        purpose="promise a third meaning",
        refs=(MECHANISM, "ev-1"),
    ),
)

#: The thesis the "3 things" path rests on: both admissible readings.
_BOTH_READINGS: tuple[str, ...] = (MECHANISM, TIMELINE)


def _strategy(
    unit: EditorialUnit,
    destination: Destination = Destination.LINKEDIN,
    *,
    boundary: Optional[InterpretationBoundary] = None,
    moves: Sequence[Move] = _TWO_MOVES,
    thesis_refs: Sequence[str] = (MECHANISM,),
    reveal: Optional[Reveal] = None,
    attempt: int = 1,
) -> EditorialStrategy:
    """One chosen E-13, built directly: S-08 and S-09 are #304's to exercise."""

    snapshot = boundary or _two_readings()
    set_id = candidate_set_id(unit.unit_id, destination, attempt)
    return EditorialStrategy(
        strategy_id=strategy_id(set_id, 1),
        unit_id=unit.unit_id,
        destination=destination,
        candidate_set_id=set_id,
        anchor_ref=anchor_id(unit.unit_id),
        boundary_ref=(snapshot.boundary_id, snapshot.version),
        editorial_job="Explain the mechanism behind the new timeline",
        angle="Why did the wait disappear?",
        editorial_thesis=Thesis(
            text="The settlement network is what removed the wait.",
            interpretation_refs=tuple(thesis_refs),
        ),
        focal_subject=FocalSubject(
            kind=FocalSubjectKind.COMPANY,
            text="The vendor named in the filing",
            refs=("ev-2",),
        ),
        leading_material_ref="ev-1",
        reader_path=tuple(moves),
        opening=Opening(
            text="The filing names the network.",
            held_back="the prior settlement time",
            refs=(MECHANISM,),
        ),
        reveal=reveal or Reveal(kind=RevealKind.IMMEDIATE),
        concession=Concession(present=False),
        ending_intention="Leave the reader with the new timeline, not the fee.",
        justifications=tuple(
            FieldJustification(
                field_name=name,
                justification=Justification(
                    text=f"{name} follows from the anchor and its leading material."
                ),
            )
            for name in STRATEGY_FIELDS
        ),
    )


def _selection(strategy: EditorialStrategy) -> StrategySelection:
    return StrategySelection(
        selection_id=selection_id(strategy.candidate_set_id),
        unit_id=strategy.unit_id,
        destination=strategy.destination,
        candidate_set_id=strategy.candidate_set_id,
        admissible=(strategy.strategy_id,),
        chosen=strategy.strategy_id,
    )


PLATFORM = PlatformRule(
    rule_id="K-DST-LI-11",
    text="A LinkedIn post runs 80–220 words and tolerates hashtags.",
    tier=KnowledgeTier.PLATFORM_RANKING,
)


def _rules(
    destination: Destination = Destination.LINKEDIN,
    *,
    plan_format: PlanFormat = PlanFormat.POST,
    length: Optional[LengthTarget] = None,
    hashtags: HashtagPolicy = HashtagPolicy.ALLOWED,
    segments_max: Optional[int] = None,
    rule: PlatformRule = PLATFORM,
) -> DestinationRules:
    return DestinationRules(
        destination=destination,
        format=plan_format,
        format_rule=rule,
        length=length or LengthTarget(minimum=80, maximum=220, unit=LengthUnit.WORDS),
        length_rule=rule,
        hashtags=hashtags,
        hashtag_rule=rule,
        segments_max=segments_max,
    )


def _contract(
    *,
    forbidden: Sequence[ForbiddenItem] = (),
    slots: Sequence[FixedSlot] = (),
    hashtags: Sequence[str] = (),
) -> AdaptationContract:
    return AdaptationContract(
        voice_brief_ref=VOICE,
        forbidden=tuple(forbidden),
        fixed_slots=tuple(slots),
        hashtags=tuple(hashtags),
    )


class _Transport:
    """One canned answer, and a count of how often it was asked for."""

    def __init__(self, answer: Any, *, fails: bool = False) -> None:
        self.answer = answer
        self.fails = fails
        self.calls = 0
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        self.requests.append(request)
        if self.fails:
            raise RuntimeError("the provider refused")
        if isinstance(self.answer, str):
            return self.answer
        return json.dumps(self.answer)


class _RefusingBudget:
    """A run whose allowance is gone before the call is made (§0.4)."""

    def spend(
        self, *, scope: OutcomeScope, scope_key: str
    ) -> Optional[OutcomeRecord]:
        return OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.BUDGET_EXHAUSTED,
            scope=scope,
            scope_key=scope_key,
            reason="the run's allowance is gone",
        )


def _ledger(**limits: int) -> AttemptCounterLedger:
    return AttemptCounterLedger(limits=limits or None)


def _workspace(tmp_path: Path) -> RunWorkspace:
    return RunWorkspace.create(tmp_path / "editorial_runs", create_run_id())


def _segmentation(
    *,
    segments: Optional[Sequence[dict[str, Any]]] = None,
    first_line: str = "The first line is visible before the 'see more' cut.",
    subheadings: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "segments": [
            dict(segment)
            for segment in (
                segments
                if segments is not None
                else (
                    {
                        "name": "Open on the network",
                        "purpose": "carry the first move",
                        "moves": [1],
                    },
                    {
                        "name": "Show the wait",
                        "purpose": "carry the leading material",
                        "moves": [2],
                    },
                )
            )
        ],
        "first_line_mechanics": first_line,
        "subheadings": subheadings,
    }


PASSING_CHECK: dict[str, Any] = {
    "fields_hold": True,
    "conflict": None,
    "forbidden_constructions": [],
}


CHECKS = plan_check_records(load_register(_REPO_ROOT / "knowledge", today=TODAY))


def _drafted(
    *,
    destination: Destination = Destination.LINKEDIN,
    boundary: Optional[InterpretationBoundary] = None,
    moves: Sequence[Move] = _TWO_MOVES,
    thesis_refs: Sequence[str] = (MECHANISM,),
    answer: Optional[dict[str, Any]] = None,
    rules: Optional[DestinationRules] = None,
    contract: Optional[AdaptationContract] = None,
    decision: Optional[DestinationDecision] = None,
    counters: Optional[AttemptCounterLedger] = None,
    reveal: Optional[Reveal] = None,
    budget: Any = None,
) -> tuple[EditorialStrategy, Any]:
    """Run S-10 and hand back the strategy with the decision it produced."""

    snapshot = boundary or _two_readings()
    unit = _unit(snapshot)
    strategy = _strategy(
        unit,
        destination,
        boundary=snapshot,
        moves=moves,
        thesis_refs=thesis_refs,
        reveal=reveal,
    )
    return strategy, adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=decision or _decision(unit, destination),
        rules=rules or _rules(destination),
        contract=contract or _contract(),
        boundary=snapshot,
        core=_core(),
        counters=counters or _ledger(),
        transport=_Transport(answer or _segmentation()),
        budget=budget,
    )


def _checked(
    *,
    destination: Destination = Destination.LINKEDIN,
    boundary: Optional[InterpretationBoundary] = None,
    moves: Sequence[Move] = _TWO_MOVES,
    thesis_refs: Sequence[str] = (MECHANISM,),
    answer: Optional[dict[str, Any]] = None,
    rules: Optional[DestinationRules] = None,
    contract: Optional[AdaptationContract] = None,
    counters: Optional[AttemptCounterLedger] = None,
    library: Sequence[ReferenceItem] = (),
    portfolio: Sequence[PlanFingerprint] = (),
    check_answer: Optional[Any] = None,
    fails: bool = False,
    budget: Any = None,
) -> tuple[EditorialStrategy, ExecutablePlan, Any]:
    """Run S-10 and then S-11 over its draft."""

    snapshot = boundary or _two_readings()
    resolved_rules = rules or _rules(destination)
    resolved_contract = contract or _contract()
    strategy, drafted = _drafted(
        destination=destination,
        boundary=snapshot,
        moves=moves,
        thesis_refs=thesis_refs,
        answer=answer,
        rules=resolved_rules,
        contract=resolved_contract,
    )
    assert drafted.plan is not None
    return (
        strategy,
        drafted.plan,
        check_plan(
            plan=drafted.plan,
            strategy=strategy,
            boundary=snapshot,
            core=_core(),
            rules=resolved_rules,
            contract=resolved_contract,
            checks=CHECKS,
            counters=counters or _ledger(),
            transport=_Transport(
                check_answer if check_answer is not None else PASSING_CHECK,
                fails=fails,
            ),
            library=library,
            portfolio=portfolio,
            budget=budget,
        ),
    )


# ===========================================================================
# Acceptance 1 · the Ramp "3 things" promise, excluded by V-P02
# ===========================================================================


def test_the_three_things_plan_is_excluded_by_v_p02():
    """Acceptance 1. Three promised points against a boundary that admits two.

    Map §13 B's own case: the short form promises "3 things" where the evidence
    was shown to carry two readings. The plan is built — S-10 adapts what S-09
    chose — and V-P02 refuses it before any prose is paid for, by code and with
    no model call made at all.
    """

    counters = _ledger()
    transport = _Transport(PASSING_CHECK)
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(
        unit, moves=_THREE_POINTS, thesis_refs=_BOTH_READINGS, boundary=boundary
    )
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=counters,
        transport=_Transport(
            _segmentation(
                segments=(
                    {"name": "One", "purpose": "carry move 1", "moves": [1]},
                    {"name": "Two", "purpose": "carry move 2", "moves": [2]},
                    {"name": "Three", "purpose": "carry move 3", "moves": [3]},
                )
            )
        ),
    )
    assert drafted.plan is not None

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(),
        contract=_contract(),
        checks=CHECKS,
        counters=counters,
        transport=transport,
    )

    assert decision.passed is False
    assert decision.approved is None
    assert decision.calls == 0 and transport.calls == 0
    verdict = decision.verdict
    assert verdict is not None and verdict.result is VerdictResult.FAIL
    promise = verdict.check("V-P02")
    assert promise is not None and promise.result is CheckOutcome.FAIL
    assert "3 point(s)" in promise.findings[0].detail
    assert "2 reading(s)" in promise.findings[0].detail
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.REPLAN
    assert outcome.state_code is StateCode.PROMISE_WIDER_THAN_BOUNDARY
    assert outcome.route_target == "S-08"
    assert outcome.counter == STRATEGY_COUNTER


def test_a_promise_the_boundary_admits_passes_v_p02():
    """The same arithmetic at its edge: two points against two readings."""

    _, _, decision = _checked(
        moves=_THREE_POINTS[:2], thesis_refs=_BOTH_READINGS
    )

    assert decision.passed is True
    verdict = decision.verdict
    assert verdict is not None
    promise = verdict.check("V-P02")
    assert promise is not None and promise.result is CheckOutcome.PASS


def test_v_p02_is_re_run_against_the_boundary_in_front_of_s11():
    """A plan keeps no standing from the boundary version it was written under.

    The draft is built against v1, which admits both readings. By the time it
    reaches the check a commit has refused one of them, and the plan that rests
    on it is refused with it — the comparison is made against the version in
    front of S-11, not the one the strategy recorded.
    """

    first = _two_readings()
    unit = _unit(first)
    strategy = _strategy(unit, boundary=first, thesis_refs=(TIMELINE,))
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=first,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=_one_reading(),
        core=_core(),
        rules=_rules(),
        contract=_contract(),
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
    )

    assert decision.passed is False
    verdict = decision.verdict
    assert verdict is not None
    promise = verdict.check("V-P02")
    assert promise is not None and promise.result is CheckOutcome.FAIL
    assert any(TIMELINE in finding.detail for finding in promise.findings)


# ===========================================================================
# Acceptance 2 · V-P03 re-plans only the destination that deviated
# ===========================================================================


def _approved_for(
    destination: Destination, boundary: InterpretationBoundary
) -> tuple[ExecutablePlan, PlanVerdict]:
    unit = _unit(boundary)
    strategy = _strategy(unit, destination, boundary=boundary)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit, destination),
        rules=_rules(destination),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None
    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(destination),
        contract=_contract(),
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
    )
    assert decision.approved is not None and decision.verdict is not None
    return decision.approved, decision.verdict


_UNIT_DESTINATIONS = (
    Destination.WIX,
    Destination.LINKEDIN,
    Destination.TELEGRAM,
)


def _unit_plans(
    boundary: InterpretationBoundary,
) -> tuple[tuple[ExecutablePlan, ...], tuple[PlanVerdict, ...]]:
    approved = [_approved_for(item, boundary) for item in _UNIT_DESTINATIONS]
    return tuple(plan for plan, _ in approved), tuple(
        verdict for _, verdict in approved
    )


def _barrier_answer(deviating: Optional[Destination] = None) -> dict[str, Any]:
    return {
        "plans": [
            {
                "destination": item.value,
                "carries_anchor": item is not deviating,
                "detail": (
                    None
                    if item is not deviating
                    else "the plan asks the reader to believe the comparison"
                ),
            }
            for item in _UNIT_DESTINATIONS
        ],
        "contradictions": [],
    }


def test_v_p03_replans_only_the_deviating_destination():
    """Acceptance 2. One destination drifts; the other two keep their approval."""

    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)
    counters = _ledger()

    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=counters,
        transport=_Transport(_barrier_answer(Destination.TELEGRAM)),
    )

    assert barrier.passed is False
    assert barrier.deviating == (Destination.TELEGRAM,)
    assert barrier.destinations == _UNIT_DESTINATIONS
    assert len(barrier.outcomes) == 1
    routed = barrier.outcomes[0]
    assert routed.outcome is ArpOutcome.REPLAN
    assert routed.state_code is StateCode.DESTINATIONS_CONTRADICT
    assert routed.route_target == "S-08"
    assert routed.scope_key == destination_scope_key(
        unit.unit_id, Destination.TELEGRAM
    )
    # The others keep their approval: nothing spent their counter, and their
    # verdicts are untouched.
    for destination in (Destination.WIX, Destination.LINKEDIN):
        key = destination_scope_key(unit.unit_id, destination)
        assert counters.used(STRATEGY_COUNTER, key) == 0
    assert all(
        verdict.result is VerdictResult.PASS
        and approval_holds(verdict, boundary)
        for verdict in verdicts
    )
    assert barrier.check.check_id == BARRIER_CHECK
    assert barrier.check.route == DEVIATION_CAUSE


def test_a_contradiction_sends_back_only_the_destination_it_names():
    """The second V-P03 question, and the same rule: one of the pair goes back."""

    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)
    answer = _barrier_answer()
    answer["contradictions"] = [
        {
            "destinations": [Destination.WIX.value, Destination.LINKEDIN.value],
            "deviating": Destination.LINKEDIN.value,
            "detail": "one says the fee fell and the other that it did not",
        }
    ]

    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(answer),
    )

    assert barrier.deviating == (Destination.LINKEDIN,)
    assert [outcome.scope_key for outcome in barrier.outcomes] == [
        destination_scope_key(unit.unit_id, Destination.LINKEDIN)
    ]


def test_a_barrier_round_that_passes_routes_nothing():
    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)

    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(_barrier_answer()),
    )

    assert barrier.passed is True
    assert barrier.outcomes == ()
    assert barrier.calls == 1


def test_a_barrier_round_nobody_could_answer_does_not_pass():
    """Fail closed: an unanswered V-P03 is not a barrier that opened."""

    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)

    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK, fails=True),
    )

    assert barrier.passed is False
    assert barrier.deviating == ()
    assert barrier.check.result is CheckOutcome.NOT_ANSWERED
    assert barrier.outcomes[0].state_code is StateCode.PLAN_CHECK_UNAVAILABLE
    assert barrier.outcomes[0].scope is OutcomeScope.UNIT
    assert "the provider refused" not in (barrier.outcomes[0].reason or "")


def test_a_round_that_judged_fewer_plans_than_it_compared_is_refused():
    """Coverage is the check: a plan nobody judged is not a plan that passed."""

    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)
    answer = _barrier_answer()
    answer["plans"] = answer["plans"][:2]

    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(answer),
    )

    assert barrier.passed is False
    assert barrier.check.result is CheckOutcome.NOT_ANSWERED


def test_the_barrier_refuses_a_plan_whose_approval_no_longer_holds():
    """F-4 at the barrier: a stale approval does not reach the comparison."""

    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)

    with pytest.raises(PlanCheckError) as refusal:
        run_barrier(
            unit_id=unit.unit_id,
            anchor=_anchor(unit, boundary),
            plans=plans,
            verdicts=verdicts,
            boundary=_one_reading(),
            checks=CHECKS,
            counters=_ledger(),
            transport=_Transport(_barrier_answer()),
        )

    assert "approval no longer holds" in str(refusal.value)


def test_the_barrier_refuses_a_draft():
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None

    with pytest.raises(PlanCheckError):
        run_barrier(
            unit_id=unit.unit_id,
            anchor=_anchor(unit, boundary),
            plans=(drafted.plan,),
            verdicts=(),
            boundary=boundary,
            checks=CHECKS,
            counters=_ledger(),
            transport=_Transport(_barrier_answer()),
        )


# ===========================================================================
# Acceptance 3 · every approved plan resolves I-04
# ===========================================================================


def test_every_approved_plan_carries_a_resolvable_chain():
    """Acceptance 3. Thesis → interpretation → evidence claim → observation.

    Recorded on the verdict, and every reference in it resolves in the records
    the run holds: the reading is admissible in this boundary version, the
    claims are usable claims of this core, and the observations are the core's.
    """

    core = _core()
    boundary = _two_readings()
    strategy, _, decision = _checked(boundary=boundary)

    assert decision.passed is True
    verdict = decision.verdict
    assert verdict is not None and verdict.chain is not None
    chain = verdict.chain
    assert chain.thesis_ref == strategy.strategy_id
    assert [link.interpretation_ref for link in chain.links] == [MECHANISM]
    usable = {claim.evidence_claim_id for claim in core.usable_claims}
    observed = {item.observation_id for item in core.observations}
    for link in chain.links:
        member = boundary.member(link.interpretation_ref)
        assert member is not None and member.admissible
        assert link.evidence_claim_refs
        assert set(link.evidence_claim_refs) <= usable
        assert link.observation_refs
        assert set(link.observation_refs) <= observed


def test_a_chain_that_does_not_resolve_is_not_approved():
    """The other direction: a reading the boundary no longer admits breaks it."""

    chain, findings = resolve_chain(
        _strategy(_unit(), thesis_refs=(TIMELINE,)), _one_reading(), _core()
    )

    assert chain is None
    assert findings and TIMELINE in findings[0].detail


def test_a_verdict_cannot_pass_without_a_chain():
    """The record refuses it, so an approval that cannot show I-04 is not one."""

    with pytest.raises(PlanCheckError) as refusal:
        PlanVerdict(
            verdict_id="pv-plan-x",
            version=1,
            unit_id="unit-x",
            destination=Destination.LINKEDIN,
            plan_ref=("plan-x", DRAFT_VERSION),
            boundary_ref=("bnd-x", 1),
            checks=(
                CheckResult(
                    check_id="V-P02",
                    check_class=CheckClass.HARD,
                    rule_status=KnowledgeStatus.INVARIANT,
                    method=CheckMethod.CODE,
                    result=CheckOutcome.PASS,
                ),
            ),
            result=VerdictResult.PASS,
            approved_plan_ref=("plan-x", APPROVED_VERSION),
        )

    assert "resolves no chain" in str(refusal.value)


# ===========================================================================
# S-10 · the decision-vs-adaptation criterion
# ===========================================================================


def test_e14_holds_no_field_e13_decided():
    """The criterion, as a shape: the plan cannot state a changed E-13 field.

    "Adaptation may not change any E-13 field" is not a rule S-10 remembers —
    every one of those fields is reached through ``strategy_ref``, and there is
    nowhere on E-14 to write a different value for one.
    """

    plan_fields = {field.name for field in dataclasses.fields(ExecutablePlan)}
    decided = {
        "editorial_job",
        "angle",
        "editorial_thesis",
        "focal_subject",
        "leading_material_ref",
        "reader_path",
        "opening",
        "reveal",
        "concession",
        "ending_intention",
        "second_interpretation_ref",
        "client_position_ref",
    }

    assert plan_fields & decided == set()
    assert "strategy_ref" in plan_fields


def test_the_adaptation_call_decides_the_segments_and_the_first_line_only():
    """§3's Decider column, read off the answer the call may give."""

    from src.editorial_core.executable_plan import SegmentationAnswer

    assert set(SegmentationAnswer.model_fields) == {
        "segments",
        "first_line_mechanics",
        "subheadings",
    }


def test_the_draft_is_v1_and_carries_no_exemplar():
    _, drafted = _drafted()

    plan = drafted.plan
    assert plan is not None
    assert plan.version == DRAFT_VERSION
    assert plan.stage_of_version is PlanStage.DRAFT
    assert plan.exemplars == ()
    assert plan.supersedes is None
    assert drafted.calls == 1


def test_every_move_is_carried_by_a_segment():
    strategy, drafted = _drafted()

    plan = drafted.plan
    assert plan is not None
    assert plan.carried_moves == frozenset({1, 2})
    assert len(strategy.reader_path) == 2


def test_a_segmentation_that_drops_a_move_is_not_a_plan():
    _, drafted = _drafted(
        answer=_segmentation(
            segments=({"name": "Only one", "purpose": "carry move 1", "moves": [1]},)
        )
    )

    assert drafted.plan is None
    outcome = drafted.outcomes[0]
    assert outcome.state_code is StateCode.PLAN_GENERATION_FAILED
    assert outcome.outcome is ArpOutcome.SKIP
    assert "uncarried" in (outcome.reason or "")


def test_a_segment_that_carries_nothing_is_not_a_segment():
    _, drafted = _drafted(
        answer=_segmentation(
            segments=(
                {"name": "Open", "purpose": "carry both moves", "moves": [1, 2]},
                {"name": "Empty", "purpose": "carry nothing", "moves": []},
            )
        )
    )

    assert drafted.plan is None
    assert drafted.outcomes[0].state_code is StateCode.PLAN_GENERATION_FAILED


def test_the_citations_come_only_from_the_core():
    strategy, drafted = _drafted()

    plan = drafted.plan
    assert plan is not None
    core = _core()
    known = {source.source_id for source in core.sources}
    assert plan.citations
    assert set(plan.citations) <= known
    assert plan.citations == citations_from_core(strategy, _two_readings(), core)


def test_the_cross_destination_link_is_always_conditional():
    """R-2: there is no field that makes a link required, and the entity says so."""

    _, drafted = _drafted(
        decision=_decision(
            _unit(),
            Destination.LINKEDIN,
            dependencies=(PublicationDependency(target=Destination.WIX),),
        )
    )

    plan = drafted.plan
    assert plan is not None
    link = plan.cross_destination_link
    assert link is not None and link.target is Destination.WIX
    assert link.interpretation_ref == MECHANISM
    assert plan.as_entity()["cross_destination_link"]["conditional"] is True
    link_fields = {
        field.name
        for field in dataclasses.fields(type(link))
    }
    assert link_fields == {"target", "interpretation_ref"}


def test_a_dropped_link_target_produces_no_link():
    """E-12 already knows the target will never publish; no promise is made.

    S-07 records such a target in ``dropped_dependencies`` **instead of** the
    publication dependencies — E-12 refuses one that is in both — so the plan
    has no dependency to follow and promises nothing it cannot deliver.
    """

    decision = _decision(
        _unit(), Destination.LINKEDIN, dropped=(Destination.WIX,)
    )
    _, drafted = _drafted(decision=decision)

    assert decision.dropped_dependencies == (Destination.WIX,)
    assert decision.publication_dependencies == ()
    assert drafted.plan is not None
    assert drafted.plan.cross_destination_link is None


def test_a_reader_path_longer_than_the_format_routes_back_to_s08():
    """§3's ARP: the structural failure, decided before the call is paid for."""

    transport = _Transport(_segmentation())
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, moves=_THREE_POINTS, boundary=boundary)
    counters = _ledger()

    decision = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(
            plan_format=PlanFormat.CAROUSEL,
            length=LengthTarget(minimum=1, maximum=2, unit=LengthUnit.SLIDES),
        ),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=counters,
        transport=transport,
    )

    assert decision.plan is None
    assert decision.calls == 0 and transport.calls == 0
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.REPLAN
    assert outcome.state_code is StateCode.ADAPTATION_CANNOT_MEET_CONSTRAINT
    assert outcome.route_target == "S-08"
    assert outcome.counter == STRATEGY_COUNTER


def test_the_structural_route_ends_in_the_destinations_skip():
    """The counter runs out, and the route ends where the registry says."""

    counters = _ledger(L_strategy=1)
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, moves=_THREE_POINTS, boundary=boundary)
    rules = _rules(
        plan_format=PlanFormat.CAROUSEL,
        length=LengthTarget(minimum=1, maximum=2, unit=LengthUnit.SLIDES),
    )

    def attempt() -> Any:
        return adapt_strategy(
            strategy=strategy,
            selection=_selection(strategy),
            decision=_decision(unit),
            rules=rules,
            contract=_contract(),
            boundary=boundary,
            core=_core(),
            counters=counters,
            transport=_Transport(_segmentation()),
        )

    first = attempt()
    second = attempt()

    assert first.outcomes[0].outcome is ArpOutcome.REPLAN
    assert second.outcomes[0].outcome is ArpOutcome.SKIP
    assert second.outcomes[0].scope is OutcomeScope.DESTINATION


def test_a_call_that_produced_nothing_is_not_a_structural_failure():
    """A provider outage is never counted as the format refusing the path."""

    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)

    decision = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(_segmentation(), fails=True),
    )

    assert decision.plan is None
    outcome = decision.outcomes[0]
    assert outcome.state_code is StateCode.PLAN_GENERATION_FAILED
    assert reason_category(outcome.state_code) is ReasonCategory.PROVIDER
    assert reason_category(
        StateCode.ADAPTATION_CANNOT_MEET_CONSTRAINT
    ) is ReasonCategory.PLAN
    assert "the provider refused" not in (outcome.reason or "")


def test_a_refused_budget_makes_no_call():
    transport = _Transport(_segmentation())
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)

    decision = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=_ledger(),
        transport=transport,
        budget=_RefusingBudget(),
    )

    assert transport.calls == 0
    assert decision.plan is None
    assert decision.outcomes[0].state_code is StateCode.BUDGET_EXHAUSTED


def test_a_selection_that_chose_nothing_cannot_be_adapted():
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)
    empty = StrategySelection(
        selection_id=selection_id(strategy.candidate_set_id),
        unit_id=unit.unit_id,
        destination=strategy.destination,
        candidate_set_id=strategy.candidate_set_id,
        outcome=OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            scope=OutcomeScope.DESTINATION,
            scope_key=destination_scope_key(unit.unit_id, strategy.destination),
            reason="no candidate survived exclusion",
        ),
    )

    with pytest.raises(PlanError):
        adapt_strategy(
            strategy=strategy,
            selection=empty,
            decision=_decision(unit),
            rules=_rules(),
            contract=_contract(),
            boundary=boundary,
            core=_core(),
            counters=_ledger(),
            transport=_Transport(_segmentation()),
        )


def test_an_article_states_its_subheadings_and_a_post_does_not():
    _, article = _drafted(
        destination=Destination.WIX,
        rules=_rules(
            Destination.WIX,
            plan_format=PlanFormat.ARTICLE,
            length=LengthTarget(minimum=600, maximum=1200, unit=LengthUnit.WORDS),
        ),
        answer=_segmentation(subheadings="One subheading per segment."),
    )
    _, post = _drafted(answer=_segmentation(subheadings="One per segment."))

    assert article.plan is not None
    assert article.plan.subheadings == "One subheading per segment."
    assert post.plan is None
    assert post.outcomes[0].state_code is StateCode.PLAN_GENERATION_FAILED


# ===========================================================================
# S-11 · the checks, their tiers and their routes
# ===========================================================================


def test_a_check_that_could_not_be_answered_is_not_a_pass():
    """Fail closed: no approval, and no counter spent on a provider outage."""

    counters = _ledger()
    _, plan, decision = _checked(counters=counters, fails=True)

    assert decision.passed is False
    assert decision.approved is None
    verdict = decision.verdict
    assert verdict is not None and verdict.result is VerdictResult.FAIL
    for check_id in ("V-P01", "V-P04"):
        result = verdict.check(check_id)
        assert result is not None
        assert result.result is CheckOutcome.NOT_ANSWERED
        assert result.passed is False
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.PLAN_CHECK_UNAVAILABLE
    assert reason_category(outcome.state_code) is ReasonCategory.PROVIDER
    assert counters.used(STRATEGY_COUNTER, plan.scope_key) == 0
    assert "the provider refused" not in (outcome.reason or "")


def test_a_construction_against_a_rule_the_contract_does_not_hold_is_unreadable():
    """An answer that cannot be routed by rule is refused, not partly used."""

    _, _, decision = _checked(
        check_answer={
            "fields_hold": True,
            "conflict": None,
            "forbidden_constructions": [
                {
                    "rule_ref": "CR-NOT-A-RULE",
                    "segment": "Open on the network",
                    "detail": "it reads as a promise",
                }
            ],
        }
    )

    assert decision.passed is False
    verdict = decision.verdict
    assert verdict is not None
    result = verdict.check("V-P04")
    assert result is not None and result.result is CheckOutcome.NOT_ANSWERED


def test_two_fields_that_cannot_both_hold_route_back_to_s08():
    counters = _ledger()
    _, plan, decision = _checked(
        counters=counters,
        check_answer={
            "fields_hold": False,
            "conflict": {
                "first_field": "reveal",
                "second_field": "length_target",
                "detail": "the delayed reveal cannot arrive inside the length",
            },
            "forbidden_constructions": [],
        },
    )

    assert decision.passed is False
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.REPLAN
    assert outcome.state_code is StateCode.PLAN_CHECK_FAILED
    assert reason_category(outcome.state_code) is ReasonCategory.PLAN
    assert outcome.route_target == "S-08"
    assert counters.used(STRATEGY_COUNTER, plan.scope_key) == 1
    verdict = decision.verdict
    assert verdict is not None
    fields = verdict.check("V-P01")
    assert fields is not None and fields.route == CHECK_FAILED_CAUSE


def test_a_tier_two_client_rule_sends_the_destination_back():
    """V-P04's first route row: a client rule can be replanned around."""

    counters = _ledger()
    contract = _contract(
        slots=(
            FixedSlot(
                name="ending_mode",
                value="reader question",
                rule_ref="CR-END-01",
            ),
        )
    )
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=counters,
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(),
        contract=contract,
        checks=CHECKS,
        counters=counters,
        transport=_Transport(PASSING_CHECK),
    )

    assert decision.passed is False
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.REPLAN
    assert outcome.state_code is StateCode.PLAN_CHECK_FAILED
    verdict = decision.verdict
    assert verdict is not None
    compliance = verdict.check("V-P04")
    assert compliance is not None and compliance.result is CheckOutcome.FAIL
    assert compliance.findings[0].tier is KnowledgeTier.APPROVED_CLIENT_RULE
    assert compliance.findings[0].rule_ref == "CR-END-01"


def test_a_tier_one_rule_with_no_compliant_variant_ends_the_destination():
    """V-P04's second row: terminal, and the counter is not spent on it."""

    hard = PlatformRule(
        rule_id="K-DST-TG-01",
        text="This surface does not carry a post in this format at all.",
        tier=KnowledgeTier.HARD_PLATFORM_POLICY,
        compliant_variant=False,
        knowledge=KnowledgeRef(
            record_id="K-DST-TG-01",
            record_version=1,
            tier=KnowledgeTier.HARD_PLATFORM_POLICY,
            file_status=KnowledgeStatus.APPROVED_RULE,
            effective_status=KnowledgeStatus.APPROVED_RULE,
        ),
    )
    counters = _ledger()
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=counters,
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(plan_format=PlanFormat.CAROUSEL, rule=hard),
        contract=_contract(),
        checks=CHECKS,
        counters=counters,
        transport=_Transport(PASSING_CHECK),
    )

    assert decision.passed is False
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.HARD_PLATFORM_POLICY_FORBIDS
    assert outcome.route_target is None
    assert counters.used(STRATEGY_COUNTER, drafted.plan.scope_key) == 0


def test_a_tier_one_rule_that_admits_a_variant_is_replanned_around():
    """Both halves of the terminal row, not one of them."""

    soft_edged = PlatformRule(
        rule_id="K-DST-TG-02",
        text="This surface runs 10–40 words; a shorter plan complies.",
        tier=KnowledgeTier.HARD_PLATFORM_POLICY,
    )
    counters = _ledger()
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=counters,
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(
            length=LengthTarget(minimum=10, maximum=40, unit=LengthUnit.WORDS),
            rule=soft_edged,
        ),
        contract=_contract(),
        checks=CHECKS,
        counters=counters,
        transport=_Transport(PASSING_CHECK),
    )

    assert decision.outcomes[0].outcome is ArpOutcome.REPLAN
    assert decision.outcomes[0].state_code is StateCode.PLAN_CHECK_FAILED


def test_a_forbidden_phrase_in_the_plans_own_surface_is_found_by_code():
    contract = _contract(
        forbidden=(
            ForbiddenItem(
                kind=ForbiddenKind.PHRASE,
                value="game changer",
                rule_ref="CR-BAN-01",
                tier=KnowledgeTier.APPROVED_CLIENT_RULE,
            ),
        )
    )
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=contract,
        boundary=boundary,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(
            _segmentation(first_line="Open on the Game Changer, then cut.")
        ),
    )
    assert drafted.plan is not None

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(),
        contract=contract,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
    )

    assert decision.passed is False
    verdict = decision.verdict
    assert verdict is not None
    compliance = verdict.check("V-P04")
    assert compliance is not None
    assert any("game changer" in finding.detail for finding in compliance.findings)


def test_v_p05_is_a_hint_and_can_never_block_or_route():
    """I-12: the soft check records what it found and decides nothing."""

    _, plan, decision = _checked(
        portfolio=(
            PlanFingerprint(
                fingerprint_id="fp-1",
                destination=Destination.LINKEDIN,
                format=PlanFormat.POST,
                segment_count=2,
            ),
        )
    )

    assert decision.passed is True
    verdict = decision.verdict
    assert verdict is not None
    portfolio = verdict.check("V-P05")
    assert portfolio is not None
    assert portfolio.check_class is CheckClass.SOFT
    assert portfolio.result is CheckOutcome.PASS
    assert portfolio.route is None
    assert portfolio.blocks is False
    assert any("fp-1" in finding.detail for finding in portfolio.findings)
    assert plan.plan_id


def test_a_soft_check_cannot_be_built_as_a_failure_or_with_a_route():
    for kwargs in (
        {"result": CheckOutcome.FAIL},
        {"result": CheckOutcome.PASS, "route": CHECK_FAILED_CAUSE},
    ):
        with pytest.raises(PlanCheckError):
            CheckResult(
                check_id="V-P05",
                check_class=CheckClass.SOFT,
                rule_status=KnowledgeStatus.CANDIDATE,
                method=CheckMethod.CODE,
                findings=(Finding(detail="the shape repeats"),),
                **kwargs,
            )


def test_the_approved_version_is_v2_and_carries_its_exemplars():
    library = (
        ReferenceItem(
            item_id="K-EXM-LI-01",
            destination=Destination.LINKEDIN,
            format=PlanFormat.POST,
            take="the way the first line withholds the figure",
            do_not_copy="the closing question",
        ),
        ReferenceItem(
            item_id="K-EXM-WIX-01",
            destination=Destination.WIX,
            format=PlanFormat.ARTICLE,
            take="the subheading rhythm",
            do_not_copy="the summary box",
        ),
    )
    _, draft, decision = _checked(library=library)

    approved = decision.approved
    assert approved is not None
    assert approved.version == APPROVED_VERSION
    assert approved.stage_of_version is PlanStage.APPROVED
    assert approved.supersedes == (draft.plan_id, DRAFT_VERSION)
    assert [item.item_id for item in approved.exemplars] == ["K-EXM-LI-01"]
    assert draft.exemplars == ()
    # Nothing else moved: S-11 must not repair plans.
    assert approved.segments == draft.segments
    assert approved.citations == draft.citations
    assert approved.length_target == draft.length_target
    assert approved.first_line_mechanics == draft.first_line_mechanics


def test_an_approved_plan_cannot_be_approved_again():
    """Sealed once written: there is no public path back to a draft."""

    _, _, decision = _checked()
    approved = decision.approved
    assert approved is not None

    with pytest.raises(PlanError):
        approved.approved_with(())


def test_s11_refuses_to_check_an_approved_version():
    _, _, decision = _checked()
    approved = decision.approved
    assert approved is not None
    boundary = _two_readings()
    unit = _unit(boundary)

    with pytest.raises(PlanCheckError):
        check_plan(
            plan=approved,
            strategy=_strategy(unit, boundary=boundary),
            boundary=boundary,
            core=_core(),
            rules=_rules(),
            contract=_contract(),
            checks=CHECKS,
            counters=_ledger(),
            transport=_Transport(PASSING_CHECK),
        )


def test_the_check_records_come_from_the_register():
    """The class and the status are the record's, as the loader read them."""

    _, _, decision = _checked()
    verdict = decision.verdict
    assert verdict is not None

    assert [item.check_id for item in verdict.checks] == list(PLAN_CHECKS)
    statuses = {item.check_id: item.rule_status for item in verdict.checks}
    assert statuses["V-P02"] is KnowledgeStatus.INVARIANT
    assert statuses["V-P04"] is KnowledgeStatus.APPROVED_RULE
    assert statuses["V-P01"] is KnowledgeStatus.CANDIDATE


def test_a_missing_check_record_refuses_the_stage():
    """A plan approved without V-P02 applied is not an approved plan."""

    register = load_register(_REPO_ROOT / "knowledge", today=TODAY)
    short = dataclasses.replace(
        register,
        checks=tuple(
            check for check in register.checks if check.identity != "V-P02"
        ),
    )

    with pytest.raises(PlanCheckError) as refusal:
        plan_check_records(short)

    assert "V-P02" in str(refusal.value)


# ===========================================================================
# F-4 · an approval does not outlive the boundary it was made against
# ===========================================================================


def test_an_approval_does_not_hold_against_a_newer_boundary_version():
    _, _, decision = _checked()
    verdict = decision.verdict
    assert verdict is not None

    assert approval_holds(verdict, _two_readings()) is True
    assert approval_holds(verdict, _one_reading()) is False


def test_a_recheck_re_establishes_an_approval_that_still_holds():
    """0 model calls, a new verdict version, and the approval carried forward."""

    strategy, _, decision = _checked()
    verdict = decision.verdict
    approved = decision.approved
    assert verdict is not None and approved is not None
    narrowed = _one_reading()

    rechecked = recheck_after_boundary_commit(
        verdict=verdict,
        plan=approved,
        strategy=strategy,
        boundary=narrowed,
        core=_core(),
        checks=CHECKS,
        counters=_ledger(),
    )

    assert rechecked.version == verdict.version + 1
    assert rechecked.result is VerdictResult.PASS
    assert rechecked.approved_plan_ref == verdict.approved_plan_ref
    assert approval_holds(rechecked, narrowed) is True
    assert approval_holds(verdict, narrowed) is False


def test_a_recheck_that_no_longer_holds_routes_back_to_s08():
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary, thesis_refs=(TIMELINE,))
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=boundary,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None
    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        rules=_rules(),
        contract=_contract(),
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
    )
    verdict = decision.verdict
    approved = decision.approved
    assert verdict is not None and approved is not None
    counters = _ledger()

    rechecked = recheck_after_boundary_commit(
        verdict=verdict,
        plan=approved,
        strategy=strategy,
        boundary=_one_reading(),
        core=_core(),
        checks=CHECKS,
        counters=counters,
    )

    assert rechecked.result is VerdictResult.FAIL
    assert rechecked.approved_plan_ref is None
    assert rechecked.outcome is not None
    assert rechecked.outcome.outcome is ArpOutcome.REPLAN
    assert rechecked.outcome.route_target == "S-08"
    assert approval_holds(rechecked, _one_reading()) is False


def test_a_recheck_against_an_older_snapshot_is_refused():
    _, _, decision = _checked()
    verdict = decision.verdict
    approved = decision.approved
    assert verdict is not None and approved is not None

    with pytest.raises(PlanCheckError):
        recheck_after_boundary_commit(
            verdict=verdict,
            plan=approved,
            strategy=_strategy(_unit()),
            boundary=_two_readings(),
            core=_core(),
            checks=CHECKS,
            counters=_ledger(),
        )


# ===========================================================================
# Boundaries · both ends of every range
# ===========================================================================


def test_a_length_target_is_checked_at_both_ends():
    surface = LengthTarget(minimum=80, maximum=220, unit=LengthUnit.WORDS)

    assert LengthTarget(80, 220, LengthUnit.WORDS).within(surface) is True
    assert LengthTarget(79, 220, LengthUnit.WORDS).within(surface) is False
    assert LengthTarget(80, 221, LengthUnit.WORDS).within(surface) is False
    assert LengthTarget(80, 220, LengthUnit.CHARACTERS).within(surface) is False
    assert surface.contains(80) is True
    assert surface.contains(220) is True
    assert surface.contains(79) is False
    assert surface.contains(221) is False


def test_a_hashtag_policy_is_checked_at_both_ends():
    with pytest.raises(PlanError):
        Hashtags(policy=HashtagPolicy.FORBIDDEN, tags=("#one",))
    with pytest.raises(PlanError):
        Hashtags(policy=HashtagPolicy.REQUIRED)

    assert Hashtags(policy=HashtagPolicy.REQUIRED, tags=("#one",)).tags == ("#one",)
    assert Hashtags(policy=HashtagPolicy.FORBIDDEN).tags == ()


def test_a_destination_that_requires_hashtags_needs_the_clients_tags():
    boundary = _two_readings()
    unit = _unit(boundary)
    strategy = _strategy(unit, boundary=boundary)

    with pytest.raises(PlanError):
        adapt_strategy(
            strategy=strategy,
            selection=_selection(strategy),
            decision=_decision(unit),
            rules=_rules(hashtags=HashtagPolicy.REQUIRED),
            contract=_contract(),
            boundary=boundary,
            core=_core(),
            counters=_ledger(),
            transport=_Transport(_segmentation()),
        )


def test_a_segmentation_outside_the_slide_range_is_refused_at_both_ends():
    rules = _rules(
        plan_format=PlanFormat.CAROUSEL,
        length=LengthTarget(minimum=2, maximum=3, unit=LengthUnit.SLIDES),
    )
    _, too_few = _drafted(
        rules=rules,
        answer=_segmentation(
            segments=({"name": "One", "purpose": "carry both", "moves": [1, 2]},)
        ),
    )
    _, fits = _drafted(rules=rules)

    assert too_few.plan is None
    assert too_few.outcomes[0].state_code is StateCode.PLAN_GENERATION_FAILED
    assert fits.plan is not None
    assert len(fits.plan.segments) == 2


# ===========================================================================
# Storage · §2.3 write ownership, and create-once
# ===========================================================================


def test_each_version_of_a_plan_is_written_by_the_stage_that_made_it(
    tmp_path: Path,
):
    workspace = _workspace(tmp_path)
    _, draft, decision = _checked()
    approved = decision.approved
    verdict = decision.verdict
    assert approved is not None and verdict is not None

    draft_entry = write_plan(workspace, draft)
    approved_entry = write_approved_plan(workspace, approved)
    verdict_entry = write_plan_verdict(workspace, verdict)

    assert draft_entry.writer_stage == PLAN_STAGE
    assert approved_entry.writer_stage == CHECK_STAGE
    assert verdict_entry.writer_stage == CHECK_STAGE
    assert draft_entry.path == plan_relative_path(
        draft.unit_id, draft.destination, draft.plan_id, DRAFT_VERSION
    )
    assert verdict_entry.path == verdict_relative_path(
        verdict.unit_id, verdict.destination, verdict.plan_ref[0], verdict.version
    )
    assert owner_of(draft_entry.path, stage_of_version="draft") == PLAN_STAGE
    assert owner_of(approved_entry.path, stage_of_version="approved") == CHECK_STAGE
    assert owner_of(verdict_entry.path) == CHECK_STAGE


def test_a_barrier_round_is_written_by_s11(tmp_path: Path):
    workspace = _workspace(tmp_path)
    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)
    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(_barrier_answer()),
    )

    entry = write_barrier_round(workspace, barrier)

    assert entry.writer_stage == CHECK_STAGE
    assert entry.path == barrier_round_relative_path(unit.unit_id, 1)
    assert owner_of(entry.path) == CHECK_STAGE
    assert json.loads((workspace.run_dir / entry.path).read_text())["passed"] is True


def test_a_draft_may_not_be_written_as_the_approved_version():
    _, draft, _ = _checked()

    with pytest.raises(PlanCheckError):
        write_approved_plan(None, draft)  # type: ignore[arg-type]


def test_a_new_attempt_has_a_plan_of_its_own():
    unit = _unit()
    first = plan_id(candidate_set_id(unit.unit_id, Destination.LINKEDIN, 1))
    second = plan_id(candidate_set_id(unit.unit_id, Destination.LINKEDIN, 2))

    assert first != second
    assert plan_relative_path(
        unit.unit_id, Destination.LINKEDIN, first, DRAFT_VERSION
    ) != plan_relative_path(
        unit.unit_id, Destination.LINKEDIN, second, DRAFT_VERSION
    )


# ===========================================================================
# The one topology, and the states these stages record
# ===========================================================================


def test_the_routes_out_of_s10_and_s11_are_the_ones_the_topology_declares():
    declared = {
        (route.source, route.cause, route.target, route.counter)
        for route in CANONICAL_TOPOLOGY.replan_routes
        if route.source in (PLAN_STAGE, CHECK_STAGE)
    }

    assert declared == {
        (PLAN_STAGE, ADAPTATION_CAUSE, "S-08", STRATEGY_COUNTER),
        (CHECK_STAGE, CHECK_FAILED_CAUSE, "S-08", STRATEGY_COUNTER),
        (CHECK_STAGE, DEVIATION_CAUSE, "S-08", STRATEGY_COUNTER),
    }


def test_b1_is_evaluated_at_s11_and_blocks_the_writer():
    barrier = next(
        item for item in CANONICAL_TOPOLOGY.barriers if item.barrier_id == BARRIER_ID
    )

    assert barrier.evaluated_at == CHECK_STAGE
    assert barrier.blocks == "S-12"


def test_the_states_these_stages_record_end_where_step_2_says():
    assert permitted_outcomes(StateCode.ADAPTATION_CANNOT_MEET_CONSTRAINT) == (
        frozenset({ArpOutcome.REPLAN, ArpOutcome.SKIP})
    )
    assert permitted_outcomes(StateCode.PLAN_CHECK_FAILED) == frozenset(
        {ArpOutcome.REPLAN, ArpOutcome.SKIP}
    )
    assert permitted_outcomes(StateCode.PLAN_GENERATION_FAILED) == frozenset(
        {ArpOutcome.SKIP}
    )
    assert permitted_outcomes(StateCode.PLAN_CHECK_UNAVAILABLE) == frozenset(
        {ArpOutcome.SKIP}
    )
    assert reason_category(StateCode.PLAN_CHECK_FAILED) is ReasonCategory.PLAN
    assert reason_category(StateCode.PLAN_CHECK_UNAVAILABLE) is ReasonCategory.PROVIDER


# ===========================================================================
# CE-1 · neither stage holds a pipeline of its own
# ===========================================================================


@pytest.mark.parametrize("module", ["executable_plan.py", "plan_check.py"])
def test_neither_stage_selects_stages_by_destination(module: str):
    """CE-1's placement rule, run over the modules this issue adds."""

    assert check_module(_REPO_ROOT / "src" / "editorial_core" / module) == []


@pytest.mark.parametrize(
    ("module", "transports", "call_sites"),
    [
        ("executable_plan.py", ["SegmentationTransport"], 1),
        ("plan_check.py", ["PlanCheckTransport", "BarrierTransport"], 2),
    ],
)
def test_each_stage_makes_exactly_the_calls_its_contract_allows(
    module: str, transports: list[str], call_sites: int
):
    """§3's Calls column, read off the modules rather than off a run.

    S-10 makes one call per destination per strategy attempt; S-11 makes one per
    destination per plan version plus one per unit per barrier round, which is
    two transports and two call sites and no third.
    """

    source = (_REPO_ROOT / "src" / "editorial_core" / module).read_text(
        encoding="utf-8"
    )
    named = [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name.endswith("Transport")
    ]

    assert named == transports
    assert source.count(".complete(") == call_sites


def test_s09_s10_and_s11_are_neighbours_in_the_one_topology():
    identifiers = CANONICAL_TOPOLOGY.stage_ids

    assert identifiers.index(PLAN_STAGE) == identifiers.index("S-09") + 1
    assert identifiers.index(CHECK_STAGE) == identifiers.index(PLAN_STAGE) + 1


def test_the_barrier_round_records_what_it_compared():
    boundary = _two_readings()
    unit = _unit(boundary)
    plans, verdicts = _unit_plans(boundary)
    barrier = run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, boundary),
        plans=plans,
        verdicts=verdicts,
        boundary=boundary,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(_barrier_answer(Destination.WIX)),
        round_index=2,
    )

    body = barrier.as_entity()

    assert body["barrier_id"] == BARRIER_ID
    assert body["round"] == 2
    assert body["destinations"] == [item.value for item in _UNIT_DESTINATIONS]
    assert body["deviating"] == [Destination.WIX.value]
    assert body["passed"] is False
    assert isinstance(barrier, BarrierRound)
