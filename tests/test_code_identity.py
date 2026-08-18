"""Code identity for Story #21 acceptance (Issue #114).

Story #21 claims two consecutive live runs executed *the same code*. These
tests hold the line that makes that claim checkable rather than testified:
the identity is read from the real repository, it is stable for one checkout
and different for another, a modified source tree is disqualified, and an
unresolvable repository yields absence instead of an invented commit.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.intake.assignment_record import (
    ASSIGNMENT_RECORD_SCHEMA_VERSION,
    AssignmentRecord,
)
from src.run.code_identity import (
    CLEAN_POLICY,
    CodeIdentity,
    qualifies_for_live_acceptance,
    resolve_code_identity,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real throwaway repository — the reader is not worth faking."""

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "reports").mkdir()
    _git_init = subprocess.run(
        ["git", "init", "-q", str(root)], capture_output=True, text=True,
    )
    assert _git_init.returncode == 0
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "src" / "module.py").write_text("VALUE = 1\n")
    (root / "reports" / "output.json").write_text("{}\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return root


# ── 1–3: the SHA itself ──────────────────────────────────────────────────────

def test_exact_head_sha_is_captured(repo: Path):
    identity = resolve_code_identity(repo)
    assert identity is not None
    assert identity.commit_sha == _git(repo, "rev-parse", "HEAD")
    assert len(identity.commit_sha) == 40
    assert identity.clean_policy == CLEAN_POLICY


def test_same_checkout_yields_the_same_identity(repo: Path):
    first = resolve_code_identity(repo)
    second = resolve_code_identity(repo)
    assert first == second                      # frozen models compare by value


def test_changed_head_yields_a_different_identity(repo: Path):
    before = resolve_code_identity(repo)
    (repo / "src" / "module.py").write_text("VALUE = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    after = resolve_code_identity(repo)
    assert after is not None and before is not None
    assert after.commit_sha != before.commit_sha


# ── 4: the dirty-worktree policy ─────────────────────────────────────────────

def test_modified_tracked_source_does_not_qualify(repo: Path):
    (repo / "src" / "module.py").write_text("VALUE = 999\n")
    identity = resolve_code_identity(repo)
    assert identity is not None                 # the commit is still knowable
    assert identity.tracked_worktree_clean is False
    assert qualifies_for_live_acceptance(identity) is False


def test_untracked_files_alone_do_not_dirty_the_checkout(repo: Path):
    (repo / "src" / "scratch.py").write_text("# not added\n")
    (repo / "reports" / "run-output").mkdir()
    identity = resolve_code_identity(repo)
    assert identity is not None
    assert identity.tracked_worktree_clean is True
    assert qualifies_for_live_acceptance(identity) is True


def test_the_run_s_own_tracked_output_does_not_disqualify_it(repo: Path):
    """A run writes into tracked ``reports/`` — that is output, not repair.

    Without this exclusion the two-run sequence could not be executed at all:
    Run A dirties tracked output by finishing, so Run B could never start
    from a qualifying checkout without committing (which would move HEAD and
    break the equal-SHA criterion this whole task exists to prove).
    """

    (repo / "reports" / "output.json").write_text('{"published": true}\n')
    identity = resolve_code_identity(repo)
    assert identity is not None
    assert identity.tracked_worktree_clean is True
    assert qualifies_for_live_acceptance(identity) is True


def test_dirty_source_beside_dirty_output_still_does_not_qualify(repo: Path):
    (repo / "reports" / "output.json").write_text('{"published": true}\n')
    (repo / "src" / "module.py").write_text("VALUE = 3\n")
    identity = resolve_code_identity(repo)
    assert identity is not None and identity.tracked_worktree_clean is False


def test_renamed_tracked_source_does_not_qualify(repo: Path):
    _git(repo, "mv", "src/module.py", "src/renamed.py")
    identity = resolve_code_identity(repo)
    assert identity is not None and identity.tracked_worktree_clean is False


# ── 5: unresolvable identity ─────────────────────────────────────────────────

def test_outside_a_repository_the_identity_is_absent(tmp_path: Path):
    identity = resolve_code_identity(tmp_path / "not-a-repo")
    assert identity is None
    assert qualifies_for_live_acceptance(None) is False


def test_a_repository_without_commits_has_no_identity(tmp_path: Path):
    root = tmp_path / "unborn"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], capture_output=True, check=True)
    assert resolve_code_identity(root) is None


def test_an_abbreviated_or_uppercase_sha_is_rejected():
    for bad in ("7d6147d", "7D6147D808DB480C848F7FB80D80BA33D9C05712", "", "z" * 40):
        with pytest.raises(Exception):
            CodeIdentity(
                commit_sha=bad, tracked_worktree_clean=True, clean_policy=CLEAN_POLICY,
            )


# ── 6–7: presence in canonical evidence, and strict reload ───────────────────

def _configuration(fill: str):
    from src.strategy.execution_context import ConfigurationIdentity

    return ConfigurationIdentity(
        schema_version="1.0",
        configuration_id="never-blank-business-strategy",
        configuration_version="1.0",
        configuration_hash="sha256:" + fill * 64,
    )


def _assignment(assignment_id: str):
    from src.intake.content_assignment import ContentAssignment

    return ContentAssignment(
        origin="manual",
        submitted_at="2026-08-18T00:00:00+00:00",
        assignment_id=assignment_id,
        topic="a topic",
        target_audience="small business owners",
        strategy_ref="never-blank-business-strategy",
        strategy_version="1.0",
    )


