"""Issue #304: 2–4 whole strategies per destination, and the one that is chosen.

SL-5's acceptance evidence for S-08 and S-09, taken from the map's walkthrough B
(§13, "Ramp Launches Instant Stablecoin Payments with Stripe's New Technology") —
the walkthrough AD-01 was written against, where the article carries the argument
on the payment timeline and a short form could carry it on the one figure.

The issue's three acceptance criteria, and the tests that are them:

1. **openings differ across destinations while each uses the leading-material
   set as carrier (AD-01)** —
   ``test_openings_differ_across_destinations_while_each_carries_the_leading_material``,
   with the two halves of the rule pinned separately by
   ``test_a_candidate_whose_opening_does_not_use_the_leading_material_is_kept``
   and ``test_a_carrier_no_move_uses_is_refused``;
2. **no label field on E-13; roles only in StrategySelection** —
   ``test_e13_has_no_label_and_no_role_field``,
   ``test_an_answer_cannot_smuggle_a_label_or_a_role_into_a_candidate`` and
   ``test_the_role_of_a_candidate_lives_only_in_the_selection``;
3. **all destinations fail in one round → REPLAN S-06** —
   ``test_all_destinations_failing_in_one_round_replans_into_s06``, with the
   three ways it must *not* fire in
   ``test_one_destination_failing_leaves_the_anchor_alone``,
   ``test_a_round_short_of_a_destination_cannot_answer_the_unit_rule`` and
   ``test_a_destination_that_established_nothing_does_not_charge_the_anchor``.

And the properties those rest on: one call per destination per attempt and no
field for a sibling or a label, code exclusion before any ranking, a ranking only
where several candidates remain, the weak-candidate limits of Step 4 §5.1, the
``DEGRADE`` to the safest admissible, ``L_strategy`` spent by the route and never
by S-08, and a candidate keeping no standing from the boundary version it was
written against.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from scripts.ci.check_ce1_placement import check_module
from src.artifacts import ArtifactCollisionError
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
    CANDIDATES_MAX,
    CANDIDATES_MIN,
    OPTIONAL_STRATEGY_FIELDS,
    STAGE as STRATEGY_STAGE,
    STRATEGY_COUNTER,
    STRATEGY_FIELDS,
    CandidateSet,
    ClientPosition,
    ContractRule,
    EditorialStrategy,
    FocalSubjectKind,
    RevealKind,
    StrategyAnswer,
    StrategyContract,
    StrategyError,
    candidate_set_id,
    propose_strategies,
    strategy_id,
    strategy_relative_path,
    write_candidate_set,
)
from src.editorial_core.destinations import (
    STAGE as DESTINATION_STAGE,
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
from src.editorial_core.material_features import (
    Asset,
    AssetClass,
    AssetKind,
    Confidence,
    ConfidenceLevel,
    FeatureFigureProvenance,
    FeatureValue,
    Freshness,
    MaterialFeature,
    MaterialFeatures,
)
from src.editorial_core.relevance_screen import AudienceTransfer, DecisionRef
from src.editorial_core.strategy_selection import (
    STAGE as SELECTION_STAGE,
    TIE_BREAKER_ORDER,
    WEAK_CANDIDATE_EARLIEST_TIEBREAKER,
    DegradeReason,
    ExclusionReason,
    SelectionDecision,
    SelectionError,
    StrategyFingerprint,
    TieBreaker,
    acts_alone,
    preference_acts_at,
    promised_points,
    review_unit_round,
    select_strategy,
    selection_relative_path,
    write_strategy_selection,
)
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.knowledge.loader import StageInputs, load_register
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

#: The universal default ladder (K-LAD-01).
LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

SIGNAL = "signal-304-ramp"
CORE = "core-304-ramp"

CLAIMS: dict[str, str] = {
    "ev-1": "The vendor states the payment settles in minutes rather than days.",
    "ev-2": "The filing records the settlement network the payment runs over.",
    "ev-3": "The vendor's page states a fee of 0.5% per transfer.",
    "ev-4": "A trade report puts the prior settlement time at two days.",
}

MECHANISM = "int-304-mechanism"
TIMELINE = "int-304-timeline"
REFUSED = "int-304-refused"

FIGURE = "ast-304-figure"
POSITION = "ast-304-position"

#: The one limitation the boundary states, and therefore the only thing a
#: concession may cite.
LIMIT_TEXT = "The material says nothing about the cost of switching."

#: The seed register's one record that names S-08 in its ``## Influences``
#: (tier 4, descriptive, ``review_by`` 2026-12-20).
LINKEDIN_RECORD = "K-DST-LI-01"


# ===========================================================================
# Fixtures
# ===========================================================================


def _core(core_id: str = CORE, version: int = 1) -> EvidenceCore:
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
        core_id=core_id,
        version=version,
        signal_ids=(SIGNAL,),
        research_artifact_refs=(("artifact-304", "sha256:" + "d" * 64),),
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
    strength_level: int = 2,
    ceiling_level: int = 2,
    kind: InterpretationKind = InterpretationKind.MECHANISM,
) -> Interpretation:
    return Interpretation(
        interpretation_id=identity,
        version=1,
        statement=statement,
        kind=kind,
        support_refs=tuple(supports),
        audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
        strength=LADDER.at(strength_level),
        ceiling=LADDER.at(ceiling_level),
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
    members: Sequence[Interpretation],
    *,
    version: int = 1,
    core_id: str = CORE,
    core_version: int = 1,
) -> InterpretationBoundary:
    return InterpretationBoundary(
        boundary_id=boundary_id(core_id),
        version=version,
        core_ref=(core_id, core_version),
        relevance_ref=DecisionRef(
            path="reports/content_packages/signal-304/decision.json",
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
        limits=(Limitation(text=LIMIT_TEXT, refs=("ev-3",)),),
    )


def _two_readings(**kwargs: Any) -> InterpretationBoundary:
    """The boundary S-08 normally meets: two admissible readings and one refused.

    The anchor's reading keeps one level of headroom under its ceiling and the
    second has none, so the interpretation-risk rung of §7.3 has something to
    separate.
    """

    return _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
                strength_level=2,
                ceiling_level=3,
            ),
            _interpretation(
                TIMELINE,
                "The wait fell from two days to minutes.",
                supports=("ev-1", "ev-4"),
                kind=InterpretationKind.COMPARISON,
            ),
            _interpretation(
                REFUSED,
                "Every business that switches will pay less.",
                supports=(),
                admissible=False,
                kind=InterpretationKind.GENERALIZATION,
            ),
        ),
        **kwargs,
    )


def _narrowed_boundary() -> InterpretationBoundary:
    """Version 2: a commit has made the second reading inadmissible."""

    return _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
                strength_level=2,
                ceiling_level=3,
            ),
            _interpretation(
                TIMELINE,
                "The wait fell from two days to minutes.",
                supports=("ev-1", "ev-4"),
                admissible=False,
                kind=InterpretationKind.COMPARISON,
            ),
        ),
        version=2,
    )


def _assets() -> tuple[Asset, ...]:
    return (
        Asset(
            asset_id=FIGURE,
            asset_class=AssetClass.EVIDENTIARY,
            kind=AssetKind.FIGURE,
            refs=("ev-1",),
            strength=Confidence(
                level=ConfidenceLevel.HIGH, rationale="The vendor states it."
            ),
        ),
        Asset(
            asset_id=POSITION,
            asset_class=AssetClass.POSITIONAL,
            kind=AssetKind.CLIENT_POSITION,
            refs=("ev-2",),
            strength=Confidence(
                level=ConfidenceLevel.MEDIUM, rationale="The contract approved it."
            ),
        ),
    )


def _features(*, documented_case: bool = True) -> MaterialFeatures:
    """E-05 with all twelve features answered (E-05 holds one entry per member)."""

    confidence = Confidence(
        level=ConfidenceLevel.MEDIUM, rationale="Read off the cited excerpts."
    )
    values = [
        FeatureValue(
            feature=MaterialFeature.DOCUMENTED_CASE,
            value=documented_case,
            confidence=confidence,
            evidence_refs=("ev-1",) if documented_case else (),
        ),
        FeatureValue(
            feature=MaterialFeature.FIGURE_PROVENANCE,
            value=FeatureFigureProvenance.THIRD_PARTY,
            confidence=confidence,
            evidence_refs=("ev-3",),
        ),
        FeatureValue(
            feature=MaterialFeature.FRESHNESS,
            value=Freshness.MEDIUM,
            confidence=confidence,
            evidence_refs=("ev-4",),
        ),
    ]
    answered = {item.feature for item in values}
    values.extend(
        FeatureValue(feature=feature, value=False, confidence=confidence)
        for feature in MaterialFeature
        if feature not in answered
    )
    return MaterialFeatures(
        features_id="fea-304", core_ref=(CORE, 1), values=tuple(values)
    )


def _unit(boundary: Optional[InterpretationBoundary] = None) -> EditorialUnit:
    return create_unit(core=_core(), boundary=boundary or _two_readings())


def _anchor(
    unit: EditorialUnit,
    *,
    boundary: Optional[InterpretationBoundary] = None,
) -> Anchor:
    """A proved anchor, for the tests that start after S-06."""

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
            LeadingItem(ref=FIGURE, kind=LeadingMaterialKind.ASSET),
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
    unit: EditorialUnit, destination: Destination = Destination.WIX
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


_DEFAULT_MOVES: tuple[dict[str, Any], ...] = (
    {
        "text": "Name the settlement network.",
        "purpose": "establish the reading",
        "refs": [MECHANISM],
    },
    {
        "text": "Show what the vendor states about the wait.",
        "purpose": "carry the reading on the leading material",
        "refs": ["ev-1"],
    },
)


def _proposal(
    *,
    job: str = "Explain the mechanism behind the new timeline",
    angle: str = "Why did the wait disappear?",
    thesis_refs: Sequence[str] = (MECHANISM,),
    focal_kind: str = "company",
    leading: str = "ev-1",
    moves: Optional[Sequence[dict[str, Any]]] = None,
    opening: str = "The filing names the network. That is the whole story.",
    opening_refs: Sequence[str] = (MECHANISM,),
    reveal: str = "immediate",
    until_move: Optional[int] = None,
    concession: Optional[dict[str, Any]] = None,
    second: Optional[str] = None,
    position: Optional[str] = None,
    knowledge_used: Sequence[str] = (),
    justified: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """One well-formed proposal, with exactly the deviations a test asks for."""

    fields = list(STRATEGY_FIELDS)
    if second is not None:
        fields.append(OPTIONAL_STRATEGY_FIELDS[0])
    if position is not None:
        fields.append(OPTIONAL_STRATEGY_FIELDS[1])
    return {
        "editorial_job": job,
        "angle": angle,
        "thesis": "The settlement network is what removed the wait.",
        "thesis_interpretation_refs": list(thesis_refs),
        "focal_subject_kind": focal_kind,
        "focal_subject": "The vendor named in the filing",
        "focal_subject_refs": ["ev-2"],
        "leading_material_ref": leading,
        "reader_path": [
            dict(move) for move in (moves if moves is not None else _DEFAULT_MOVES)
        ],
        "opening": {
            "text": opening,
            "held_back": "the fee",
            "refs": list(opening_refs),
        },
        "reveal": reveal,
        "until_move": until_move,
        "concession": concession
        or {"present": False, "limitation_ref": None, "move_index": None},
        "ending_intention": "Leave the reader with the new timeline, not the fee.",
        "second_interpretation_ref": second,
        "client_position_ref": position,
        "justifications": [
            {
                "field_name": name,
                "text": f"{name} follows from the anchor and its leading material.",
                "refs": [],
            }
            for name in (fields if justified is None else justified)
        ],
        "knowledge_used": list(knowledge_used),
    }


def _answer(*proposals: dict[str, Any]) -> dict[str, Any]:
    return {"candidates": list(proposals or (_proposal(), _proposal()))}


def _ranking(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"rankings": list(rows)}


def _row(index: int, evidence: int = 3, destination: int = 3) -> dict[str, Any]:
    return {
        "index": index,
        "evidence_fit": evidence,
        "destination_fit": destination,
        "reason": f"candidate {index} judged against both criteria",
    }


def _proposed(
    *proposals: dict[str, Any],
    destination: Destination = Destination.WIX,
    boundary: Optional[InterpretationBoundary] = None,
    contract: Optional[StrategyContract] = None,
    features: Optional[MaterialFeatures] = None,
    knowledge: Sequence[Any] = (),
) -> CandidateSet:
    """Run S-08 and hand back the set, for the tests that start at S-09."""

    snapshot = boundary or _two_readings()
    subject = _unit(snapshot)
    proposal = propose_strategies(
        unit=subject,
        anchor=_anchor(subject, boundary=snapshot),
        decision=_decision(subject, destination),
        boundary=snapshot,
        core=_core(),
        features=features or _features(),
        contract=contract or StrategyContract(),
        transport=_Transport(_answer(*proposals)),
        assets=_assets(),
        knowledge=knowledge,
    )
    assert proposal.candidate_set is not None
    return proposal.candidate_set


def _selected(candidate_set: CandidateSet, **kwargs: Any) -> SelectionDecision:
    return select_strategy(
        candidate_set=candidate_set,
        boundary=kwargs.pop("boundary", None) or _two_readings(),
        core=_core(),
        features=kwargs.pop("features", None) or _features(),
        contract=kwargs.pop("contract", None) or StrategyContract(),
        counters=kwargs.pop("counters", None) or _ledger(),
        assets=_assets(),
        **kwargs,
    )


# ===========================================================================
# AD-01 · the leading material carries, and the opening is free
# ===========================================================================


def test_openings_differ_across_destinations_while_each_carries_the_leading_material():
    """Acceptance 1. AD-01's Model C, as two independent calls.

    The unit's leading-material set is the one thing the destinations share, and
    each destination's strategy foregrounds a member of it in a move. The
    openings are not derived from it and differ — on LinkedIn the opening does
    not touch the leading material at all, which AD-01 explicitly allows.
    """

    unit = _unit()
    anchor = _anchor(unit)
    leading = {item.ref for item in anchor.leading_material}
    figure_path = [
        {
            "text": "Name the settlement network.",
            "purpose": "establish the reading",
            "refs": [MECHANISM],
        },
        {
            "text": "Put the one figure on the screen.",
            "purpose": "carry the reading on the leading material",
            "refs": [FIGURE],
        },
    ]

    article = _Transport(
        _answer(
            _proposal(opening="The filing names the network."),
            _proposal(
                opening="Two days became minutes. Here is the machinery.",
                opening_refs=["ev-4"],
            ),
        )
    )
    post = _Transport(
        _answer(
            _proposal(
                opening="A question first: what were you waiting for?",
                opening_refs=[],
                leading=FIGURE,
                moves=figure_path,
            ),
            _proposal(
                opening="One number, and then the machinery behind it.",
                opening_refs=[],
                leading=FIGURE,
                moves=figure_path,
            ),
        )
    )

    made = {
        Destination.WIX: propose_strategies(
            unit=unit,
            anchor=anchor,
            decision=_decision(unit, Destination.WIX),
            boundary=_two_readings(),
            core=_core(),
            features=_features(),
            contract=StrategyContract(),
            transport=article,
            assets=_assets(),
        ),
        Destination.LINKEDIN: propose_strategies(
            unit=unit,
            anchor=anchor,
            decision=_decision(unit, Destination.LINKEDIN),
            boundary=_two_readings(),
            core=_core(),
            features=_features(),
            contract=StrategyContract(),
            transport=post,
            assets=_assets(),
        ),
    }

    openings: set[str] = set()
    for destination, proposal in made.items():
        assert proposal.candidate_set is not None
        assert proposal.candidate_set.rejected == ()
        candidates = proposal.candidate_set.candidates
        assert len(candidates) == CANDIDATES_MIN
        for candidate in candidates:
            assert candidate.destination is destination
            # AD-01's link: a member of the unit's set, used as the carrier.
            assert candidate.leading_material_ref in leading
            assert candidate.carries_leading_material
            openings.add(candidate.opening.text)

    # AD-01's independence: four strategies, four different openings, and the
    # LinkedIn ones do not touch the leading material in the opening at all.
    assert len(openings) == 2 * CANDIDATES_MIN
    linkedin = made[Destination.LINKEDIN].candidate_set
    assert linkedin is not None
    assert all(candidate.opening.refs == () for candidate in linkedin.candidates)
    assert {candidate.leading_material_ref for candidate in linkedin.candidates} == {
        FIGURE
    }


def test_a_candidate_whose_opening_does_not_use_the_leading_material_is_kept():
    """AD-01 rejected "leading material must be the opening" by name.

    The half of the rule that is easiest to lose: the check reads the moves and
    not the opening, so a candidate that opens on something else survives.
    """

    candidate_set = _proposed(
        _proposal(opening="A question first.", opening_refs=[]),
        _proposal(),
    )

    assert candidate_set.rejected == ()
    first = candidate_set.candidates[0]
    assert first.leading_material_ref not in first.opening.refs
    assert first.carries_leading_material


def test_a_carrier_no_move_uses_is_refused():
    """The other half: a carrier the reader path never uses carries nothing."""

    candidate_set = _proposed(
        _proposal(
            opening_refs=["ev-1"],
            moves=[
                {
                    "text": "Name the settlement network.",
                    "purpose": "establish",
                    "refs": [MECHANISM],
                },
                {
                    "text": "Say what the filing records.",
                    "purpose": "support",
                    "refs": ["ev-2"],
                },
            ],
        ),
        _proposal(),
    )

    assert [item.index for item in candidate_set.rejected] == [1]
    assert "primary evidentiary carrier" in candidate_set.rejected[0].reason
    assert len(candidate_set.candidates) == 1


def test_leading_material_outside_the_anchor_set_is_refused():
    candidate_set = _proposed(_proposal(leading="ev-3"), _proposal())

    assert [item.index for item in candidate_set.rejected] == [1]
    assert "leading-material set" in candidate_set.rejected[0].reason


# ===========================================================================
# I-10 / AD-07 · no label, and no role on E-13
# ===========================================================================


def test_e13_has_no_label_and_no_role_field():
    """Acceptance 2, first half. Fix F-1 and AD-07, as the absence of a field."""

    declared = {field.name for field in dataclasses.fields(EditorialStrategy)}
    assert not {name for name in declared if "label" in name or "role" in name}

    written = _proposed().candidates[0].as_entity()
    assert not {key for key in written if "label" in key or "role" in key}


def test_an_answer_cannot_smuggle_a_label_or_a_role_into_a_candidate():
    """The answer is parsed strictly, so a label has nowhere to arrive either."""

    assert StrategyAnswer.model_validate(_proposal()) is not None
    for smuggled in ("label", "material_label", "role"):
        with pytest.raises(ValidationError):
            StrategyAnswer.model_validate({**_proposal(), smuggled: "Teardown"})


def test_the_role_of_a_candidate_lives_only_in_the_selection():
    """Acceptance 2, second half. E-13 is immutable; the selection holds roles."""

    candidate_set = _proposed(_proposal(), _proposal())
    before = [candidate.as_entity() for candidate in candidate_set.candidates]

    decision = _selected(
        candidate_set, transport=_Transport(_ranking(_row(1, 4), _row(2, 2)))
    )

    selection = decision.selection
    assert selection is not None
    assert selection.chosen == candidate_set.candidates[0].strategy_id
    assert set(selection.admissible) == {
        candidate.strategy_id for candidate in candidate_set.candidates
    }
    # Nothing on the candidates changed, and nothing on them says who won.
    assert [candidate.as_entity() for candidate in candidate_set.candidates] == before
    assert all("chosen" not in entity for entity in before)


def test_the_s08_request_has_nowhere_to_put_a_sibling_or_a_label():
    """§1's "Not an input" row, kept by the shape of the call (I-06, AD-07)."""

    transport = _Transport(_answer())
    unit = _unit()
    propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=transport,
        assets=_assets(),
    )

    sent = json.loads(transport.requests[0])
    assert set(sent) == {
        "unit",
        "anchor",
        "destination",
        "boundary",
        "core",
        "features",
        "assets",
        "contract",
        "knowledge",
    }
    assert sent["destination"]["destination"] == Destination.WIX.value

    taken = set(inspect.signature(propose_strategies).parameters)
    assert not {
        name for name in taken if "sibling" in name or "label" in name or "text" in name
    }


