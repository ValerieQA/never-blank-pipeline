"""Issue #292: the boundary commit, and what a crash inside one may not do.

S-04 changes two entities at once — the interpretations (E-08) and the boundary
that lists them (E-09) — and Step 3 §2.4 makes the E-09 file the commit marker
so that a half-written change is invisible rather than misleading. These
scenarios are the four claims that rest on it:

- **The marker goes last.** One commit writes every E-08 version first and the
  boundary file after them, and the marker carries the digest of each file it
  references.
- **A crash between the two steps leaves the previous boundary current.** The
  orphan E-08 files stay on disk for forensics and no reader sees them: the
  acceptance evidence for this issue.
- **A commit holds together or does not happen.** Both sides of the pair, one
  exact version of each interpretation, never in both lists, and — at a
  re-entry — a newly discovered interpretation recorded as inadmissible. Every
  refusal happens before the first write.
- **The current boundary is the highest version whose digests verify.** An E-08
  file changed after the commit unverifies its own boundary version, and the
  reader falls back rather than planning against it.

The ARP records, counters and budget wrap are in ``tests/test_292_arp.py``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from src.run.boundary_commit import (
    Admissibility,
    BoundaryCommit,
    BoundaryCommitError,
    BoundaryMember,
    InterpretationVersion,
    boundary_relative_path,
    boundary_versions,
    commit_boundary,
    current_boundary,
    interpretation_relative_path,
    orphan_interpretation_versions,
    write_interpretation_version,
)
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import RunInputs
from src.run.run_workspace import (
    DeciderKind,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
    file_digest,
    owner_of,
    verify_run_workspace,
)
from src.strategy.execution_context import ConfigurationIdentity

TS_UTC = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

#: A run identifies itself with the UUID v4 ``create_run_id`` mints and nothing
#: else (``src/run/run_context.py``), so the workspace, its manifest and the
#: StageRecord here agree on the ID the way a real run makes them agree.
RUN_ID = create_run_id()


def _workspace(tmp_path: Path) -> RunWorkspace:
    return RunWorkspace.create(tmp_path / "editorial_runs", RUN_ID)


def _run_context() -> RunContext:
    return RunContext(
        run_id=RUN_ID,
        assignment_id="sig-292",
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
        configuration_identity=ConfigurationIdentity(
            schema_version="1.0",
            configuration_id="never-blank",
            configuration_version="1.0.0",
            configuration_hash="sha256:" + "c" * 64,
        ),
    )


def _stage_record(seq: int) -> StageRecord:
    """One S-04 execution, so the run can be sealed and verified."""

    started = TS_UTC + timedelta(minutes=seq)
    return StageRecord(
        run_id=RUN_ID,
        seq=seq,
        stage="S-04",
        scope_key="sig-292",
        started_at=started,
        ended_at=started + timedelta(seconds=5),
        created_by=StageAttribution(
            stage="S-04", component="boundary-commit", decider=DeciderKind.CODE
        ),
        status=StageStatus.COMPLETED,
    )


def _interpretation(
    interpretation_id: str,
    version: int,
    admissibility: Admissibility,
    *,
    supersedes: Optional[str] = None,
) -> InterpretationVersion:
    return InterpretationVersion(
        interpretation_id=interpretation_id,
        version=version,
        admissibility=admissibility,
        payload={
            "interpretation_id": interpretation_id,
            "version": version,
            "supersedes": supersedes,
            "statement": f"{interpretation_id} at version {version}",
        },
    )


def _member(
    interpretation_id: str, version: int, admissibility: Admissibility
) -> BoundaryMember:
    return BoundaryMember(
        interpretation_id=interpretation_id,
        version=version,
        admissibility=admissibility,
    )


def _first_commit(workspace: RunWorkspace) -> BoundaryCommit:
    """The boundary S-04 commits on its first pass: one of each list."""

    return commit_boundary(
        workspace,
        boundary_id="bnd-292",
        version=1,
        interpretations=(
            _interpretation("int-1", 1, Admissibility.ADMISSIBLE),
            _interpretation("int-2", 1, Admissibility.INADMISSIBLE),
        ),
        members=(
            _member("int-1", 1, Admissibility.ADMISSIBLE),
            _member("int-2", 1, Admissibility.INADMISSIBLE),
        ),
        payload={
            "relevance_ref": "decision.json#digest",
            "probe_families": ["transfer"],
        },
    )


def _marker(workspace: RunWorkspace, version: int) -> dict[str, Any]:
    path = workspace.run_dir / boundary_relative_path(version)
    return json.loads(path.read_text(encoding="utf-8"))


def _pairs(members: Sequence[Any]) -> list[tuple[str, int]]:
    """The exact (``interpretation_id``, ``version``) pairs, in order."""

    return [(member.interpretation_id, member.version) for member in members]


def test_the_boundary_paths_belong_to_stage_s_04():
    """§2.3 gives ``signal/boundary/**`` to S-04 and to nobody else."""

    assert owner_of(boundary_relative_path(2)) == "S-04"
    assert owner_of(interpretation_relative_path("int-1", 3)) == "S-04"


def test_the_marker_is_written_last_and_carries_the_digests(tmp_path: Path):
    workspace = _workspace(tmp_path)
    commit = _first_commit(workspace)
    workspace.write_stage_record(_stage_record(1))
    manifest = workspace.write_manifest(
        _run_context(),
        inputs=RunInputs.stated_absent("boundary fixture: no editorial input"),
    )

    # The entity index is assembled from the writes as they happened, so its
    # order is the order the commit wrote in: every E-08 version, then E-09.
    written = [entry.entity_type for entry in manifest.entities]
    assert written == ["E-08", "E-08", "E-09"]
    assert manifest.entities[-1].path == commit.path
    report = verify_run_workspace(tmp_path / "editorial_runs", RUN_ID)
    assert report.verified_entities == 3

    marker = _marker(workspace, 1)
    assert marker["version"] == 1
    assert marker["supersedes"] is None
    assert marker["relevance_ref"] == "decision.json#digest"
    admissible = [entry["interpretation_id"] for entry in marker["members"]["admissible"]]
    assert admissible == ["int-1"]
    for entry in marker["members"]["admissible"] + marker["members"]["inadmissible"]:
        path = workspace.run_dir / interpretation_relative_path(
            entry["interpretation_id"], entry["version"]
        )
        assert entry["digest"] == file_digest(path)

    boundary = current_boundary(workspace.run_dir)
    assert boundary is not None
    assert boundary.version == 1
    assert boundary.boundary_id == "bnd-292"
    assert [member.interpretation_id for member in boundary.admissible] == ["int-1"]
    assert [member.interpretation_id for member in boundary.inadmissible] == ["int-2"]
    assert orphan_interpretation_versions(workspace.run_dir) == ()


def test_a_crash_between_the_writes_leaves_the_previous_boundary_current(
    tmp_path: Path,
):
    """The acceptance case: the marker never arrived, so nothing changed.

    A re-entry reclassifies ``int-1`` and discovers ``int-3``. The process dies
    after both E-08 files and before ``boundary.v2.json``. The boundary in force
    is still version 1 — with ``int-1`` still admissible at version 1 — and the
    two files left behind are invisible to every reader.
    """

    workspace = _workspace(tmp_path)
    _first_commit(workspace)

    write_interpretation_version(
        workspace,
        _interpretation(
            "int-1", 2, Admissibility.INADMISSIBLE, supersedes="int-1.v1"
        ),
    )
    write_interpretation_version(
        workspace, _interpretation("int-3", 1, Admissibility.INADMISSIBLE)
    )
    # ... and the run dies here, before the marker.

    boundary = current_boundary(workspace.run_dir)
    assert boundary is not None
    assert boundary.version == 1
    assert _pairs(boundary.admissible) == [("int-1", 1)]
    assert len(boundary_versions(workspace.run_dir)) == 1

    orphans = orphan_interpretation_versions(workspace.run_dir)
    assert _pairs(orphans) == [("int-1", 2), ("int-3", 1)]
    for orphan in orphans:
        assert (workspace.run_dir / orphan.path).is_file(), "kept for forensics"


def test_a_re_entry_commits_both_sides_and_copies_nothing(tmp_path: Path):
    workspace = _workspace(tmp_path)
    _first_commit(workspace)

    commit = commit_boundary(
        workspace,
        boundary_id="bnd-292",
        version=2,
        interpretations=(
            _interpretation(
                "int-1", 2, Admissibility.INADMISSIBLE, supersedes="int-1.v1"
            ),
            _interpretation("int-3", 1, Admissibility.INADMISSIBLE),
        ),
        members=(
            _member("int-1", 2, Admissibility.INADMISSIBLE),
            _member("int-2", 1, Admissibility.INADMISSIBLE),
            _member("int-3", 1, Admissibility.INADMISSIBLE),
        ),
    )
    assert commit.written == ("int-1", "int-3")

    boundary = current_boundary(workspace.run_dir)
    assert boundary is not None
    assert boundary.version == 2
    assert boundary.admissible == ()
    assert _pairs(boundary.members) == [("int-1", 2), ("int-2", 1), ("int-3", 1)]
    # The unchanged interpretation is referenced where it is (§2.4 rule 4).
    copied = workspace.run_dir / interpretation_relative_path("int-2", 2)
    assert not copied.exists()
    assert _marker(workspace, 2)["supersedes"] == 1
    assert orphan_interpretation_versions(workspace.run_dir) == ()


def test_a_changed_interpretation_unverifies_its_own_boundary(tmp_path: Path):
    """§2.4 rule 4: the current boundary is the highest one that verifies."""

    workspace = _workspace(tmp_path)
    _first_commit(workspace)
    commit_boundary(
        workspace,
        boundary_id="bnd-292",
        version=2,
        interpretations=(
            _interpretation(
                "int-1", 2, Admissibility.INADMISSIBLE, supersedes="int-1.v1"
            ),
        ),
        members=(
            _member("int-1", 2, Admissibility.INADMISSIBLE),
            _member("int-2", 1, Admissibility.INADMISSIBLE),
        ),
    )
    tampered = workspace.run_dir / interpretation_relative_path("int-1", 2)
    tampered.write_text(json.dumps({"statement": "something else"}), encoding="utf-8")

    versions = boundary_versions(workspace.run_dir)
    assert [(version.version, version.verified) for version in versions] == [
        (1, True),
        (2, False),
    ]
    assert "digests" in (versions[1].defect or "")

    boundary = current_boundary(workspace.run_dir)
    assert boundary is not None and boundary.version == 1


def test_an_unreadable_marker_is_not_the_boundary(tmp_path: Path):
    workspace = _workspace(tmp_path)
    _first_commit(workspace)
    (workspace.run_dir / boundary_relative_path(1)).write_text(
        "{not json", encoding="utf-8"
    )

    assert current_boundary(workspace.run_dir) is None
    assert boundary_versions(workspace.run_dir)[0].verified is False


def test_a_new_interpretation_at_a_re_entry_is_recorded_as_inadmissible(
    tmp_path: Path,
):
    workspace = _workspace(tmp_path)
    _first_commit(workspace)

    with pytest.raises(BoundaryCommitError, match="discovered by a re-entry"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=2,
            interpretations=(_interpretation("int-9", 1, Admissibility.ADMISSIBLE),),
            members=(
                _member("int-1", 1, Admissibility.ADMISSIBLE),
                _member("int-2", 1, Admissibility.INADMISSIBLE),
                _member("int-9", 1, Admissibility.ADMISSIBLE),
            ),
        )
    assert not (
        workspace.run_dir / interpretation_relative_path("int-9", 1)
    ).exists(), "a refused commit writes nothing at all"


def test_an_interpretation_the_marker_would_not_reference_is_refused(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(BoundaryCommitError, match="without the marker referencing it"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(
                _interpretation("int-1", 1, Admissibility.ADMISSIBLE),
                _interpretation("int-2", 1, Admissibility.INADMISSIBLE),
            ),
            members=(_member("int-1", 1, Admissibility.ADMISSIBLE),),
        )
    assert boundary_versions(workspace.run_dir) == ()
    assert orphan_interpretation_versions(workspace.run_dir) == ()


def test_a_member_that_exists_nowhere_is_refused(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(BoundaryCommitError, match="neither written by this commit"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(_interpretation("int-1", 1, Admissibility.ADMISSIBLE),),
            members=(
                _member("int-1", 1, Admissibility.ADMISSIBLE),
                _member("int-4", 1, Admissibility.INADMISSIBLE),
            ),
        )


def test_an_interpretation_may_not_sit_in_both_lists(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(BoundaryCommitError, match="appears twice in the member list"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(_interpretation("int-1", 1, Admissibility.ADMISSIBLE),),
            members=(
                _member("int-1", 1, Admissibility.ADMISSIBLE),
                _member("int-1", 1, Admissibility.INADMISSIBLE),
            ),
        )


def test_the_record_and_the_boundary_cannot_disagree_about_the_list(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(BoundaryCommitError, match="cannot disagree"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(_interpretation("int-1", 1, Admissibility.ADMISSIBLE),),
            members=(_member("int-1", 1, Admissibility.INADMISSIBLE),),
        )


def test_neither_side_of_the_pair_exists_without_the_other(tmp_path: Path):
    """§2.4 rule 5: a boundary version with no E-08 change is not a commit."""

    workspace = _workspace(tmp_path)
    with pytest.raises(BoundaryCommitError, match="writes at least one E-08 version"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(),
            members=(_member("int-1", 1, Admissibility.ADMISSIBLE),),
        )


def test_a_boundary_version_follows_the_one_on_disk(tmp_path: Path):
    workspace = _workspace(tmp_path)
    _first_commit(workspace)

    with pytest.raises(BoundaryCommitError, match="the next commit is version 2"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=3,
            interpretations=(_interpretation("int-5", 1, Admissibility.INADMISSIBLE),),
            members=(_member("int-5", 1, Admissibility.INADMISSIBLE),),
        )


def test_a_later_version_says_what_it_supersedes(tmp_path: Path):
    workspace = _workspace(tmp_path)
    _first_commit(workspace)

    with pytest.raises(BoundaryCommitError, match="does not say what it supersedes"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=2,
            interpretations=(_interpretation("int-1", 2, Admissibility.INADMISSIBLE),),
            members=(
                _member("int-1", 2, Admissibility.INADMISSIBLE),
                _member("int-2", 1, Admissibility.INADMISSIBLE),
            ),
        )


def test_a_first_version_supersedes_nothing(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(BoundaryCommitError, match="replaces nothing"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(
                _interpretation(
                    "int-1", 1, Admissibility.ADMISSIBLE, supersedes="int-0.v1"
                ),
            ),
            members=(_member("int-1", 1, Admissibility.ADMISSIBLE),),
        )


def test_the_body_may_not_state_what_the_commit_states(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(BoundaryCommitError, match="may not carry"):
        commit_boundary(
            workspace,
            boundary_id="bnd-292",
            version=1,
            interpretations=(_interpretation("int-1", 1, Admissibility.ADMISSIBLE),),
            members=(_member("int-1", 1, Admissibility.ADMISSIBLE),),
            payload={"members": {"admissible": [], "inadmissible": []}},
        )
