"""Issue #291: immutable, verifiable run storage.

Step 3 gives the canonical engine a run workspace with four properties. Each
one is a claim that has to be able to fail, so each one has scenarios here:

- **P1 create-once.** A path already written is refused, and the first write
  is what stays on disk.
- **P2 the version is in the key.** A version the file name does not state is
  refused, both at write time and at verification.
- **P6 write ownership.** A stage may write only the paths §2.3 gives it; a
  file that reached the workspace some other way, or a stage record claiming
  a file another stage wrote, is detected by verification.
- **Manifest last.** A run killed before its manifest is ``incomplete``: its
  files remain for forensics, and no other run reads them as a source.

The fixture run at the bottom of the helpers is the acceptance evidence: one
complete run, written the way a run writes it, whose manifest verifies.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

import pytest

from src.artifacts import ArtifactCollisionError, atomic_write_json
from src.artifacts.provenance import ProvenanceError, verify_run_provenance
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import (
    EntityIndexEntry,
    RunDigestMismatchError,
    RunManifest,
)
from src.run.run_workspace import (
    EDITORIAL_RUNS_ROOT,
    MANIFEST_NAME,
    PLAN_APPROVED,
    PLAN_DRAFT,
    DeciderKind,
    EntityRef,
    IncompleteRunError,
    RunWorkspace,
    RunWorkspaceError,
    StageAttribution,
    StageRecord,
    StageStatus,
    WorkspaceVerificationError,
    WriteOwnershipError,
    file_digest,
    is_complete,
    load_source_run,
    owner_of,
    verify_run_workspace,
    version_in_name,
    versioned_name,
)
from src.strategy.execution_context import ConfigurationIdentity

TS_UTC = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)

_UNIT = "units/unit-291"
_DEST = f"{_UNIT}/destinations/linkedin"


def _run_context(run_id: str) -> RunContext:
    return RunContext(
        run_id=run_id,
        assignment_id="sig-291",
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
        configuration_identity=ConfigurationIdentity(
            schema_version="1.0",
            configuration_id="never-blank",
            configuration_version="1.0.0",
            configuration_hash="sha256:" + "a" * 64,
        ),
    )


def _stage_record(
    run_id: str,
    seq: int,
    stage: str,
    scope_key: str,
    outputs: tuple[EntityRef, ...] = (),
) -> StageRecord:
    """One stage execution, with the entities it produced as its outputs."""

    started = TS_UTC + timedelta(minutes=seq)
    return StageRecord(
        run_id=run_id,
        seq=seq,
        stage=stage,
        scope_key=scope_key,
        started_at=started,
        ended_at=started + timedelta(seconds=30),
        created_by=StageAttribution(
            stage=stage, component=f"{stage}-writer", decider=DeciderKind.CODE
        ),
        outputs=outputs,
        status=StageStatus.COMPLETED,
    )


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


class _Write(NamedTuple):
    """One entity a fixture stage writes."""

    path: str
    entity_type: str
    entity_id: str
    version: Optional[int]
    payload: dict[str, Any]


class _StageStep(NamedTuple):
    """One stage execution of the fixture run, and what it wrote."""

    stage: str
    scope_key: str
    writes: tuple[_Write, ...]


def _write(
    path: str,
    entity_type: str,
    entity_id: str,
    version: Optional[int] = None,
    **payload: Any,
) -> _Write:
    return _Write(path, entity_type, entity_id, version, {"id": entity_id, **payload})


#: The fixture run: the §2.2 layout walked once, in stage order, covering
#: every row of the §2.3 ownership table that a single-signal, single-unit,
#: single-destination run touches — including the two rows that share a
#: directory (``strategies/``) and the one that is split by what the version
#: is rather than by where it sits (``plans/``).
_FIXTURE_RUN: tuple[_StageStep, ...] = (
    _StageStep("S-00", "signal", (
        _write("signal/selection.json", "E-01.selection", "sig-291"),
    )),
    _StageStep("S-01", "signal", (
        _write("signal/core/core.v1.json", "E-04", "core-291", 1),
        _write("signal/relevance.ref.json", "E-04.relevance_ref", "rel-291"),
    )),
    _StageStep("S-02", "signal", (
        _write("signal/features/features.v1.json", "E-05", "feat-291", 1),
        _write("signal/assets/assets.v1.json", "E-06", "ast-291", 1),
        _write("signal/notes/material_notes.json", "MaterialNotes", "notes-291"),
    )),
    _StageStep("S-03", "signal", (
        _write("signal/gaps/gap-291.json", "E-07", "gap-291"),
        _write("signal/core/core.v2.json", "E-04", "core-291", 2),
    )),
    _StageStep("S-04", "signal", (
        _write(
            "signal/boundary/interpretations/int-291.v1.json", "E-08", "int-291", 1
        ),
        _write("signal/boundary/boundary.v1.json", "E-09", "bnd-291", 1),
    )),
    _StageStep("S-05", "signal", (
        _write(f"{_UNIT}/unit.json", "E-10", "unit-291"),
    )),
    _StageStep("S-06", "unit-291", (
        _write(f"{_UNIT}/anchor/anchor.v1.json", "E-11", "anc-291", 1),
    )),
    _StageStep("S-07", "unit-291", (
        _write(f"{_DEST}/decision.json", "E-12", "dst-291-linkedin"),
    )),
    _StageStep("S-08", "unit-291/linkedin", (
        _write(f"{_DEST}/strategies/cs-291/str-291.json", "E-13", "str-291"),
    )),
    _StageStep("S-09", "unit-291/linkedin", (
        _write(
            f"{_DEST}/strategies/cs-291/selection.json",
            "StrategySelection",
            "cs-291",
        ),
    )),
    _StageStep("S-10", "unit-291/linkedin", (
        _write(
            f"{_DEST}/plans/plan-291.v1.json",
            "E-14", "plan-291", 1, stage_of_version=PLAN_DRAFT,
        ),
    )),
    _StageStep("S-11", "unit-291/linkedin", (
        _write(
            f"{_DEST}/plans/plan-291.v2.json",
            "E-14", "plan-291", 2, stage_of_version=PLAN_APPROVED,
        ),
        _write(
            f"{_DEST}/verdicts/plan_plan-291.v2.json", "PlanVerdict", "pv-291", 2
        ),
        _write(f"{_UNIT}/b1/round_1.json", "B1Round", "b1-291-r1"),
    )),
    _StageStep("S-12", "unit-291/linkedin", (
        _write(f"{_DEST}/texts/txt-291.v1.json", "E-15", "txt-291", 1),
    )),
    _StageStep("S-13", "unit-291/linkedin", (
        _write(
            f"{_DEST}/verdicts/text_txt-291.v1.json", "TextVerdict", "tv-291", 1
        ),
    )),
    _StageStep("S-14", "linkedin", (
        _write(f"{_DEST}/publication.json", "PublicationRef", "pub-291"),
        _write("fingerprints/fp-291.json", "E-16", "fp-291"),
    )),
)

_FIXTURE_ENTITY_COUNT = sum(len(step.writes) for step in _FIXTURE_RUN)


class _FixtureRun(NamedTuple):
    runs_root: Path
    run_id: str
    workspace: RunWorkspace
    manifest: RunManifest


def _build_fixture_run(runs_root: Path, run_id: str) -> _FixtureRun:
    """One complete run, written the way a run writes one.

    Entities through the writer that owns each path, a StageRecord per stage
    execution naming what that execution produced, and the manifest last.
    Nothing is written down twice: the index the manifest carries is built
    from the writes themselves.
    """

    workspace = RunWorkspace.create(runs_root, run_id)
    for seq, step in enumerate(_FIXTURE_RUN):
        entries = [
            workspace.write_entity(
                stage=step.stage,
                relative_path=item.path,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                version=item.version,
                payload=item.payload,
            )
            for item in step.writes
        ]
        workspace.write_stage_record(
            _stage_record(run_id, seq, step.stage, step.scope_key, _refs(entries))
        )
    manifest = workspace.write_manifest(_run_context(run_id))
    return _FixtureRun(runs_root, run_id, workspace, manifest)


@pytest.fixture
def fixture_run(tmp_path) -> _FixtureRun:
    return _build_fixture_run(tmp_path / "editorial_runs", create_run_id())


def _empty_workspace(tmp_path) -> RunWorkspace:
    return RunWorkspace.create(tmp_path / "editorial_runs", create_run_id())


def _rewrite_manifest(run: _FixtureRun, data: dict) -> None:
    """Edit a sealed manifest, which only something outside the run can do."""

    (run.workspace.run_dir / MANIFEST_NAME).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _manifest_of(run: _FixtureRun) -> dict:
    return json.loads(
        (run.workspace.run_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    )


# ===========================================================================
# Acceptance: a fixture run's manifest verifies
# ===========================================================================


def test_a_fixture_runs_manifest_verifies(fixture_run):
    report = verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)

    assert report.run_id == fixture_run.run_id
    assert report.run_digest == fixture_run.manifest.run_digest
    assert report.verified_entities == _FIXTURE_ENTITY_COUNT
    assert report.verified_stage_records == len(_FIXTURE_RUN)
    # every stage that ran is in the index as the writer of what it wrote,
    # so "which stage wrote this?" is answered by the manifest alone
    assert {entry.writer_stage for entry in fixture_run.manifest.entities} == {
        step.stage for step in _FIXTURE_RUN
    }
    assert is_complete(fixture_run.workspace.run_dir)


def test_a_complete_run_is_readable_as_a_source(fixture_run):
    run_dir, manifest = load_source_run(fixture_run.runs_root, fixture_run.run_id)

    assert run_dir == fixture_run.workspace.run_dir
    assert manifest.run_digest == fixture_run.manifest.run_digest
    assert manifest.run_context.run_id == fixture_run.run_id


def test_the_run_id_alone_is_the_workspace_key(fixture_run):
    assert EDITORIAL_RUNS_ROOT == Path("reports/editorial_runs")
    assert fixture_run.workspace.run_dir == fixture_run.runs_root / fixture_run.run_id
    # AD-04: the signal is an attribute of the manifest, never a directory key
    assert "sig-291" not in str(fixture_run.workspace.run_dir)
    assert fixture_run.manifest.run_context.assignment_id == "sig-291"


def test_the_trace_index_is_the_execution_order(fixture_run):
    assert [entry.stage for entry in fixture_run.manifest.trace] == [
        step.stage for step in _FIXTURE_RUN
    ]
    assert [entry.seq for entry in fixture_run.manifest.trace] == sorted(
        entry.seq for entry in fixture_run.manifest.trace
    )


# ===========================================================================
# P1 — create-once
# ===========================================================================


def test_an_overwrite_is_refused_and_the_first_write_stands(tmp_path):
    workspace = _empty_workspace(tmp_path)
    first = workspace.write_entity(
        stage="S-01",
        relative_path="signal/core/core.v1.json",
        entity_type="E-04",
        entity_id="core-291",
        version=1,
        payload={"claims": ["first"]},
    )

    with pytest.raises(ArtifactCollisionError):
        workspace.write_entity(
            stage="S-01",
            relative_path="signal/core/core.v1.json",
            entity_type="E-04",
            entity_id="core-291",
            version=1,
            payload={"claims": ["second"]},
        )

    path = workspace.run_dir / "signal/core/core.v1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["claims"] == ["first"]
    assert file_digest(path) == first.digest


def test_a_second_workspace_for_one_run_is_refused(tmp_path):
    run_id = create_run_id()
    RunWorkspace.create(tmp_path, run_id)

    # a crashed run is never resumed: the second workspace could only be a
    # resumption or a run_id collision, and both are wrong
    with pytest.raises(ArtifactCollisionError):
        RunWorkspace.create(tmp_path, run_id)


# ===========================================================================
# P2 — the version is in the key
# ===========================================================================


def test_the_version_a_file_name_states_is_the_version_it_carries():
    assert versioned_name("core", 2) == "core.v2.json"
    assert version_in_name(versioned_name("core", 2)) == 2
    assert version_in_name("plan_plan-291.v2.json") == 2
    assert version_in_name("material_notes.json") is None


@pytest.mark.parametrize(
    "stage, path, version",
    [
        ("S-03", "signal/core/core.v2.json", 1),      # name says 2, writer says 1
        ("S-03", "signal/gaps/gap-291.json", 1),      # name says nothing at all
        ("S-01", "signal/core/core.v1.json", None),   # name says 1, writer says none
    ],
)
def test_a_version_the_file_name_does_not_state_is_refused(
    tmp_path, stage, path, version
):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(RunWorkspaceError, match="the version is in the key"):
        workspace.write_entity(
            stage=stage,
            relative_path=path,
            entity_type="E-04",
            entity_id="core-291",
            version=version,
            payload={"id": "core-291"},
        )


# ===========================================================================
# P6 — write ownership, refused at the write
# ===========================================================================


@pytest.mark.parametrize(
    "stage, path, owner",
    [
        ("S-02", "signal/core/core.v1.json", "S-01"),
        ("S-01", "signal/core/core.v2.json", "S-03"),
        ("S-03", "signal/features/features.v1.json", "S-02"),
        ("S-08", f"{_DEST}/strategies/cs-291/selection.json", "S-09"),
        ("S-09", f"{_DEST}/strategies/cs-291/str-291.json", "S-08"),
        ("S-12", f"{_DEST}/verdicts/text_txt-291.v1.json", "S-13"),
        ("S-13", f"{_DEST}/texts/txt-291.v1.json", "S-12"),
        ("S-07", f"{_UNIT}/unit.json", "S-05"),
    ],
)
def test_a_stage_may_not_write_a_path_another_stage_owns(
    tmp_path, stage, path, owner
):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(WriteOwnershipError, match=f"gives that path to {owner}"):
        workspace.write_entity(
            stage=stage,
            relative_path=path,
            entity_type="E-XX",
            entity_id="ent-291",
            version=version_in_name(path.rsplit("/", 1)[-1]),
            payload={"id": "ent-291"},
        )
    assert not (workspace.run_dir / path).exists()


def test_the_plans_directory_is_split_by_what_the_version_is(tmp_path):
    workspace = _empty_workspace(tmp_path)

    # the same directory, two owners: §2.3 gives the draft to S-10 and the
    # approved version to S-11, and says so by what the version is
    workspace.write_entity(
        stage="S-10",
        relative_path=f"{_DEST}/plans/plan-291.v1.json",
        entity_type="E-14",
        entity_id="plan-291",
        version=1,
        payload={"stage_of_version": PLAN_DRAFT},
    )
    workspace.write_entity(
        stage="S-11",
        relative_path=f"{_DEST}/plans/plan-291.v2.json",
        entity_type="E-14",
        entity_id="plan-291",
        version=2,
        payload={"stage_of_version": PLAN_APPROVED, "supersedes": "plan-291.v1"},
    )

    with pytest.raises(WriteOwnershipError, match="gives that path to S-11"):
        workspace.write_entity(
            stage="S-10",
            relative_path=f"{_DEST}/plans/plan-291.v3.json",
            entity_type="E-14",
            entity_id="plan-291",
            version=3,
            payload={"stage_of_version": PLAN_APPROVED},
        )


def test_a_plan_that_declares_neither_stage_of_version_belongs_to_neither(tmp_path):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(WriteOwnershipError, match="belongs to neither"):
        workspace.write_entity(
            stage="S-10",
            relative_path=f"{_DEST}/plans/plan-291.v1.json",
            entity_type="E-14",
            entity_id="plan-291",
            version=1,
            payload={"id": "plan-291"},
        )


def test_a_path_outside_the_layout_has_no_writer(tmp_path):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(WriteOwnershipError, match="outside the run workspace layout"):
        workspace.write_entity(
            stage="S-12",
            relative_path=f"{_DEST}/scratch.json",
            entity_type="E-15",
            entity_id="txt-291",
            payload={"id": "txt-291"},
        )


@pytest.mark.parametrize(
    "path, expected",
    [
        (MANIFEST_NAME, "use write_manifest"),
        ("trace/0000_S-00_signal.json", "use write_stage_record"),
    ],
)
def test_an_entity_write_may_not_take_over_another_writers_file(
    tmp_path, path, expected
):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(WriteOwnershipError, match=expected):
        workspace.write_entity(
            stage="S-14",
            relative_path=path,
            entity_type="E-16",
            entity_id="fp-291",
            payload={"id": "fp-291"},
        )


def test_the_ownership_table_answers_for_every_path_the_fixture_run_writes():
    for step in _FIXTURE_RUN:
        for item in step.writes:
            assert (
                owner_of(
                    item.path,
                    stage_of_version=item.payload.get("stage_of_version"),
                )
                == step.stage
            )


# ===========================================================================
# P6 — write ownership, detected by verification
# ===========================================================================


def test_a_stage_claiming_a_file_another_stage_wrote_is_detected(tmp_path):
    runs_root, run_id = tmp_path / "editorial_runs", create_run_id()
    workspace = RunWorkspace.create(runs_root, run_id)
    entry = workspace.write_entity(
        stage="S-08",
        relative_path=f"{_DEST}/strategies/cs-291/str-291.json",
        entity_type="E-13",
        entity_id="str-291",
        payload={"id": "str-291"},
    )
    # the write was legitimate; the claim about who made it is not
    workspace.write_stage_record(
        _stage_record(run_id, 0, "S-12", "unit-291/linkedin", _refs([entry]))
    )
    workspace.write_manifest(_run_context(run_id))

    with pytest.raises(WriteOwnershipError, match="which §2.3 gives to S-08"):
        verify_run_workspace(runs_root, run_id)


def test_a_manifest_that_credits_the_wrong_stage_fails_verification(fixture_run):
    data = _manifest_of(fixture_run)
    for entry in data["entities"]:
        if entry["path"] == "signal/core/core.v1.json":
            entry["writer_stage"] = "S-02"
    _rewrite_manifest(fixture_run, data)

    # the files are untouched, so the run digest still matches: what fails is
    # the ownership of one path, which is the question §2.3 exists to answer
    with pytest.raises(WriteOwnershipError, match="outside its path patterns"):
        verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)


def test_a_file_that_never_went_through_the_writer_is_detected(fixture_run):
    atomic_write_json(
        fixture_run.workspace.run_dir / "signal/notes/planted.json", {"planted": True}
    )

    with pytest.raises(WorkspaceVerificationError, match="not in the manifest index"):
        verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)


# ===========================================================================
# Manifest digests
# ===========================================================================


def test_a_file_changed_after_the_run_indexed_it_fails_verification(fixture_run):
    path = fixture_run.workspace.run_dir / "signal/core/core.v1.json"
    path.write_text(json.dumps({"id": "core-291", "tampered": True}), encoding="utf-8")

    with pytest.raises(
        WorkspaceVerificationError, match="changed after the run indexed it"
    ):
        verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)


def test_an_indexed_file_that_is_gone_fails_verification(fixture_run):
    (fixture_run.workspace.run_dir / "fingerprints/fp-291.json").unlink()

    with pytest.raises(WorkspaceVerificationError, match="not in the workspace"):
        verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)


def test_an_index_edited_after_the_run_sealed_it_fails_verification(fixture_run):
    data = _manifest_of(fixture_run)
    dropped = data["entities"].pop()
    (fixture_run.workspace.run_dir / dropped["path"]).unlink()
    _rewrite_manifest(fixture_run, data)

    with pytest.raises(RunDigestMismatchError, match="sealed it"):
        verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)


def test_a_manifest_from_another_run_fails_verification(fixture_run, tmp_path):
    other = _build_fixture_run(tmp_path / "other_runs", create_run_id())
    _rewrite_manifest(fixture_run, _manifest_of(other))

    with pytest.raises(WorkspaceVerificationError, match="belongs to run"):
        verify_run_workspace(fixture_run.runs_root, fixture_run.run_id)


# ===========================================================================
# Manifest last, and the incomplete run
# ===========================================================================


def test_a_run_killed_before_its_manifest_is_incomplete_and_never_a_source(tmp_path):
    runs_root, run_id = tmp_path / "editorial_runs", create_run_id()
    workspace = RunWorkspace.create(runs_root, run_id)
    step = _FIXTURE_RUN[0]
    entry = workspace.write_entity(
        stage=step.stage,
        relative_path=step.writes[0].path,
        entity_type=step.writes[0].entity_type,
        entity_id=step.writes[0].entity_id,
        version=step.writes[0].version,
        payload=step.writes[0].payload,
    )
    workspace.write_stage_record(
        _stage_record(run_id, 0, step.stage, step.scope_key, _refs([entry]))
    )
    # and the process dies here: no manifest is ever written

    assert not is_complete(workspace.run_dir)
    # its partial files remain, for forensics…
    assert (workspace.run_dir / step.writes[0].path).is_file()
    # …and are never read as a source by another run
    with pytest.raises(IncompleteRunError, match="incomplete"):
        load_source_run(runs_root, run_id)
    with pytest.raises(IncompleteRunError, match="incomplete"):
        verify_run_workspace(runs_root, run_id)


def test_nothing_may_be_written_after_the_manifest(fixture_run):
    workspace = fixture_run.workspace
    assert workspace.sealed

    with pytest.raises(RunWorkspaceError, match="nothing follows"):
        workspace.write_entity(
            stage="S-14",
            relative_path="fingerprints/fp-later.json",
            entity_type="E-16",
            entity_id="fp-later",
            payload={"id": "fp-later"},
        )
    with pytest.raises(RunWorkspaceError, match="nothing follows"):
        workspace.write_stage_record(
            _stage_record(fixture_run.run_id, 99, "S-15", "run")
        )
    with pytest.raises(RunWorkspaceError, match="nothing follows"):
        workspace.write_manifest(_run_context(fixture_run.run_id))


def test_a_manifest_is_refused_for_another_runs_context(tmp_path):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(RunWorkspaceError, match="belongs to run"):
        workspace.write_manifest(_run_context(create_run_id()))
    assert not is_complete(workspace.run_dir)


# ===========================================================================
# StageRecord
# ===========================================================================


def test_a_stage_that_runs_again_writes_a_new_record(tmp_path):
    runs_root, run_id = tmp_path / "editorial_runs", create_run_id()
    workspace = RunWorkspace.create(runs_root, run_id)

    first = workspace.write_stage_record(
        _stage_record(run_id, 0, "S-08", "unit-291/linkedin/attempt_1")
    )
    second = workspace.write_stage_record(
        _stage_record(run_id, 1, "S-08", "unit-291/linkedin/attempt_2")
    )

    # two executions, two files: the re-entry is the evidence, not a version
    assert first.path != second.path
    assert (workspace.run_dir / first.path).is_file()
    assert (workspace.run_dir / second.path).is_file()


def test_stage_record_seq_is_monotonic_within_the_run(tmp_path):
    runs_root, run_id = tmp_path / "editorial_runs", create_run_id()
    workspace = RunWorkspace.create(runs_root, run_id)
    workspace.write_stage_record(_stage_record(run_id, 4, "S-00", "signal"))

    with pytest.raises(RunWorkspaceError, match="monotonic"):
        workspace.write_stage_record(_stage_record(run_id, 4, "S-01", "signal"))


def test_a_stage_record_from_another_run_is_refused(tmp_path):
    workspace = _empty_workspace(tmp_path)

    with pytest.raises(RunWorkspaceError, match="belongs to run"):
        workspace.write_stage_record(
            _stage_record(create_run_id(), 0, "S-00", "signal")
        )


def test_a_record_attributed_to_another_stage_is_refused():
    with pytest.raises(ValueError, match="not a second opinion"):
        StageRecord(
            run_id=create_run_id(),
            seq=0,
            stage="S-08",
            scope_key="unit-291/linkedin",
            started_at=TS_UTC,
            ended_at=TS_UTC,
            created_by=StageAttribution(
                stage="S-09", component="strategist", decider=DeciderKind.MODEL
            ),
            status=StageStatus.COMPLETED,
        )


def test_a_stage_record_round_trips_through_its_serialization(fixture_run):
    path = fixture_run.workspace.run_dir / fixture_run.manifest.trace[0].path
    record = StageRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    assert record.stage == _FIXTURE_RUN[0].stage
    assert record.run_id == fixture_run.run_id
    assert record.to_dict() == json.loads(path.read_text(encoding="utf-8"))


# ===========================================================================
# The extended verify_run_provenance (§4.3)
# ===========================================================================


def test_verify_run_provenance_verifies_the_run_workspace_when_given_one(tmp_path):
    from tests.test_provenance_chain import SIG, _full_run

    packages = tmp_path / "packages"
    packages.mkdir()
    code, runs = _full_run(packages)
    assert code == 0 and len(runs) == 1
    run = _build_fixture_run(tmp_path / "editorial_runs", runs[0])

    # production passes no root, and gets exactly the verification it had
    baseline = verify_run_provenance(packages, SIG, runs[0])
    assert baseline.editorial_run_digest is None

    report = verify_run_provenance(
        packages, SIG, runs[0], editorial_runs_root=run.runs_root
    )
    assert report.editorial_run_digest == run.manifest.run_digest
    assert report.verified_artifacts == baseline.verified_artifacts


def test_verify_run_provenance_refuses_a_workspace_that_does_not_verify(tmp_path):
    from tests.test_provenance_chain import SIG, _full_run

    packages = tmp_path / "packages"
    packages.mkdir()
    code, runs = _full_run(packages)
    assert code == 0 and len(runs) == 1
    run = _build_fixture_run(tmp_path / "editorial_runs", runs[0])
    (run.workspace.run_dir / "signal/core/core.v1.json").write_text(
        json.dumps({"id": "core-291", "tampered": True}), encoding="utf-8"
    )

    # the artifact chain is untouched and still verifies on its own…
    assert verify_run_provenance(packages, SIG, runs[0]).run_id == runs[0]
    # …so what fails is the workspace, and the error says which of the two
    with pytest.raises(ProvenanceError, match="workspace does not verify"):
        verify_run_provenance(
            packages, SIG, runs[0], editorial_runs_root=run.runs_root
        )