def test_identity_survives_strict_reload_on_the_assignment_anchor():
    identity = CodeIdentity(
        commit_sha="a" * 40, tracked_worktree_clean=True, clean_policy=CLEAN_POLICY,
    )
    record = AssignmentRecord(
        run_id="run-1",
        execution_mode="controlled-live",
        configuration_identity=_configuration("b"),
        assignment=_assignment("sig-1"),
        code_identity=identity,
    )
    raw = json.loads(record.model_dump_json())
    assert raw["schema_version"] == ASSIGNMENT_RECORD_SCHEMA_VERSION
    assert raw["code_identity"]["commit_sha"] == "a" * 40

    reloaded = AssignmentRecord.model_validate(raw)
    assert reloaded.code_identity == identity


def test_records_written_before_this_contract_still_load():
    """Create-once evidence is never rewritten, so 1.0 must stay readable."""

    legacy = {
        "schema_version": "1.0",
        "run_id": "run-0",
        "execution_mode": "dry-run",
        "configuration_identity": _configuration("c").model_dump(mode="json"),
        "assignment": _assignment("sig-0").model_dump(mode="json"),
    }
    record = AssignmentRecord.model_validate(legacy)
    assert record.code_identity is None
    assert qualifies_for_live_acceptance(record.code_identity) is False


# ── 8: nothing but the identity may enter the identity ───────────────────────

def test_no_extra_fields_can_be_smuggled_into_the_identity():
    with pytest.raises(Exception):
        CodeIdentity(
            commit_sha="a" * 40,
            tracked_worktree_clean=True,
            clean_policy=CLEAN_POLICY,
            api_key="secret",                     # extra="forbid"
        )


def test_the_identity_carries_no_environment_or_secret_surface(monkeypatch, repo: Path):
    monkeypatch.setenv("NB_WIX_API_KEY", "super-secret-value")
    monkeypatch.setenv("NB_ZERNIO_API_KEY", "another-secret")
    identity = resolve_code_identity(repo)
    assert identity is not None
    serialized = identity.model_dump_json()
    assert "secret" not in serialized
    # only the three declared fields exist at all
    assert set(json.loads(serialized)) == {
        "commit_sha", "tracked_worktree_clean", "clean_policy",
    }


def test_the_reader_never_mutates_the_repository(repo: Path):
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain")
    resolve_code_identity(repo)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain") == before_status


# ── The two-run acceptance condition (Issue #114 review correction) ──────────
#
# These prove the *evidence* behaves as the Story #21 procedure assumes. No
# production code compares two runs — the comparison is the operator's, made
# in the runbook — so what is tested here is what the operator's comparison
# rests on.


def test_two_runs_at_the_same_head_record_the_same_identity(repo: Path):
    """The acceptance condition, in the case where it must hold."""

    run_a = resolve_code_identity(repo)
    # Run A leaves output behind: excluded roots, uncommitted.
    (repo / "reports" / "output.json").write_text('{"run": "a"}\n')
    (repo / "reports" / "run-a-artifacts").mkdir()
    run_b = resolve_code_identity(repo)

    assert run_a is not None and run_b is not None
    assert run_a.commit_sha == run_b.commit_sha
    assert run_a.tracked_worktree_clean and run_b.tracked_worktree_clean
    assert qualifies_for_live_acceptance(run_a)
    assert qualifies_for_live_acceptance(run_b)


def test_generated_changes_under_either_output_root_stay_clean(repo: Path):
    (repo / "data").mkdir()
    (repo / "data" / "history.jsonl").write_text('{"published": true}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add data root")

    (repo / "data" / "history.jsonl").write_text('{"published": true}\n{"more": 1}\n')
    (repo / "reports" / "output.json").write_text('{"run": "a"}\n')
    identity = resolve_code_identity(repo)
    assert identity is not None and identity.tracked_worktree_clean is True


def test_an_artifact_only_commit_breaks_the_same_sha_condition(repo: Path):
    """Why the runbook forbids committing between the runs.

    The exclusion of the output roots is about *working-tree changes*. It says
    nothing about commits: ``commit_sha`` is the exact ``rev-parse HEAD``, so
    committing Run A's artifacts — even though they are excluded from
    cleanliness, even though no source changed — moves HEAD and gives Run B a
    different identity. Cleanliness and commit identity are separate
    guarantees, and this is the case that separates them.
    """

    run_a = resolve_code_identity(repo)

    (repo / "reports" / "output.json").write_text('{"run": "a"}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore: persist run A artifacts")

    run_b = resolve_code_identity(repo)
    assert run_a is not None and run_b is not None

    # Both runs individually qualify — nothing is dirty, no source moved …
    assert run_a.tracked_worktree_clean and run_b.tracked_worktree_clean
    assert qualifies_for_live_acceptance(run_a)
    assert qualifies_for_live_acceptance(run_b)
    # … and yet the acceptance condition cannot be met.
    assert run_a.commit_sha != run_b.commit_sha


def test_an_automated_commit_touching_only_excluded_roots_also_breaks_it(repo: Path):
    """Automated VI publishing commits to data/ and report artifacts.

    It moves HEAD like any other commit, which is why the runbook resets the
    sequence rather than reasoning that the commit "was only artifacts".
    """

    frozen = resolve_code_identity(repo)
    (repo / "data").mkdir()
    (repo / "data" / "visibility_queue.jsonl").write_text('{"queued": 1}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore(vi): publish run [skip ci]")

    after = resolve_code_identity(repo)
    assert frozen is not None and after is not None
    assert after.commit_sha != frozen.commit_sha
