"""Issue #299: S-01 builds Evidence Core v1 and screens relevance before spend.

SL-3's acceptance evidence for the second stage, as scenarios:

1. **on a fixed set of saved real research artifacts** (``tests/fixtures/
   evidence_core_299/``, three CNBC items this repository recorded), every core
   is referentially valid and every claim has a verdict, a strength and a
   ceiling — including the claims whose support did not establish them;
2. **relevance ``revise`` routes to enrichment**: a ``REPLAN`` into S-03 that
   spends ``L_enrich`` and names the gap, and a ``SKIP`` once the counter is
   gone. Not the wait the current engine takes;
3. the reconciled #58 profile, whose diff is in the pull request: relevance and
   claim mode feed the boundary, and the angle fields are hints — which is
   asserted here structurally, over what ``for_boundary()`` contains.

And the properties the stage rests on: observations are built from the
artifact's own support references and attributed by code (I-03 at source), the
existing research contract is wrapped and not replaced (AD-05), the Release 1
READY gate is not this stage's to apply, and every state it records is
countable in the public ledger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from src.editorial.decision_contract import (
    AudienceRelevanceBasisType,
    BusinessAudienceRelevance,
    DecisionDisposition,
    research_artifact_digest,
)
from src.editorial.decision_lens_evaluator import (
    DecisionLensEvaluator,
    DecisionLensInstructions,
)
from src.editorial.decision_lifecycle import RELEASE1_LENS_PROFILE
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.evidence_core import (
    STAGE,
    EvidenceClaim,
    EvidenceCore,
    EvidenceCoreError,
    ExtendedAssessment,
    ExtendedEvidenceAssessor,
    Figure,
    FigureProvenance,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
    build_attribution,
    build_evidence_core,
    observation_id,
    retrieve_evidence_core,
)
from src.editorial_core.relevance_screen import (
    ENRICHMENT_ROUTE_CAUSE,
    AudienceTransfer,
    RelevanceScreen,
    RelevanceScreenError,
    RequestedGapKind,
    screen_relevance,
)
from src.intake import from_jsonl_signal
from src.research.adapters.fake import (
    DeterministicFakeResearchProvider,
    FakeResearchScenario,
)
from src.research.assessment import (
    JUDGMENT_INSTRUCTIONS,
    EvidenceAssessmentError,
    assess_artifact,
)
from src.research.evidence import (
    Contradiction,
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    ResolutionStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
    UncertaintyAssessment,
)
from src.research.lifecycle import (
    ResearchGateError,
    build_research_request,
    load_research_envelope,
    validate_research_envelope,
)
from src.run import ExecutionMode, RunContext
from src.run.call_budget import RunCallBudget
from src.run.call_budget_arp import ArpCallBudget
from src.run.run_summary import ReasonCategory, reason_category
from src.run.run_workspace import (
    DeciderKind,
    EntityRef,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import (
    ConfigurationIdentity,
    StrategyExecutionContext,
)
from tests import test_generate_and_publish as legacy

#: The universal default ladder, worded as ``knowledge/ladders/default.md``
#: words it (K-LAD-01). The run's one ladder is an input of the stage, so the
#: test hands over the same one a run would.
LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

#: A client that will not assert past a corroborated claim.
CLIENT_CEILING = LADDER.at(3)

FIXTURES = Path("tests/fixtures/evidence_core_299")

#: The three saved artifacts, with the readiness each reaches once its evidence
#: is assessed. Only one of them would pass the Release 1 READY gate.
SAVED_CASES = (
    ("target_chair_support", EvidenceReadiness.NEEDS_REVIEW),
    ("ups_cold_chain_investment", EvidenceReadiness.READY),
    ("lucid_workforce_reduction", EvidenceReadiness.NEEDS_REVIEW),
)

NOW = datetime(2026, 6, 22, 16, 0, tzinfo=timezone.utc)

#: The two #58 fields AD-09 demotes to hints. Distinctive strings, so a test can
#: prove they are nowhere in what S-04 receives.
ANGLE = "ANGLE-HINT: how an owner keeps one profitable line sharp"
DEFENSIBLE = "PERSPECTIVE-HINT: the decision was about defending margin"


def _identity() -> ConfigurationIdentity:
    return ConfigurationIdentity(
        schema_version="1.0",
        configuration_id="never_blank",
        configuration_version="1",
        configuration_hash="sha256:" + "a" * 64,
    )


# ===========================================================================
# Transports: a model that answers what it was asked, and one that replays a
# saved answer
# ===========================================================================


class _Answering:
    """An extended assessment that answers exactly the request it was given.

    Deterministic and offline. It reads the claims and observation IDs out of
    the request, so it can never answer about something that was not asked —
    which is what makes the knobs below the only way a test produces a
    malformed answer.
    """

    def __init__(
        self,
        *,
        disposition: str = "accepted",
        strength_level: int = 2,
        kind: str = "quote",
        rationale: str = "The cited excerpt states the claim.",
        omit_claim: bool = False,
        omit_observation: bool = False,
        invent_observation: bool = False,
        raw: Optional[str] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.disposition = disposition
        self.strength_level = strength_level
        self.kind = kind
        self.rationale = rationale
        self.omit_claim = omit_claim
        self.omit_observation = omit_observation
        self.invent_observation = invent_observation
        self.raw = raw
        self.error = error
        self.instructions: list[str] = []
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.instructions.append(instructions)
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.raw is not None:
            return self.raw
        payload = json.loads(request)
        verdicts: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        for item in payload["claims"]:
            verdicts.append({
                "evidence_id": item["evidence_claim_id"],
                "disposition": self.disposition,
                "rationale": self.rationale,
            })
            claims.append({
                "evidence_claim_id": item["evidence_claim_id"],
                "scope": "the case the cited support records, and no wider",
                "strength_level": self.strength_level,
            })
            for observed in item["observations"]:
                observations.append({
                    "observation_id": observed["observation_id"],
                    "kind": self.kind,
                    "is_third_party_assertion": False,
                    "figure": None,
                })
        if self.omit_claim:
            claims = claims[:-1]
        if self.omit_observation:
            observations = observations[:-1]
        if self.invent_observation:
            observations.append({
                "observation_id": "obs-nobody-asked-about-1",
                "kind": "quote",
                "is_third_party_assertion": False,
                "figure": None,
            })
        return json.dumps({
            "verdicts": verdicts,
            "claims": claims,
            "observations": observations,
        })


class _Saved:
    """The saved extended assessment of one fixture, replayed verbatim."""

    def __init__(self, case: str) -> None:
        self.payload = (FIXTURES / f"{case}.response.json").read_text(encoding="utf-8")
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.requests.append(request)
        return self.payload


class _Lens:
    """The #58 transport, citing the evidence it read off its own request."""

    def __init__(
        self,
        *,
        disposition: str = "proceed",
        relevance: str = "direct",
        claim_mode: str = "direct_audience_claim",
        sufficiency: Optional[str] = None,
        basis_type: str = "direct_audience_evidence",
        restrictions: tuple[str, ...] = (),
        error: Optional[BaseException] = None,
    ) -> None:
        self.disposition = disposition
        self.relevance = relevance
        self.claim_mode = claim_mode
        self.sufficiency = sufficiency
        self.basis_type = basis_type
        self.restrictions = restrictions
        self.error = error
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        evidence = json.loads(request)["research_evidence"]
        evidence_ids = [item["evidence_id"] for item in evidence]
        source_ids = sorted(
            {source for item in evidence for source in item["source_ids"]}
        )
        sufficiency = self.sufficiency or (
            "sufficient" if self.disposition == "proceed" else "partial"
        )
        return json.dumps({
            "disposition": self.disposition,
            "claim_mode": self.claim_mode,
            "relevance": self.relevance,
            "evidence_sufficiency": sufficiency,
            "why_signal_matters": "It touches a decision the audience is making.",
            "business_value_connection": "The recorded case names the mechanism.",
            "audience_problem_or_opportunity": "Where to sharpen a current offer.",
            "defensible_perspective": DEFENSIBLE,
            "supported_editorial_angle": ANGLE,
            "source_ids": source_ids,
            "evidence_ids": evidence_ids,
            "relevance_bases": [{
                "basis_type": self.basis_type,
                "statement": "The cited research concerns the configured audience.",
                "evidence_ids": evidence_ids,
                "source_ids": source_ids,
                "documented_direct_consequence": None,
            }],
            "criterion_results": [{
                "criterion_id": "nb-supported-mechanism",
                "assessment": "satisfied",
                "conclusion": "The evidence supports one specific mechanism.",
                "evidence_ids": evidence_ids,
                "source_ids": source_ids,
                "restrictions": [],
            }],
            "research_condition_handling": [],
            "restrictions": list(self.restrictions),
            "disposition_reasons": ["The recorded evidence decides it."],
        })


