"""The run workspace: create-once storage and write ownership (Issue #291).

Step 3 gives the canonical engine two storage tiers. This module is tier 1:
the run workspace at ``reports/editorial_runs/<run_id>/`` (§2.1), the layout
it holds (§2.2), the table saying which stage owns which path (§2.3), the
StageRecord written per stage execution (§4.2) and the manifest the run
harness writes last (§4.3). The durable ledger is tier 2 and is not here.

Four properties this module exists to make refusable rather than merely
documented:

``P1`` create-once
    Every file is written once, through the same ``atomic_write_json``
    link(2) commit the legacy run namespace has always used — one create-once
    mechanism in the repository, not a second one beside it. A writer that
    finds the path taken raises ``ArtifactCollisionError``; change means a new
    version file with ``supersedes``, never an edit.
``P2`` the version is in the key
    A versioned entity states its version in its file name
    (``core.v2.json``), and the writer refuses a version the name does not
    state. No reader ever has to guess "the latest" from a modification time.
``P6`` write ownership
    Each path pattern has exactly one writing stage (§2.3). A write outside a
    stage's patterns is refused where it is attempted, and — because the
    manifest records the writer of every file — it stays detectable
    afterwards from the manifest alone.
manifest last
    ``manifest.json`` is written after everything else. Until it exists the
    run is ``incomplete``: its files stay for forensics and no other run reads
    them as a source (§4.3). Writing it seals the workspace, which is what
    makes "last" a property rather than an intention. Runs are not resumable,
    so an incomplete run is never reopened either — a crashed run becomes a
    new run with a new ``run_id``.

:func:`verify_run_workspace` is the reader's side of all four, and the one
``verify_run_provenance`` delegates to (``src/artifacts/provenance.py``).

This module holds no stage logic and no clock: a StageRecord's timestamps are
its stage's, handed in. Sources: ``04_STEP3_STORAGE_AND_RUN_TRACE.md`` §1–§2
and §4, ``01_STEP1_TYPED_ENTITIES.md`` §0.1 and §0.4.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as _PydanticValidationError

# The repository's one create-once commit and its one path-component
# validator, reused rather than copied: two answers to "may this be written
# here" would eventually be two different answers.
from src.artifacts import (
    ArtifactCollisionError,
    _validate_path_component,
    atomic_write_json,
)
from src.run.code_identity import CodeIdentity
from src.run.run_context import RunContext
from src.run.run_manifest import (
    EntityIndexEntry,
    RunManifest,
    TraceIndexEntry,
    verify_run_digest,
    verify_topology_digest,
)

#: Root of tier 1 (§2.1). The key is the ``run_id`` alone: signal IDs are
#: manifest attributes, never directory keys (AD-04).
EDITORIAL_RUNS_ROOT = Path("reports/editorial_runs")

MANIFEST_NAME = "manifest.json"
TRACE_DIRECTORY = "trace"

#: The manifest's writer in the §2.3 table — the run harness, not a stage.
RUN_HARNESS = "run-harness"

#: ``trace/*`` has no fixed owner: §2.3 gives each file to "the stage named in
#: the file". :func:`owner_of` returns this, and the trace is checked against
#: each record's own ``created_by.stage`` instead.
TRACE_STAGE = "stage-named-in-the-trace-file"

_STAGE_ID_PATTERN = r"^S-(?:0\d|1[0-5])$"
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: Schema version of the StageRecord contract shape.
_STAGE_RECORD_SCHEMA_VERSION = "1.0"

#: ``core.v2.json`` → 2. The version sits between dots so that a name may
#: carry an ID with digits in it and still state exactly one version.
_VERSION_IN_NAME = re.compile(r"\.v(\d+)\.")

#: ``stage_of_version`` is the one field of a payload the ownership table
#: reads: ``plans/*`` is the single row §2.3 splits between two stages by what
#: the version is rather than by where it sits.
_STAGE_OF_VERSION = "stage_of_version"

PLAN_DRAFT = "draft"
PLAN_APPROVED = "approved"


class RunWorkspaceError(RuntimeError):
    """The workspace was asked for something its contract refuses."""


class WriteOwnershipError(RunWorkspaceError):
    """A stage wrote, or is recorded as having written, a path it does not own."""


class IncompleteRunError(RunWorkspaceError):
    """A run with no manifest was asked for as a source (§4.3)."""


class WorkspaceVerificationError(RunWorkspaceError):
    """The workspace does not match the manifest that indexes it."""


# ===========================================================================
# Write ownership (§2.3)
# ===========================================================================


class PathOwnership(BaseModel):
    """One row of the §2.3 write-ownership table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    #: Set only for ``plans/*``: S-10 writes the draft version and S-11 the
    #: approved one, into the same directory, so that row is decided by the
    #: version's own ``stage_of_version`` and not by its path.
    stage_of_version: Optional[str] = None


