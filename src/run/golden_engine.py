"""The canonical engine, executing: real S-00…S-13 in order (Issue #351, SL-6.5).

SL-1 built a harness of typed pass-throughs and SL-3…SL-6 built the thirteen
stages in isolation; until this module, **no runtime importer reached a stage
function at all**. This is the wiring that closes that gap: one real material
through the real stages, in ``CANONICAL_TOPOLOGY`` order, with the typed
artifact each produces carried to the consumer that declares it by ID *and*
version through :class:`~src.run.run_workspace.RunWorkspace`.

What this module is, and is not
-------------------------------
It **wires**; it decides nothing. Every editorial judgment belongs to the stage
that declares it, every authority is read from its own production producer, and
nothing here invents a configuration value, a default or a fallback:

- the ten model boundaries are #361's :func:`golden_engine_transports` bindings,
  handed to the stage whose Protocol each implements. This module adds no
  provider and no second call path (see :class:`_CallMeter`);
- the client's fit rules, destinations, contracts, voice, forbidden list,
  destination rules, audience profile and Reference Library come from #337's,
  #363's and #368's producers, through :func:`golden_engine_configuration`;
- ``StrengthLadder`` is adapted from the universal authority the register
  already carries (:func:`universal_strength_ladder`) — the seam the read-only
  interface audit of 2026-09-30 identified as having no producer;
- ``UnitFacts`` is **lifted**, never classified (:func:`unit_facts`): the two
  values are #365's, persisted on the intake record before S-00 saw it, and a
  record that states neither produces ``UnitFacts()`` with both ``None``, which
  S-07's rules read as "the unit states nothing" and fail closed on. A record
  that states nothing and a lift that produced nothing are **not** the same
  state, and S-07 keeps them apart: the first is facts whose values are
  ``None``, and the second is no facts at all, which the stage refuses rather
  than decides on.

It also does not **run** the seams it wires. Every verification of this slice
uses deterministic typed test doubles satisfying the core's own Protocols
(owner clarification, 2026-09-30): a green suite here means the wiring is built
and typed, not that a provider was ever called.

The four things a wiring that merely ran the stages in order would miss
----------------------------------------------------------------------
Each of these is orchestration — no stage can do it, because no stage can see
what it needs to:

1. **the bounded edit loop.** ``L_edit`` routes S-13 → S-12, and S-12's target
   is ``revise_prose``. A real destination is therefore
   ``S-12 → S-13 → (revise → S-13)``, bounded at the approved-plan key
   ``<plan_id>/v<version>``. The second edit on one approved plan is refused by
   the ledger and the publication is skipped;
2. **REPLAN record propagation.** ``propose_strategies`` checks the authorizing
   record rather than trusting the attempt number, so the harness keeps the
   route it was handed and gives it back on the next attempt. Re-calling the
   stage is not enough;
3. **the F-4 sibling truth re-check.** After any S-04 re-entry commits a new
   boundary version, every already-accepted sibling verdict of the unit is
   re-checked against it — one truth call each, V-T02 only — before anything
   may reach S-14. No stage knows which siblings were accepted;
4. **barrier B1's ``expected_destinations``** (seam 11), which #305 made a
   required argument precisely so that the set is declared by the harness and
   not inferred from the plans a caller happened to pass.

Where the run stops
-------------------
At S-13. S-14 and S-15 are #308's and SL-12's, and a stage of the topology that
has no implementation stops the run rather than being papered over
(:class:`StageNotWiredError`) — the one rule this module keeps from the
pass-through harness it replaces, and the reason a pass-through cannot reappear
quietly.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2–§0.4,
§1–§5.4; ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2,
§2.3, §4.1, §4.2; ``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md``
§0.1.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NamedTuple, Optional, Protocol

from src.editorial.decision_contract import DecisionLensProfileIdentity
from src.editorial.decision_lens_evaluator import DecisionLensEvaluator
from src.editorial.source_eligibility import SourceEligibilityTransport
from src.editorial_core.anchor import (
    Anchor,
    AnchorDecision,
    choose_anchor,
    write_anchor,
)
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeRecord,
    OutcomeScope,
)
from src.editorial_core.candidate_strategies import (
    CandidateSet,
    EditorialStrategy,
    StrategyContract,
    propose_strategies,
    write_candidate_set,
)
from src.editorial_core.destinations import (
    ContractDestinations,
    Destination,
    DestinationDecision,
    DestinationDecisionSet,
    UnitFacts,
    decide_destinations,
    destination_scope_key,
    write_destination_decisions,
)
from src.editorial_core.editorial_units import (
    EditorialUnit,
    create_unit,
    run_split_candidate,
    write_unit,
)
from src.editorial_core.enrichment import Gap, GapStatus, enrich, open_gaps
from src.editorial_core.evidence_core import (
    EvidenceCore,
    StrengthLadder,
    retrieve_evidence_core,
)
from src.editorial_core.executable_plan import (
    AdaptationContract,
    DestinationRules,
    ExecutablePlan,
    ForbiddenItem,
    adapt_strategy,
    write_plan,
)
from src.editorial_core.interpretation_boundary import (
    DetectedInterpretation,
    InterpretationBoundary,
    ProbeFamily,
    commit_boundary_version,
    decide_boundary,
    probe_families,
    re_enter_boundary,
)
from src.editorial_core.material_features import (
    Asset,
    MaterialFeatures,
    MaterialNote,
    describe_material,
)
from src.publishing.publication_markers import active_client
from src.editorial_core.publication import (
    FINGERPRINTS_DIRECTORY,
    AcceptedText,
    Fingerprint,
    PackageRecord,
    publish_in_shadow,
    write_fingerprint_to_ledger,
)
from src.editorial_core.plan_check import (
    BarrierRound,
    PlanVerdict,
    approval_holds,
    check_plan,
    plan_check_records,
    recheck_after_boundary_commit,
    run_barrier,
    write_approved_plan,
    write_barrier_round,
    write_plan_verdict,
)
from src.editorial_core.relevance_screen import (
    RelevanceAssessment,
    screen_relevance,
)
from src.editorial_core.signal_selection import (
    ContractFitRules,
    PortfolioFingerprint,
    SignalSelection,
    select_signal,
)
from src.editorial_core.strategy_selection import (
    StrategySelection,
    select_strategy,
    write_strategy_selection,
)
from src.editorial_core.text_check import (
    BOUNDARY_COUNTER,
    PriorPublication,
    TextFingerprint,
    TextResult,
    TextVerdict,
    affected_siblings,
    check_text,
    recheck_siblings_after_boundary_commit,
    text_check_records,
    verdict_id,
)
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.editorial_core.writer import (
    Text,
    VoiceBrief,
    revise_prose,
    write_prose,
    write_text,
)
from src.knowledge.destination_rules import rule_catalogue
from src.knowledge.ladder import parse_universal_ladder
from src.knowledge.loader import KnowledgeBase, LoadedCheck, load_register
from src.knowledge.validator import DEFAULT_LADDER_NAME, LADDERS_DIR_NAME
from src.research.assessment import EvidenceJudgmentTransport
from src.research.provider import ResearchProvider, ResearchProviderRequest
from src.run.call_budget import RunCallBudgetExceededError
from src.run.call_budget_arp import (
    ArpCallBudget,
    DestinationProgress,
    DestinationState,
)
from src.run.expected_destinations import (
    ExpectedDestinationsError,
    expected_destinations,
)
from src.run.run_context import RunContext
from src.run.run_summary import DestinationFirstPass, RunScope
from src.run import stage_routing
from src.run.run_workspace import (
    DeciderKind,
    EntityIndexEntry,
    EntityRef,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
    file_digest,
)
from src.run.signal_adapter import (
    DOMAIN_FIELD,
    RISK_FIELD,
    golden_engine_fit_rules,
    selection_candidate,
    stated_single_value,
)
from src.run.transports import GoldenEngineTransports
from src.strategy.adaptation_contract import adaptation_contract
from src.strategy.audience_profile import AudienceProfile, audience_profile
from src.strategy.business_config import EditorialRole
from src.strategy.client_contract import (
    CONTRACT_FILE,
    ClientContract,
    client_contract,
    contract_destinations,
    voice_brief,
)
from src.strategy.execution_context import (
    AudienceSelection,
    ConfigurationIdentity,
    DecisionLensEditorialStrategyView,
)
from src.strategy.reference_library import ReferenceLibrary, reference_library
from src.strategy.strategy_contract import strategy_contract

#: What the StageRecords of a canonical run say produced them. Not a stage
#: module's own name — the stage is in ``created_by.stage`` — but the layer that
#: executed it, so that a reader comparing two runs can tell a canonical
#: execution from anything else by this value alone.
GOLDEN_ENGINE_COMPONENT: Final[str] = "golden-engine"

#: The serialization a StageRecord's ``request_digest`` is taken over. Bump it
#: only when the meaning of the payload changes, never when a request does —
#: the digest is how a changed request is noticed.
CANONICAL_REQUEST_SERIALIZATION: Final[str] = "golden-engine-stage-requests-v1"

#: The run harness stamps every execution (the editorial core reads no clock),
#: one fixed step apart, so that one run's trace is the same shape whatever the
#: machine's speed.
_STAGE_SECONDS: Final[int] = 1

#: Entity types, as Step 1 names them. Written out where the harness itself
#: writes the entity, which is every stage that ships no ``write_*`` helper of
#: its own (S-00 … S-03, and S-13).
_SELECTION_ENTITY_TYPE: Final[str] = "E-01.selection"
_CORE_ENTITY_TYPE: Final[str] = "E-04"
_RELEVANCE_ENTITY_TYPE: Final[str] = "E-04.relevance_ref"
_FEATURES_ENTITY_TYPE: Final[str] = "E-05"
_ASSETS_ENTITY_TYPE: Final[str] = "E-06"
_NOTES_ENTITY_TYPE: Final[str] = "MaterialNotes"
_GAPS_ENTITY_TYPE: Final[str] = "E-07"
_INTERPRETATION_ENTITY_TYPE: Final[str] = "E-08"
_BOUNDARY_ENTITY_TYPE: Final[str] = "E-09"
_TEXT_ENTITY_TYPE: Final[str] = "E-15"
_TEXT_VERDICT_ENTITY_TYPE: Final[str] = "TextVerdict"

#: The stages this harness calls for real, in the registry's own order. Listed
#: so that :func:`_wired` can answer "is every declared stage accounted for"
#: without re-deriving it from the code that calls them.
WIRED_STAGES: Final[tuple[str, ...]] = (
    "S-00",
    "S-01",
    "S-02",
    "S-03",
    "S-04",
    "S-05",
    "S-06",
    "S-07",
    "S-08",
    "S-09",
    "S-10",
    "S-11",
    "S-12",
    "S-13",
    "S-14",
)

#: The one stage of the topology this engine does not execute. S-15 is SL-12's
#: and has no implementation to call — so the run ends after S-14 and says so,
#: rather than standing a pass-through in for it, which is exactly what #351
#: exists to remove. S-14 joined the wired stages in #308, in **shadow**: it
#: packages what can be packaged and fingerprints every accepted text, and
#: reaches no provider, no image pipeline and no marker store.
UNWIRED_STAGES: Final[tuple[str, ...]] = ("S-15",)

#: ``E-16`` as the run workspace and the trace name it.
_FINGERPRINT_ENTITY_TYPE: Final[str] = "E-16"


class GoldenEngineError(RuntimeError):
    """The engine was asked for a run it cannot honestly make."""


class StageNotWiredError(GoldenEngineError):
    """The topology declares a stage this harness has no implementation for.

    The pass-through harness's rule, kept: "a walking skeleton that quietly
    skips a stage is not the canonical engine walking". What changed is only
    what satisfies it — a real stage call rather than a typed pass-through.
    """


# ===========================================================================
# The one thing the harness puts between a stage and #361's binding
# ===========================================================================


class _Completes(Protocol):
    """The shape all ten ``editorial_core`` transport Protocols declare."""

    def complete(self, *, instructions: str, request: str) -> str: ...


def request_digest(requests: Sequence[tuple[str, str]]) -> str:
    """``sha256:<hex>`` over the requests one stage execution issued, in order.

    §4.2 gives a StageRecord one ``request_digest`` and P8 is why it is a
    digest rather than the text: "a request digest proves which request was
    made without carrying what it said". Two stages make two calls per
    execution (S-04 generate and probe, S-13 truth and execution), so the one
    value is taken over the ordered sequence — always the same rule, so the
    field has one meaning for every stage rather than one meaning for the
    single-call stages and another for the rest.
    """

    payload = json.dumps(
        {
            "serialization": CANONICAL_REQUEST_SERIALIZATION,
            "requests": [
                {"instructions": instructions, "request": request}
                for instructions, request in requests
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _CallMeter:
    """#361's binding, and a record of what was asked of it.

    Not a second transport layer and not a provider: it holds the binding
    :func:`~src.run.transports.golden_engine_transports` built, forwards the
    two strings unchanged and returns the answer, exactly as that module's own
    ``_NamedTransport`` holds the provider core. It performs no provider call
    and carries no model, no client and no instructions of its own.

    It exists because §4.2 asks every model-deciding StageRecord for a request
    digest and no stage returns the request it sent. Without this, the one
    field that distinguishes "this stage really called a model" from "this
    stage was wired to a provider that answers nothing" could not be filled —
    which is one of the acceptance criteria this slice is judged on.
    """

    def __init__(self, binding: _Completes) -> None:
        self._binding = binding
        self._requests: list[tuple[str, str]] = []

    @property
    def binding(self) -> _Completes:
        """The production binding, unchanged, for a caller that wants it."""

        return self._binding

    @property
    def calls(self) -> int:
        return len(self._requests)

    def mark(self) -> int:
        """Where the next execution's requests begin."""

        return len(self._requests)

    def since(self, mark: int) -> tuple[tuple[str, str], ...]:
        """The requests issued after ``mark``, in order."""

        return tuple(self._requests[mark:])

    def complete(self, *, instructions: str, request: str) -> str:
        self._requests.append((instructions, request))
        return self._binding.complete(instructions=instructions, request=request)


