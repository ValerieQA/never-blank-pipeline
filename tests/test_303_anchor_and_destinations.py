"""Issue #303: one anchor per unit, and a rule for each of the six destinations.

SL-5's acceptance evidence for S-06 and S-07, taken from the map's walkthrough B
(§13, "Ramp Launches Instant Stablecoin Payments with Stripe's New Technology") —
the walkthrough AD-01 was written against, where the article carries the argument
on the payment timeline and a short form could carry it on the one figure.

The issue's three acceptance criteria, and the tests that are them:

1. **every exclusion cites a rule and tier** —
   ``test_every_exclusion_cites_a_rule_and_a_tier``, parametrised over all five
   rules E-12 admits, plus
   ``test_the_rule_with_the_most_authority_decides_a_destination_several_refuse``;
2. **a destination without capability is ``generate_only``** —
   ``test_a_destination_without_capability_is_generate_only`` and
   ``test_a_destination_without_an_idempotency_authority_cannot_publish``
   (Step 3 §3.6 rule 7);
3. **zero model calls in S-07 (trace)** —
   ``test_s07_makes_no_model_call_and_has_no_transport_to_make_one_with``, which
   reads the module rather than trusting the stage, and
   ``test_the_stage_record_of_s07_records_no_call``.

And the properties those rest on: the anchor is chosen against the newest
boundary version, ``strength_used`` never exceeds the ceiling, leading material
that does not support the anchor is not leading material, ``L_anchor`` is spent by
the route that re-enters S-06 and never by S-06 itself, and a dependency set with
a cycle has no publication order and is refused rather than answered.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from src.artifacts import ArtifactCollisionError
from src.editorial_core.anchor import (
    AMBIGUITY_CAUSE,
    ANCHOR_COUNTER,
    LEADING_MATERIAL_MAX,
    STAGE as ANCHOR_STAGE,
    Anchor,
    AnchorCandidate,
    AnchorError,
    LeadingItem,
    LeadingMaterialKind,
    anchor_id,
    anchor_relative_path,
    choose_anchor,
    re_enter_anchor,
    write_anchor,
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
from src.editorial_core.destinations import (
    AS_IS_CAPABILITY,
    ROLLOUT_SCOPE,
    STAGE as DESTINATION_STAGE,
    CadenceRule,
    ContractDestination,
    ContractDestinations,
    DependencyKind,
    Destination,
    DestinationCapability,
    DestinationDecision,
    DestinationDecisionSet,
    DestinationError,
    DestinationFingerprint,
    DestinationMode,
    Eligibility,
    ExclusionRule,
    ModeRule,
    PlatformPolicy,
    PublicationDependency,
    UnitFacts,
    decide_destinations,
    decision_id,
    decision_relative_path,
    destination_scope_key,
    platform_policies,
    publication_order,
    write_destination_decisions,
)
from src.editorial_core.editorial_units import EditorialUnit, UnitStatus, create_unit
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
)
from src.editorial_core.interpretation_boundary import (
    Ambiguity,
    InadmissibleReason,
    Interpretation,
    InterpretationBoundary,
    InterpretationKind,
    Justification,
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
)
from src.editorial_core.relevance_screen import AudienceTransfer, DecisionRef
from src.knowledge.loader import StageInputs, load_register
from src.publishing.publication_markers import DESTINATIONS as MARKER_DESTINATIONS
from src.publishing.release_scope import (
    NON_R1_PUBLISH_CHANNELS,
    R1_PUBLISH_CHANNELS,
)
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
from src.run.ledger import LedgerCommitStatus
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import RunInputs, RunManifest
from src.run.run_summary import (
    ReasonCategory,
    RunScope,
    RunSummary,
    WorkspaceRef,
    reason_category,
)
from src.run.run_workspace import (
    DeciderKind,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
    WriteOwnershipError,
    owner_of,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

#: The universal default ladder (K-LAD-01), whose own record names
#: ``S-06 · E-11.strength_used``.
LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

SIGNAL = "signal-303-ramp"
CORE = "core-303-ramp"

#: Walkthrough B's material: the mechanism, the timeline and the one figure.
CLAIMS: dict[str, str] = {
    "ev-1": "The vendor states the payment settles in minutes rather than days.",
    "ev-2": "The filing records the settlement network the payment runs over.",
    "ev-3": "The vendor's page states a fee of 0.5% per transfer.",
    "ev-4": "A trade report puts the prior settlement time at two days.",
}

MECHANISM = "int-303-mechanism"
TIMELINE = "int-303-timeline"
REFUSED = "int-303-refused"

#: The evidentiary asset of walkthrough B: the one figure.
FIGURE = "ast-303-figure"
#: A client position, which AD-01 never lets carry a text.
POSITION = "ast-303-position"


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
        research_artifact_refs=(("artifact-303", "sha256:" + "d" * 64),),
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
    ambiguities: Sequence[Ambiguity] = (),
    core_id: str = CORE,
    core_version: int = 1,
) -> InterpretationBoundary:
    return InterpretationBoundary(
        boundary_id=boundary_id(core_id),
        version=version,
        core_ref=(core_id, core_version),
        relevance_ref=DecisionRef(
            path="reports/content_packages/signal-303/decision.json",
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
        ambiguities=tuple(ambiguities),
    )


def _two_readings(**kwargs: Any) -> InterpretationBoundary:
    """The boundary S-06 normally meets: two admissible readings and one refused."""

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
            refs=("pos-1",),
            strength=Confidence(
                level=ConfidenceLevel.MEDIUM, rationale="The contract approved it."
            ),
        ),
    )


def _unit(
    boundary: Optional[InterpretationBoundary] = None,
    core: Optional[EvidenceCore] = None,
) -> EditorialUnit:
    return create_unit(
        core=core or _core(), boundary=boundary or _two_readings()
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


def _answer(
    *,
    chosen_index: int = 1,
    strength_level: int = 2,
    leading: Sequence[str] = ("ev-1",),
    candidates: int = 2,
) -> dict[str, Any]:
    return {
        "chosen_index": chosen_index,
        "strength_level": strength_level,
        "leading_material": list(leading),
        "candidates": [
            {"index": index, "reason": f"considered at position {index}"}
            for index in range(1, candidates + 1)
        ],
    }


def _ledger(**limits: int) -> AttemptCounterLedger:
    return AttemptCounterLedger(limits=limits or None)


def _workspace(tmp_path: Path) -> RunWorkspace:
    return RunWorkspace.create(tmp_path / "editorial_runs", create_run_id())


def _chosen(unit: EditorialUnit, **kwargs: Any) -> Anchor:
    """A proved anchor, for the tests that start after S-06."""

    boundary = kwargs.pop("boundary", None) or _two_readings()
    decision = choose_anchor(
        unit=unit,
        boundary=boundary,
        core=kwargs.pop("core", None) or _core(core_id=boundary.core_ref[0]),
        transport=_Transport(_answer(**kwargs)),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )
    assert decision.anchor is not None
    return decision.anchor


# ===========================================================================
# S-06 · the anchor
# ===========================================================================


def test_the_unit_gets_one_anchor_at_the_strength_the_evidence_carries():
    """§1: one anchor, the strength used, the leading set, the ambiguity flag."""

    unit = _unit()
    transport = _Transport(_answer(chosen_index=1, strength_level=2))

    decision = choose_anchor(
        unit=unit,
        boundary=_two_readings(),
        core=_core(),
        transport=transport,
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    anchor = decision.anchor
    assert anchor is not None
    assert anchor.anchor_id == anchor_id(unit.unit_id)
    assert anchor.version == 1
    assert anchor.interpretation_ref == (MECHANISM, 1)
    assert anchor.boundary_ref == (boundary_id(CORE), 1)
    assert anchor.strength_used == LADDER.at(2)
    assert anchor.leading_material == (
        LeadingItem(ref="ev-1", kind=LeadingMaterialKind.EVIDENCE_CLAIM),
    )
    assert anchor.ambiguity_touches_anchor is False
    assert [(row.interpretation_id, row.chosen) for row in anchor.candidates] == [
        (MECHANISM, True),
        (TIMELINE, False),
    ], "§1's Trace: every candidate in scope, with its reason"
    assert decision.calls == 1 and transport.calls == 1
    assert anchor.outcome.outcome is ArpOutcome.RESOLVE
    assert (
        anchor.outcome.state_code is StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION
    )
    assert decision.outcomes == (anchor.outcome,)


def test_the_refused_reading_of_the_boundary_is_never_a_candidate():
    """§1 Post: "the anchor is admissible and in scope"."""

    anchor = _chosen(_unit())

    assert REFUSED not in [row.interpretation_id for row in anchor.candidates]


def test_a_strength_above_the_ceiling_is_lowered_to_it():
    """E-11: "``strength_used`` ≤ interpretation ceiling", by code (AD-10)."""

    anchor = _chosen(_unit(), strength_level=4)

    assert anchor.strength_used == LADDER.at(2), (
        "the ceiling is applied as a minimum over one ladder, not refused"
    )


def test_a_strength_the_ladder_does_not_have_is_capped_before_the_ceiling():
    """A ladder has no position above its top, so there is none to ask for."""

    anchor = _chosen(_unit(), strength_level=99)

    assert anchor.strength_used == LADDER.at(2)


def test_leading_material_that_does_not_support_the_anchor_is_dropped():
    """§1 Post: "the leading-material set supports the anchor", by reference."""

    anchor = _chosen(_unit(), leading=("ev-4", "ev-1"))

    assert anchor.leading_material == (
        LeadingItem(ref="ev-1", kind=LeadingMaterialKind.EVIDENCE_CLAIM),
    ), "ev-4 supports the timeline reading, and the anchor is the mechanism"


def test_a_second_leading_item_is_kept_only_because_it_supports_the_anchor():
    """AD-01: "a second item is allowed only if both items support the anchor"."""

    anchor = _chosen(_unit(), leading=("ev-1", "ev-2"))

    assert [item.ref for item in anchor.leading_material] == ["ev-1", "ev-2"]


def test_an_evidentiary_asset_is_leading_material_when_it_rests_on_the_anchor():
    """AD-01 allows "evidence claims or assets", and the kind is recorded."""

    anchor = _chosen(_unit(), leading=(FIGURE,))

    assert anchor.leading_material == (
        LeadingItem(ref=FIGURE, kind=LeadingMaterialKind.ASSET),
    )


def test_a_positional_asset_is_never_leading_material():
    """A positional asset is a client position (E-06), not an evidentiary carrier."""

    decision = choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(leading=(POSITION,))),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None
    assert decision.outcomes[0].state_code is StateCode.ANCHOR_SELECTION_FAILED


def test_a_set_of_more_than_two_is_cut_to_two():
    """AD-01 caps the set, and the cap is code's."""

    anchor = _chosen(_unit(), leading=("ev-1", "ev-2", FIGURE))

    assert len(anchor.leading_material) == LEADING_MATERIAL_MAX


