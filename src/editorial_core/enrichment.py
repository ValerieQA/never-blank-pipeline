"""S-03 · The enrichment loop: gaps, search, stop reasons (Issue #300, SL-3).

The stage that closes what blocks a decision and decides when to stop. Step 2
§1 gives it one authority — "close gaps that **block a decision**, and decide
when to stop" — and one prohibition: "it must not collect 'interesting
extras'". Both are enforced here by construction rather than by intent: a
MaterialNote becomes an E-07 only when it names the decision it blocks, and
every round spends ``L_enrich``, so the loop is finite whatever it finds.

What it does, in the order it does it
-------------------------------------
1. **Opening gaps, by code.** S-02's notes and the gap the relevance screen
   asked for become E-07 records — the only ones, because S-03 is the sole
   producer of E-07 (fix F-3). A note with no ``blocks`` target opens nothing.
   A gap the current core already satisfies is opened and abandoned at once as
   ``not_needed``, so a spurious note costs no round.
2. **Searching, by code.** The existing provider boundary, reused whole: one
   ``SourceDirective`` per open gap carried into a ``ResearchProviderRequest``
   beside the client's own preferred and excluded sources, and
   ``execute_research``. Nothing is persisted here: ``research.json`` is
   create-once and belongs to S-01, and the core references every artifact it
   wraps by ID and digest.
3. **Re-assessing and recomputing, by model.** Two calls per round (§1,
   Calls): the extended assessment of :mod:`src.editorial_core.evidence_core`
   over what the search returned, and the S-02 description recomputed over the
   core version that results.

**A round is the unit of commit.** The core version and the feature vector a
round produces are adopted together or not at all, because E-05 is recomputed
per core version and a core no feature vector describes is a core S-04 cannot
read. A round that cannot finish leaves the previous versions standing and the
gap open.

**The core is append-only** (E-04). A round adds sources, observations and
claims; it never drops one and never rewrites one. Material the search returned
that the core already holds is not added twice — the core keeps its own copy,
and the artifact the round retrieved is referenced by digest either way.

**Who decides what is closed.** Code, from what entered the core, and one test
per kind: a figure provenance gap by a figure the source produced itself, an
asset gap by an asset the recomputation found, a counter-evidence gap by
material that runs against what the core holds, an evidence gap by new usable
material. A kind whose satisfaction code cannot test — a reader connection, and
whatever ``other`` was opened for — is not closed here at all: whether the
material establishes a reader connection or an interpretation is S-04's
judgment, and taking it here would be worse than leaving the gap open, because
a closure stops the loop searching for what still blocks the decision. Such a
gap reaches S-04 abandoned with the stop reason the loop ended on, and whether
an abandoned gap costs the signal is S-04's too (§1, ARP), which is why it is
recorded here with no outcome of its own.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.3,
§0.4 and §1 (S-03); ``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md``
§2 (E-04, E-07); ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §6.2 and
`K-PRC-08`; ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§2.2 and §2.5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Final, Optional

from src.editorial.decision_contract import research_artifact_digest
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    EvidenceCoreError,
    ExtendedEvidenceAssessor,
    FigureProvenance,
    SourceObservation,
    Strength,
    StrengthLadder,
    build_evidence_core,
)
from src.editorial_core.material_features import (
    Asset,
    GapKind,
    MaterialFeatures,
    MaterialNote,
    MaterialTransport,
    describe_material,
)
from src.editorial_core.relevance_screen import RequestedGapKind
from src.editorial_core.signal_selection import CallBudget
from src.research.assessment import EvidenceAssessmentError, assess_artifact
from src.research.evidence import (
    Contradiction,
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedResearchArtifact,
    NormalizedSource,
    ResolutionStatus,
    UncertaintyAssessment,
    UncertaintyMateriality,
)
from src.research.provider import (
    FreshnessRequirement,
    ResearchProvider,
    ResearchProviderRequest,
    SourceDirective,
    SourceDirectiveKind,
    SourcePriority,
    execute_research,
)

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-03"

#: The counter a round spends (§0.3): "L_enrich | signal | 2 rounds | consumed
#: by S-03 enrichment rounds". The limit in force is the ledger's, not this
#: module's — the number is a tunable implementation parameter (OPEN-22).
ENRICHMENT_COUNTER: Final[str] = "L_enrich"

#: The most directives one search request may carry, from the provider
#: contract's own bound. What the bound cuts into is not a free choice: the
#: client's excluded sources are a prohibition and are carried whole, and the
#: gap queries come before the client's preferred sources in what is left.
MAX_DIRECTIVES: Final[int] = 20


class EnrichmentError(RuntimeError):
    """S-03 was asked to enrich something its contract cannot enrich."""


# ===========================================================================
# E-07 · Gap
# ===========================================================================


class GapStatus(str, Enum):
    """E-07's statuses. A run never ends with an ``OPEN`` one."""

    OPEN = "open"
    CLOSED = "closed"
    ABANDONED = "abandoned"


