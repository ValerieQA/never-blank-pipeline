"""The boundary commit on disk: E-08 first, E-09 last (Issue #292, slice SL-1).

S-04 does not write one entity. It writes a **coordinated** change to two: the
interpretations (E-08) and the boundary that lists them (E-09). Step 2 §1 S-04
fixes the rule and Step 3 §2.4 says how storage implements it:

1. every **new** E-08 version is written first — a new record as
   ``<int_id>.v1.json``, a reclassification as ``<int_id>.v<n+1>.json`` with
   ``supersedes``;
2. ``boundary.v<m+1>.json`` is written **last**. It lists every member as an
   exact (``interpretation_id``, ``version``) pair and carries the digest of
   each E-08 file it references;
3. **the E-09 file is the commit marker.** An E-08 version that no E-09 version
   references is invisible to every reader. A process that dies between the two
   steps leaves orphan E-08 files, which are ignored;
4. "the current boundary" is the highest ``boundary.v<m>.json`` whose referenced
   digests all verify;
5. readers that decided against a boundary store its version, and invalidation
   after a commit is a code comparison of those pairs (Step 2 §5.4, F-4).

Why a marker at all: the E-09 version is the unit of consistency. A reader that
took "the newest E-08 files" as the boundary would, for the one instant a crash
can make permanent, see an interpretation reclassified as inadmissible while
the boundary still lists the reading that depended on it — and would plan
against a boundary that never existed. With the marker written last, that state
is unreachable: it is not a smaller window, it is no window.

Nothing here decides anything editorial. What an interpretation says, whether
it is admissible and which probe families found it are S-04's, in a later
slice; this module enforces the shape of the commit and the invisibility of an
orphan. It writes through :class:`~src.run.run_workspace.RunWorkspace`, so
create-once, the version in the key and §2.3 write ownership hold here too —
``signal/boundary/**`` belongs to S-04 and to nothing else.

Sources: ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.4;
``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-04, boundary
commit) and §5.4.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# The repository's one path-component validator, reused rather than copied: an
# interpretation ID reaches a file name, and two answers to "is this a safe
# component" would eventually be two different answers.
from src.artifacts import _validate_path_component
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace, file_digest, versioned_name

#: Where the boundary lives inside the run workspace (§2.2). Both paths belong
#: to S-04 in the §2.3 ownership table, under ``signal/boundary/**``.
BOUNDARY_DIRECTORY = "signal/boundary"
INTERPRETATIONS_DIRECTORY = f"{BOUNDARY_DIRECTORY}/interpretations"

#: The stage that owns every write in this module.
BOUNDARY_STAGE = "S-04"

#: Entity types as the manifest's entity index records them.
INTERPRETATION_ENTITY_TYPE = "E-08"
BOUNDARY_ENTITY_TYPE = "E-09"

_BOUNDARY_STEM = "boundary"
_BOUNDARY_FILE = re.compile(r"^boundary\.v(\d+)\.json$")
_INTERPRETATION_FILE = re.compile(r"^(?P<id>.+)\.v(?P<version>\d+)\.json$")

#: The fields the marker states about the commit itself. A caller's E-09 body
#: may not carry them: the membership is only knowable after the E-08 files are
#: written, because it carries their digests.
_MARKER_FIELDS = ("boundary_id", "version", "supersedes", "members")

_ADMISSIBLE_KEY = "admissible"
_INADMISSIBLE_KEY = "inadmissible"


class BoundaryCommitError(RuntimeError):
    """The commit does not hold together, and was refused before any write."""


class BoundaryReadError(RuntimeError):
    """A boundary file on disk cannot be read as one."""


class Admissibility(str, Enum):
    """Which of the boundary's two lists an interpretation sits in.

    Never both: an interpretation that is admissible and inadmissible at once
    is not a boundary, it is a contradiction (S-04 post-condition).
    """

    ADMISSIBLE = "admissible"
    INADMISSIBLE = "inadmissible"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InterpretationVersion(_Frozen):
    """One E-08 version this commit writes.

    ``payload`` is the E-08 body, whose schema is Step 1's and belongs to the
    slice that produces interpretations. What is checked here is what the
    commit depends on: that version 1 supersedes nothing and a later version
    says what it supersedes (Step 1 §0.1).
    """

    interpretation_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    admissibility: Admissibility
    payload: dict[str, Any]


class BoundaryMember(_Frozen):
    """One member of the boundary being committed, as an exact pair.

    A member whose version this commit does not write is an unchanged
    interpretation: it is **not** copied, and the marker references the file
    that is already there (§2.4 rule 4).
    """

    interpretation_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    admissibility: Admissibility


class CommittedMember(_Frozen):
    """One member as the marker records it: the pair, and the file's digest."""

    interpretation_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    admissibility: Admissibility
    digest: str = Field(min_length=1)