# ===========================================================================
# S-08 · one call per destination per attempt, and the schema
# ===========================================================================


def test_one_call_per_destination_per_attempt():
    transport = _Transport(_answer())
    unit = _unit()

    proposal = propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=transport,
        assets=_assets(),
    )

    assert transport.calls == 1
    assert proposal.calls == 1
    assert proposal.candidate_set is not None
    assert proposal.candidate_set.attempt == 1


@pytest.mark.parametrize("proposed", [1, CANDIDATES_MAX + 1])
def test_an_answer_outside_two_to_four_strategies_is_not_an_answer(proposed: int):
    unit = _unit()

    proposal = propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=_Transport(_answer(*[_proposal() for _ in range(proposed)])),
        assets=_assets(),
    )

    assert proposal.candidate_set is None
    assert [outcome.state_code for outcome in proposal.outcomes] == [
        StateCode.STRATEGY_GENERATION_FAILED
    ]
    assert proposal.outcomes[0].outcome is ArpOutcome.SKIP
    assert proposal.outcomes[0].scope is OutcomeScope.DESTINATION


def test_a_provider_that_refused_is_not_recorded_as_no_admissible_strategy():
    """The state the machinery reaches is kept apart from the editorial one."""

    unit = _unit()

    proposal = propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=_Transport(_answer(), fails=True),
        assets=_assets(),
    )

    assert proposal.candidate_set is None
    outcome = proposal.outcomes[0]
    assert outcome.state_code is StateCode.STRATEGY_GENERATION_FAILED
    assert reason_category(outcome.state_code) is ReasonCategory.PROVIDER
    assert reason_category(StateCode.NO_ADMISSIBLE_STRATEGY) is ReasonCategory.STRATEGY
    assert permitted_outcomes(StateCode.STRATEGY_GENERATION_FAILED) == frozenset(
        {ArpOutcome.SKIP}
    )
    # Nothing of the provider's own text reaches the record.
    assert "the provider refused" not in (outcome.reason or "")