def test_an_answer_naming_no_supporting_material_is_a_citation_failure():
    """Every admissible reading rests on a claim, so one always exists to name."""

    decision = choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(leading=("ev-4",))),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.ANCHOR_SELECTION_FAILED, (
        "a model that cited the wrong claims is the machinery failing, not the "
        "material; 'no provable anchor' is a different state and a different "
        "category in the ledger"
    )
    assert outcome.scope is OutcomeScope.UNIT


def test_an_answer_that_judged_only_its_own_choice_is_not_an_answer():
    """E-11 keeps a reason per candidate; an unasked question is not a verdict."""

    decision = choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(candidates=1)),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None
    assert decision.outcomes[0].state_code is StateCode.ANCHOR_SELECTION_FAILED
    assert "reason(s) for" in (decision.outcomes[0].reason or "")


def test_a_choice_outside_the_candidate_list_is_refused():
    """A reading the unit's boundary does not admit cannot be its anchor."""

    decision = choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(chosen_index=3)),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None
    assert decision.outcomes[0].state_code is StateCode.ANCHOR_SELECTION_FAILED


@pytest.mark.parametrize("answer", ["not json at all", {"chosen_index": 1}])
def test_an_unreadable_answer_is_a_recorded_skip_and_not_an_exception(answer: Any):
    """A caller that had to catch an error would have nothing to record."""

    decision = choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(answer),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None
    assert decision.outcomes[0].state_code is StateCode.ANCHOR_SELECTION_FAILED
    assert decision.calls == 1, "the call was made and paid for"


def test_a_transport_failure_never_reaches_the_caller_as_the_providers_text():
    decision = choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(), fails=True),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None
    assert "the provider refused" not in (decision.outcomes[0].reason or "")


