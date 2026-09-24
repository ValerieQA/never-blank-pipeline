"""Issue #300: S-02 describes the material and S-03 closes what blocks a decision.

SL-3's acceptance evidence for the third and fourth stages, as scenarios:

1. **on the fixed signal set** (``tests/fixtures/evidence_core_299/``, the three
   saved CNBC research artifacts NB-03b built its cores from), every positive
   feature has references that resolve to claims the core holds — and an item
   whose references do not hold is dropped and recorded as a ``DEGRADE``,
   never retried;
2. **every enrichment ends with a recorded stop reason**: a gap closes against
   the core version that closed it, and every gap left open is abandoned with
   one of E-07's four reasons — the counter ran out, the budget ran out, the
   search found nothing, or the core already held it;
3. **calls per stage are recorded**: one for S-02, two per enrichment round,
   and none at all for an enrichment with no blocking gap.

And the properties the two stages rest on: no label is produced (I-10), a
calculation is arithmetic code does over usable figures the core holds, a
positional asset comes only from an approved position of the Client Contract, a
note that blocks no decision opens no gap, a gap is met only by the material it
names, a gap closes only on material of the kind it asks for and only in a round
that carried its query — in the core's closure list as much as in E-07 — the
client's excluded sources survive the request's directive bound, and a round is
committed whole or not at all so that the core and its description are never
two different versions.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest

from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.enrichment import (
    ENRICHMENT_COUNTER,
    MAX_DIRECTIVES,
    Enrichment,
    EnrichmentError,
    Gap,
    GapBlocks,
    GapStatus,
    StopReason,
    enrich,
    open_gaps,
)
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    ExtendedEvidenceAssessor,
    Figure,
    FigureProvenance,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
    build_evidence_core,
)
from src.editorial_core.material_features import (
    MATERIAL_INSTRUCTIONS,
    AssetClass,
    AssetKind,
    CalculationMethod,
    ConfidenceLevel,
    FeatureFigureProvenance,
    Freshness,
    GapKind,
    MaterialFeature,
    MaterialFeaturesError,
    MaterialNote,
    NoteBlock,
    Quantity,
    describe_material,
    read_amount,
)
from src.editorial_core.relevance_screen import ENRICHMENT_ROUTE_CAUSE, RequestedGapKind
from src.research.assessment import assess_artifact
from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
)
from src.research.provider import (
    CompleteResearchResult,
    FailedResearchResult,
    FreshnessRequirement,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    RetrievalStatus,
    SourceDirective,
    SourceDirectiveKind,
    SourceOrigin,
    SourcePriority,
    SourceRetrievalOutcome,
)
from src.run.call_budget import RunCallBudget
from src.run.call_budget_arp import ArpCallBudget
from src.run.run_summary import ReasonCategory, reason_category
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext

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

CLIENT_CEILING = LADDER.at(3)

FIXTURES = Path("tests/fixtures/evidence_core_299")

#: The fixed signal set: the three saved research artifacts of NB-03b.
SAVED_CASES = (
    "target_chair_support",
    "ups_cold_chain_investment",
    "lucid_workforce_reduction",
)

NOW = datetime(2026, 6, 22, 17, 0, tzinfo=timezone.utc)

RUN_ID = "3f9c1d7a-58b2-4e6c-9a1f-2d4b6e8c0a11"

SIGNAL = "signal-300"

#: An approved position of the Client Contract, as S-02 receives the list.
APPROVED_POSITION = "position-nb-automation-stance"

#: The client's source policy, as the run's own research request carries it:
#: one source it required, and one domain it prefers.
CLIENT_DIRECTIVES = (
    SourceDirective(
        directive_id="required-source-1",
        priority=SourcePriority.REQUIRED,
        kind=SourceDirectiveKind.URL,
        value="https://www.cnbc.com/2026/06/22/item.html",
    ),
    SourceDirective(
        directive_id="preferred-source-1",
        priority=SourcePriority.PREFERRED,
        kind=SourceDirectiveKind.DOMAIN,
        value="reuters.com",
        material=False,
    ),
)


# ===========================================================================
# Transports: a model that answers the request it was given
# ===========================================================================


class _Describing:
    """An S-02 description built from the request it was handed.

    It cites only claim IDs the request contains, so a test that wants an
    unheld reference has to ask for one — which is what keeps the reference
    check being tested rather than the fixture.
    """

    def __init__(
        self,
        *,
        positive: tuple[str, ...] = ("documented_case", "named_company"),
        figure_provenance: str = "third_party",
        freshness: str = "high",
        refs: Optional[tuple[str, ...]] = None,
        assets: tuple[dict[str, Any], ...] = (),
        notes: tuple[dict[str, Any], ...] = (),
        raw: Optional[str] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.positive = positive
        self.figure_provenance = figure_provenance
        self.freshness = freshness
        self.refs = refs
        self.assets = assets
        self.notes = notes
        self.raw = raw
        self.error = error
        self.calls = 0
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.raw is not None:
            return self.raw
        payload = json.loads(request)
        usable = [
            item["evidence_claim_id"]
            for item in payload["claims"]
            if item["verdict"] in {"accepted", "qualified"}
        ]
        cited = list(self.refs) if self.refs is not None else usable[:1]
        features = []
        for feature in MaterialFeature:
            if feature is MaterialFeature.FIGURE_PROVENANCE:
                value: Any = self.figure_provenance
                positive = self.figure_provenance != "none"
            elif feature is MaterialFeature.FRESHNESS:
                value = self.freshness
                positive = True
            else:
                value = feature.value in self.positive
                positive = bool(value)
            features.append({
                "feature": feature.value,
                "value": value,
                "confidence": "medium",
                "rationale": "Read off the cited excerpt.",
                "evidence_refs": cited if positive else [],
            })
        return json.dumps({
            "features": features,
            "assets": list(self.assets),
            "notes": list(self.notes),
        })


class _Answering:
    """An extended assessment that answers exactly the request it was given."""

    def __init__(
        self,
        *,
        strength_level: int = 2,
        figure: bool = False,
        disposition: str = "accepted",
    ) -> None:
        self.strength_level = strength_level
        self.figure = figure
        self.disposition = disposition
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        payload = json.loads(request)
        verdicts = []
        claims = []
        observations = []
        for item in payload["claims"]:
            identity = item["evidence_claim_id"]
            verdicts.append({
                "evidence_id": identity,
                "disposition": self.disposition,
                "rationale": "The cited excerpt states the claim.",
            })
            claims.append({
                "evidence_claim_id": identity,
                "scope": "The recorded case, as reported.",
                "strength_level": self.strength_level,
            })
            for observed in item["observations"]:
                observations.append({
                    "observation_id": observed["observation_id"],
                    "kind": "figure" if self.figure else "quote",
                    "is_third_party_assertion": False,
                    "figure": (
                        {
                            "value": "12 million",
                            "unit": "USD",
                            "as_of": None,
                            "provenance": "own",
                        }
                        if self.figure
                        else None
                    ),
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

    def complete(self, *, instructions: str, request: str) -> str:
        return self.payload


class _Model:
    """One transport, answering both calls a round makes.

    The stages reach the same provider; what separates the two calls is the
    instructions each carries, so the test separates them the same way.
    """

    def __init__(self, describe: _Describing, assess: _Answering) -> None:
        self.describe = describe
        self.assess = assess

    def complete(self, *, instructions: str, request: str) -> str:
        if instructions == MATERIAL_INSTRUCTIONS:
            return self.describe.complete(instructions=instructions, request=request)
        return self.assess.complete(instructions=instructions, request=request)


# ===========================================================================
# A provider that answers an enrichment search with new material
# ===========================================================================


class _Enriching:
    """One new source, one new claim, per search. Deterministic and offline."""

    def __init__(self, *, failing: bool = False) -> None:
        self.failing = failing
        self.requests: list[ResearchProviderRequest] = []

    def research(self, request: ResearchProviderRequest) -> Any:
        self.requests.append(request)
        number = len(self.requests)
        started = request.requested_at
        invocation = ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id="enrichment-fake",
                adapter_id="never-blank-enrichment-fake",
                adapter_version="1.0",
                invocation_id=f"33333333-3333-4333-8333-{number:012d}",
            ),
            started_at=started,
            completed_at=started + timedelta(seconds=1),
            attempt_count=1,
        )
        base = dict(
            request_run_id=request.run_id,
            request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id,
            invocation=invocation,
        )
        if self.failing:
            return FailedResearchResult(
                outcome=ResearchOperationOutcome.FAILED,
                source_outcomes=(),
                operation_failure=ProviderFailure(
                    code=ProviderFailureCode.EMPTY_RESULT,
                    message="Nothing matched the enrichment query.",
                    retryable=False,
                ),
                **base,
            )
        source_id = f"source-enrichment-{number}"
        url = f"https://enrichment.test/found-{number}"
        retrieved = SourceRetrievalOutcome(
            retrieval_id=f"retrieval-enrichment-{number}",
            directive_id=request.source_directives[0].directive_id,
            source_id=source_id,
            origin=SourceOrigin.PROVIDER_DISCOVERED,
            locator=url,
            status=RetrievalStatus.RETRIEVED,
            attempted_at=started,
            retrieved_at=started,
        )
        excerpt = f"A second outlet recorded the same filing, round {number}."
        artifact = NormalizedResearchArtifact(
            artifact_id=f"research-enrichment-{number}",
            run_id=request.run_id,
            assignment_id=request.assignment_id,
            signal_id=request.signal_id,
            configuration_identity=request.strategy.identity,
            created_at=started,
            sources=(
                NormalizedSource(
                    source_id=source_id,
                    locator=SourceLocator(kind=SourceLocatorKind.URL, value=url),
                    title=f"Enrichment source {number}",
                    publisher="Enrichment Press",
                    publication_time=PublicationTime(
                        status=PublicationTimeStatus.NOT_COLLECTED
                    ),
                    retrieved_at=started,
                ),
            ),
            evidence=(
                ExtractedEvidence(
                    evidence_id=f"evidence-enrichment-{number}",
                    claim=excerpt,
                    source_ids=(source_id,),
                    support=(
                        SupportReference(source_id=source_id, excerpt=excerpt),
                    ),
                    disposition=EvidenceDisposition.NOT_ASSESSED,
                ),
            ),
            readiness=EvidenceReadiness.INSUFFICIENT,
        )
        return CompleteResearchResult(
            outcome=ResearchOperationOutcome.COMPLETE,
            source_outcomes=(retrieved,),
            artifact=artifact,
            operation_failure=None,
            **base,
        )


# ===========================================================================
# Cores: the saved set, and hand-built ones for single properties
# ===========================================================================


def _saved_core(case: str) -> EvidenceCore:
    """One saved artifact, assessed through the real path and wrapped as E-04."""

    raw = (FIXTURES / f"{case}.artifact.json").read_text(encoding="utf-8")
    artifact = NormalizedResearchArtifact.model_validate_json(raw)
    assessor = ExtendedEvidenceAssessor(_Saved(case), ladder=LADDER)
    assessed = assess_artifact(artifact, transport=assessor)
    return build_evidence_core(
        artifact=assessed,
        assessment=assessor.assessment,
        core_id=f"core-{case}",
        ladder=LADDER,
        client_ceiling=CLIENT_CEILING,
    )


def _source(source_id: str = "source-1") -> NormalizedSource:
    return NormalizedSource(
        source_id=source_id,
        locator=SourceLocator(
            kind=SourceLocatorKind.URL, value=f"https://example.test/{source_id}"
        ),
        title="Recorded report",
        publisher="Example Press",
        publication_time=PublicationTime(
            status=PublicationTimeStatus.KNOWN, value=NOW - timedelta(days=1)
        ),
        retrieved_at=NOW,
    )


def _claim(
    index: int,
    *,
    figure: Optional[Figure] = None,
    verdict: EvidenceDisposition = EvidenceDisposition.ACCEPTED,
) -> tuple[SourceObservation, EvidenceClaim]:
    identity = f"evidence-{index}"
    observation = SourceObservation(
        observation_id=f"obs-{identity}-1",
        signal_id=SIGNAL,
        source_ref="source-1",
        kind=ObservationKind.FIGURE if figure is not None else ObservationKind.QUOTE,
        excerpt=f"The filing records item {index}.",
        attribution=f"Example Press reports: The filing records item {index}.",
        is_third_party_assertion=False,
        figure=figure,
    )
    return observation, EvidenceClaim(
        evidence_claim_id=identity,
        statement=f"The filing records item {index}.",
        observation_refs=(observation.observation_id,),
        source_refs=("source-1",),
        verdict=verdict,
        verdict_rationale="The cited excerpt states it.",
        scope="The filing, as recorded.",
        strength=LADDER.at(2),
        ceiling=LADDER.at(2),
    )


def _core(
    *,
    figures: tuple[Optional[Figure], ...] = (None,),
    verdicts: tuple[EvidenceDisposition, ...] = (),
    readiness: EvidenceReadiness = EvidenceReadiness.READY,
    core_id: str = "core-300",
) -> EvidenceCore:
    """A small core, built directly: E-04 is what the stages read."""

    pairs = [
        _claim(
            index,
            figure=figure,
            verdict=(
                verdicts[index - 1]
                if index - 1 < len(verdicts)
                else EvidenceDisposition.ACCEPTED
            ),
        )
        for index, figure in enumerate(figures, 1)
    ]
    return EvidenceCore(
        core_id=core_id,
        version=1,
        signal_ids=(SIGNAL,),
        research_artifact_refs=(("artifact-300", "sha256:" + "b" * 64),),
        sources=(_source(),),
        observations=tuple(observation for observation, _ in pairs),
        evidence_claims=tuple(claim for _, claim in pairs),
        readiness=readiness,
    )


def _strategy() -> Any:
    return StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    ).research


def _request(
    core: EvidenceCore,
    *,
    directives: Optional[tuple[SourceDirective, ...]] = None,
) -> ResearchProviderRequest:
    """The run's own research request, as S-03 receives it."""

    return ResearchProviderRequest(
        run_id=RUN_ID,
        assignment_id=core.signal_ids[0],
        signal_id=core.signal_ids[0],
        strategy=_strategy(),
        freshness=FreshnessRequirement(
            retrieved_not_before=NOW - timedelta(hours=2),
            allow_open_discovery=False,
        ),
        source_directives=CLIENT_DIRECTIVES if directives is None else directives,
        requested_at=NOW,
    )