# ===========================================================================
# Artifacts: the saved set, and hand-built ones for single properties
# ===========================================================================


def _saved_artifact(case: str) -> NormalizedResearchArtifact:
    raw = (FIXTURES / f"{case}.artifact.json").read_text(encoding="utf-8")
    return NormalizedResearchArtifact.model_validate_json(raw)


def _assess(
    artifact: NormalizedResearchArtifact, transport: Any
) -> tuple[NormalizedResearchArtifact, ExtendedEvidenceAssessor]:
    """One artifact through the real assessment path, extension and all.

    The transport always sits behind an :class:`ExtendedEvidenceAssessor`,
    because that is where it sits in the stage: the assessor is what turns the
    #125 request into the extended one and keeps the classification.
    """

    assessor = ExtendedEvidenceAssessor(transport, ladder=LADDER)
    return assess_artifact(artifact, transport=assessor), assessor


def _saved_core(case: str) -> tuple[EvidenceCore, NormalizedResearchArtifact]:
    """One saved artifact, assessed through the real path and wrapped as E-04."""

    assessed, assessor = _assess(_saved_artifact(case), _Saved(case))
    core = build_evidence_core(
        artifact=assessed,
        assessment=assessor.assessment,
        core_id=f"core-{case}",
        ladder=LADDER,
        client_ceiling=CLIENT_CEILING,
    )
    return core, assessed


def _source(
    source_id: str = "source-1",
    *,
    title: str = "Recorded report",
    publisher: Optional[str] = "Example Press",
    locator: str = "https://example.test/report",
) -> NormalizedSource:
    return NormalizedSource(
        source_id=source_id,
        locator=SourceLocator(kind=SourceLocatorKind.URL, value=locator),
        title=title,
        publisher=publisher,
        publication_time=PublicationTime(
            status=PublicationTimeStatus.KNOWN, value=NOW - timedelta(days=1)
        ),
        retrieved_at=NOW,
    )


def _record(
    evidence_id: str = "evidence-1",
    *,
    claim: str = "The plant recalled one component batch.",
    excerpts: tuple[str, ...] = ("The plant recalled one component batch.",),
    source_id: str = "source-1",
    disposition: EvidenceDisposition = EvidenceDisposition.NOT_ASSESSED,
    rationale: Optional[str] = None,
) -> ExtractedEvidence:
    return ExtractedEvidence(
        evidence_id=evidence_id,
        claim=claim,
        source_ids=(source_id,),
        support=tuple(
            SupportReference(source_id=source_id, excerpt=excerpt, location="summary")
            for excerpt in excerpts
        ),
        disposition=disposition,
        assessment_rationale=rationale,
    )


def _artifact(
    *,
    evidence: tuple[ExtractedEvidence, ...] = (),
    sources: tuple[NormalizedSource, ...] = (),
    readiness: EvidenceReadiness = EvidenceReadiness.INSUFFICIENT,
    uncertainties: tuple[UncertaintyAssessment, ...] = (),
    contradictions: tuple[Contradiction, ...] = (),
) -> NormalizedResearchArtifact:
    return NormalizedResearchArtifact(
        artifact_id="artifact-299",
        run_id="3f9c1d7a-58b2-4e6c-9a1f-2d4b6e8c0a11",
        assignment_id="assignment-299",
        signal_id="signal-299",
        configuration_identity=_identity(),
        created_at=NOW,
        sources=sources or (_source(),),
        evidence=evidence or (_record(),),
        uncertainties=uncertainties,
        contradictions=contradictions,
        readiness=readiness,
    )


# ===========================================================================
# The saved set (acceptance evidence 1)
# ===========================================================================


@pytest.mark.parametrize(("case", "readiness"), SAVED_CASES)
def test_every_saved_artifact_builds_a_core_whose_references_resolve(
    case: str, readiness: EvidenceReadiness
):
    """Referential validity is enforced in the constructor; this is the set."""

    core, assessed = _saved_core(case)

    assert core.version == 1
    assert core.readiness is readiness
    assert core.signal_ids == (assessed.signal_id,)
    assert core.research_artifact_refs == (
        (assessed.artifact_id, research_artifact_digest(assessed)),
    )
    known_sources = {source.source_id for source in core.sources}
    known_observations = {item.observation_id for item in core.observations}
    for claim in core.evidence_claims:
        assert set(claim.observation_refs) <= known_observations
        assert set(claim.source_refs) <= known_sources
    for observation in core.observations:
        assert observation.source_ref in known_sources