class StopReason(str, Enum):
    """Why enrichment stopped with a gap still open (E-07).

    ``NOTHING_FOUND`` is the reason for every round that ended with nothing
    entering the core, whether the search returned no material or the
    machinery that turns material into a core version could not be run. The
    round record says which of the two it was; the gap says only that the
    search did not close it, because that is the fact S-04 decides on.
    """

    LIMIT_REACHED = "limit_reached"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NOTHING_FOUND = "nothing_found"
    NOT_NEEDED = "not_needed"


@dataclass(frozen=True, slots=True)
class GapBlocks:
    """What a gap blocks: a stage and the decision it cannot take (E-07)."""

    stage: str
    decision: str

    def as_entity(self) -> dict[str, str]:
        return {"stage": self.stage, "decision": self.decision}


@dataclass(frozen=True, slots=True)
class Gap:
    """``E-07``: what is missing, and what the loop did about it.

    ``blocks`` is required and not optional, which is the whole prevention of
    endless enrichment: "only gaps that block a decision are opened".
    """

    gap_id: str
    kind: GapKind
    description: str
    blocks: GapBlocks
    attempts: int = 0
    status: GapStatus = GapStatus.OPEN
    search_directives: tuple[SourceDirective, ...] = ()
    #: The core version whose arrival closed the gap.
    closure: Optional[int] = None
    stop_reason: Optional[StopReason] = None

    def __post_init__(self) -> None:
        if not self.gap_id.strip() or not self.description.strip():
            raise EnrichmentError(
                f"gap {self.gap_id!r} is missing its identity or its description"
            )
        if self.attempts < 0:
            raise EnrichmentError(f"gap {self.gap_id!r} records {self.attempts} attempts")
        if (self.status is GapStatus.CLOSED) != (self.closure is not None):
            raise EnrichmentError(
                f"gap {self.gap_id!r} is {self.status.value} and "
                + ("names" if self.closure is not None else "names no")
                + " closing core version; E-07 records the version a closure "
                "produced, and a closure with no version behind it is not one"
            )
        if (self.status is GapStatus.ABANDONED) != (self.stop_reason is not None):
            raise EnrichmentError(
                f"gap {self.gap_id!r} is {self.status.value} and "
                + ("names" if self.stop_reason is not None else "names no")
                + " stop reason; every abandoned gap says why the loop stopped "
                "on it (§1, Post)"
            )

    def as_entity(self) -> dict[str, Any]:
        """The entity body written to ``signal/gaps/<gap_id>.json`` (§2.2)."""

        return {
            "entity_type": "E-07",
            "entity_id": self.gap_id,
            "gap_id": self.gap_id,
            "kind": self.kind.value,
            "description": self.description,
            "blocks": self.blocks.as_entity(),
            "search_directives": [
                directive.model_dump(mode="json")
                for directive in self.search_directives
            ],
            "attempts": self.attempts,
            "status": self.status.value,
            "closure": self.closure,
            "stop_reason": (
                None if self.stop_reason is None else self.stop_reason.value
            ),
        }


# ===========================================================================
# What one round did
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EnrichmentRound:
    """One round of the loop, as the trace records it (§1, Trace)."""

    number: int
    gap_ids: tuple[str, ...]
    #: ``(artifact_id, digest)`` of what the search returned, if anything.
    artifact_ref: Optional[tuple[str, str]] = None
    observations_added: int = 0
    claims_added: int = 0
    usable_claims_added: int = 0
    #: The core version this round produced, or ``None`` when it was not
    #: committed: a round is adopted whole or not at all.
    core_version: Optional[int] = None
    calls: int = 0
    #: Why the round produced no core version, in this module's own words.
    #: Never a provider's text.
    failure: Optional[str] = None

    def as_entity(self) -> dict[str, Any]:
        return {
            "round": self.number,
            "gap_ids": list(self.gap_ids),
            "artifact_ref": (
                None
                if self.artifact_ref is None
                else {
                    "artifact_id": self.artifact_ref[0],
                    "digest": self.artifact_ref[1],
                }
            ),
            "observations_added": self.observations_added,
            "claims_added": self.claims_added,
            "usable_claims_added": self.usable_claims_added,
            "core_version": self.core_version,
            "calls": self.calls,
            "failure": self.failure,
        }