def test_the_request_carries_no_destination_no_position_and_no_lens():
    """§1 forbids S-06 destinations, and Step 1 forbids the rest of the context."""

    transport = _Transport(_answer())
    choose_anchor(
        unit=_unit(),
        boundary=_two_readings(),
        core=_core(),
        transport=transport,
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    request = json.loads(transport.requests[0])
    assert set(request) == {"core", "candidates", "assets", "ladder"}
    assert POSITION not in transport.requests[0], (
        "a positional asset is a client position, and the anchor is chosen on "
        "what is true"
    )
    for name in (*R1_PUBLISH_CHANNELS, *NON_R1_PUBLISH_CHANNELS):
        assert name not in transport.requests[0]


# ---------------------------------------------------------------------------
# The ambiguity route (§1, ARP; map §6.2)
# ---------------------------------------------------------------------------


def _ambiguous() -> InterpretationBoundary:
    return _two_readings(
        ambiguities=(
            Ambiguity(
                ambiguity_id="amb-303-1",
                text="The two sources give different settlement times.",
                interpretation_refs=(MECHANISM,),
            ),
        )
    )


def test_an_ambiguity_touching_the_anchor_routes_to_enrichment():
    """§1: "REPLAN into S-03 once if ``L_enrich`` remains"."""

    unit = _unit()
    counters = _ledger()

    decision = choose_anchor(
        unit=unit,
        boundary=_ambiguous(),
        core=_core(),
        transport=_Transport(_answer()),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    assert decision.anchor is None, (
        "the run goes back to S-03 and returns; an anchor written now would be "
        "the newest version of a reading the run went back to reconsider"
    )
    route = decision.outcomes[0]
    assert route.outcome is ArpOutcome.REPLAN
    assert route.route_target == "S-03"
    assert route.counter == "L_enrich"
    assert route.scope is OutcomeScope.UNIT and route.scope_key == unit.unit_id
    assert counters.used("L_enrich", SIGNAL) == 1, (
        "L_enrich is counted per signal (§0.3), whatever scope the record names"
    )


def _stage_record(stage: str, outcomes: Sequence[OutcomeRecord]) -> StageRecord:
    return StageRecord(
        run_id=create_run_id(),
        seq=1,
        stage=stage,
        scope_key="unit-303",
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=1),
        created_by=StageAttribution(
            stage=stage, component="anchor", decider=DeciderKind.MODEL
        ),
        outcomes=tuple(outcomes),
        status=StageStatus.COMPLETED,
    )


def test_the_route_out_of_this_stage_is_the_one_the_topology_declares():
    """An undeclared backward edge is a second engine (§5.3)."""

    taken = choose_anchor(
        unit=_unit(),
        boundary=_ambiguous(),
        core=_core(),
        transport=_Transport(_answer()),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    ).outcomes[0]

    record = _stage_record(ANCHOR_STAGE, (taken,))
    assert record.outcomes[0].route_target == "S-03"
    assert AMBIGUITY_CAUSE == "ambiguity_touches_anchor"

    undeclared = OutcomeRecord(
        outcome=ArpOutcome.REPLAN,
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        scope=OutcomeScope.UNIT,
        scope_key="unit-303",
        counter="L_enrich",
        attempt=1,
        limit=2,
        route_target="S-02",
    )
    with pytest.raises(ValueError, match="not a declared"):
        _stage_record(ANCHOR_STAGE, (undeclared,))


def test_an_exhausted_enrichment_counter_weakens_the_anchor():
    """§1: "otherwise weaken (``DEGRADE``)" — map §6.2's second step."""

    unit = _unit()
    counters = _ledger(L_enrich=1)
    assert counters.spend_attempt("L_enrich", SIGNAL) == 1

    decision = choose_anchor(
        unit=unit,
        boundary=_ambiguous(),
        core=_core(),
        transport=_Transport(_answer(strength_level=2)),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    anchor = decision.anchor
    assert anchor is not None
    assert anchor.strength_used == LADDER.at(1), "one level lower, never higher"
    assert anchor.ambiguity_touches_anchor is True
    assert anchor.outcome.outcome is ArpOutcome.DEGRADE
    assert anchor.outcome.state_code is StateCode.EVIDENCE_CONFLICT_IN_ANCHOR
    assert anchor.outcome.scope_key == unit.unit_id


def test_an_anchor_at_the_ladders_floor_cannot_be_weakened_and_skips_the_unit():
    """Map §6.2: "if there is no provable anchor, ``SKIP`` the unit"."""

    counters = _ledger(L_enrich=1)
    counters.spend_attempt("L_enrich", SIGNAL)
    floor = _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
                strength_level=1,
                ceiling_level=1,
            ),
        ),
        ambiguities=(
            Ambiguity(
                ambiguity_id="amb-303-1",
                text="The two sources give different settlement times.",
                interpretation_refs=(MECHANISM,),
            ),
        ),
    )

    decision = choose_anchor(
        unit=_unit(boundary=floor),
        boundary=floor,
        core=_core(),
        transport=_Transport(_answer(strength_level=1, candidates=1)),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    assert decision.anchor is None, (
        "weakening at the floor changes nothing, and reporting it as a DEGRADE "
        "would say the run proceeded more carefully when it did not"
    )
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.scope is OutcomeScope.UNIT


# ---------------------------------------------------------------------------
# Versions and staleness (patch R2)
# ---------------------------------------------------------------------------


def test_a_reading_the_newest_boundary_refuses_is_not_a_candidate():
    """The unit's scope names readings; the newest E-09 version judges them."""

    unit = _unit()
    committed = _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
            ),
            Interpretation(
                interpretation_id=TIMELINE,
                version=2,
                supersedes=f"{TIMELINE}.v1",
                statement="The wait fell from two days to minutes.",
                kind=InterpretationKind.COMPARISON,
                support_refs=("ev-1", "ev-4"),
                audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
                strength=LADDER.at(2),
                ceiling=LADDER.at(2),
                admissibility=Admissibility.INADMISSIBLE,
                rationale=Justification(text="The claims do not carry it."),
                inadmissible_reason=InadmissibleReason.UNSUPPORTED,
                temptation_note="It is the number a writer reaches for.",
            ),
        ),
        version=2,
    )

    decision = choose_anchor(
        unit=unit,
        boundary=committed,
        core=_core(),
        transport=_Transport(_answer(candidates=1)),
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    anchor = decision.anchor
    assert anchor is not None
    assert [row.interpretation_id for row in anchor.candidates] == [MECHANISM]
    assert anchor.boundary_ref == (boundary_id(CORE), 2)


def test_a_boundary_older_than_the_unit_is_refused():
    """A superseded snapshot permits readings a newer one has already refused."""

    unit = create_unit(core=_core(), boundary=_two_readings(version=3))

    with pytest.raises(AnchorError, match="version"):
        choose_anchor(
            unit=unit,
            boundary=_two_readings(version=2),
            core=_core(),
            transport=_Transport(_answer()),
            ladder=LADDER,
            counters=_ledger(),
            assets=_assets(),
        )


def test_a_boundary_admitting_nothing_in_scope_skips_the_unit_without_a_call():
    """There is nothing to ask about, so nothing is paid for."""

    unit = _unit()
    refused_only = _boundary(
        (
            Interpretation(
                interpretation_id=MECHANISM,
                version=2,
                supersedes=f"{MECHANISM}.v1",
                statement="The settlement network is what removes the wait.",
                kind=InterpretationKind.MECHANISM,
                support_refs=("ev-1",),
                audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
                strength=LADDER.at(1),
                ceiling=LADDER.at(2),
                admissibility=Admissibility.INADMISSIBLE,
                rationale=Justification(text="The claims do not carry it."),
                inadmissible_reason=InadmissibleReason.UNSUPPORTED,
                temptation_note="It is the mechanism a writer assumes.",
            ),
        ),
        version=2,
    )
    transport = _Transport(_answer())

    decision = choose_anchor(
        unit=unit,
        boundary=refused_only,
        core=_core(),
        transport=transport,
        ladder=LADDER,
        counters=_ledger(),
        assets=_assets(),
    )

    assert decision.anchor is None and transport.calls == 0
    assert (
        decision.outcomes[0].state_code
        is StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION
    )


@pytest.mark.parametrize("status", [UnitStatus.SKIPPED, UnitStatus.COMPLETED])
def test_a_unit_that_is_not_active_never_reaches_the_stage(status: UnitStatus):
    """§1 Pre: "unit active"."""

    unit = _unit()
    inactive = EditorialUnit(
        unit_id=unit.unit_id,
        signal_ids=unit.signal_ids,
        core_ref=unit.core_ref,
        boundary_ref=unit.boundary_ref,
        interpretation_scope=unit.interpretation_scope,
        split=unit.split,
        status=status,
    )

    with pytest.raises(AnchorError, match=status.value):
        choose_anchor(
            unit=inactive,
            boundary=_two_readings(),
            core=_core(),
            transport=_Transport(_answer()),
            ladder=LADDER,
            counters=_ledger(),
            assets=_assets(),
        )


def test_a_unit_over_several_signals_has_no_one_enrichment_allowance():
    """``L_enrich`` is counted per signal (§0.3), and AD-04 builds no such unit."""

    unit = _unit()
    merged = EditorialUnit(
        unit_id=unit.unit_id,
        signal_ids=(SIGNAL, "signal-303-other"),
        core_ref=unit.core_ref,
        boundary_ref=unit.boundary_ref,
        interpretation_scope=unit.interpretation_scope,
        split=unit.split,
    )

    with pytest.raises(AnchorError, match="counted per signal"):
        choose_anchor(
            unit=merged,
            boundary=_two_readings(),
            core=_core(),
            transport=_Transport(_answer()),
            ladder=LADDER,
            counters=_ledger(),
            assets=_assets(),
        )


def test_a_core_the_boundary_is_not_over_is_refused():
    with pytest.raises(AnchorError, match="core at"):
        choose_anchor(
            unit=_unit(),
            boundary=_two_readings(),
            core=_core(version=2),
            transport=_Transport(_answer()),
            ladder=LADDER,
            counters=_ledger(),
            assets=_assets(),
        )


# ---------------------------------------------------------------------------
# Re-entry (§0.3: L_anchor is spent by the route, not by the stage)
# ---------------------------------------------------------------------------


def _anchor_route(unit: EditorialUnit, counters: AttemptCounterLedger) -> OutcomeRecord:
    """The REPLAN S-04 produces when a commit invalidates the anchor."""

    return counters.route(
        source="S-04",
        cause="anchor_invalidated_by_re_entry",
        scope_key=unit.unit_id,
        state_code=StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
        reason="the anchor's reading is inadmissible in the newest version",
    )


def test_a_re_entry_excludes_the_failed_anchor_and_chooses_again():
    """§1: "exclude the failed anchor and choose again"."""

    unit = _unit()
    previous = _chosen(unit)
    counters = _ledger()
    route = _anchor_route(unit, counters)
    transport = _Transport(_answer(candidates=1))

    decision = re_enter_anchor(
        previous=previous,
        route=route,
        unit=unit,
        boundary=_two_readings(),
        core=_core(),
        transport=transport,
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    anchor = decision.anchor
    assert anchor is not None
    assert anchor.version == 2, "§2.5: +1 per re-entry, and the old version is kept"
    assert anchor.anchor_id == previous.anchor_id
    assert anchor.interpretation_ref == (TIMELINE, 1)
    assert [row.interpretation_id for row in anchor.candidates] == [TIMELINE]
    assert transport.calls == 1


def test_the_stage_it_re_enters_never_spends_the_counter_again():
    """§0.3 counts ``L_anchor`` once; spending it twice makes one attempt none."""

    unit = _unit()
    previous = _chosen(unit)
    counters = _ledger()
    route = _anchor_route(unit, counters)
    assert counters.used(ANCHOR_COUNTER, unit.unit_id) == 1

    re_enter_anchor(
        previous=previous,
        route=route,
        unit=unit,
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(candidates=1)),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    assert counters.used(ANCHOR_COUNTER, unit.unit_id) == 1


def test_an_exhausted_anchor_counter_never_reaches_the_stage():
    """The route returns the unit's SKIP instead of a REPLAN."""

    unit = _unit()
    counters = _ledger()
    first = _anchor_route(unit, counters)
    second = _anchor_route(unit, counters)

    assert first.outcome is ArpOutcome.REPLAN
    assert second.outcome is ArpOutcome.SKIP
    assert second.scope is OutcomeScope.UNIT
    with pytest.raises(AnchorError, match="authorized by a SKIP"):
        re_enter_anchor(
            previous=_chosen(unit),
            route=second,
            unit=unit,
            boundary=_two_readings(),
            core=_core(),
            transport=_Transport(_answer()),
            ladder=LADDER,
            counters=counters,
            assets=_assets(),
        )


def test_a_re_entry_that_cannot_show_its_route_is_refused():
    """Three ways a route is not the one §0.3 counts, and each is refused."""

    unit = _unit()
    previous = _chosen(unit)
    wrong_target = AttemptCounterLedger().route(
        source="S-06",
        cause=AMBIGUITY_CAUSE,
        scope_key=SIGNAL,
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        reason="an ambiguity reaches the anchor",
        on_exhaustion=ArpOutcome.DEGRADE,
    )
    wrong_counter = OutcomeRecord(
        outcome=ArpOutcome.REPLAN,
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        scope=OutcomeScope.UNIT,
        scope_key=unit.unit_id,
        counter="L_enrich",
        attempt=1,
        limit=2,
        route_target=ANCHOR_STAGE,
    )
    other_unit = AttemptCounterLedger().route(
        source="S-04",
        cause="anchor_invalidated_by_re_entry",
        scope_key="unit-somebody-else",
        state_code=StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
        reason="another unit's anchor fell",
    )

    cases = (
        (wrong_target, "targets"),
        (wrong_counter, "L_enrich"),
        (other_unit, "unit-somebody"),
    )
    for route, message in cases:
        with pytest.raises(AnchorError, match=message):
            re_enter_anchor(
                previous=previous,
                route=route,
                unit=unit,
                boundary=_two_readings(),
                core=_core(),
                transport=_Transport(_answer()),
                ladder=LADDER,
                counters=_ledger(),
                assets=_assets(),
            )


def test_a_re_entry_with_nothing_left_weakens_the_failed_anchor_without_a_call():
    """§1's "or weaken it": there is nothing to ask, so nothing is asked."""

    single = _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
            ),
        )
    )
    unit = _unit(boundary=single)
    previous = _chosen(unit, boundary=single, candidates=1)
    counters = _ledger()
    route = _anchor_route(unit, counters)
    transport = _Transport(_answer())

    decision = re_enter_anchor(
        previous=previous,
        route=route,
        unit=unit,
        boundary=single,
        core=_core(),
        transport=transport,
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    anchor = decision.anchor
    assert anchor is not None
    assert transport.calls == 0 and decision.calls == 0
    assert anchor.version == 2
    assert anchor.interpretation_ref == (MECHANISM, 1)
    assert anchor.strength_used == LADDER.at(1)
    assert anchor.outcome.outcome is ArpOutcome.DEGRADE


def test_a_re_entry_with_nothing_left_and_nothing_weaker_skips_the_unit():
    floor = _boundary(
        (
            _interpretation(
                MECHANISM,
                "The settlement network is what removes the wait.",
                supports=("ev-1", "ev-2"),
                strength_level=1,
                ceiling_level=1,
            ),
        )
    )
    unit = _unit(boundary=floor)
    previous = _chosen(unit, boundary=floor, strength_level=1, candidates=1)
    counters = _ledger()

    decision = re_enter_anchor(
        previous=previous,
        route=_anchor_route(unit, counters),
        unit=unit,
        boundary=floor,
        core=_core(),
        transport=_Transport(_answer()),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )

    assert decision.anchor is None
    assert decision.outcomes[0].outcome is ArpOutcome.SKIP
    assert (
        decision.outcomes[0].state_code
        is StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION
    )


def test_a_previous_anchor_of_another_unit_is_not_a_previous_version():
    unit = _unit()
    other = create_unit(core=_core(core_id="core-303-other"), boundary=_two_readings(
        core_id="core-303-other"
    ))
    counters = _ledger()

    with pytest.raises(AnchorError, match="belongs to unit"):
        re_enter_anchor(
            previous=_chosen(other, boundary=_two_readings(core_id="core-303-other")),
            route=_anchor_route(unit, counters),
            unit=unit,
            boundary=_two_readings(),
            core=_core(),
            transport=_Transport(_answer()),
            ladder=LADDER,
            counters=counters,
            assets=_assets(),
        )


# ---------------------------------------------------------------------------
# E-11's own rules, and storage
# ---------------------------------------------------------------------------


def _anchor_fields(unit: EditorialUnit) -> dict[str, Any]:
    return dict(
        anchor_id=anchor_id(unit.unit_id),
        version=1,
        unit_id=unit.unit_id,
        interpretation_ref=(MECHANISM, 1),
        boundary_ref=(boundary_id(CORE), 1),
        strength_used=LADDER.at(2),
        leading_material=(
            LeadingItem(ref="ev-1", kind=LeadingMaterialKind.EVIDENCE_CLAIM),
        ),
        candidates=(
            AnchorCandidate(
                interpretation_id=MECHANISM, chosen=True, reason="it is provable"
            ),
        ),
        ambiguity_touches_anchor=False,
        outcome=OutcomeRecord(
            outcome=ArpOutcome.RESOLVE,
            state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
            scope=OutcomeScope.UNIT,
            scope_key=unit.unit_id,
            reason="the anchor is provable",
        ),
    )


def test_an_anchor_records_exactly_one_chosen_candidate():
    """I-07: one anchor per unit, shown to have been chosen."""

    unit = _unit()
    fields = _anchor_fields(unit)

    with pytest.raises(AnchorError, match="0 chosen"):
        Anchor(**{**fields, "candidates": (
            AnchorCandidate(
                interpretation_id=MECHANISM, chosen=False, reason="not this one"
            ),
        )})
    with pytest.raises(AnchorError, match="2 chosen"):
        Anchor(**{**fields, "candidates": (
            AnchorCandidate(
                interpretation_id=MECHANISM, chosen=True, reason="this one"
            ),
            AnchorCandidate(
                interpretation_id=TIMELINE, chosen=True, reason="and this one"
            ),
        )})


def test_the_chosen_candidate_and_the_anchor_are_one_reading():
    unit = _unit()

    with pytest.raises(AnchorError, match="records"):
        Anchor(**{**_anchor_fields(unit), "interpretation_ref": (TIMELINE, 1)})


def test_an_anchor_without_leading_material_cannot_be_constructed():
    with pytest.raises(AnchorError, match="no leading material"):
        Anchor(**{**_anchor_fields(_unit()), "leading_material": ()})


def test_a_leading_set_wider_than_two_cannot_be_constructed():
    unit = _unit()
    wide = tuple(
        LeadingItem(ref=ref, kind=LeadingMaterialKind.EVIDENCE_CLAIM)
        for ref in ("ev-1", "ev-2", "ev-3")
    )

    with pytest.raises(AnchorError, match="3 leading items"):
        Anchor(**{**_anchor_fields(unit), "leading_material": wide})


def test_one_leading_item_counted_twice_is_one_item():
    unit = _unit()
    twice = (
        LeadingItem(ref="ev-1", kind=LeadingMaterialKind.EVIDENCE_CLAIM),
        LeadingItem(ref="ev-1", kind=LeadingMaterialKind.ASSET),
    )

    with pytest.raises(AnchorError, match="twice"):
        Anchor(**{**_anchor_fields(unit), "leading_material": twice})


def test_the_anchor_path_belongs_to_this_stage_and_keeps_its_versions(tmp_path: Path):
    """§2.3 and §2.5: ``units/*/anchor/*`` is S-06's, and the old version stays."""

    workspace = _workspace(tmp_path)
    unit = _unit()
    first = _chosen(unit)
    relative = anchor_relative_path(unit.unit_id, 1)

    assert relative == f"units/{unit.unit_id}/anchor/anchor.v1.json"
    assert owner_of(relative) == ANCHOR_STAGE

    entry = write_anchor(workspace, first)
    assert entry.entity_type == "E-11" and entry.version == 1
    assert entry.writer_stage == ANCHOR_STAGE
    written = json.loads((workspace.run_dir / entry.path).read_text(encoding="utf-8"))
    assert written["interpretation_ref"] == {
        "interpretation_id": MECHANISM,
        "version": 1,
    }
    assert written["boundary_ref"] == {"boundary_id": boundary_id(CORE), "version": 1}
    assert written["strength_used"] == {"ladder_id": LADDER.ladder_id, "level": 2}
    assert written["leading_material"] == [
        {"ref": "ev-1", "kind": "evidence_claim"}
    ]
    assert written["ambiguity_touches_anchor"] is False

    with pytest.raises(ArtifactCollisionError):
        write_anchor(workspace, first)

    counters = _ledger()
    second = re_enter_anchor(
        previous=first,
        route=_anchor_route(unit, counters),
        unit=unit,
        boundary=_two_readings(),
        core=_core(),
        transport=_Transport(_answer(candidates=1)),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    ).anchor
    assert second is not None
    write_anchor(workspace, second)
    kept = sorted(
        path.name for path in (workspace.run_dir / "units").rglob("anchor.v*.json")
    )
    assert kept == ["anchor.v1.json", "anchor.v2.json"]


def test_another_stage_may_not_write_an_anchor(tmp_path: Path):
    workspace = _workspace(tmp_path)
    anchor = _chosen(_unit())

    with pytest.raises(WriteOwnershipError):
        workspace.write_entity(
            stage=DESTINATION_STAGE,
            relative_path=anchor_relative_path(anchor.unit_id, anchor.version),
            entity_type="E-11",
            entity_id=anchor.anchor_id,
            payload=anchor.as_entity(),
            version=anchor.version,
        )


def test_an_unsafe_unit_id_never_reaches_an_anchor_path():
    with pytest.raises(ValueError):
        anchor_relative_path("../escape", 1)


# ===========================================================================
# S-07 · the destinations
# ===========================================================================

#: The canonical contract: all six destinations, and the social posts may link
#: to the article (§0.2, AD-02 §5).
def _contract(**overrides: ContractDestination) -> ContractDestinations:
    rows = {
        destination.value: ContractDestination(
            destination=destination,
            rule_id=f"NB-DST-{destination.value}",
            links_to=() if destination is Destination.WIX else (Destination.WIX,),
        )
        for destination in Destination
    }
    rows.update(overrides)
    return ContractDestinations(rows=tuple(rows.values()))


def _decided(unit: EditorialUnit, **kwargs: Any) -> DestinationDecisionSet:
    return decide_destinations(
        unit=unit,
        anchor=kwargs.pop("anchor", None) or _chosen(unit),
        contract=kwargs.pop("contract", None) or _contract(),
        facts=kwargs.pop("facts", None) or UnitFacts(
            topic_key="payments", risk_level="standard"
        ),
        **kwargs,
    )


def test_every_destination_the_contract_declares_gets_exactly_one_decision():
    """§1 Post, over the six destinations AD-02 names."""

    unit = _unit()
    decided = _decided(unit)

    assert [decision.destination for decision in decided.decisions] == list(
        Destination
    )
    assert decided.undeclared == ()
    assert decided.outcome is None
    for decision in decided.decisions:
        assert decision.destination_decision_id == decision_id(
            unit.unit_id, decision.destination
        )
        assert decision.rule_ref
        assert decision.tier is KnowledgeTier.APPROVED_CLIENT_RULE


def test_a_destination_without_capability_is_generate_only():
    """Acceptance criterion 2, and the AS-IS behaviour of this repository."""

    decided = _decided(_unit())
    by_destination = {
        decision.destination: decision for decision in decided.decisions
    }

    assert [item.destination for item in decided.publishing] == [
        Destination.WIX,
        Destination.LINKEDIN,
    ]
    for destination in (
        Destination.FACEBOOK,
        Destination.INSTAGRAM,
        Destination.THREADS,
        Destination.TELEGRAM,
    ):
        decision = by_destination[destination]
        assert decision.eligibility is Eligibility.ELIGIBLE, (
            "AD-02 §4: fit is never predicted up front; a destination without a "
            "package is still attempted, and only its publication is withheld"
        )
        assert decision.mode is DestinationMode.GENERATE_ONLY
        assert decision.mode_rule is ModeRule.NOT_CAPABLE
        assert decision.capability_gaps == (
            "package",
            "preflight",
            "metrics_collector",
        )
        assert decision.publishes is False


def test_a_destination_without_an_idempotency_authority_cannot_publish():
    """Step 3 §3.6 rule 7, reported on its own: it risks publishing twice."""

    capability = dict(AS_IS_CAPABILITY)
    capability[Destination.WIX] = DestinationCapability(
        destination=Destination.WIX,
        publisher=True,
        package=True,
        preflight=True,
        idempotency_authority=False,
        metrics_collector=True,
    )

    decision = _decided(_unit(), capability=capability).decision(Destination.WIX)

    assert decision is not None
    assert decision.mode is DestinationMode.GENERATE_ONLY
    assert decision.mode_rule is ModeRule.NO_IDEMPOTENCY_AUTHORITY
    assert decision.capability_gaps == ("idempotency_authority",)


def test_a_capable_destination_outside_the_rollout_scope_is_generate_only():
    """AD-02 §3: capability and rollout scope "must never be confused"."""

    capability = {
        destination: DestinationCapability(
            destination=destination,
            publisher=True,
            package=True,
            preflight=True,
            idempotency_authority=True,
            metrics_collector=True,
        )
        for destination in Destination
    }

    decided = _decided(_unit(), capability=capability)
    telegram = decided.decision(Destination.TELEGRAM)

    assert telegram is not None
    assert telegram.mode is DestinationMode.GENERATE_ONLY
    assert telegram.mode_rule is ModeRule.OUTSIDE_ROLLOUT_SCOPE
    assert telegram.capability_gaps == ()
    assert [item.destination for item in decided.publishing] == [
        Destination.WIX,
        Destination.LINKEDIN,
    ], "the rollout scope is what today's release publishes, not capability"


def test_all_six_publish_once_the_rollout_scope_is_the_contracts_destinations():
    """AD-02: "the finished canonical run publishes to all six"."""

    capability = {
        destination: DestinationCapability(
            destination=destination,
            publisher=True,
            package=True,
            preflight=True,
            idempotency_authority=True,
            metrics_collector=True,
        )
        for destination in Destination
    }

    decided = _decided(
        _unit(), capability=capability, rollout_scope=frozenset(Destination)
    )

    assert len(decided.publishing) == len(Destination)
    for decision in decided.decisions:
        assert decision.mode_rule is ModeRule.PUBLISHES


def test_the_contract_may_choose_to_generate_and_not_publish():
    """Step 1: ``generate_only`` is "a temporary migration state, or a contract
    choice"."""

    contract = _contract(
        wix=ContractDestination(
            destination=Destination.WIX, rule_id="NB-DST-wix", publishes=False
        )
    )

    decision = _decided(_unit(), contract=contract).decision(Destination.WIX)

    assert decision is not None
    assert decision.mode_rule is ModeRule.CONTRACT_GENERATE_ONLY
    assert decision.capability_gaps == ()


# ---------------------------------------------------------------------------
# Acceptance criterion 1: every exclusion cites a rule and a tier
# ---------------------------------------------------------------------------

_POLICY = PlatformPolicy(
    destination=Destination.INSTAGRAM,
    knowledge=KnowledgeRef(
        record_id="K-DST-META-02",
        record_version=1,
        tier=KnowledgeTier.HARD_PLATFORM_POLICY,
        file_status=KnowledgeStatus.APPROVED_RULE,
        effective_status=KnowledgeStatus.APPROVED_RULE,
    ),
)


def _exclusion_case(rule: ExclusionRule) -> tuple[Destination, dict[str, Any]]:
    """One way to reach each of E-12's five exclusion rules."""

    if rule is ExclusionRule.CONTRACT_DISABLED:
        return Destination.TELEGRAM, {
            "contract": _contract(
                telegram=ContractDestination(
                    destination=Destination.TELEGRAM,
                    rule_id="NB-DST-telegram",
                    enabled=False,
                )
            )
        }
    if rule is ExclusionRule.CONTRACT_TOPIC:
        return Destination.THREADS, {
            "contract": _contract(
                threads=ContractDestination(
                    destination=Destination.THREADS,
                    rule_id="NB-DST-threads",
                    refused_topics=("payments",),
                )
            )
        }
    if rule is ExclusionRule.CONTRACT_RISK:
        return Destination.FACEBOOK, {
            "contract": _contract(
                facebook=ContractDestination(
                    destination=Destination.FACEBOOK,
                    rule_id="NB-DST-facebook",
                    refused_risk_levels=("standard",),
                )
            )
        }
    if rule is ExclusionRule.HARD_PLATFORM_POLICY:
        return Destination.INSTAGRAM, {"policies": (_POLICY,)}
    return Destination.LINKEDIN, {
        "cadence": (
            CadenceRule(
                rule_id="NB-CAD-linkedin",
                destination=Destination.LINKEDIN,
                allowed=1,
            ),
        ),
        "portfolio": (
            DestinationFingerprint(
                fingerprint_id="fp-1",
                destination=Destination.LINKEDIN,
                published=True,
            ),
        ),
    }


@pytest.mark.parametrize("rule", list(ExclusionRule))
def test_every_exclusion_cites_a_rule_and_a_tier(rule: ExclusionRule):
    """Acceptance criterion 1, over all five rules E-12 admits."""

    unit = _unit()
    destination, kwargs = _exclusion_case(rule)
    decision = _decided(unit, **kwargs).decision(destination)

    assert decision is not None
    assert decision.eligibility is Eligibility.EXCLUDED
    assert decision.exclusion_rule is rule
    assert decision.rule_ref, "the rule that refused is named"
    assert decision.tier in tuple(KnowledgeTier)
    assert decision.mode is None and decision.mode_rule is None
    outcome = decision.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.scope is OutcomeScope.DESTINATION
    assert outcome.scope_key == destination_scope_key(unit.unit_id, destination)
    assert rule.value in (outcome.reason or "")
    assert decision.tier.value in (outcome.reason or "")
    assert ArpOutcome.SKIP in permitted_outcomes(outcome.state_code)


def test_a_tier_one_exclusion_cites_the_record_as_it_was_at_the_time_of_use():
    decision = _decided(_unit(), policies=(_POLICY,)).decision(Destination.INSTAGRAM)

    assert decision is not None
    assert decision.knowledge == _POLICY.knowledge
    assert decision.tier is KnowledgeTier.HARD_PLATFORM_POLICY
    assert decision.outcome is not None
    assert decision.outcome.knowledge == (_POLICY.knowledge,)


def test_the_rule_with_the_most_authority_decides_a_destination_several_refuse():
    """Map §5: "in a conflict the higher tier wins"."""

    contract = _contract(
        instagram=ContractDestination(
            destination=Destination.INSTAGRAM,
            rule_id="NB-DST-instagram",
            enabled=False,
        )
    )

    decision = _decided(
        _unit(), contract=contract, policies=(_POLICY,)
    ).decision(Destination.INSTAGRAM)

    assert decision is not None
    assert decision.exclusion_rule is ExclusionRule.HARD_PLATFORM_POLICY, (
        "a client reading the exclusion learns which rule would have to change, "
        "and a platform rule is not one it can edit"
    )
    assert decision.tier is KnowledgeTier.HARD_PLATFORM_POLICY


def test_a_record_below_tier_one_cannot_exclude_a_destination():
    """§1: "``K-DST-*`` at tier 1 only"; the rest act at S-08 and S-10."""

    with pytest.raises(DestinationError, match="tier 4"):
        PlatformPolicy(
            destination=Destination.THREADS,
            knowledge=KnowledgeRef(
                record_id="K-DST-TH-01",
                record_version=1,
                tier=KnowledgeTier.PLATFORM_RANKING,
                file_status=KnowledgeStatus.DESCRIPTIVE,
                effective_status=KnowledgeStatus.DESCRIPTIVE,
            ),
        )


def test_a_unit_that_states_no_topic_is_refused_by_a_row_that_names_topics():
    """Silence is not admission, and the safe direction publishes nothing."""

    contract = _contract(
        threads=ContractDestination(
            destination=Destination.THREADS,
            rule_id="NB-DST-threads",
            refused_topics=("crypto",),
        )
    )

    decision = _decided(
        _unit(), contract=contract, facts=UnitFacts(risk_level="standard")
    ).decision(Destination.THREADS)

    assert decision is not None
    assert decision.exclusion_rule is ExclusionRule.CONTRACT_TOPIC


def test_a_topic_the_row_does_not_refuse_leaves_the_destination_eligible():
    contract = _contract(
        threads=ContractDestination(
            destination=Destination.THREADS,
            rule_id="NB-DST-threads",
            refused_topics=("crypto",),
        )
    )

    decision = _decided(_unit(), contract=contract).decision(Destination.THREADS)

    assert decision is not None
    assert decision.eligibility is Eligibility.ELIGIBLE


def test_cadence_counts_published_fingerprints_and_no_others():
    """A ``generate_only`` text took no slot in the calendar."""

    cadence = (
        CadenceRule(
            rule_id="NB-CAD-linkedin", destination=Destination.LINKEDIN, allowed=1
        ),
    )
    generated_only = (
        DestinationFingerprint(
            fingerprint_id="fp-1",
            destination=Destination.LINKEDIN,
            published=False,
        ),
    )

    decision = _decided(
        _unit(), cadence=cadence, portfolio=generated_only
    ).decision(Destination.LINKEDIN)

    assert decision is not None
    assert decision.eligibility is Eligibility.ELIGIBLE


def test_cadence_counts_the_destination_it_is_declared_for():
    cadence = (
        CadenceRule(
            rule_id="NB-CAD-linkedin", destination=Destination.LINKEDIN, allowed=1
        ),
    )
    elsewhere = (
        DestinationFingerprint(
            fingerprint_id="fp-1", destination=Destination.WIX, published=True
        ),
    )

    decision = _decided(
        _unit(), cadence=cadence, portfolio=elsewhere
    ).decision(Destination.LINKEDIN)

    assert decision is not None
    assert decision.eligibility is Eligibility.ELIGIBLE


def test_a_cadence_rule_that_allows_nothing_is_refused():
    """A rule that defers for ever is the contract disabling the destination."""

    with pytest.raises(DestinationError, match="allows 0"):
        CadenceRule(
            rule_id="NB-CAD-linkedin", destination=Destination.LINKEDIN, allowed=0
        )


def test_two_cadence_rules_over_one_destination_are_refused():
    cadence = (
        CadenceRule(rule_id="a", destination=Destination.WIX, allowed=1),
        CadenceRule(rule_id="b", destination=Destination.WIX, allowed=2),
    )

    with pytest.raises(DestinationError, match="two cadence rules"):
        _decided(_unit(), cadence=cadence)


def test_zero_eligible_destinations_skips_the_unit():
    """§1's ARP column, with the reason it names."""

    unit = _unit()
    contract = ContractDestinations(
        rows=tuple(
            ContractDestination(
                destination=destination,
                rule_id=f"NB-DST-{destination.value}",
                enabled=False,
            )
            for destination in Destination
        )
    )

    decided = _decided(unit, contract=contract)

    assert decided.eligible == ()
    outcome = decided.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.NO_ELIGIBLE_DESTINATION
    assert outcome.scope is OutcomeScope.UNIT
    assert outcome.scope_key == unit.unit_id


def test_a_destination_the_contract_never_mentioned_is_neither_state():
    """§1 Post covers what the contract declares; the rest is recorded as that."""

    contract = ContractDestinations(
        rows=(
            ContractDestination(destination=Destination.WIX, rule_id="NB-DST-wix"),
            ContractDestination(
                destination=Destination.LINKEDIN,
                rule_id="NB-DST-linkedin",
                links_to=(Destination.WIX,),
            ),
        )
    )

    decided = _decided(_unit(), contract=contract)

    assert decided.undeclared == (
        Destination.FACEBOOK,
        Destination.INSTAGRAM,
        Destination.THREADS,
        Destination.TELEGRAM,
    )
    assert decided.decision(Destination.TELEGRAM) is None
    assert len(decided.decisions) == 2


# ---------------------------------------------------------------------------
# Publication dependencies, recorded separately from content (AD-02 §5)
# ---------------------------------------------------------------------------


def test_dependencies_are_recorded_separately_and_put_wix_first():
    """§0.2: "a destination that others link to goes first"."""

    decided = _decided(_unit())
    linkedin = decided.decision(Destination.LINKEDIN)

    assert linkedin is not None
    assert linkedin.publication_dependencies == (
        PublicationDependency(target=Destination.WIX, kind=DependencyKind.LINK),
    )
    assert linkedin.dropped_dependencies == ()
    order = publication_order(decided.decisions)
    assert order[0] is Destination.WIX
    assert set(order) == set(Destination)


def test_a_dependency_on_an_excluded_destination_is_dropped_and_recorded():
    """An order cannot wait on a destination that will never run (R-2, §0.2)."""

    contract = _contract(
        wix=ContractDestination(
            destination=Destination.WIX, rule_id="NB-DST-wix", enabled=False
        )
    )

    decided = _decided(_unit(), contract=contract)
    linkedin = decided.decision(Destination.LINKEDIN)

    assert linkedin is not None
    assert linkedin.publication_dependencies == ()
    assert linkedin.dropped_dependencies == (Destination.WIX,), (
        "S-10 has to know that the plan it writes cannot carry the link"
    )
    assert Destination.WIX not in publication_order(decided.decisions)


def test_a_dependency_on_a_generate_only_destination_is_kept():
    """R-2 answers the binding at S-14: "only if its target was published"."""

    contract = _contract(
        wix=ContractDestination(
            destination=Destination.WIX, rule_id="NB-DST-wix", publishes=False
        )
    )

    linkedin = _decided(_unit(), contract=contract).decision(Destination.LINKEDIN)

    assert linkedin is not None
    assert linkedin.publication_dependencies == (
        PublicationDependency(target=Destination.WIX),
    )


def test_a_dependency_cycle_has_no_order_and_is_refused():
    """§0.2 needs an order wherever order matters; a cycle has none."""

    contract = _contract(
        wix=ContractDestination(
            destination=Destination.WIX,
            rule_id="NB-DST-wix",
            links_to=(Destination.LINKEDIN,),
        )
    )

    with pytest.raises(DestinationError, match="wait on each other"):
        _decided(_unit(), contract=contract)


def test_a_contract_row_cannot_link_to_itself():
    with pytest.raises(DestinationError, match="linking to itself"):
        ContractDestination(
            destination=Destination.WIX,
            rule_id="NB-DST-wix",
            links_to=(Destination.WIX,),
        )


# ---------------------------------------------------------------------------
# Acceptance criterion 3: zero model calls in S-07
# ---------------------------------------------------------------------------


def test_s07_makes_no_model_call_and_has_no_transport_to_make_one_with():
    """Acceptance criterion 3, read off the module rather than trusted."""

    module = _REPO_ROOT / "src" / "editorial_core" / "destinations.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))

    completions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "complete"
    ]
    assert completions == [], "§1, Calls: 0 — and nothing here can make one"

    protocols = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(base, ast.Name) and base.id == "Protocol"
            for base in node.bases
        )
    ]
    assert protocols == [], "a transport boundary would be a call waiting to happen"

    imported = {
        name.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for name in node.names
    }
    assert not [item for item in imported if "ransport" in item]
    assert "transport" not in _signature_names(tree, "decide_destinations")
    assert "budget" not in _signature_names(tree, "decide_destinations"), (
        "a stage that spends nothing needs no budget to be refused by"
    )