class _Meters(NamedTuple):
    """One meter per #361 binding, under the name that binding carries."""

    material: _CallMeter
    boundary: _CallMeter
    anchor: _CallMeter
    strategy: _CallMeter
    ranking: _CallMeter
    segmentation: _CallMeter
    plan_check: _CallMeter
    barrier: _CallMeter
    writer: _CallMeter
    text_check: _CallMeter


def _meters(transports: GoldenEngineTransports) -> _Meters:
    """Meter each of the ten bindings, by name.

    By name and never through one shared object: ``transports.py``'s whole
    reason for ten named classes over one core is that "the named type is the
    unit of routing", and a harness that collapsed them into one would be able
    to hand the evidence-judgment boundary to a stage that judges no evidence.
    """

    return _Meters(
        material=_CallMeter(transports.material),
        boundary=_CallMeter(transports.boundary),
        anchor=_CallMeter(transports.anchor),
        strategy=_CallMeter(transports.strategy),
        ranking=_CallMeter(transports.ranking),
        segmentation=_CallMeter(transports.segmentation),
        plan_check=_CallMeter(transports.plan_check),
        barrier=_CallMeter(transports.barrier),
        writer=_CallMeter(transports.writer),
        text_check=_CallMeter(transports.text_check),
    )


# ===========================================================================
# What the run is handed
# ===========================================================================


@dataclass(frozen=True, slots=True)
class GoldenEngineSeams:
    """Every boundary the canonical run is handed rather than constructs.

    Five, and they are five because the thirteen stages declare their model
    boundaries in three places: #361 bundled the ten that live in
    ``editorial_core``, and S-00's ``SourceEligibilityTransport`` and S-01's
    ``EvidenceJudgmentTransport`` sit outside that bundle with production
    implementations of their own (``scripts/streams/select_eligible_signal.py``
    and ``src/research/lifecycle.py``). The research provider and the Decision
    Lens evaluator are the existing pipeline's, reached in AD-05's allowed
    direction: S-01 wraps the research contract.
    """

    transports: GoldenEngineTransports
    research: ResearchProvider
    eligibility: SourceEligibilityTransport
    evidence_judgment: EvidenceJudgmentTransport
    relevance: DecisionLensEvaluator


@dataclass(frozen=True, slots=True)
class ResearchBinding:
    """S-01's wrap of the existing research and relevance contracts.

    The five configured inputs ``screen_relevance`` requires are legacy
    Decision-Lens types produced in ``src/editorial/decision_lifecycle.py`` and
    ``src/strategy/execution_context.py``. The harness reaches into that layer
    for them, which is AD-05's "S-01 wraps the research contract" and the
    allowed dependency direction; it is carried as one typed value so that a
    run states where each came from rather than assembling it inline.

    ``run_dir`` is the **legacy** content-package run directory, which is where
    ``research.json`` and ``decision.json`` are written create-once. It is not
    the canonical workspace: the canonical run references those two artifacts by
    path and digest (``DecisionRef``) rather than copying them, which is the
    wrap relationship Step 0 describes.
    """

    request: ResearchProviderRequest
    identity: ConfigurationIdentity
    strategy_view: DecisionLensEditorialStrategyView
    audience_selection: AudienceSelection
    lens_profile: DecisionLensProfileIdentity
    assignment_id: str
    run_dir: Path
    run_started_at: datetime


@dataclass(frozen=True, slots=True)
class GoldenEngineConfiguration:
    """The authorities a canonical run reads, each from its own producer.

    Assembled once, before S-00, and frozen: which contract a run executed
    against is decided by the code that loaded it and never swapped underneath
    a stage. Every field here is a **hard** input except ``library``, which §3
    lists among S-11's inputs and lets degrade — and whose absence is recorded
    as ``REFERENCE_LIBRARY_UNAVAILABLE`` rather than passed over.
    """

    fit_rules: ContractFitRules
    role: EditorialRole
    contract: ClientContract
    destinations: ContractDestinations
    strategy: StrategyContract
    adaptation: AdaptationContract
    rules: Mapping[Destination, DestinationRules]
    brief: VoiceBrief
    forbidden: tuple[ForbiddenItem, ...]
    ladder: StrengthLadder
    audience: AudienceProfile
    families: tuple[ProbeFamily, ...]
    plan_checks: Mapping[str, LoadedCheck]
    text_checks: Mapping[str, LoadedCheck]
    knowledge: KnowledgeBase
    register_dir: Path
    library: Optional[ReferenceLibrary] = None

    @property
    def approved_positions(self) -> tuple[str, ...]:
        """The position IDs S-02's assets may cite (Step 1 §4).

        "Only from the contract", so the list is an input rather than something
        a description may assert. An empty tuple is the client having approved
        none, which S-02 reads as refusing every positional asset offered.
        """

        return tuple(item.position_id for item in self.strategy.positions)


def universal_strength_ladder(
    knowledge: KnowledgeBase, *, register_dir: Path
) -> StrengthLadder:
    """The run's ``StrengthLadder``, adapted from the universal authority.

    The seam the 2026-09-30 interface audit found: four stages require a
    ``ladder`` and nothing produced one, while the authority itself has existed
    since #294 — ``knowledge/ladders/default.md``, parsed by
    :func:`~src.knowledge.ladder.parse_universal_ladder`, which until now was
    called only by the validator and never for consumption.

    Two halves, and both are mechanical:

    - **which** ladder. The universal one, because Never Blank declares no
      ``claim_strength_ceiling``; a client that declares one restricts it, and
      that restriction travels as a plan slot of the Client Contract rather
      than as a second ladder (§4.1, and ``strength_ladder_version``'s own
      note). Nothing is invented here either way;
    - **what** it becomes. ``StrengthLadder(ladder_id, levels)`` takes the
      record's ID and the ``Wording`` column of its ``## Levels`` table, in the
      table's own order, weakest first. The wording is what a writer may say
      (U-4), which is exactly what ``StrengthLadder.wording`` returns, so no
      level is renamed, merged, reordered or added.

    Raises :class:`GoldenEngineError` when the register holds no ladder: a run
    whose claims have nothing to be measured against would record a strength on
    a ladder nobody wrote.
    """

    path = Path(register_dir) / LADDERS_DIR_NAME / DEFAULT_LADDER_NAME
    loaded = next(
        (item for item in knowledge.records if Path(item.record.path) == path),
        None,
    )
    if loaded is None:
        raise GoldenEngineError(
            f"{path} is not in the loaded register, so this run has no strength "
            "ladder. Four stages require one (S-01b, S-03, S-04, S-06) and §7 "
            "gives it one authority; a ladder the engine chose for itself would "
            "be a ceiling nobody approved"
        )
    levels = parse_universal_ladder(loaded.record)
    return StrengthLadder(
        ladder_id=loaded.identity,
        levels=tuple(level.wording for level in levels),
    )


def unit_facts(signal: Mapping[str, Any]) -> UnitFacts:
    """The unit's topic and risk facts, lifted from the lineage that holds them.

    S-07 requires ``facts: UnitFacts`` and nothing produced it. §1's Inputs
    column says where the values come from: they "come from the core and
    boundary … **lifted out and handed over** rather than discovered here,
    exactly as ``SelectionCandidate`` lifts the signal's ``topic_key``". So this
    lifts, and what it lifts are the two fields #365 persists on the intake
    record before S-00 ever reads it — the same two, with the same spelling and
    the same single-value discipline, read through
    :func:`~src.run.signal_adapter.stated_single_value` so that there is one
    answer to "what does this record state" rather than two.

    **Nothing is inferred, classified, defaulted or invented.** Classification
    is #365's and the admitted vocabulary is #363's. A record that states
    neither value produces ``UnitFacts()`` with both ``None``, which is
    meaningful and fail-closed: "``None`` means the unit states nothing, which
    is not the same as stating something the contract allows", and a contract
    row naming refused topics cannot show that an unnamed topic is not one of
    them.
    """

    return UnitFacts(
        topic_key=stated_single_value(signal, DOMAIN_FIELD),
        risk_level=stated_single_value(signal, RISK_FIELD),
    )


def golden_engine_configuration(
    *,
    register_dir: Path,
    client_dir: Path,
    role: EditorialRole,
    root: Optional[Path] = None,
    today: Optional[date] = None,
) -> GoldenEngineConfiguration:
    """Load every authority a canonical run executes against, once.

    Each from its own producer and none of them reimplemented here: this
    function is a list of calls, deliberately, because the one thing it must
    not become is a second place where a configured value is decided.

    ``role`` is handed in rather than resolved: which editorial role a run
    executes under comes from the assignment, and a harness that picked one
    would be choosing what a candidate is judged against.
    """

    knowledge = load_register(register_dir, today=today)
    contract = client_contract(directory=client_dir)
    catalogue = rule_catalogue(
        register=register_dir, contract=client_dir / CONTRACT_FILE, today=today
    )
    return GoldenEngineConfiguration(
        fit_rules=golden_engine_fit_rules(directory=client_dir),
        role=role,
        contract=contract,
        destinations=contract_destinations(contract),
        strategy=strategy_contract(directory=client_dir),
        adaptation=adaptation_contract(
            directory=client_dir,
            register=register_dir,
            root=root,
            today=today,
        ),
        rules={
            destination: catalogue.rules_for(destination)
            for destination in Destination
        },
        brief=voice_brief(contract, root=root),
        forbidden=contract.forbidden,
        ladder=universal_strength_ladder(knowledge, register_dir=register_dir),
        audience=audience_profile(register_dir, directory=client_dir),
        families=probe_families(knowledge),
        plan_checks=plan_check_records(knowledge),
        text_checks=text_check_records(knowledge),
        knowledge=knowledge,
        register_dir=register_dir,
        library=reference_library(directory=client_dir),
    )


# ===========================================================================
# What one execution produced
# ===========================================================================


