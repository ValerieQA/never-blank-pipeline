"""Issue #306: prose that executes the approved plan and decides nothing.

SL-6's acceptance evidence for S-12, on the same walkthrough B material as #304
and #305 (map §13, "Ramp Launches Instant Stablecoin Payments with Stripe's New
Technology"): an approved LinkedIn plan, checked, past barrier B1, written.

The issue's two acceptance criteria, and the tests that are them:

1. **the trace proves the Writer received no sibling text, no label and no raw
   research** — ``test_the_writer_receives_no_sibling_text_no_label_or_raw_research``,
   which writes a real sibling destination's text first and then asserts that
   nothing of it, of the core's research artifact, of the material the plan does
   not reference or of the boundary beyond it reaches the second call; with
   ``test_the_s12_request_has_nowhere_to_put_a_sibling_or_a_label`` for the
   shape that makes it so, and
   ``test_the_recorded_inputs_are_the_request_that_was_sent`` for the trace being
   about that exact request rather than about a claim made beside it;
2. **a planted "plan cannot hold" fixture routes to S-08** —
   ``test_a_planted_plan_that_cannot_hold_routes_to_s08``, with
   ``test_a_refusal_writes_no_text``,
   ``test_a_refusal_with_no_reason_is_still_a_refusal`` and
   ``test_the_refusal_ends_the_destination_once_l_strategy_is_gone`` for the
   three ways it must not be read as anything else.

And the properties they rest on: I-08 (only an approved plan opens prose), B1
blocking S-12, F-4 (an approval a boundary commit overtook opens nothing), the
links computed from the cited sources, a body that cannot disagree with its own
parts, and a call nobody could read kept apart from a Writer that refused the
plan.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import ValidationError

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
    AdaptationContract,
    DestinationRules,
    ExecutablePlan,
    HashtagPolicy,
    LengthTarget,
    LengthUnit,
    PlanFormat,
    PlatformRule,
    adapt_strategy,
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
    BARRIER_ID,
    BarrierRound,
    PlanVerdict,
    ReferenceItem,
    check_plan,
    plan_check_records,
    run_barrier,
)
from src.editorial_core.relevance_screen import AudienceTransfer, DecisionRef
from src.editorial_core.strategy_selection import StrategySelection, selection_id
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.editorial_core.writer import (
    PLAN_DOES_NOT_HOLD_CAUSE,
    STAGE as WRITER_STAGE,
    STRATEGY_COUNTER,
    WITHHELD_INPUTS,
    ReferencedCore,
    Text,
    TextSegment,
    VoiceBrief,
    WriterAnswer,
    WriterError,
    WriterSignal,
    referenced_core,
    resolved_links,
    text_id,
    text_relative_path,
    write_prose,
    write_text,
)
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

SIGNAL = "signal-306-ramp"
CORE = "core-306-ramp"

#: The research artifact the core wraps. It is the "raw research" §3 keeps out,
#: so both halves of the reference are planted markers: neither the ID nor the
#: digest may appear in what the Writer is shown.
ARTIFACT = "artifact-306-raw-research"
ARTIFACT_DIGEST = "sha256:" + "d" * 64

#: Claims of the core, as (statement, source). ``ev-unused`` is the planted
#: material the plan does not reference: it sits on a source the plan does not
#: cite, so no path through E-14 reaches it.
CLAIMS: dict[str, tuple[str, str]] = {
    "ev-1": (
        "The vendor states the payment settles in minutes rather than days.",
        "src-1",
    ),
    "ev-2": (
        "The filing records the settlement network the payment runs over.",
        "src-1",
    ),
    "ev-3": ("A trade report puts the prior settlement time at two days.", "src-1"),
    "ev-unused": (
        "UNREFERENCED-CLAIM: a second vendor priced its own transfers last spring.",
        "src-2",
    ),
}

MECHANISM = "int-306-mechanism"
TIMELINE = "int-306-timeline"
REFUSED = "int-306-refused"

#: The inadmissible reading: the boundary beyond what the plan references.
REFUSED_READING = "REFUSED-READING: every business that switches will pay less."

VOICE = "voice-doc-v3"
VOICE_TEXT = "Plain sentences. No hype. Name the mechanism before the benefit."

#: What the sibling destination's text says, and nothing else does.
SIBLING_MARKER = "SIBLING-TEXT: the wix text says this and only the wix text."

SOURCE_URL = "https://example.test/item"


# ===========================================================================
# Fixtures
# ===========================================================================


def _core() -> EvidenceCore:
    observations = tuple(
        SourceObservation(
            observation_id=f"obs-{identity}",
            signal_id=SIGNAL,
            source_ref=source,
            kind=ObservationKind.QUOTE,
            excerpt=statement,
            attribution=f"Example Press reports: {statement}",
            is_third_party_assertion=False,
        )
        for identity, (statement, source) in CLAIMS.items()
    )
    claims = tuple(
        EvidenceClaim(
            evidence_claim_id=identity,
            statement=statement,
            observation_refs=(f"obs-{identity}",),
            source_refs=(source,),
            verdict=EvidenceDisposition.ACCEPTED,
            verdict_rationale="The cited excerpt states it.",
            scope="One named vendor, as reported.",
            strength=LADDER.at(2),
            ceiling=LADDER.at(2),
        )
        for identity, (statement, source) in CLAIMS.items()
    )
    return EvidenceCore(
        core_id=CORE,
        version=1,
        signal_ids=(SIGNAL,),
        research_artifact_refs=((ARTIFACT, ARTIFACT_DIGEST),),
        sources=(
            NormalizedSource(
                source_id="src-1",
                locator=SourceLocator(
                    kind=SourceLocatorKind.URL, value=SOURCE_URL
                ),
                title="Recorded report",
                publisher="Example Press",
                publication_time=PublicationTime(
                    status=PublicationTimeStatus.KNOWN, value=NOW
                ),
                retrieved_at=NOW,
            ),
            NormalizedSource(
                source_id="src-2",
                locator=SourceLocator(
                    kind=SourceLocatorKind.IDENTIFIER, value="doi:10.0000/unused"
                ),
                title="A second report nobody cites",
                publisher="Other Press",
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
            path="reports/content_packages/signal-306/decision.json",
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
    """The boundary the plan was approved against: two admissible, one refused."""

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
                REFUSED_READING,
                supports=(),
                admissible=False,
                kind=InterpretationKind.GENERALIZATION,
            ),
        )
    )


def _one_reading() -> InterpretationBoundary:
    """Version 2: a commit has made the comparison inadmissible (F-4)."""

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
    unit: EditorialUnit, destination: Destination = Destination.LINKEDIN
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


def _strategy(
    unit: EditorialUnit,
    destination: Destination = Destination.LINKEDIN,
    *,
    boundary: Optional[InterpretationBoundary] = None,
) -> EditorialStrategy:
    """One chosen E-13, built directly: S-08 and S-09 are #304's to exercise."""

    snapshot = boundary or _two_readings()
    set_id = candidate_set_id(unit.unit_id, destination, 1)
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
            interpretation_refs=(MECHANISM,),
        ),
        focal_subject=FocalSubject(
            kind=FocalSubjectKind.COMPANY,
            text="The vendor named in the filing",
            refs=("ev-2",),
        ),
        leading_material_ref="ev-1",
        reader_path=_TWO_MOVES,
        opening=Opening(
            text="The filing names the network.",
            held_back="the prior settlement time",
            refs=(MECHANISM,),
        ),
        reveal=Reveal(kind=RevealKind.IMMEDIATE),
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
) -> DestinationRules:
    return DestinationRules(
        destination=destination,
        format=plan_format,
        format_rule=PLATFORM,
        length=LengthTarget(minimum=80, maximum=220, unit=LengthUnit.WORDS),
        length_rule=PLATFORM,
        hashtags=HashtagPolicy.ALLOWED,
        hashtag_rule=PLATFORM,
    )