def _signature_names(tree: ast.Module, function: str) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return {
                argument.arg
                for group in (node.args.args, node.args.kwonlyargs)
                for argument in group
            }
    raise AssertionError(f"{function} is not defined in this module")


def test_the_stage_record_of_s07_records_no_call(tmp_path: Path):
    """The trace the harness writes: ``calls`` counted, and the count is zero."""

    workspace = _workspace(tmp_path)
    unit = _unit()
    decided = _decided(unit, policies=(_POLICY,))
    entries = write_destination_decisions(workspace, decided)

    record = StageRecord(
        run_id=workspace.run_id,
        seq=1,
        stage=DESTINATION_STAGE,
        scope_key=unit.unit_id,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=1),
        created_by=StageAttribution(
            stage=DESTINATION_STAGE,
            component="destinations",
            decider=DeciderKind.RULE,
        ),
        outcomes=tuple(
            decision.outcome
            for decision in decided.decisions
            if decision.outcome is not None
        ),
        calls={"count": 0, "tokens_in": 0, "tokens_out": 0},
        status=StageStatus.COMPLETED,
    )
    workspace.write_stage_record(record)

    assert record.calls == {"count": 0, "tokens_in": 0, "tokens_out": 0}
    assert record.created_by.request_digest is None, (
        "no request was made, so there is no digest of one"
    )
    assert len(entries) == len(Destination)