@pytest.mark.parametrize(("case", "readiness"), SAVED_CASES)
def test_every_claim_of_every_saved_core_has_a_verdict_strength_and_ceiling(
    case: str, readiness: EvidenceReadiness
):
    core, _ = _saved_core(case)

    assert core.evidence_claims, "a saved artifact with no claim proves nothing"
    for claim in core.evidence_claims:
        assert isinstance(claim.verdict, EvidenceDisposition)
        assert claim.verdict_rationale.strip()
        assert claim.scope.strip()
        assert claim.strength.ladder_id == LADDER.ladder_id
        assert claim.ceiling.ladder_id == LADDER.ladder_id
        assert 1 <= claim.strength.level <= len(LADDER.levels)
        # The ceiling is the lower of the client's and the evidence's, so it is
        # never above either of them.
        assert claim.ceiling.level <= claim.strength.level
        assert claim.ceiling.level <= CLIENT_CEILING.level


@pytest.mark.parametrize(("case", "readiness"), SAVED_CASES)
def test_the_core_holds_one_observation_per_excerpt_retrieval_returned(
    case: str, readiness: EvidenceReadiness
):
    """I-03 at source: nothing enters the core without an observation, and no
    observation enters it that a source did not record."""

    core, assessed = _saved_core(case)

    expected = tuple(
        observation_id(item.evidence_id, index)
        for item in assessed.evidence
        for index, _ in enumerate(item.support, 1)
    )
    assert tuple(item.observation_id for item in core.observations) == expected
    for claim, record in zip(core.evidence_claims, assessed.evidence):
        assert len(claim.observation_refs) == len(record.support)
        assert claim.statement == record.claim  # AD-05: mapped, not renamed


@pytest.mark.parametrize(("case", "readiness"), SAVED_CASES)
def test_every_observation_of_every_saved_core_is_attributed_by_code(
    case: str, readiness: EvidenceReadiness
):
    core, _ = _saved_core(case)
    sources = {source.source_id: source for source in core.sources}
    answer = (FIXTURES / f"{case}.response.json").read_text(encoding="utf-8")

    for observation in core.observations:
        source = sources[observation.source_ref]
        assert observation.attribution == build_attribution(
            source, observation.excerpt
        )
        assert (source.publisher or source.title) in observation.attribution
        # The model never wrote it, and could not have: the saved answer it gave
        # does not contain the attribution at all.
        assert observation.attribution not in answer


def test_a_claim_its_support_does_not_establish_is_floored_by_code():
    """The saved Target answer places the rejected claim at level 2 anyway."""

    core, _ = _saved_core("target_chair_support")
    claims = {claim.evidence_claim_id: claim for claim in core.evidence_claims}

    over_reach = claims["evidence-cornell-board-refresh"]
    assert over_reach.verdict is EvidenceDisposition.REJECTED
    assert over_reach.usable is False
    assert over_reach.strength == LADDER.bottom
    assert over_reach.ceiling == LADDER.bottom
    # And the assessment did say 2, so the floor is this stage's doing.
    saved = json.loads(
        (FIXTURES / "target_chair_support.response.json").read_text(encoding="utf-8")
    )
    placed = {item["evidence_claim_id"]: item for item in saved["claims"]}
    assert placed["evidence-cornell-board-refresh"]["strength_level"] == 2

    supported = claims["evidence-cornell-support"]
    assert supported.usable is True
    assert supported.strength == LADDER.at(2)


def test_a_qualified_claim_carries_the_limitation_its_own_rationale_named():
    core, _ = _saved_core("lucid_workforce_reduction")
    claims = {claim.evidence_claim_id: claim for claim in core.evidence_claims}

    qualified = claims["evidence-lucid-workforce"]
    assert qualified.verdict is EvidenceDisposition.QUALIFIED
    assert qualified.usable is True
    assert qualified.caveats == (qualified.verdict_rationale,)
    # Two observations from one source: the positional IDs go past 1.
    assert qualified.observation_refs == (
        "obs-evidence-lucid-workforce-1",
        "obs-evidence-lucid-workforce-2",
    )
    assert qualified.source_refs == ("source-cnbc-lucid-layoffs",)


def test_a_figure_observation_carries_the_figure_and_its_provenance():
    core, _ = _saved_core("ups_cold_chain_investment")
    observations = {item.observation_id: item for item in core.observations}

    figure = observations["obs-evidence-ups-investment-1"]
    assert figure.kind is ObservationKind.FIGURE
    assert figure.figure is not None
    assert figure.figure.value == "$48 million"
    assert figure.figure.unit == "USD"
    assert figure.figure.provenance is FigureProvenance.THIRD_PARTY
    assert figure.figure.as_of is not None
    assert figure.figure.as_of.isoformat() == "2026-06-22"
    assert figure.is_third_party_assertion is True
    assert figure.as_entity()["figure"]["figure_provenance"] == "third_party"


def test_the_saved_set_carries_its_uncertainties_into_the_core():
    core, assessed = _saved_core("lucid_workforce_reduction")

    assert core.uncertainties == assessed.uncertainties
    assert [item.uncertainty_id for item in core.uncertainties] == [
        "uncertainty-lucid-savings"
    ]
    claim_ids = {claim.evidence_claim_id for claim in core.evidence_claims}
    for item in core.uncertainties:
        assert set(item.evidence_ids) <= claim_ids


# ===========================================================================
# The core's own rules (E-02, E-03, E-04)
# ===========================================================================


def _observation(**overrides: Any) -> SourceObservation:
    fields: dict[str, Any] = dict(
        observation_id="obs-evidence-1-1",
        signal_id="signal-299",
        source_ref="source-1",
        kind=ObservationKind.QUOTE,
        excerpt="The plant recalled one component batch.",
        attribution="Example Press reports: The plant recalled one component batch.",
        is_third_party_assertion=False,
    )
    fields.update(overrides)
    return SourceObservation(**fields)