class CanonicalExecution(NamedTuple):
    """One canonical execution of S-00…S-13, and what the ledger needs of it.

    The harness that owns the manifest and the ledger takes this: the records,
    the identities the run actually produced, and the summary facts §3.3 asks
    for that no single StageRecord carries.
    """

    records: tuple[StageRecord, ...]
    signal_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    scopes: tuple[RunScope, ...]
    first_pass: tuple[DestinationFirstPass, ...]
    split_candidate: bool
    #: Destinations holding an accepted text at the end of the run. Not a
    #: publication: S-14 is #308's, and nothing here publishes.
    accepted: tuple[Destination, ...]
    #: Where the run stopped, when it stopped before S-13. ``None`` for a run
    #: that reached the end of the wired topology.
    stopped_at: Optional[str] = None
    #: Every E-16 S-14 wrote, in destination order. Empty for a run that
    #: reached no accepted text — not for one that published nothing, because a
    #: shadow run still fingerprints what it accepted.
    fingerprints: tuple[Fingerprint, ...] = ()
    #: One package record per accepted text: built, required input unavailable,
    #: or no package type yet (#308).
    packages: tuple[PackageRecord, ...] = ()
    #: The durable E-16 records this run wrote, by the exact path each went to.
    #: Carried so the learning-record commit commits **these files** and not a
    #: glob of the ledger: the summary states that commit's status (§3.3), and
    #: a status over files nobody named would be a status about nothing.
    fingerprint_paths: tuple[Path, ...] = ()
    #: The verdict behind each accepted text, in destination order. Carried
    #: because the TextVerdict **entity** records its hints by check ID alone —
    #: the free text stays in the workspace (§3.3) — so what a soft check like
    #: V-S05 actually found is readable from the execution and from nowhere else.
    verdicts: tuple[TextVerdict, ...] = ()


# ===========================================================================
# The run
# ===========================================================================


def execute_canonical_topology(
    *,
    workspace: RunWorkspace,
    run_context: RunContext,
    seams: GoldenEngineSeams,
    configuration: GoldenEngineConfiguration,
    signal: Mapping[str, Any],
    binding: ResearchBinding,
    budget: ArpCallBudget,
    counters: Optional[AttemptCounterLedger] = None,
    now: Optional[datetime] = None,
    portfolio: Sequence[PortfolioFingerprint] = (),
    priors: Sequence[PriorPublication] = (),
    text_portfolio: Sequence[TextFingerprint] = (),
    ledger_dir: Optional[Path] = None,
) -> CanonicalExecution:
    """Execute the real S-00…S-13 over one intake record, and record every step.

    Returns a :class:`CanonicalExecution` in every case the stage contracts have
    an outcome for, including the runs that stop early: a refused signal, a core
    with no usable claim, a boundary admitting nothing and a unit with no
    eligible destination are all recorded ``SKIP``s (I-01), and a caller that
    had to catch an error would have nothing to write into the trace.

    It raises only for a run that cannot honestly be made: a topology stage with
    no implementation (:class:`StageNotWiredError`), or a stage precondition the
    harness itself broke — §6.2 has no state for a stage run out of order, and
    inventing one would hide a wiring defect behind an editorial-looking skip.
    """

    check_every_stage_is_wired()
    # The canonical path enters `stage_routing` here (NB-07a1). It never did:
    # the engine did not import the module, so `_STAGE` was empty for every
    # canonical call and both hooks inside the shared model client were silent
    # no-ops — #279's request evidence was absent for canonical runs, not merely
    # unused. One block covers the whole run, so a stage cannot be observed
    # outside it, and the routing object is per run because the usage entries
    # drained into each record belong to this run alone.
    with stage_routing.recording(stage_routing.StageRouting(run_id=run_context.run_id)):
        return _execute_canonical_topology(
            workspace=workspace,
            run_context=run_context,
            seams=seams,
            configuration=configuration,
            signal=signal,
            binding=binding,
            budget=budget,
            counters=counters,
            now=now,
            portfolio=portfolio,
            priors=priors,
            text_portfolio=text_portfolio,
            ledger_dir=ledger_dir,
        )


def _execute_canonical_topology(
    *,
    workspace: RunWorkspace,
    run_context: RunContext,
    seams: GoldenEngineSeams,
    configuration: GoldenEngineConfiguration,
    signal: Mapping[str, Any],
    binding: ResearchBinding,
    budget: ArpCallBudget,
    counters: Optional[AttemptCounterLedger],
    now: Optional[datetime],
    portfolio: Sequence[PortfolioFingerprint],
    priors: Sequence[PriorPublication],
    text_portfolio: Sequence[TextFingerprint],
    ledger_dir: Optional[Path],
) -> CanonicalExecution:
    """The run itself, inside the routing block its caller opened."""

    return _Run(
        trace=_Trace(workspace, run_context),
        meters=_meters(seams.transports),
        seams=seams,
        configuration=configuration,
        signal=signal,
        binding=binding,
        budget=budget,
        counters=counters if counters is not None else AttemptCounterLedger(),
        now=now or run_context.started_at,
        portfolio=tuple(portfolio),
        priors=tuple(priors),
        text_portfolio=tuple(text_portfolio),
        run_context=run_context,
        ledger_dir=ledger_dir,
        workspace=workspace,
    ).execute()


def check_every_stage_is_wired() -> None:
    """Every stage of the registry is either wired here or named as unwired.

    The pass-through harness's rule, and the reason it is kept: a stage the
    topology declares and the harness quietly passes over is not the canonical
    engine executing. What this slice changes is that "wired" now means a real
    stage call — so a pass-through put back in place of one would have to be
    declared here, in the open, rather than slipped into a table of writers.

    Public because it is the rule rather than an implementation detail of one
    run: a reader, and a test, can ask it without starting a run.
    """

    accounted = set(WIRED_STAGES) | set(UNWIRED_STAGES)
    missing = [
        stage.stage_id
        for stage in CANONICAL_TOPOLOGY.stages
        if stage.stage_id not in accounted
    ]
    if missing:
        raise StageNotWiredError(
            "the topology declares "
            + ", ".join(missing)
            + " and the Golden Engine has no implementation wired for it; a "
            "harness that quietly skips a stage is not the canonical engine "
            "executing, and standing a pass-through in for one is what this "
            "slice exists to remove"
        )


class _Trace:
    """The run's StageRecords, written as they happen (§4.2)."""

    def __init__(self, workspace: RunWorkspace, context: RunContext) -> None:
        self._workspace = workspace
        self._context = context
        self.records: list[StageRecord] = []

    def record(
        self,
        *,
        stage: str,
        scope_key: str,
        decider: DeciderKind,
        outputs: Sequence[EntityRef] = (),
        inputs: Sequence[EntityRef] = (),
        calls: int = 0,
        requests: Sequence[tuple[str, str]] = (),
        outcomes: Sequence[OutcomeRecord] = (),
    ) -> StageRecord:
        """Record one stage execution, and write it into ``trace/``."""

        seq = len(self.records)
        started = self._context.started_at + timedelta(
            seconds=seq * _STAGE_SECONDS
        )
        # The two observations this execution produced, taken before the record
        # is built so that nothing it spent can be attributed to the next one.
        # Outside a recording run both are empty, and the usage then states that
        # no response reported anything rather than claiming zero tokens.
        active = stage_routing.current()
        observed = active.take_usage(stage) if active is not None else ()
        requested = active.take_requests(stage) if active is not None else ()
        usage = stage_routing.UsageTotals.of(observed, calls=calls)
        routing_evidence = (
            {"requests": [item.as_evidence() for item in requested]}
            if requested
            else None
        )
        record = StageRecord(
            run_id=self._context.run_id,
            seq=seq,
            stage=stage,
            scope_key=scope_key,
            started_at=started,
            ended_at=started + timedelta(seconds=_STAGE_SECONDS),
            created_by=StageAttribution(
                stage=stage,
                component=GOLDEN_ENGINE_COMPONENT,
                decider=decider,
                # A model-deciding execution states the digest of what it sent;
                # one that made no call has nothing to digest, and says nothing
                # rather than a digest over an empty request.
                request_digest=request_digest(requests) if requests else None,
            ),
            inputs=tuple(inputs),
            outputs=tuple(outputs),
            # What this execution's calls actually cost, from the provider's own
            # usage (NB-07a1). Drained per stage, so a second execution of the
            # same stage carries only its own; measured or stated absent, never
            # a zero standing in for a number nobody read.
            calls=usage.as_calls(calls),
            routing=routing_evidence,
            outcomes=tuple(outcomes),
            status=StageStatus.COMPLETED,
        )
        self._workspace.write_stage_record(record)
        self.records.append(record)
        return record


def _decider(calls: int) -> DeciderKind:
    """Who decided this execution: the model it called, or the code that did not.

    Read off the stage's own call count rather than asserted, so that
    "every model-deciding record carries a request digest" stays exactly true
    for the stages whose call is conditional — S-09 makes none when one
    candidate survives code exclusion, and S-11 makes none when a deterministic
    check has already refused the plan.
    """

    return DeciderKind.MODEL if calls > 0 else DeciderKind.CODE


def _ref(entry: EntityIndexEntry) -> EntityRef:
    """One ``EntityIndexEntry`` as the lineage reference a StageRecord carries.

    Built from the **write that happened** — the index entry the workspace
    returned, with the digest it computed off the bytes on disk — so that a
    producer's claimed output and a consumer's claimed input resolve through the
    manifest to one file, by ID and version. A reference assembled beside the
    write would be a second, optimistic description of it.
    """

    return EntityRef(
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        version=entry.version,
        digest=entry.digest,
    )


def _refs(entries: Sequence[EntityIndexEntry]) -> tuple[EntityRef, ...]:
    return tuple(_ref(entry) for entry in entries)


def _text_ref(text: Text) -> EntityRef:
    """One E-15 version as the input reference S-13's record carries."""

    return EntityRef(
        entity_type=_TEXT_ENTITY_TYPE,
        entity_id=text.text_id,
        version=text.version,
        digest=text.content_digest,
    )


def _replan_to(
    outcomes: Sequence[OutcomeRecord], target: str
) -> Optional[OutcomeRecord]:
    """The REPLAN this stage recorded into ``target``, if it recorded one.

    Returned rather than acted on, because it is the record the next attempt has
    to show: #304's ``_authorized`` refuses a re-entry that cannot name the
    counter that paid for it at which scope, so the harness carries the record
    forward instead of re-calling the stage with a higher attempt number.
    """

    return next(
        (
            outcome
            for outcome in outcomes
            if outcome.outcome is ArpOutcome.REPLAN
            and outcome.route_target == target
        ),
        None,
    )


#: The scope key for a refusal that arrived before S-00 named the signal. It
#: cannot normally happen — S-00 sets the id before it spends — and exists so
#: that an exhaustion record never carries an empty scope key.
_UNIDENTIFIED: Final[str] = "unidentified-signal"


@dataclass
class _Lane:
    """One destination's state through S-08…S-13."""

    decision: DestinationDecision
    attempt: int = 1
    re_entry: Optional[OutcomeRecord] = None
    strategy: Optional[EditorialStrategy] = None
    plan: Optional[ExecutablePlan] = None
    verdict: Optional[PlanVerdict] = None
    #: S-09's selection, kept because E-16 records the tie-breaker that decided
    #: this destination's strategy and no other artifact carries it.
    selection: Optional[StrategySelection] = None
    text: Optional[Text] = None
    accepted: Optional[TextVerdict] = None
    skipped: bool = False
    reopened: bool = False
    plan_first_pass: bool = True
    text_first_pass: bool = True
    candidates: tuple[EntityRef, ...] = field(default_factory=tuple)

    @property
    def destination(self) -> Destination:
        return self.decision.destination