def _blocking_note(
    kind: GapKind = GapKind.EVIDENCE, note_id: str = "note-1"
) -> MaterialNote:
    return MaterialNote(
        note_id=note_id,
        kind=kind,
        description="No second source records the filing.",
        blocks=NoteBlock("S-04", "whether the reading carries beyond one report"),
    )


def _enrich(
    core: EvidenceCore,
    *,
    notes: tuple[MaterialNote, ...] = (),
    requested_gaps: tuple[RequestedGapKind, ...] = (),
    assets: tuple[Any, ...] = (),
    provider: Optional[_Enriching] = None,
    request: Optional[ResearchProviderRequest] = None,
    transport: Optional[Any] = None,
    counters: Optional[AttemptCounterLedger] = None,
    budget: Optional[Any] = None,
) -> Any:
    described = describe_material(core=core, transport=_Describing())
    assert described.features is not None
    return enrich(
        core=core,
        features=described.features,
        assets=assets or described.assets,
        notes=notes,
        requested_gaps=requested_gaps,
        provider=provider or _Enriching(),
        request=request or _request(core),
        transport=transport or _Model(_Describing(), _Answering()),
        ladder=LADDER,
        counters=counters or AttemptCounterLedger(),
        now=NOW,
        client_ceiling=CLIENT_CEILING,
        budget=budget,
    )