#: The §2.3 table, in the order it is consulted: the first row that matches
#: owns the path. Order is how the table says "v1 belongs to S-01 or S-02 and
#: every later version to S-03" without a second vocabulary for version
#: ranges — the exact name is listed above the pattern that also matches it.
WRITE_OWNERSHIP: tuple[PathOwnership, ...] = (
    PathOwnership(pattern=MANIFEST_NAME, owner=RUN_HARNESS),
    PathOwnership(pattern=f"{TRACE_DIRECTORY}/*", owner=TRACE_STAGE),
    PathOwnership(pattern="signal/selection.json", owner="S-00"),
    PathOwnership(pattern="signal/core/core.v1.json", owner="S-01"),
    PathOwnership(pattern="signal/relevance.ref.json", owner="S-01"),
    PathOwnership(pattern="signal/core/core.v*.json", owner="S-03"),
    PathOwnership(pattern="signal/features/features.v1.json", owner="S-02"),
    PathOwnership(pattern="signal/features/features.v*.json", owner="S-03"),
    PathOwnership(pattern="signal/assets/assets.v1.json", owner="S-02"),
    PathOwnership(pattern="signal/assets/assets.v*.json", owner="S-03"),
    PathOwnership(pattern="signal/notes/*", owner="S-02"),
    PathOwnership(pattern="signal/gaps/*", owner="S-03"),
    PathOwnership(pattern="signal/boundary/**", owner="S-04"),
    PathOwnership(pattern="units/*/unit.json", owner="S-05"),
    PathOwnership(pattern="units/*/anchor/*", owner="S-06"),
    PathOwnership(pattern="units/*/b1/*", owner="S-11"),
    PathOwnership(pattern="units/*/destinations/*/decision.json", owner="S-07"),
    PathOwnership(
        pattern="units/*/destinations/*/strategies/*/selection.json", owner="S-09"
    ),
    PathOwnership(pattern="units/*/destinations/*/strategies/*/*", owner="S-08"),
    PathOwnership(
        pattern="units/*/destinations/*/plans/*",
        owner="S-10",
        stage_of_version=PLAN_DRAFT,
    ),
    PathOwnership(
        pattern="units/*/destinations/*/plans/*",
        owner="S-11",
        stage_of_version=PLAN_APPROVED,
    ),
    PathOwnership(pattern="units/*/destinations/*/verdicts/plan_*", owner="S-11"),
    PathOwnership(pattern="units/*/destinations/*/texts/*", owner="S-12"),
    PathOwnership(pattern="units/*/destinations/*/verdicts/text_*", owner="S-13"),
    PathOwnership(pattern="units/*/destinations/*/publication.json", owner="S-14"),
    PathOwnership(pattern="fingerprints/*", owner="S-14"),
)


def owner_of(relative_path: str, *, stage_of_version: Any = None) -> str:
    """The one stage §2.3 allows to write this path.

    Raises when no row matches, which is the same refusal as a wrong writer
    and for the same reason: the layout in §2.2 is the whole set of places a
    run has, so a path outside it is owned by nobody and written by nobody.
    """

    for row in WRITE_OWNERSHIP:
        if not _matches(row.pattern, relative_path):
            continue
        discriminated = row.stage_of_version is not None
        if discriminated and row.stage_of_version != stage_of_version:
            continue
        return row.owner
    if any(_matches(row.pattern, relative_path) for row in WRITE_OWNERSHIP):
        raise WriteOwnershipError(
            f"no stage owns {relative_path!r} for "
            f"{_STAGE_OF_VERSION}={stage_of_version!r}; §2.3 splits that path "
            f"between {PLAN_DRAFT!r} (S-10) and {PLAN_APPROVED!r} (S-11), and "
            "a version that declares neither belongs to neither"
        )
    raise WriteOwnershipError(
        f"no stage owns {relative_path!r}: it is outside the run workspace "
        "layout (§2.2), and a path no pattern covers has no writer"
    )


