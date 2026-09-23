"""The walking skeleton: the whole topology, end to end (Issue #293, slice SL-1).

SL-1's goal is "a walking skeleton of the one canonical engine: every stage
S-00…S-15 exists as a typed pass-through, run end to end on a fixture signal
with fake providers" (Step 6 §2). This module is that run. It is the harness
the earlier SL-1 pieces were built for, and it holds **no stage logic at all**:
each stage writes the entities §2.2 gives it, records what it did, and hands
on. What a stage decides arrives in SL-3 … SL-6.

What it proves, and how
-----------------------
**The topology executes.** The stages come from ``CANONICAL_TOPOLOGY`` in the
registry's own order, and a stage the registry declares without a pass-through
here stops the run (:class:`SkeletonError`). The skeleton cannot execute a
different engine from the one the digest names, because it keeps no second
list of stages.

**Six destinations.** Every destination-scoped stage loops over all six
(Principle B, Step 6 §0.2), from the one list the repository already keeps.
The six destination folders in the workspace are what that looks like on disk.

**The manifest verifies.** Entities go through :class:`RunWorkspace`, so
create-once, the version in the key and §2.3 write ownership hold; the
manifest is written last, and ``verify_run_workspace`` is run over the sealed
result before the run reports success.

**The ledger takes the summary.** The run ends with a public-safe RunSummary
in ``data/editorial/`` (§3.2) and, when the caller asks for it, a commit. A
commit that fails is recorded and the run still ends normally (§3.1) — which
is the one behaviour of this harness that production will depend on.

Production safety
-----------------
Shadow only, and unable to be otherwise:

- there are no model calls. The run carries an :class:`ArpCallBudget` and
  spends nothing from it, and the provider it carries is
  :class:`RefusingProvider`, which raises if anything asks it for text;
- there is no external publish call and no publication marker. S-14 runs in
  shadow: it writes the run's own publication record and fingerprint, and
  consults no idempotency authority, because it publishes nothing;
- the ledger commit is off unless a caller turns it on, so running the
  skeleton on a developer's machine or in a test cannot touch the repository.

S-15 is post-run: in the target it is a scheduled observation job (SL-12) over
already-published destinations. It runs here, in order, as the pass-through
the slice asks for — writing no entity, because §2.3 gives it no workspace
path and the workspace writer would refuse one.

Sources: ``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md`` §2 (SL-1)
and §0.2; ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§2.2, §2.3, §3 and §4.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

from src.editorial_core.arp import OutcomeScope
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.publishing.publication_markers import DESTINATIONS, active_client
from src.run.boundary_commit import (
    Admissibility,
    BoundaryMember,
    InterpretationVersion,
    boundary_relative_path,
    commit_boundary,
)
from src.run.call_budget import DEFAULT_CEILING, RunCallBudget
from src.run.call_budget_arp import ArpCallBudget
from src.run.code_identity import CodeIdentity, resolve_code_identity
from src.run.ledger import (
    DEFAULT_PUSH_ATTEMPTS,
    DEFAULT_RETRY_SECONDS,
    LedgerCommitReport,
    LedgerCommitStatus,
    commit_ledger,
    commit_message,
)
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import EntityIndexEntry, RunManifest
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

#: Written into every entity body. A reader that finds one of these files must
#: be able to tell at a glance that it carries no editorial content.
PASS_THROUGH_MARKER = "pass_through"

#: §2.1: the workspace is one Actions artifact per run, 90 days.
WORKSPACE_RETENTION_DAYS = 90

#: The run harness stamps every execution (the editorial core reads no clock),
#: one fixed step apart, so that one fixture run's trace is the same shape
#: whatever the machine's speed.
_STAGE_SECONDS = 1

_INTERPRETATION_ENTITY_TYPE = "E-08"
_BOUNDARY_ENTITY_TYPE = "E-09"


class SkeletonError(RuntimeError):
    """The skeleton was asked for a run it cannot honestly make."""


class ProviderRefused(RuntimeError):
    """Something asked the shadow run's provider for text."""


