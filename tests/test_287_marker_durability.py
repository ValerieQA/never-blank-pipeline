"""#287: the publication authority survives the runner, and one run wins a key.

Three things the first attempt at NB-00a left open, all of them ways a real
double publication could still happen (PR #321 review):

1. the store was written into a GitHub-hosted runner's working tree and died
   with it, so the next run's checkout saw nothing and could republish;
2. two runs that both read "nothing published" both recorded an intent and
   both published;
3. a directory that could not be synced still reported a durable write.

The proofs here are deterministic: a real git repository with a real remote
for the persistence seam, and real filesystem failures for the rest. No
network, no credential, no publisher.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from src.publishing.publication_markers import (
    AuthorityState,
    MarkerStore,
    PublicationIdentity,
)

SCRIPT = Path("scripts/ci/persist_publication_markers.sh").resolve()
STORE_PATH = "data/editorial/publication_markers"

#: Every workflow that can publish, and whether it takes a dry-run input.
PUBLISHING_WORKFLOWS = {
    "monday_publish.yml": True,
    "wednesday_golden.yml": True,
    "research_generate_and_publish.yml": True,
    "visibility_publish.yml": True,
    "daily_signal_research.yml": False,
    "scheduled_publish.yml": False,
}


def _store(root: Path) -> MarkerStore:
    """A store that exists: a missing root means "no authority", not "empty"."""

    root.mkdir(parents=True, exist_ok=True)
    return MarkerStore(root)


def _identity(destination: str = "wix") -> PublicationIdentity:
    return PublicationIdentity(
        client="never_blank",
        destination=destination,
        source_signal_ids=("sig-287-0001",),
    )


# ── one run wins a key ─────────────────────────────────────────────────────


def test_a_second_run_cannot_claim_a_key_another_run_already_holds(tmp_path):
    """The simultaneous case `lookup` cannot see: both read "not published"."""

    store = _store(tmp_path)
    identity = _identity()

    first = store.record_intent(identity, run_id="run-A")
    second = store.record_intent(identity, run_id="run-B")

    assert first is not None, "the first run must be allowed to call"
    assert second is None, "the second run must not be allowed to call"


def test_our_own_claim_is_re_entrant_within_one_run(tmp_path):
    """Re-entry is not a race — a run may re-record its own intent."""

    store = _store(tmp_path)
    identity = _identity()

    first = store.record_intent(identity, run_id="run-A")
    again = store.record_intent(identity, run_id="run-A")

    assert first is not None
    assert again is not None
    assert again.run_id == "run-A"


def test_an_unreadable_claim_is_treated_as_another_runs_claim(tmp_path):
    """A half-written claim is still a claim; it must never read as absent."""

    store = _store(tmp_path)
    identity = _identity()
    path = store.intent_path(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ truncated", encoding="utf-8")

    assert store.record_intent(identity, run_id="run-A") is None


# ── a durability failure is never reported as success ──────────────────────


def test_a_directory_that_cannot_be_synced_forbids_the_call(tmp_path, monkeypatch):
    """A rename is not durable until its directory is; a swallowed failure lies."""

    import src.publishing.publication_markers as markers

    store = _store(tmp_path)
    monkeypatch.setattr(markers, "_fsync_dir", lambda path: False)

    assert store.record_intent(_identity(), run_id="run-A") is None


def test_a_directory_that_cannot_be_opened_reports_failure(tmp_path):
    """The other half: `_fsync_dir` must PRODUCE a false, not only honour one.

    Monkeypatching the function proves the callers respect its answer. This
    proves the answer is real, against a directory that is not there.
    """

    from src.publishing.publication_markers import _fsync_dir

    assert _fsync_dir(tmp_path) is True
    assert _fsync_dir(tmp_path / "does-not-exist") is False


def test_an_undurable_write_is_never_reported_as_durable(tmp_path, monkeypatch):
    """`_write_durably` must carry the directory sync's answer out to callers."""

    import src.publishing.publication_markers as markers

    path = tmp_path / "store" / "x.json"
    assert markers._write_durably(path, {"a": 1}) is True
    monkeypatch.setattr(markers, "_fsync_dir", lambda directory: False)
    assert markers._write_durably(path, {"a": 2}) is False


def test_a_marker_whose_directory_cannot_be_synced_is_not_confirmed(
    tmp_path, monkeypatch
):
    import src.publishing.publication_markers as markers

    store = _store(tmp_path)
    monkeypatch.setattr(markers, "_fsync_dir", lambda path: False)
    monkeypatch.setattr(markers, "_MARKER_RETRY_SECONDS", 0)

    assert (
        store.record_marker(_identity(), external_id="x-1", run_id="run-A") is None
    )


# ── the workflow seam ──────────────────────────────────────────────────────


@pytest.mark.parametrize("workflow", sorted(PUBLISHING_WORKFLOWS))
def test_every_publishing_workflow_persists_the_markers(workflow):
    """The store is committed by every workflow that can write to it."""

    data = yaml.safe_load(Path(".github/workflows", workflow).read_text())
    steps = [
        step
        for job in data["jobs"].values()
        for step in job.get("steps", [])
        if "persist_publication_markers.sh" in str(step.get("run", ""))
    ]

    assert len(steps) == 1, f"{workflow} must persist the markers exactly once"


