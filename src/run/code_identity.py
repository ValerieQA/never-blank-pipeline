"""Deterministic code identity for one pipeline run (Issue #114 / Story #21).

Story #21 asks for two consecutive live runs *without code repair between
them*. Proving that requires the runs to say, in their own evidence, which
code executed — otherwise the claim rests on operator testimony.

The identity is deliberately tiny: the checked-out commit and whether the
tracked source of that checkout still matched it. It is read from the local
repository only — no network, no repository mutation, no branch, remote,
author, message or diff, and nothing from the environment. This is not build
metadata and is not a deployment record; it exists to answer one question,
``did Run A and Run B execute the same code``.

When the identity cannot be resolved — no repository, no ``git``, an
unexpected output shape — the answer is *absence*. A fabricated or partial
identity would be worse than none, because Story #21 acceptance is exactly
the claim that identity supports.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


#: The rule by which ``tracked_worktree_clean`` was decided, recorded beside
#: the flag so a later change to the rule cannot silently rewrite the meaning
#: of an already-persisted ``true``.
#:
#: ``tracked-source-v1``: no tracked file outside the pipeline's own output
#: roots may differ from ``HEAD``. The exclusion is not a convenience — a run
#: writes into tracked files under ``reports/``, so a rule covering them would
#: make the second of two consecutive runs permanently non-qualifying. What
#: must not differ is the code and configuration that decide behavior.
CLEAN_POLICY = "tracked-source-v1"

#: Roots the pipeline itself writes into. Changes here are run output, not
#: code repair.
_OUTPUT_ROOTS = ("reports/", "data/")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_TIMEOUT_SECONDS = 30


class CodeIdentity(BaseModel):
    """Which code executed a run, and whether its source was untouched."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit_sha: str = Field(min_length=40, max_length=40)
    tracked_worktree_clean: bool
    clean_policy: str = Field(min_length=1, max_length=64)

    @field_validator("commit_sha")
    @classmethod
    def _full_lowercase_sha(cls, value: str) -> str:
        # An abbreviated or upper-case SHA would still compare equal to itself
        # and unequal to a differently-formatted record of the same commit.
        if not _SHA_RE.match(value):
            raise ValueError("commit_sha must be a full 40-character lowercase hex SHA")
        return value


def qualifies_for_live_acceptance(identity: Optional[CodeIdentity]) -> bool:
    """Story #21 qualification, derived rather than stored.

    A stored verdict could drift from the fields it summarizes; this cannot.
    Absence fails closed: a run that could not prove its code identity is not
    acceptance evidence, whether because it ran outside a repository or
    because it predates this contract.
    """

    return identity is not None and identity.tracked_worktree_clean


def resolve_code_identity(repo_root: Optional[Path] = None) -> Optional[CodeIdentity]:
    """Read the local checkout's identity, or return ``None``.

    Both commands are local reads. ``rev-parse`` resolves ``HEAD`` without
    touching the object store's remotes, and ``status --untracked-files=no``
    deliberately ignores untracked files: artifacts a run leaves behind are
    not a modification of the code that produced them.
    """

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]

    sha = _git(root, "rev-parse", "HEAD")
    if sha is None:
        return None
    sha = sha.strip()
    if not _SHA_RE.match(sha):
        # A detached, unborn or otherwise unusual HEAD gives something that is
        # not a commit. There is no honest identity to record for it.
        return None

    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    if status is None:
        return None

    return CodeIdentity(
        commit_sha=sha,
        tracked_worktree_clean=_tracked_source_is_clean(status),
        clean_policy=CLEAN_POLICY,
    )


def _tracked_source_is_clean(porcelain_status: str) -> bool:
    """True when nothing outside the pipeline's output roots differs."""

    for line in porcelain_status.splitlines():
        path = line[3:].strip() if len(line) > 3 else ""
        if not path:
            continue
        # A rename prints "old -> new"; the destination decides.
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        path = path.strip('"')
        if not path.startswith(_OUTPUT_ROOTS):
            return False
    return True


def _git(root: Path, *args: str) -> Optional[str]:
    """Run one read-only git command, or return ``None`` on any failure."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # No git binary, no permission, a timeout — all mean the same thing
        # here: the identity is unavailable, not zero.
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout
