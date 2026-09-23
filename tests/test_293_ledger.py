"""Issue #293: the durable learning ledger and its commit step.

Step 3 §3 gives the canonical engine a second storage tier, and two of its
properties have to be able to fail before they mean anything:

- **one file per record, written once** (P1, P4). Two runs never contend on
  the end of a shared file, and a record is never edited in place.
- **a commit failure is recorded and does not fail the run** (§3.1). This is
  the one the rest of the engine leans on: a lost learning record must not be
  able to turn into a lost run, so the commit step returns a report and there
  is nothing to catch.

The commit tests run against a real repository with a real remote, because
what is being tested is the git mechanism itself.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.artifacts import ArtifactCollisionError
from src.run.ledger import (
    DEFAULT_LEDGER_ROOT,
    LEDGER_DIR_VAR,
    LedgerCommitFailure,
    LedgerCommitStatus,
    LedgerError,
    commit_ledger,
    commit_message,
    ledger_path,
    ledger_root,
    write_record,
)

STORE = "data/editorial"


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


def _record(work: Path, name: str = "runs/never_blank/2026-09/run-a.json") -> Path:
    return write_record(name, {"run_id": "run-a"}, root=work / STORE)


def _branch_head(repository: Path, branch: str = "main") -> str:
    return subprocess.run(
        ["git", "-C", str(repository), "rev-parse", branch],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _committed_paths(work: Path) -> list[str]:
    return subprocess.run(
        ["git", "-C", str(work), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


# ── the root ───────────────────────────────────────────────────────────────


def test_the_ledger_root_is_the_committed_one_unless_redirected(monkeypatch):
    monkeypatch.delenv(LEDGER_DIR_VAR, raising=False)
    assert ledger_root() == DEFAULT_LEDGER_ROOT

    monkeypatch.setenv(LEDGER_DIR_VAR, "/tmp/elsewhere")
    assert ledger_root() == Path("/tmp/elsewhere")


def test_a_record_path_cannot_climb_out_of_the_ledger(tmp_path):
    for attempt in ("../secrets.json", "/etc/passwd", "runs/../../x.json", "  "):
        with pytest.raises((LedgerError, ValueError)):
            ledger_path(attempt, root=tmp_path)


# ── one file per record, written once ──────────────────────────────────────


def test_each_record_is_its_own_file(tmp_path):
    first = write_record("runs/c/2026-09/a.json", {"run_id": "a"}, root=tmp_path)
    second = write_record("runs/c/2026-09/b.json", {"run_id": "b"}, root=tmp_path)

    assert first != second
    assert json.loads(first.read_text(encoding="utf-8"))["run_id"] == "a"
    assert json.loads(second.read_text(encoding="utf-8"))["run_id"] == "b"


def test_a_record_is_never_overwritten(tmp_path):
    write_record("runs/c/2026-09/a.json", {"run_id": "a"}, root=tmp_path)

    with pytest.raises(ArtifactCollisionError):
        write_record("runs/c/2026-09/a.json", {"run_id": "a-again"}, root=tmp_path)


# ── the commit step ────────────────────────────────────────────────────────


def test_the_commit_step_commits_and_pushes_the_record(tmp_path):
    work, remote = _repo(tmp_path)
    record = _record(work)

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.COMMITTED
    assert report.failure is None
    assert report.attempts == 1
    assert _committed_paths(work) == [f"{STORE}/runs/never_blank/2026-09/run-a.json"]
    # The push reached the remote, which is the whole point of the step.
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(remote), str(fresh)], check=True)
    assert (fresh / STORE / "runs/never_blank/2026-09/run-a.json").is_file()


def test_the_commit_step_commits_nothing_but_the_run_s_own_records(tmp_path):
    """§3.6: the markers under the same root are another step's, under its rules."""

    work, _ = _repo(tmp_path)
    record = _record(work)
    # Whatever else is in the tree — an edit the run made, and a publication
    # marker its own step deliberately withheld — is not this step's.
    (work / "README.md").write_text("edited by the run\n", encoding="utf-8")
    marker = work / STORE / "publication_markers/never_blank/wix/key.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.COMMITTED
    assert _committed_paths(work) == [f"{STORE}/runs/never_blank/2026-09/run-a.json"]