def _contract() -> AdaptationContract:
    return AdaptationContract(voice_brief_ref=VOICE)


class _Transport:
    """One canned answer, and a record of what it was asked for."""

    def __init__(self, answer: Any, *, fails: bool = False) -> None:
        self.answer = answer
        self.fails = fails
        self.calls = 0
        self.requests: list[str] = []
        self.instructions: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        self.requests.append(request)
        self.instructions.append(instructions)
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


SEGMENT_NAMES = ("Open on the network", "Show the wait")


def _segmentation(*, subheadings: Optional[str] = None) -> dict[str, Any]:
    return {
        "segments": [
            {
                "name": SEGMENT_NAMES[0],
                "purpose": "carry the first move",
                "moves": [1],
            },
            {
                "name": SEGMENT_NAMES[1],
                "purpose": "carry the leading material",
                "moves": [2],
            },
        ],
        "first_line_mechanics": "The first line is visible before the cut.",
        "subheadings": subheadings,
    }


PASSING_CHECK: dict[str, Any] = {
    "fields_hold": True,
    "conflict": None,
    "forbidden_constructions": [],
}

CHECKS = plan_check_records(load_register(_REPO_ROOT / "knowledge", today=TODAY))

LIBRARY = (
    ReferenceItem(
        item_id="K-EXM-07",
        destination=Destination.LINKEDIN,
        format=PlanFormat.POST,
        take="the first line names the mechanism",
        do_not_copy="the closing question",
    ),
)