class RefusingProvider:
    """The "fake provider" of the walking skeleton: it answers nothing.

    A stage of this slice has no logic, so nothing in the run has anything to
    ask a model. Carrying a provider that refuses — rather than no provider at
    all — is what makes "no model calls" a property the run enforces instead of
    one it happens to have: a stage that grows a call before its slice arrives
    fails loudly here, in shadow, rather than quietly spending a budget.
    """

    def complete(self, *args: Any, **kwargs: Any) -> str:
        raise ProviderRefused(
            "the walking skeleton makes no model calls: every stage is a typed "
            "pass-through, and the stage logic that needs a provider arrives "
            "in SL-3 and later"
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
# The run
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
) -> SkeletonRun:
    """Run the canonical topology end to end as pass-throughs, and report.

    ``commit`` is off by default: a shadow run that wrote to the repository
    because nobody said otherwise would be a production effect, and this slice
    has none. With it on, a failed commit is recorded in the report and the run
    still returns normally (§3.1).

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

    manifest = workspace.write_manifest(context, identity)
    verification = verify_run_workspace(workspace.run_dir.parent, context.run_id)

    ledger = _write_ledger(
        context=context,
        manifest=manifest,
        records=tuple(records),
        fixture=signal,
        destinations=names,
        run_dir=workspace.run_dir,
        client=client or active_client(),
        budget=budget,
        code_identity=identity,
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
    fixture: SkeletonFixture,
    destinations: Sequence[str],
    run_dir: Path,
    client: str,
    budget: ArpCallBudget,
    code_identity: Optional[CodeIdentity],
    ledger_dir: Optional[Path],
    commit: bool,
    repo_root: Optional[Path],
    commit_attempts: int,
    commit_retry_seconds: float,
) -> _LedgerStep:
    """Write the RunSummary to the ledger, and commit if asked (§3.1, §3.2).

    Two commit steps, and they are two for a reason one cannot get around: the
    summary **states** the status of the ledger commit (§3.3), so the records
    it summarizes must be committed before it can be written. The summary's own
    commit is therefore the second step, and its failure is returned to the
    caller rather than written into the file that failed to be committed.

    What §3.1 promises holds either way: the records are on disk, the run does
    not wait, and nothing is undone. This slice writes no learning record yet —
    fingerprints arrive with S-14 in SL-7 and observations with S-15 in SL-12 —
    so the first step normally has nothing to commit, and says so.
    """

    records_commit = _commit(
        commit,
        kind="learning",
        run_id=context.run_id,
        # None yet: fingerprints arrive with S-14 in SL-7 and observations with
        # S-15 in SL-12, and each will hand its files to this step.
        paths=(),
        repo_root=repo_root,
        attempts=commit_attempts,
        retry_seconds=commit_retry_seconds,
    )
    summary = RunSummary.for_run(
        run_context=context,
        manifest=manifest,
        records=records,
        scopes=_scopes(fixture, destinations),
        client=client,
        signal_ids=(fixture.signal_id,),
        unit_ids=(fixture.unit_id,),
        workspace=WorkspaceRef(
            artifact_name=f"editorial-run-{context.run_id}",
            retention_days=WORKSPACE_RETENTION_DAYS,
            expires_on=_expiry(context.started_at),
            manifest_digest=file_digest(run_dir / MANIFEST_NAME),
        ),
        call_budget_limit=budget.limit,
        ledger_commit=records_commit.status,
        code_identity=code_identity,
        # Every plan was approved at the first attempt and every text accepted
        # at version 1, because a pass-through has nothing to fail at. The
        # flags are recorded so that the rate is computable from the ledger.
        first_pass=tuple(
            DestinationFirstPass(
                destination=name,
                plan_first_pass=True,
                text_first_pass=True,
            )
            for name in destinations
        ),
        fingerprint_ids=tuple(
            fixture.fingerprint_id(name) for name in destinations
        ),
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
    """Every scope this run had, for the summary's final-state table (§3.3).

    The signal, the unit and the six destinations — and no publication scope,
    because a shadow run makes no external call and a publication that never
    happened must not appear in the ledger as one that resolved. When S-14
    publishes for real (SL-11), its scopes join this list.
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