def _matches(pattern: str, relative_path: str) -> bool:
    """Does the POSIX path match the pattern?

    ``*`` stands for exactly one path segment, with optional literal text
    around it (``plan_*``); ``**`` stands for one or more segments. Neither
    ``fnmatch``, whose ``*`` crosses ``/``, nor ``PurePath.match``, which
    anchors at the right, says that, so the walk is written out.
    """

    return _match_segments(pattern.split("/"), relative_path.split("/"))


def _match_segments(pattern: list[str], parts: list[str]) -> bool:
    if not pattern:
        return not parts
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(
            _match_segments(rest, parts[index:]) for index in range(1, len(parts) + 1)
        )
    if not parts:
        return False
    return _segment_matches(head, parts[0]) and _match_segments(rest, parts[1:])


def _segment_matches(pattern: str, part: str) -> bool:
    if "*" not in pattern:
        return pattern == part
    prefix, _, suffix = pattern.partition("*")
    return (
        len(part) >= len(prefix) + len(suffix)
        and part.startswith(prefix)
        and part.endswith(suffix)
    )


# ===========================================================================
# Names, paths and digests
# ===========================================================================


def versioned_name(stem: str, version: int, suffix: str = ".json") -> str:
    """``("core", 2)`` → ``core.v2.json``: P2, the version is in the key."""

    if version < 1:
        raise ValueError(f"a version starts at 1; got {version}")
    return f"{stem}.v{version}{suffix}"


def version_in_name(file_name: str) -> Optional[int]:
    """The version a file name states, or ``None`` when it states none."""

    match = _VERSION_IN_NAME.search(file_name)
    return int(match.group(1)) if match else None


def file_digest(path: Path) -> str:
    """``sha256:<hex>`` over the exact bytes on disk."""

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_editorial_run_dir(runs_root: Path, run_id: str) -> Path:
    """``<runs_root>/<run_id>``, with ``run_id`` validated. Creates nothing."""

    _validate_path_component(run_id, "run_id")
    return Path(runs_root) / run_id


def _validated_relative_path(relative_path: str) -> str:
    """A workspace-relative POSIX path, or a refusal.

    Checked before any path is built, exactly as the legacy run namespace
    checks its two key components: nothing absolute, nothing empty and
    nothing that could climb out of the run it belongs to.
    """

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise RunWorkspaceError(
            f"a workspace path must be a non-blank string; got {relative_path!r}"
        )
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("/"):
        raise RunWorkspaceError(f"a workspace path must be relative: {relative_path!r}")
    parts = normalized.split("/")
    for part in parts:
        _validate_path_component(part, "workspace path component")
    return "/".join(parts)


def stage_record_file_name(record: "StageRecord") -> str:
    """``<seq>_<stage>_<scope-key>.json`` (§2.2), zero-padded so that the
    directory's own order is the execution order."""

    scope = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in record.scope_key
    )
    return f"{record.seq:04d}_{record.stage}_{scope}.json"


# ===========================================================================
# StageRecord (§4.2)
# ===========================================================================