def _approved(
    destination: Destination = Destination.LINKEDIN,
    *,
    boundary: Optional[InterpretationBoundary] = None,
    plan_format: PlanFormat = PlanFormat.POST,
    library: Sequence[ReferenceItem] = LIBRARY,
) -> tuple[EditorialStrategy, ExecutablePlan, PlanVerdict]:
    """S-10 then S-11 over one destination: an approved plan and its verdict."""

    snapshot = boundary or _two_readings()
    unit = _unit(snapshot)
    strategy = _strategy(unit, destination, boundary=snapshot)
    rules = _rules(destination, plan_format=plan_format)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit, destination),
        rules=rules,
        contract=_contract(),
        boundary=snapshot,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(
            _segmentation(
                subheadings=(
                    "The two segments run on under their own subheadings."
                    if plan_format is PlanFormat.ARTICLE
                    else None
                )
            )
        ),
    )
    assert drafted.plan is not None
    checked = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=snapshot,
        core=_core(),
        rules=rules,
        contract=_contract(),
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
        library=library,
    )
    assert checked.approved is not None and checked.verdict is not None
    return strategy, checked.approved, checked.verdict


def _round(plans: Sequence[ExecutablePlan]) -> dict[str, Any]:
    return {
        "plans": [
            {
                "destination": plan.destination.value,
                "carries_anchor": True,
                "detail": None,
            }
            for plan in plans
        ],
        "contradictions": [],
    }


def _barrier(
    plans: Sequence[ExecutablePlan],
    verdicts: Sequence[PlanVerdict],
    *,
    boundary: Optional[InterpretationBoundary] = None,
    answer: Optional[Any] = None,
    fails: bool = False,
) -> BarrierRound:
    """One real B1 round over the unit's approved plans (S-11)."""

    snapshot = boundary or _two_readings()
    unit = _unit(snapshot)
    return run_barrier(
        unit_id=unit.unit_id,
        anchor=_anchor(unit, snapshot),
        expected_destinations=frozenset(plan.destination for plan in plans),
        plans=tuple(plans),
        verdicts=tuple(verdicts),
        boundary=snapshot,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(answer or _round(plans), fails=fails),
    )


def _prose(
    *,
    parts: Optional[Sequence[dict[str, str]]] = None,
    plan_holds: bool = True,
    reason: Optional[str] = None,
    title: Optional[str] = None,
    dek: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "plan_holds": plan_holds,
        "reason": reason,
        "title": title,
        "dek": dek,
        "segments": [
            dict(item)
            for item in (
                parts
                if parts is not None
                else (
                    {
                        "name": SEGMENT_NAMES[0],
                        "text": "The filing names the settlement network.",
                    },
                    {
                        "name": SEGMENT_NAMES[1],
                        "text": "The vendor states the payment settles in minutes.",
                    },
                )
            )
        ],
    }


REFUSAL_REASON = (
    "the two segments cannot carry both moves at 80 words, and the core holds "
    "no figure for the second"
)


def _brief() -> VoiceBrief:
    return VoiceBrief(brief_ref=VOICE, text=VOICE_TEXT)


