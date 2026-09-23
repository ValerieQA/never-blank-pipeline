"""Issue #293: the walking skeleton, end to end over six destinations.

SL-1's acceptance evidence, as scenarios:

1. **a fixture run creates six destination folders and a verified manifest** —
   the whole canonical topology executed once, sealed, and accepted by the
   reader that refuses a workspace which does not match its own manifest;
2. **the RunSummary validator rejects free text, money and raw errors** — the
   summary this run puts in the ledger is public-safe (the validator's own
   scenarios are in ``test_293_run_summary.py``);
3. **a ledger commit failure is recorded and does not fail the run**.

And the two production-safety claims the slice rests on: the run makes no model
call and no external publish call, and it touches the repository only when a
caller explicitly asks it to.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.editorial_core.topology import CANONICAL_TOPOLOGY, topology_digest
from src.run.code_identity import CLEAN_POLICY, CodeIdentity
from src.run.ledger import LedgerCommitFailure, LedgerCommitStatus
from src.run.run_summary import RunSummary, verify_public_safe
from src.run.run_workspace import (
    MANIFEST_NAME,
    TRACE_DIRECTORY,
    file_digest,
    is_complete,
)
from src.run.walking_skeleton import (
    CANONICAL_DESTINATIONS,
    PASS_THROUGH_MARKER,
    ProviderRefused,
    SkeletonError,
    SkeletonFixture,
    SkeletonRun,
    run_walking_skeleton,
)

_IDENTITY = CodeIdentity(
    commit_sha="c" * 40,
    tracked_worktree_clean=True,
    clean_policy=CLEAN_POLICY,
)

STORE = "data/editorial"


def _run(tmp_path: Path, **overrides: Any) -> SkeletonRun:
    """One shadow skeleton run, entirely inside the test's own directories."""

    arguments: dict[str, Any] = dict(
        runs_root=tmp_path / "editorial_runs",
        ledger_dir=tmp_path / STORE,
        code_identity=_IDENTITY,
        commit_retry_seconds=0.0,
    )
    arguments.update(overrides)
    return run_walking_skeleton(**arguments)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """A working clone with a real remote, and the remote."""

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    for key, value in (
        ("user.name", "t"),
        ("user.email", "t@e"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "-C", str(work), "config", key, value], check=True)
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "seed"], check=True)
    subprocess.run(
        ["git", "-C", str(work), "push", "-q", "-u", "origin", "main"], check=True
    )
    return work, remote


# ── (1) the fixture run ────────────────────────────────────────────────────


def test_a_fixture_run_creates_six_destination_folders(tmp_path):
    run = _run(tmp_path)

    folders = run.destination_dirs

    assert len(folders) == 6
    assert {folder.name for folder in folders} == set(CANONICAL_DESTINATIONS)
    # Each one holds the whole per-destination chain, not just a directory.
    for folder in folders:
        assert (folder / "decision.json").is_file()
        assert list(folder.glob("strategies/*/selection.json"))
        assert list(folder.glob("plans/*.v2.json"))
        assert list(folder.glob("texts/*.v1.json"))
        assert (folder / "publication.json").is_file()


def test_a_fixture_run_produces_a_manifest_that_verifies(tmp_path):
    run = _run(tmp_path)

    assert is_complete(run.run_dir)
    assert run.verification.run_id == run.run_context.run_id
    assert run.verification.run_digest == run.manifest.run_digest
    assert run.verification.verified_entities == len(run.manifest.entities)
    assert run.verification.verified_stage_records == len(run.records)


def test_every_stage_of_the_registry_executed_and_recorded_it(tmp_path):
    run = _run(tmp_path)

    executed = [record.stage for record in run.records]

    assert set(executed) == set(CANONICAL_TOPOLOGY.stage_ids)
    # The registry's order is the run's order, and nothing reorders it.
    assert executed == sorted(executed)
    assert [record.seq for record in run.records] == list(range(len(run.records)))
    trace = list((run.run_dir / TRACE_DIRECTORY).glob("*.json"))
    assert len(trace) == len(run.records)


def test_every_destination_scoped_stage_ran_once_per_destination(tmp_path):
    run = _run(tmp_path)

    for stage in ("S-08", "S-09", "S-10", "S-12", "S-13", "S-14"):
        scopes = {
            record.scope_key for record in run.records if record.stage == stage
        }
        assert scopes == {
            f"{SkeletonFixture().unit_id}/{name}"
            for name in CANONICAL_DESTINATIONS
        }, stage


def test_the_entities_declare_themselves_as_pass_throughs(tmp_path):
    run = _run(tmp_path)

    for entry in run.manifest.entities:
        body = json.loads((run.run_dir / entry.path).read_text(encoding="utf-8"))
        assert body.get(PASS_THROUGH_MARKER) is True, entry.path


def test_the_manifest_records_the_canonical_topology(tmp_path):
    run = _run(tmp_path)

    assert run.manifest.topology_digest == topology_digest()


def test_two_runs_of_different_configurations_share_one_topology_digest(tmp_path):
    """CE-1: configuration does not make a second engine (Step 6 §0.1)."""

    first = _run(tmp_path, fixture=SkeletonFixture("sig-a", "unit-a"), client="a")
    second = _run(tmp_path, fixture=SkeletonFixture("sig-b", "unit-b"), client="b")

    assert first.run_dir != second.run_dir
    assert first.manifest.topology_digest == second.manifest.topology_digest
    assert first.summary.topology_digest == second.summary.topology_digest