def _claim(**overrides: Any) -> EvidenceClaim:
    fields: dict[str, Any] = dict(
        evidence_claim_id="evidence-1",
        statement="The plant recalled one component batch.",
        observation_refs=("obs-evidence-1-1",),
        source_refs=("source-1",),
        verdict=EvidenceDisposition.ACCEPTED,
        verdict_rationale="The excerpt states the recall.",
        scope="one plant, in June 2026",
        strength=LADDER.at(2),
        ceiling=LADDER.at(2),
    )
    fields.update(overrides)
    return EvidenceClaim(**fields)


def _core(**overrides: Any) -> EvidenceCore:
    fields: dict[str, Any] = dict(
        core_id="core-299",
        version=1,
        signal_ids=("signal-299",),
        research_artifact_refs=(("artifact-299", "sha256:" + "b" * 64),),
        sources=(_source(),),
        observations=(_observation(),),
        evidence_claims=(_claim(),),
        readiness=EvidenceReadiness.READY,
    )
    fields.update(overrides)
    return EvidenceCore(**fields)


def test_a_core_whose_claim_cites_a_missing_observation_is_refused():
    with pytest.raises(EvidenceCoreError, match="not in the core"):
        _core(evidence_claims=(_claim(observation_refs=("obs-nowhere-1",)),))


def test_a_claim_that_cites_a_source_no_observation_carries_is_refused():
    with pytest.raises(EvidenceCoreError, match="keeps the two consistent"):
        _core(
            sources=(_source(), _source("source-2", locator="https://other.test/a")),
            evidence_claims=(_claim(source_refs=("source-1", "source-2")),),
        )


def test_a_claim_with_no_observation_at_all_is_fabrication():
    with pytest.raises(EvidenceCoreError, match="I-04"):
        _claim(observation_refs=())


def test_a_ceiling_above_the_strength_it_caps_is_refused():
    with pytest.raises(EvidenceCoreError, match="never be above it"):
        _claim(strength=LADDER.at(2), ceiling=LADDER.at(3))


def test_a_qualified_claim_with_no_caveat_is_an_acceptance():
    with pytest.raises(EvidenceCoreError, match="caveat"):
        _claim(verdict=EvidenceDisposition.QUALIFIED, caveats=())


def test_an_observation_that_is_a_figure_without_one_is_refused():
    with pytest.raises(EvidenceCoreError, match="requires one for a figure"):
        _observation(kind=ObservationKind.FIGURE)


def test_an_observation_that_is_not_a_figure_may_not_carry_one():
    with pytest.raises(EvidenceCoreError, match="admits one for nothing else"):
        _observation(
            figure=Figure(value="48", provenance=FigureProvenance.OWN),
        )


def test_an_observation_with_no_attribution_is_a_fact_with_no_provenance():
    with pytest.raises(EvidenceCoreError, match="I-03"):
        _observation(attribution="   ")


def test_two_strengths_on_two_ladders_are_not_comparable():
    other = StrengthLadder(ladder_id="client-ladder", levels=("seen", "confirmed"))
    with pytest.raises(EvidenceCoreError, match="one ladder"):
        LADDER.lower_of(LADDER.at(2), other.at(1))


def test_one_level_is_not_a_ladder():
    with pytest.raises(EvidenceCoreError, match="not a ladder"):
        StrengthLadder(ladder_id="thin", levels=("reported",))


def test_the_ceiling_is_the_lower_of_the_client_ceiling_and_the_strength():
    artifact = _artifact(
        evidence=(
            _record(disposition=EvidenceDisposition.ACCEPTED, rationale="Stated."),
        ),
    )
    assessor = ExtendedEvidenceAssessor(_Answering(strength_level=4), ladder=LADDER)
    # The record is already assessed, so `assess_artifact` asks nobody: the
    # extension is obtained the same way this stage obtains it in the wrap.
    assessment = _extension(assessor, artifact)

    core = build_evidence_core(
        artifact=artifact,
        assessment=assessment,
        core_id="core-ceiling",
        ladder=LADDER,
        client_ceiling=LADDER.at(2),
    )

    claim = core.evidence_claims[0]
    assert claim.strength == LADDER.at(4)
    assert claim.ceiling == LADDER.at(2)


def test_a_core_with_no_client_ceiling_is_capped_by_the_evidence_alone():
    artifact = _artifact(
        evidence=(
            _record(disposition=EvidenceDisposition.ACCEPTED, rationale="Stated."),
        ),
    )
    assessor = ExtendedEvidenceAssessor(_Answering(strength_level=3), ladder=LADDER)

    core = build_evidence_core(
        artifact=artifact,
        assessment=_extension(assessor, artifact),
        core_id="core-no-ceiling",
        ladder=LADDER,
    )

    assert core.evidence_claims[0].ceiling == LADDER.at(3)


def test_a_usable_claim_the_assessment_never_placed_is_refused():
    """An artifact assessed elsewhere arrives usable and unclassified."""

    artifact = _artifact(
        evidence=(
            _record(
                disposition=EvidenceDisposition.ACCEPTED,
                rationale="Somebody else's assessor said so.",
            ),
        ),
    )

    with pytest.raises(EvidenceCoreError, match="never placed it on the ladder"):
        build_evidence_core(
            artifact=artifact,
            assessment=None,
            core_id="core-unplaced",
            ladder=LADDER,
        )


def test_a_core_carries_the_contradictions_of_the_artifact_it_wraps():
    records = (
        _record("evidence-1"),
        _record("evidence-2", claim="The recall covered two batches."),
    )
    artifact = _artifact(
        evidence=records,
        contradictions=(
            Contradiction(
                contradiction_id="contradiction-1",
                resolution=ResolutionStatus.UNRESOLVED,
                description="The two records state the batch count differently.",
                evidence_ids=("evidence-1", "evidence-2"),
            ),
        ),
    )
    assessed, assessor = _assess(artifact, _Answering())

    core = build_evidence_core(
        artifact=assessed,
        assessment=assessor.assessment,
        core_id="core-contradiction",
        ladder=LADDER,
    )

    assert [item.contradiction_id for item in core.contradictions] == [
        "contradiction-1"
    ]
    # An unresolved contradiction among usable claims is a real finding, and the
    # readiness the assessor derived says so rather than the core hiding it.
    assert core.readiness is EvidenceReadiness.NEEDS_REVIEW
    assert len(core.usable_claims) == 2


def _extension(
    assessor: ExtendedEvidenceAssessor, artifact: NormalizedResearchArtifact
) -> Optional[ExtendedAssessment]:
    """The extension for an artifact whose records are already assessed.

    ``assess_artifact`` only asks about records that need a verdict, so a test
    working with pre-assessed ones drives the assessor through the same request
    shape that module builds.
    """

    request = json.dumps({
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "claim": item.claim,
                "support": [ref.excerpt for ref in item.support],
            }
            for item in artifact.evidence
        ]
    })
    assessor.complete(instructions="", request=request)
    return assessor.assessment