@dataclass(frozen=True, slots=True)
class Enrichment:
    """What S-03 made of one described core: the final versions, and the gaps.

    The core, features and assets carried here are "the final versions for
    S-04" (§1, Post), and they are consistent by construction: a round commits
    a core version and the feature vector describing it together.
    """

    signal_id: str
    core: EvidenceCore
    features: MaterialFeatures
    assets: tuple[Asset, ...] = ()
    gaps: tuple[Gap, ...] = ()
    rounds: tuple[EnrichmentRound, ...] = ()
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0

    def __post_init__(self) -> None:
        still_open = [gap.gap_id for gap in self.gaps if gap.status is GapStatus.OPEN]
        if still_open:
            raise EnrichmentError(
                "enrichment ended with gap(s) still open: "
                + ", ".join(still_open)
                + "; §1 leaves every opened gap closed or abandoned with a stop "
                "reason, and an open one is a run that waits"
            )
        if self.features.core_ref != (self.core.core_id, self.core.version):
            raise EnrichmentError(
                f"the feature vector describes {self.features.core_ref!r} and "
                f"the final core is ({self.core.core_id!r}, {self.core.version}); "
                "E-05 is recomputed per core version, and a vector describing "
                "another one is not this core's description"
            )

    @property
    def continues(self) -> bool:
        """May S-04 run on these versions?"""

        return not any(
            outcome.outcome is ArpOutcome.SKIP for outcome in self.outcomes
        )

    @property
    def closed(self) -> tuple[Gap, ...]:
        return tuple(gap for gap in self.gaps if gap.status is GapStatus.CLOSED)

    @property
    def abandoned(self) -> tuple[Gap, ...]:
        return tuple(gap for gap in self.gaps if gap.status is GapStatus.ABANDONED)


# ===========================================================================
# Opening gaps, by code (§1, Decider)
# ===========================================================================


#: The relevance screen asks for two of E-07's six kinds, and they are the same
#: vocabulary. A table rather than a cast, so that a kind the screen could ask
#: for and E-07 does not have would be a missing row instead of a surprise.
_SCREEN_GAP_KINDS: Mapping[RequestedGapKind, GapKind] = {
    RequestedGapKind.EVIDENCE: GapKind.EVIDENCE,
    RequestedGapKind.READER_CONNECTION: GapKind.READER_CONNECTION,
}

#: What a gap the relevance screen asked for says it blocks. S-01 is the stage
#: that could not decide, and the decision it could not take is the relevance
#: of the material to the configured audience.
_SCREEN_BLOCKS: Mapping[RequestedGapKind, str] = {
    RequestedGapKind.EVIDENCE: (
        "the relevance screen found the evidence insufficient to establish "
        "relevance for the configured audience"
    ),
    RequestedGapKind.READER_CONNECTION: (
        "the relevance screen could not establish the audience connection the "
        "declared claim mode requires"
    ),
}


def gap_id(core_id: str, index: int) -> str:
    """The ID of the ``index``-th gap opened for one core."""

    return f"gap-{core_id}-{index}"


def open_gaps(
    *,
    core: EvidenceCore,
    assets: Sequence[Asset],
    notes: Sequence[MaterialNote] = (),
    requested_gaps: Sequence[RequestedGapKind] = (),
) -> tuple[Gap, ...]:
    """The gaps this signal opens, in the order they were asked for.

    Code's, and deliberately narrow: a note that names no blocked decision
    opens nothing, which is what "it must not collect interesting extras"
    means in practice. A gap whose own material the core already holds is
    opened and abandoned as ``not_needed`` in the same step — it is recorded,
    because a note that turned out not to block anything is worth reading
    offline, and it costs no round.
    """

    # Each opened gap beside the claims the note behind it cited, which are the
    # material it says is missing. E-07 carries no references of its own, and
    # the gaps the relevance screen asks for name no claim at all.
    opened: list[tuple[Gap, tuple[str, ...]]] = []
    index = 0
    for requested in dict.fromkeys(requested_gaps):
        index += 1
        opened.append(
            (
                Gap(
                    gap_id=gap_id(core.core_id, index),
                    kind=_SCREEN_GAP_KINDS[requested],
                    description=_SCREEN_BLOCKS[requested],
                    blocks=GapBlocks("S-01", _SCREEN_BLOCKS[requested]),
                ),
                (),
            )
        )
    for note in notes:
        if note.blocks is None:
            continue
        index += 1
        opened.append(
            (
                Gap(
                    gap_id=gap_id(core.core_id, index),
                    kind=note.kind,
                    description=note.description,
                    blocks=GapBlocks(note.blocks.stage, note.blocks.decision),
                ),
                note.refs,
            )
        )
    return tuple(
        (
            replace(gap, status=GapStatus.ABANDONED, stop_reason=StopReason.NOT_NEEDED)
            if _already_met(gap, cited, core, assets)
            else gap
        )
        for gap, cited in opened
    )