def _write(
    *,
    transport: Any,
    destination: Destination = Destination.LINKEDIN,
    plan_format: PlanFormat = PlanFormat.POST,
    boundary: Optional[InterpretationBoundary] = None,
    current: Optional[InterpretationBoundary] = None,
    library: Sequence[ReferenceItem] = LIBRARY,
    counters: Optional[AttemptCounterLedger] = None,
    budget: Any = None,
    brief: Optional[VoiceBrief] = None,
    plan: Optional[ExecutablePlan] = None,
    barrier: Optional[BarrierRound] = None,
) -> Any:
    """Run S-12 over a plan that S-10, S-11 and B1 really produced."""

    snapshot = boundary or _two_readings()
    strategy, approved, verdict = _approved(
        destination,
        boundary=snapshot,
        plan_format=plan_format,
        library=library,
    )
    return write_prose(
        plan=plan or approved,
        verdict=verdict,
        barrier=barrier or _barrier((approved,), (verdict,), boundary=snapshot),
        strategy=strategy,
        boundary=current or snapshot,
        core=_core(),
        brief=brief or _brief(),
        counters=counters or _ledger(),
        transport=transport,
        budget=budget,
    )


# ===========================================================================
# Acceptance 1 · the trace proves what the Writer was given
# ===========================================================================


def test_the_writer_receives_no_sibling_text_no_label_or_raw_research():
    """Acceptance 1, on a run where all three exist to be leaked.

    The wix text is written first and really exists; the core really wraps a
    research artifact; the boundary really holds a refused reading; the core
    really holds a claim the plan does not reference. None of it reaches the
    second call, and the recorded inputs say so against the request's digest.
    """

    boundary = _two_readings()
    sibling = _write(
        transport=_Transport(
            _prose(
                parts=(
                    {"name": SEGMENT_NAMES[0], "text": SIBLING_MARKER},
                    {"name": SEGMENT_NAMES[1], "text": "And the wait is gone."},
                )
            )
        ),
        destination=Destination.WIX,
        library=(),
        boundary=boundary,
    )
    assert sibling.text is not None
    assert SIBLING_MARKER in sibling.text.body

    transport = _Transport(_prose())
    written = _write(transport=transport, boundary=boundary)

    assert written.text is not None
    rendered = transport.requests[0]
    for planted in (
        SIBLING_MARKER,
        sibling.text.text_id,
        sibling.text.plan_ref[0],
        ARTIFACT,
        ARTIFACT_DIGEST,
        CLAIMS["ev-unused"][0],
        REFUSED_READING,
        REFUSED,
    ):
        assert planted not in rendered
    assert "label" not in rendered.lower()

    inputs = written.text.inputs
    assert inputs.withheld == WITHHELD_INPUTS
    assert set(inputs.core_item_refs) == {
        "src-1",
        "ev-1",
        "ev-2",
        "ev-3",
        "obs-ev-1",
        "obs-ev-2",
        "obs-ev-3",
    }
    assert inputs.exemplar_refs == ("K-EXM-07",)
    assert inputs.voice_brief_ref == VOICE


def test_the_s12_request_has_nowhere_to_put_a_sibling_or_a_label():
    """§3's "Not an input" row, kept by the shape of the call (I-06, AD-07)."""

    transport = _Transport(_prose())
    _write(transport=transport)

    sent = json.loads(transport.requests[0])
    assert set(sent) == {
        "plan",
        "strategy",
        "core_items",
        "exemplars",
        "voice_brief",
        "forbidden",
        "fixed_slots",
    }
    assert set(sent["core_items"]) == {"sources", "claims", "observations"}

    taken = set(inspect.signature(write_prose).parameters)
    assert not {
        name
        for name in taken
        if "sibling" in name or "label" in name or "research" in name
    }
    declared = {field.name for field in dataclasses.fields(Text)}
    assert not {name for name in declared if "label" in name or "sibling" in name}


def test_the_recorded_inputs_are_the_request_that_was_sent():
    """The trace is about one request, and names which one.

    A record that only listed what was withheld would be a claim with nothing
    to check it against; the digest is what ties the claim to the bytes.
    """

    transport = _Transport(_prose())
    written = _write(transport=transport)

    assert written.text is not None
    expected = (
        "sha256:"
        + hashlib.sha256(transport.requests[0].encode("utf-8")).hexdigest()
    )
    assert written.text.inputs.request_digest == expected
    assert written.text.as_entity()["inputs"]["request_digest"] == expected
    assert written.text.as_entity()["inputs"]["withheld"] == list(WITHHELD_INPUTS)