# ===========================================================================
# The extended assessment: one call, wrapping the existing one
# ===========================================================================


def test_the_extended_assessment_is_one_call_and_the_existing_one():
    transport = _Answering()
    artifact = _artifact(
        evidence=(_record("evidence-1"), _record("evidence-2", claim="A second.")),
    )

    assessed, assessor = _assess(artifact, transport)

    assert len(transport.requests) == 1, "S-01 makes one assessment call"
    assert [item.disposition for item in assessed.evidence] == [
        EvidenceDisposition.ACCEPTED,
        EvidenceDisposition.ACCEPTED,
    ]
    assert assessed.assessor is not None
    assert assessed.readiness is EvidenceReadiness.READY
    # One response, two consumers: the verdicts went to `assess_artifact` and
    # the classification stayed with the assessor.
    assessment = assessor.assessment
    assert assessment is not None
    assert len(assessment.claims) == 2
    assert len(assessment.observations) == 2


def test_the_extension_rides_on_the_existing_judgment_instructions():
    transport = _Answering()
    _assess(_artifact(), transport)

    instructions = transport.instructions[0]
    assert instructions.startswith(JUDGMENT_INSTRUCTIONS)
    for asked in ("is_third_party_assertion", "strength_level", "scope"):
        assert asked in instructions
    request = json.loads(transport.requests[0])
    assert request["strength_ladder"]["ladder_id"] == LADDER.ladder_id
    assert len(request["strength_ladder"]["levels"]) == len(LADDER.levels)
    assert request["claims"][0]["observations"][0]["observation_id"] == (
        "obs-evidence-1-1"
    )


def test_a_structural_rejection_still_overrules_what_the_model_said():
    """`assess_artifact` never asks about a record it cannot assess, so the
    model's opinion of it never exists to be preferred."""

    transport = _Answering(disposition="accepted")
    artifact = _artifact(
        evidence=(
            _record("evidence-1"),
            _record("evidence-thin", excerpts=("The plant said so.", " ")),
        ),
    )

    assessed, assessor = _assess(artifact, transport)
    assert transport.requests, "the assessable record was still judged"
    core = build_evidence_core(
        artifact=assessed,
        assessment=assessor.assessment,
        core_id="core-structural",
        ladder=LADDER,
    )

    thin = next(
        claim
        for claim in core.evidence_claims
        if claim.evidence_claim_id == "evidence-thin"
    )
    # The model was never asked about it, so the model's "accepted" never
    # existed for the structural rejection to overrule.
    assert thin.verdict is EvidenceDisposition.REJECTED
    assert "not assessable" in thin.verdict_rationale.casefold()
    assert thin.strength == LADDER.bottom
    assert thin.ceiling == LADDER.bottom
    assert thin.scope != core.evidence_claims[0].scope
    # Its readable excerpt is still in the core, because the core is what the
    # run found; the blank one becomes no observation, because E-02 needs one.
    assert thin.observation_refs == ("obs-evidence-thin-1",)
    unclassified = core.observations[-1]
    assert unclassified.observation_id == "obs-evidence-thin-1"
    assert unclassified.kind is ObservationKind.OTHER
    assert unclassified.is_third_party_assertion is False


def test_a_record_with_nothing_readable_in_it_enters_the_core_not_at_all():
    artifact = _artifact(
        evidence=(_record("evidence-1"), _record("evidence-blank", excerpts=(" ",))),
    )

    assessed, assessor = _assess(artifact, _Answering())
    core = build_evidence_core(
        artifact=assessed,
        assessment=assessor.assessment,
        core_id="core-blank",
        ladder=LADDER,
    )

    assert [claim.evidence_claim_id for claim in core.evidence_claims] == [
        "evidence-1"
    ]
    assert [item.observation_id for item in core.observations] == [
        "obs-evidence-1-1"
    ]
    # The artifact the core references by digest still records the retrieval.
    assert {item.evidence_id for item in assessed.evidence} == {
        "evidence-1",
        "evidence-blank",
    }


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        (_Answering(omit_claim=True), "classified no claim"),
        (_Answering(omit_observation=True), "classified no observation"),
        (_Answering(invent_observation=True), "does not contain"),
        (_Answering(strength_level=9), "strength level 9"),
        (_Answering(raw="not json"), "assessment contract"),
        (_Answering(raw=json.dumps({"claims": [], "observations": []})), "contract"),
    ],
)
def test_an_assessment_that_does_not_satisfy_the_contract_promotes_nothing(
    transport: _Answering, expected: str
):
    artifact = _artifact(
        evidence=(_record("evidence-1"), _record("evidence-2", claim="A second.")),
    )
    assessor = ExtendedEvidenceAssessor(transport, ladder=LADDER)

    with pytest.raises(EvidenceAssessmentError):
        assess_artifact(artifact, transport=assessor)

    assert assessor.assessment is None
    assert expected in (assessor.failure or "")


def test_an_assessment_the_provider_refused_is_never_a_verdict():
    transport = _Answering(error=RuntimeError("the provider did not answer"))
    assessor = ExtendedEvidenceAssessor(transport, ladder=LADDER)

    with pytest.raises(EvidenceAssessmentError):
        assess_artifact(_artifact(), transport=assessor)

    assert assessor.assessment is None


# ===========================================================================
# The research wrap (§1, Seam)
# ===========================================================================


@dataclass(frozen=True)
class _Run:
    """One run's worth of real context, for the stage to execute against."""

    root: Path
    strategy: Any
    assignment: Any
    run: Any
    request: Any
    run_dir: Path
    audience: Any

    @property
    def signal_id(self) -> str:
        return self.request.signal_id

    @property
    def now(self) -> datetime:
        return self.request.requested_at + timedelta(seconds=2)


def _run(tmp_path: Path) -> _Run:
    strategy = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    signal = dict(legacy._RAW_SIGNAL)
    assignment = from_jsonl_signal(
        signal,
        strategy_ref=legacy._STRATEGY_STUB.strategy_id,
        strategy_version=legacy._STRATEGY_STUB.strategy_version,
        submitted_at=datetime.now(timezone.utc),
    )
    run = RunContext.from_assignment(
        assignment, ExecutionMode.DRY_RUN, configuration_identity=strategy.identity
    )
    request = build_research_request(
        run, assignment, signal, strategy.research, now=datetime.now(timezone.utc)
    )
    return _Run(
        root=tmp_path,
        strategy=strategy,
        assignment=assignment,
        run=run,
        request=request,
        run_dir=tmp_path / assignment.assignment_id / "runs" / run.run_id,
        audience=strategy.decision_lens_editorial.select_audience(
            assignment.target_audience
        ),
    )