class _Record(BaseModel):
    """Every trace record is immutable and rejects fields it does not know."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DeciderKind(str, Enum):
    """What decided (Step 1 §0.4), following the existing ``EvaluatorKind``.

    ``human_review`` is deliberately absent: no production stage waits for a
    person (I-01, I-02).
    """

    MODEL = "model"
    RULE = "rule"
    CODE = "code"


class StageStatus(str, Enum):
    """Whether the execution itself finished (§4.2).

    Not the ARP outcome: a stage that ran to the end and skipped a
    destination is ``completed``, with the SKIP in ``outcomes``.
    """

    COMPLETED = "completed"
    FAILED_INFRASTRUCTURE = "failed_infrastructure"


class StageAttribution(_Record):
    """What produced a record (Step 1 §0.4).

    Prompts and text are never here: a request digest proves which request
    was made without carrying what it said (P8, the ``stage_routing``
    precedent).
    """

    stage: str = Field(pattern=_STAGE_ID_PATTERN)
    component: str = Field(min_length=1)
    decider: DeciderKind
    #: Model or rule identity and version. Absent for a ``code`` decider,
    #: which is its own identity.
    decider_identity: Optional[str] = None
    #: From ``stage_routing``. Absent when the stage issued no model request.
    request_digest: Optional[str] = Field(default=None, pattern=_DIGEST_PATTERN)


class EntityRef(_Record):
    """An entity version a stage read or wrote (§4.2)."""

    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    version: Optional[int] = Field(default=None, ge=1)
    digest: str = Field(pattern=_DIGEST_PATTERN)


class StageRecord(_Record):
    """One stage execution.

    One file per execution, not per stage: a stage that runs again — a
    re-entry, a further attempt — writes a new record with a higher ``seq``
    rather than a new version of the old one. The re-entries are the evidence
    the trace exists to hold (§4.4).

    ``run_id`` and ``schema_version`` are not in the §4.2 field table but are
    written all the same: P7 has every reader validate schema version, run
    binding and digest before use, and a record that cannot say which run it
    belongs to cannot be strictly reloaded at all.
    """

    schema_version: str = _STAGE_RECORD_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    #: Monotonic within the run.
    seq: int = Field(ge=0)
    stage: str = Field(pattern=_STAGE_ID_PATTERN)
    #: e.g. ``signal``, ``unit_7/linkedin/attempt_2``.
    scope_key: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime
    created_by: StageAttribution
    inputs: tuple[EntityRef, ...] = ()
    outputs: tuple[EntityRef, ...] = ()
    #: §4.2 also gives a StageRecord its routing evidence, its call
    #: accounting, its OutcomeRecords and its PrecedenceApplications. Their
    #: shapes belong to the ARP plumbing (NB-01c), so they are carried here as
    #: written rather than typed against stage contracts that do not exist
    #: yet. What this slice fixes is that they have a place and travel with
    #: the execution they describe.
    routing: Optional[dict[str, Any]] = None
    calls: Optional[dict[str, Any]] = None
    outcomes: tuple[dict[str, Any], ...] = ()
    precedence: tuple[dict[str, Any], ...] = ()
    status: StageStatus

    @field_validator("schema_version", mode="after")
    @classmethod
    def _schema_version_known(cls, value: str) -> str:
        if value != _STAGE_RECORD_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {_STAGE_RECORD_SCHEMA_VERSION!r}; "
                f"got {value!r}"
            )
        return value

    @field_validator("started_at", "ended_at", mode="after")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _internally_consistent(self) -> "StageRecord":
        if self.created_by.stage != self.stage:
            raise ValueError(
                f"the record is stage {self.stage} but is attributed to "
                f"{self.created_by.stage}; attribution is not a second opinion"
            )
        if self.ended_at < self.started_at:
            raise ValueError("a stage execution cannot end before it started")
        return self

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible: enums as values, timestamps as ISO-8601 UTC."""

        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageRecord":
        """Strictly reload one record (P7), or say what is wrong with it."""

        if not isinstance(data, dict):
            raise ValueError(
                f"StageRecord.from_dict expects a dict; got {type(data).__name__}"
            )
        try:
            return cls.model_validate(data)
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(f"StageRecord field '{loc}': {first['msg']}") from exc


# ===========================================================================
# The writer
# ===========================================================================