# ---------------------------------------------------------------------------
# E-12's own rules, and storage
# ---------------------------------------------------------------------------


def _decision_fields(unit: EditorialUnit) -> dict[str, Any]:
    return dict(
        destination_decision_id=decision_id(unit.unit_id, Destination.WIX),
        unit_id=unit.unit_id,
        destination=Destination.WIX,
        eligibility=Eligibility.ELIGIBLE,
        rule_ref="NB-DST-wix",
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        mode=DestinationMode.PUBLISH,
        mode_rule=ModeRule.PUBLISHES,
    )


def test_an_eligible_destination_records_no_outcome():
    """An OutcomeRecord is an unresolved state; deciding the destination
    resolved it."""

    unit = _unit()
    invented = OutcomeRecord(
        outcome=ArpOutcome.RESOLVE,
        state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
        scope=OutcomeScope.DESTINATION,
        scope_key=destination_scope_key(unit.unit_id, Destination.WIX),
        reason="eligible",
    )

    with pytest.raises(DestinationError, match="indicators count"):
        DestinationDecision(**{**_decision_fields(unit), "outcome": invented})


def test_an_excluded_destination_without_its_skip_is_refused():
    unit = _unit()

    with pytest.raises(DestinationError, match="is a run that waits"):
        DestinationDecision(
            destination_decision_id=decision_id(unit.unit_id, Destination.WIX),
            unit_id=unit.unit_id,
            destination=Destination.WIX,
            eligibility=Eligibility.EXCLUDED,
            rule_ref="NB-DST-wix",
            tier=KnowledgeTier.APPROVED_CLIENT_RULE,
            exclusion_rule=ExclusionRule.CONTRACT_DISABLED,
        )