def _already_met(
    gap: Gap,
    cited: Sequence[str],
    core: EvidenceCore,
    assets: Sequence[Asset],
) -> bool:
    """Does the core already hold the material *this* gap asks for?

    Only the two kinds with a test code can make on the material as it stands,
    and only over the claims the note behind the gap cited: a provenance gap
    asks for the provenance of one figure and an asset gap for one asset over
    named material, so any own figure and any asset at all are not tests of
    them — a note asking about a second figure would be abandoned without ever
    being searched for. A gap that cites nothing names no material to look for
    and is searched rather than dismissed against material it is not about. For
    the other kinds, what would satisfy the gap is a judgment S-04 makes, so
    S-03 searches rather than deciding it has nothing to search for.
    """

    wanted = set(cited)
    if not wanted:
        return False
    if gap.kind is GapKind.FIGURE_PROVENANCE:
        return wanted <= _own_figure_claims(core)
    if gap.kind is GapKind.ASSET:
        return any(wanted <= set(item.refs) for item in assets)
    return False


def _own_figure_claims(core: EvidenceCore) -> set[str]:
    """The claims the core holds over a figure the source produced itself."""

    own = {
        item.observation_id for item in core.observations if _is_own_figure(item)
    }
    return {
        claim.evidence_claim_id
        for claim in core.evidence_claims
        if set(claim.observation_refs) & own
    }


def _is_own_figure(observation: SourceObservation) -> bool:
    return (
        observation.figure is not None
        and observation.figure.provenance is FigureProvenance.OWN
    )


# ===========================================================================
# The stage
# ===========================================================================


def enrich(
    *,
    core: EvidenceCore,
    features: MaterialFeatures,
    assets: Sequence[Asset] = (),
    notes: Sequence[MaterialNote] = (),
    requested_gaps: Sequence[RequestedGapKind] = (),
    provider: ResearchProvider,
    request: ResearchProviderRequest,
    transport: MaterialTransport,
    ladder: StrengthLadder,
    counters: AttemptCounterLedger,
    now: datetime,
    client_ceiling: Optional[Strength] = None,
    approved_positions: Sequence[str] = (),
    budget: Optional[CallBudget] = None,
) -> Enrichment:
    """Close what blocks a decision, and stop with a recorded reason.

    Returns an :class:`Enrichment` in every case. Zero rounds is an ordinary
    result and the common one: "no blocking gap → zero rounds" (§1, ARP), and
    the versions S-02 produced are then the final ones.

    ``now`` is handed in rather than read, as it is at S-01: the editorial core
    is given its inputs, and timestamps are the run harness's (CE-1 placement
    rule). It stamps the search request the providers are asked against.
    """

    signal_id = core.signal_ids[0]
    if features.core_ref != (core.core_id, core.version):
        raise EnrichmentError(
            f"{signal_id} reached {STAGE} with a feature vector describing "
            f"{features.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); S-03 enriches a core its own "
            "description was computed over"
        )

    gaps = list(
        open_gaps(
            core=core, assets=assets, notes=notes, requested_gaps=requested_gaps
        )
    )
    current = _State(
        core=core, features=features, assets=tuple(assets), calls=0
    )
    rounds: list[EnrichmentRound] = []
    outcomes: list[OutcomeRecord] = []
    stop: Optional[StopReason] = None

    while stop is None and any(gap.status is GapStatus.OPEN for gap in gaps):
        number = len(rounds) + 1
        if counters.spend_attempt(ENRICHMENT_COUNTER, signal_id) is None:
            # §0.3: "L_enrich exhausted → stop; the same as a stop condition".
            stop = StopReason.LIMIT_REACHED
            break
        searched = tuple(gap for gap in gaps if gap.status is GapStatus.OPEN)
        outcome = _round(
            number=number,
            searched=searched,
            state=current,
            provider=provider,
            request=request,
            transport=transport,
            ladder=ladder,
            now=now,
            client_ceiling=client_ceiling,
            approved_positions=approved_positions,
            budget=budget,
        )
        rounds.append(outcome.record)
        outcomes.extend(outcome.outcomes)
        spent = current.calls + outcome.record.calls
        searched_ids = {gap.gap_id for gap in searched}
        gaps = [
            (
                replace(
                    gap,
                    attempts=gap.attempts + 1,
                    search_directives=(
                        gap.search_directives + outcome.directives_for(gap.gap_id)
                    ),
                )
                if gap.gap_id in searched_ids
                else gap
            )
            for gap in gaps
        ]
        if outcome.state is None:
            current = replace(current, calls=spent)
            stop = outcome.stop or StopReason.NOTHING_FOUND
            break
        current = replace(outcome.state, calls=spent)
        # Only the gaps whose query the request actually carried: a gap the
        # directive bound cut is a gap this round did not search for, and
        # material it never asked about does not close it.
        carried = {identity for identity, _ in outcome.directives}
        gaps = [
            (
                replace(gap, status=GapStatus.CLOSED, closure=current.core.version)
                if gap.gap_id in carried and _closes(gap, outcome.added)
                else gap
            )
            for gap in gaps
        ]

    gaps = [
        (
            replace(gap, status=GapStatus.ABANDONED, stop_reason=stop)
            if gap.status is GapStatus.OPEN and stop is not None
            else gap
        )
        for gap in gaps
    ]
    outcomes.extend(
        _resolved(signal_id, gap)
        for gap in gaps
        if gap.status is GapStatus.CLOSED
    )
    return Enrichment(
        signal_id=signal_id,
        core=current.core,
        features=current.features,
        assets=current.assets,
        gaps=tuple(gaps),
        rounds=tuple(rounds),
        outcomes=tuple(outcomes),
        calls=current.calls,
    )