def _retrieve(
    context: _Run,
    *,
    provider: Optional[Any] = None,
    transport: Optional[Any] = None,
    budget: Optional[Any] = None,
):
    return retrieve_evidence_core(
        provider=provider or DeterministicFakeResearchProvider(),
        request=context.request,
        run_dir=context.run_dir,
        identity=context.strategy.identity,
        run_started_at=context.run.started_at,
        now=context.now,
        transport=transport or _Answering(),
        ladder=LADDER,
        core_id=f"core-{context.assignment.assignment_id}",
        client_ceiling=CLIENT_CEILING,
        budget=budget,
    )


def test_a_selected_signal_becomes_a_core_over_the_real_adapter(tmp_path: Path):
    context = _run(tmp_path)

    build = _retrieve(context)

    assert build.continues is True
    assert build.outcome is None
    core = build.core
    assert core is not None
    assert core.readiness is EvidenceReadiness.READY
    assert len(core.usable_claims) == 1
    assert (context.run_dir / "research.json").exists()
    # The core wraps the artifact the lifecycle persisted, by ID and digest.
    assert build.research is not None
    assert core.research_artifact_refs == (
        (build.research.artifact_id, research_artifact_digest(build.research)),
    )


def test_a_retrieval_that_produced_no_artifact_skips_the_signal(tmp_path: Path):
    context = _run(tmp_path)

    build = _retrieve(
        context,
        provider=DeterministicFakeResearchProvider(FakeResearchScenario.UNAVAILABLE),
    )

    assert build.core is None
    assert build.outcome is not None
    assert build.outcome.outcome is ArpOutcome.SKIP
    assert build.outcome.state_code is StateCode.RESEARCH_FAILED
    assert build.outcome.scope is OutcomeScope.SIGNAL
    assert build.outcome.scope_key == context.signal_id
    assert reason_category(build.outcome.state_code) is ReasonCategory.PROVIDER


def test_an_assessment_that_failed_is_a_skip_and_not_thin_evidence(tmp_path: Path):
    context = _run(tmp_path)

    build = _retrieve(
        context, transport=_Answering(error=RuntimeError("no answer"))
    )

    assert build.core is None
    assert build.outcome is not None
    assert build.outcome.state_code is StateCode.EVIDENCE_ASSESSMENT_FAILED
    assert build.outcome.state_code is not StateCode.NO_USABLE_EVIDENCE_CLAIM
    assert reason_category(build.outcome.state_code) is ReasonCategory.PROVIDER
    # Nothing was promoted, and the retrieval was not thrown away.
    assert (context.run_dir / "research.json").exists()


def test_a_core_with_no_usable_claim_is_written_and_the_signal_skipped(
    tmp_path: Path,
):
    context = _run(tmp_path)

    build = _retrieve(context, transport=_Answering(disposition="rejected"))

    assert build.core is not None, "the core is the evidence of what was found"
    assert build.core.usable_claims == ()
    assert build.continues is False
    assert build.outcome is not None
    assert build.outcome.state_code is StateCode.NO_USABLE_EVIDENCE_CLAIM
    # This one *is* about the material, so it is counted as evidence.
    assert reason_category(build.outcome.state_code) is ReasonCategory.EVIDENCE


def test_the_release_one_readiness_gate_is_not_this_stages(tmp_path: Path):
    """Production stops a run that is not READY and loses the retrieval. S-01
    records readiness and lets the ARP decide (Step 2 §1)."""

    context = _run(tmp_path)

    build = _retrieve(context, transport=_Answering(disposition="rejected"))

    assert build.core is not None
    assert build.core.readiness is EvidenceReadiness.INSUFFICIENT
    envelope = load_research_envelope(
        context.root, context.signal_id, context.run.run_id
    )
    with pytest.raises(ResearchGateError, match="not ready"):
        validate_research_envelope(
            envelope,
            run_id=context.run.run_id,
            assignment_id=context.assignment.assignment_id,
            signal_id=context.signal_id,
            identity=context.strategy.identity,
            run_started_at=context.run.started_at,
            now=context.now,
        )


def test_a_refused_call_is_never_made_and_the_signal_is_skipped(tmp_path: Path):
    context = _run(tmp_path)
    budget = RunCallBudget(1)
    budget.spend()
    provider = DeterministicFakeResearchProvider()

    build = _retrieve(context, provider=provider, budget=ArpCallBudget(budget))

    assert provider.requests == [], "the refused call is not made"
    assert build.core is None
    assert build.outcome is not None
    assert build.outcome.state_code is StateCode.BUDGET_EXHAUSTED


def test_the_stage_spends_one_call_for_the_assessment(tmp_path: Path):
    context = _run(tmp_path)
    budget = RunCallBudget(4)

    build = _retrieve(context, budget=ArpCallBudget(budget))

    assert build.continues is True
    assert budget.used == 1


# ===========================================================================
# The relevance screen (acceptance evidence 2)
# ===========================================================================


def _instructions() -> DecisionLensInstructions:
    """The profile identity the lifecycle expects, with a fixed instruction text.

    Deliberately not the maintained file: these tests are about how the
    disposition is routed, and pinning the text here keeps them from moving
    whenever the profile is revised.
    """

    return DecisionLensInstructions(
        instruction_id="never-blank-decision-lens",
        profile_id=RELEASE1_LENS_PROFILE.lens_profile_id,
        profile_version=RELEASE1_LENS_PROFILE.lens_profile_version,
        version="1.0",
        instructions="Judge relevance and claim mode for the audience. JSON only.",
    )


def _screen(
    context: _Run,
    build: Any,
    lens: _Lens,
    *,
    counters: Optional[AttemptCounterLedger] = None,
    budget: Optional[Any] = None,
) -> RelevanceScreen:
    return screen_relevance(
        core=build.core,
        research=build.research,
        evaluator=DecisionLensEvaluator(transport=lens, instructions=_instructions()),
        strategy_view=context.strategy.decision_lens_editorial,
        audience=context.audience,
        identity=context.strategy.identity,
        lens_profile=RELEASE1_LENS_PROFILE,
        run_id=context.run.run_id,
        assignment_id=context.assignment.assignment_id,
        signal_id=context.signal_id,
        run_dir=context.run_dir,
        counters=counters or AttemptCounterLedger(),
        budget=budget,
    )