def test_the_referenced_core_is_what_the_plan_reaches_and_not_the_core():
    """§3's Inputs: the core items the plan references, resolved by code."""

    _, plan, _ = _approved()
    strategy = _strategy(_unit(), Destination.LINKEDIN)

    resolved = referenced_core(plan, strategy, _core())

    assert [source.source_id for source in resolved.sources] == ["src-1"]
    assert "ev-unused" not in {claim.evidence_claim_id for claim in resolved.claims}
    assert {claim.evidence_claim_id for claim in resolved.claims} == {
        "ev-1",
        "ev-2",
        "ev-3",
    }
    assert {item.observation_id for item in resolved.observations} == {
        "obs-ev-1",
        "obs-ev-2",
        "obs-ev-3",
    }


def test_a_citation_the_core_does_not_hold_is_refused():
    """Resolution fails closed: an unresolvable citation is not a thinner text."""

    _, plan, _ = _approved()
    thinner = dataclasses.replace(plan, citations=("src-1", "src-absent"))

    with pytest.raises(WriterError):
        referenced_core(thinner, _strategy(_unit(), Destination.LINKEDIN), _core())


def test_the_call_is_made_once_and_is_never_handed_the_provider_text_back():
    transport = _Transport(_prose())
    written = _write(transport=transport)

    assert transport.calls == 1
    assert written.calls == 1
    assert "decide nothing" in transport.instructions[0].lower()


# ===========================================================================
# Acceptance 2 · a plan that cannot hold routes to S-08
# ===========================================================================


def test_a_planted_plan_that_cannot_hold_routes_to_s08():
    """Acceptance 2. The Writer refuses, and the destination re-plans."""

    counters = _ledger()
    decision = _write(
        transport=_Transport(_prose(plan_holds=False, parts=(), reason=REFUSAL_REASON)),
        counters=counters,
    )

    assert decision.text is None
    assert decision.refused is True
    assert decision.signal is not None
    assert decision.signal.plan_holds is False
    assert decision.signal.reason == REFUSAL_REASON

    assert len(decision.outcomes) == 1
    routed = decision.outcomes[0]
    assert routed.outcome is ArpOutcome.REPLAN
    assert routed.route_target == "S-08"
    assert routed.state_code is StateCode.PLAN_DOES_NOT_HOLD
    assert routed.counter == STRATEGY_COUNTER
    assert routed.reason == REFUSAL_REASON

    unit = _unit()
    key = destination_scope_key(unit.unit_id, Destination.LINKEDIN)
    assert routed.scope_key == key
    assert counters.used(STRATEGY_COUNTER, key) == 1


def test_a_refusal_writes_no_text():
    """§3's Post: on ``plan_holds = false``, no text is accepted."""

    decision = _write(
        transport=_Transport(_prose(plan_holds=False, parts=(), reason=REFUSAL_REASON))
    )

    assert decision.text is None
    # And the entity cannot express one either: a refused plan has no prose.
    with pytest.raises(WriterError):
        Text(
            text_id="txt-x",
            version=1,
            unit_id="unit-x",
            destination=Destination.LINKEDIN,
            plan_ref=("plan-x", 2),
            segments=(TextSegment(name="a", text="b"),),
            writer_signal=WriterSignal(plan_holds=False, reason="it does not hold"),
            inputs=_written_inputs(),
        )


def test_a_refusal_with_no_reason_is_still_a_refusal():
    """The route is taken, and the missing reason is recorded as missing.

    Reading a reasonless refusal as "no answer" would charge the machinery for a
    judgment that was made, and reading it as a text would improvise one.
    """

    decision = _write(
        transport=_Transport(_prose(plan_holds=False, parts=(), reason=None))
    )

    assert decision.text is None
    assert decision.refused is True
    assert decision.signal is not None
    assert decision.signal.reason is not None
    assert "named no reason" in decision.signal.reason
    assert decision.outcomes[0].state_code is StateCode.PLAN_DOES_NOT_HOLD
    assert decision.outcomes[0].outcome is ArpOutcome.REPLAN


def test_the_refusal_ends_the_destination_once_l_strategy_is_gone():
    """§5.3's terminal column: ``SKIP`` the destination, never a run that waits."""

    counters = _ledger(L_strategy=1)
    answer = _prose(plan_holds=False, parts=(), reason=REFUSAL_REASON)

    first = _write(transport=_Transport(answer), counters=counters)
    second = _write(transport=_Transport(answer), counters=counters)

    assert first.outcomes[0].outcome is ArpOutcome.REPLAN
    assert second.outcomes[0].outcome is ArpOutcome.SKIP
    assert second.outcomes[0].scope is OutcomeScope.DESTINATION
    assert second.refused is True