class _Run:
    """One canonical execution, as the object that carries its state.

    A class rather than a long function because the four pieces of
    orchestration this slice adds — the edit loop, the REPLAN records, the
    sibling re-check and the barrier rounds — are all about state that outlives
    one stage call, and threading it through free functions would put the state
    in the signatures instead of in one place that can be read.
    """

    def __init__(
        self,
        *,
        trace: _Trace,
        meters: _Meters,
        seams: GoldenEngineSeams,
        configuration: GoldenEngineConfiguration,
        signal: Mapping[str, Any],
        binding: ResearchBinding,
        budget: ArpCallBudget,
        counters: AttemptCounterLedger,
        now: datetime,
        portfolio: Sequence[PortfolioFingerprint],
        priors: Sequence[PriorPublication],
        text_portfolio: Sequence[TextFingerprint],
        run_context: RunContext,
        ledger_dir: Optional[Path],
        workspace: RunWorkspace,
    ) -> None:
        self.trace = trace
        self.meters = meters
        self.seams = seams
        self.cfg = configuration
        self.signal = signal
        self.binding = binding
        self.budget = budget
        self.counters = counters
        self.now = now
        self.portfolio = tuple(portfolio)
        self.priors = tuple(priors)
        self.text_portfolio = tuple(text_portfolio)
        self.workspace = workspace
        self.run_context = run_context
        self.ledger_dir = ledger_dir

        self.signal_id: str = ""
        #: The stage currently executing. Only §0.4's exhaustion handler reads
        #: it: a refusal that arrives from inside a transport has to be recorded
        #: against the stage that asked for the call, and guessing which one from
        #: the lane state would attribute it to whichever stage looks plausible.
        self.executing: str = "S-00"
        self.core: Optional[EvidenceCore] = None
        self.features: Optional[MaterialFeatures] = None
        self.assets: tuple[Asset, ...] = ()
        self.notes: tuple[MaterialNote, ...] = ()
        self.assessment: Optional[RelevanceAssessment] = None
        self.boundary: Optional[InterpretationBoundary] = None
        self.unit: Optional[EditorialUnit] = None
        self.anchor: Optional[Anchor] = None
        self.decisions: Optional[DestinationDecisionSet] = None
        self.barrier: Optional[BarrierRound] = None
        self.lanes: dict[Destination, _Lane] = {}
        self.barrier_round = 0
        self.split_candidate = False
        self.lineage: dict[str, EntityRef] = {}
        self.fingerprints: tuple[Fingerprint, ...] = ()
        self.packages: tuple[PackageRecord, ...] = ()
        self.fingerprint_paths: tuple[Path, ...] = ()

    # ------------------------------------------------------------------
    # The whole run
    # ------------------------------------------------------------------

    def _at(self, stage: str) -> None:
        """Advance the stage cursor, and name the stage for the observers.

        One mechanism for two readers. §0.4's exhaustion handler needs to know
        which stage asked for the refused call, and ``stage_routing``'s hooks
        need the same name to attribute a request (#279) and a provider usage
        (NB-07a1) to the execution that made it. Keeping them one assignment is
        what stops them from disagreeing: a stage that advanced the cursor and
        not the name would have its tokens recorded against its predecessor.
        """

        self.executing = stage
        stage_routing.set_stage(stage)

    def execute(self) -> CanonicalExecution:
        try:
            return self._execute()
        except RunCallBudgetExceededError as exhausted:
            # §0.4, and the one case `ArpCallBudget` cannot refuse in advance: a
            # stage is admitted while a call remains and makes two. #171 refuses
            # the second before the provider — that property is not negotiable —
            # and the stop becomes ARP outcomes here rather than an exception out
            # of a run that has already paid for accepted work (R-3, §0.4.4).
            return self._budget_exhausted(exhausted)

    def _execute(self) -> CanonicalExecution:
        for stage, step in (
            ("S-00", self._s00),
            ("S-01", self._s01),
            ("S-02", self._s02),
            ("S-03", self._s03),
            ("S-04", self._s04),
            ("S-05", self._s05),
            ("S-06", self._s06),
            ("S-07", self._s07),
        ):
            self._at(stage)
            if not step():
                return self._finished(stopped_at=stage)
        for destination in self._order():
            self._plan(destination)
        if not self._barrier():
            return self._finished(stopped_at="S-11")
        self._produce_texts()
        self._s14()
        return self._finished()

    # ------------------------------------------------------------------
    # S-14 · publication and fingerprint, in shadow (#308)
    # ------------------------------------------------------------------

    def _s14(self) -> None:
        """Fingerprint every accepted text, and package what can be packaged.

        The shadow half of S-14, and the whole of what SL-7 asks for: the run
        measures what the canonical chain costs, and a measurement must not
        publish. Nothing here reaches a provider, an image pipeline or a marker
        store — not behind a flag, but because no such call exists on this path.

        ``calls=0``, because §1's Calls column is 0 and the stage takes no
        transport. A run that accepted nothing records no S-14 at all: there is
        no publication scope to record, and an empty record would make the
        indicators count a scope nobody reached.
        """

        self.executing = "S-14"
        accepted = [
            lane for lane in self._ordered_lanes() if lane.accepted is not None
        ]
        if not accepted:
            return
        unit = self._unit()
        texts: list[AcceptedText] = []
        for lane in accepted:
            if lane.text is None or lane.plan is None or lane.strategy is None:
                raise GoldenEngineError(
                    f"{lane.destination.value} holds an accepted verdict and "
                    "not the text, plan and strategy E-16 snapshots; a "
                    "fingerprint records what was accepted, and one assembled "
                    "from part of it would remember a text that never existed"
                )
            assert self.features is not None
            texts.append(
                AcceptedText(
                    text=lane.text,
                    decision=lane.decision,
                    plan=lane.plan,
                    strategy=lane.strategy,
                    features=self.features,
                    deciding_tiebreaker=(
                        None
                        if lane.selection is None
                        or lane.selection.deciding_tiebreaker is None
                        else lane.selection.deciding_tiebreaker.value
                    ),
                )
            )
        # No PackageInputs: a canonical run holds none of what the existing Wix
        # and LinkedIn builders require — it produces E-15 rather than a legacy
        # generated artifact, it calls no image pipeline, and it reads no
        # publication target. Each absence is recorded by name rather than
        # fabricated (owner decision, 2026-10-02).
        round_result = publish_in_shadow(
            accepted=tuple(texts),
            unit_id=unit.unit_id,
            run_id=self.run_context.run_id,
            client=active_client(),
        )
        outputs: list[EntityRef] = []
        durable: list[Path] = []
        for fingerprint in round_result.fingerprints:
            written = self.workspace.write_entity(
                stage="S-14",
                relative_path=(
                    f"{FINGERPRINTS_DIRECTORY}/{fingerprint.fingerprint_id}.json"
                ),
                entity_type=_FINGERPRINT_ENTITY_TYPE,
                entity_id=fingerprint.fingerprint_id,
                payload=fingerprint.as_entity(),
            )
            outputs.append(_ref(written))
            # And the durable copy: §3.2 retains E-16 indefinitely, because the
            # 90-day run workspace outlives nothing Portfolio Memory reads. The
            # path is kept, because the learning-record commit commits these
            # files by name.
            durable.append(
                write_fingerprint_to_ledger(
                    fingerprint,
                    month=f"{self.run_context.started_at.year:04d}-"
                    f"{self.run_context.started_at.month:02d}",
                    root=self.ledger_dir,
                )
            )
        self.fingerprints = round_result.fingerprints
        self.packages = round_result.packages
        self.fingerprint_paths = tuple(durable)
        self.trace.record(
            stage="S-14",
            scope_key=unit.unit_id,
            decider=DeciderKind.CODE,
            inputs=tuple(
                _text_ref(item.text) for item in texts
            ),
            outputs=tuple(outputs),
            calls=round_result.calls,
        )

    # ------------------------------------------------------------------
    # Budget exhaustion the wrap could not refuse in advance (§0.4)
    # ------------------------------------------------------------------

    def _budget_exhausted(
        self, exhausted: RunCallBudgetExceededError
    ) -> CanonicalExecution:
        """Record §0.4's four points and finish, rather than raising out.

        1. the refused call was not made — #171 refused it before the provider;
        2. the unit of work that needed it ends in ``SKIP``, which is the
           destination that was mid-flight when the refusal came, or the signal
           when nothing destination-scoped had started;
        3. destinations not yet started end in ``SKIP`` in **reverse**
           destination order, which :meth:`ArpCallBudget.exhaustion_outcomes`
           decides from the progress list;
        4. texts already accepted stay accepted — ``_finished`` reads them from
           the lanes, so nothing here has to preserve them.
        """

        progress = self._progress()
        mid = [
            item
            for item in progress
            if item.state is DestinationState.IN_PROGRESS
        ]
        refused = [
            self.budget.spend(
                scope=OutcomeScope.DESTINATION, scope_key=item.destination
            )
            for item in mid
        ] or [
            self.budget.spend(
                scope=OutcomeScope.SIGNAL,
                scope_key=self.signal_id or _UNIDENTIFIED,
            )
        ]
        outcomes = tuple(item for item in refused if item is not None)
        outcomes += self.budget.exhaustion_outcomes(progress)
        for item in mid:
            lane = self.lanes.get(Destination(item.destination))
            if lane is not None:
                lane.skipped = True
        self.trace.record(
            stage=self.executing,
            scope_key=self.signal_id or _UNIDENTIFIED,
            decider=DeciderKind.CODE,
            calls=0,
            outcomes=outcomes,
        )
        return self._finished(stopped_at=self.executing)

    def _progress(self) -> tuple[DestinationProgress, ...]:
        """How far each destination got, in the three states §0.4 distinguishes.

        Read off the lanes rather than tracked beside them: a destination holding
        an accepted verdict is ``TEXT_ACCEPTED``, one that was skipped or never
        reached a plan is ``NOT_STARTED``, and anything else is mid-flight — and
        mid-flight is where a refusal lands.
        """

        states: list[DestinationProgress] = []
        for lane in self._ordered_lanes():
            if lane.accepted is not None:
                state = DestinationState.TEXT_ACCEPTED
            elif lane.skipped or lane.plan is None:
                state = DestinationState.NOT_STARTED
            else:
                state = DestinationState.IN_PROGRESS
            states.append(
                DestinationProgress(
                    destination=lane.destination.value, state=state
                )
            )
        return tuple(states)

    def _finished(
        self, *, stopped_at: Optional[str] = None
    ) -> CanonicalExecution:
        return CanonicalExecution(
            records=tuple(self.trace.records),
            signal_ids=(self.signal_id,) if self.signal_id else (),
            unit_ids=() if self.unit is None else (self.unit.unit_id,),
            scopes=self._scopes(),
            first_pass=tuple(
                DestinationFirstPass(
                    destination=lane.destination.value,
                    plan_first_pass=lane.plan_first_pass,
                    text_first_pass=lane.text_first_pass,
                )
                for lane in self._ordered_lanes()
            ),
            split_candidate=self.split_candidate,
            accepted=tuple(
                lane.destination
                for lane in self._ordered_lanes()
                if lane.accepted is not None
            ),
            stopped_at=stopped_at,
            verdicts=tuple(
                lane.accepted
                for lane in self._ordered_lanes()
                if lane.accepted is not None
            ),
            fingerprints=self.fingerprints,
            packages=self.packages,
            fingerprint_paths=self.fingerprint_paths,
        )

    def _scopes(self) -> tuple[RunScope, ...]:
        """Every scope this run had, for the summary's final-state table (§3.3).

        Declared from what the run actually reached: a destination the run never
        decided about is not a destination that resolved, and listing one would
        make the skip rate count a scope nobody attempted. No publication scope
        — this run publishes nothing, and a publication that never happened must
        not appear in the ledger as one that resolved.
        """

        scopes: list[RunScope] = []
        if self.signal_id:
            scopes.append(
                RunScope(scope=OutcomeScope.SIGNAL, scope_key=self.signal_id)
            )
        unit = self.unit
        if unit is not None:
            scopes.append(
                RunScope(scope=OutcomeScope.UNIT, scope_key=unit.unit_id)
            )
            scopes.extend(
                RunScope(
                    scope=OutcomeScope.DESTINATION,
                    scope_key=destination_scope_key(
                        unit.unit_id, lane.destination
                    ),
                )
                for lane in self._ordered_lanes()
            )
        return tuple(scopes)

    # ------------------------------------------------------------------
    # S-00 · signal selection
    # ------------------------------------------------------------------

    def _s00(self) -> bool:
        """Seam 1, and the stage that reads it.

        The candidate is the intake record as intake wrote it
        (:func:`~src.run.signal_adapter.selection_candidate`); the fit rules are
        the client's, bound to the fields #365 persists. A record lacking either
        classification is refused **by the rule**, with the rule named in the
        trace — not pre-screened here, which would take the refusal away from
        the rule that owns it.
        """

        candidate = selection_candidate(self.signal)
        self.signal_id = candidate.signal_id
        selection: SignalSelection = select_signal(
            candidate,
            fit_rules=self.cfg.fit_rules,
            role=self.cfg.role,
            transport=self.seams.eligibility,
            portfolio=self.portfolio,
            budget=self.budget,
        )
        written = self.workspace.write_entity(
            stage="S-00",
            relative_path="signal/selection.json",
            entity_type=_SELECTION_ENTITY_TYPE,
            entity_id=selection.signal_id,
            payload=selection.as_entity(),
        )
        self.lineage[_SELECTION_ENTITY_TYPE] = _ref(written)
        judged = selection.eligibility is not None
        self.trace.record(
            stage="S-00",
            scope_key=self.signal_id,
            # The fit rules are code's and the source-class judgment is the
            # model's. A selection that ended at a fit rule was decided by rule.
            decider=DeciderKind.MODEL if judged else DeciderKind.RULE,
            outputs=(self.lineage[_SELECTION_ENTITY_TYPE],),
            calls=1 if judged else 0,
            outcomes=() if selection.outcome is None else (selection.outcome,),
        )
        return selection.selected

    # ------------------------------------------------------------------
    # S-01 · the Evidence Core and the relevance screen
    # ------------------------------------------------------------------

    def _s01(self) -> bool:
        build = retrieve_evidence_core(
            provider=self.seams.research,
            request=self.binding.request,
            run_dir=self.binding.run_dir,
            identity=self.binding.identity,
            run_started_at=self.binding.run_started_at,
            now=self.now,
            transport=self.seams.evidence_judgment,
            ladder=self.cfg.ladder,
            core_id=f"core-{self.signal_id}",
            # The client's evidence policy, from the contract that declared it
            # (§1, S-01 Inputs: "Client Contract evidence policy and strength
            # ladder"). Both halves now arrive from the same authority, and
            # neither is decided here.
            authority_required=self.cfg.contract.requires_primary_authority,
            budget=self.budget,
        )
        outputs: list[EntityRef] = []
        if build.core is not None:
            written = self.workspace.write_entity(
                stage="S-01",
                relative_path="signal/core/core.v1.json",
                entity_type=_CORE_ENTITY_TYPE,
                entity_id=build.core.core_id,
                version=1,
                payload=build.core.as_entity(),
            )
            self.lineage[_CORE_ENTITY_TYPE] = _ref(written)
            outputs.append(self.lineage[_CORE_ENTITY_TYPE])
        if not build.continues:
            self.trace.record(
                stage="S-01",
                scope_key=self.signal_id,
                decider=DeciderKind.MODEL,
                inputs=(self.lineage[_SELECTION_ENTITY_TYPE],),
                outputs=tuple(outputs),
                calls=1,
                outcomes=() if build.outcome is None else (build.outcome,),
            )
            return False

        assert build.core is not None and build.research is not None
        screen = screen_relevance(
            core=build.core,
            research=build.research,
            evaluator=self.seams.relevance,
            strategy_view=self.binding.strategy_view,
            audience=self.binding.audience_selection,
            identity=self.binding.identity,
            lens_profile=self.binding.lens_profile,
            run_id=self.binding.request.run_id,
            assignment_id=self.binding.assignment_id,
            signal_id=self.signal_id,
            run_dir=self.binding.run_dir,
            counters=self.counters,
            budget=self.budget,
        )
        if screen.assessment is not None:
            written = self.workspace.write_entity(
                stage="S-01",
                relative_path="signal/relevance.ref.json",
                entity_type=_RELEVANCE_ENTITY_TYPE,
                entity_id=screen.assessment.assessment_id,
                payload=screen.assessment.as_entity(),
            )
            self.lineage[_RELEVANCE_ENTITY_TYPE] = _ref(written)
            outputs.append(self.lineage[_RELEVANCE_ENTITY_TYPE])
        self.trace.record(
            stage="S-01",
            scope_key=self.signal_id,
            decider=DeciderKind.MODEL,
            inputs=(self.lineage[_SELECTION_ENTITY_TYPE],),
            outputs=tuple(outputs),
            # The extended evidence assessment and the relevance screen: two
            # calls. The research retrieval beside them is the provider's own
            # and is counted by the research pipeline rather than twice here.
            calls=2,
            outcomes=() if screen.outcome is None else (screen.outcome,),
        )
        self.core = build.core
        self.assessment = screen.assessment
        # A `revise` or `hold` disposition is a REPLAN into S-03, not a stop:
        # the gap it asks for is carried into enrichment, which is the one route
        # §1 gives S-01 and the reason the screen records an assessment with it.
        return screen.continues or screen.replans

    # ------------------------------------------------------------------
    # S-02 · material features and initial assets
    # ------------------------------------------------------------------

    def _s02(self) -> bool:
        assert self.core is not None
        core = self.core
        mark = self.meters.material.mark()
        described = describe_material(
            core=core,
            transport=self.meters.material,
            approved_positions=self.cfg.approved_positions,
            budget=self.budget,
        )
        outputs: list[EntityRef] = []
        if described.features is not None:
            features = described.features
            outputs.append(
                _ref(
                    self.workspace.write_entity(
                        stage="S-02",
                        relative_path="signal/features/features.v1.json",
                        entity_type=_FEATURES_ENTITY_TYPE,
                        entity_id=features.features_id,
                        version=1,
                        payload=features.as_entity(),
                    )
                )
            )
            outputs.append(
                _ref(
                    self.workspace.write_entity(
                        stage="S-02",
                        relative_path="signal/assets/assets.v1.json",
                        entity_type=_ASSETS_ENTITY_TYPE,
                        entity_id=f"ast-{core.core_id}-v1",
                        version=1,
                        payload=_asset_set(features, described.assets, 1),
                    )
                )
            )
            outputs.append(
                _ref(
                    self.workspace.write_entity(
                        stage="S-02",
                        relative_path="signal/notes/material_notes.json",
                        entity_type=_NOTES_ENTITY_TYPE,
                        entity_id=f"notes-{described.signal_id}",
                        payload=described.as_entity(),
                    )
                )
            )
            self.lineage[_FEATURES_ENTITY_TYPE] = outputs[0]
            self.lineage[_ASSETS_ENTITY_TYPE] = outputs[1]
        self.trace.record(
            stage="S-02",
            scope_key=self.signal_id,
            decider=_decider(described.calls),
            inputs=(self.lineage[_CORE_ENTITY_TYPE],),
            outputs=tuple(outputs),
            calls=described.calls,
            requests=self.meters.material.since(mark),
            outcomes=described.outcomes,
        )
        if not described.continues:
            return False
        self.features = described.features
        self.assets = described.assets
        self.notes = described.notes
        return True

    # ------------------------------------------------------------------
    # S-03 · the enrichment loop
    # ------------------------------------------------------------------

    def _s03(self) -> bool:
        """Enrich what blocks a decision, or record that nothing did.

        Zero rounds is the ordinary result and the common one (§1, ARP: "no
        blocking gap → zero rounds"), and the stage still records that it ran: a
        stage that left no entity is not a stage that did not execute.

        The gaps are computed first, through S-03's own :func:`open_gaps`, so
        that a run with nothing to close makes **no call at all** rather than
        paying for a round that would search for nothing.
        """

        assert self.core is not None and self.features is not None
        core, features = self.core, self.features
        # The description this stage enriches, read before a round can re-point
        # the lineage at the one a round commits. A stage records what it
        # consumed, and what S-03 consumed is S-02's vector: re-reading the
        # entry at the end of an enriching round would make the trace say that
        # S-03's input was the E-05 S-03 itself had just written, which is a
        # reference no earlier stage of the run produced.
        description = self.lineage[_FEATURES_ENTITY_TYPE]
        requested = (
            () if self.assessment is None else self.assessment.requested_gaps
        )
        gaps = open_gaps(
            core=core,
            assets=self.assets,
            notes=self.notes,
            requested_gaps=requested,
        )
        if not any(gap.status is GapStatus.OPEN for gap in gaps):
            self.trace.record(
                stage="S-03",
                scope_key=self.signal_id,
                decider=DeciderKind.CODE,
                inputs=(description,),
                outputs=self._gap_refs(gaps),
            )
            return True

        mark = self.meters.material.mark()
        enriched = enrich(
            core=core,
            features=features,
            assets=self.assets,
            notes=self.notes,
            requested_gaps=requested,
            provider=self.seams.research,
            request=self.binding.request,
            transport=self.meters.material,
            ladder=self.cfg.ladder,
            counters=self.counters,
            now=self.now,
            approved_positions=self.cfg.approved_positions,
            budget=self.budget,
            # The same client policy S-01 built the core under. A round that
            # rebuilt a claim without it would return it uncapped.
            authority_required=self.cfg.contract.requires_primary_authority,
        )
        outputs = list(self._gap_refs(enriched.gaps))
        version = enriched.core.version
        if version > core.version:
            outputs.append(
                _ref(
                    self.workspace.write_entity(
                        stage="S-03",
                        relative_path=f"signal/core/core.v{version}.json",
                        entity_type=_CORE_ENTITY_TYPE,
                        entity_id=enriched.core.core_id,
                        version=version,
                        payload=enriched.core.as_entity(),
                    )
                )
            )
            self.lineage[_CORE_ENTITY_TYPE] = outputs[-1]
            outputs.append(
                _ref(
                    self.workspace.write_entity(
                        stage="S-03",
                        relative_path=(
                            f"signal/features/features.v{version}.json"
                        ),
                        entity_type=_FEATURES_ENTITY_TYPE,
                        entity_id=enriched.features.features_id,
                        version=version,
                        payload=enriched.features.as_entity(),
                    )
                )
            )
            self.lineage[_FEATURES_ENTITY_TYPE] = outputs[-1]
            outputs.append(
                _ref(
                    self.workspace.write_entity(
                        stage="S-03",
                        relative_path=f"signal/assets/assets.v{version}.json",
                        entity_type=_ASSETS_ENTITY_TYPE,
                        entity_id=f"ast-{enriched.core.core_id}-v{version}",
                        version=version,
                        payload=_asset_set(
                            enriched.features, enriched.assets, version
                        ),
                    )
                )
            )
            self.lineage[_ASSETS_ENTITY_TYPE] = outputs[-1]
        self.trace.record(
            stage="S-03",
            scope_key=self.signal_id,
            decider=_decider(enriched.calls),
            inputs=(description,),
            outputs=tuple(outputs),
            calls=enriched.calls,
            requests=self.meters.material.since(mark),
            outcomes=enriched.outcomes,
        )
        self.core = enriched.core
        self.features = enriched.features
        self.assets = enriched.assets
        return enriched.continues

    def _gap_refs(self, gaps: Sequence[Gap]) -> tuple[EntityRef, ...]:
        """Every E-07 the loop opened, written where §2.3 puts it."""

        return tuple(
            _ref(
                self.workspace.write_entity(
                    stage="S-03",
                    relative_path=f"signal/gaps/{gap.gap_id}.json",
                    entity_type=_GAPS_ENTITY_TYPE,
                    entity_id=gap.gap_id,
                    payload=gap.as_entity(),
                )
            )
            for gap in gaps
        )

    # ------------------------------------------------------------------
    # S-04 · the Interpretation Boundary
    # ------------------------------------------------------------------

    def _s04(self) -> bool:
        assert self.core is not None and self.features is not None
        if self.assessment is None:
            raise GoldenEngineError(
                f"{self.signal_id} reached S-04 with no relevance assessment; §1 "
                "makes the RelevanceAssessment a required input, and a boundary "
                "drawn without the claim mode it declares would be drawn against "
                "an audience connection nobody established"
            )
        mark = self.meters.boundary.mark()
        decided = decide_boundary(
            core=self.core,
            features=self.features,
            relevance=self.assessment.for_boundary(),
            relevance_ref=self.assessment.decision,
            audience=self.cfg.audience,
            families=self.cfg.families,
            transport=self.meters.boundary,
            ladder=self.cfg.ladder,
            assets=self.assets,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if decided.boundary is not None:
            outputs = self._commit(decided.boundary)
        self.trace.record(
            stage="S-04",
            scope_key=self.signal_id,
            decider=_decider(decided.calls),
            inputs=(
                self.lineage[_CORE_ENTITY_TYPE],
                self.lineage[_FEATURES_ENTITY_TYPE],
            ),
            outputs=outputs,
            calls=decided.calls,
            requests=self.meters.boundary.since(mark),
            outcomes=decided.outcomes,
        )
        if decided.boundary is None or any(
            outcome.outcome is ArpOutcome.SKIP for outcome in decided.outcomes
        ):
            return False
        self.boundary = decided.boundary
        return True

    def _commit(
        self, boundary: InterpretationBoundary
    ) -> tuple[EntityRef, ...]:
        """One boundary version, through §2.4's coordinated commit.

        The E-08 versions first and the E-09 marker last, through the module
        that owns that order, so the harness walks the rule rather than writing
        a marker of its own beside it.
        """

        commit = commit_boundary_version(self.workspace, boundary)
        members = tuple(
            EntityRef(
                entity_type=_INTERPRETATION_ENTITY_TYPE,
                entity_id=member.interpretation_id,
                version=member.version,
                digest=member.digest,
            )
            for member in commit.members
        )
        marker = EntityRef(
            entity_type=_BOUNDARY_ENTITY_TYPE,
            entity_id=commit.boundary_id,
            version=commit.version,
            digest=file_digest(self.workspace.run_dir / commit.path),
        )
        self.lineage[_BOUNDARY_ENTITY_TYPE] = marker
        return members + (marker,)

    # ------------------------------------------------------------------
    # S-05 · the Editorial Unit
    # ------------------------------------------------------------------

    def _s05(self) -> bool:
        assert self.core is not None and self.boundary is not None
        unit = create_unit(core=self.core, boundary=self.boundary)
        written = _ref(write_unit(self.workspace, unit))
        self.lineage["E-10"] = written
        self.trace.record(
            stage="S-05",
            scope_key=self.signal_id,
            decider=DeciderKind.CODE,
            inputs=(
                self.lineage[_CORE_ENTITY_TYPE],
                self.lineage[_BOUNDARY_ENTITY_TYPE],
            ),
            outputs=(written,),
        )
        self.unit = unit
        self.split_candidate = run_split_candidate((unit,))
        return True

    # ------------------------------------------------------------------
    # S-06 · the anchor
    # ------------------------------------------------------------------

    def _s06(self) -> bool:
        assert self.unit is not None and self.boundary is not None
        assert self.core is not None
        mark = self.meters.anchor.mark()
        decided: AnchorDecision = choose_anchor(
            unit=self.unit,
            boundary=self.boundary,
            core=self.core,
            transport=self.meters.anchor,
            ladder=self.cfg.ladder,
            counters=self.counters,
            assets=self.assets,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if decided.anchor is not None:
            outputs = (_ref(write_anchor(self.workspace, decided.anchor)),)
            self.lineage["E-11"] = outputs[0]
        self.trace.record(
            stage="S-06",
            scope_key=self.unit.unit_id,
            decider=_decider(decided.calls),
            inputs=(self.lineage["E-10"], self.lineage[_BOUNDARY_ENTITY_TYPE]),
            outputs=outputs,
            calls=decided.calls,
            requests=self.meters.anchor.since(mark),
            outcomes=decided.outcomes,
        )
        if decided.anchor is None:
            return False
        self.anchor = decided.anchor
        return True

    # ------------------------------------------------------------------
    # S-07 · the six destination decisions
    # ------------------------------------------------------------------

    def _s07(self) -> bool:
        """Every destination the contract declares, decided by rule.

        One execution for the whole unit, and all six decisions written —
        eligible and excluded alike — because §1's Post column is a record of
        the whole set: an excluded destination whose decision was not written
        would be indistinguishable from one nobody decided about.

        ``capability``, ``rollout_scope``, ``policies``, ``cadence`` and
        ``portfolio`` are deliberately not supplied. The first two default to
        this repository's AS-IS facts, which is the honest answer — Wix and
        LinkedIn publish and the other four generate only — and the last three
        are inputs a scheduled run assembles from the day it runs on; a harness
        that invented a cadence rule here would be deciding one.
        """

        assert self.unit is not None and self.anchor is not None
        # What the lift answered, before the stage has established that it is
        # the input §1 requires. The engine calls `unit_facts` as a module
        # global, so "nothing produced the facts" is a state this stage can be
        # handed — and it is the one state it must not decide in: every rule
        # that refuses a destination for this unit's topic or risk reads them,
        # so a fan-out decided without them is decided as though the contract
        # refused nothing (#370).
        lifted: object = unit_facts(self.signal)
        if not isinstance(lifted, UnitFacts):
            raise GoldenEngineError(
                f"{self.unit.unit_id} reached S-07 and nothing lifted its unit "
                "facts; §1 makes `facts: UnitFacts` a required input, and the "
                "destinations this stage would decide without the topic and "
                "risk the intake record states are destinations no contract "
                "rule was given anything to refuse"
            )
        decided = decide_destinations(
            unit=self.unit,
            anchor=self.anchor,
            contract=self.cfg.destinations,
            facts=lifted,
        )
        written = write_destination_decisions(self.workspace, decided)
        self.trace.record(
            stage="S-07",
            scope_key=self.unit.unit_id,
            # Rule, and no call: AD-02 removed the model judgment from this
            # stage entirely, and every decision cites a rule and a tier.
            decider=DeciderKind.RULE,
            inputs=(self.lineage["E-10"], self.lineage["E-11"]),
            outputs=_refs(written),
            outcomes=() if decided.outcome is None else (decided.outcome,),
        )
        self.decisions = decided
        self.lanes = {
            decision.destination: _Lane(decision=decision)
            for decision in decided.eligible
        }
        return bool(self.lanes)

    # ------------------------------------------------------------------
    # S-08 … S-11 · a plan per destination, then barrier B1
    # ------------------------------------------------------------------

    def _plan(self, destination: Destination) -> None:
        """One destination through S-08 → S-09 → S-10 → S-11, with its attempts.

        The loop is the REPLAN route table executing: every failure that routes
        to S-08 comes back here with the record that authorized it, and the loop
        ends when the ledger stops returning one — which it must, because
        ``L_strategy`` is finite and is spent by the stage that detected the
        failure rather than by this loop.
        """

        lane = self.lanes[destination]
        lane.reopened = False
        while not lane.skipped and lane.plan is None:
            candidates = self._s08(lane)
            if candidates is None:
                return
            chosen = self._s09(lane, candidates)
            if chosen is None:
                continue
            lane.selection = chosen[1]
            plan = self._s10(lane, chosen[0], chosen[1])
            if plan is None:
                continue
            self._s11(lane, chosen[0], plan)

    def _s08(self, lane: _Lane) -> Optional[CandidateSet]:
        self._at("S-08")
        assert self.unit is not None and self.anchor is not None
        assert self.boundary is not None and self.core is not None
        assert self.features is not None
        mark = self.meters.strategy.mark()
        proposal = propose_strategies(
            unit=self.unit,
            anchor=self.anchor,
            decision=lane.decision,
            boundary=self.boundary,
            core=self.core,
            features=self.features,
            contract=self.cfg.strategy,
            transport=self.meters.strategy,
            assets=self.assets,
            attempt=lane.attempt,
            re_entry=lane.re_entry,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if proposal.candidate_set is not None:
            outputs = _refs(
                write_candidate_set(self.workspace, proposal.candidate_set)
            )
        lane.candidates = outputs
        self.trace.record(
            stage="S-08",
            scope_key=self._scope(lane),
            decider=_decider(proposal.calls),
            inputs=(self.lineage["E-11"], self.lineage[_BOUNDARY_ENTITY_TYPE]),
            outputs=outputs,
            calls=proposal.calls,
            requests=self.meters.strategy.since(mark),
            outcomes=proposal.outcomes,
        )
        if proposal.candidate_set is None:
            lane.skipped = True
            return None
        return proposal.candidate_set

    def _s09(
        self, lane: _Lane, candidates: CandidateSet
    ) -> Optional[tuple[EditorialStrategy, StrategySelection]]:
        assert self.boundary is not None and self.core is not None
        assert self.features is not None
        self._at("S-09")
        mark = self.meters.ranking.mark()
        decided = select_strategy(
            candidate_set=candidates,
            boundary=self.boundary,
            core=self.core,
            features=self.features,
            contract=self.cfg.strategy,
            counters=self.counters,
            transport=self.meters.ranking,
            assets=self.assets,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if decided.selection is not None:
            outputs = (
                _ref(
                    write_strategy_selection(self.workspace, decided.selection)
                ),
            )
        self.trace.record(
            stage="S-09",
            scope_key=self._scope(lane),
            decider=_decider(decided.calls),
            inputs=lane.candidates,
            outputs=outputs,
            calls=decided.calls,
            requests=self.meters.ranking.since(mark),
            outcomes=decided.outcomes,
        )
        selection = decided.selection
        if selection is None or selection.chosen is None:
            self._routed(lane, decided.outcomes)
            return None
        strategy = candidates.candidate(selection.chosen)
        if strategy is None:
            raise GoldenEngineError(
                f"S-09 chose {selection.chosen!r} for "
                f"{lane.destination.value} and the candidate set it ranked does "
                "not hold it; a selection names a candidate of its own set"
            )
        return strategy, selection

    def _s10(
        self,
        lane: _Lane,
        strategy: EditorialStrategy,
        selection: StrategySelection,
    ) -> Optional[ExecutablePlan]:
        assert self.boundary is not None and self.core is not None
        self._at("S-10")
        mark = self.meters.segmentation.mark()
        drafted = adapt_strategy(
            strategy=strategy,
            selection=selection,
            decision=lane.decision,
            rules=self.cfg.rules[lane.destination],
            contract=self.cfg.adaptation,
            boundary=self.boundary,
            core=self.core,
            counters=self.counters,
            transport=self.meters.segmentation,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if drafted.plan is not None:
            outputs = (_ref(write_plan(self.workspace, drafted.plan)),)
        self.trace.record(
            stage="S-10",
            scope_key=self._scope(lane),
            decider=_decider(drafted.calls),
            inputs=(self.lineage[_BOUNDARY_ENTITY_TYPE],),
            outputs=outputs,
            calls=drafted.calls,
            requests=self.meters.segmentation.since(mark),
            outcomes=drafted.outcomes,
        )
        if drafted.plan is None:
            self._routed(lane, drafted.outcomes)
            return None
        return drafted.plan

    def _s11(
        self,
        lane: _Lane,
        strategy: EditorialStrategy,
        plan: ExecutablePlan,
    ) -> None:
        assert self.boundary is not None and self.core is not None
        self._at("S-11")
        mark = self.meters.plan_check.mark()
        checked = check_plan(
            plan=plan,
            strategy=strategy,
            boundary=self.boundary,
            core=self.core,
            rules=self.cfg.rules[lane.destination],
            contract=self.cfg.adaptation,
            checks=self.cfg.plan_checks,
            counters=self.counters,
            transport=self.meters.plan_check,
            library=self.cfg.library,
            budget=self.budget,
        )
        outputs: list[EntityRef] = []
        if checked.approved is not None:
            outputs.append(
                _ref(write_approved_plan(self.workspace, checked.approved))
            )
        if checked.verdict is not None:
            outputs.append(
                _ref(write_plan_verdict(self.workspace, checked.verdict))
            )
        self.trace.record(
            stage="S-11",
            scope_key=self._scope(lane),
            decider=_decider(checked.calls),
            inputs=(self.lineage[_BOUNDARY_ENTITY_TYPE],),
            outputs=tuple(outputs),
            calls=checked.calls,
            requests=self.meters.plan_check.since(mark),
            outcomes=checked.outcomes,
        )
        if not checked.passed:
            self._routed(lane, checked.outcomes)
            return
        lane.strategy = strategy
        lane.plan = checked.approved
        lane.verdict = checked.verdict
        # The attempt that produced this plan is over, so the lane is no longer
        # waiting to be re-planned: a flag left set here would send an approved
        # plan back through S-08 on the next pass.
        lane.reopened = False

    def _routed(self, lane: _Lane, outcomes: Sequence[OutcomeRecord]) -> None:
        """Carry a REPLAN into S-08 forward, or end the destination.

        The record is kept and handed back, because that is what the next
        attempt has to show: #304's ``_authorized`` refuses an attempt that
        cannot name which counter paid for it at which scope, so a harness that
        only incremented the attempt number would be refused — and one that
        incremented it *without* being refused would be a loop nobody bounded.
        """

        route = _replan_to(outcomes, "S-08")
        lane.plan = None
        lane.verdict = None
        lane.strategy = None
        lane.plan_first_pass = False
        if route is None:
            # The ledger refused the route, so this destination has ended. It is
            # not reopened: a lane nothing can re-plan is a lane the next round
            # would ask the barrier about and the barrier would refuse.
            lane.skipped = True
            lane.reopened = False
            return
        lane.attempt += 1
        lane.re_entry = route
        lane.reopened = True

    def _scope(self, lane: _Lane) -> str:
        return destination_scope_key(self._unit().unit_id, lane.destination)

    # ------------------------------------------------------------------
    # The state a late stage may not be run without
    # ------------------------------------------------------------------

    def _unit(self) -> EditorialUnit:
        if self.unit is None:
            raise GoldenEngineError(
                "a destination-scoped stage was reached before S-05 created the "
                "unit; §6.2 has no state for a stage run out of order"
            )
        return self.unit

    def _material(self) -> tuple[InterpretationBoundary, EvidenceCore]:
        """The boundary and the core every stage from S-05 on is handed.

        Raised rather than asserted, and read rather than cached: a boundary
        commit replaces the current version mid-run, and a stage handed the
        version this run started with would be checking a text against a
        snapshot that no longer holds (F-4).
        """

        if self.boundary is None or self.core is None:
            raise GoldenEngineError(
                "a stage was reached without the core and the boundary it reads; "
                "I-03 makes the core the only source of facts, and §6.2 has no "
                "state for a stage run out of order"
            )
        return self.boundary, self.core

    def _approved_plan(
        self, lane: _Lane
    ) -> tuple[ExecutablePlan, PlanVerdict, EditorialStrategy]:
        """What I-08 requires before prose exists: the approved plan and its
        verdict, and the strategy the plan executes."""

        if lane.plan is None or lane.verdict is None or lane.strategy is None:
            raise GoldenEngineError(
                f"{lane.destination.value} reached S-12 without an approved "
                "plan, its verdict and the strategy it executes; I-08 opens "
                "prose on an approved plan only"
            )
        return lane.plan, lane.verdict, lane.strategy

    def _passed_barrier(self) -> BarrierRound:
        if self.barrier is None:
            raise GoldenEngineError(
                "S-12 was reached with no barrier round; §0.2 is that no text is "
                "written for any destination of a unit before B1 passes"
            )
        return self.barrier

    # ------------------------------------------------------------------
    # Barrier B1 (seam 11)
    # ------------------------------------------------------------------

    def _barrier(self) -> bool:
        """Hold every destination at B1 until V-P03 passes, or nobody is left.

        ``expected_destinations`` is seam 11: #305 made it required because "a
        barrier that concluded anything from the plans it happened to be shown
        would be a barrier a caller can open by passing fewer of them". The set
        is declared from S-07's own answer minus what the run has since skipped,
        and a round the barrier sends back is re-planned and declared again —
        shorter — which is §0.2's "B1 re-evaluates without it".
        """
        self._at("S-11")

        unit = self._unit()
        decisions = self.decisions
        anchor = self.anchor
        if decisions is None or anchor is None:
            raise GoldenEngineError(
                "B1 was reached before S-06 and S-07 produced the anchor and the "
                "unit's destination decisions; V-P03 compares the unit's plans "
                "against its anchor, and a round with neither compares nothing"
            )
        while True:
            # Read the boundary each round: a commit between rounds replaces the
            # version the plans must still hold against (F-4).
            boundary, _ = self._material()
            try:
                expected = expected_destinations(
                    decisions, skipped=self._skipped()
                )
            except ExpectedDestinationsError:
                # Every eligible destination has ended. That is a unit with
                # nowhere left to go, recorded by the stages that skipped each
                # destination — not a barrier round with no participants.
                return False
            planned = [
                self.lanes[destination]
                for destination in sorted(expected, key=lambda item: item.value)
            ]
            # F-4, the half §5.4 gives the harness: when the boundary version
            # moves, S-11's code checks re-run on **every approved plan of the
            # unit** (0 model calls) — not only on the one about to be written.
            # The barrier compares siblings, so a round that admitted one plan
            # approved against the version a commit replaced would carry a stale
            # approval past the barrier, which is the defect itself. A plan whose
            # re-check fails routes back to S-08 like any other failed hard check
            # and the round is declared again — shorter, or with its new plan.
            stale = [
                lane
                for lane in planned
                if lane.verdict is not None
                and not approval_holds(lane.verdict, boundary)
            ]
            if stale:
                for lane in stale:
                    if self._recheck_plan(lane) or lane.skipped:
                        continue
                    self._plan(lane.destination)
                continue
            without = [lane for lane in planned if lane.plan is None]
            if without:
                raise GoldenEngineError(
                    "B1 was reached with no approved plan for "
                    + ", ".join(lane.destination.value for lane in without)
                    + "; the round's participants are the harness's to declare, "
                    "and declaring a destination that has no plan would ask the "
                    "barrier to compare one that does not exist"
                )
            self.barrier_round += 1
            mark = self.meters.barrier.mark()
            round_result = run_barrier(
                unit_id=unit.unit_id,
                anchor=anchor,
                expected_destinations=expected,
                plans=tuple(
                    lane.plan for lane in planned if lane.plan is not None
                ),
                verdicts=tuple(
                    lane.verdict for lane in planned if lane.verdict is not None
                ),
                boundary=boundary,
                checks=self.cfg.plan_checks,
                counters=self.counters,
                transport=self.meters.barrier,
                round_index=self.barrier_round,
                budget=self.budget,
            )
            written = _ref(write_barrier_round(self.workspace, round_result))
            self.trace.record(
                stage="S-11",
                scope_key=unit.unit_id,
                decider=_decider(round_result.calls),
                inputs=(self.lineage["E-11"],),
                outputs=(written,),
                calls=round_result.calls,
                requests=self.meters.barrier.since(mark),
                outcomes=round_result.outcomes,
            )
            if round_result.passed:
                self.barrier = round_result
                return True
            if not self._send_back(
                round_result.deviating, round_result.outcomes
            ):
                return False

    def _send_back(
        self,
        deviating: Sequence[Destination],
        outcomes: Sequence[OutcomeRecord],
    ) -> bool:
        """Re-plan what V-P03 sent back, and report whether anything moved.

        Only the destinations that deviated: "the others keep their approval",
        which is the route table's own wording. A destination whose route the
        ledger refused ends here, by the record the ledger returned, and a round
        in which nothing could be re-planned is a barrier that can never pass —
        so the unit stops rather than looping over the same plans.
        """

        moved = False
        for destination in deviating:
            lane = self.lanes.get(destination)
            if lane is None:
                continue
            route = next(
                (
                    outcome
                    for outcome in outcomes
                    if outcome.outcome is ArpOutcome.REPLAN
                    and outcome.route_target == "S-08"
                    and outcome.scope_key == self._scope(lane)
                ),
                None,
            )
            self._routed(lane, () if route is None else (route,))
            if lane.skipped:
                continue
            self._plan(destination)
            moved = moved or lane.plan is not None
        return moved

    # ------------------------------------------------------------------
    # S-12 and S-13 · prose, checks, and the bounded edit loop
    # ------------------------------------------------------------------

    def _produce_texts(self) -> None:
        """Write and check every destination's text, re-planning what reopens.

        The outer loop is S-13's ``L_strategy`` route taken honestly: a
        structural fault is the plan's and goes back to S-08 (I-09), which means
        a new plan, a new barrier round and a new text — not a second edit of a
        text whose plan no longer stands. It terminates because every reopen
        spends ``L_strategy``, which is finite per destination.
        """

        while True:
            for lane in self._ordered_lanes():
                if lane.skipped or lane.accepted is not None:
                    continue
                if lane.plan is None:
                    continue
                self._text(lane)
            reopened = [
                lane for lane in self._ordered_lanes() if lane.reopened
            ]
            if not reopened:
                return
            for lane in reopened:
                self._plan(lane.destination)
            if not self._barrier():
                return

    def _text(self, lane: _Lane) -> None:
        self._at("S-12")
        boundary, core = self._material()
        barrier = self._passed_barrier()
        _, verdict, _ = self._approved_plan(lane)
        if not approval_holds(verdict, boundary):
            # F-4: an approval the current boundary version has taken away opens
            # nothing. The plan is re-established against the new version before
            # any prose is paid for, exactly as §5.4 requires.
            if not self._recheck_plan(lane):
                return
        # Read again: the re-check produced a **new verdict version**, and the
        # old one does not become current again (§5.4).
        plan, verdict, strategy = self._approved_plan(lane)
        mark = self.meters.writer.mark()
        decision = write_prose(
            plan=plan,
            verdict=verdict,
            barrier=barrier,
            strategy=strategy,
            boundary=boundary,
            core=core,
            brief=self.cfg.brief,
            counters=self.counters,
            transport=self.meters.writer,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if decision.text is not None:
            outputs = (_ref(write_text(self.workspace, decision.text)),)
        self.trace.record(
            stage="S-12",
            scope_key=self._scope(lane),
            decider=_decider(decision.calls),
            inputs=(self.lineage[_BOUNDARY_ENTITY_TYPE],),
            outputs=outputs,
            calls=decision.calls,
            requests=self.meters.writer.since(mark),
            outcomes=decision.outcomes,
        )
        if decision.text is None:
            self._routed(lane, decision.outcomes)
            return
        lane.text = decision.text
        self._check(lane)

    def _check(self, lane: _Lane) -> None:
        """S-13 over one text, and the bounded edit loop its route opens.

        The loop is ``S-12 → S-13 → (revise_prose → S-13)`` and it is bounded by
        the ledger rather than by a count kept here: ``L_edit`` is counted per
        **approved plan** at ``<plan_id>/v<version>``, so a second edit of the
        same plan is refused and the publication is skipped. A harness that kept
        its own count would mint a fresh allowance with every text version,
        which is exactly the defect ``edit_scope_key`` exists to prevent.
        """
        self._at("S-13")

        boundary, core = self._material()
        while True:
            text, plan = lane.text, lane.plan
            if text is None or plan is None:
                return
            mark = self.meters.text_check.mark()
            decided = check_text(
                text=text,
                plan=plan,
                boundary=boundary,
                core=core,
                forbidden=self.cfg.forbidden,
                checks=self.cfg.text_checks,
                counters=self.counters,
                transport=self.meters.text_check,
                priors=self.priors,
                portfolio=self.text_portfolio,
            )
            verdict = decided.verdict
            self.trace.record(
                stage="S-13",
                scope_key=self._scope(lane),
                decider=_decider(verdict.calls),
                inputs=(_text_ref(text),),
                outputs=(self._write_verdict(lane, verdict),),
                calls=verdict.calls,
                requests=self.meters.text_check.since(mark),
                outcomes=() if verdict.outcome is None else (verdict.outcome,),
            )
            if verdict.result is TextResult.ACCEPTED:
                lane.accepted = verdict
                return
            lane.text_first_pass = False
            if verdict.result is TextResult.EDIT:
                if not self._edit(lane, verdict):
                    return
                continue
            if (
                verdict.result is TextResult.REPLAN
                and verdict.counter == BOUNDARY_COUNTER
            ):
                self._re_enter_boundary(lane, verdict)
                return
            # Everything else is the plan's fault, not the prose's: the route
            # goes back to S-08 and `_produce_texts` re-plans the destination.
            lane.text = None
            self._routed(
                lane, () if verdict.outcome is None else (verdict.outcome,)
            )
            return

    def _edit(self, lane: _Lane, verdict: TextVerdict) -> bool:
        """One edit of the same approved plan, carrying S-13's own findings.

        The findings are S-13's and are carried rather than restated: an edit
        answering a paraphrase of the check would be a second judgment made by
        the harness. ``revise_prose`` spends no counter — ``L_edit`` was counted
        at S-13 — so charging it again here would turn one permitted edit into
        none.
        """
        self._at("S-12")

        boundary, core = self._material()
        barrier = self._passed_barrier()
        plan, approved, strategy = self._approved_plan(lane)
        prior = lane.text
        if prior is None:
            raise GoldenEngineError(
                f"{lane.destination.value} is being edited with no prior text; an "
                "edit is the next version of a text that exists"
            )
        findings = tuple(
            finding.detail
            for check in verdict.checks
            for finding in check.findings
        )
        if not findings:
            raise GoldenEngineError(
                f"{verdict.verdict_id} routes an edit and records no finding; an "
                "edit answers a text check, and one with nothing to answer is a "
                "second write charged to the wrong counter"
            )
        mark = self.meters.writer.mark()
        revised = revise_prose(
            prior=prior,
            findings=findings,
            plan=plan,
            verdict=approved,
            barrier=barrier,
            strategy=strategy,
            boundary=boundary,
            core=core,
            brief=self.cfg.brief,
            counters=self.counters,
            transport=self.meters.writer,
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if revised.text is not None:
            outputs = (_ref(write_text(self.workspace, revised.text)),)
        self.trace.record(
            stage="S-12",
            scope_key=self._scope(lane),
            decider=_decider(revised.calls),
            inputs=(_text_ref(prior),),
            outputs=outputs,
            calls=revised.calls,
            requests=self.meters.writer.since(mark),
            outcomes=revised.outcomes,
        )
        if revised.text is None:
            lane.text = None
            self._routed(lane, revised.outcomes)
            return False
        lane.text = revised.text
        return True

    def _write_verdict(self, lane: _Lane, verdict: TextVerdict) -> EntityRef:
        """One TextVerdict, at the path §2.2 gives the text version it judged.

        §2.5 gives one verdict per text version, so the version in the name is
        the **text's** — which is what makes an edit's verdict a new file rather
        than an overwrite of the one the prior version was judged by.
        """

        unit = self._unit()
        text_id, version = verdict.text_ref
        return _ref(
            self.workspace.write_entity(
                stage="S-13",
                relative_path=(
                    f"units/{unit.unit_id}/destinations/"
                    f"{lane.destination.value}/verdicts/"
                    f"text_{text_id}.v{version}.json"
                ),
                entity_type=_TEXT_VERDICT_ENTITY_TYPE,
                entity_id=verdict_id(verdict.text_ref),
                version=version,
                payload=verdict.as_entity(),
            )
        )

    # ------------------------------------------------------------------
    # The F-4 halves no stage can do
    # ------------------------------------------------------------------

    def _re_enter_boundary(self, lane: _Lane, verdict: TextVerdict) -> None:
        """S-13's V-T02 route: back into S-04, then the sibling re-check.

        This is where the orchestration the issue calls out lives. A wiring that
        ran the stages in order and stopped would satisfy every per-stage
        contract and still publish a text accepted against a boundary version
        that no longer holds, because no stage knows which siblings were
        accepted. So after the re-entry commits a new version, every
        already-accepted sibling verdict of this unit is re-checked against it —
        one truth call each, V-T02 only — **before** anything may reach S-14.
        """
        self._at("S-04")

        boundary, core = self._material()
        unit = self._unit()
        # The version this execution **reads**, captured before it commits the
        # next one: `_commit` replaces `lineage[E-09]` with the version it
        # writes, so a reference read afterwards would name this execution's own
        # output as its input — a lineage reference that resolves to nothing
        # upstream, which is the one thing a seam proof cannot resolve (#370).
        read = self.lineage[_BOUNDARY_ENTITY_TYPE]
        text = lane.text
        if text is None:
            raise GoldenEngineError(
                f"{lane.destination.value} routes a re-entry with no text; the "
                "reading the boundary is asked about is one a text expressed"
            )
        statement = next(
            (
                finding.detail
                for check in verdict.checks
                if check.check_id == "V-T02"
                for finding in check.findings
            ),
            None,
        )
        if statement is None:
            raise GoldenEngineError(
                f"{verdict.verdict_id} routes to S-04 on {BOUNDARY_COUNTER} and "
                "records no V-T02 finding; the re-entry is given what the text "
                "expressed, and one that cannot say what it was would ask the "
                "boundary about nothing"
            )
        if verdict.outcome is None:
            raise GoldenEngineError(
                f"{verdict.verdict_id} routes to S-04 on {BOUNDARY_COUNTER} and "
                "carries no outcome; the re-entry is taken on the record that "
                "spent the counter, and one that cannot name it bounded nothing"
            )
        mark = self.meters.boundary.mark()
        reentry = re_enter_boundary(
            boundary=boundary,
            core=core,
            audience=self.cfg.audience,
            detected=DetectedInterpretation(
                statement=statement,
                # The destination **scope key**, not the destination's name:
                # `DetectedInterpretation.destination` is the scope §0.3 skips,
                # and the onward L_strategy route keys on it, so S-08 refuses a
                # route it cannot match to this destination's own key. The bare
                # value had never been exercised, because until the counter
                # ownership was fixed no re-entry ever reached the onward route.
                destination=self._scope(lane),
                text_ref=text.text_id,
            ),
            unit_id=unit.unit_id,
            transport=self.meters.boundary,
            ladder=self.cfg.ladder,
            counters=self.counters,
            # S-13's own REPLAN, carried rather than re-spent. §5.3 lists the
            # S-13 → S-04 edge once and gives it one `L_boundary`, so the record
            # that paid for this re-entry is the one S-13 already wrote; the
            # harness hands it over exactly as `_replan_to` hands S-08 its own.
            authorizing=verdict.outcome,
            anchor_interpretation_id=(
                None if self.anchor is None else self.anchor.interpretation_ref[0]
            ),
            budget=self.budget,
        )
        outputs: tuple[EntityRef, ...] = ()
        if reentry.boundary is not None:
            outputs = self._commit(reentry.boundary)
        self.trace.record(
            stage="S-04",
            scope_key=self.signal_id,
            decider=_decider(reentry.calls),
            inputs=(read,),
            outputs=outputs,
            calls=reentry.calls,
            requests=self.meters.boundary.since(mark),
            outcomes=reentry.outcomes,
        )
        lane.text = None
        if reentry.boundary is None:
            # The counter was exhausted, the budget refused, or the test call
            # did not answer. In all three the destination is skipped rather
            # than released, and the boundary is unchanged — so no sibling was
            # put in question and there is nothing to re-check.
            lane.skipped = True
            return
        self.boundary = reentry.boundary
        # The siblings first, and that order is the whole of §5.4: a text
        # accepted against the version this commit replaced may not reach S-14,
        # and the destination that caused the commit has not been routed yet.
        self._recheck_siblings()
        # Then the route the re-entry itself took. A commit that left the anchor
        # standing sends this destination back to S-08 on `L_strategy`, which is
        # a new attempt; one that invalidated the anchor routes to S-06, which
        # this slice does not re-enter, so the destination ends with the record
        # that says why.
        self._routed(lane, reentry.outcomes)

    def _recheck_siblings(self) -> None:
        """Re-check every sibling the commit put in question (§5.4, F-4).

        One call per affected sibling and V-T02 only, through S-13's own
        ``recheck_siblings_after_boundary_commit``: re-running the execution
        call would pay for an answer that cannot have changed, because the
        plan's execution is what it was and what moved is which readings the
        boundary admits.

        No second TextVerdict entity is written. §2.5 gives one verdict per text
        version, and the re-check judges the same version — so what the run
        records is the StageRecord, which carries the result and its outcome,
        rather than a file overwriting the verdict it supersedes.
        """
        self._at("S-13")

        boundary, core = self._material()
        accepted: list[tuple[Text, TextVerdict]] = []
        plans: dict[Destination, ExecutablePlan] = {}
        for lane in self._ordered_lanes():
            if lane.text is not None and lane.accepted is not None:
                accepted.append((lane.text, lane.accepted))
            if lane.plan is not None:
                plans[lane.destination] = lane.plan
        if not accepted:
            return
        at_risk = affected_siblings(
            tuple(item[1] for item in accepted), boundary
        )
        if not at_risk:
            return
        mark = self.meters.text_check.mark()
        decisions = recheck_siblings_after_boundary_commit(
            boundary=boundary,
            accepted=tuple(accepted),
            core=core,
            plans=plans,
            checks=self.cfg.text_checks,
            counters=self.counters,
            transport=self.meters.text_check,
        )
        requests = self.meters.text_check.since(mark)
        for decision in decisions:
            verdict = decision.verdict
            lane = self.lanes[verdict.destination]
            self.trace.record(
                stage="S-13",
                scope_key=self._scope(lane),
                decider=_decider(verdict.calls),
                inputs=(self.lineage[_BOUNDARY_ENTITY_TYPE],),
                calls=verdict.calls,
                requests=requests,
                outcomes=() if verdict.outcome is None else (verdict.outcome,),
            )
            # A sibling that no longer holds loses its acceptance. The whole
            # point of the re-check is that such a text "cannot remain
            # publishable", so the acceptance is dropped rather than left
            # standing beside a failing verdict.
            if verdict.accepted:
                lane.accepted = verdict
                continue
            lane.accepted = None
            lane.text = None
            lane.text_first_pass = False
            lane.skipped = True

    def _recheck_plan(self, lane: _Lane) -> bool:
        """Re-establish one approval against a newer boundary version (F-4).

        S-11's code checks only — V-P02 and the chain, **0 model calls** — which
        is what §5.4 asks for. An approval that survives is recorded against the
        new version and :func:`approval_holds` starts answering ``True`` for it;
        one that does not routes back to S-08 like any other failed hard check.
        """
        self._at("S-11")

        boundary, core = self._material()
        plan, approved, strategy = self._approved_plan(lane)
        verdict = recheck_after_boundary_commit(
            verdict=approved,
            plan=plan,
            strategy=strategy,
            boundary=boundary,
            core=core,
            checks=self.cfg.plan_checks,
            counters=self.counters,
        )
        self.trace.record(
            stage="S-11",
            scope_key=self._scope(lane),
            decider=DeciderKind.CODE,
            inputs=(self.lineage[_BOUNDARY_ENTITY_TYPE],),
            outputs=(_ref(write_plan_verdict(self.workspace, verdict)),),
            outcomes=() if verdict.outcome is None else (verdict.outcome,),
        )
        lane.verdict = verdict
        lane.plan_first_pass = False
        if approval_holds(verdict, boundary):
            return True
        self._routed(
            lane, () if verdict.outcome is None else (verdict.outcome,)
        )
        return False

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def _order(self) -> tuple[Destination, ...]:
        return tuple(sorted(self.lanes, key=lambda item: item.value))

    def _ordered_lanes(self) -> tuple[_Lane, ...]:
        return tuple(self.lanes[item] for item in self._order())

    def _skipped(self) -> tuple[Destination, ...]:
        return tuple(
            lane.destination for lane in self._ordered_lanes() if lane.skipped
        )


def _asset_set(
    features: MaterialFeatures, assets: Sequence[Asset], version: int
) -> dict[str, Any]:
    """The ``E-06`` body: this core version's assets, as they were found.

    Composed here because ``material_features`` ships an ``as_entity`` per asset
    and no envelope around them — §2.2 gives the version one file, so the
    envelope is the workspace's shape and not the stage's.
    """

    return {
        "entity_type": _ASSETS_ENTITY_TYPE,
        "entity_id": f"ast-{features.core_ref[0]}-v{version}",
        "version": version,
        "core_ref": list(features.core_ref),
        "assets": [item.as_entity() for item in assets],
    }