def test_a_thesis_outside_the_anchor_is_refused():
    candidate_set = _proposed(_proposal(thesis_refs=[TIMELINE]), _proposal())

    assert [item.index for item in candidate_set.rejected] == [1]
    assert "anchor" in candidate_set.rejected[0].reason


def test_a_second_interpretation_must_be_admissible_and_in_the_unit_scope():
    candidate_set = _proposed(_proposal(second=REFUSED), _proposal(second=TIMELINE))

    assert [item.index for item in candidate_set.rejected] == [1]
    assert candidate_set.candidates[0].second_interpretation_ref == TIMELINE


def test_a_field_without_a_justification_is_refused():
    short = [name for name in STRATEGY_FIELDS if name != "opening"]
    candidate_set = _proposed(_proposal(justified=short), _proposal())

    assert [item.index for item in candidate_set.rejected] == [1]
    assert "opening" in candidate_set.rejected[0].reason


def test_knowledge_used_is_resolved_against_what_the_stage_was_routed():
    """I-11: ``knowledge_used`` records what reached the stage, not what a
    candidate claims reached it."""

    register = load_register(_REPO_ROOT / "knowledge", today=TODAY)
    routed = register.select(
        STRATEGY_STAGE, StageInputs(destination=Destination.LINKEDIN.value)
    ).routed
    assert LINKEDIN_RECORD in {item.identity for item in routed}

    candidate_set = _proposed(
        _proposal(knowledge_used=[LINKEDIN_RECORD]),
        _proposal(knowledge_used=["K-DST-NOT-ROUTED-01"]),
        destination=Destination.LINKEDIN,
        knowledge=routed,
    )

    assert [item.index for item in candidate_set.rejected] == [2]
    used = candidate_set.candidates[0].knowledge_used
    assert [ref.record_id for ref in used] == [LINKEDIN_RECORD]
    # The tier is the register's answer and never the candidate's.
    assert used[0].tier is KnowledgeTier.PLATFORM_RANKING