def test_a_call_nobody_could_read_is_not_a_refusal():
    """The machinery's failure is kept apart from the Writer's finding (I-09)."""

    for transport in (
        _Transport(_prose(), fails=True),
        _Transport("not json at all"),
        _Transport({"plan_holds": True}),
    ):
        decision = _write(transport=transport)

        assert decision.text is None
        assert decision.signal is None
        assert decision.refused is False
        assert decision.outcomes[0].outcome is ArpOutcome.SKIP
        assert decision.outcomes[0].state_code is StateCode.TEXT_GENERATION_FAILED
        assert decision.inputs is not None


def test_a_text_that_executes_another_plans_segments_is_not_this_plans_text():
    """Step 1 §5 aligns the parts to the plan's segments, in the plan's order."""

    renamed = _write(
        transport=_Transport(
            _prose(
                parts=(
                    {"name": "Some other opening", "text": "Prose."},
                    {"name": SEGMENT_NAMES[1], "text": "More prose."},
                )
            )
        )
    )
    reordered = _write(
        transport=_Transport(
            _prose(
                parts=(
                    {"name": SEGMENT_NAMES[1], "text": "Prose."},
                    {"name": SEGMENT_NAMES[0], "text": "More prose."},
                )
            )
        )
    )
    dropped = _write(
        transport=_Transport(
            _prose(parts=({"name": SEGMENT_NAMES[0], "text": "Prose."},))
        )
    )

    for decision in (renamed, reordered, dropped):
        assert decision.text is None
        assert decision.signal is None
        assert decision.outcomes[0].state_code is StateCode.TEXT_GENERATION_FAILED


def test_a_plan_that_holds_with_no_part_is_neither_written_nor_refused():
    decision = _write(transport=_Transport(_prose(parts=())))

    assert decision.text is None
    assert decision.outcomes[0].state_code is StateCode.TEXT_GENERATION_FAILED


def test_the_answer_has_no_field_for_a_changed_plan_or_an_invented_link():
    """The Writer repairs no decision it did not make: there is nowhere to put one."""

    assert WriterAnswer.model_validate(_prose()) is not None
    for smuggled in ("thesis", "links", "label", "reader_path", "length_target"):
        with pytest.raises(ValidationError):
            WriterAnswer.model_validate({**_prose(), smuggled: "anything"})


# ===========================================================================
# I-08, B1 and F-4 · what opens prose at all
# ===========================================================================


def test_a_draft_plan_opens_no_prose():
    """I-08: E-15 requires an ``approved`` E-14 (§3, Pre)."""

    snapshot = _two_readings()
    unit = _unit(snapshot)
    strategy = _strategy(unit, Destination.LINKEDIN, boundary=snapshot)
    drafted = adapt_strategy(
        strategy=strategy,
        selection=_selection(strategy),
        decision=_decision(unit),
        rules=_rules(),
        contract=_contract(),
        boundary=snapshot,
        core=_core(),
        counters=_ledger(),
        transport=_Transport(_segmentation()),
    )
    assert drafted.plan is not None
    transport = _Transport(_prose())

    with pytest.raises(WriterError):
        _write(transport=transport, plan=drafted.plan)

    assert transport.calls == 0


def test_an_approval_a_boundary_commit_overtook_opens_no_prose():
    """F-4: the plan's boundary version must equal the current one (§5.4)."""

    transport = _Transport(_prose())

    with pytest.raises(WriterError):
        _write(
            transport=transport,
            boundary=_two_readings(),
            current=_one_reading(),
        )

    assert transport.calls == 0


def test_a_barrier_that_has_not_passed_opens_no_prose():
    """§0.2: no text is written before B1 passes — including the unanswered round."""

    boundary = _two_readings()
    _, approved, verdict = _approved(boundary=boundary)
    unanswered = _barrier(
        (approved,), (verdict,), boundary=boundary, fails=True
    )
    deviating = _barrier(
        (approved,),
        (verdict,),
        boundary=boundary,
        answer={
            "plans": [
                {
                    "destination": approved.destination.value,
                    "carries_anchor": False,
                    "detail": "the plan asks the reader to believe the comparison",
                }
            ],
            "contradictions": [],
        },
    )

    assert unanswered.passed is False
    assert deviating.passed is False
    for barrier in (unanswered, deviating):
        transport = _Transport(_prose())
        with pytest.raises(WriterError):
            _write(transport=transport, boundary=boundary, barrier=barrier)
        assert transport.calls == 0