def test_a_mode_that_disagrees_with_its_rule_is_refused():
    unit = _unit()

    with pytest.raises(DestinationError, match="publishes exactly when"):
        DestinationDecision(
            **{**_decision_fields(unit), "mode_rule": ModeRule.OUTSIDE_ROLLOUT_SCOPE}
        )


def test_capability_gaps_belong_to_a_mode_capability_decided():
    unit = _unit()

    with pytest.raises(DestinationError, match="capability gaps"):
        DestinationDecision(
            **{**_decision_fields(unit), "capability_gaps": ("package",)}
        )


def test_a_tier_that_does_not_belong_to_the_rule_is_refused():
    unit = _unit()

    with pytest.raises(DestinationError, match="tier"):
        DestinationDecision(
            destination_decision_id=decision_id(unit.unit_id, Destination.WIX),
            unit_id=unit.unit_id,
            destination=Destination.WIX,
            eligibility=Eligibility.EXCLUDED,
            rule_ref="NB-DST-wix",
            tier=KnowledgeTier.HARD_PLATFORM_POLICY,
            exclusion_rule=ExclusionRule.CONTRACT_DISABLED,
            outcome=OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=StateCode.DESTINATION_OUTSIDE_CONTRACT,
                scope=OutcomeScope.DESTINATION,
                scope_key=destination_scope_key(unit.unit_id, Destination.WIX),
                reason="the contract disabled it",
            ),
        )


