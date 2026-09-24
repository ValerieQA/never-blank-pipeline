"""Issue #301: S-04 decides what the material may mean, and probes for what it may not.

SL-4's acceptance evidence for the Interpretation Boundary, as scenarios taken
from the map's own manual walkthroughs (§13, A–C) and saved in
``tests/fixtures/interpretation_boundary_301/``:

1. **uranium** (walkthrough C) ends in ``SKIP`` with "no admissible
   interpretation", and the reading the real engine produced — "owners were
   buried in inspections" — is kept in the boundary rather than discarded;
2. **Ramp** (walkthrough B) records "the business has more money" as
   inadmissible, found by the benefit-inflation probe family, beside the
   boundary limitation "there is not more money";
3. **the breakfast founder** (walkthrough A) records "you, the reader, bake at
   night" as inadmissible, found by the transfer-to-the-reader family whose own
   ``## Real examples`` section quotes that sentence;
4. a **simulated re-entry** from S-13 produces a coordinated commit — the new
   E-08 version first, the E-09 marker last — and the orphan test passes: an
   E-08 version written without its marker is invisible to every reader.

And the properties the stage rests on: two separate calls and never one (U-1),
code rules that only ever narrow the boundary (ceilings, the transfer rule,
resolvable references, no dual listing), a probe answer that skipped a family
refused rather than read as "nothing found" (patch R1), no client position,
lens or portfolio anywhere in either request, and every refusal on the way into
a re-entry ending in the causing destination's ``SKIP``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from src.editorial.decision_contract import (
    AudienceRelevanceBasisType,
    BusinessAudienceRelevance,
)
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeScope,
    StateCode,
    permitted_outcomes,
)
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
)
from src.editorial_core.interpretation_boundary import (
    CAPPED_LEVEL,
    GENERATE_INSTRUCTIONS,
    PROBE_INSTRUCTIONS,
    TEST_INSTRUCTIONS,
    BoundaryDecision,
    BoundaryError,
    DetectedInterpretation,
    InadmissibleReason,
    Interpretation,
    InterpretationBoundary,
    InterpretationKind,
    Justification,
    ProbeApplication,
    ProbeFinding,
    commit_boundary_version,
    decide_boundary,
    interpretation_id,
    probe_families,
    re_enter_boundary,
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
from src.editorial_core.relevance_screen import (
    AudienceTransfer,
    BoundaryInput,
    DecisionRef,
    RelevanceBasis,
)
from src.knowledge.loader import load_register
from src.knowledge.vocabulary import load_vocabularies
from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
)
from src.run.boundary_commit import (
    Admissibility,
    InterpretationVersion,
    boundary_relative_path,
    current_boundary,
    interpretation_relative_path,
    orphan_interpretation_versions,
    write_interpretation_version,
)
from src.run.call_budget import RunCallBudget
from src.run.call_budget_arp import ArpCallBudget
from src.run.run_context import create_run_id
from src.run.run_summary import ReasonCategory, reason_category
from src.run.run_workspace import RunWorkspace
from src.strategy.audience_profile import (
    ATTRIBUTES_VOCABULARY,
    PROFILE_FILE,
    load_audience_profile,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTER = _REPO_ROOT / "knowledge"
CLIENT = _REPO_ROOT / "clients" / "never_blank"
FIXTURES = Path("tests/fixtures/interpretation_boundary_301")

#: The day the register is read for. Before every `K-TEMPT-*` record's
#: `review_by`, so the seven families arrive at their own status and the trace
#: this suite reads is not a demotion story.
TODAY = date(2026, 9, 24)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

#: The universal default ladder, worded as ``knowledge/ladders/default.md``
#: words it (K-LAD-01), exactly as NB-03b's suite hands it to S-01.
LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

#: Step 2 §4 U-1: the seven initial probe families, from real errors.
PROBE_FAMILY_COUNT = 7

#: An approved position of the Client Contract, as S-02 records one. It exists
#: in this suite only to be looked for in the two requests and not found.
APPROVED_POSITION = "position-nb-automation-stance"


# ===========================================================================
# The three walkthroughs, as cores
# ===========================================================================


@dataclass(frozen=True)
class _Claim:
    """One evidence claim of a walkthrough's core."""

    identity: str
    statement: str
    scope: str
    level: int
    verdict: EvidenceDisposition = EvidenceDisposition.ACCEPTED


@dataclass(frozen=True)
class _Walkthrough:
    """One saved case: its core, and what the relevance screen said about it."""

    case: str
    claims: tuple[_Claim, ...]
    #: The claims #58 recorded as carrying the audience connection. The code
    #: transfer rule is checked against exactly this set.
    audience_refs: tuple[str, ...]
    claim_mode: AudienceTransfer