def test_a_barrier_that_did_not_compare_this_destination_opens_no_prose():
    boundary = _two_readings()
    mine_strategy, mine, my_verdict = _approved(
        Destination.LINKEDIN, boundary=boundary
    )
    _, other, other_verdict = _approved(
        Destination.TELEGRAM, boundary=boundary, library=()
    )
    elsewhere = _barrier((other,), (other_verdict,), boundary=boundary)

    assert elsewhere.passed is True
    with pytest.raises(WriterError):
        write_prose(
            plan=mine,
            verdict=my_verdict,
            barrier=elsewhere,
            strategy=mine_strategy,
            boundary=boundary,
            core=_core(),
            brief=_brief(),
            counters=_ledger(),
            transport=_Transport(_prose()),
        )


def test_a_voice_the_plan_did_not_approve_opens_no_prose():
    transport = _Transport(_prose())

    with pytest.raises(WriterError):
        _write(
            transport=transport,
            brief=VoiceBrief(brief_ref="voice-doc-v4", text=VOICE_TEXT),
        )

    assert transport.calls == 0


def test_the_budget_refuses_before_the_call():
    transport = _Transport(_prose())

    decision = _write(transport=transport, budget=_RefusingBudget())

    assert transport.calls == 0
    assert decision.calls == 0
    assert decision.text is None
    assert decision.signal is None
    assert decision.inputs is None
    assert decision.outcomes[0].state_code is StateCode.BUDGET_EXHAUSTED


# ===========================================================================
# E-15 · what the text is
# ===========================================================================


def _written_inputs() -> Any:
    """The inputs record of one real execution, for entity-level tests."""

    written = _write(transport=_Transport(_prose()))
    assert written.text is not None
    return written.text.inputs


def test_the_text_is_the_plan_executed_and_carries_its_own_signal():
    written = _write(transport=_Transport(_prose()))

    text = written.text
    assert text is not None
    _, plan, _ = _approved()
    assert text.text_id == text_id(plan.plan_id)
    assert text.version == 1
    assert text.plan_ref == plan.plan_ref
    assert text.destination is Destination.LINKEDIN
    assert text.writer_signal.plan_holds is True
    assert text.writer_signal.reason is None
    assert [segment.name for segment in text.segments] == list(SEGMENT_NAMES)
    assert text.title is None and text.dek is None


def test_the_body_is_the_parts_in_order_and_cannot_disagree_with_them():
    """``body`` is derived, so no edit can leave it out of step with its parts."""

    written = _write(transport=_Transport(_prose()))

    text = written.text
    assert text is not None
    assert text.body == "\n\n".join(segment.text for segment in text.segments)
    assert "body" not in {field.name for field in dataclasses.fields(Text)}
    assert text.as_entity()["body"] == text.body


def test_the_content_digest_is_over_what_the_text_says():
    written = _write(transport=_Transport(_prose()))
    text = written.text
    assert text is not None

    same = dataclasses.replace(
        text, version=2, supersedes=(text.text_id, 1)
    )
    changed = dataclasses.replace(
        text,
        segments=(
            TextSegment(name=SEGMENT_NAMES[0], text="Other prose entirely."),
            text.segments[1],
        ),
    )

    assert text.content_digest.startswith("sha256:")
    assert same.content_digest == text.content_digest
    assert changed.content_digest != text.content_digest


def test_an_article_states_a_title_and_a_dek_and_a_post_does_not():
    article = _write(
        transport=_Transport(
            _prose(title="The network behind the minutes", dek="What the filing says.")
        ),
        destination=Destination.WIX,
        plan_format=PlanFormat.ARTICLE,
        library=(),
    )
    assert article.text is not None
    assert article.text.title == "The network behind the minutes"
    assert article.text.dek == "What the filing says."

    untitled = _write(
        transport=_Transport(_prose()),
        destination=Destination.WIX,
        plan_format=PlanFormat.ARTICLE,
        library=(),
    )
    titled_post = _write(transport=_Transport(_prose(title="A headline", dek="A dek")))

    for decision in (untitled, titled_post):
        assert decision.text is None
        assert decision.outcomes[0].state_code is StateCode.TEXT_GENERATION_FAILED