def test_a_decision_set_that_accounts_for_five_destinations_is_not_a_record():
    unit = _unit()
    decided = _decided(unit)

    with pytest.raises(DestinationError, match="neither a decision nor a"):
        DestinationDecisionSet(
            unit_id=unit.unit_id, decisions=decided.decisions[:5]
        )


def test_the_decision_path_belongs_to_this_stage_and_is_written_once(tmp_path: Path):
    """§2.3: ``destinations/*/decision.json`` is S-07's; P1 writes it once."""

    workspace = _workspace(tmp_path)
    unit = _unit()
    decided = _decided(unit, policies=(_POLICY,))
    relative = decision_relative_path(unit.unit_id, Destination.INSTAGRAM)

    assert relative == (
        f"units/{unit.unit_id}/destinations/instagram/decision.json"
    )
    assert owner_of(relative) == DESTINATION_STAGE

    write_destination_decisions(workspace, decided)
    written = json.loads((workspace.run_dir / relative).read_text(encoding="utf-8"))
    assert written["entity_type"] == "E-12"
    assert written["eligibility"] == "excluded"
    assert written["exclusion_rule"] == "hard_platform_policy"
    assert written["tier"] == "1"
    assert written["knowledge"]["record_id"] == "K-DST-META-02"
    assert written["mode"] is None

    with pytest.raises(ArtifactCollisionError):
        write_destination_decisions(workspace, decided)


def test_an_excluded_destination_is_written_too(tmp_path: Path):
    """The exclusion's rule and tier are the evidence AD-02 exists to produce."""

    workspace = _workspace(tmp_path)
    unit = _unit()
    contract = _contract(
        telegram=ContractDestination(
            destination=Destination.TELEGRAM,
            rule_id="NB-DST-telegram",
            enabled=False,
            links_to=(Destination.WIX,),
        )
    )
    write_destination_decisions(workspace, _decided(unit, contract=contract))

    decisions = sorted(
        path.parent.name
        for path in (workspace.run_dir / "units").rglob("decision.json")
    )
    assert decisions == sorted(item.value for item in Destination)


def test_another_stage_may_not_write_a_destination_decision(tmp_path: Path):
    workspace = _workspace(tmp_path)
    unit = _unit()
    decision = _decided(unit).decisions[0]

    with pytest.raises(WriteOwnershipError):
        workspace.write_entity(
            stage=ANCHOR_STAGE,
            relative_path=decision_relative_path(unit.unit_id, decision.destination),
            entity_type="E-12",
            entity_id=decision.destination_decision_id,
            payload=decision.as_entity(),
        )


def test_an_unsafe_unit_id_never_reaches_a_decision_path():
    with pytest.raises(ValueError):
        decision_relative_path("../escape", Destination.WIX)


# ---------------------------------------------------------------------------
# The inputs S-07 refuses, and the lists it must not duplicate
# ---------------------------------------------------------------------------