class BoundaryCommit(_Frozen):
    """What one S-04 execution committed."""

    boundary_id: str
    version: int
    #: Run-relative path of the marker.
    path: str
    members: tuple[CommittedMember, ...]
    #: The E-08 versions this commit wrote, in the order they were written.
    written: tuple[str, ...]


class BoundaryVersion(_Frozen):
    """One ``boundary.v<m>.json`` as a reader finds it.

    ``verified`` is §2.4 rule 4: every referenced E-08 file exists and still
    digests to what the marker recorded. An unverified version is not read as
    the boundary — the reader falls back to the last one that verifies, which
    is the same fallback a crash between the two write steps needs.
    """

    version: int = Field(ge=1)
    path: str
    boundary_id: Optional[str] = None
    members: tuple[CommittedMember, ...] = ()
    verified: bool
    #: Why it does not verify, when it does not.
    defect: Optional[str] = None

    @property
    def admissible(self) -> tuple[CommittedMember, ...]:
        return tuple(
            member
            for member in self.members
            if member.admissibility is Admissibility.ADMISSIBLE
        )

    @property
    def inadmissible(self) -> tuple[CommittedMember, ...]:
        return tuple(
            member
            for member in self.members
            if member.admissibility is Admissibility.INADMISSIBLE
        )


class InterpretationFile(_Frozen):
    """One E-08 file on disk, by the pair its name states."""

    interpretation_id: str
    version: int
    path: str


# ===========================================================================
# Paths
# ===========================================================================


def interpretation_relative_path(interpretation_id: str, version: int) -> str:
    """``signal/boundary/interpretations/<int_id>.v<n>.json`` (§2.2)."""

    _validate_path_component(interpretation_id, "interpretation_id")
    name = versioned_name(interpretation_id, version)
    return f"{INTERPRETATIONS_DIRECTORY}/{name}"


def boundary_relative_path(version: int) -> str:
    """``signal/boundary/boundary.v<m>.json`` (§2.2): the commit marker."""

    return f"{BOUNDARY_DIRECTORY}/{versioned_name(_BOUNDARY_STEM, version)}"


# ===========================================================================
# Writing
# ===========================================================================


def write_interpretation_version(
    workspace: RunWorkspace, interpretation: InterpretationVersion
) -> EntityIndexEntry:
    """Write one E-08 version and return the manifest entry it produced.

    Public because step 1 of the commit is a real step: a caller that writes
    interpretations and then stops is exactly the crash §2.4 rule 3 describes,
    and the files it leaves are orphans that no reader sees. Ordinary S-04 code
    calls :func:`commit_boundary`, which performs both steps in order.
    """

    _checked_payload(interpretation)
    relative = interpretation_relative_path(
        interpretation.interpretation_id, interpretation.version
    )
    return workspace.write_entity(
        stage=BOUNDARY_STAGE,
        relative_path=relative,
        entity_type=INTERPRETATION_ENTITY_TYPE,
        entity_id=interpretation.interpretation_id,
        payload=interpretation.payload,
        version=interpretation.version,
    )


