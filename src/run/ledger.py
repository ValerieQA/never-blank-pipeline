"""The durable learning ledger, tier 2 (Issue #293, slice SL-1).

Step 3 §0 finding 1: nothing the target needs across runs is durable today.
The run workspace is an Actions artifact that expires in 90 days, so portfolio
memory, skip and degrade rates, publication observations and the knowledge
queue would all disappear with it. §3 gives those records a second tier — a
small, append-only ledger committed to the repository — and this module is its
writer and its commit step.

What the tier is (§3.1, §3.2, P4, P9)
-------------------------------------
Root ``data/editorial/``, next to the existing durable ``data/research/`` and
``data/strategy/``. **One file per record**, never a shared append-only file:
two runs finishing at once then conflict on nothing, because they touch
different paths. Every file is written once, through the repository's single
``atomic_write_json`` link(2) commit, so a record is create-once here exactly
as it is in the workspace.

The commit step is the one ``monday_publish.yml`` already uses: stage only the
records the run wrote, commit ``[skip ci]``, push, and on a push race rebase
onto the remote and try again. It sets no git configuration of its own — the
committing identity belongs to the job, exactly as it does for the marker
persistence step, and a library that rewrote a developer's ``user.email``
would be a worse surprise than a recorded failure.

Why it can fail and why that is not an error (§3.1)
---------------------------------------------------
A push can fail for reasons that have nothing to do with this run. When it
does, the failure is **recorded and the run ends normally**: it does not undo a
publication, it does not wait for a person (I-02), and the next run does not
try to recover it. The records are still in the run's workspace artifact, and
recovery is offline maintenance. That is why :func:`commit_ledger` returns a
report instead of raising — a caller cannot accidentally turn a lost learning
record into a failed run, because there is nothing to catch.

**This applies to learning records only.** Publication idempotency never
depends on this commit: it has its own authority, written first and alone
(§3.6, invariant S3-I1, ``src/publishing/publication_markers.py``).

The report carries a failure **category** and never a git message: a
RunSummary records this status (§3.3), the repository is public (P9), and a
provider or transport message is exactly what §3.3 keeps out of the ledger.

Sources: ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§3.1, §3.2 and §6; ``scripts/ci/persist_publication_markers.sh`` for the
commit mechanism this mirrors.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# The repository's one create-once commit and its one path-component
# validator, reused rather than copied — as the run workspace reuses them.
from src.artifacts import _validate_path_component, atomic_write_json

#: Root of tier 2 (§3.1).
DEFAULT_LEDGER_ROOT = Path("data/editorial")

#: Redirects the ledger exactly as ``NB_PUBLICATION_MARKERS_DIR`` redirects the
#: idempotency authority: a test must never be able to commit a durable
#: learning record into the tracked tree.
LEDGER_DIR_VAR = "NB_EDITORIAL_LEDGER_DIR"

#: Bounded, because nothing waits (I-02). Five attempts is what the marker
#: persistence step uses, and a race that survives five rebases is not a race.
DEFAULT_PUSH_ATTEMPTS = 5
DEFAULT_RETRY_SECONDS = 3.0

_GIT_TIMEOUT_SECONDS = 120


class LedgerError(RuntimeError):
    """The ledger was asked for something its contract refuses."""


class LedgerCommitStatus(str, Enum):
    """What became of one run's ledger commit (§3.1).

    ``NOT_ATTEMPTED`` is the shadow default: a slice that runs beside
    production writes its records and leaves the repository alone. It is a
    state of its own rather than a second spelling of ``FAILED``, because a
    commit nobody asked for is not a commit that went wrong.
    """

    COMMITTED = "committed"
    NOTHING_TO_COMMIT = "nothing_to_commit"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class LedgerCommitFailure(str, Enum):
    """Why a commit failed, as a closed category.

    A category and never the git output: this value reaches the RunSummary, the
    RunSummary is committed to a public repository (P9), and §3.3 keeps raw
    messages out of the ledger. What a reader needs is which step gave way; the
    message itself belongs to the job log.
    """

    GIT_UNAVAILABLE = "git_unavailable"
    NO_REPOSITORY = "no_repository"
    STAGE_FAILED = "stage_failed"
    #: The run wrote records and git staged none of them — normally an ignore
    #: rule over the ledger path. Reported as a failure rather than as
    #: ``nothing_to_commit`` because the silent version of this is a ledger
    #: that quietly never receives anything.
    NOTHING_STAGED = "nothing_staged"
    COMMIT_FAILED = "commit_failed"
    PUSH_FAILED = "push_failed"


class LedgerCommitReport(BaseModel):
    """What one commit step did, and what it could not do."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: LedgerCommitStatus
    #: How many pushes were attempted. Zero when nothing needed pushing.
    attempts: int = Field(default=0, ge=0)
    #: The failing step, present exactly when the status is ``failed``.
    failure: Optional[LedgerCommitFailure] = None

    @property
    def blocked_the_run(self) -> bool:
        """Always false, and stated so it can be asserted.

        §3.1: a failed ledger commit does not undo a publication and does not
        stop a run. The property exists because "it does not block" is a claim
        a test should be able to make about the returned value rather than
        about the absence of an exception.
        """

        return False


def ledger_root() -> Path:
    """Where the ledger lives (``NB_EDITORIAL_LEDGER_DIR``, else the default)."""

    configured = os.environ.get(LEDGER_DIR_VAR, "").strip()
    return Path(configured) if configured else DEFAULT_LEDGER_ROOT