# ===========================================================================
# One round
# ===========================================================================


@dataclass(frozen=True, slots=True)
class _State:
    """The versions in force between rounds. Replaced whole, or not at all."""

    core: EvidenceCore
    features: MaterialFeatures
    assets: tuple[Asset, ...]
    calls: int


@dataclass(frozen=True, slots=True)
class _Added:
    """What one round put into the core, as closure is decided on it."""

    usable_claims: int = 0
    own_figure: bool = False
    new_asset: bool = False
    #: Material that runs against what the core holds: a claim the assessment
    #: found conflicting, or a contradiction it recorded over the merged core.
    counter_material: bool = False


@dataclass(frozen=True, slots=True)
class _RoundOutcome:
    """One round's record, its outcomes, and the state it commits — or none."""

    record: EnrichmentRound
    outcomes: tuple[OutcomeRecord, ...] = ()
    state: Optional[_State] = None
    added: _Added = _Added()
    stop: Optional[StopReason] = None
    directives: tuple[tuple[str, SourceDirective], ...] = ()

    def directives_for(self, identity: str) -> tuple[SourceDirective, ...]:
        return tuple(
            directive
            for gap_identity, directive in self.directives
            if gap_identity == identity
        )


def _round(
    *,
    number: int,
    searched: Sequence[Gap],
    state: _State,
    provider: ResearchProvider,
    request: ResearchProviderRequest,
    transport: MaterialTransport,
    ladder: StrengthLadder,
    now: datetime,
    client_ceiling: Optional[Strength],
    approved_positions: Sequence[str],
    budget: Optional[CallBudget],
) -> _RoundOutcome:
    """Search, re-assess, recompute — and commit all three or none of them."""

    gap_ids = tuple(gap.gap_id for gap in searched)
    signal_id = state.core.signal_ids[0]
    try:
        directives = _directives(searched)
        search = _search_request(request, directives, now)
    except EnrichmentError as exc:
        # This module's own refusal, so it is this module's own words.
        return _failed_round(number, gap_ids, f"no search could be built: {exc}")
    except (ValueError, TypeError) as exc:
        return _failed_round(
            number, gap_ids, f"no search could be built ({type(exc).__name__})"
        )
    # Only the directives the request actually carries: the provider contract
    # bounds a request at twenty, and a gap whose query was cut is a gap this
    # round did not search for.
    asked = {directive.directive_id for directive in search.source_directives}
    taken = tuple(
        (gap.gap_id, directive)
        for gap, directive in zip(searched, directives)
        if directive.directive_id in asked
    )

    try:
        result = execute_research(provider, search)
    except Exception as exc:  # noqa: BLE001 — sanitized, never the provider's text
        return _failed_round(
            number,
            gap_ids,
            f"the research provider did not answer ({type(exc).__name__})",
            directives=taken,
        )
    artifact: Optional[NormalizedResearchArtifact] = getattr(result, "artifact", None)
    if artifact is None:
        return _failed_round(
            number,
            gap_ids,
            f"the search returned no artifact ({result.outcome.value})",
            directives=taken,
        )

    if budget is not None:
        refusal = budget.spend(scope=OutcomeScope.SIGNAL, scope_key=signal_id)
        if refusal is not None:
            return _failed_round(
                number,
                gap_ids,
                "the extended assessment was refused before it was made",
                directives=taken,
                outcomes=(refusal,),
                stop=StopReason.BUDGET_EXHAUSTED,
            )

    assessor = ExtendedEvidenceAssessor(transport, ladder=ladder)
    try:
        assessed = assess_artifact(artifact, transport=assessor)
    except EvidenceAssessmentError as exc:
        return _failed_round(
            number,
            gap_ids,
            assessor.failure or str(exc),
            directives=taken,
            calls=assessor.calls,
        )

    try:
        candidate, added = _merged(
            state.core, assessed, assessor, ladder, client_ceiling
        )
    except EvidenceCoreError as exc:
        return _failed_round(
            number,
            gap_ids,
            f"the retrieved material does not form a core version: {exc}",
            directives=taken,
            calls=assessor.calls,
        )

    described = describe_material(
        core=candidate,
        transport=transport,
        approved_positions=approved_positions,
        budget=budget,
    )
    calls = assessor.calls + described.calls
    if described.features is None:
        refused = any(
            item.state_code is StateCode.BUDGET_EXHAUSTED
            for item in described.outcomes
        )
        return _failed_round(
            number,
            gap_ids,
            "the core version was not described, so it was not committed",
            directives=taken,
            calls=calls,
            # A recomputation that did not answer leaves the standing
            # description in force, so it is not the S-02 state of a signal
            # that has none: that SKIP is dropped and the round record carries
            # what happened. Budget exhaustion is the other case — §0.4 ends
            # the work that needed the call, and the refusal is its SKIP.
            outcomes=tuple(
                item
                for item in described.outcomes
                if item.state_code is not StateCode.MATERIAL_DESCRIPTION_FAILED
            ),
            stop=StopReason.BUDGET_EXHAUSTED if refused else None,
        )

    added = replace(
        added, new_asset=len(described.assets) > len(state.assets)
    )
    # The closure list belongs to the version the closure produced (§2.5), and
    # which gaps closed is known only once the recomputation has run. Only the
    # gaps whose query the request carried, which is the test E-07 is closed on
    # too: a core naming a gap the loop then abandoned would record a closure no
    # gap stands behind.
    carried = {identity for identity, _ in taken}
    committed = replace(
        candidate,
        closed_gaps=candidate.closed_gaps
        + tuple(
            gap.gap_id
            for gap in searched
            if gap.gap_id in carried and _closes(gap, added)
        ),
    )
    return _RoundOutcome(
        record=EnrichmentRound(
            number=number,
            gap_ids=gap_ids,
            artifact_ref=(assessed.artifact_id, research_artifact_digest(assessed)),
            observations_added=len(committed.observations) - len(state.core.observations),
            claims_added=len(committed.evidence_claims)
            - len(state.core.evidence_claims),
            usable_claims_added=added.usable_claims,
            core_version=committed.version,
            calls=calls,
        ),
        outcomes=tuple(described.outcomes),
        state=_State(
            core=committed,
            features=described.features,
            assets=described.assets,
            calls=state.calls,
        ),
        added=added,
        directives=taken,
    )