def test_a_person_in_the_story_needs_a_documented_case():
    without = _proposed(
        _proposal(focal_kind="person_in_story"),
        _proposal(),
        features=_features(documented_case=False),
    )
    assert [item.index for item in without.rejected] == [1]

    with_case = _proposed(_proposal(focal_kind="person_in_story"), _proposal())
    assert with_case.rejected == ()


def test_a_concession_cites_a_limitation_the_boundary_states():
    candidate_set = _proposed(
        _proposal(
            concession={
                "present": True,
                "limitation_ref": "the material says nothing at all",
                "move_index": 2,
            }
        ),
        _proposal(
            concession={
                "present": True,
                "limitation_ref": LIMIT_TEXT,
                "move_index": 2,
            }
        ),
    )

    assert [item.index for item in candidate_set.rejected] == [1]
    assert candidate_set.candidates[0].concession.limitation_ref == LIMIT_TEXT


def test_a_client_position_comes_only_from_the_contract():
    contract = StrategyContract(
        positions=(
            ClientPosition(
                position_id=POSITION,
                text="We think settlement time is the thing to measure.",
                rule_id="CR-POS-01",
            ),
        )
    )

    refused = _proposed(_proposal(position=FIGURE), _proposal())
    assert [item.index for item in refused.rejected] == [1]

    approved = _proposed(_proposal(position=POSITION), _proposal(), contract=contract)
    assert approved.rejected == ()
    assert approved.candidates[0].client_position_ref == POSITION


def test_a_delayed_reveal_names_a_move_the_path_has():
    candidate_set = _proposed(
        _proposal(reveal="delayed", until_move=7),
        _proposal(reveal="delayed", until_move=2),
    )

    assert [item.index for item in candidate_set.rejected] == [1]
    assert candidate_set.candidates[0].reveal.until_move == 2


def test_s08_refuses_an_anchor_the_newest_boundary_no_longer_admits():
    """§1 Pre: "anchor valid". Commit rule 6, read at the stage that needs it."""

    unit = _unit()
    narrowed = _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
                admissible=False,
            ),
            _interpretation(
                TIMELINE,
                "The wait fell from two days to minutes.",
                supports=("ev-1", "ev-4"),
            ),
        ),
        version=2,
    )

    with pytest.raises(StrategyError, match="does not admit"):
        propose_strategies(
            unit=unit,
            anchor=_anchor(unit),
            decision=_decision(unit),
            boundary=narrowed,
            core=_core(),
            features=_features(),
            contract=StrategyContract(),
            transport=_Transport(_answer()),
            assets=_assets(),
        )


# ===========================================================================
# S-08 · L_strategy is spent by the route, never here
# ===========================================================================


def _route(
    unit: EditorialUnit,
    counters: AttemptCounterLedger,
    destination: Destination = Destination.WIX,
) -> OutcomeRecord:
    return counters.route(
        source=SELECTION_STAGE,
        cause="no_admissible_candidate",
        scope_key=destination_scope_key(unit.unit_id, destination),
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
        reason="nothing was admissible",
    )


def test_a_second_attempt_without_its_route_is_refused():
    unit = _unit()

    with pytest.raises(StrategyError, match="with no route"):
        propose_strategies(
            unit=unit,
            anchor=_anchor(unit),
            decision=_decision(unit),
            boundary=_two_readings(),
            core=_core(),
            features=_features(),
            contract=StrategyContract(),
            transport=_Transport(_answer()),
            assets=_assets(),
            attempt=2,
        )