def test_the_push_lands_on_the_remote_and_branch_it_was_given(tmp_path):
    """The rebase targets those two; the push has to target the same ones.

    A push that followed the checkout's own upstream instead would report
    ``committed`` having left the ledger branch exactly as it found it.
    """

    work, remote = _repo(tmp_path)
    elsewhere = tmp_path / "elsewhere.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", elsewhere], check=True)
    subprocess.run(
        ["git", "-C", str(work), "remote", "add", "elsewhere", str(elsewhere)],
        check=True,
    )
    # The configured upstream is now the other remote: a bare ``git push``
    # would go there and not to the ledger the caller asked for.
    subprocess.run(
        ["git", "-C", str(work), "push", "-q", "-u", "elsewhere", "main"], check=True
    )
    record = _record(work)

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        remote="origin",
        branch="main",
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.COMMITTED
    assert _branch_head(remote) == _branch_head(work)
    assert _branch_head(elsewhere) != _branch_head(work)


def test_a_run_that_wrote_no_record_commits_nothing(tmp_path):
    work, _ = _repo(tmp_path)

    report = commit_ledger(
        paths=(),
        message=commit_message("learning", "run-a", ()),
        repo_root=work,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.NOTHING_TO_COMMIT
    assert report.failure is None


def test_records_the_repository_ignores_are_a_failure_not_a_silence(tmp_path):
    """A ledger that quietly never receives anything is the worst outcome."""

    work, _ = _repo(tmp_path)
    (work / ".gitignore").write_text(f"{STORE}/\n", encoding="utf-8")
    record = _record(work)

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.FAILED
    assert report.failure is LedgerCommitFailure.STAGE_FAILED


def test_the_committed_ledger_path_is_not_ignored_by_this_repository():
    """The condition that would make the failure above happen in production.

    ``data/*`` is ignored wholesale, because almost everything under it is
    runtime scratch. The ledger is not: a RunSummary that cannot be added is a
    RunSummary the indicators never see.
    """

    checked = subprocess.run(
        ["git", "check-ignore", "-q", f"{STORE}/runs/never_blank/2026-09/x.json"],
        capture_output=True,
        check=False,
    )

    # git check-ignore: 0 = ignored, 1 = not ignored.
    assert checked.returncode == 1


# ── failure is recorded, never raised (§3.1) ───────────────────────────────


def test_a_push_that_cannot_succeed_is_recorded_and_does_not_raise(tmp_path):
    work, _ = _repo(tmp_path)
    record = _record(work)
    # The remote is gone: the commit is made and the push can never land.
    subprocess.run(["git", "-C", str(work), "remote", "remove", "origin"], check=True)

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        attempts=2,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.FAILED
    assert report.failure is LedgerCommitFailure.PUSH_FAILED
    assert report.blocked_the_run is False
    # §3.1: the record is still on disk, and recovery is offline maintenance.
    assert record.is_file()


def test_a_record_outside_any_repository_is_recorded_not_raised(tmp_path):
    record = write_record(
        "runs/c/2026-09/a.json", {"run_id": "a"}, root=tmp_path / "ledger"
    )

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=tmp_path,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.FAILED
    assert report.failure is LedgerCommitFailure.NO_REPOSITORY


def test_a_record_that_is_not_inside_the_checkout_is_refused_by_category(tmp_path):
    work, _ = _repo(tmp_path)
    record = write_record(
        "runs/c/2026-09/a.json", {"run_id": "a"}, root=tmp_path / "outside"
    )

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        retry_seconds=0.0,
    )

    assert report.status is LedgerCommitStatus.FAILED
    assert report.failure is LedgerCommitFailure.NO_REPOSITORY


def test_the_report_never_carries_a_git_message(tmp_path):
    """P9: the status reaches a public RunSummary, so it is a category."""

    work, _ = _repo(tmp_path)
    record = _record(work)
    subprocess.run(["git", "-C", str(work), "remote", "remove", "origin"], check=True)

    report = commit_ledger(
        paths=(record,),
        message=commit_message("run-summary", "run-a", (record,)),
        repo_root=work,
        attempts=1,
        retry_seconds=0.0,
    )

    assert set(report.model_dump()) == {"status", "attempts", "failure"}
    assert report.failure is not None
    assert report.failure.value in {item.value for item in LedgerCommitFailure}


# ── the caller's contract ──────────────────────────────────────────────────


def test_a_commit_step_that_would_never_push_is_a_programming_error(tmp_path):
    work, _ = _repo(tmp_path)
    record = _record(work)

    with pytest.raises(LedgerError):
        commit_ledger(paths=(record,), message="x", repo_root=work, attempts=0)

    with pytest.raises(LedgerError):
        commit_ledger(paths=(record,), message="   ", repo_root=work)


def test_the_commit_subject_says_what_it_holds_and_nothing_else():
    subject = commit_message("run-summary", "run-a", (Path("a.json"),))

    assert subject == "editorial ledger: 1 run-summary record(s) from run run-a"