@pytest.mark.parametrize("workflow", sorted(PUBLISHING_WORKFLOWS))
def test_the_persistence_step_survives_a_later_destination_failing(workflow):
    """`always()`, never `success()` — that is the whole point of the step.

    A run where the second destination fails is exactly the run whose first
    marker must become durable. A step guarded by `success()` commits nothing
    there, which is the defect this step exists to close.
    """

    data = yaml.safe_load(Path(".github/workflows", workflow).read_text())
    step = next(
        step
        for job in data["jobs"].values()
        for step in job.get("steps", [])
        if "persist_publication_markers.sh" in str(step.get("run", ""))
    )
    condition = str(step.get("if", ""))

    assert "always()" in condition, f"{workflow}: persistence must run on failure too"
    assert "success()" not in condition, f"{workflow}: success() strands the marker"


@pytest.mark.parametrize(
    "workflow", sorted(w for w, has_dry_run in PUBLISHING_WORKFLOWS.items() if has_dry_run)
)
def test_a_dry_run_workflow_never_persists_publication_evidence(workflow):
    """A rehearsal that leaves durable evidence suppresses a real publication."""

    data = yaml.safe_load(Path(".github/workflows", workflow).read_text())
    step = next(
        step
        for job in data["jobs"].values()
        for step in job.get("steps", [])
        if "persist_publication_markers.sh" in str(step.get("run", ""))
    )

    assert "dry_run != 'true'" in str(step.get("if", "")), workflow
    assert "DRY_RUN" in step.get("env", {}), f"{workflow}: the script needs its own guard"


# ── the script, against a real repository ──────────────────────────────────


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """A working clone with a real remote, and the remote."""

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@e"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(work), "config", key, value], check=True)
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "-u", "origin", "main"], check=True)
    return work, remote


def _publish_in(work: Path, destination: str = "wix", run_id: str = "run-A") -> None:
    """What a publishing run leaves behind for one destination that succeeded."""

    store = _store(work / STORE_PATH)
    identity = _identity(destination)
    assert store.record_intent(identity, run_id=run_id) is not None
    assert store.record_marker(identity, external_id="ext-1", run_id=run_id) is not None


def _run_script(work: Path, **env: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "GITHUB_RUN_ID": "1", **env}
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=work, env=environment,
        capture_output=True, text=True, check=False,
    )


def test_the_script_persists_the_markers_and_nothing_else(tmp_path):
    work, _ = _repo(tmp_path)
    _publish_in(work)
    # Whatever else a publishing run leaves in the tree is not this step's.
    (work / "reports").mkdir()
    (work / "reports" / "scratch.json").write_text("{}", encoding="utf-8")

    result = _run_script(work)

    assert result.returncode == 0, result.stderr
    committed = subprocess.run(
        ["git", "-C", str(work), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert committed, "the markers must be committed"
    assert all(path.startswith(STORE_PATH) for path in committed), committed


def test_a_dry_run_persists_nothing(tmp_path):
    work, _ = _repo(tmp_path)
    _publish_in(work)
    before = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout

    result = _run_script(work, DRY_RUN="true")

    after = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert result.returncode == 0
    assert before == after, "a rehearsal must leave no durable publication evidence"


def test_a_later_destination_failing_does_not_strand_the_earlier_marker(tmp_path):
    """The partial failure, end to end: run 1 publishes wix, linkedin fails."""

    work, remote = _repo(tmp_path)
    store = _store(work / STORE_PATH)
    wix, linkedin = _identity("wix"), _identity("linkedin")
    assert store.record_intent(wix, run_id="run-A") is not None
    assert store.record_marker(wix, external_id="wix-1", run_id="run-A") is not None
    # linkedin claimed the key and then the call failed: intent, no marker.
    assert store.record_intent(linkedin, run_id="run-A") is not None

    # The publishing step exited non-zero. The persistence step still runs.
    assert _run_script(work).returncode == 0

    # A fresh checkout — a different runner, nothing carried over.
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(remote), str(fresh)], check=True)
    fresh_store = MarkerStore(fresh / STORE_PATH)

    assert fresh_store.lookup(wix).state is AuthorityState.PUBLISHED
    assert fresh_store.lookup(linkedin).state is AuthorityState.POSSIBLY_PUBLISHED
    assert fresh_store.lookup(wix).marker.external_id == "wix-1"


def test_a_fresh_checkout_refuses_to_republish_what_a_previous_run_published(tmp_path):
    work, remote = _repo(tmp_path)
    _publish_in(work)
    assert _run_script(work).returncode == 0

    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(remote), str(fresh)], check=True)
    store = MarkerStore(fresh / STORE_PATH)

    assert store.record_intent(_identity(), run_id="run-B") is None, (
        "a key published by an earlier run must not be claimable by the next"
    )


def test_a_crash_after_the_claim_survives_to_the_next_checkout(tmp_path):
    """At-most-once across runners: the intent alone already forbids the key."""

    work, remote = _repo(tmp_path)
    store = _store(work / STORE_PATH)
    identity = _identity()
    assert store.record_intent(identity, run_id="run-A") is not None
    # Crash here: the call may or may not have happened, no marker was written.

    assert _run_script(work).returncode == 0

    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(remote), str(fresh)], check=True)
    lookup = MarkerStore(fresh / STORE_PATH).lookup(identity)

    assert lookup.state is AuthorityState.POSSIBLY_PUBLISHED
    assert not lookup.may_publish


def test_the_persisted_intent_is_the_one_the_run_wrote(tmp_path):
    work, remote = _repo(tmp_path)
    store = _store(work / STORE_PATH)
    identity = _identity()
    store.record_intent(identity, run_id="run-A")
    assert _run_script(work).returncode == 0

    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(remote), str(fresh)], check=True)
    written = json.loads(
        (fresh / STORE_PATH / "never_blank" / "wix").glob("*.intent.json").__next__()
        .read_text(encoding="utf-8")
    )

    assert written["run_id"] == "run-A"
    assert written["source_signal_ids"] == ["sig-287-0001"]