def test_another_destinations_route_bounds_nothing_here():
    unit = _unit()
    counters = _ledger()
    elsewhere = _route(unit, counters, Destination.LINKEDIN)

    with pytest.raises(StrategyError, match="counted per destination"):
        propose_strategies(
            unit=unit,
            anchor=_anchor(unit),
            decision=_decision(unit),
            boundary=_two_readings(),
            core=_core(),
            features=_features(),
            contract=StrategyContract(),
            transport=_Transport(_answer()),
            assets=_assets(),
            attempt=2,
            re_entry=elsewhere,
        )


def test_an_unkeyed_route_authorizes_no_destination():
    """A REPLAN that names no destination cannot show which one paid.

    ``L_strategy`` is counted per destination (§0.3), so a re-entry has to prove
    the destination whose attempt it spent. ``OutcomeRecord.scope_key`` is
    optional on the durable record, and an absent one means "the scope key of
    the StageRecord that carries it" — which this boundary cannot resolve. If it
    were accepted here, one unkeyed record would authorize a second attempt at
    *every* destination, which is the unbounded loop the counter exists to stop.
    """

    unit = _unit()
    counters = _ledger()
    keyed = _route(unit, counters)
    unkeyed = keyed.model_copy(update={"scope_key": None})
    assert unkeyed.scope_key is None
    assert unkeyed.counter == STRATEGY_COUNTER
    assert unkeyed.outcome is ArpOutcome.REPLAN
    assert unkeyed.route_target == STRATEGY_STAGE

    with pytest.raises(StrategyError, match="counted per destination"):
        propose_strategies(
            unit=unit,
            anchor=_anchor(unit),
            decision=_decision(unit),
            boundary=_two_readings(),
            core=_core(),
            features=_features(),
            contract=StrategyContract(),
            transport=_Transport(_answer()),
            assets=_assets(),
            attempt=2,
            re_entry=unkeyed,
        )


def test_the_route_that_paid_for_the_attempt_names_the_set_it_produces():
    unit = _unit()
    counters = _ledger()
    route = _route(unit, counters)
    assert route.outcome is ArpOutcome.REPLAN
    assert route.counter == STRATEGY_COUNTER
    assert route.route_target == STRATEGY_STAGE

    proposal = propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=_Transport(_answer()),
        assets=_assets(),
        attempt=2,
        re_entry=route,
    )

    assert proposal.candidate_set is not None
    assert proposal.candidate_set.candidate_set_id == candidate_set_id(
        unit.unit_id, Destination.WIX, 2
    )
    assert proposal.candidate_set.candidate_set_id != candidate_set_id(
        unit.unit_id, Destination.WIX, 1
    )
    assert proposal.candidate_set.re_entry_cause == (
        StateCode.NO_ADMISSIBLE_STRATEGY.value
    )


def test_s08_spends_no_counter_of_its_own():
    unit = _unit()
    counters = _ledger()

    propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=_Transport(_answer()),
        assets=_assets(),
    )

    scope_key = destination_scope_key(unit.unit_id, Destination.WIX)
    assert counters.used(STRATEGY_COUNTER, scope_key) == 0


def test_a_budget_refusal_makes_no_call_and_writes_no_set():
    unit = _unit()
    transport = _Transport(_answer())

    proposal = propose_strategies(
        unit=unit,
        anchor=_anchor(unit),
        decision=_decision(unit),
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        transport=transport,
        assets=_assets(),
        budget=_RefusingBudget(),
    )

    assert transport.calls == 0
    assert proposal.calls == 0
    assert proposal.candidate_set is None
    assert proposal.outcomes[0].state_code is StateCode.BUDGET_EXHAUSTED


# ===========================================================================
# S-09 · code first, and a call only where one is needed
# ===========================================================================


def test_one_admissible_candidate_is_chosen_without_a_ranking():
    """§3: "0 [calls] if at most one candidate remains after code exclusion"."""

    candidate_set = _proposed(_proposal(), _proposal(second=TIMELINE))

    decision = _selected(candidate_set, boundary=_narrowed_boundary())

    assert decision.calls == 0
    selection = decision.selection
    assert selection is not None
    assert selection.chosen == candidate_set.candidates[0].strategy_id
    assert selection.deciding_tiebreaker is None
    # Nothing was unresolved, so no §6.2 state was reached.
    assert selection.outcome is None
    assert decision.outcomes == ()


def test_several_admissible_candidates_are_ranked_once():
    candidate_set = _proposed(_proposal(), _proposal())
    transport = _Transport(_ranking(_row(1, 5), _row(2, 2)))

    decision = _selected(candidate_set, transport=transport)

    assert transport.calls == 1
    assert decision.calls == 1
    selection = decision.selection
    assert selection is not None
    assert selection.chosen == candidate_set.candidates[0].strategy_id
    assert selection.deciding_tiebreaker is TieBreaker.EVIDENCE_FIT
    assert selection.outcome is not None
    assert selection.outcome.outcome is ArpOutcome.RESOLVE
    assert selection.outcome.state_code is StateCode.SEVERAL_EQUAL_STRATEGIES


def test_the_tie_breakers_are_applied_in_the_map_order():
    candidate_set = _proposed(_proposal(), _proposal())

    # Evidence fit ties, destination fit does not: the second rung decides.
    decision = _selected(
        candidate_set, transport=_Transport(_ranking(_row(1, 3, 1), _row(2, 3, 5)))
    )

    selection = decision.selection
    assert selection is not None
    assert selection.deciding_tiebreaker is TieBreaker.DESTINATION_FIT
    assert selection.chosen == candidate_set.candidates[1].strategy_id


def test_a_code_rung_decides_when_the_model_cannot():
    """Interpretation risk is arithmetic, and it sits above every soft rung."""

    candidate_set = _proposed(_proposal(), _proposal(second=TIMELINE))

    decision = _selected(
        candidate_set, transport=_Transport(_ranking(_row(1), _row(2)))
    )

    selection = decision.selection
    assert selection is not None
    assert selection.deciding_tiebreaker is TieBreaker.INTERPRETATION_RISK
    # The candidate that rests on the anchor alone keeps a level of headroom.
    assert selection.chosen == candidate_set.candidates[0].strategy_id


def test_the_portfolio_rung_is_a_soft_penalty_and_never_an_exclusion():
    candidate_set = _proposed(_proposal(reveal="gradual"), _proposal())
    recent = (
        StrategyFingerprint(
            fingerprint_id="fp-304-1",
            destination=Destination.WIX,
            focal_subject_kind=FocalSubjectKind.COMPANY,
            reveal=RevealKind.IMMEDIATE,
        ),
    )

    decision = _selected(
        candidate_set,
        transport=_Transport(_ranking(_row(1), _row(2))),
        portfolio=recent,
    )

    selection = decision.selection
    assert selection is not None
    # Both candidates survive: the portfolio orders, it never removes.
    assert len(selection.admissible) == 2
    assert selection.deciding_tiebreaker is TieBreaker.PORTFOLIO
    assert selection.chosen == candidate_set.candidates[0].strategy_id