# ===========================================================================
# S-02 on the fixed signal set (acceptance evidence 1)
# ===========================================================================


@pytest.mark.parametrize("case", SAVED_CASES)
def test_every_saved_core_is_described_by_all_twelve_features(case: str):
    described = describe_material(core=_saved_core(case), transport=_Describing())

    assert described.continues is True
    assert described.features is not None
    assert {item.feature for item in described.features.values} == set(MaterialFeature)


@pytest.mark.parametrize("case", SAVED_CASES)
def test_every_positive_feature_of_every_saved_core_has_references(case: str):
    """Acceptance evidence: on the fixed signal set, every positive feature
    has references, and every one of them resolves to a claim the core holds."""

    core = _saved_core(case)
    described = describe_material(core=core, transport=_Describing())

    assert described.features is not None
    positive = described.features.positive
    assert positive, "the fixed set describes something about every core"
    held = {claim.evidence_claim_id for claim in core.evidence_claims}
    usable = {claim.evidence_claim_id for claim in core.usable_claims}
    for item in positive:
        assert item.evidence_refs, f"{item.feature.value} is positive and cites nothing"
        assert set(item.evidence_refs) <= held
        assert set(item.evidence_refs) & usable


@pytest.mark.parametrize("case", SAVED_CASES)
def test_no_saved_description_produces_a_label(case: str):
    """I-10: no label lives in E-05, and there is no field for one."""

    described = describe_material(core=_saved_core(case), transport=_Describing())

    assert described.features is not None
    body = json.dumps(described.features.as_entity())
    assert "material_label" not in body
    assert "label" not in {item.feature.value for item in described.features.values}


def test_a_positive_feature_whose_reference_the_core_lacks_is_dropped():
    core = _core()
    described = describe_material(
        core=core, transport=_Describing(refs=("evidence-not-in-this-core",))
    )

    assert described.features is not None
    dropped = {item.identity for item in described.dropped}
    assert "documented_case" in dropped
    withdrawn = described.features.value_of(MaterialFeature.DOCUMENTED_CASE)
    assert withdrawn.value is False
    assert withdrawn.confidence.level is ConfidenceLevel.LOW
    assert withdrawn.evidence_refs == ()
    assert all(
        outcome.outcome is ArpOutcome.DEGRADE
        and outcome.state_code is StateCode.MATERIAL_WITHOUT_REFERENCE
        for outcome in described.outcomes
    )


