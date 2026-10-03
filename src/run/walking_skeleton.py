"""The run harness: SL-1's walking skeleton, and SL-6.5's canonical run.

SL-1's goal was "a walking skeleton of the one canonical engine: every stage
S-00…S-15 exists as a typed pass-through, run end to end on a fixture signal
with fake providers" (Step 6 §2). :func:`run_walking_skeleton` is that run, and
it holds **no stage logic at all**.

#351 added the other entry point. :func:`run_golden_engine` runs the **real**
S-00…S-13 through :mod:`src.run.golden_engine`, over #361's production
transport bindings, and it is the canonical shadow run: there is no
pass-through in it, no fixture stands in for a stage, and
``PASS_THROUGH_MARKER`` never appears in its trace. The two share everything
below the stages — the workspace, the manifest, the verification, the
public-safe RunSummary and the ledger commit — because those are the same facts
about a run whichever executed it.

**Which is which, and why both.** The pass-through run is SL-1's own acceptance
evidence and keeps proving what it proved: that the topology executes, that six
destinations are covered, that the manifest verifies and that a failed ledger
commit does not fail a run. It is a fixture proof and says so — every entity it
writes carries :data:`PASS_THROUGH_MARKER`, so no reader and no later slice can
mistake one of its workspaces for a canonical run. What it may not be is the
evidence for a *canonical* run, which is why #351 did not extend it:
``PASS_THROUGH_MARKER count == 0`` is a property of
:func:`run_golden_engine` alone.

What they prove, and how
------------------------
**The topology executes.** The stages come from ``CANONICAL_TOPOLOGY`` in the
registry's own order, and a stage the registry declares that the run has no
implementation for stops the run — :class:`SkeletonError` here, and
:class:`~src.run.golden_engine.StageNotWiredError` there. Neither can execute a
different engine from the one the digest names, because neither keeps a second
list of stages.

**Six destinations.** Every destination-scoped stage covers all six (Principle
B, Step 6 §0.2), from the one list the repository already keeps. The six
destination folders in the workspace are what that looks like on disk, and the
canonical run checks afterwards that S-07 really decided about each one
(:func:`decided_every_destination`).

**The manifest verifies.** Entities go through :class:`RunWorkspace`, so
create-once, the version in the key and §2.3 write ownership hold; the manifest
is written last, and ``verify_run_workspace`` is run over the sealed result
before the run reports success. It states its §4.1 input versions too (#336) —
and for a fixture run with pass-through stages that statement is that it read
none of them, which is the honest one.

**The ledger takes the summary.** The run ends with a public-safe RunSummary in
``data/editorial/`` (§3.2) and, when the caller asks for it, a commit. A commit
that fails is recorded and the run still ends normally (§3.1) — which is the one
behaviour of this harness that production will depend on.

Production safety
-----------------
Shadow only, and unable to be otherwise:

- the pass-through run makes **no** model call. It carries an
  :class:`ArpCallBudget` and spends nothing from it, and the provider it carries
  is :class:`RefusingProvider`, which raises if anything asks it for text;
- the canonical run constructs **no** transport and reads no model
  configuration: its seams are handed in, so a test supplies typed doubles and
  cannot make a paid call, and ``NB_GOLDEN_ENGINE_MODEL`` stays a requirement of
  whoever builds real transports, with no default anywhere;
- there is no external publish call and no publication marker. The canonical
  run does not execute S-14 at all (#308 owns it), and S-14 in the pass-through
  run writes the run's own publication record and fingerprint, consults no
  idempotency authority, and publishes nothing;
- the ledger commit is off unless a caller turns it on, so running either on a
  developer's machine or in a test cannot touch the repository.

S-15 is post-run: in the target it is a scheduled observation job (SL-12) over
already-published destinations. It runs in the pass-through harness, in order,
as the pass-through the slice asks for — writing no entity, because §2.3 gives
it no workspace path and the workspace writer would refuse one.

Sources: ``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md`` §2 (SL-1)
and §0.2; ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§2.2, §2.3, §3 and §4.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

from src.editorial_core.arp import AttemptCounterLedger, OutcomeScope
from src.editorial_core.signal_selection import PortfolioFingerprint
from src.editorial_core.text_check import PriorPublication, TextFingerprint
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.publishing.publication_markers import DESTINATIONS, active_client
from src.run.boundary_commit import (
    Admissibility,
    BoundaryMember,
    InterpretationVersion,
    boundary_relative_path,
    commit_boundary,
)
from src.run.call_budget import (
    DEFAULT_CEILING,
    GOLDEN_ENGINE_MAX_CEILING,
    RunCallBudget,
    activate_call_budget,
)
from src.run.call_budget_arp import ArpCallBudget
from src.run.code_identity import CodeIdentity, resolve_code_identity
from src.run.golden_engine import (
    CanonicalExecution,
    GoldenEngineConfiguration,
    GoldenEngineSeams,
    ResearchBinding,
    execute_canonical_topology,
)
from src.run.ledger import (
    DEFAULT_PUSH_ATTEMPTS,
    DEFAULT_RETRY_SECONDS,
    LedgerCommitReport,
    LedgerCommitStatus,
    commit_ledger,
    commit_message,
)
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import EntityIndexEntry, RunInputs, RunManifest
from src.run.run_summary import (
    DestinationFirstPass,
    RunScope,
    RunSummary,
    WorkspaceRef,
    write_run_summary,
)
from src.run.run_workspace import (
    EDITORIAL_RUNS_ROOT,
    MANIFEST_NAME,
    PLAN_APPROVED,
    PLAN_DRAFT,
    DeciderKind,
    EntityRef,
    RunWorkspace,
    RunWorkspaceReport,
    StageAttribution,
    StageRecord,
    StageStatus,
    file_digest,
    verify_run_workspace,
)

#: The six destinations, from the one list the repository keeps (#227: a
#: duplicated list is a list that drifts). Wix and LinkedIn first, because that
#: is the order publication needs — LinkedIn's post carries the article URL.
CANONICAL_DESTINATIONS: tuple[str, ...] = DESTINATIONS

#: What the StageRecords say produced them. A pass-through decides nothing, so
#: its decider is ``code`` and it has no model or rule identity.
SKELETON_COMPONENT = "walking-skeleton"

#: What a canonical run records as the strategy that produced it. Distinct from
#: :data:`SKELETON_COMPONENT` so that a RunSummary says which of the two runs it
#: summarizes without a reader having to open the workspace.
GOLDEN_ENGINE_STRATEGY_REF = "golden-engine"

#: Written into every entity body **of the pass-through run**. A reader that
#: finds one of these files must be able to tell at a glance that it carries no
#: editorial content — and, since #351, that the workspace holding it is not a
#: canonical run. The canonical run writes this nowhere.
PASS_THROUGH_MARKER = "pass_through"

#: What the manifest states for every §4.1 input when the caller supplies no
#: input versions. A stage with no logic reads no contract, no lens and no
#: register, so there is nothing to record — and the manifest says that rather
#: than leaving the section out, because "the run read none" and "the run did
#: not say" are different facts about a run (#336).
SKELETON_READS_NO_INPUT = (
    "the walking skeleton is a fixture shadow run: every stage is a typed "
    "pass-through and reads no editorial input"
)

#: What the manifest states when a **canonical** run's caller recorded no §4.1
#: input versions. Deliberately a different sentence from
#: :data:`SKELETON_READS_NO_INPUT`: the canonical stages do read editorial
#: inputs, so the honest statement is about the caller's record of them and not
#: about the engine.
CANONICAL_INPUTS_NOT_STATED = (
    "this run's caller recorded no §4.1 input versions; the inputs the "
    "canonical stages read are not stated by this manifest"
)

#: §2.1: the workspace is one Actions artifact per run, 90 days.
WORKSPACE_RETENTION_DAYS = 90

#: The run harness stamps every execution (the editorial core reads no clock),
#: one fixed step apart, so that one fixture run's trace is the same shape
#: whatever the machine's speed.
_STAGE_SECONDS = 1

_INTERPRETATION_ENTITY_TYPE = "E-08"
_BOUNDARY_ENTITY_TYPE = "E-09"


class SkeletonError(RuntimeError):
    """The harness was asked for a run it cannot honestly make."""


class ProviderRefused(RuntimeError):
    """Something asked the pass-through run's provider for text."""