def test_a_run_over_fewer_than_six_destinations_is_refused(tmp_path):
    with pytest.raises(SkeletonError, match="six destinations"):
        _run(tmp_path, destinations=("wix", "linkedin"))


def test_a_refused_run_leaves_no_workspace_behind(tmp_path):
    with pytest.raises(SkeletonError):
        _run(tmp_path, destinations=())

    assert not (tmp_path / "editorial_runs").exists()


# ── (2) the summary that reaches the ledger ────────────────────────────────


def test_the_run_writes_one_public_safe_summary_to_the_ledger(tmp_path):
    run = _run(tmp_path)

    assert run.summary_path.is_file()
    assert run.summary_path == tmp_path / STORE / run.summary.relative_path()
    stored = json.loads(run.summary_path.read_text(encoding="utf-8"))
    verify_public_safe(stored)
    assert RunSummary.from_dict(stored) == run.summary


def test_the_summary_says_how_every_scope_of_the_run_ended(tmp_path):
    run = _run(tmp_path)

    keys = [state.scope_key for state in run.summary.scope_outcomes]

    assert keys[0] == SkeletonFixture().signal_id
    assert keys[1] == SkeletonFixture().unit_id
    assert keys[2:] == [
        f"{SkeletonFixture().unit_id}/{name}" for name in CANONICAL_DESTINATIONS
    ]
    # A pass-through leaves nothing unresolved, so nothing is counted as a skip.
    assert all(state.state_code is None for state in run.summary.scope_outcomes)


def test_the_summary_points_at_the_workspace_it_summarizes(tmp_path):
    run = _run(tmp_path)

    assert run.summary.workspace.manifest_digest == file_digest(
        run.run_dir / MANIFEST_NAME
    )
    assert run.summary.workspace.retention_days == 90
    assert run.summary.run_id == run.run_context.run_id


def test_the_summary_reports_every_counter_and_no_spend(tmp_path):
    run = _run(tmp_path)

    assert {entry.counter for entry in run.summary.counters} == {
        counter.counter_id for counter in CANONICAL_TOPOLOGY.counters
    }
    assert all(entry.used == 0 for entry in run.summary.counters)


# ── production safety ──────────────────────────────────────────────────────


def test_the_run_makes_no_model_call(tmp_path):
    run = _run(tmp_path)

    assert run.summary.calls_total == 0
    assert all(entry.calls == 0 for entry in run.summary.stage_calls)
    # And nothing could have made one: the provider it carried refuses.
    with pytest.raises(ProviderRefused):
        run.provider.complete("anything")


def test_the_run_publishes_nothing(tmp_path):
    run = _run(tmp_path)

    assert run.summary.publications == ()
    assert run.summary.publication_unconfirmed == ()
    for folder in run.destination_dirs:
        record = json.loads(
            (folder / "publication.json").read_text(encoding="utf-8")
        )
        assert record["published"] is False
        assert record["mode"] == "shadow"


def test_the_run_touches_no_repository_unless_it_is_asked_to(tmp_path):
    run = _run(tmp_path)

    assert run.records_commit.status is LedgerCommitStatus.NOT_ATTEMPTED
    assert run.summary_commit.status is LedgerCommitStatus.NOT_ATTEMPTED


# ── (3) the ledger commit ──────────────────────────────────────────────────


def test_the_run_commits_its_summary_when_asked(tmp_path):
    work, remote = _repo(tmp_path)

    run = _run(
        tmp_path,
        ledger_dir=work / STORE,
        repo_root=work,
        commit=True,
    )

    assert run.summary_commit.status is LedgerCommitStatus.COMMITTED
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(remote), str(fresh)], check=True)
    assert (fresh / STORE / run.summary.relative_path()).is_file()


def test_a_ledger_commit_failure_is_recorded_and_does_not_fail_the_run(tmp_path):
    work, _ = _repo(tmp_path)
    # The push can never land, which is the §3.1 case: the learning record is
    # lost to the repository and the run is not.
    subprocess.run(["git", "-C", str(work), "remote", "remove", "origin"], check=True)

    run = _run(
        tmp_path,
        ledger_dir=work / STORE,
        repo_root=work,
        commit=True,
        commit_attempts=1,
    )

    assert run.summary_commit.status is LedgerCommitStatus.FAILED
    assert run.summary_commit.failure is LedgerCommitFailure.PUSH_FAILED
    assert run.summary_commit.blocked_the_run is False
    # The run finished: a sealed, verified workspace and a summary on disk.
    assert is_complete(run.run_dir)
    assert run.verification.run_id == run.run_context.run_id
    assert run.summary_path.is_file()


def test_the_summary_states_the_status_of_the_commit_it_can_state(tmp_path):
    """§3.3: the summary carries ``ledger_commit`` for the records it covers.

    This slice writes no learning record yet, so that first step has nothing to
    commit and says so. The summary's own commit is the second step, and its
    result is reported to the caller — a file cannot record the failure to
    commit itself.
    """

    work, _ = _repo(tmp_path)

    run = _run(tmp_path, ledger_dir=work / STORE, repo_root=work, commit=True)

    assert run.records_commit.status is LedgerCommitStatus.NOTHING_TO_COMMIT
    assert run.summary.ledger_commit is LedgerCommitStatus.NOTHING_TO_COMMIT
    assert run.summary_commit.status is LedgerCommitStatus.COMMITTED