def test_a_feature_grounded_only_in_a_rejected_claim_is_dropped():
    """E-03's usability rule reaching backwards: a description may sit beside a
    rejected claim, and may not stand on one alone."""

    core = _core(
        figures=(None, None),
        verdicts=(EvidenceDisposition.REJECTED, EvidenceDisposition.ACCEPTED),
    )
    described = describe_material(
        core=core, transport=_Describing(refs=("evidence-1",))
    )

    assert described.features is not None
    assert "documented_case" in {item.identity for item in described.dropped}

    beside = describe_material(
        core=core, transport=_Describing(refs=("evidence-1", "evidence-2"))
    )
    assert beside.dropped == ()


def test_a_description_the_model_did_not_answer_skips_the_signal():
    described = describe_material(core=_core(), transport=_Describing(raw="{}"))

    assert described.continues is False
    assert described.features is None
    assert [outcome.state_code for outcome in described.outcomes] == [
        StateCode.MATERIAL_DESCRIPTION_FAILED
    ]
    assert described.calls == 1, "the call was made and is counted"


def test_a_transport_that_refused_is_never_a_description():
    described = describe_material(
        core=_core(), transport=_Describing(error=RuntimeError("provider is down"))
    )

    assert described.features is None
    assert described.outcomes[0].state_code is StateCode.MATERIAL_DESCRIPTION_FAILED
    assert "provider is down" not in (described.outcomes[0].reason or "")


def test_a_refused_call_is_never_made_and_the_signal_is_skipped():
    budget = RunCallBudget(1)
    budget.spend()
    transport = _Describing()

    described = describe_material(
        core=_core(), transport=transport, budget=ArpCallBudget(budget)
    )

    assert transport.calls == 0, "the refused call is not made"
    assert described.features is None
    assert described.outcomes[0].state_code is StateCode.BUDGET_EXHAUSTED
    assert described.calls == 0


def test_the_stage_spends_one_call():
    """Acceptance evidence: calls per stage are recorded. S-02 makes one."""

    budget = RunCallBudget(4)
    transport = _Describing()

    described = describe_material(
        core=_core(), transport=transport, budget=ArpCallBudget(budget)
    )

    assert described.calls == 1
    assert transport.calls == 1
    assert budget.used == 1


def test_the_one_call_sees_the_core_and_the_approved_positions_only():
    core = _core()
    transport = _Describing()

    describe_material(
        core=core, transport=transport, approved_positions=(APPROVED_POSITION,)
    )

    payload = json.loads(transport.requests[0])
    assert payload["approved_positions"] == [APPROVED_POSITION]
    assert [item["evidence_claim_id"] for item in payload["claims"]] == [
        claim.evidence_claim_id for claim in core.evidence_claims
    ]
    assert "research_artifact" not in payload
    assert "supported_editorial_angle" not in json.dumps(payload)


def test_a_core_with_no_usable_claim_never_reaches_this_stage():
    core = _core(verdicts=(EvidenceDisposition.REJECTED,))

    with pytest.raises(MaterialFeaturesError):
        describe_material(core=core, transport=_Describing())


# ===========================================================================
# Assets and the calculations code does
# ===========================================================================


def _asset(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "asset_class": "evidentiary",
        "kind": "figure",
        "refs": ["evidence-1"],
        "strength": "medium",
        "rationale": "The figure is not reported elsewhere.",
        "derivation": None,
    }
    entry.update(overrides)
    return entry


def _figure(value: str, unit: Optional[str] = "USD") -> Figure:
    return Figure(value=value, provenance=FigureProvenance.OWN, unit=unit)


def test_an_asset_whose_claim_the_core_does_not_hold_is_dropped():
    described = describe_material(
        core=_core(),
        transport=_Describing(assets=(_asset(refs=["evidence-elsewhere"]),)),
    )

    assert described.assets == ()
    assert [item.kind for item in described.dropped] == ["asset"]
    assert described.outcomes[0].state_code is StateCode.MATERIAL_WITHOUT_REFERENCE


def test_a_calculation_is_arithmetic_code_does_over_the_figures_in_the_core():
    core = _core(figures=(_figure("$8 million"), _figure("$5 million")))
    described = describe_material(
        core=core,
        transport=_Describing(
            assets=(
                _asset(
                    kind="calculation",
                    refs=["evidence-1", "evidence-2"],
                    derivation={
                        "inputs": ["evidence-1", "evidence-2"],
                        "method": "difference",
                    },
                ),
            )
        ),
    )

    assert described.dropped == ()
    (asset,) = described.assets
    assert asset.kind is AssetKind.CALCULATION
    assert asset.derivation is not None
    assert asset.derivation.method is CalculationMethod.DIFFERENCE
    assert asset.derivation.result == Quantity(Decimal("3000000"), "USD")
    assert asset.as_entity()["derivation"]["result"]["amount"] == "3000000"


def test_a_percent_change_is_computed_from_the_first_input_to_the_second():
    core = _core(figures=(_figure("200", None), _figure("250", None)))
    described = describe_material(
        core=core,
        transport=_Describing(
            assets=(
                _asset(
                    kind="calculation",
                    refs=["evidence-1", "evidence-2"],
                    derivation={
                        "inputs": ["evidence-1", "evidence-2"],
                        "method": "percent_change",
                    },
                ),
            )
        ),
    )

    (asset,) = described.assets
    assert asset.derivation is not None
    assert asset.derivation.result == Quantity(Decimal("25"), "%")


def test_a_calculation_over_amounts_in_two_units_is_dropped():
    core = _core(figures=(_figure("$8 million"), _figure("120", "employees")))
    described = describe_material(
        core=core,
        transport=_Describing(
            assets=(
                _asset(
                    kind="calculation",
                    refs=["evidence-1", "evidence-2"],
                    derivation={
                        "inputs": ["evidence-1", "evidence-2"],
                        "method": "difference",
                    },
                ),
            )
        ),
    )

    assert described.assets == ()
    assert "units" in described.dropped[0].reason


def test_a_calculation_over_a_figure_code_cannot_read_is_dropped():
    core = _core(
        figures=(_figure("about a third of the fleet", None), _figure("120", None))
    )
    described = describe_material(
        core=core,
        transport=_Describing(
            assets=(
                _asset(
                    kind="calculation",
                    refs=["evidence-1", "evidence-2"],
                    derivation={
                        "inputs": ["evidence-1", "evidence-2"],
                        "method": "difference",
                    },
                ),
            )
        ),
    )

    assert described.assets == ()
    assert "arithmetic is never left to the model" in described.dropped[0].reason