class RefusingProvider:
    """The "fake provider" of the walking skeleton: it answers nothing.

    A stage of SL-1 has no logic, so nothing in that run has anything to ask a
    model. Carrying a provider that refuses — rather than no provider at all —
    is what makes "no model calls" a property the run enforces instead of one it
    happens to have: a stage that grows a call before its slice arrives fails
    loudly here, in shadow, rather than quietly spending a budget.

    It is **not** reachable from the canonical run. :func:`run_golden_engine`
    takes its model boundaries as an argument and builds none, so there is
    nowhere for this to be substituted for a real transport.
    """

    def complete(self, *args: Any, **kwargs: Any) -> str:
        raise ProviderRefused(
            "the walking skeleton makes no model calls: every stage is a typed "
            "pass-through, and the real stages run through run_golden_engine "
            "over the production transport bindings instead"
        )


# ===========================================================================
# The fixture
# ===========================================================================


@dataclass(frozen=True)
class SkeletonFixture:
    """The fixture signal the skeleton walks, and the IDs derived from it.

    Derived rather than listed so that two runs of the same fixture produce the
    same names, and a run of a different fixture cannot collide with them.
    """

    signal_id: str = "sig-skeleton"
    unit_id: str = "unit-skeleton"

    @property
    def core_id(self) -> str:
        return f"core-{self.signal_id}"

    @property
    def interpretation_id(self) -> str:
        return f"int-{self.signal_id}"

    @property
    def boundary_id(self) -> str:
        return f"bnd-{self.signal_id}"

    @property
    def unit_dir(self) -> str:
        return f"units/{self.unit_id}"

    def destination_dir(self, destination: str) -> str:
        return f"{self.unit_dir}/destinations/{destination}"

    def destination_scope_key(self, destination: str) -> str:
        return f"{self.unit_id}/{destination}"

    def candidate_set_id(self, destination: str) -> str:
        return f"cs-{self.unit_id}-{destination}"

    def strategy_id(self, destination: str) -> str:
        return f"str-{self.unit_id}-{destination}"

    def plan_id(self, destination: str) -> str:
        return f"plan-{self.unit_id}-{destination}"

    def text_id(self, destination: str) -> str:
        return f"txt-{self.unit_id}-{destination}"

    def fingerprint_id(self, destination: str) -> str:
        return f"fp-{self.unit_id}-{destination}"