def test_a_proceed_disposition_lets_the_signal_go_forward(tmp_path: Path):
    context = _run(tmp_path)
    build = _retrieve(context)
    lens = _Lens()

    screen = _screen(context, build, lens)

    assert lens.calls == 1, "the relevance screen runs exactly once"
    assert screen.continues is True
    assert screen.outcome is None
    assessment = screen.assessment
    assert assessment is not None
    assert assessment.disposition is DecisionDisposition.PROCEED
    assert assessment.requested_gaps == ()
    assert assessment.core_ref == build.core.core_id
    assert (context.run_dir / "decision.json").exists()
    assert assessment.decision.path.endswith("decision.json")
    assert assessment.decision.digest.startswith("sha256:")


@pytest.mark.parametrize("disposition", ["revise", "hold"])
def test_relevance_revise_or_hold_routes_to_enrichment(
    tmp_path: Path, disposition: str
):
    """R-1: not a wait. The REPLAN the current engine does not have."""

    context = _run(tmp_path)
    build = _retrieve(context)

    screen = _screen(context, build, _Lens(disposition=disposition))

    assert screen.replans is True
    outcome = screen.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.REPLAN
    assert outcome.state_code is StateCode.RELEVANCE_NOT_ESTABLISHED
    assert outcome.route_target == "S-03"
    assert outcome.counter == "L_enrich"
    assert (outcome.attempt, outcome.limit) == (1, 2)
    assert outcome.scope is OutcomeScope.SIGNAL
    # The route carries what enrichment is asked to close.
    assessment = screen.assessment
    assert assessment is not None
    assert RequestedGapKind.EVIDENCE in assessment.requested_gaps
    assert assessment.as_entity()["requested_gaps"] == [
        gap.value for gap in assessment.requested_gaps
    ]


def test_an_unmet_audience_connection_asks_for_a_reader_connection_gap(
    tmp_path: Path,
):
    context = _run(tmp_path)
    build = _retrieve(context)

    screen = _screen(
        context,
        build,
        _Lens(disposition="revise", relevance="indirect", sufficiency="sufficient"),
    )

    assessment = screen.assessment
    assert assessment is not None
    # Direct-claim mode with indirect relevance has not met its own bar, and the
    # evidence was sufficient, so the gap is the reader connection alone.
    assert assessment.requested_gaps == (RequestedGapKind.READER_CONNECTION,)


def test_the_enrichment_route_ends_in_a_skip_once_l_enrich_is_gone(
    tmp_path: Path,
):
    context = _run(tmp_path)
    build = _retrieve(context)
    counters = AttemptCounterLedger(limits={"L_enrich": 1})
    # The attempt an earlier `revise` would have spent. The ledger is the run's,
    # and it is never reset inside one (§5.3).
    counters.route(
        source=STAGE,
        cause=ENRICHMENT_ROUTE_CAUSE,
        scope_key=context.signal_id,
        state_code=StateCode.RELEVANCE_NOT_ESTABLISHED,
    )

    screen = _screen(context, build, _Lens(disposition="revise"), counters=counters)

    outcome = screen.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.RELEVANCE_NOT_ESTABLISHED
    assert outcome.route_target is None
    assert outcome.exhausted is True
    assert screen.replans is False


@pytest.mark.parametrize(
    ("lens", "state"),
    [
        (_Lens(disposition="reject"), StateCode.SIGNAL_NOT_RELEVANT),
        (
            _Lens(disposition="revise", relevance="irrelevant"),
            StateCode.SIGNAL_NOT_RELEVANT,
        ),
        (
            _Lens(disposition="insufficient_evidence"),
            StateCode.RELEVANCE_EVIDENCE_INSUFFICIENT,
        ),
    ],
)
def test_the_terminal_dispositions_skip_the_signal(
    tmp_path: Path, lens: _Lens, state: StateCode
):
    context = _run(tmp_path)
    build = _retrieve(context)

    screen = _screen(context, build, lens)

    outcome = screen.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is state
    assert outcome.counter is None, "a terminal state spends no counter"
    # The judgment is still recorded: a skipped signal's screen is evidence too.
    assert screen.assessment is not None
    assert screen.assessment.requested_gaps == ()


def test_a_screen_that_produced_no_judgment_is_a_skip_and_not_a_stop(
    tmp_path: Path,
):
    context = _run(tmp_path)
    build = _retrieve(context)

    screen = _screen(
        context, build, _Lens(error=RuntimeError("the lens provider refused"))
    )

    assert screen.assessment is None
    outcome = screen.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.RELEVANCE_SCREEN_FAILED
    assert reason_category(outcome.state_code) is ReasonCategory.PROVIDER
    assert not (context.run_dir / "decision.json").exists()


def test_a_refused_call_stops_the_screen_before_the_lens(tmp_path: Path):
    context = _run(tmp_path)
    build = _retrieve(context)
    budget = RunCallBudget(1)
    budget.spend()
    lens = _Lens()

    screen = _screen(context, build, lens, budget=ArpCallBudget(budget))

    assert lens.calls == 0
    assert screen.outcome is not None
    assert screen.outcome.state_code is StateCode.BUDGET_EXHAUSTED


def test_the_screen_judges_the_core_the_run_built(tmp_path: Path):
    context = _run(tmp_path)
    build = _retrieve(context)
    other = _artifact()

    with pytest.raises(RelevanceScreenError, match="the evidence that core holds"):
        screen_relevance(
            core=build.core,
            research=other,
            evaluator=DecisionLensEvaluator(
                transport=_Lens(), instructions=_instructions()
            ),
            strategy_view=context.strategy.decision_lens_editorial,
            audience=context.audience,
            identity=context.strategy.identity,
            lens_profile=RELEASE1_LENS_PROFILE,
            run_id=context.run.run_id,
            assignment_id=context.assignment.assignment_id,
            signal_id=context.signal_id,
            run_dir=context.run_dir,
            counters=AttemptCounterLedger(),
        )


# ===========================================================================
# AD-08 and AD-09: what the boundary receives, and what it does not
# ===========================================================================