def test_a_calculation_over_a_claim_with_no_figure_is_dropped():
    core = _core(figures=(None, _figure("120", None)))
    described = describe_material(
        core=core,
        transport=_Describing(
            assets=(
                _asset(
                    kind="calculation",
                    refs=["evidence-1", "evidence-2"],
                    derivation={
                        "inputs": ["evidence-1", "evidence-2"],
                        "method": "ratio",
                    },
                ),
            )
        ),
    )

    assert described.assets == ()
    assert "0 figure(s)" in described.dropped[0].reason


def test_a_calculation_over_a_claim_the_assessment_rejected_is_dropped():
    """E-06: a calculation is a derived evidence claim, so every amount it
    reads comes from a claim that may be referenced downstream. One accepted
    figure beside a rejected one passes the reference check and is still not
    arithmetic this stage may emit."""

    core = _core(
        figures=(_figure("$8 million"), _figure("$5 million")),
        verdicts=(EvidenceDisposition.ACCEPTED, EvidenceDisposition.REJECTED),
    )
    described = describe_material(
        core=core,
        transport=_Describing(
            assets=(
                _asset(
                    kind="calculation",
                    refs=["evidence-1", "evidence-2"],
                    derivation={
                        "inputs": ["evidence-1", "evidence-2"],
                        "method": "difference",
                    },
                ),
            )
        ),
    )

    assert described.assets == ()
    assert "evidence-2" in described.dropped[0].reason
    assert described.outcomes[0].state_code is StateCode.MATERIAL_WITHOUT_REFERENCE


def test_a_positional_asset_the_contract_did_not_approve_is_a_missing_position():
    described = describe_material(
        core=_core(),
        transport=_Describing(
            assets=(
                _asset(
                    asset_class="positional",
                    kind="client_position",
                    refs=["position-invented-by-the-model"],
                ),
            )
        ),
        approved_positions=(APPROVED_POSITION,),
    )

    assert described.assets == ()
    assert described.outcomes[0].state_code is StateCode.CLIENT_POSITION_MISSING
    assert described.outcomes[0].outcome is ArpOutcome.DEGRADE


def test_an_approved_position_is_the_only_positional_asset_there_can_be():
    described = describe_material(
        core=_core(),
        transport=_Describing(
            assets=(
                _asset(
                    asset_class="positional",
                    kind="client_position",
                    refs=[APPROVED_POSITION],
                ),
            )
        ),
        approved_positions=(APPROVED_POSITION,),
    )

    (asset,) = described.assets
    assert asset.asset_class is AssetClass.POSITIONAL
    assert asset.refs == (APPROVED_POSITION,)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    (
        ("$530 million", None, Quantity(Decimal("530000000"), "$")),
        ("48", "USD", Quantity(Decimal("48"), "USD")),
        ("1,250.5", None, Quantity(Decimal("1250.5"), None)),
        ("18%", None, Quantity(Decimal("18"), "%")),
        ("-4 thousand", None, Quantity(Decimal("-4000"), None)),
        ("roughly 18%", None, None),
        ("530 million dollars", None, None),
    ),
)
def test_read_amount_reads_what_the_excerpt_stated_or_refuses_it(
    value: str, unit: Optional[str], expected: Optional[Quantity]
):
    assert read_amount(Figure(value, FigureProvenance.OWN, unit=unit)) == expected


# ===========================================================================
# MaterialNotes are not gaps (fix F-3)
# ===========================================================================


def test_a_note_that_blocks_nothing_is_recorded_and_opens_no_gap():
    core = _core()
    described = describe_material(
        core=core,
        transport=_Describing(
            notes=(
                {
                    "kind": "evidence",
                    "description": "The filing does not say who signed it.",
                    "refs": ["evidence-1"],
                    "blocks_stage": None,
                    "blocks": None,
                },
            )
        ),
    )

    (note,) = described.notes
    assert note.blocks is None
    assert open_gaps(core=core, assets=(), notes=described.notes) == ()


def test_a_note_that_blocks_a_decision_becomes_the_one_gap_s_03_opens():
    core = _core()
    described = describe_material(
        core=core,
        transport=_Describing(
            notes=(
                {
                    "kind": "counter_evidence",
                    "description": "Nothing records the other side of the dispute.",
                    "refs": [],
                    "blocks_stage": "S-04",
                    "blocks": "whether the contested reading is admissible",
                },
            )
        ),
    )

    (gap,) = open_gaps(core=core, assets=(), notes=described.notes)
    assert gap.kind is GapKind.COUNTER_EVIDENCE
    assert gap.blocks.stage == "S-04"
    assert gap.status is GapStatus.OPEN


def test_the_relevance_screen_gap_is_opened_and_says_what_it_blocks():
    core = _core()

    gaps = open_gaps(
        core=core,
        assets=(),
        requested_gaps=(RequestedGapKind.READER_CONNECTION,),
    )

    (gap,) = gaps
    assert gap.kind is GapKind.READER_CONNECTION
    assert gap.blocks.stage == "S-01"
    assert "claim mode" in gap.blocks.decision


def test_a_gap_the_core_already_satisfies_is_abandoned_as_not_needed():
    core = _core(figures=(_figure("48", "USD"),))
    note = MaterialNote(
        note_id="note-1",
        kind=GapKind.FIGURE_PROVENANCE,
        description="No figure the subject produced itself.",
        refs=("evidence-1",),
        blocks=NoteBlock("S-08", "whether an opening may be built on a figure"),
    )

    (gap,) = open_gaps(core=core, assets=(), notes=(note,))

    assert gap.status is GapStatus.ABANDONED
    assert gap.stop_reason is StopReason.NOT_NEEDED
    assert gap.attempts == 0


def test_a_provenance_gap_about_another_figure_is_searched_not_dismissed():
    """What satisfies a gap is the material the gap names. A figure the source
    produced itself answers a note about *that* figure, and a note asking for
    the provenance of a second one is a gap the loop still has to search."""

    core = _core(figures=(_figure("48", "USD"), None))
    note = MaterialNote(
        note_id="note-1",
        kind=GapKind.FIGURE_PROVENANCE,
        description="The second figure is quoted from elsewhere.",
        refs=("evidence-2",),
        blocks=NoteBlock("S-08", "whether an opening may be built on a figure"),
    )

    (gap,) = open_gaps(core=core, assets=(), notes=(note,))

    assert gap.status is GapStatus.OPEN
    assert gap.stop_reason is None