def fixture_run_context(
    fixture: SkeletonFixture, started_at: datetime
) -> RunContext:
    """The identity of one shadow skeleton run.

    Built directly rather than through ``RunContext.from_assignment``: there is
    no ContentAssignment behind a fixture signal, and inventing one would put a
    fabricated intake record into the evidence. The run is a dry run by
    construction — the canonical engine does not publish until SL-11.
    """

    return RunContext(
        run_id=create_run_id(),
        assignment_id=fixture.signal_id,
        started_at=started_at,
        strategy_ref=SKELETON_COMPONENT,
        strategy_version="1.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
    )


# ===========================================================================
# One stage execution
# ===========================================================================


class _Write(NamedTuple):
    """One entity a pass-through stage writes."""

    path: str
    entity_type: str
    entity_id: str
    version: Optional[int] = None
    extra: Optional[dict[str, Any]] = None


#: A stage execution's writer: it performs the writes and returns the entity
#: references the StageRecord then claims as its outputs.
_Writer = Callable[[RunWorkspace, str], tuple[EntityRef, ...]]


class _Execution(NamedTuple):
    """One execution of one stage: the scope it runs for, and what it writes."""

    scope_key: str
    writer: _Writer


def _body(
    entity_type: str,
    entity_id: str,
    version: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One pass-through entity body: its identity, and that it is a stub.

    Deliberately thin. The entity schemas are Step 1's and belong to the slices
    that produce real ones; what every reader of this run needs is to see that
    the file carries no editorial content at all.
    """

    body: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        PASS_THROUGH_MARKER: True,
        "produced_by": SKELETON_COMPONENT,
    }
    if version is not None:
        body["version"] = version
    body.update(extra or {})
    return body


def _entities(*writes: _Write) -> _Writer:
    """A writer that writes these entities through the workspace."""

    def write(workspace: RunWorkspace, stage: str) -> tuple[EntityRef, ...]:
        return _refs([
            workspace.write_entity(
                stage=stage,
                relative_path=item.path,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                version=item.version,
                payload=_body(
                    item.entity_type, item.entity_id, item.version, item.extra
                ),
            )
            for item in writes
        ])

    return write


def _refs(entries: Sequence[EntityIndexEntry]) -> tuple[EntityRef, ...]:
    return tuple(
        EntityRef(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            version=entry.version,
            digest=entry.digest,
        )
        for entry in entries
    )


def _nothing(workspace: RunWorkspace, stage: str) -> tuple[EntityRef, ...]:
    """A stage execution that writes no entity, and legitimately so.

    S-03 runs no enrichment round on a fixture with no gap, and S-15 has no
    workspace path at all (§2.3). Both still record that they ran: a stage that
    left no entity is not a stage that did not execute, and §4.1 asks the trace
    to be able to say which it was.
    """

    return ()


def _boundary_writer(fixture: SkeletonFixture) -> _Writer:
    """S-04's coordinated commit: the interpretation first, the marker last.

    Through ``commit_boundary`` rather than two plain writes, so the skeleton
    walks the §2.4 rule instead of writing an E-09 body of its own beside the
    module that owns that body's shape.
    """

    def write(workspace: RunWorkspace, stage: str) -> tuple[EntityRef, ...]:
        commit = commit_boundary(
            workspace,
            boundary_id=fixture.boundary_id,
            version=1,
            interpretations=(
                InterpretationVersion(
                    interpretation_id=fixture.interpretation_id,
                    version=1,
                    admissibility=Admissibility.ADMISSIBLE,
                    payload=_body(
                        _INTERPRETATION_ENTITY_TYPE,
                        fixture.interpretation_id,
                        1,
                    ),
                ),
            ),
            members=(
                BoundaryMember(
                    interpretation_id=fixture.interpretation_id,
                    version=1,
                    admissibility=Admissibility.ADMISSIBLE,
                ),
            ),
            payload={
                PASS_THROUGH_MARKER: True,
                "produced_by": SKELETON_COMPONENT,
            },
        )
        marker = workspace.run_dir / boundary_relative_path(commit.version)
        interpretations = tuple(
            EntityRef(
                entity_type=_INTERPRETATION_ENTITY_TYPE,
                entity_id=member.interpretation_id,
                version=member.version,
                digest=member.digest,
            )
            for member in commit.members
        )
        return interpretations + (
            EntityRef(
                entity_type=_BOUNDARY_ENTITY_TYPE,
                entity_id=commit.boundary_id,
                version=commit.version,
                digest=file_digest(marker),
            ),
        )

    return write


# ===========================================================================
# The pass-throughs, one per stage of the registry
# ===========================================================================


def _pass_throughs(
    fixture: SkeletonFixture, destinations: Sequence[str]
) -> dict[str, tuple[_Execution, ...]]:
    """Every stage of the canonical topology, as the executions it performs.

    Keyed by stage ID and consulted in the registry's order, so this table
    cannot put the stages in an order of its own. A destination-scoped stage
    has one execution per destination; S-11 has those and one more, because
    the barrier B1 it evaluates is unit-scoped (§0.2).
    """

    def per_destination(
        writer_for: Callable[[str], _Writer],
    ) -> tuple[_Execution, ...]:
        return tuple(
            _Execution(fixture.destination_scope_key(name), writer_for(name))
            for name in destinations
        )

    def strategy(destination: str) -> _Writer:
        candidates = fixture.candidate_set_id(destination)
        strategy_id = fixture.strategy_id(destination)
        return _entities(_Write(
            f"{fixture.destination_dir(destination)}/strategies/"
            f"{candidates}/{strategy_id}.json",
            "E-13",
            strategy_id,
        ))

    def selection(destination: str) -> _Writer:
        candidates = fixture.candidate_set_id(destination)
        return _entities(_Write(
            f"{fixture.destination_dir(destination)}/strategies/"
            f"{candidates}/selection.json",
            "StrategySelection",
            candidates,
        ))

    def draft_plan(destination: str) -> _Writer:
        plan = fixture.plan_id(destination)
        return _entities(_Write(
            f"{fixture.destination_dir(destination)}/plans/{plan}.v1.json",
            "E-14",
            plan,
            1,
            {"stage_of_version": PLAN_DRAFT},
        ))

    def approved_plan(destination: str) -> _Writer:
        directory = fixture.destination_dir(destination)
        plan = fixture.plan_id(destination)
        return _entities(
            _Write(
                f"{directory}/plans/{plan}.v2.json",
                "E-14",
                plan,
                2,
                {"stage_of_version": PLAN_APPROVED, "supersedes": f"{plan}.v1"},
            ),
            _Write(
                f"{directory}/verdicts/plan_{plan}.v2.json",
                "PlanVerdict",
                f"pv-{plan}",
                2,
            ),
        )

    def text(destination: str) -> _Writer:
        text_id = fixture.text_id(destination)
        return _entities(_Write(
            f"{fixture.destination_dir(destination)}/texts/{text_id}.v1.json",
            "E-15",
            text_id,
            1,
        ))

    def text_verdict(destination: str) -> _Writer:
        text_id = fixture.text_id(destination)
        return _entities(_Write(
            f"{fixture.destination_dir(destination)}/verdicts/"
            f"text_{text_id}.v1.json",
            "TextVerdict",
            f"tv-{text_id}",
            1,
        ))

    def publication(destination: str) -> _Writer:
        fingerprint = fixture.fingerprint_id(destination)
        return _entities(
            _Write(
                f"{fixture.destination_dir(destination)}/publication.json",
                "PublicationRef",
                f"pub-{fixture.unit_id}-{destination}",
                None,
                # Shadow: no external call was made, so there is no external
                # ID, no URL and no marker. The record says which it is.
                {"mode": "shadow", "published": False},
            ),
            _Write(
                f"fingerprints/{fingerprint}.json",
                "E-16",
                fingerprint,
            ),
        )

    return {
        "S-00": (_Execution(fixture.signal_id, _entities(_Write(
            "signal/selection.json", "E-01.selection", fixture.signal_id,
        ))),),
        "S-01": (_Execution(fixture.signal_id, _entities(
            _Write("signal/core/core.v1.json", "E-04", fixture.core_id, 1),
            _Write(
                "signal/relevance.ref.json",
                "E-04.relevance_ref",
                f"rel-{fixture.signal_id}",
            ),
        )),),
        "S-02": (_Execution(fixture.signal_id, _entities(
            _Write(
                "signal/features/features.v1.json",
                "E-05",
                f"feat-{fixture.signal_id}",
                1,
            ),
            _Write(
                "signal/assets/assets.v1.json",
                "E-06",
                f"ast-{fixture.signal_id}",
                1,
            ),
            _Write(
                "signal/notes/material_notes.json",
                "MaterialNotes",
                f"notes-{fixture.signal_id}",
            ),
        )),),
        # The enrichment loop runs no round on a fixture with no gap, so it
        # writes no version and no gap file. It still records that it ran.
        "S-03": (_Execution(fixture.signal_id, _nothing),),
        "S-04": (_Execution(fixture.signal_id, _boundary_writer(fixture)),),
        "S-05": (_Execution(fixture.signal_id, _entities(_Write(
            f"{fixture.unit_dir}/unit.json", "E-10", fixture.unit_id,
        ))),),
        "S-06": (_Execution(fixture.unit_id, _entities(_Write(
            f"{fixture.unit_dir}/anchor/anchor.v1.json",
            "E-11",
            f"anc-{fixture.unit_id}",
            1,
        ))),),
        # One execution, every destination: S-07 decides the destination set of
        # the unit, and these six decision files are the six folders.
        "S-07": (_Execution(fixture.unit_id, _entities(*(
            _Write(
                f"{fixture.destination_dir(name)}/decision.json",
                "E-12",
                f"dst-{fixture.unit_id}-{name}",
                None,
                {"mode": "generate_only"},
            )
            for name in destinations
        ))),),
        "S-08": per_destination(strategy),
        "S-09": per_destination(selection),
        "S-10": per_destination(draft_plan),
        # B1 blocks S-12, so the barrier round is recorded after the six plans
        # are approved and before any text is written.
        "S-11": per_destination(approved_plan) + (
            _Execution(fixture.unit_id, _entities(_Write(
                f"{fixture.unit_dir}/b1/round_1.json",
                "B1Round",
                f"b1-{fixture.unit_id}-r1",
                None,
                {"destinations": list(destinations), "passed": True},
            ))),
        ),
        "S-12": per_destination(text),
        "S-13": per_destination(text_verdict),
        "S-14": per_destination(publication),
        # Observation is post-run and writes into the ledger in SL-12. Here it
        # is the pass-through that completes the topology.
        "S-15": (_Execution("run", _nothing),),
    }


# ===========================================================================
# The pass-through run (SL-1)
# ===========================================================================


class SkeletonRun(NamedTuple):
    """One completed skeleton run and the evidence it produced."""

    run_context: RunContext
    run_dir: Path
    manifest: RunManifest
    verification: RunWorkspaceReport
    records: tuple[StageRecord, ...]
    summary: RunSummary
    summary_path: Path
    #: The provider the run carried and never asked (see :class:`RefusingProvider`).
    provider: RefusingProvider
    #: The commit of the run's learning records, which the summary states.
    records_commit: LedgerCommitReport
    #: The commit of the summary itself. A failure here is reported and nothing
    #: more: the run has already ended (§3.1).
    summary_commit: LedgerCommitReport

    @property
    def destination_dirs(self) -> tuple[Path, ...]:
        """The destination folders the run created, sorted by name."""

        return tuple(sorted(
            path
            for path in (self.run_dir / "units").glob("*/destinations/*")
            if path.is_dir()
        ))


def run_walking_skeleton(
    *,
    runs_root: Optional[Path] = None,
    fixture: Optional[SkeletonFixture] = None,
    run_context: Optional[RunContext] = None,
    started_at: Optional[datetime] = None,
    destinations: Sequence[str] = CANONICAL_DESTINATIONS,
    client: Optional[str] = None,
    call_budget_limit: int = DEFAULT_CEILING,
    ledger_dir: Optional[Path] = None,
    commit: bool = False,
    repo_root: Optional[Path] = None,
    commit_attempts: int = DEFAULT_PUSH_ATTEMPTS,
    commit_retry_seconds: float = DEFAULT_RETRY_SECONDS,
    code_identity: Optional[CodeIdentity] = None,
    inputs: Optional[RunInputs] = None,
) -> SkeletonRun:
    """Run the canonical topology end to end as pass-throughs, and report.

    SL-1's run, unchanged by #351 and deliberately so: it is the acceptance
    evidence for the harness below the stages, and every entity it writes
    declares itself a pass-through, so a workspace it produced can never be
    read as a canonical run. The canonical run is :func:`run_golden_engine`.

    ``commit`` is off by default: a shadow run that wrote to the repository
    because nobody said otherwise would be a production effect, and this slice
    has none. With it on, a failed commit is recorded in the report and the run
    still returns normally (§3.1).

    ``inputs`` are the §4.1 input versions the manifest states. A caller that
    loaded a register or a client contract hands them in (``run_inputs``);
    without them the run states, per input, that a fixture shadow run read
    none — see :data:`SKELETON_READS_NO_INPUT`.

    Raises only when the run cannot honestly be made: a destination list that
    is not the canonical six, a registry stage with no pass-through, or a
    sealed workspace that does not verify. None of those is a run with a defect
    in it; each is a run that must not be offered as evidence.
    """

    signal = fixture or SkeletonFixture()
    names = _checked_destinations(destinations)
    context = run_context or fixture_run_context(
        signal, started_at or datetime.now(tz=timezone.utc)
    )
    identity = (
        code_identity if code_identity is not None else resolve_code_identity()
    )

    budget = ArpCallBudget(RunCallBudget(call_budget_limit))
    provider = RefusingProvider()
    workspace = RunWorkspace.create(
        Path(runs_root) if runs_root is not None else EDITORIAL_RUNS_ROOT,
        context.run_id,
    )

    planned = _pass_throughs(signal, names)
    records: list[StageRecord] = []
    for stage in CANONICAL_TOPOLOGY.stages:
        if stage.stage_id not in planned:
            raise SkeletonError(
                f"the topology declares {stage.stage_id} and the skeleton has "
                "no pass-through for it; a walking skeleton that quietly skips "
                "a stage is not the canonical engine walking"
            )
        for execution in planned[stage.stage_id]:
            records.append(_execute(
                workspace,
                context,
                seq=len(records),
                stage=stage.stage_id,
                execution=execution,
            ))

    manifest = workspace.write_manifest(
        context,
        identity,
        inputs=(
            inputs
            if inputs is not None
            else RunInputs.stated_absent(SKELETON_READS_NO_INPUT)
        ),
    )
    verification = verify_run_workspace(workspace.run_dir.parent, context.run_id)

    ledger = _write_ledger(
        context=context,
        manifest=manifest,
        records=tuple(records),
        signal_ids=(signal.signal_id,),
        unit_ids=(signal.unit_id,),
        scopes=_scopes(signal, names),
        run_dir=workspace.run_dir,
        client=client or active_client(),
        budget=budget,
        code_identity=identity,
        # Every plan was approved at the first attempt and every text accepted
        # at version 1, because a pass-through has nothing to fail at. The
        # flags are recorded so that the rate is computable from the ledger.
        first_pass=tuple(
            DestinationFirstPass(
                destination=name,
                plan_first_pass=True,
                text_first_pass=True,
            )
            for name in names
        ),
        fingerprint_ids=tuple(signal.fingerprint_id(name) for name in names),
        # A pass-through run writes no durable learning record: the IDs above
        # name the destinations it passed through, not files on the ledger.
        record_paths=(),
        ledger_dir=ledger_dir,
        commit=commit,
        repo_root=repo_root,
        commit_attempts=commit_attempts,
        commit_retry_seconds=commit_retry_seconds,
    )
    return SkeletonRun(
        run_context=context,
        run_dir=workspace.run_dir,
        manifest=manifest,
        verification=verification,
        records=tuple(records),
        summary=ledger.summary,
        summary_path=ledger.summary_path,
        provider=provider,
        records_commit=ledger.records_commit,
        summary_commit=ledger.summary_commit,
    )


def _execute(
    workspace: RunWorkspace,
    context: RunContext,
    *,
    seq: int,
    stage: str,
    execution: _Execution,
) -> StageRecord:
    """Perform one stage execution and record it (§4.2)."""

    started = context.started_at + timedelta(seconds=seq * _STAGE_SECONDS)
    record = StageRecord(
        run_id=context.run_id,
        seq=seq,
        stage=stage,
        scope_key=execution.scope_key,
        started_at=started,
        ended_at=started + timedelta(seconds=_STAGE_SECONDS),
        created_by=StageAttribution(
            stage=stage,
            component=SKELETON_COMPONENT,
            decider=DeciderKind.CODE,
        ),
        outputs=execution.writer(workspace, stage),
        # No model call was made, and the record says so rather than leaving a
        # reader to infer it from a missing block.
        calls={"count": 0, "tokens_in": 0, "tokens_out": 0},
        status=StageStatus.COMPLETED,
    )
    workspace.write_stage_record(record)
    return record


# ===========================================================================
# The canonical run (#351)
# ===========================================================================


class GoldenEngineRun(NamedTuple):
    """One completed canonical run and the evidence it produced.

    Beside :class:`SkeletonRun` rather than instead of it, and the two are
    deliberately different types: a caller holding one of these has a run over
    the real stages, and no field of it can be satisfied by a pass-through.
    There is no ``provider`` here, because the canonical run builds none — its
    model boundaries are handed in.
    """

    run_context: RunContext
    run_dir: Path
    manifest: RunManifest
    verification: RunWorkspaceReport
    records: tuple[StageRecord, ...]
    summary: RunSummary
    summary_path: Path
    #: What the execution itself reported: the identities, the scopes and the
    #: first-pass flags no single StageRecord carries.
    execution: CanonicalExecution
    records_commit: LedgerCommitReport
    summary_commit: LedgerCommitReport

    @property
    def destination_dirs(self) -> tuple[Path, ...]:
        """The destination folders the run created, sorted by name."""

        return tuple(sorted(
            path
            for path in (self.run_dir / "units").glob("*/destinations/*")
            if path.is_dir()
        ))


def canonical_run_context(signal_id: str, started_at: datetime) -> RunContext:
    """The identity of one canonical shadow run.

    Built directly rather than through ``RunContext.from_assignment`` for the
    callers that have no ContentAssignment to hand — a diagnostic run over one
    intake record. The run is a dry run by construction: the canonical engine
    does not publish until SL-11, and this harness does not execute S-14 at all.
    """

    return RunContext(
        run_id=create_run_id(),
        assignment_id=signal_id,
        started_at=started_at,
        strategy_ref=GOLDEN_ENGINE_STRATEGY_REF,
        strategy_version="1.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
    )


def run_golden_engine(
    *,
    seams: GoldenEngineSeams,
    configuration: GoldenEngineConfiguration,
    signal: Mapping[str, Any],
    binding: ResearchBinding,
    runs_root: Optional[Path] = None,
    run_context: Optional[RunContext] = None,
    started_at: Optional[datetime] = None,
    destinations: Sequence[str] = CANONICAL_DESTINATIONS,
    client: Optional[str] = None,
    call_budget_limit: int = GOLDEN_ENGINE_MAX_CEILING,
    counters: Optional[AttemptCounterLedger] = None,
    now: Optional[datetime] = None,
    portfolio: Sequence[PortfolioFingerprint] = (),
    priors: Sequence[PriorPublication] = (),
    text_portfolio: Sequence[TextFingerprint] = (),
    ledger_dir: Optional[Path] = None,
    commit: bool = False,
    repo_root: Optional[Path] = None,
    commit_attempts: int = DEFAULT_PUSH_ATTEMPTS,
    commit_retry_seconds: float = DEFAULT_RETRY_SECONDS,
    code_identity: Optional[CodeIdentity] = None,
    inputs: Optional[RunInputs] = None,
) -> GoldenEngineRun:
    """Run the real S-00…S-13 over one intake record, seal it, and report.

    ``seams`` and ``configuration`` are required and have no defaults. That is
    the production-safety property of this signature: this function constructs
    no transport, reads no model configuration and loads no contract, so there
    is nowhere here for a fallback provider or a defaulted client value to
    appear — and nothing in it can reach :class:`RefusingProvider` either.

    ``call_budget_limit`` defaults to the canonical path's own ceiling and not to
    the legacy one. Step 2 §0.3 records 40 as "AS-IS: the current engine's
    ceiling", and §6 puts the six-destination minimum at 44 and the normal case
    at 61, so a complete canonical run has never fitted ``R1_MAX_CEILING``. It is
    a runaway guard rather than a target spend: the final number is SL-7's to set
    from measured data.

    ``commit`` is off by default, for the reason the pass-through run's is. With
    it on, a failed commit is recorded in the report and the run still returns
    normally (§3.1).

    Raises only when the run cannot honestly be made: a destination list that is
    not the canonical six, a registry stage the engine has no implementation
    for, a destination set S-07 did not decide about, or a sealed workspace that
    does not verify. None of those is a run with a defect in it; each is a run
    that must not be offered as evidence.
    """

    names = _checked_destinations(destinations)
    context = run_context or canonical_run_context(
        str(signal.get("SIGNAL_ID") or "unidentified-signal"),
        started_at or datetime.now(tz=timezone.utc),
    )
    identity = (
        code_identity if code_identity is not None else resolve_code_identity()
    )
    # The canonical path's own ceiling, not the legacy one: a clean
    # six-destination run records 50 model calls (Step 2 §6 puts the
    # six-destination minimum at 44 and the normal case at 61), so
    # `R1_MAX_CEILING` cannot admit one. Named explicitly, so the
    # legacy default, Wednesday's 56 and `R1_MAX_CEILING` are all
    # untouched and no other caller inherits 60.
    run_budget = RunCallBudget(
        call_budget_limit, hard_max=GOLDEN_ENGINE_MAX_CEILING
    )
    budget = ArpCallBudget(run_budget)
    workspace = RunWorkspace.create(
        Path(runs_root) if runs_root is not None else EDITORIAL_RUNS_ROOT,
        context.run_id,
    )
    # #171's counter is charged inside `llm_client.chat`, and only while a budget
    # is active. Without this the ceiling would bound nothing on the canonical
    # path: `ArpCallBudget` asks whether a unit of work can start, and §0.3 gives
    # the counter one consumer — "Every model call" (#351 review, 2026-10-01).
    with activate_call_budget(run_budget):
        execution = execute_canonical_topology(
            workspace=workspace,
            run_context=context,
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
            # The same ledger the summary is written to, and not this process's
            # default: S-14's durable E-16 records and the summary that reports
            # their commit are one run's records, so two roots would put them in
            # two places and leave the commit able to reach only one.
            ledger_dir=ledger_dir,
        )
    decided_every_destination(execution.records, names)

    manifest = workspace.write_manifest(
        context,
        identity,
        inputs=(
            inputs
            if inputs is not None
            else RunInputs.stated_absent(CANONICAL_INPUTS_NOT_STATED)
        ),
    )
    verification = verify_run_workspace(workspace.run_dir.parent, context.run_id)

    ledger = _write_ledger(
        context=context,
        manifest=manifest,
        records=execution.records,
        # A run refused at S-00 still names the signal it refused: the summary's
        # signal list is what the run was about, not what it accepted.
        signal_ids=execution.signal_ids or (context.assignment_id,),
        unit_ids=execution.unit_ids,
        scopes=execution.scopes,
        run_dir=workspace.run_dir,
        client=client or active_client(),
        budget=budget,
        code_identity=identity,
        first_pass=execution.first_pass,
        # S-14's output, since #308 wired it in shadow. Every ID here names a
        # record the run really wrote, to the workspace and to the durable
        # ledger — a fingerprint listed by a run that produced none would be a
        # learning record nobody can open.
        fingerprint_ids=tuple(
            item.fingerprint_id for item in execution.fingerprints
        ),
        # The same records, by the exact path each one went to, so the learning
        # commit commits what this run wrote and the summary's ledger_commit
        # is a statement about those files.
        record_paths=execution.fingerprint_paths,
        split_candidate=execution.split_candidate,
        ledger_dir=ledger_dir,
        commit=commit,
        repo_root=repo_root,
        commit_attempts=commit_attempts,
        commit_retry_seconds=commit_retry_seconds,
    )
    return GoldenEngineRun(
        run_context=context,
        run_dir=workspace.run_dir,
        manifest=manifest,
        verification=verification,
        records=execution.records,
        summary=ledger.summary,
        summary_path=ledger.summary_path,
        execution=execution,
        records_commit=ledger.records_commit,
        summary_commit=ledger.summary_commit,
    )


def decided_every_destination(
    records: Sequence[StageRecord], destinations: Sequence[str]
) -> None:
    """S-07 decided about every destination the run declared, or the run fails.

    The other half of Principle B, and the half a destination list alone cannot
    give: the declaration says six, and this says the run really produced six
    decisions, each citing a rule and a tier (§1, Post). A run that reached S-07
    and decided about five would otherwise seal a verified manifest over a unit
    one surface short, and nothing downstream would notice.

    A run that stopped **before** S-07 is not short of decisions — it has none,
    recorded as the ``SKIP`` that ended it — so there is nothing here to check.
    """

    decided = [record for record in records if record.stage == "S-07"]
    if not decided:
        return
    produced = sum(len(record.outputs) for record in decided)
    if produced != len(destinations):
        raise SkeletonError(
            f"S-07 wrote {produced} destination decision(s) and the run declared "
            f"{len(destinations)}. §1 asks for exactly one decision per declared "
            "destination, eligible or excluded; a run short of one has a surface "
            "nobody decided about"
        )


# ===========================================================================
# What both runs share
# ===========================================================================


def _checked_destinations(destinations: Sequence[str]) -> tuple[str, ...]:
    """The six, in publication order, or a refusal (Principle B, §0.2).

    Every slice that touches destinations covers all six. A run over a shorter
    list would still produce a verifiable manifest — which is exactly why the
    list is refused here rather than left to be noticed in a folder count.
    """

    ordered = tuple(destinations)
    if ordered != CANONICAL_DESTINATIONS:
        raise SkeletonError(
            "the skeleton runs over all six destinations in publication order "
            f"({', '.join(CANONICAL_DESTINATIONS)}); got "
            f"{', '.join(ordered) or 'none'}. Principle B: the code, the tests "
            "and the traces never assume fewer"
        )
    return ordered


class _LedgerStep(NamedTuple):
    """What the run's ledger step produced."""

    summary: RunSummary
    summary_path: Path
    records_commit: LedgerCommitReport
    summary_commit: LedgerCommitReport


def _write_ledger(
    *,
    context: RunContext,
    manifest: RunManifest,
    records: tuple[StageRecord, ...],
    signal_ids: Sequence[str],
    unit_ids: Sequence[str],
    scopes: Sequence[RunScope],
    run_dir: Path,
    client: str,
    budget: ArpCallBudget,
    code_identity: Optional[CodeIdentity],
    first_pass: Sequence[DestinationFirstPass],
    fingerprint_ids: Sequence[str],
    record_paths: Sequence[Path],
    ledger_dir: Optional[Path],
    commit: bool,
    repo_root: Optional[Path],
    commit_attempts: int,
    commit_retry_seconds: float,
    split_candidate: bool = False,
) -> _LedgerStep:
    """Write the RunSummary to the ledger, and commit if asked (§3.1, §3.2).

    Two commit steps, and they are two for a reason one cannot get around: the
    summary **states** the status of the ledger commit (§3.3), so the records
    it summarizes must be committed before it can be written. The summary's own
    commit is therefore the second step, and its failure is returned to the
    caller rather than written into the file that failed to be committed.

    What §3.1 promises holds either way: the records are on disk, the run does
    not wait, and nothing is undone. A failed learning commit is reported as
    such by the summary while the records it names stay where S-14 wrote them.

    ``record_paths`` are the durable learning records **this run** wrote, named
    one by one by the stage that wrote them. They are named and not globbed
    because the summary states this commit's status (§3.3): a status collected
    over whatever happened to be untracked under the ledger would be a claim
    about other runs' files as much as this one's. The canonical run hands over
    S-14's E-16 records; the pass-through run writes none, and its empty
    sequence is the honest value, not a gap. Observations arrive with S-15 in
    SL-12 and will hand their files to this same step.

    The identities and the scopes are arguments rather than derived, because the
    two runs know them differently: the pass-through run derives them from its
    fixture, and the canonical run is told them by the stages that produced
    them. Everything below that is identical, which is why it is one function.
    """

    records_commit = _commit(
        commit,
        kind="learning",
        run_id=context.run_id,
        paths=tuple(record_paths),
        repo_root=repo_root,
        attempts=commit_attempts,
        retry_seconds=commit_retry_seconds,
    )
    summary = RunSummary.for_run(
        run_context=context,
        manifest=manifest,
        records=records,
        scopes=scopes,
        client=client,
        signal_ids=signal_ids,
        unit_ids=unit_ids,
        workspace=WorkspaceRef(
            artifact_name=f"editorial-run-{context.run_id}",
            retention_days=WORKSPACE_RETENTION_DAYS,
            expires_on=_expiry(context.started_at),
            manifest_digest=file_digest(run_dir / MANIFEST_NAME),
        ),
        call_budget_limit=budget.limit,
        ledger_commit=records_commit.status,
        code_identity=code_identity,
        first_pass=first_pass,
        fingerprint_ids=fingerprint_ids,
        split_candidate=split_candidate,
    )
    summary_path = write_run_summary(summary, root=ledger_dir)
    summary_commit = _commit(
        commit,
        kind="run-summary",
        run_id=context.run_id,
        paths=(summary_path,),
        repo_root=repo_root,
        attempts=commit_attempts,
        retry_seconds=commit_retry_seconds,
    )
    return _LedgerStep(summary, summary_path, records_commit, summary_commit)


def _commit(
    asked: bool,
    *,
    kind: str,
    run_id: str,
    paths: Sequence[Path],
    repo_root: Optional[Path],
    attempts: int,
    retry_seconds: float,
) -> LedgerCommitReport:
    if not asked:
        return LedgerCommitReport(status=LedgerCommitStatus.NOT_ATTEMPTED)
    return commit_ledger(
        paths=paths,
        message=commit_message(kind, run_id, paths),
        repo_root=repo_root,
        attempts=attempts,
        retry_seconds=retry_seconds,
    )


def _scopes(
    fixture: SkeletonFixture, destinations: Sequence[str]
) -> tuple[RunScope, ...]:
    """Every scope the pass-through run had, for the §3.3 final-state table.

    The signal, the unit and the six destinations — and no publication scope,
    because a shadow run makes no external call and a publication that never
    happened must not appear in the ledger as one that resolved. When S-14
    publishes for real (SL-11), its scopes join this list.

    The canonical run declares its own (``CanonicalExecution.scopes``), from
    what it actually reached rather than from a fixture's names.
    """

    return (
        RunScope(scope=OutcomeScope.SIGNAL, scope_key=fixture.signal_id),
        RunScope(scope=OutcomeScope.UNIT, scope_key=fixture.unit_id),
    ) + tuple(
        RunScope(
            scope=OutcomeScope.DESTINATION,
            scope_key=fixture.destination_scope_key(name),
        )
        for name in destinations
    )


def _expiry(started_at: datetime) -> date:
    """When the run's 90-day workspace artifact stops being readable (§2.1)."""

    return (started_at + timedelta(days=WORKSPACE_RETENTION_DAYS)).date()