def commit_boundary(
    workspace: RunWorkspace,
    *,
    boundary_id: str,
    version: int,
    interpretations: Sequence[InterpretationVersion],
    members: Sequence[BoundaryMember],
    payload: Optional[dict[str, Any]] = None,
) -> BoundaryCommit:
    """Write one boundary commit: the E-08 versions, then the marker.

    Every check happens before the first write, so a commit that cannot hold
    together leaves nothing behind at all. Refused, in order: a version that
    does not follow the boundary already on disk; a commit with no E-08 change
    (§2.4 rule 5 — neither side of the pair exists without the other); a member
    list that names an interpretation twice; a written version no member
    references, which would be an orphan created on purpose; a member whose
    file is neither written here nor already on disk; a written version whose
    admissibility disagrees with its member entry; and, at a re-entry, a newly
    discovered interpretation recorded as anything but inadmissible (§2.4 /
    Step 2 S-04 rule 2).
    """

    if not boundary_id.strip():
        raise BoundaryCommitError("a boundary commit needs a boundary ID")
    if version < 1:
        raise BoundaryCommitError(f"a boundary version starts at 1; got {version}")

    existing = boundary_versions(workspace.run_dir)
    expected = existing[-1].version + 1 if existing else 1
    if version != expected:
        raise BoundaryCommitError(
            f"this run's boundary is at version {expected - 1}, so the next "
            f"commit is version {expected}; got {version}. A gap in the "
            "versions would leave a reader unable to say which snapshot is "
            "current (§2.4 rule 4)"
        )

    written = _checked_interpretations(interpretations)
    resolved = _checked_members(
        workspace.run_dir,
        members,
        written=written,
        version=version,
        known_ids=_known_interpretation_ids(existing),
    )
    body = _checked_body(payload)

    order: list[str] = []
    digests: dict[tuple[str, int], str] = {}
    for interpretation in interpretations:
        entry = write_interpretation_version(workspace, interpretation)
        key = (interpretation.interpretation_id, interpretation.version)
        digests[key] = entry.digest
        order.append(interpretation.interpretation_id)

    committed = tuple(
        CommittedMember(
            interpretation_id=member.interpretation_id,
            version=member.version,
            admissibility=member.admissibility,
            # A member this commit wrote is digested from the file it just
            # committed; an unchanged one from the file that was already there.
            digest=digest
            if digest is not None
            else digests[(member.interpretation_id, member.version)],
        )
        for member, digest in resolved
    )
    relative = boundary_relative_path(version)
    workspace.write_entity(
        stage=BOUNDARY_STAGE,
        relative_path=relative,
        entity_type=BOUNDARY_ENTITY_TYPE,
        entity_id=boundary_id,
        payload={
            **body,
            "boundary_id": boundary_id,
            "version": version,
            # Readers reference a boundary by its version (§2.4 rule 5), so
            # that is what a later version supersedes.
            "supersedes": version - 1 if version > 1 else None,
            "members": {
                _ADMISSIBLE_KEY: [
                    _member_entry(member)
                    for member in committed
                    if member.admissibility is Admissibility.ADMISSIBLE
                ],
                _INADMISSIBLE_KEY: [
                    _member_entry(member)
                    for member in committed
                    if member.admissibility is Admissibility.INADMISSIBLE
                ],
            },
        },
        version=version,
    )
    return BoundaryCommit(
        boundary_id=boundary_id,
        version=version,
        path=relative,
        members=committed,
        written=tuple(order),
    )


def _member_entry(member: CommittedMember) -> dict[str, Any]:
    return {
        "interpretation_id": member.interpretation_id,
        "version": member.version,
        "digest": member.digest,
    }


def _checked_payload(interpretation: InterpretationVersion) -> None:
    """Step 1 §0.1 on one E-08 version: a later version says what it replaces."""

    supersedes = interpretation.payload.get("supersedes")
    stated = isinstance(supersedes, str) and bool(supersedes.strip())
    if interpretation.version > 1 and not stated:
        raise BoundaryCommitError(
            f"{interpretation.interpretation_id} version "
            f"{interpretation.version} does not say what it supersedes; a "
            "reclassification is a new version of the same record, and the "
            "chain is how a reader follows it (Step 1 §0.1)"
        )
    if interpretation.version == 1 and supersedes is not None:
        raise BoundaryCommitError(
            f"{interpretation.interpretation_id} version 1 claims to supersede "
            f"{supersedes!r}; a first version replaces nothing"
        )


def _checked_interpretations(
    interpretations: Sequence[InterpretationVersion],
) -> dict[tuple[str, int], InterpretationVersion]:
    if not interpretations:
        raise BoundaryCommitError(
            "a boundary commit writes at least one E-08 version: no E-08 "
            "change exists without a new E-09 version, and none the other way "
            "round (§2.4 rule 5)"
        )
    written: dict[tuple[str, int], InterpretationVersion] = {}
    for interpretation in interpretations:
        _checked_payload(interpretation)
        if any(key[0] == interpretation.interpretation_id for key in written):
            raise BoundaryCommitError(
                f"{interpretation.interpretation_id} is written more than once "
                "in one commit; the boundary lists one exact version of each "
                "interpretation, so only one of them could be a member"
            )
        written[(interpretation.interpretation_id, interpretation.version)] = (
            interpretation
        )
    return written