@pytest.mark.parametrize(
    ("cited", "status"),
    [
        (("evidence-1",), GapStatus.ABANDONED),
        (("evidence-2",), GapStatus.OPEN),
        ((), GapStatus.OPEN),
    ],
)
def test_an_asset_gap_is_met_only_by_an_asset_over_the_material_it_names(
    cited: tuple[str, ...], status: GapStatus
):
    """An asset gap asks for one asset over named material. An asset the
    description built over other claims is not that asset, and a note that named
    no claim at all names nothing to check the assets against."""

    core = _core(figures=(None, None))
    described = describe_material(
        core=core, transport=_Describing(assets=(_asset(refs=["evidence-1"]),))
    )
    assert described.assets, "the description built the asset to be tested against"
    note = MaterialNote(
        note_id="note-1",
        kind=GapKind.ASSET,
        description="Nothing here the reader could not get elsewhere.",
        refs=cited,
        blocks=NoteBlock("S-04", "whether the signal carries an asset at all"),
    )

    (gap,) = open_gaps(core=core, assets=described.assets, notes=(note,))

    assert gap.status is status


# ===========================================================================
# S-03: the loop, and the stop reason it always records
# ===========================================================================


def test_no_blocking_gap_means_zero_rounds_and_no_calls():
    core = _core()
    provider = _Enriching()

    enrichment = _enrich(core, provider=provider)

    assert enrichment.rounds == ()
    assert enrichment.gaps == ()
    assert enrichment.calls == 0
    assert provider.requests == [], "nothing is searched for"
    assert enrichment.core is core
    assert enrichment.continues is True


def test_an_evidence_gap_closes_against_the_core_version_that_closed_it():
    core = _core()

    enrichment = _enrich(core, notes=(_blocking_note(),))

    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.CLOSED
    assert gap.closure == 2
    assert gap.attempts == 1
    assert [directive.kind for directive in gap.search_directives] == [
        SourceDirectiveKind.QUERY
    ]
    assert enrichment.core.version == 2
    assert enrichment.core.closed_gaps == (gap.gap_id,)
    assert enrichment.features.core_ref == (core.core_id, 2)
    resolved = [
        outcome for outcome in enrichment.outcomes if outcome.outcome is ArpOutcome.RESOLVE
    ]
    assert [outcome.state_code for outcome in resolved] == [
        StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION
    ]
    assert resolved[0].scope is OutcomeScope.SIGNAL


def test_a_counter_evidence_gap_is_not_closed_by_material_that_agrees():
    """What closes a gap is material of the kind the gap asks for. A round that
    found a second source saying the same thing found no counter-evidence, and
    closing on it would stop the loop looking for any."""

    core = _core()
    counters = AttemptCounterLedger()

    enrichment = _enrich(
        core, notes=(_blocking_note(GapKind.COUNTER_EVIDENCE),), counters=counters
    )

    assert enrichment.rounds[0].usable_claims_added == 1, "material did arrive"
    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.ABANDONED
    assert gap.stop_reason is StopReason.LIMIT_REACHED
    assert gap.attempts == counters.limit(ENRICHMENT_COUNTER)
    assert enrichment.core.closed_gaps == ()


def test_a_counter_evidence_gap_closes_on_material_that_runs_against_the_core():
    core = _core()
    # A verdict of `conflicting` is the assessment's own record that the
    # retrieved material and the core do not agree: code reads it, and judges
    # nothing itself.
    transport = _Model(_Describing(), _Answering(disposition="conflicting"))

    enrichment = _enrich(
        core,
        notes=(_blocking_note(GapKind.COUNTER_EVIDENCE),),
        transport=transport,
    )

    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.CLOSED
    assert gap.closure == 2
    assert enrichment.rounds[0].usable_claims_added == 0
    assert enrichment.core.closed_gaps == (gap.gap_id,)


def test_a_reader_connection_gap_is_not_closed_by_material_s_03_cannot_judge():
    """Whether material establishes a reader connection is S-04's judgment. S-03
    searches for it and records that it stopped; it never says it was found."""

    core = _core()
    counters = AttemptCounterLedger()

    enrichment = _enrich(
        core,
        requested_gaps=(RequestedGapKind.READER_CONNECTION,),
        counters=counters,
    )

    assert len(enrichment.rounds) == counters.limit(ENRICHMENT_COUNTER)
    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.ABANDONED
    assert gap.stop_reason is StopReason.LIMIT_REACHED
    assert enrichment.continues is True, "S-04 decides what an abandoned gap costs"


def test_two_calls_are_recorded_for_one_round():
    """Acceptance evidence: calls per stage. One round is one extended
    assessment and one features recomputation."""

    budget = RunCallBudget(8)

    enrichment = _enrich(
        _core(), notes=(_blocking_note(),), budget=ArpCallBudget(budget)
    )

    assert enrichment.calls == 2
    assert enrichment.rounds[0].calls == 2
    assert budget.used == 2


@pytest.mark.parametrize("case", SAVED_CASES)
def test_on_the_fixed_set_every_enrichment_ends_with_a_recorded_stop_reason(
    case: str,
):
    """Acceptance evidence: no gap is left open, and every abandoned one says
    why the loop stopped on it."""

    core = _saved_core(case)
    scenarios = (
        _enrich(core, notes=(_blocking_note(),), provider=_Enriching(failing=True)),
        _enrich(core, notes=(_blocking_note(),)),
        _enrich(
            core,
            notes=(_blocking_note(GapKind.COUNTER_EVIDENCE),),
            provider=_Enriching(),
            transport=_Model(_Describing(), _Answering()),
        ),
    )
    for enrichment in scenarios:
        assert all(gap.status is not GapStatus.OPEN for gap in enrichment.gaps)
        for gap in enrichment.abandoned:
            assert gap.stop_reason is not None
        for gap in enrichment.closed:
            assert gap.closure is not None