def _closes(gap: Gap, added: _Added) -> bool:
    """Did what a round added close this gap? Code's, from what entered the core.

    One test per kind, and each is a property of the material rather than a
    reading of it: an evidence gap asks for material the core can reason from
    and a round that produced a usable claim produced it, while a
    counter-evidence gap asks for material that runs against what the core
    already holds — which is what a conflicting verdict and a recorded
    contradiction are, and which a usable claim agreeing with the core is not.

    The kinds code has no test for are not closed here. S-03 may say that the
    search produced material, and may not say that the material establishes a
    reader connection or an interpretation; those are S-04's. Saying it anyway
    would not be a harmless overstatement, because a closure ends the loop's
    search for what still blocks the decision.
    """

    if gap.kind is GapKind.FIGURE_PROVENANCE:
        return added.own_figure
    if gap.kind is GapKind.ASSET:
        return added.new_asset
    if gap.kind is GapKind.COUNTER_EVIDENCE:
        return added.counter_material
    return gap.kind is GapKind.EVIDENCE and added.usable_claims > 0


def _failed_round(
    number: int,
    gap_ids: tuple[str, ...],
    failure: str,
    *,
    directives: tuple[tuple[str, SourceDirective], ...] = (),
    calls: int = 0,
    outcomes: tuple[OutcomeRecord, ...] = (),
    stop: Optional[StopReason] = None,
) -> _RoundOutcome:
    return _RoundOutcome(
        record=EnrichmentRound(
            number=number, gap_ids=gap_ids, calls=calls, failure=failure
        ),
        outcomes=outcomes,
        stop=stop,
        directives=directives,
    )