def test_a_ranking_that_does_not_judge_every_candidate_is_not_a_ranking():
    candidate_set = _proposed(_proposal(), _proposal())

    decision = _selected(candidate_set, transport=_Transport(_ranking(_row(1))))

    selection = decision.selection
    assert selection is not None
    assert selection.degrade_reason is DegradeReason.RANKING_UNAVAILABLE


def test_a_set_that_needs_a_ranking_and_has_no_ranker_is_a_stage_run_wrong():
    candidate_set = _proposed(_proposal(), _proposal())

    with pytest.raises(SelectionError, match="no ranking transport"):
        _selected(candidate_set)


def test_a_budget_refusal_at_s09_establishes_nothing_and_writes_no_selection():
    candidate_set = _proposed(_proposal(), _proposal())
    transport = _Transport(_ranking(_row(1), _row(2)))

    decision = _selected(
        candidate_set, transport=transport, budget=_RefusingBudget()
    )

    assert transport.calls == 0
    assert decision.selection is None
    assert not decision.established_no_candidate
    assert decision.outcomes[0].state_code is StateCode.BUDGET_EXHAUSTED


# ===========================================================================
# S-09 · the deterministic exclusions
# ===========================================================================


def test_a_candidate_keeps_no_standing_from_the_boundary_it_was_written_against():
    """The stale form does not keep the authority the fresh one has withdrawn."""

    candidate_set = _proposed(_proposal(second=TIMELINE), _proposal(second=TIMELINE))
    assert candidate_set.rejected == ()
    assert all(candidate.boundary_ref[1] == 1 for candidate in candidate_set.candidates)

    decision = _selected(candidate_set, boundary=_narrowed_boundary())

    selection = decision.selection
    assert selection is not None
    assert selection.admissible == ()
    assert {item.reason for item in selection.excluded} == {
        ExclusionReason.INADMISSIBLE_INTERPRETATION
    }
    assert all(item.tier is KnowledgeTier.EVIDENCE for item in selection.excluded)


def test_a_promise_wider_than_the_boundary_is_excluded_before_any_ranking():
    """V-P02, and the map's own example: "3 things" against two readings."""

    three_things = _proposal(
        second=TIMELINE,
        moves=[
            {"text": "One.", "purpose": "point", "refs": [MECHANISM]},
            {"text": "Two.", "purpose": "point", "refs": [TIMELINE]},
            {"text": "Three.", "purpose": "point", "refs": [MECHANISM, "ev-1"]},
        ],
    )
    candidate_set = _proposed(three_things, _proposal())
    assert promised_points(candidate_set.candidates[0]) == 3

    transport = _Transport(_ranking(_row(1)))
    decision = _selected(candidate_set, transport=transport)

    selection = decision.selection
    assert selection is not None
    assert [item.reason for item in selection.excluded] == [
        ExclusionReason.PROMISE_WIDER_THAN_BOUNDARY
    ]
    assert selection.chosen == candidate_set.candidates[1].strategy_id
    # One candidate left after code exclusion, so no ranking was needed.
    assert transport.calls == 0


def test_a_tier_two_prohibition_excludes_with_its_rule_and_tier():
    contract = StrategyContract(
        prohibitions=(
            ContractRule(
                rule_id="CR-NO-DELAY",
                text="This client does not hold the point back.",
                reveals=(RevealKind.DELAYED,),
            ),
        )
    )
    candidate_set = _proposed(_proposal(reveal="delayed", until_move=2), _proposal())

    decision = _selected(candidate_set, contract=contract)

    selection = decision.selection
    assert selection is not None
    assert [item.rule_ref for item in selection.excluded] == ["CR-NO-DELAY"]
    assert selection.excluded[0].reason is ExclusionReason.CONTRACT_PROHIBITION
    assert selection.excluded[0].tier is KnowledgeTier.APPROVED_CLIENT_RULE


def test_a_prohibition_weaker_than_tier_two_is_refused_as_a_prohibition():
    with pytest.raises(StrategyError, match="deterministic exclusions"):
        StrategyContract(
            prohibitions=(
                ContractRule(
                    rule_id="CR-SOFT",
                    text="A preference, offered as a prohibition.",
                    tier=KnowledgeTier.EDITORIAL,
                    reveals=(RevealKind.DELAYED,),
                ),
            )
        )


# ===========================================================================
# Step 4 §5.1 · what a weak candidate may not do
# ===========================================================================


def _weak(*, reinforced: Optional[str] = None) -> KnowledgeRef:
    return KnowledgeRef(
        record_id="CR-WEAK-01",
        record_version=1,
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        file_status=KnowledgeStatus.CANDIDATE,
        effective_status=KnowledgeStatus.WEAK_CANDIDATE,
        reinforced_by=reinforced,
    )


def test_a_weak_candidate_alone_excludes_nothing_and_is_recorded_as_a_hint():
    rule = ContractRule(
        rule_id="CR-WEAK-01",
        text="Nobody has re-checked this one.",
        reveals=(RevealKind.DELAYED,),
        knowledge=_weak(),
    )
    candidate_set = _proposed(
        _proposal(reveal="delayed", until_move=2),
        _proposal(reveal="delayed", until_move=2),
    )

    decision = _selected(
        candidate_set,
        contract=StrategyContract(prohibitions=(rule,)),
        transport=_Transport(_ranking(_row(1, 5), _row(2, 2))),
    )

    selection = decision.selection
    assert selection is not None
    assert not acts_alone(rule)
    assert selection.excluded == ()
    assert len(selection.hints) == len(candidate_set.candidates)
    assert selection.hints[0].rule_ref == "CR-WEAK-01"
    assert selection.hints[0].knowledge.effective_status is (
        KnowledgeStatus.WEAK_CANDIDATE
    )
    assert selection.chosen is not None


def test_a_reinforced_weak_candidate_acts_at_its_own_weight():
    rule = ContractRule(
        rule_id="CR-WEAK-01",
        text="Reinforced by a rule nobody demoted.",
        reveals=(RevealKind.DELAYED,),
        knowledge=_weak(reinforced="CR-FRESH-02"),
    )
    candidate_set = _proposed(_proposal(reveal="delayed", until_move=2), _proposal())

    decision = _selected(candidate_set, contract=StrategyContract(prohibitions=(rule,)))

    selection = decision.selection
    assert selection is not None
    assert acts_alone(rule)
    assert selection.hints == ()
    assert [item.rule_ref for item in selection.excluded] == ["CR-WEAK-01"]


def test_a_weak_candidate_may_not_order_the_three_rungs_that_rest_on_evidence():
    weak = ContractRule(rule_id="CR-WEAK-01", text="Demoted.", knowledge=_weak())
    fresh = ContractRule(rule_id="CR-FRESH-01", text="In force.")

    early = TIE_BREAKER_ORDER[
        : TIE_BREAKER_ORDER.index(WEAK_CANDIDATE_EARLIEST_TIEBREAKER)
    ]
    assert early == (
        TieBreaker.EVIDENCE_FIT,
        TieBreaker.DESTINATION_FIT,
        TieBreaker.INTERPRETATION_RISK,
    )
    for rung in early:
        assert not preference_acts_at(weak, rung)
        assert preference_acts_at(fresh, rung)
    for rung in TIE_BREAKER_ORDER[len(early) :]:
        assert preference_acts_at(weak, rung)