class RunWorkspace:
    """One run's workspace, and the only thing that writes into it.

    It keeps the index as it goes — every write returns the manifest entry it
    produced — so the manifest is assembled from what was actually written
    rather than from what a caller later says was written. That is what makes
    the entity index evidence instead of a second, optimistic description.
    """

    def __init__(self, run_dir: Path, run_id: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self._entities: list[EntityIndexEntry] = []
        self._trace: list[TraceIndexEntry] = []
        self._sealed = False

    @classmethod
    def create(cls, runs_root: Path, run_id: str) -> "RunWorkspace":
        """Create the workspace of a new run under ``runs_root``.

        An existing directory is refused rather than reopened. Runs are not
        resumable (§4.3), so a second run in one directory could only be a
        ``run_id`` collision or a resumption, and both are wrong.
        """

        run_dir = resolve_editorial_run_dir(runs_root, run_id)
        try:
            run_dir.mkdir(parents=True)
        except FileExistsError as exc:
            raise ArtifactCollisionError(
                f"a run workspace already exists at {run_dir} — a run writes "
                "its workspace once, and a crashed run is never resumed"
            ) from exc
        return cls(run_dir, run_id)

    @property
    def sealed(self) -> bool:
        """Has the manifest been written? Nothing follows it (§4.3)."""

        return self._sealed

    def write_entity(
        self,
        *,
        stage: str,
        relative_path: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        version: Optional[int] = None,
    ) -> EntityIndexEntry:
        """Write one entity version and index it.

        Refuses, in this order: a write after the manifest, because nothing
        follows the manifest (§4.3); a path outside the §2.2 layout; a path
        §2.3 gives to another stage (P6); a version the file name does not
        state (P2); and a path already written (P1).
        """

        self._refuse_when_sealed(f"write {relative_path!r}")
        relative = _validated_relative_path(relative_path)
        owner = owner_of(relative, stage_of_version=payload.get(_STAGE_OF_VERSION))
        if owner == RUN_HARNESS:
            raise WriteOwnershipError(
                f"{relative} is the run harness's to write, at the end of the "
                "run; use write_manifest"
            )
        if owner == TRACE_STAGE:
            raise WriteOwnershipError(
                f"{relative} is a stage record, not an entity; use "
                "write_stage_record, which names the stage in the file"
            )
        if owner != stage:
            raise WriteOwnershipError(
                f"{stage} may not write {relative}: §2.3 gives that path to "
                f"{owner}, and each path pattern has exactly one writing stage"
            )
        stated = version_in_name(relative.rsplit("/", 1)[-1])
        if stated != version:
            raise RunWorkspaceError(
                f"{relative} states version {stated!r} in its name but is being "
                f"written as version {version!r}; the version is in the key (P2)"
            )

        path = self.run_dir / relative
        atomic_write_json(path, payload)
        entry = EntityIndexEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            version=version,
            path=relative,
            digest=file_digest(path),
            writer_stage=stage,
        )
        self._entities.append(entry)
        return entry

    def write_stage_record(self, record: StageRecord) -> TraceIndexEntry:
        """Write one StageRecord into ``trace/`` and index it (§4.2)."""

        self._refuse_when_sealed("write a stage record")
        if record.run_id != self.run_id:
            raise RunWorkspaceError(
                f"stage record belongs to run {record.run_id!r}, not to "
                f"{self.run_id!r}"
            )
        if self._trace and record.seq <= self._trace[-1].seq:
            raise RunWorkspaceError(
                f"stage record seq {record.seq} does not follow "
                f"{self._trace[-1].seq}; seq is monotonic within the run (§4.2)"
            )

        relative = f"{TRACE_DIRECTORY}/{stage_record_file_name(record)}"
        path = self.run_dir / relative
        atomic_write_json(path, record.to_dict())
        entry = TraceIndexEntry(
            seq=record.seq,
            stage=record.stage,
            scope_key=record.scope_key,
            path=relative,
            digest=file_digest(path),
        )
        self._trace.append(entry)
        return entry

    def write_manifest(
        self,
        run_context: RunContext,
        code_identity: Optional[CodeIdentity] = None,
    ) -> RunManifest:
        """Write ``manifest.json`` last, and seal the workspace (§4.3).

        Until this returns the run is ``incomplete`` and no other run may read
        it. Writing it seals the workspace: every writer here refuses
        afterwards, so "the manifest is written last" is something the code
        enforces rather than something the caller remembers.
        """

        self._refuse_when_sealed("write the manifest")
        if run_context.run_id != self.run_id:
            raise RunWorkspaceError(
                f"run context belongs to run {run_context.run_id!r}, not to "
                f"{self.run_id!r}"
            )
        manifest = RunManifest.for_run(
            run_context,
            code_identity,
            entities=tuple(self._entities),
            trace=tuple(self._trace),
        )
        atomic_write_json(self.run_dir / MANIFEST_NAME, manifest.to_dict())
        self._sealed = True
        return manifest

    def _refuse_when_sealed(self, what: str) -> None:
        if self._sealed:
            raise RunWorkspaceError(
                f"cannot {what}: the manifest is written and nothing follows "
                "it (§4.3). A run that has more to say is a new run"
            )