def test_a_search_that_returned_nothing_abandons_the_gap_and_commits_no_version():
    core = _core()

    enrichment = _enrich(
        core, notes=(_blocking_note(),), provider=_Enriching(failing=True)
    )

    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.ABANDONED
    assert gap.stop_reason is StopReason.NOTHING_FOUND
    assert enrichment.core is core, "an uncommitted round leaves the version standing"
    assert enrichment.rounds[0].core_version is None
    assert enrichment.rounds[0].failure is not None
    assert enrichment.continues is True, "S-04 decides what an open gap costs"


def test_the_loop_stops_when_l_enrich_is_gone():
    core = _core()
    counters = AttemptCounterLedger()
    # A gap the search can never close: only a figure the subject produced
    # itself closes a figure-provenance gap, and the enrichment source records
    # none.
    note = MaterialNote(
        note_id="note-1",
        kind=GapKind.FIGURE_PROVENANCE,
        description="No figure the subject produced itself.",
        blocks=NoteBlock("S-08", "whether an opening may be built on a figure"),
    )

    enrichment = _enrich(core, notes=(note,), counters=counters)

    limit = counters.limit(ENRICHMENT_COUNTER)
    assert len(enrichment.rounds) == limit
    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.ABANDONED
    assert gap.stop_reason is StopReason.LIMIT_REACHED
    assert gap.attempts == limit
    assert counters.exhausted(ENRICHMENT_COUNTER, SIGNAL)
    assert enrichment.calls == 2 * limit


def test_the_counter_is_the_one_the_relevance_screen_route_already_spent():
    """§0.3 gives S-01's route into S-03 and S-03's own rounds one counter, and
    §5.3's termination argument rests on it never being reset."""

    core = _core()
    counters = AttemptCounterLedger()
    counters.route(
        source="S-01",
        cause=ENRICHMENT_ROUTE_CAUSE,
        scope_key=SIGNAL,
        state_code=StateCode.RELEVANCE_NOT_ESTABLISHED,
    )
    note = MaterialNote(
        note_id="note-1",
        kind=GapKind.FIGURE_PROVENANCE,
        description="No figure the subject produced itself.",
        blocks=NoteBlock("S-08", "whether an opening may be built on a figure"),
    )

    enrichment = _enrich(core, notes=(note,), counters=counters)

    assert len(enrichment.rounds) == counters.limit(ENRICHMENT_COUNTER) - 1
    assert enrichment.gaps[0].stop_reason is StopReason.LIMIT_REACHED


def test_a_refused_assessment_stops_the_loop_before_the_call_is_made():
    budget = RunCallBudget(2)
    # One call for the S-02 description the fixture makes, one left over, and
    # then nothing for the round.
    budget.spend()
    budget.spend()
    provider = _Enriching()

    enrichment = _enrich(
        _core(),
        notes=(_blocking_note(),),
        provider=provider,
        budget=ArpCallBudget(budget),
    )

    assert provider.requests, "the search is not a model call and is still made"
    (gap,) = enrichment.gaps
    assert gap.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert enrichment.calls == 0
    assert enrichment.continues is False
    assert [outcome.state_code for outcome in enrichment.outcomes] == [
        StateCode.BUDGET_EXHAUSTED
    ]


def test_a_round_that_cannot_be_described_commits_no_core_version():
    core = _core()
    transport = _Model(_Describing(raw="{}"), _Answering())

    enrichment = _enrich(core, notes=(_blocking_note(),), transport=transport)

    assert enrichment.core is core
    assert enrichment.features.core_ref == (core.core_id, 1)
    assert enrichment.rounds[0].core_version is None
    assert enrichment.gaps[0].stop_reason is StopReason.NOTHING_FOUND
    assert enrichment.continues is True, (
        "the standing description is still in force, so the signal is not the "
        "one S-02 skips for having none"
    )


def test_a_round_adds_to_the_core_and_drops_nothing_from_it():
    core = _core()

    enrichment = _enrich(core, notes=(_blocking_note(),))

    assert enrichment.core.version == core.version + 1
    held = {claim.evidence_claim_id for claim in core.evidence_claims}
    assert held <= {
        claim.evidence_claim_id for claim in enrichment.core.evidence_claims
    }
    assert {source.source_id for source in core.sources} <= {
        source.source_id for source in enrichment.core.sources
    }
    assert len(enrichment.core.research_artifact_refs) == 2
    assert enrichment.rounds[0].usable_claims_added == 1


def test_the_search_keeps_the_run_identity_and_the_client_source_policy():
    core = _core()
    provider = _Enriching()

    _enrich(core, notes=(_blocking_note(),), provider=provider)

    (search,) = provider.requests
    original = _request(core)
    assert search.run_id == original.run_id
    assert search.signal_id == original.signal_id
    assert search.strategy.identity == original.strategy.identity
    assert search.freshness.allow_open_discovery is True
    priorities = {
        directive.directive_id: directive.priority
        for directive in search.source_directives
    }
    assert priorities["preferred-source-1"] is SourcePriority.PREFERRED
    assert "required-source-1" not in priorities


def _excluded(index: int) -> SourceDirective:
    return SourceDirective(
        directive_id=f"excluded-source-{index}",
        priority=SourcePriority.EXCLUDED,
        kind=SourceDirectiveKind.DOMAIN,
        value=f"excluded-{index}.test",
        material=False,
    )


def test_more_gaps_than_the_request_holds_never_drop_an_excluded_source():
    """The provider bounds a request at twenty directives. A preferred source
    the bound cuts is one the round did not ask for; an excluded source it cut
    would be one the client prohibited and the round researched anyway."""

    core = _core()
    provider = _Enriching()
    notes = tuple(
        _blocking_note(note_id=f"note-{index}")
        for index in range(1, MAX_DIRECTIVES + 1)
    )

    _enrich(
        core,
        notes=notes,
        provider=provider,
        request=_request(core, directives=CLIENT_DIRECTIVES + (_excluded(1),)),
    )

    search = provider.requests[0]
    assert len(search.source_directives) == MAX_DIRECTIVES
    priorities = {
        directive.directive_id: directive.priority
        for directive in search.source_directives
    }
    assert priorities["excluded-source-1"] is SourcePriority.EXCLUDED
    assert "preferred-source-1" not in priorities, (
        "the gap queries take the room the exclusions leave, before the "
        "client's preferred sources"
    )
    queries = [
        directive
        for directive in search.source_directives
        if directive.priority is SourcePriority.DISCOVERY
    ]
    assert len(queries) == MAX_DIRECTIVES - 1
    second = provider.requests[1]
    assert [directive.priority for directive in second.source_directives] == [
        SourcePriority.EXCLUDED,
        SourcePriority.DISCOVERY,
        SourcePriority.PREFERRED,
    ], (
        "the gap the bound cut is searched in the next round rather than "
        "closed by material the round never asked about"
    )