def _checked_members(
    run_dir: Path,
    members: Sequence[BoundaryMember],
    *,
    written: dict[tuple[str, int], InterpretationVersion],
    version: int,
    known_ids: frozenset[str],
) -> tuple[tuple[BoundaryMember, Optional[str]], ...]:
    """Every member with the digest of the file it references.

    ``None`` where this commit writes the file: its digest exists only after it
    is written, which is the whole reason the marker goes last.
    """

    if not members:
        raise BoundaryCommitError(
            "a boundary version is a complete snapshot, so it has at least one "
            "member (§2.4 rule 1)"
        )
    resolved: list[tuple[BoundaryMember, Optional[str]]] = []
    seen: set[str] = set()
    for member in members:
        if member.interpretation_id in seen:
            raise BoundaryCommitError(
                f"{member.interpretation_id} appears twice in the member list; "
                "a snapshot lists one exact version of each interpretation, in "
                "one of the two lists and never in both"
            )
        seen.add(member.interpretation_id)
        key = (member.interpretation_id, member.version)
        new_version = written.get(key)
        if new_version is not None:
            if new_version.admissibility is not member.admissibility:
                raise BoundaryCommitError(
                    f"{member.interpretation_id} version {member.version} is "
                    f"written as {new_version.admissibility.value} and listed "
                    f"as {member.admissibility.value}; the record and the "
                    "boundary cannot disagree about which list it is in"
                )
            if (
                version > 1
                and member.version == 1
                and member.interpretation_id not in known_ids
                and member.admissibility is not Admissibility.INADMISSIBLE
            ):
                raise BoundaryCommitError(
                    f"{member.interpretation_id} is new at boundary version "
                    f"{version} and is listed as admissible; an interpretation "
                    "discovered by a re-entry is recorded as inadmissible with "
                    "its reason (§2.4 rule 2)"
                )
            resolved.append((member, None))
            continue
        path = run_dir / interpretation_relative_path(
            member.interpretation_id, member.version
        )
        if not path.is_file():
            raise BoundaryCommitError(
                f"{member.interpretation_id} version {member.version} is a "
                "member but is neither written by this commit nor already in "
                "the workspace; an unchanged interpretation is referenced "
                "where it is, and a changed one is written first (§2.4 rules 1 "
                "and 4)"
            )
        resolved.append((member, file_digest(path)))

    orphaned = sorted(
        f"{key[0]} version {key[1]}"
        for key in written
        if not any(
            (member.interpretation_id, member.version) == key for member, _ in resolved
        )
    )
    if orphaned:
        raise BoundaryCommitError(
            "this commit would write "
            + ", ".join(orphaned)
            + " without the marker referencing it; an E-08 version no E-09 "
            "version references is invisible to every reader (§2.4 rule 3), so "
            "writing one deliberately is refused"
        )
    return tuple(resolved)