def ledger_path(relative_path: str, *, root: Optional[Path] = None) -> Path:
    """The absolute path of one ledger record, with every component validated.

    Nothing absolute, nothing empty and nothing that could climb out of the
    ledger: a record ID reaches a file name, and the ledger is committed.
    """

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise LedgerError(
            f"a ledger path must be a non-blank string; got {relative_path!r}"
        )
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("/"):
        raise LedgerError(f"a ledger path must be relative: {relative_path!r}")
    parts = normalized.split("/")
    for part in parts:
        _validate_path_component(part, "ledger path component")
    base = Path(root) if root is not None else ledger_root()
    return base.joinpath(*parts)


def write_record(
    relative_path: str,
    payload: dict[str, Any],
    *,
    root: Optional[Path] = None,
) -> Path:
    """Write one durable record and return where it went (P1, P4).

    One record, one file. The write is the repository's create-once commit, so
    a second run that produced the same path is refused rather than merged:
    the ledger is append-only, and an edit is a new record, never an
    overwrite.
    """

    path = ledger_path(relative_path, root=root)
    atomic_write_json(path, payload)
    return path


def commit_ledger(
    *,
    paths: Sequence[Path],
    message: str,
    repo_root: Optional[Path] = None,
    remote: str = "origin",
    branch: str = "main",
    attempts: int = DEFAULT_PUSH_ATTEMPTS,
    retry_seconds: float = DEFAULT_RETRY_SECONDS,
) -> LedgerCommitReport:
    """Commit the run's own ledger records and push, rebasing on a race.

    The §3.1 mechanism, over exactly the files the run wrote and nothing else:
    every git command carries those paths as its pathspec. That is narrower
    than "the ledger directory" on purpose. The publication markers live under
    the same root and are committed by their own step, first and alone, under
    its own rules (§3.6) — a learning commit that swept the whole root would
    quietly commit a marker that step had deliberately withheld.

    A run that wrote no record commits nothing. A run that wrote records none
    of which git staged reports ``nothing_staged``: silence there would be a
    ledger that never receives anything.

    Never raises for a git failure. Every one of them ends in a ``failed``
    report naming the step that gave way, because §3.1 makes a lost learning
    record a recorded fact and not a run failure. ``[skip ci]`` is appended for
    the reason the marker step appends it: a commit of stored evidence is not a
    change anything needs to re-test.
    """

    if attempts < 1:
        raise LedgerError(
            f"a commit step pushes at least once; got attempts={attempts!r}"
        )
    if not message.strip():
        raise LedgerError("a ledger commit needs a message")

    if not paths:
        return LedgerCommitReport(status=LedgerCommitStatus.NOTHING_TO_COMMIT)

    repo = Path(repo_root) if repo_root is not None else Path.cwd()
    if not _git_available():
        return LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            failure=LedgerCommitFailure.GIT_UNAVAILABLE,
        )
    if not (repo / ".git").exists():
        return LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            failure=LedgerCommitFailure.NO_REPOSITORY,
        )
    try:
        pathspec = [
            str(Path(path).resolve().relative_to(repo.resolve())) for path in paths
        ]
    except ValueError:
        # A record outside the checkout cannot be committed by it. That is a
        # configuration answer rather than a git failure, and it is reported
        # the same way: the record is on disk either way.
        return LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            failure=LedgerCommitFailure.NO_REPOSITORY,
        )

    if _git(repo, "add", "--", *pathspec) is None:
        return LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            failure=LedgerCommitFailure.STAGE_FAILED,
        )
    # ``git diff --staged --quiet`` exits 0 when the index matches HEAD: the
    # run wrote records and the repository took none of them.
    if _git(repo, "diff", "--staged", "--quiet", "--", *pathspec) is not None:
        return LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            failure=LedgerCommitFailure.NOTHING_STAGED,
        )
    subject = f"{message} [skip ci]"
    if _git(repo, "commit", "-q", "-m", subject, "--", *pathspec) is None:
        return LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            failure=LedgerCommitFailure.COMMIT_FAILED,
        )

    tried = 0
    for attempt in range(1, attempts + 1):
        tried = attempt
        if _git(repo, "push") is not None:
            return LedgerCommitReport(
                status=LedgerCommitStatus.COMMITTED, attempts=attempt
            )
        if attempt == attempts:
            break
        # Rebase and retry rather than force-push: another run's record is not
        # this run's to discard.
        if _git(repo, "pull", "--rebase", "--autostash", remote, branch) is None:
            break
        if retry_seconds > 0:
            time.sleep(attempt * retry_seconds)

    return LedgerCommitReport(
        status=LedgerCommitStatus.FAILED,
        attempts=tried,
        failure=LedgerCommitFailure.PUSH_FAILED,
    )


def commit_message(kind: str, run_id: str, paths: Sequence[Path]) -> str:
    """``editorial ledger: <n> <kind> record(s) from run <run_id>``.

    The subject says what the commit holds and which run produced it, and
    nothing about what the records contain: a commit subject is as public as
    the ledger it commits.
    """

    return f"editorial ledger: {len(paths)} {kind} record(s) from run {run_id}"


def _git_available() -> bool:
    """Is there a git to run at all?

    Probed once, before the first command, so that a deployment without git
    reports ``git_unavailable`` rather than looking like a staging failure.
    Each category then means exactly one thing to whoever reads the summary.
    """

    try:
        completed = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _git(repo: Path, *args: str) -> Optional[str]:
    """Run one git command in the checkout, or return ``None`` if it failed.

    Output is captured and discarded on failure on purpose. The caller turns a
    ``None`` into a closed failure category; a transport message would reach
    the RunSummary, and the RunSummary is public (P9).
    """

    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout
