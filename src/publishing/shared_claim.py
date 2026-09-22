"""The claim that two runners can both see, decided before either publishes.

``MarkerStore`` takes a key exclusively on its own filesystem. On a persistent
working tree that is the whole answer. On GitHub-hosted runners it is not: two
jobs have two filesystems, so both create the intent, both believe they may
call, and both publish (#321 review). Persisting afterwards cannot undo an
external side effect — the arbitration has to happen *before* the call.

The store already lives in git, and a remote ref update is atomic and
server-side: exactly one push of a given parent lands. That is the arbiter.
This module is not a second idempotency authority — it is how the existing one
becomes visible to a runner that has not seen it yet. The claim is per key, so
two runs publishing different things never wait for each other.

Fail-closed everywhere: anything this cannot establish, verify or clean up
returns ``False``, and ``False`` means the provider is not called.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Final, Optional, Protocol

from src.utils.logger import get_logger

log = get_logger("publishing.shared_claim")

#: Enough attempts to lose the push race to unrelated commits a few times.
_PUSH_ATTEMPTS: Final[int] = 5


class SharedClaim(Protocol):
    """Arbitrates one key across runners, before the irreversible call."""

    def acquire(self, path: Path, run_id: str) -> bool:
        """Is this run the one allowed to publish the key ``path`` stands for?"""


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    )


class GitSharedClaim:
    """The remote branch decides. One push of a given parent lands; the rest lose.

    ``acquire`` commits the single intent file and pushes it. A push that lands
    IS the claim, and it is durable for every later runner at the moment it
    lands — before this run calls the provider. A push that is rejected means
    someone else moved the branch: if they took this key, this run has lost and
    must not call; if they did something unrelated, this run rebases and tries
    again.
    """

    def __init__(self, repo: Path, *, branch: str = "", remote: str = "origin") -> None:
        self.repo = Path(repo)
        self.remote = remote
        self.branch = branch or os.environ.get("NB_CLAIM_BRANCH", "main")

    # ── reading what the remote says about one key ─────────────────────────

    def _remote_run_id(self, relative: str) -> Optional[str]:
        """The run that owns this key on the remote, or ``None`` if nobody does."""

        shown = _git(self.repo, "show", f"{self.remote}/{self.branch}:{relative}")
        if shown.returncode != 0:
            return None
        try:
            data = json.loads(shown.stdout)
        except json.JSONDecodeError:
            # Present but unreadable is still someone's claim, never ours.
            return ""
        return str(data.get("run_id", "")) if isinstance(data, dict) else ""

    # ── taking it ──────────────────────────────────────────────────────────

    def acquire(self, path: Path, run_id: str) -> bool:
        try:
            relative = str(Path(path).resolve().relative_to(self.repo.resolve()))
        except ValueError:
            log.warning("shared claim: %s is outside %s", path, self.repo)
            return False

        if _git(self.repo, "add", "--", relative).returncode != 0:
            return False
        # The identity travels with the command. A hosted runner has no git
        # user configured, and a claim that cannot commit is a publication
        # that cannot happen — too important to depend on a workflow
        # remembering to set it.
        committed = _git(
            self.repo,
            "-c", "user.name=github-actions[bot]",
            "-c", "user.email=github-actions[bot]@users.noreply.github.com",
            "-c", "commit.gpgsign=false",
            "commit", "-q",
            "-m", f"publication claim: {relative} [skip ci]", "--", relative,
        )
        if committed.returncode != 0 and _git(
            self.repo, "diff", "--staged", "--quiet", "--", relative
        ).returncode != 0:
            log.warning("shared claim: could not commit %s", relative)
            return False

        for attempt in range(_PUSH_ATTEMPTS):
            pushed = _git(self.repo, "push", self.remote, f"HEAD:{self.branch}")
            if pushed.returncode == 0:
                return True

            if _git(self.repo, "fetch", "-q", self.remote, self.branch).returncode != 0:
                log.warning("shared claim: cannot verify the remote; refusing")
                return False

            owner = self._remote_run_id(relative)
            if owner is not None and owner != run_id:
                # Someone else holds this key. Drop our commit so the workspace
                # carries their claim, not a losing one of our own.
                _git(self.repo, "reset", "-q", "--hard", f"{self.remote}/{self.branch}")
                log.info("shared claim: %s is held by another run", relative)
                return False
            if owner == run_id:
                return True

            # The branch moved for unrelated reasons; put our claim on top.
            if _git(self.repo, "rebase", f"{self.remote}/{self.branch}").returncode != 0:
                _git(self.repo, "rebase", "--abort")
                log.warning("shared claim: could not rebase onto the remote")
                return False
            log.info("shared claim: retrying push (%d)", attempt + 1)

        log.warning("shared claim: exhausted push attempts for %s", relative)
        return False


def shared_claim_required() -> bool:
    """Whether a claim this runner alone can see is not good enough.

    True on a hosted runner, where "nobody else has this key" is a statement
    about one ephemeral filesystem and nothing more. ``NB_SHARED_CLAIM`` can
    force it either way for a test or a self-hosted setup.
    """

    forced = os.environ.get("NB_SHARED_CLAIM", "").strip().lower()
    if forced in {"1", "true", "required"}:
        return True
    if forced in {"0", "false", "off"}:
        return False
    return bool(os.environ.get("GITHUB_ACTIONS"))


def default_shared_claim(root: Path) -> Optional[SharedClaim]:
    """The arbiter for a store that lives in a git checkout with a remote."""

    top = _git(Path(root), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None
    repo = Path(top.stdout.strip())
    if _git(repo, "remote", "get-url", "origin").returncode != 0:
        return None
    return GitSharedClaim(repo)