@pytest.mark.parametrize(
    ("claim_mode", "transfer", "relevance", "restrictions"),
    [
        (
            "direct_audience_claim",
            AudienceTransfer.DIRECT_AUDIENCE,
            "direct",
            (),
        ),
        (
            "bounded_external_case",
            AudienceTransfer.BOUNDED_EXTERNAL_CASE,
            "indirect",
            ("The external outcome is not asserted for the audience.",),
        ),
    ],
)
def test_the_claim_mode_becomes_the_audience_transfer_the_boundary_reads(
    tmp_path: Path,
    claim_mode: str,
    transfer: AudienceTransfer,
    relevance: str,
    restrictions: tuple[str, ...],
):
    """AD-08: E-08's transfer field reuses the meaning of #58's claim mode."""

    context = _run(tmp_path)
    build = _retrieve(context)

    screen = _screen(
        context,
        build,
        _Lens(
            claim_mode=claim_mode, relevance=relevance, restrictions=restrictions
        ),
    )

    assert screen.continues is True
    assessment = screen.assessment
    assert assessment is not None
    assert assessment.audience_transfer is transfer
    boundary = assessment.for_boundary()
    assert boundary.audience_transfer is transfer
    assert boundary.relevance is BusinessAudienceRelevance(relevance)
    assert [basis.basis_type for basis in boundary.relevance_bases] == [
        AudienceRelevanceBasisType.DIRECT_AUDIENCE_EVIDENCE
    ]


def test_the_angle_fields_are_hints_and_reach_no_later_stage(tmp_path: Path):
    """AD-09, made structural: there is nowhere in BoundaryInput to put one."""

    context = _run(tmp_path)
    build = _retrieve(context)

    screen = _screen(context, build, _Lens())
    assessment = screen.assessment
    assert assessment is not None

    assert assessment.hints.supported_editorial_angle == ANGLE
    assert assessment.hints.defensible_perspective == DEFENSIBLE
    boundary = json.dumps(assessment.for_boundary().as_entity())
    assert ANGLE not in boundary
    assert DEFENSIBLE not in boundary

    entity = assessment.as_entity()
    assert entity["hints"]["consumed_downstream"] is False
    assert ANGLE not in json.dumps(entity["boundary_input"])
    # And the decision artifact still carries them, so nothing was deleted from
    # the #58 contract to achieve it.
    assert ANGLE in (context.run_dir / "decision.json").read_text(encoding="utf-8")


# ===========================================================================
# The public ledger and the trace
# ===========================================================================


def test_every_state_this_stage_records_is_countable_in_the_public_ledger():
    for state in (
        StateCode.RESEARCH_FAILED,
        StateCode.EVIDENCE_ASSESSMENT_FAILED,
        StateCode.NO_USABLE_EVIDENCE_CLAIM,
        StateCode.RELEVANCE_SCREEN_FAILED,
        StateCode.RELEVANCE_NOT_ESTABLISHED,
        StateCode.SIGNAL_NOT_RELEVANT,
        StateCode.RELEVANCE_EVIDENCE_INSUFFICIENT,
    ):
        assert isinstance(reason_category(state), ReasonCategory)
    # Not one of them is free text, and the three that are conditions of the
    # machinery are not counted as editorial reasons.
    assert reason_category(StateCode.RESEARCH_FAILED) is ReasonCategory.PROVIDER
    assert (
        reason_category(StateCode.NO_USABLE_EVIDENCE_CLAIM) is ReasonCategory.EVIDENCE
    )
    assert (
        reason_category(StateCode.SIGNAL_NOT_RELEVANT) is ReasonCategory.CONTRACT_FIT
    )


def test_the_trace_shows_the_core_and_the_relevance_reference(tmp_path: Path):
    """The entities at the paths §2.3 gives S-01, and the record that made them."""

    context = _run(tmp_path)
    build = _retrieve(context)
    screen = _screen(context, build, _Lens(disposition="revise"))
    assert build.core is not None
    assert screen.assessment is not None

    workspace = RunWorkspace.create(tmp_path / "editorial_runs", context.run.run_id)
    core_entry = workspace.write_entity(
        stage=STAGE,
        relative_path="signal/core/core.v1.json",
        entity_type="E-04",
        entity_id=build.core.core_id,
        payload=build.core.as_entity(),
        version=1,
    )
    relevance_entry = workspace.write_entity(
        stage=STAGE,
        relative_path="signal/relevance.ref.json",
        entity_type="E-04.relevance_ref",
        entity_id=screen.assessment.assessment_id,
        payload=screen.assessment.as_entity(),
    )
    started = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    trace = workspace.write_stage_record(
        StageRecord(
            run_id=context.run.run_id,
            seq=1,
            stage=STAGE,
            scope_key=context.signal_id,
            started_at=started,
            ended_at=started + timedelta(seconds=4),
            created_by=StageAttribution(
                stage=STAGE, component="evidence-core", decider=DeciderKind.MODEL
            ),
            outputs=tuple(
                EntityRef(
                    entity_type=entry.entity_type,
                    entity_id=entry.entity_id,
                    version=entry.version,
                    digest=entry.digest,
                )
                for entry in (core_entry, relevance_entry)
            ),
            outcomes=(screen.outcome,) if screen.outcome is not None else (),
            status=StageStatus.COMPLETED,
        )
    )

    core_body = json.loads(
        (workspace.run_dir / "signal/core/core.v1.json").read_text(encoding="utf-8")
    )
    assert core_body["entity_type"] == "E-04"
    assert core_body["version"] == 1
    assert core_body["evidence_claims"][0]["strength"]["ladder_id"] == "K-LAD-01"
    assert core_body["evidence_claims"][0]["ceiling"]["level"] <= (
        core_body["evidence_claims"][0]["strength"]["level"]
    )
    assert core_body["observations"][0]["attribution"]

    relevance_body = json.loads(
        (workspace.run_dir / "signal/relevance.ref.json").read_text(encoding="utf-8")
    )
    assert relevance_body["entity_type"] == "E-04.relevance_ref"
    assert relevance_body["boundary_input"]["audience_transfer"] == "direct_audience"
    assert relevance_body["decision"]["digest"].startswith("sha256:")

    reloaded = StageRecord.from_dict(
        json.loads((workspace.run_dir / trace.path).read_text(encoding="utf-8"))
    )
    assert reloaded.stage == STAGE
    assert [ref.entity_type for ref in reloaded.outputs] == [
        "E-04",
        "E-04.relevance_ref",
    ]
    # The REPLAN is accepted by the trace because the route is declared (§5.3).
    assert [outcome.route_target for outcome in reloaded.outcomes] == ["S-03"]