def test_a_precedence_application_records_which_record_won():
    prohibition = ContractRule(
        rule_id="CR-NO-DELAY",
        text="No delayed reveal for this client.",
        reveals=(RevealKind.DELAYED,),
        knowledge=KnowledgeRef(
            record_id="K-CLI-01",
            record_version=1,
            tier=KnowledgeTier.APPROVED_CLIENT_RULE,
            file_status=KnowledgeStatus.APPROVED_RULE,
            effective_status=KnowledgeStatus.APPROVED_RULE,
        ),
    )
    preference = ContractRule(
        rule_id="K-EDI-01",
        text="A delayed reveal suits the company as subject.",
        tier=KnowledgeTier.EDITORIAL,
        focal_subjects=(FocalSubjectKind.COMPANY,),
        knowledge=KnowledgeRef(
            record_id="K-EDI-01",
            record_version=1,
            tier=KnowledgeTier.EDITORIAL,
            file_status=KnowledgeStatus.DESCRIPTIVE,
            effective_status=KnowledgeStatus.DESCRIPTIVE,
        ),
    )
    candidate_set = _proposed(_proposal(reveal="delayed", until_move=2), _proposal())

    decision = _selected(
        candidate_set,
        contract=StrategyContract(
            prohibitions=(prohibition,), preferences=(preference,)
        ),
    )

    selection = decision.selection
    assert selection is not None
    applied = selection.precedence_applications
    assert len(applied) == 1
    assert applied[0].winner.record_id == "K-CLI-01"
    assert applied[0].loser.record_id == "K-EDI-01"


# ===========================================================================
# S-09 · DEGRADE to the safest admissible
# ===========================================================================


def test_a_ranking_that_cannot_be_read_degrades_to_the_safest_admissible():
    candidate_set = _proposed(_proposal(second=TIMELINE), _proposal())

    decision = _selected(candidate_set, transport=_Transport("not json"))

    selection = decision.selection
    assert selection is not None
    assert selection.outcome is not None
    assert selection.outcome.outcome is ArpOutcome.DEGRADE
    assert selection.degrade_reason is DegradeReason.RANKING_UNAVAILABLE
    assert selection.deciding_tiebreaker is None
    # The safest is the one with the most headroom under its ceiling, which is
    # the candidate resting on the anchor alone.
    assert selection.chosen == candidate_set.candidates[1].strategy_id
    assert decision.calls == 1


def test_leaders_no_criterion_separates_are_a_degrade_and_say_why():
    candidate_set = _proposed(_proposal(), _proposal())

    decision = _selected(
        candidate_set, transport=_Transport(_ranking(_row(1, 3, 3), _row(2, 3, 3)))
    )

    selection = decision.selection
    assert selection is not None
    assert selection.degrade_reason is DegradeReason.LEADERS_INSEPARABLE
    assert selection.outcome is not None
    assert selection.outcome.outcome is ArpOutcome.DEGRADE
    # Two facts a reader must be able to tell apart, and the durable record
    # carries the difference rather than the free-text reason.
    written = selection.as_entity()
    assert written["degrade_reason"] == DegradeReason.LEADERS_INSEPARABLE.value
    assert written["deciding_tiebreaker"] is None


def test_the_degrade_never_reaches_past_the_candidates_the_rules_allowed():
    """Fail-closed: the safest is chosen among the survivors, not among all."""

    contract = StrategyContract(
        prohibitions=(
            ContractRule(
                rule_id="CR-NO-DELAY",
                text="No delayed reveal.",
                reveals=(RevealKind.DELAYED,),
            ),
        )
    )
    candidate_set = _proposed(
        _proposal(reveal="delayed", until_move=2),
        _proposal(second=TIMELINE),
        _proposal(second=TIMELINE, job="A second reading, told twice over"),
    )

    decision = _selected(
        candidate_set, contract=contract, transport=_Transport("not json")
    )

    selection = decision.selection
    assert selection is not None
    assert selection.degrade_reason is DegradeReason.RANKING_UNAVAILABLE
    assert selection.chosen in selection.admissible
    assert selection.chosen != candidate_set.candidates[0].strategy_id


# ===========================================================================
# S-09 · no admissible candidate, and the unit rule (fix F-5)
# ===========================================================================


def _failed(
    unit: EditorialUnit,
    destination: Destination,
    counters: AttemptCounterLedger,
) -> SelectionDecision:
    """One destination that established it has no admissible candidate."""

    empty = CandidateSet(
        unit_id=unit.unit_id,
        destination=destination,
        candidate_set_id=candidate_set_id(unit.unit_id, destination, 1),
        attempt=1,
    )
    return select_strategy(
        candidate_set=empty,
        boundary=_two_readings(),
        core=_core(),
        features=_features(),
        contract=StrategyContract(),
        counters=counters,
        assets=_assets(),
    )


def test_no_admissible_candidate_replans_the_destination_into_s08():
    unit = _unit()
    counters = _ledger()

    decision = _failed(unit, Destination.WIX, counters)

    assert decision.established_no_candidate
    route = decision.outcomes[0]
    assert route.outcome is ArpOutcome.REPLAN
    assert route.route_target == STRATEGY_STAGE
    assert route.counter == STRATEGY_COUNTER
    assert route.scope is OutcomeScope.DESTINATION
    assert route.state_code is StateCode.NO_ADMISSIBLE_STRATEGY
    selection = decision.selection
    assert selection is not None
    assert selection.chosen is None
    assert selection.outcome is route


def test_the_destination_is_skipped_once_l_strategy_is_gone():
    unit = _unit()
    counters = _ledger(L_strategy=1)

    first = _failed(unit, Destination.WIX, counters)
    second = _failed(unit, Destination.WIX, counters)

    assert first.outcomes[0].outcome is ArpOutcome.REPLAN
    assert second.outcomes[0].outcome is ArpOutcome.SKIP
    assert second.outcomes[0].scope is OutcomeScope.DESTINATION
    assert second.outcomes[0].state_code is StateCode.NO_ADMISSIBLE_STRATEGY


def test_all_destinations_failing_in_one_round_replans_into_s06():
    """Acceptance 3. Fix F-5's unit rule, and the counter it spends."""

    unit = _unit()
    counters = _ledger()
    eligible = (Destination.WIX, Destination.LINKEDIN)
    decisions = [_failed(unit, destination, counters) for destination in eligible]

    route = review_unit_round(
        unit_id=unit.unit_id,
        eligible=eligible,
        decisions=decisions,
        counters=counters,
    )

    assert route is not None
    assert route.outcome is ArpOutcome.REPLAN
    assert route.route_target == "S-06"
    assert route.counter == "L_anchor"
    assert route.scope is OutcomeScope.UNIT
    assert route.scope_key == unit.unit_id
    assert route.state_code is StateCode.NO_ADMISSIBLE_STRATEGY