def test_the_core_records_no_closure_for_a_gap_the_directive_bound_cut():
    """A core version's closure list and the gaps' own records are one fact. The
    gap whose query the bound cut was not searched, so the round closes it in
    neither place — and with the loop's last round spent, the gap S-04 reads is
    abandoned rather than closed by material nobody asked about."""

    core = _core()
    counters = AttemptCounterLedger()
    counters.route(
        source="S-01",
        cause=ENRICHMENT_ROUTE_CAUSE,
        scope_key=SIGNAL,
        state_code=StateCode.RELEVANCE_NOT_ESTABLISHED,
    )
    notes = tuple(
        _blocking_note(note_id=f"note-{index}")
        for index in range(1, MAX_DIRECTIVES + 1)
    )

    enrichment = _enrich(
        core,
        notes=notes,
        counters=counters,
        request=_request(core, directives=CLIENT_DIRECTIVES + (_excluded(1),)),
    )

    assert len(enrichment.rounds) == 1
    (cut,) = enrichment.abandoned
    assert cut.stop_reason is StopReason.LIMIT_REACHED
    assert cut.gap_id not in enrichment.core.closed_gaps
    assert sorted(enrichment.core.closed_gaps) == sorted(
        gap.gap_id for gap in enrichment.closed
    )


def test_exclusions_that_fill_the_request_leave_no_round_to_search():
    core = _core()
    provider = _Enriching()

    enrichment = _enrich(
        core,
        notes=(_blocking_note(),),
        provider=provider,
        request=_request(
            core,
            directives=tuple(
                _excluded(index) for index in range(1, MAX_DIRECTIVES + 1)
            ),
        ),
    )

    assert provider.requests == [], "a search with no room for the gap is not sent"
    (gap,) = enrichment.gaps
    assert gap.status is GapStatus.ABANDONED
    assert gap.stop_reason is StopReason.NOTHING_FOUND
    failure = enrichment.rounds[0].failure
    assert failure is not None and "no gap query fits" in failure


def test_a_description_of_another_core_version_is_refused():
    core = _core()
    described = describe_material(core=core, transport=_Describing())
    assert described.features is not None
    other = _core(core_id="core-other")

    with pytest.raises(EnrichmentError):
        enrich(
            core=other,
            features=described.features,
            provider=_Enriching(),
            request=_request(other),
            transport=_Model(_Describing(), _Answering()),
            ladder=LADDER,
            counters=AttemptCounterLedger(),
            now=NOW,
        )


def test_a_gap_left_open_is_never_an_enrichment():
    """The post-condition, asserted directly against the record type."""

    core = _core()
    described = describe_material(core=core, transport=_Describing())
    assert described.features is not None

    with pytest.raises(EnrichmentError):
        Enrichment(
            signal_id=SIGNAL,
            core=core,
            features=described.features,
            gaps=(
                Gap(
                    gap_id="gap-1",
                    kind=GapKind.EVIDENCE,
                    description="Nothing records the other side.",
                    blocks=GapBlocks("S-04", "admissibility"),
                ),
            ),
        )


def test_a_closed_gap_names_the_version_that_closed_it_or_is_refused():
    with pytest.raises(EnrichmentError):
        Gap(
            gap_id="gap-1",
            kind=GapKind.EVIDENCE,
            description="Nothing records the other side.",
            blocks=GapBlocks("S-04", "admissibility"),
            status=GapStatus.CLOSED,
        )
    with pytest.raises(EnrichmentError):
        Gap(
            gap_id="gap-1",
            kind=GapKind.EVIDENCE,
            description="Nothing records the other side.",
            blocks=GapBlocks("S-04", "admissibility"),
            status=GapStatus.ABANDONED,
        )


# ===========================================================================
# The states both stages record are countable in the public ledger
# ===========================================================================


@pytest.mark.parametrize(
    ("state", "category"),
    (
        (StateCode.MATERIAL_DESCRIPTION_FAILED, ReasonCategory.PROVIDER),
        (StateCode.MATERIAL_WITHOUT_REFERENCE, ReasonCategory.EVIDENCE),
    ),
)
def test_the_new_states_are_counted_under_a_category(
    state: StateCode, category: ReasonCategory
):
    assert reason_category(state) is category


def test_an_attempt_is_never_spent_past_the_limit():
    counters = AttemptCounterLedger()
    limit = counters.limit(ENRICHMENT_COUNTER)

    spent = [counters.spend_attempt(ENRICHMENT_COUNTER, SIGNAL) for _ in range(limit)]

    assert spent == list(range(1, limit + 1))
    assert counters.spend_attempt(ENRICHMENT_COUNTER, SIGNAL) is None
    assert counters.used(ENRICHMENT_COUNTER, SIGNAL) == limit


def test_a_value_that_asserts_nothing_need_cite_nothing():
    """Each domain has one floor: false, "none" and "low". They are also what
    the reference check withdraws a dropped feature to."""

    described = describe_material(
        core=_core(), transport=_Describing(figure_provenance="none", freshness="low")
    )

    assert described.features is not None
    assert described.dropped == ()
    provenance = described.features.value_of(MaterialFeature.FIGURE_PROVENANCE)
    assert provenance.value is FeatureFigureProvenance.NONE
    assert provenance.positive is False
    assert provenance.evidence_refs == ()
    freshness = described.features.value_of(MaterialFeature.FRESHNESS)
    assert freshness.value is Freshness.LOW
    assert freshness.positive is False
    assert freshness.evidence_refs == ()