def test_the_links_are_the_cited_sources_and_never_the_calls():
    written = _write(transport=_Transport(_prose()))
    text = written.text
    assert text is not None

    assert text.links == (SOURCE_URL,)
    # src-2 is located by an identifier and is not cited: neither the plan's
    # citations nor a link can reach it.
    assert all("unused" not in link for link in text.links)

    _, plan, _ = _approved()
    assert resolved_links(referenced_core(plan, _strategy(_unit()), _core())) == (
        SOURCE_URL,
    )


def test_the_first_version_supersedes_nothing_and_an_edit_names_what_it_edits():
    """§3's edit lineage: a version above the first is an edit of the one before."""

    written = _write(transport=_Transport(_prose()))
    text = written.text
    assert text is not None
    assert text.version == 1
    assert text.supersedes is None
    assert text.as_entity()["supersedes"] is None

    edited = dataclasses.replace(text, version=2, supersedes=(text.text_id, 1))
    assert edited.as_entity()["supersedes"] == {
        "text_id": text.text_id,
        "version": 1,
    }
    with pytest.raises(WriterError):
        dataclasses.replace(text, version=2)
    with pytest.raises(WriterError):
        dataclasses.replace(text, version=2, supersedes=("txt-other", 1))
    with pytest.raises(WriterError):
        dataclasses.replace(text, supersedes=(text.text_id, 1))


def test_a_part_with_no_prose_is_not_a_part():
    with pytest.raises(WriterError):
        TextSegment(name=SEGMENT_NAMES[0], text="   ")


def test_a_signal_that_holds_carries_no_commentary():
    with pytest.raises(WriterError):
        WriterSignal(plan_holds=True, reason="the plan is fine")
    with pytest.raises(WriterError):
        WriterSignal(plan_holds=False, reason="  ")


def test_a_resolution_with_no_usable_claim_is_refused():
    with pytest.raises(WriterError):
        ReferencedCore(sources=(), claims=(), observations=())


# ===========================================================================
# Storage · §2.3 write ownership, and the topology this stage lives in
# ===========================================================================


def test_the_text_is_written_where_s12_owns_it(tmp_path: Path):
    workspace = _workspace(tmp_path)
    written = _write(transport=_Transport(_prose()))
    text = written.text
    assert text is not None

    entry = write_text(workspace, text)

    assert entry.writer_stage == WRITER_STAGE
    assert entry.path == text_relative_path(
        text.unit_id, text.destination, text.text_id, text.version
    )
    assert owner_of(entry.path) == WRITER_STAGE
    stored = json.loads((workspace.run_dir / entry.path).read_text())
    assert stored["entity_type"] == "E-15"
    assert stored["writer_signal"]["plan_holds"] is True
    assert stored["content_digest"] == text.content_digest
    assert stored["inputs"]["withheld"] == list(WITHHELD_INPUTS)


def test_the_route_out_of_s12_is_the_one_the_topology_declares():
    routes = [
        route
        for route in CANONICAL_TOPOLOGY.replan_routes
        if route.source == WRITER_STAGE
    ]

    assert len(routes) == 1
    assert routes[0].target == "S-08"
    assert routes[0].cause == PLAN_DOES_NOT_HOLD_CAUSE
    assert routes[0].counter == STRATEGY_COUNTER

    barrier = next(
        item for item in CANONICAL_TOPOLOGY.barriers if item.barrier_id == BARRIER_ID
    )
    assert barrier.blocks == WRITER_STAGE


@pytest.mark.parametrize(
    "state_code",
    [StateCode.TEXT_GENERATION_FAILED, StateCode.PLAN_DOES_NOT_HOLD],
)
def test_every_state_this_slice_uses_is_bounded_and_counted(state_code: StateCode):
    """A state with no permitted outcome or no category is one nothing can read."""

    assert permitted_outcomes(state_code)
    assert reason_category(state_code) in tuple(ReasonCategory)


def test_the_writer_module_obeys_the_ce1_placement_rule():
    assert (
        check_module(_REPO_ROOT / "src" / "editorial_core" / "writer.py") == []
    )