def _resolved(signal_id: str, gap: Gap) -> OutcomeRecord:
    """§1, ARP: "Gap closed → RESOLVE"."""

    return OutcomeRecord(
        outcome=ArpOutcome.RESOLVE,
        state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
        scope=OutcomeScope.SIGNAL,
        scope_key=signal_id,
        reason=(
            f"gap {gap.gap_id} ({gap.kind.value}) was closed by core version "
            f"{gap.closure}: {gap.blocks.stage} needed "
            f"{gap.blocks.decision}"
        ),
    )


# ===========================================================================
# The search (§1, Seam: SourceDirective, ResearchProviderRequest, providers)
# ===========================================================================


def _directives(searched: Sequence[Gap]) -> tuple[SourceDirective, ...]:
    """One discovery directive per open gap, from the gap's own description."""

    return tuple(
        SourceDirective(
            directive_id=gap.gap_id[:120],
            priority=SourcePriority.DISCOVERY,
            kind=SourceDirectiveKind.QUERY,
            value=" ".join(gap.description.split())[:2000],
            # Enrichment material is not what the signal was retrieved for, so
            # a round that finds none of it is not a failed retrieval of the
            # signal itself.
            material=False,
        )
        for gap in searched
    )


def _search_request(
    request: ResearchProviderRequest,
    directives: Sequence[SourceDirective],
    now: datetime,
) -> ResearchProviderRequest:
    """The run's own research request, re-aimed at the open gaps.

    Identity, strategy and freshness boundary are the run's: a round that
    searched under another configuration would put material into the core that
    the run's own artifact could not be checked against. What changes is the
    directives — the gaps' queries, and the client's preferred and excluded
    sources carried across so that its source policy still holds. The required
    directives are not carried: that source has been retrieved already, and
    asking for it again returns the material the core has.

    The provider bounds a request at twenty directives, and the exclusions are
    carried whole whatever else has to go: a preferred source the bound cut is
    a source the round did not ask for, while an excluded source the bound cut
    is a source the client prohibited and the round would research anyway. A
    client whose exclusions leave room for no gap query at all has asked for a
    round that cannot be searched, and that is refused rather than sent.
    """

    excluded = tuple(
        directive
        for directive in request.source_directives
        if directive.priority is SourcePriority.EXCLUDED
    )
    preferred = tuple(
        directive
        for directive in request.source_directives
        if directive.priority is SourcePriority.PREFERRED
    )
    room = MAX_DIRECTIVES - len(excluded)
    if room < 1:
        raise EnrichmentError(
            f"the client excludes {len(excluded)} sources and a request carries "
            f"{MAX_DIRECTIVES} directives, so no gap query fits beside them"
        )
    return ResearchProviderRequest(
        run_id=request.run_id,
        assignment_id=request.assignment_id,
        signal_id=request.signal_id,
        strategy=request.strategy,
        freshness=FreshnessRequirement(
            retrieved_not_before=request.freshness.retrieved_not_before,
            allow_open_discovery=True,
        ),
        source_directives=excluded + (tuple(directives) + preferred)[:room],
        requested_at=now,
    )


# ===========================================================================
# The merge (E-04, append-only)
# ===========================================================================