def test_one_destination_failing_leaves_the_anchor_alone():
    unit = _unit()
    counters = _ledger()
    survived = _selected(
        _proposed(_proposal(), _proposal(), destination=Destination.LINKEDIN),
        counters=counters,
        transport=_Transport(_ranking(_row(1, 5), _row(2, 2))),
    )
    assert survived.unit_id == unit.unit_id

    route = review_unit_round(
        unit_id=unit.unit_id,
        eligible=(Destination.WIX, Destination.LINKEDIN),
        decisions=[_failed(unit, Destination.WIX, counters), survived],
        counters=counters,
    )

    assert route is None
    assert counters.used("L_anchor", unit.unit_id) == 0


def test_a_round_short_of_a_destination_cannot_answer_the_unit_rule():
    unit = _unit()
    counters = _ledger()

    with pytest.raises(SelectionError, match="without a decision for"):
        review_unit_round(
            unit_id=unit.unit_id,
            eligible=(Destination.WIX, Destination.LINKEDIN),
            decisions=[_failed(unit, Destination.WIX, counters)],
            counters=counters,
        )

    assert counters.used("L_anchor", unit.unit_id) == 0


def test_a_destination_that_established_nothing_does_not_charge_the_anchor():
    """A budget refusal is not a verdict about the anchor."""

    unit = _unit()
    counters = _ledger()
    refused = _selected(
        _proposed(_proposal(), _proposal(), destination=Destination.LINKEDIN),
        counters=counters,
        transport=_Transport(_ranking(_row(1), _row(2))),
        budget=_RefusingBudget(),
    )
    assert refused.selection is None

    route = review_unit_round(
        unit_id=unit.unit_id,
        eligible=(Destination.WIX, Destination.LINKEDIN),
        decisions=[_failed(unit, Destination.WIX, counters), refused],
        counters=counters,
    )

    assert route is None
    assert counters.used("L_anchor", unit.unit_id) == 0


def test_the_unit_route_skips_the_unit_once_l_anchor_is_gone():
    unit = _unit()
    counters = _ledger(L_anchor=1)
    eligible = (Destination.WIX,)

    first = review_unit_round(
        unit_id=unit.unit_id,
        eligible=eligible,
        decisions=[_failed(unit, Destination.WIX, counters)],
        counters=counters,
    )
    second = review_unit_round(
        unit_id=unit.unit_id,
        eligible=eligible,
        decisions=[_failed(unit, Destination.WIX, counters)],
        counters=counters,
    )

    assert first is not None
    assert first.outcome is ArpOutcome.REPLAN
    assert second is not None
    assert second.outcome is ArpOutcome.SKIP
    assert second.scope is OutcomeScope.UNIT


def test_a_round_over_a_destination_s07_never_made_eligible_is_refused():
    unit = _unit()
    counters = _ledger()

    with pytest.raises(SelectionError, match="did not make eligible"):
        review_unit_round(
            unit_id=unit.unit_id,
            eligible=(Destination.WIX,),
            decisions=[
                _failed(unit, Destination.WIX, counters),
                _failed(unit, Destination.TELEGRAM, counters),
            ],
            counters=counters,
        )


def test_both_routes_out_of_s09_are_the_ones_the_topology_declares():
    declared = {
        (route.cause, route.target, route.counter)
        for route in CANONICAL_TOPOLOGY.replan_routes
        if route.source == SELECTION_STAGE
    }

    assert declared == {
        ("no_admissible_candidate", STRATEGY_STAGE, "L_strategy"),
        ("no_admissible_candidate_on_any_destination", "S-06", "L_anchor"),
    }


# ===========================================================================
# Storage: §2.3 write ownership, and create-once
# ===========================================================================


def test_the_candidates_and_the_selection_are_written_by_their_own_stages(
    tmp_path: Path,
):
    workspace = _workspace(tmp_path)
    candidate_set = _proposed(_proposal(), _proposal())
    decision = _selected(
        candidate_set, transport=_Transport(_ranking(_row(1, 5), _row(2, 2)))
    )
    assert decision.selection is not None

    written = write_candidate_set(workspace, candidate_set)
    index = write_strategy_selection(workspace, decision.selection)

    assert [entry.writer_stage for entry in written] == [STRATEGY_STAGE] * 2
    assert index.writer_stage == SELECTION_STAGE
    for entry in written:
        assert owner_of(entry.path) == STRATEGY_STAGE
    assert owner_of(index.path) == SELECTION_STAGE
    assert index.path == selection_relative_path(
        candidate_set.unit_id,
        candidate_set.destination,
        candidate_set.candidate_set_id,
    )
    assert written[0].path == strategy_relative_path(
        candidate_set.unit_id,
        candidate_set.destination,
        candidate_set.candidate_set_id,
        candidate_set.candidates[0].strategy_id,
    )


def test_a_candidate_is_written_once(tmp_path: Path):
    workspace = _workspace(tmp_path)
    candidate_set = _proposed(_proposal(), _proposal())

    write_candidate_set(workspace, candidate_set)

    with pytest.raises(ArtifactCollisionError):
        write_candidate_set(workspace, candidate_set)


def test_the_selection_of_a_new_attempt_has_a_path_of_its_own():
    unit = _unit()
    first = candidate_set_id(unit.unit_id, Destination.WIX, 1)
    second = candidate_set_id(unit.unit_id, Destination.WIX, 2)

    assert selection_relative_path(
        unit.unit_id, Destination.WIX, first
    ) != selection_relative_path(unit.unit_id, Destination.WIX, second)
    assert strategy_id(first, 1) != strategy_id(second, 1)


# ===========================================================================
# CE-1 · the two stages hold no pipeline of their own
# ===========================================================================


@pytest.mark.parametrize(
    "module", ["candidate_strategies.py", "strategy_selection.py"]
)
def test_neither_stage_selects_stages_by_destination(module: str):
    """CE-1's placement rule, run over the modules this issue adds."""

    assert check_module(_REPO_ROOT / "src" / "editorial_core" / module) == []


@pytest.mark.parametrize(
    ("module", "protocol"),
    [
        ("candidate_strategies.py", "StrategyTransport"),
        ("strategy_selection.py", "RankingTransport"),
    ],
)
def test_each_stage_has_exactly_one_transport_and_one_call_site(
    module: str, protocol: str
):
    """§1 and §3's Calls columns, read off the modules rather than off a run."""

    source = (_REPO_ROOT / "src" / "editorial_core" / module).read_text(
        encoding="utf-8"
    )
    named = [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name.endswith("Transport")
    ]

    assert named == [protocol]
    assert source.count(".complete(") == 1


def test_s07_s08_and_s09_are_neighbours_in_the_one_topology():
    identifiers = CANONICAL_TOPOLOGY.stage_ids

    assert identifiers.index(STRATEGY_STAGE) == identifiers.index(DESTINATION_STAGE) + 1
    assert identifiers.index(SELECTION_STAGE) == identifiers.index(STRATEGY_STAGE) + 1