# ===========================================================================
# Reading
# ===========================================================================


def is_complete(run_dir: Path) -> bool:
    """Does the run have its manifest, and is it therefore complete (§4.3)?"""

    return (run_dir / MANIFEST_NAME).is_file()


def load_manifest(run_dir: Path) -> RunManifest:
    """Read and strictly validate one run's manifest.

    A missing manifest is ``IncompleteRunError`` rather than a file error: the
    run is not broken, it is unfinished, and the difference is what a reader
    needs to know.
    """

    path = run_dir / MANIFEST_NAME
    if not path.is_file():
        raise IncompleteRunError(
            f"the run at {run_dir} has no {MANIFEST_NAME}: it is incomplete, "
            "and an incomplete run is never read as a source (§4.3). Its files "
            "remain for forensics"
        )
    data = _load_json_object(path)
    try:
        return RunManifest.from_dict(data)
    except ValueError as exc:
        raise WorkspaceVerificationError(
            f"{path} violates the manifest contract: {exc}"
        ) from exc


def load_source_run(runs_root: Path, run_id: str) -> tuple[Path, RunManifest]:
    """Open a finished run for reading by another run.

    The one door into somebody else's workspace, and the door that fails
    closed: an incomplete run raises instead of yielding its partial files.
    """

    run_dir = resolve_editorial_run_dir(runs_root, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"no run workspace at {run_dir}")
    return run_dir, load_manifest(run_dir)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise WorkspaceVerificationError(f"{path} is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceVerificationError(f"{path} is not a JSON object")
    return data


# ===========================================================================
# Verification (§4.3)
# ===========================================================================


class RunWorkspaceReport(BaseModel):
    """What one successful workspace verification proved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    run_digest: str
    verified_entities: int
    verified_stage_records: int


def verify_run_workspace(runs_root: Path, run_id: str) -> RunWorkspaceReport:
    """Verify one run workspace against its own manifest (§4.3).

    Strictly read-only, and proves five things:

    1. the run is complete — it has a manifest, which strictly reloads, binds
       to this ``run_id``, records the canonical topology and carries the
       digest of its own index;
    2. every indexed file exists and still digests to what the manifest says;
    3. nothing else is in the workspace: an unindexed file is either a write
       the run did not record or one that arrived after it;
    4. the write-ownership table holds — the stage recorded as the writer of
       each path is the stage §2.3 gives that path to (P6);
    5. every StageRecord's outputs are in the entity index, with the same
       digest, written by the stage the record itself names.
    """

    run_dir = resolve_editorial_run_dir(runs_root, run_id)
    if not run_dir.is_dir():
        raise WorkspaceVerificationError(f"run workspace does not exist: {run_dir}")

    manifest = load_manifest(run_dir)
    if manifest.run_context.run_id != run_id:
        raise WorkspaceVerificationError(
            f"the manifest at {run_dir} belongs to run "
            f"{manifest.run_context.run_id!r}, not to {run_id!r}"
        )
    verify_topology_digest(manifest)
    verify_run_digest(manifest)

    indexed: set[str] = {MANIFEST_NAME}
    for entry in manifest.entities:
        path = _verified_file(run_dir, entry.path, entry.digest)
        stated = version_in_name(entry.path.rsplit("/", 1)[-1])
        if stated != entry.version:
            raise WorkspaceVerificationError(
                f"{entry.path} states version {stated!r} in its name but is "
                f"indexed as version {entry.version!r} (P2)"
            )
        owner = owner_of(
            entry.path,
            stage_of_version=_load_json_object(path).get(_STAGE_OF_VERSION),
        )
        if owner != entry.writer_stage:
            raise WriteOwnershipError(
                f"{entry.writer_stage} is recorded as the writer of "
                f"{entry.path}, which §2.3 gives to {owner}: the stage wrote "
                "outside its path patterns"
            )
        indexed.add(entry.path)

    by_identity = {
        (entry.entity_type, entry.entity_id, entry.version): entry
        for entry in manifest.entities
    }
    previous_seq: Optional[int] = None
    for entry in manifest.trace:
        path = _verified_file(run_dir, entry.path, entry.digest)
        record = _load_stage_record(path)
        if record.run_id != run_id:
            raise WorkspaceVerificationError(
                f"{entry.path} belongs to run {record.run_id!r}, not to {run_id!r}"
            )
        if (record.seq, record.stage, record.scope_key) != (
            entry.seq,
            entry.stage,
            entry.scope_key,
        ):
            raise WorkspaceVerificationError(
                f"the trace index describes {entry.path} as "
                f"{entry.seq}/{entry.stage}/{entry.scope_key}, but the record "
                f"says {record.seq}/{record.stage}/{record.scope_key}"
            )
        expected_name = f"{TRACE_DIRECTORY}/{stage_record_file_name(record)}"
        if entry.path != expected_name:
            raise WriteOwnershipError(
                f"{entry.path} is not the name its record gives it "
                f"({expected_name}); §2.3 gives a trace file to the stage named "
                "in it, so the name is part of the ownership"
            )
        if previous_seq is not None and entry.seq <= previous_seq:
            raise WorkspaceVerificationError(
                f"stage record seq {entry.seq} does not follow {previous_seq}; "
                "seq is monotonic within the run (§4.2)"
            )
        previous_seq = entry.seq
        for output in record.outputs:
            _verify_output(record, output, by_identity)
        indexed.add(entry.path)

    for stray in _workspace_files(run_dir):
        if stray not in indexed:
            raise WorkspaceVerificationError(
                f"{stray} is in the workspace but not in the manifest index: "
                "the manifest indexes the whole run, so an unindexed file is "
                "either a write the run did not record or one that arrived "
                "after it"
            )

    return RunWorkspaceReport(
        run_id=run_id,
        run_digest=manifest.run_digest,
        verified_entities=len(manifest.entities),
        verified_stage_records=len(manifest.trace),
    )


def _verified_file(run_dir: Path, relative: str, digest: str) -> Path:
    """The indexed file, proven to be the bytes the manifest indexed."""

    path = run_dir / _validated_relative_path(relative)
    if not path.is_file():
        raise WorkspaceVerificationError(
            f"{relative} is in the manifest index but not in the workspace"
        )
    actual = file_digest(path)
    if actual != digest:
        raise WorkspaceVerificationError(
            f"{relative} digests {actual}, but the manifest records {digest}: "
            "the file changed after the run indexed it"
        )
    return path


def _load_stage_record(path: Path) -> StageRecord:
    try:
        return StageRecord.from_dict(_load_json_object(path))
    except ValueError as exc:
        raise WorkspaceVerificationError(
            f"{path} violates the StageRecord contract: {exc}"
        ) from exc


def _verify_output(
    record: StageRecord,
    output: EntityRef,
    by_identity: dict[tuple[str, str, Optional[int]], EntityIndexEntry],
) -> None:
    """One StageRecord output against the entity index (§4.3).

    This is where "did any stage write outside its paths?" is answered for a
    file that reached the workspace some other way than through the writer:
    the record names the stage, the index names the path's proven owner, and
    a claim that they are the same stage is checkable.
    """

    identity = (output.entity_type, output.entity_id, output.version)
    entry = by_identity.get(identity)
    if entry is None:
        raise WorkspaceVerificationError(
            f"stage record {record.seq} ({record.stage}) claims output "
            f"{identity}, which is in no entity index entry"
        )
    if entry.digest != output.digest:
        raise WorkspaceVerificationError(
            f"stage record {record.seq} ({record.stage}) claims output "
            f"{identity} at digest {output.digest}, but the entity index "
            f"records {entry.digest}"
        )
    # ``writer_stage`` was proven above to be the owner §2.3 gives the path,
    # so comparing the record's own stage with it is the §2.3 check: "compare
    # the StageRecord's created_by.stage with the path".
    if entry.writer_stage != record.created_by.stage:
        raise WriteOwnershipError(
            f"stage record {record.seq} ({record.created_by.stage}) claims to "
            f"have written {entry.path}, which §2.3 gives to "
            f"{entry.writer_stage}"
        )


def _workspace_files(run_dir: Path) -> Iterator[str]:
    """Every file in the workspace, as a workspace-relative POSIX path.

    Dot-files are skipped: the only ones a workspace can hold are the
    writer's own ``.tmp_`` files, which exist between two lines of an atomic
    commit and are never evidence.
    """

    for path in sorted(run_dir.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        yield path.relative_to(run_dir).as_posix()