WALKTHROUGHS: dict[str, _Walkthrough] = {
    # §13 A · "This Dad Lost His Job and Started Making a Breakfast Staple…"
    "breakfast_founder": _Walkthrough(
        case="breakfast_founder",
        claims=(
            _Claim(
                "ev-breakfast-1",
                "The founder's home operation reached $85,000 in sales in its "
                "first year.",
                "One named founder's business, as reported.",
                2,
            ),
            _Claim(
                "ev-breakfast-2",
                "The founder describes filling orders overnight from a home "
                "kitchen.",
                "The founder's own account, as reported.",
                1,
            ),
            _Claim(
                "ev-breakfast-3",
                "The reported order volume exceeded what the home kitchen "
                "could produce in a day.",
                "The named case, as reported.",
                2,
            ),
        ),
        audience_refs=("ev-breakfast-1",),
        # The screen found a direct claim mode, so the *default* permits a
        # direct-audience reading and only the code rule can refuse one. That
        # is what makes the refusal below the code rule's and not the default's.
        claim_mode=AudienceTransfer.DIRECT_AUDIENCE,
    ),
    # §13 B · "Ramp Launches Instant Stablecoin Payments…"
    "ramp_stablecoin": _Walkthrough(
        case="ramp_stablecoin",
        claims=(
            _Claim(
                "ev-ramp-1",
                "Ramp says settlement of stablecoin payments completes within "
                "minutes rather than days.",
                "Ramp's own announcement, as reported.",
                2,
            ),
            _Claim(
                "ev-ramp-2",
                "The payment rail does not change the amount a business is "
                "owed.",
                "The documented mechanism.",
                2,
            ),
            _Claim(
                "ev-ramp-3",
                "The compliance requirements for a business on the rail are "
                "recorded as unchanged.",
                "The documented requirement list.",
                2,
            ),
        ),
        audience_refs=("ev-ramp-1",),
        claim_mode=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
    ),
    # §13 C · "U.S. Uranium Production Hits Record High in 2025…"
    "uranium_record_high": _Walkthrough(
        case="uranium_record_high",
        claims=(
            _Claim(
                "ev-uranium-1",
                "U.S. uranium production in 2025 was triple the 2024 figure.",
                "National production statistics, as published.",
                3,
            ),
            _Claim(
                "ev-uranium-2",
                "The published series covers producers, not their suppliers or "
                "contractors.",
                "The published series' own coverage note.",
                3,
            ),
            _Claim(
                "ev-uranium-3",
                "No inspection or compliance figure appears in the published "
                "series.",
                "The published series, as read.",
                2,
            ),
        ),
        audience_refs=("ev-uranium-1",),
        claim_mode=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
    ),
}


def _source() -> NormalizedSource:
    return NormalizedSource(
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
    )


def _core(walkthrough: _Walkthrough) -> EvidenceCore:
    """One walkthrough's core, built directly: E-04 is what S-04 reads."""

    signal_id = f"signal-301-{walkthrough.case}"
    observations = []
    claims = []
    for claim in walkthrough.claims:
        observation = SourceObservation(
            observation_id=f"obs-{claim.identity}",
            signal_id=signal_id,
            source_ref="src-1",
            kind=ObservationKind.QUOTE,
            excerpt=claim.statement,
            attribution=f"Example Press reports: {claim.statement}",
            is_third_party_assertion=False,
        )
        observations.append(observation)
        claims.append(
            EvidenceClaim(
                evidence_claim_id=claim.identity,
                statement=claim.statement,
                observation_refs=(observation.observation_id,),
                source_refs=("src-1",),
                verdict=claim.verdict,
                verdict_rationale="The cited excerpt states it.",
                scope=claim.scope,
                strength=LADDER.at(claim.level),
                ceiling=LADDER.at(claim.level),
            )
        )
    return EvidenceCore(
        core_id=f"core-301-{walkthrough.case}",
        version=1,
        signal_ids=(signal_id,),
        research_artifact_refs=(
            (f"artifact-301-{walkthrough.case}", "sha256:" + "d" * 64),
        ),
        sources=(_source(),),
        observations=tuple(observations),
        evidence_claims=tuple(claims),
        readiness=EvidenceReadiness.READY,
    )


def _features(core: EvidenceCore) -> MaterialFeatures:
    """E-05 over one core: all twelve, one positive value with a reference."""

    cited = (core.evidence_claims[0].evidence_claim_id,)
    values = []
    for feature in MaterialFeature:
        if feature is MaterialFeature.FIGURE_PROVENANCE:
            value: Any = FeatureFigureProvenance.NONE
        elif feature is MaterialFeature.FRESHNESS:
            value = Freshness.LOW
        else:
            value = feature is MaterialFeature.DOCUMENTED_CASE
        values.append(
            FeatureValue(
                feature=feature,
                value=value,
                confidence=Confidence(
                    ConfidenceLevel.MEDIUM, "Read off the cited excerpt."
                ),
                evidence_refs=cited if value is True else (),
            )
        )
    return MaterialFeatures(
        features_id=f"feat-{core.core_id}",
        core_ref=(core.core_id, core.version),
        values=tuple(values),
    )


def _relevance(
    walkthrough: _Walkthrough, *, claim_mode: Optional[AudienceTransfer] = None
) -> BoundaryInput:
    return BoundaryInput(
        relevance=BusinessAudienceRelevance.INDIRECT,
        audience_transfer=claim_mode or walkthrough.claim_mode,
        relevance_bases=(
            RelevanceBasis(
                basis_type=AudienceRelevanceBasisType.CREDIBLE_SECTOR_EVIDENCE,
                evidence_claim_refs=walkthrough.audience_refs,
                source_refs=("src-1",),
            ),
        ),
    )


RELEVANCE_REF = DecisionRef(
    path="artifacts/decision.json", digest="sha256:" + "e" * 64
)


def _audience() -> Any:
    attributes = load_vocabularies(REGISTER).get(ATTRIBUTES_VOCABULARY)
    return load_audience_profile(CLIENT / PROFILE_FILE, attributes)


def _families() -> Any:
    return probe_families(load_register(REGISTER, today=TODAY))


def _saved(case: str, kind: str) -> str:
    return (FIXTURES / f"{case}.{kind}.json").read_text(encoding="utf-8")


# ===========================================================================
# Transports: the saved answers, routed by the instructions each call carries
# ===========================================================================