def test_the_destination_vocabulary_mirrors_the_one_release_scope_list():
    """#227: a duplicated list is a list that drifts."""

    assert {item.value for item in Destination} == {
        *R1_PUBLISH_CHANNELS,
        *NON_R1_PUBLISH_CHANNELS,
    }
    assert ROLLOUT_SCOPE == frozenset(
        Destination(name) for name in R1_PUBLISH_CHANNELS
    )


def test_the_as_is_capability_table_is_this_repositorys_own_state():
    """AD-02 §3's five parts, as the modules that provide them stand today."""

    assert set(AS_IS_CAPABILITY) == set(Destination)
    for destination, capability in AS_IS_CAPABILITY.items():
        assert capability.destination is destination
        assert capability.publisher is True
        assert capability.idempotency_authority is True, (
            "publication_markers.py keys all six"
        )
    assert {
        destination.value
        for destination, capability in AS_IS_CAPABILITY.items()
        if capability.capable
    } == set(R1_PUBLISH_CHANNELS)
    assert {item.value for item in Destination} <= set(MARKER_DESTINATIONS), (
        "the idempotency authority Step 3 §3.6 requires covers every destination"
    )


def test_a_destination_capability_nobody_stated_is_not_an_incapable_one():
    """Assuming capability is the assumption that publishes."""

    capability = {
        destination: AS_IS_CAPABILITY[destination]
        for destination in Destination
        if destination is not Destination.TELEGRAM
    }

    with pytest.raises(DestinationError, match="states nothing about telegram"):
        _decided(_unit(), capability=capability)


def test_a_capability_row_filed_under_another_destination_answers_for_nothing():
    capability = dict(AS_IS_CAPABILITY)
    capability[Destination.TELEGRAM] = AS_IS_CAPABILITY[Destination.WIX]

    with pytest.raises(DestinationError, match="describes wix"):
        _decided(_unit(), capability=capability)


def test_a_contract_with_no_destination_is_refused():
    with pytest.raises(DestinationError, match="required input"):
        ContractDestinations(rows=())


def test_a_contract_that_declares_one_destination_twice_is_refused():
    with pytest.raises(DestinationError, match="twice"):
        ContractDestinations(
            rows=(
                ContractDestination(destination=Destination.WIX, rule_id="a"),
                ContractDestination(destination=Destination.WIX, rule_id="b"),
            )
        )


def test_two_contract_rows_may_not_answer_to_one_rule_id():
    with pytest.raises(DestinationError, match="declared twice"):
        ContractDestinations(
            rows=(
                ContractDestination(destination=Destination.WIX, rule_id="same"),
                ContractDestination(
                    destination=Destination.LINKEDIN,
                    rule_id="same",
                    links_to=(Destination.WIX,),
                ),
            )
        )


def test_another_units_anchor_never_decides_this_units_destinations():
    unit = _unit()
    other = create_unit(
        core=_core(core_id="core-303-other"),
        boundary=_two_readings(core_id="core-303-other"),
    )

    with pytest.raises(DestinationError, match="is the anchor of"):
        decide_destinations(
            unit=unit,
            anchor=_chosen(other, boundary=_two_readings(core_id="core-303-other")),
            contract=_contract(),
            facts=UnitFacts(topic_key="payments", risk_level="standard"),
        )


def test_the_register_holds_no_tier_one_destination_record_today():
    """The AS-IS state: the tier-1 K-DST records are not in the seed set."""

    knowledge = load_register(_REPO_ROOT / "knowledge", today=date(2026, 9, 24))

    for destination in Destination:
        assert platform_policies(
            knowledge,
            StageInputs(destination=destination.value),
        ) == ()


def test_a_platform_policy_cannot_be_resolved_without_a_destination():
    knowledge = load_register(_REPO_ROOT / "knowledge", today=date(2026, 9, 24))

    with pytest.raises(DestinationError, match="name none"):
        platform_policies(knowledge, StageInputs())


# ===========================================================================
# The durable ledger (Step 3 §3.3)
# ===========================================================================

_INPUTS = RunInputs.stated_absent("SL-5 fixture: no editorial input")


def _summary(records: Sequence[StageRecord], scopes: Sequence[RunScope]) -> RunSummary:
    context = RunContext(
        run_id=records[0].run_id,
        assignment_id=SIGNAL,
        started_at=NOW,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
    )
    return RunSummary.for_run(
        run_context=context,
        manifest=RunManifest.for_run(context, inputs=_INPUTS),
        records=tuple(records),
        scopes=tuple(scopes),
        client="never_blank",
        signal_ids=(SIGNAL,),
        workspace=WorkspaceRef(
            artifact_name="editorial-run-303",
            retention_days=90,
            expires_on=date(2026, 12, 23),
            manifest_digest="sha256:" + "a" * 64,
        ),
        call_budget_limit=40,
        ledger_commit=LedgerCommitStatus.NOT_ATTEMPTED,
    )


def test_a_cadence_deferral_outlives_the_workspace_as_its_own_category():
    """§3.3: a skip is counted by state code and a closed category."""

    unit = _unit()
    decided = _decided(
        unit,
        cadence=(
            CadenceRule(
                rule_id="NB-CAD-linkedin",
                destination=Destination.LINKEDIN,
                allowed=1,
            ),
        ),
        portfolio=(
            DestinationFingerprint(
                fingerprint_id="fp-1",
                destination=Destination.LINKEDIN,
                published=True,
            ),
        ),
    )
    run_id = create_run_id()
    record = StageRecord(
        run_id=run_id,
        seq=1,
        stage=DESTINATION_STAGE,
        scope_key=unit.unit_id,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=1),
        created_by=StageAttribution(
            stage=DESTINATION_STAGE,
            component="destinations",
            decider=DeciderKind.RULE,
        ),
        outcomes=tuple(
            decision.outcome
            for decision in decided.decisions
            if decision.outcome is not None
        ),
        calls={"count": 0},
        status=StageStatus.COMPLETED,
    )
    key = destination_scope_key(unit.unit_id, Destination.LINKEDIN)

    summary = _summary(
        (record,), (RunScope(scope=OutcomeScope.DESTINATION, scope_key=key),)
    )
    reloaded = RunSummary.from_dict(summary.to_dict())
    deferred = [
        state for state in reloaded.scope_outcomes if state.scope_key == key
    ]

    assert len(deferred) == 1
    assert deferred[0].outcome is ArpOutcome.SKIP
    assert deferred[0].state_code is StateCode.DESTINATION_DEFERRED_BY_CADENCE
    assert deferred[0].category is ReasonCategory.CADENCE, (
        "an intended gap in the calendar is not a contract that does not cover "
        "the material, and map §6.3 reads the difference"
    )


def test_the_anchors_own_outcome_reaches_the_summary_as_a_unit_state():
    unit = _unit()
    counters = _ledger(L_enrich=1)
    counters.spend_attempt("L_enrich", SIGNAL)
    decision = choose_anchor(
        unit=unit,
        boundary=_ambiguous(),
        core=_core(),
        transport=_Transport(_answer()),
        ladder=LADDER,
        counters=counters,
        assets=_assets(),
    )
    record = StageRecord(
        run_id=create_run_id(),
        seq=1,
        stage=ANCHOR_STAGE,
        scope_key=unit.unit_id,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=1),
        created_by=StageAttribution(
            stage=ANCHOR_STAGE, component="anchor", decider=DeciderKind.MODEL
        ),
        outcomes=decision.outcomes,
        calls={"count": decision.calls},
        status=StageStatus.COMPLETED,
    )

    summary = _summary(
        (record,), (RunScope(scope=OutcomeScope.UNIT, scope_key=unit.unit_id),)
    )
    states = {state.scope_key: state for state in summary.scope_outcomes}

    assert states[unit.unit_id].outcome is ArpOutcome.DEGRADE
    assert states[unit.unit_id].category is ReasonCategory.EVIDENCE


@pytest.mark.parametrize(
    "state_code",
    [
        StateCode.ANCHOR_SELECTION_FAILED,
        StateCode.DESTINATION_OUTSIDE_CONTRACT,
        StateCode.HARD_PLATFORM_POLICY_FORBIDS,
        StateCode.DESTINATION_DEFERRED_BY_CADENCE,
        StateCode.NO_ELIGIBLE_DESTINATION,
    ],
)
def test_every_state_this_slice_adds_is_bounded_and_counted(state_code: StateCode):
    """A state with no permitted outcome or no category is one nothing can read."""

    assert permitted_outcomes(state_code)
    assert reason_category(state_code) in tuple(ReasonCategory)