def _merged(
    core: EvidenceCore,
    artifact: NormalizedResearchArtifact,
    assessor: ExtendedEvidenceAssessor,
    ladder: StrengthLadder,
    client_ceiling: Optional[Strength],
) -> tuple[EvidenceCore, _Added]:
    """The next core version: everything the core held, plus what is new.

    The round's material is turned into core entities by the S-01 builder, so
    observations are built from support references and attributed by code there
    exactly as they are at v1 (I-03 at source). What this adds is the
    append-only rule: nothing already in the core is written twice, and nothing
    already in the core is dropped. A source the round returned under an ID the
    core already carries keeps the core's own record — the artifact is
    referenced by digest either way, so both readings stay recoverable.
    """

    fresh = build_evidence_core(
        artifact=artifact,
        assessment=assessor.assessment,
        core_id=core.core_id,
        ladder=ladder,
        client_ceiling=client_ceiling,
        version=core.version + 1,
    )
    known_claims = {item.evidence_claim_id for item in core.evidence_claims}
    known_observations = {item.observation_id for item in core.observations}
    known_sources = {item.source_id for item in core.sources}

    claims = tuple(
        item
        for item in fresh.evidence_claims
        if item.evidence_claim_id not in known_claims
        and not (set(item.observation_refs) & known_observations)
    )
    kept = {ref for item in claims for ref in item.observation_refs}
    observations = tuple(
        item for item in fresh.observations if item.observation_id in kept
    )
    sources: tuple[NormalizedSource, ...] = tuple(
        item for item in fresh.sources if item.source_id not in known_sources
    )

    merged_claims = known_claims | {item.evidence_claim_id for item in claims}
    merged_sources = known_sources | {item.source_id for item in sources}
    uncertainties = _carried(
        core.uncertainties, fresh.uncertainties, merged_claims, merged_sources
    )
    contradictions = _carried(
        core.contradictions, fresh.contradictions, merged_claims, merged_sources
    )
    refs = core.research_artifact_refs
    reference = (artifact.artifact_id, research_artifact_digest(artifact))
    if reference not in refs:
        refs = refs + (reference,)

    return (
        EvidenceCore(
            core_id=core.core_id,
            version=core.version + 1,
            signal_ids=core.signal_ids,
            research_artifact_refs=refs,
            sources=core.sources + sources,
            observations=core.observations + observations,
            evidence_claims=core.evidence_claims + claims,
            readiness=_readiness(core, claims, uncertainties, contradictions),
            uncertainties=core.uncertainties + uncertainties,
            contradictions=core.contradictions + contradictions,
            closed_gaps=core.closed_gaps,
        ),
        _Added(
            usable_claims=sum(1 for item in claims if item.usable),
            own_figure=any(_is_own_figure(item) for item in observations),
            counter_material=bool(contradictions)
            or any(
                item.verdict is EvidenceDisposition.CONFLICTING for item in claims
            ),
        ),
    )


def _readiness(
    core: EvidenceCore,
    claims: Sequence[EvidenceClaim],
    uncertainties: Sequence[UncertaintyAssessment],
    contradictions: Sequence[Contradiction],
) -> EvidenceReadiness:
    """The merged core's readiness, by the rule ``assess_artifact`` derives it with.

    A round never makes a core readier than it was: what the assessment could
    not accept before is still in the core, and the core is append-only. So the
    only transition a round can cause is ``READY`` → ``NEEDS_REVIEW``, from a
    claim the assessment did not accept, an unresolved contradiction or an
    unresolved material uncertainty — the three findings §125 derives that
    readiness from. ``INSUFFICIENT`` cannot arise here, because a core with no
    usable claim never reaches S-02 at all.
    """

    if core.readiness is not EvidenceReadiness.READY:
        return core.readiness
    if any(not claim.usable for claim in claims):
        return EvidenceReadiness.NEEDS_REVIEW
    if any(
        item.resolution is ResolutionStatus.UNRESOLVED for item in contradictions
    ):
        return EvidenceReadiness.NEEDS_REVIEW
    if any(
        item.materiality is UncertaintyMateriality.MATERIAL
        and item.resolution is ResolutionStatus.UNRESOLVED
        for item in uncertainties
    ):
        return EvidenceReadiness.NEEDS_REVIEW
    return EvidenceReadiness.READY


def _carried(
    held: Sequence[Any],
    found: Sequence[Any],
    claims: set[str],
    sources: set[str],
) -> tuple[Any, ...]:
    """The uncertainties or contradictions a round adds.

    Only the ones the merged core can resolve: E-04's referential integrity is
    what makes the core checkable, and an uncertainty pointing at a claim the
    merge did not take would make the version unreadable rather than richer.
    """

    known = {_identity(item) for item in held}
    return tuple(
        item
        for item in found
        if _identity(item) not in known
        and set(item.evidence_ids) <= claims
        and set(item.source_ids) <= sources
    )


def _identity(item: Any) -> str:
    if isinstance(item, UncertaintyAssessment):
        return item.uncertainty_id
    if isinstance(item, Contradiction):
        return item.contradiction_id
    raise EnrichmentError(  # pragma: no cover - the core holds only these two
        f"{type(item).__name__} is not a core annotation"
    )