def _checked_body(payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    body = dict(payload or {})
    stated = sorted(field for field in _MARKER_FIELDS if field in body)
    if stated:
        raise BoundaryCommitError(
            "the E-09 body may not carry "
            + ", ".join(stated)
            + ": the commit states them, because the membership carries the "
            "digests of files that do not exist until it writes them"
        )
    return body


# ===========================================================================
# Reading
# ===========================================================================


def boundary_versions(run_dir: Path) -> tuple[BoundaryVersion, ...]:
    """Every ``boundary.v<m>.json`` of one run, oldest first.

    Each one is parsed and checked against the E-08 files it references, so a
    reader can see not only which version is current but why a later one is
    not. A file that cannot be parsed is reported as unverified rather than
    raising: the reason a marker is unreadable is forensic evidence, and the
    boundary in force is still the last one that verifies.
    """

    directory = Path(run_dir) / BOUNDARY_DIRECTORY
    if not directory.is_dir():
        return ()
    found: list[BoundaryVersion] = []
    for path in sorted(directory.iterdir()):
        match = _BOUNDARY_FILE.match(path.name)
        if match is None or not path.is_file():
            continue
        found.append(_read_boundary_version(Path(run_dir), path, int(match.group(1))))
    return tuple(sorted(found, key=lambda boundary: boundary.version))


def current_boundary(run_dir: Path) -> Optional[BoundaryVersion]:
    """The boundary in force: the highest version that verifies (§2.4 rule 4).

    ``None`` when the run has committed none — including the case where the
    only marker on disk does not verify, which is not a boundary a reader may
    plan against.
    """

    for boundary in reversed(boundary_versions(run_dir)):
        if boundary.verified:
            return boundary
    return None


def orphan_interpretation_versions(run_dir: Path) -> tuple[InterpretationFile, ...]:
    """E-08 files that no E-09 version references (§2.4 rule 3).

    These are invisible: not a weaker input, not a candidate, not read at all.
    They exist because a process died between the two write steps, and they are
    listed here for the same reason the incomplete run's files are kept — so
    that what happened can be seen afterwards.
    """

    referenced = {
        (member.interpretation_id, member.version)
        for boundary in boundary_versions(run_dir)
        for member in boundary.members
    }
    return tuple(
        found
        for found in _interpretation_files(Path(run_dir))
        if (found.interpretation_id, found.version) not in referenced
    )


def _interpretation_files(run_dir: Path) -> tuple[InterpretationFile, ...]:
    directory = run_dir / INTERPRETATIONS_DIRECTORY
    if not directory.is_dir():
        return ()
    found: list[InterpretationFile] = []
    for path in sorted(directory.iterdir()):
        match = _INTERPRETATION_FILE.match(path.name)
        if match is None or not path.is_file():
            continue
        found.append(
            InterpretationFile(
                interpretation_id=match.group("id"),
                version=int(match.group("version")),
                path=path.relative_to(run_dir).as_posix(),
            )
        )
    return tuple(found)


def _read_boundary_version(run_dir: Path, path: Path, version: int) -> BoundaryVersion:
    relative = path.relative_to(run_dir).as_posix()
    try:
        members, boundary_id = _parse_marker(path, version)
    except BoundaryReadError as exc:
        return BoundaryVersion(
            version=version, path=relative, verified=False, defect=str(exc)
        )

    defect = _unverified_member(run_dir, members)
    return BoundaryVersion(
        version=version,
        path=relative,
        boundary_id=boundary_id,
        members=members,
        verified=defect is None,
        defect=defect,
    )


def _unverified_member(
    run_dir: Path, members: tuple[CommittedMember, ...]
) -> Optional[str]:
    """The first member whose file is missing or changed, as a defect."""

    for member in members:
        member_path = run_dir / interpretation_relative_path(
            member.interpretation_id, member.version
        )
        if not member_path.is_file():
            return (
                f"{member.interpretation_id} version {member.version} is a "
                "member and is not in the workspace"
            )
        actual = file_digest(member_path)
        if actual != member.digest:
            return (
                f"{member.interpretation_id} version {member.version} digests "
                f"{actual}, but the marker records {member.digest}"
            )
    return None


def _parse_marker(
    path: Path, version: int
) -> tuple[tuple[CommittedMember, ...], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BoundaryReadError(f"{path.name} is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise BoundaryReadError(f"{path.name} is not a JSON object")
    if data.get("version") != version:
        raise BoundaryReadError(
            f"{path.name} states version {data.get('version')!r}; the version "
            "is in the key, and a marker that disagrees with its own name "
            "cannot say which snapshot it is"
        )
    raw = data.get("members")
    if not isinstance(raw, dict):
        raise BoundaryReadError(f"{path.name} carries no member lists")

    members: list[CommittedMember] = []
    seen: set[str] = set()
    for key, admissibility in (
        (_ADMISSIBLE_KEY, Admissibility.ADMISSIBLE),
        (_INADMISSIBLE_KEY, Admissibility.INADMISSIBLE),
    ):
        entries = raw.get(key, [])
        if not isinstance(entries, list):
            raise BoundaryReadError(f"{path.name} member list {key!r} is not a list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise BoundaryReadError(
                    f"{path.name} member list {key!r} holds something that is "
                    "not a member"
                )
            try:
                member = CommittedMember(
                    interpretation_id=entry.get("interpretation_id", ""),
                    version=entry.get("version", 0),
                    admissibility=admissibility,
                    digest=entry.get("digest", ""),
                )
                # A member ID reaches a file name, so a marker that carries an
                # unsafe one is unreadable rather than followed.
                _validate_path_component(
                    entry.get("interpretation_id", ""), "interpretation_id"
                )
            except ValueError as exc:
                raise BoundaryReadError(
                    f"{path.name} member list {key!r} holds an invalid member: "
                    f"{exc}"
                ) from exc
            if member.interpretation_id in seen:
                raise BoundaryReadError(
                    f"{path.name} lists {member.interpretation_id} twice; a "
                    "snapshot holds one version of each interpretation, never "
                    "in both lists"
                )
            seen.add(member.interpretation_id)
            members.append(member)
    if not members:
        raise BoundaryReadError(f"{path.name} lists no members")

    boundary_id = data.get("boundary_id")
    return tuple(members), boundary_id if isinstance(boundary_id, str) else None


def _known_interpretation_ids(existing: Sequence[BoundaryVersion]) -> frozenset[str]:
    """Every interpretation any boundary version of this run has recorded."""

    return frozenset(
        member.interpretation_id for boundary in existing for member in boundary.members
    )