class _Replaying:
    """The two saved answers of one walkthrough, and nothing else.

    Routed by instructions rather than by call order, because what separates
    the generate call from the probe call is exactly that (U-1) — a transport
    that answered by position would pass a stage that made one call twice.
    """

    def __init__(
        self,
        *,
        generate: Optional[str] = None,
        probe: Optional[str] = None,
        test: Optional[str] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.generate = generate
        self.probe = probe
        self.test = test
        self.error = error
        self.instructions: list[str] = []
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.instructions.append(instructions)
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if instructions == GENERATE_INSTRUCTIONS:
            return self.generate or "{}"
        if instructions == PROBE_INSTRUCTIONS:
            return self.probe or "{}"
        return self.test or "{}"


def _transport(case: str, **overrides: Any) -> _Replaying:
    answers: dict[str, Any] = {
        "generate": _saved(case, "generate"),
        "probe": _saved(case, "probe"),
    }
    answers.update(overrides)
    return _Replaying(**answers)


def _decide(
    case: str,
    *,
    transport: Optional[_Replaying] = None,
    assets: Sequence[Asset] = (),
    claim_mode: Optional[AudienceTransfer] = None,
    budget: Optional[ArpCallBudget] = None,
) -> BoundaryDecision:
    walkthrough = WALKTHROUGHS[case]
    core = _core(walkthrough)
    return decide_boundary(
        core=core,
        features=_features(core),
        relevance=_relevance(walkthrough, claim_mode=claim_mode),
        relevance_ref=RELEVANCE_REF,
        audience=_audience(),
        families=_families(),
        transport=transport or _transport(case),
        ladder=LADDER,
        assets=assets,
        budget=budget,
    )


def _member(boundary: InterpretationBoundary, statement: str) -> Interpretation:
    for item in boundary.members:
        if item.statement == statement:
            return item
    raise AssertionError(
        f"the boundary lists no interpretation stating {statement!r}; it lists "
        + "; ".join(item.statement for item in boundary.members)
    )


def _probe(boundary: InterpretationBoundary, record_id: str) -> ProbeApplication:
    for item in boundary.probes:
        if item.record_id == record_id:
            return item
    raise AssertionError(f"{record_id} was not recorded as applied")


def _without(
    payload: str, *, family: Optional[str] = None, verdict: Optional[int] = None
) -> str:
    """One saved probe answer with a family or a verdict taken out of it."""

    answer = json.loads(payload)
    if family is not None:
        answer["families"] = [
            item for item in answer["families"] if item["record_id"] != family
        ]
    if verdict is not None:
        answer["verdicts"] = [
            item for item in answer["verdicts"] if item["index"] != verdict
        ]
    return json.dumps(answer)


# ===========================================================================
# Acceptance: the three walkthroughs
# ===========================================================================


def test_the_uranium_walkthrough_skips_with_no_admissible_interpretation():
    """§13 C: `SKIP`, reason "no admissible interpretation for the reader"."""

    decision = _decide("uranium_record_high")
    boundary = decision.boundary

    assert boundary is not None, (
        "the boundary is produced even when it admits nothing: what was "
        "generated and tested is the finding"
    )
    assert boundary.admissible == ()
    assert boundary.outcome.outcome is ArpOutcome.SKIP
    assert (
        boundary.outcome.state_code
        is StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION
    )
    assert "no admissible interpretation" in (boundary.outcome.reason or "")
    assert boundary.outcome.scope is OutcomeScope.SIGNAL


def test_the_uranium_walkthrough_keeps_the_reading_the_real_output_produced():
    """The inadmissible list is V-T02's detection material, not a discard pile."""

    boundary = _decide("uranium_record_high").boundary
    assert boundary is not None

    buried = _member(boundary, "Owners were buried in inspections.")
    assert buried.admissibility is Admissibility.INADMISSIBLE
    assert buried.inadmissible_reason is InadmissibleReason.UNSUPPORTED
    assert buried.temptation_note, "I-05 detection needs the note, not only the list"
    assert _probe(boundary, "K-TEMPT-07").interpretation_id == buried.interpretation_id


def test_the_ladder_refuses_a_forecast_the_probe_admitted():
    """Step 4 §7: a forecast is capped at level 2, whatever its supports."""

    boundary = _decide("uranium_record_high").boundary
    assert boundary is not None

    forecast = _member(boundary, "Contractors to the sector will see sustained demand.")
    assert forecast.kind is InterpretationKind.FORECAST
    assert forecast.ceiling.level == CAPPED_LEVEL, (
        "the supporting claim reaches level 3 and the forecast cap is what "
        "brings the ceiling down"
    )
    assert forecast.strength.level == 3
    assert forecast.inadmissible_reason is InadmissibleReason.EXCEEDS_CEILING


def test_the_ramp_walkthrough_records_benefit_inflation_as_inadmissible():
    """§13 B: "the business has more money" is what the material invites."""

    decision = _decide("ramp_stablecoin")
    boundary = decision.boundary
    assert boundary is not None

    inflated = _member(boundary, "The business has more money.")
    assert inflated.admissibility is Admissibility.INADMISSIBLE
    assert inflated.inadmissible_reason is InadmissibleReason.UNSUPPORTED
    found = _probe(boundary, "K-TEMPT-02")
    assert found.finding is ProbeFinding.FOUND
    assert found.interpretation_id == inflated.interpretation_id
    assert [limit.text for limit in boundary.limits] == ["There is not more money."]
    assert boundary.outcome.outcome is ArpOutcome.RESOLVE


def test_the_ramp_walkthrough_records_the_contradicted_burden_reading():
    """The second family of walkthrough B: "the compliance checklist doubles"."""

    boundary = _decide("ramp_stablecoin").boundary
    assert boundary is not None

    doubled = _member(boundary, "The compliance checklist doubles.")
    assert doubled.inadmissible_reason is InadmissibleReason.CONTRADICTED, (
        "the probe's own reason survives: code narrows the boundary, it does "
        "not relabel a judgment that was already made"
    )
    assert _probe(boundary, "K-TEMPT-07").interpretation_id == doubled.interpretation_id


def test_the_breakfast_walkthrough_records_the_reader_scene_as_inadmissible():
    """§13 A: "you, the reader, bake at night", found by K-TEMPT-01."""

    boundary = _decide("breakfast_founder").boundary
    assert boundary is not None

    scene = _member(boundary, "You, the reader, bake at night.")
    assert scene.admissibility is Admissibility.INADMISSIBLE
    assert scene.inadmissible_reason is InadmissibleReason.INVENTED_SCENE
    assert scene.temptation_note
    transfer = _probe(boundary, "K-TEMPT-01")
    assert transfer.finding is ProbeFinding.FOUND
    assert transfer.interpretation_id == scene.interpretation_id
    assert [item.statement for item in boundary.admissible] == [
        "Growth hit the founder's capacity: orders arrived faster than one "
        "home kitchen could fill them."
    ]


# ===========================================================================
# The code rules (§1, Decider; U-1 step 3)
# ===========================================================================


def test_the_transfer_rule_refuses_a_reader_consequence_the_probe_admitted():
    """AD-08 and E-08: `direct_audience` needs evidence scoped to the reader."""

    boundary = _decide("breakfast_founder").boundary
    assert boundary is not None

    transferred = _member(
        boundary, "Readers who bake at home will hit the same ceiling."
    )
    assert transferred.audience_transfer is AudienceTransfer.DIRECT_AUDIENCE
    assert transferred.inadmissible_reason is (
        InadmissibleReason.TRANSFER_NOT_SUPPORTED
    ), "the probe admitted it; the relevance screen scoped no claim to the reader"


def test_the_claim_mode_narrows_a_direct_reading_and_the_code_never_widens_one():
    """AD-08: the #58 claim mode is the default, and code only makes it stricter."""

    boundary = _decide(
        "breakfast_founder", claim_mode=AudienceTransfer.BOUNDED_EXTERNAL_CASE
    ).boundary
    assert boundary is not None

    transferred = _member(
        boundary, "Readers who bake at home will hit the same ceiling."
    )
    assert transferred.audience_transfer is AudienceTransfer.BOUNDED_EXTERNAL_CASE, (
        "the model asked for direct_audience and the screen established a "
        "bounded external case; the stricter of the two is what is recorded"
    )
    assert transferred.admissibility is Admissibility.ADMISSIBLE


def test_a_reading_citing_nothing_the_core_holds_is_refused_by_code():
    """Resolvable references, the third code rule (I-04's middle link)."""

    boundary = _decide("breakfast_founder").boundary
    assert boundary is not None

    invented = _member(boundary, "Hiring would have solved the problem.")
    assert invented.support_refs == ()
    assert invented.inadmissible_reason is InadmissibleReason.UNSUPPORTED

    usable = {
        claim.evidence_claim_id
        for claim in _core(WALKTHROUGHS["breakfast_founder"]).usable_claims
    }
    for item in boundary.admissible:
        assert item.support_refs, "every admissible reading cites a usable claim"
        assert set(item.support_refs) <= usable


def test_an_admissible_reading_citing_an_unusable_claim_is_refused():
    """E-03's usability rule: only accepted and qualified claims carry a reading."""

    walkthrough = _Walkthrough(
        case="breakfast_founder",
        claims=(
            WALKTHROUGHS["breakfast_founder"].claims[0],
            _Claim(
                "ev-breakfast-2",
                "A second outlet's account of the same kitchen was rejected.",
                "The second account, as assessed.",
                1,
                verdict=EvidenceDisposition.REJECTED,
            ),
            WALKTHROUGHS["breakfast_founder"].claims[2],
        ),
        audience_refs=("ev-breakfast-1",),
        claim_mode=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
    )
    core = _core(walkthrough)
    generated = json.loads(_saved("breakfast_founder", "generate"))
    generated["interpretations"][0]["support_refs"] = ["ev-breakfast-2"]

    decision = decide_boundary(
        core=core,
        features=_features(core),
        relevance=_relevance(walkthrough),
        relevance_ref=RELEVANCE_REF,
        audience=_audience(),
        families=_families(),
        transport=_transport(
            "breakfast_founder", generate=json.dumps(generated)
        ),
        ladder=LADDER,
    )

    assert decision.boundary is not None
    refused = decision.boundary.members[0]
    assert refused.inadmissible_reason is InadmissibleReason.UNSUPPORTED
    assert refused.strength.level == 1, (
        "a reading with nothing citable behind it is floored, not left at the "
        "level the model asked for"
    )


def test_a_reading_resting_on_a_refused_premise_is_refused_with_it():
    """I-05 one link along: a conclusion a text may state only by stating an
    inadmissible premise is inadmissible too."""

    generated = json.loads(_saved("ramp_stablecoin", "generate"))
    probed = json.loads(_saved("ramp_stablecoin", "probe"))
    probed["verdicts"][0]["admissibility"] = "inadmissible"
    probed["verdicts"][0]["reason"] = "contradicted"
    probed["verdicts"][0]["temptation_note"] = "The announcement is quotable."

    boundary = _decide(
        "ramp_stablecoin",
        transport=_transport(
            "ramp_stablecoin",
            generate=json.dumps(generated),
            probe=json.dumps(probed),
        ),
    ).boundary
    assert boundary is not None

    dependent = _member(
        boundary,
        "A business on this rail can plan its cash timing against a shorter "
        "settlement window.",
    )
    assert dependent.depends_on == (
        interpretation_id("core-301-ramp_stablecoin", 1),
    )
    assert dependent.inadmissible_reason is InadmissibleReason.UNSUPPORTED
    assert boundary.admissible == ()


def test_no_interpretation_sits_in_both_lists():
    """E-09 validation, by construction: one admissibility per record."""

    boundary = _decide("ramp_stablecoin").boundary
    assert boundary is not None

    identities = [item.interpretation_id for item in boundary.members]
    assert len(identities) == len(set(identities))
    assert set(boundary.admissible).isdisjoint(boundary.inadmissible)
    assert len(boundary.admissible) + len(boundary.inadmissible) == len(
        boundary.members
    )


def test_a_boundary_listing_one_interpretation_twice_is_refused():
    """The same rule, asserted where it would have to fail."""

    boundary = _decide("ramp_stablecoin").boundary
    assert boundary is not None

    with pytest.raises(BoundaryError, match="listed twice"):
        InterpretationBoundary(
            boundary_id=boundary.boundary_id,
            version=1,
            core_ref=boundary.core_ref,
            relevance_ref=boundary.relevance_ref,
            members=(boundary.members[0], boundary.members[0]),
            probes=boundary.probes,
            outcome=boundary.outcome,
            reader_connection=boundary.reader_connection,
        )


def test_an_admissible_record_may_not_stand_above_its_ceiling():
    """Step 1, E-08: that state has one reason, and it is `exceeds_ceiling`."""

    with pytest.raises(BoundaryError, match="exceeds_ceiling"):
        Interpretation(
            interpretation_id="int-301-1",
            version=1,
            statement="Asserted above what the evidence reaches.",
            kind=InterpretationKind.CAUSE,
            support_refs=("ev-1",),
            audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
            strength=LADDER.at(4),
            ceiling=LADDER.at(2),
            admissibility=Admissibility.ADMISSIBLE,
            rationale=Justification(text="Because."),
        )


def test_an_inadmissible_record_carries_a_reason_and_a_temptation_note():
    """§1 Post, and the detection material V-T02 reconciles against."""

    for missing, pattern in (
        ({"inadmissible_reason": None}, "says why not"),
        ({"temptation_note": None}, "temptation note"),
    ):
        fields: dict[str, Any] = {
            "interpretation_id": "int-301-1",
            "version": 1,
            "statement": "A reading the evidence does not carry.",
            "kind": InterpretationKind.CAUSE,
            "support_refs": (),
            "audience_transfer": AudienceTransfer.BOUNDED_EXTERNAL_CASE,
            "strength": LADDER.at(1),
            "ceiling": LADDER.at(1),
            "admissibility": Admissibility.INADMISSIBLE,
            "rationale": Justification(text="Because."),
            "inadmissible_reason": InadmissibleReason.UNSUPPORTED,
            "temptation_note": "A writer would reach for it.",
        }
        fields.update(missing)
        with pytest.raises(BoundaryError, match=pattern):
            Interpretation(**fields)


# ===========================================================================
# The two calls (U-1) and what a half-answered stage may not do
# ===========================================================================


def test_the_stage_makes_two_separate_calls_in_order():
    """U-1: generate, then probe, and never the two in one call."""

    transport = _transport("ramp_stablecoin")
    decision = _decide("ramp_stablecoin", transport=transport)

    assert transport.instructions == [GENERATE_INSTRUCTIONS, PROBE_INSTRUCTIONS]
    assert decision.calls == 2
    assert GENERATE_INSTRUCTIONS != PROBE_INSTRUCTIONS


def test_every_family_of_the_register_is_recorded_as_applied():
    """Patch R1: the boundary records which families were applied."""

    boundary = _decide("ramp_stablecoin").boundary
    assert boundary is not None

    applied = [item.record_id for item in boundary.probes]
    assert applied == [family.record_id for family in _families()]
    assert len(applied) == PROBE_FAMILY_COUNT
    for item in boundary.probes:
        assert item.note, "a family that found nothing says what it looked for"
        assert item.knowledge is not None, (
            "the trace records the family as it was at the time of use"
        )
    assert {item.finding for item in boundary.probes} == {
        ProbeFinding.FOUND,
        ProbeFinding.NONE_FOUND,
    }


def test_a_probe_that_skips_a_family_is_refused_rather_than_read_as_nothing_found():
    """"This family found nothing" and "nobody asked" are different facts."""

    transport = _transport(
        "ramp_stablecoin",
        probe=_without(_saved("ramp_stablecoin", "probe"), family="K-TEMPT-03"),
    )
    decision = _decide("ramp_stablecoin", transport=transport)

    assert decision.boundary is None, (
        "an admissible set nobody tested against the whole checklist is not a "
        "weaker boundary; it is the error U-1 exists to catch"
    )
    outcome = decision.outcomes[0]
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.BOUNDARY_PROBE_FAILED
    assert "K-TEMPT-03" in (outcome.reason or "")
    assert decision.calls == 2


def test_a_probe_that_leaves_an_interpretation_untested_is_refused():
    """U-1 tests every generated reading; an untested one is not admissible."""

    transport = _transport(
        "ramp_stablecoin",
        probe=_without(_saved("ramp_stablecoin", "probe"), verdict=2),
    )
    decision = _decide("ramp_stablecoin", transport=transport)

    assert decision.boundary is None
    assert decision.outcomes[0].state_code is StateCode.BOUNDARY_PROBE_FAILED


def test_a_probe_refusing_a_reading_without_a_reason_is_refused():
    """§1 Post gives every inadmissible reading a reason and a note."""

    probed = json.loads(_saved("ramp_stablecoin", "probe"))
    probed["verdicts"][0]["admissibility"] = "inadmissible"
    decision = _decide(
        "ramp_stablecoin",
        transport=_transport("ramp_stablecoin", probe=json.dumps(probed)),
    )

    assert decision.boundary is None
    assert decision.outcomes[0].state_code is StateCode.BOUNDARY_PROBE_FAILED


def test_a_probe_answering_for_a_family_this_run_does_not_carry_is_refused():
    """The checklist is the register's, not the model's."""

    probed = json.loads(_saved("ramp_stablecoin", "probe"))
    probed["families"].append(
        {"record_id": "K-TEMPT-99", "finding": "Invented.", "tempting": None}
    )
    decision = _decide(
        "ramp_stablecoin",
        transport=_transport("ramp_stablecoin", probe=json.dumps(probed)),
    )

    assert decision.boundary is None
    assert "K-TEMPT-99" in (decision.outcomes[0].reason or "")


def test_a_generate_call_that_does_not_answer_skips_the_signal():
    """Nothing to degrade to: an empty boundary is not a weaker one."""

    for transport in (
        _transport("ramp_stablecoin", generate="not json at all"),
        _Replaying(error=RuntimeError("provider refused")),
    ):
        decision = _decide("ramp_stablecoin", transport=transport)

        assert decision.boundary is None
        assert decision.outcomes[0].state_code is StateCode.BOUNDARY_GENERATION_FAILED
        assert decision.outcomes[0].outcome is ArpOutcome.SKIP
        assert decision.calls == 1
        assert transport.instructions == [GENERATE_INSTRUCTIONS], (
            "the probe is not attempted over nothing"
        )


def test_a_budget_that_runs_out_before_the_probe_leaves_no_boundary():
    """The fail-closed edge: a generated, unprobed set is never recorded."""

    budget = RunCallBudget(1)
    transport = _transport("ramp_stablecoin")

    decision = _decide(
        "ramp_stablecoin", transport=transport, budget=ArpCallBudget(budget)
    )

    assert transport.instructions == [GENERATE_INSTRUCTIONS]
    assert decision.boundary is None
    assert decision.outcomes[0].state_code is StateCode.BUDGET_EXHAUSTED
    assert decision.calls == 1


def test_a_budget_already_spent_makes_no_call_at_all():
    budget = RunCallBudget(1)
    budget.spend()
    transport = _transport("ramp_stablecoin")

    decision = _decide(
        "ramp_stablecoin", transport=transport, budget=ArpCallBudget(budget)
    )

    assert transport.instructions == []
    assert decision.calls == 0
    assert decision.boundary is None


# ===========================================================================
# What may not enter the boundary (Step 1, E-09)
# ===========================================================================


def test_no_client_position_reaches_either_request():
    """"Client rights to speak, lens and portfolio do not enter the boundary"."""

    positional = Asset(
        asset_id="asset-301-position",
        asset_class=AssetClass.POSITIONAL,
        kind=AssetKind.CLIENT_POSITION,
        refs=(APPROVED_POSITION,),
        strength=Confidence(ConfidenceLevel.HIGH, "The client declared it."),
    )
    evidentiary = Asset(
        asset_id="asset-301-figure",
        asset_class=AssetClass.EVIDENTIARY,
        kind=AssetKind.FIGURE,
        refs=("ev-ramp-1",),
        strength=Confidence(ConfidenceLevel.MEDIUM, "The announcement carries it."),
    )
    transport = _transport("ramp_stablecoin")

    _decide("ramp_stablecoin", transport=transport, assets=(positional, evidentiary))

    assert transport.requests, "the requests are what the claim is about"
    for request in transport.requests:
        assert APPROVED_POSITION not in request
        assert "client_position" not in request
        assert "portfolio" not in request
        assert "lens" not in request
    assert "asset-301-figure" in transport.requests[0], (
        "the evidentiary assets do go in: §1 lists E-06 among S-04's inputs"
    )


def test_the_audience_profile_is_the_only_context_that_enters():
    """Step 1: only the Audience Profile enters, for the reader connection.

    Asserted on the whole key set of each request rather than on what is
    missing from it: "there is nowhere to put a client position" is a claim
    about the shape of the request, and a test that only looked for the words
    would pass a request that grew a field for one.
    """

    transport = _transport("ramp_stablecoin")
    _decide("ramp_stablecoin", transport=transport)

    generate, probe = (json.loads(request) for request in transport.requests)
    assert set(generate) == {
        "core", "features", "assets", "audience_profile", "ladder", "relevance"
    }
    assert set(probe) == {
        "core", "audience_profile", "interpretations", "probe_families"
    }
    assert generate["audience_profile"] == {
        "english_level": "global",
        "cultural_context": "international",
    }


# ===========================================================================
# The ARP column (§1)
# ===========================================================================


def test_only_low_strength_interpretations_degrade():
    """§1, ARP: proceed with low confidence recorded."""

    generated = json.loads(_saved("ramp_stablecoin", "generate"))
    for item in generated["interpretations"]:
        item["strength_level"] = 1

    boundary = _decide(
        "ramp_stablecoin",
        transport=_transport("ramp_stablecoin", generate=json.dumps(generated)),
    ).boundary
    assert boundary is not None

    assert boundary.admissible, "the readings stand; what is low is their strength"
    assert boundary.outcome.outcome is ArpOutcome.DEGRADE
    assert (
        boundary.outcome.state_code is StateCode.ONLY_LOW_STRENGTH_INTERPRETATION
    )


def test_a_boundary_with_no_reader_connection_skips_even_with_a_reading():
    """§1 Post: the reader connection is present, or the outcome is `SKIP`."""

    generated = json.loads(_saved("ramp_stablecoin", "generate"))
    generated["reader_connection"] = None

    decision = _decide(
        "ramp_stablecoin",
        transport=_transport("ramp_stablecoin", generate=json.dumps(generated)),
    )
    boundary = decision.boundary
    assert boundary is not None

    assert boundary.admissible, "readings the evidence admits are still recorded"
    assert boundary.reader_connection is None
    assert boundary.outcome.outcome is ArpOutcome.SKIP
    assert "connection to the configured audience" in (boundary.outcome.reason or "")


def test_a_reader_connection_citing_nothing_the_core_holds_is_not_one():
    """The connection is a claim about the material, and is cited or not made."""

    generated = json.loads(_saved("ramp_stablecoin", "generate"))
    generated["reader_connection"]["refs"] = ["ev-not-in-this-core"]

    boundary = _decide(
        "ramp_stablecoin",
        transport=_transport("ramp_stablecoin", generate=json.dumps(generated)),
    ).boundary
    assert boundary is not None
    assert boundary.reader_connection is None
    assert boundary.outcome.outcome is ArpOutcome.SKIP


def test_the_new_states_permit_only_the_outcomes_step_2_gives_them():
    assert permitted_outcomes(StateCode.BOUNDARY_GENERATION_FAILED) == frozenset(
        {ArpOutcome.SKIP}
    )
    assert permitted_outcomes(StateCode.BOUNDARY_PROBE_FAILED) == frozenset(
        {ArpOutcome.SKIP}
    )
    assert permitted_outcomes(
        StateCode.ONLY_LOW_STRENGTH_INTERPRETATION
    ) == frozenset({ArpOutcome.DEGRADE})


def test_the_new_states_are_counted_where_a_client_can_read_them():
    """Step 3 §3.3: a provider outage is never counted as editorial selectivity."""

    assert (
        reason_category(StateCode.BOUNDARY_GENERATION_FAILED)
        is ReasonCategory.PROVIDER
    )
    assert reason_category(StateCode.BOUNDARY_PROBE_FAILED) is ReasonCategory.PROVIDER
    assert (
        reason_category(StateCode.ONLY_LOW_STRENGTH_INTERPRETATION)
        is ReasonCategory.BOUNDARY
    )


# ===========================================================================
# The boundary commit, and the re-entry from S-13
# ===========================================================================


RUN_ID = create_run_id()


def _workspace(tmp_path: Path) -> RunWorkspace:
    return RunWorkspace.create(tmp_path / "editorial_runs", RUN_ID)


def _committed(tmp_path: Path, case: str = "ramp_stablecoin") -> tuple[
    RunWorkspace, InterpretationBoundary
]:
    workspace = _workspace(tmp_path)
    boundary = _decide(case).boundary
    assert boundary is not None
    commit_boundary_version(workspace, boundary)
    return workspace, boundary


def _reentry(
    boundary: InterpretationBoundary,
    *,
    answer: dict[str, Any],
    counters: Optional[AttemptCounterLedger] = None,
    anchor: Optional[str] = None,
    destination: str = "unit-301/wix",
    unit_id: str = "unit-301",
    transport: Optional[_Replaying] = None,
) -> Any:
    walkthrough = WALKTHROUGHS["ramp_stablecoin"]
    return re_enter_boundary(
        boundary=boundary,
        core=_core(walkthrough),
        audience=_audience(),
        detected=DetectedInterpretation(
            statement=answer.get("statement") or "A reading the text expressed.",
            destination=destination,
            text_ref="txt-301-1",
        ),
        unit_id=unit_id,
        transport=transport or _Replaying(test=json.dumps(answer)),
        ladder=LADDER,
        counters=counters or AttemptCounterLedger(),
        anchor_interpretation_id=anchor,
    )


NEW_READING = {
    "matches": None,
    "reason": "unsupported",
    "temptation_note": "Being paid first reads as being ahead, which nothing measures.",
    "finding": "Nothing in the core compares this business with any other.",
    "statement": "Every business on the rail is paid faster than its competitors.",
    "kind": "comparison",
    "support_refs": [],
    "rationale": "The announcement states a settlement window and no comparison.",
    "rationale_refs": ["ev-ramp-1"],
}


def test_a_re_entry_commits_both_sides_with_the_marker_last(tmp_path: Path):
    """The acceptance evidence: a coordinated E-08/E-09 change, committed once."""

    workspace, boundary = _committed(tmp_path)
    first = current_boundary(workspace.run_dir)
    assert first is not None and first.version == 1

    reentry = _reentry(
        boundary,
        answer=NEW_READING,
        anchor=boundary.admissible[0].interpretation_id,
    )
    assert reentry.boundary is not None
    commit = commit_boundary_version(workspace, reentry.boundary)

    assert commit.version == 2
    assert commit.written == (reentry.detected_interpretation_id,), (
        "the unchanged members are referenced where they are, not copied"
    )
    current = current_boundary(workspace.run_dir)
    assert current is not None and current.version == 2 and current.verified
    assert (
        reentry.detected_interpretation_id,
        1,
    ) in [(item.interpretation_id, item.version) for item in current.members]
    assert orphan_interpretation_versions(workspace.run_dir) == (), (
        "a commit that finished leaves no E-08 version the marker does not "
        "reference"
    )


def test_an_e_08_version_written_without_its_marker_is_invisible(tmp_path: Path):
    """The orphan test, at the stage that writes the pair (§2.4 rule 3)."""

    workspace, boundary = _committed(tmp_path)
    reentry = _reentry(boundary, answer=NEW_READING)
    assert reentry.boundary is not None
    discovered = next(
        item
        for item in reentry.boundary.members
        if item.interpretation_id == reentry.detected_interpretation_id
    )

    # The crash: step 1 of the commit ran and step 2 did not.
    write_interpretation_version(
        workspace,
        InterpretationVersion(
            interpretation_id=discovered.interpretation_id,
            version=discovered.version,
            admissibility=discovered.admissibility,
            payload=discovered.as_entity(),
        ),
    )

    current = current_boundary(workspace.run_dir)
    assert current is not None and current.version == 1, (
        "the previous boundary stays current: the marker is the commit"
    )
    orphans = orphan_interpretation_versions(workspace.run_dir)
    assert [item.interpretation_id for item in orphans] == [
        discovered.interpretation_id
    ]
    assert (
        workspace.run_dir
        / interpretation_relative_path(discovered.interpretation_id, 1)
    ).is_file(), "the orphan is kept on disk, for forensics"
    assert not (workspace.run_dir / boundary_relative_path(2)).exists()


def test_a_re_entry_that_reclassifies_the_anchor_routes_to_s_06(tmp_path: Path):
    """§1, ARP: the anchor was invalidated → `REPLAN` → S-06 (`L_anchor`)."""

    workspace, boundary = _committed(tmp_path)
    anchor = boundary.admissible[0]

    reentry = _reentry(
        boundary,
        answer={
            "matches": anchor.interpretation_id,
            "reason": "contradicted",
            "temptation_note": "The announcement is quotable and reads as settled.",
            "finding": "The text stated the window as a general fact.",
        },
        anchor=anchor.interpretation_id,
    )

    assert reentry.boundary is not None
    assert reentry.anchor_invalidated is True
    assert reentry.detected_interpretation_id == anchor.interpretation_id
    onward = reentry.outcomes[-1]
    assert onward.outcome is ArpOutcome.REPLAN
    assert onward.route_target == "S-06"
    assert onward.counter == "L_anchor"

    reclassified = next(
        item
        for item in reentry.boundary.members
        if item.interpretation_id == anchor.interpretation_id
    )
    assert reclassified.version == 2
    assert reclassified.supersedes == f"{anchor.interpretation_id}.v1"
    assert reclassified.admissibility is Admissibility.INADMISSIBLE

    # The reading that rested on the anchor loses its admissibility with it,
    # and loses it as a new version: its version 1 is already on disk.
    dependent = next(
        item
        for item in reentry.boundary.members
        if anchor.interpretation_id in item.depends_on
    )
    assert dependent.version == 2
    assert dependent.supersedes == f"{dependent.interpretation_id}.v1"
    assert dependent.inadmissible_reason is InadmissibleReason.UNSUPPORTED
    assert reentry.boundary.admissible == ()

    commit = commit_boundary_version(workspace, reentry.boundary)
    assert commit.written == (
        anchor.interpretation_id,
        dependent.interpretation_id,
    )
    current = current_boundary(workspace.run_dir)
    assert current is not None and current.version == 2 and current.verified
    assert current.admissible == (), (
        "a stale admissible pair never survives the commit that refused its "
        "premise"
    )


def test_a_re_entry_that_leaves_the_anchor_standing_routes_to_s_08(tmp_path: Path):
    """§1, ARP: the anchor stays admissible → `REPLAN` → S-08 (`L_strategy`)."""

    workspace, boundary = _committed(tmp_path)
    anchor = boundary.admissible[0]

    reentry = _reentry(
        boundary, answer=NEW_READING, anchor=anchor.interpretation_id
    )

    assert reentry.anchor_invalidated is False
    onward = reentry.outcomes[-1]
    assert onward.route_target == "S-08"
    assert onward.counter == "L_strategy"
    assert onward.scope is OutcomeScope.DESTINATION


def test_an_exhausted_boundary_counter_skips_the_causing_destination(tmp_path: Path):
    """§0.3: the destination whose text caused it, reason
    `boundary_reentry_exhausted`."""

    workspace, boundary = _committed(tmp_path)
    counters = AttemptCounterLedger()
    transport = _Replaying(test=json.dumps(NEW_READING))

    first = _reentry(
        boundary, answer=NEW_READING, counters=counters, transport=transport
    )
    assert first.boundary is not None

    second = _reentry(
        boundary,
        answer=NEW_READING,
        counters=counters,
        destination="unit-301/linkedin",
        transport=transport,
    )

    assert second.boundary is None
    assert second.calls == 0, "the refused call is never made"
    refused = second.outcomes[0]
    assert refused.outcome is ArpOutcome.SKIP
    assert refused.state_code is StateCode.BOUNDARY_REENTRY_EXHAUSTED
    assert refused.scope is OutcomeScope.DESTINATION
    assert refused.scope_key == "unit-301/linkedin", (
        "the counter is the unit's and the skip is the destination's (§0.3)"
    )
    assert transport.instructions == [TEST_INSTRUCTIONS], (
        "L_boundary is counted per unit, so the second destination of the same "
        "unit shares the attempt the first one spent"
    )


def test_a_test_call_that_does_not_answer_skips_the_destination(tmp_path: Path):
    """Fail closed: a text S-13 refused is not released because a call failed."""

    workspace, boundary = _committed(tmp_path)

    reentry = _reentry(
        boundary,
        answer=NEW_READING,
        transport=_Replaying(test="not json at all"),
    )

    assert reentry.boundary is None
    assert reentry.calls == 1
    skipped = reentry.outcomes[-1]
    assert skipped.outcome is ArpOutcome.SKIP
    assert skipped.scope is OutcomeScope.DESTINATION
    assert (
        skipped.state_code is StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION
    )


def test_a_test_call_naming_an_interpretation_the_boundary_lacks_is_refused(
    tmp_path: Path,
):
    """A match is a match against this boundary, or it is not one."""

    workspace, boundary = _committed(tmp_path)
    answer = dict(NEW_READING, matches="int-not-in-this-boundary")

    reentry = _reentry(boundary, answer=answer)

    assert reentry.boundary is None
    assert reentry.outcomes[-1].outcome is ArpOutcome.SKIP


def test_a_re_entry_without_a_unit_is_refused(tmp_path: Path):
    """`L_boundary` is counted per unit; an unnamed unit bounds nothing."""

    workspace, boundary = _committed(tmp_path)

    with pytest.raises(BoundaryError, match="counted per unit"):
        _reentry(boundary, answer=NEW_READING, unit_id="  ")
