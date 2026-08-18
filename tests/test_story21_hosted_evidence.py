"""The hosted live path must preserve its own evidence (Story #21).

A hosted runner can publish to Wix and LinkedIn for real and then be destroyed
along with the canonical run namespace — leaving a genuine publication that
cannot be verified by Story #16 provenance, Story #20 reporting, or Story #21
closure. That is the failure mode these tests exist to prevent: they hold the
workflow's evidence-preservation contract, not its publishing behavior.

They are configuration contract tests. No production Python is involved, which
is itself part of the contract: the run directory layout is owned by
``resolve_run_dir``, and the workflow must follow it rather than invent a
second source of truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "research_generate_and_publish.yml"

ENTRYPOINT_FRAGMENT = "scripts/generate_and_publish.py --signal-id"
EVIDENCE_STEP = "Preserve canonical run evidence"
BOOKKEEPING_STEP = "Mark signal as published"


@pytest.fixture(scope="module")
def steps() -> list[dict]:
    spec = yaml.safe_load(WORKFLOW.read_text())
    jobs = list(spec["jobs"].values())
    assert len(jobs) == 1, "the live workflow is expected to define exactly one job"
    return jobs[0]["steps"]


def _index(steps: list[dict], predicate) -> int:
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    raise AssertionError("step not found")


def _evidence_step(steps: list[dict]) -> dict:
    return steps[_index(steps, lambda s: s.get("name") == EVIDENCE_STEP)]


# ── 1. the canonical run namespace is preserved ──────────────────────────────

def test_the_canonical_run_namespace_is_uploaded(steps):
    step = _evidence_step(steps)
    assert step["uses"].startswith("actions/upload-artifact@")
    path = step["with"]["path"]
    assert path == (
        "reports/content_packages/${{ steps.resolve.outputs.signal_id }}/runs/"
    )


def test_the_uploaded_path_matches_the_production_run_layout():
    """The workflow follows ``resolve_run_dir``; it does not redefine it."""

    from src.artifacts import resolve_run_dir

    produced = resolve_run_dir(Path("reports/content_packages"), "SIG", "RUN")
    assert produced == Path("reports/content_packages/SIG/runs/RUN")

    step_path = yaml.safe_load(WORKFLOW.read_text())
    text = WORKFLOW.read_text()
    # the uploaded prefix is exactly the layout production writes
    assert "reports/content_packages/${{ steps.resolve.outputs.signal_id }}/runs/" in text
    assert str(produced.parent) == "reports/content_packages/SIG/runs"


def test_run_id_is_not_reconstructed_from_a_second_source(steps):
    """``run_id`` is generated inside the process and never guessed outside it."""

    step = _evidence_step(steps)
    path = step["with"]["path"]
    assert "run_id" not in path.lower()
    assert "grep" not in str(step) and "sed" not in str(step)


# ── 2. preservation happens after the live attempt ───────────────────────────

def test_evidence_is_preserved_after_the_canonical_entrypoint_runs(steps):
    entrypoint = _index(steps, lambda s: ENTRYPOINT_FRAGMENT in str(s.get("run", "")))
    evidence = _index(steps, lambda s: s.get("name") == EVIDENCE_STEP)
    assert evidence > entrypoint


def test_the_canonical_run_precedes_publication_bookkeeping(steps):
    entrypoint = _index(steps, lambda s: ENTRYPOINT_FRAGMENT in str(s.get("run", "")))
    bookkeeping = _index(steps, lambda s: s.get("name") == BOOKKEEPING_STEP)
    assert entrypoint < bookkeeping


def test_evidence_preservation_cannot_suppress_publication_bookkeeping(steps):
    """Ordering, not decoration — this is why the evidence step comes last.

    ``Mark signal as published`` is guarded by ``success()``. An evidence
    upload standing in front of it could fail for an unrelated
    artifact-service reason, turn ``success()`` false, and silently skip the
    record of a publication that really happened — leaving a later run free to
    treat an already-published signal as unconsumed. Evidence may never veto
    bookkeeping.
    """

    bookkeeping = _index(steps, lambda s: s.get("name") == BOOKKEEPING_STEP)
    evidence = _index(steps, lambda s: s.get("name") == EVIDENCE_STEP)
    assert bookkeeping < evidence

    # …and the guard that makes the ordering matter is still the original one,
    # so this test keeps failing if either side of the interaction changes.
    assert steps[bookkeeping]["if"] == "success() && inputs.dry_run != 'true'"


def test_evidence_survives_a_failed_bookkeeping_step(steps):
    """Running last must not mean running only on a clean path."""

    assert _evidence_step(steps)["if"] == "always()"


# ── 3. failed and blocked attempts keep their evidence ───────────────────────

def test_a_failed_or_blocked_attempt_still_preserves_evidence(steps):
    """A blocked preflight or failed publication is evidence, not a discard.

    ``run_report.json`` is written on those paths too (Story #20), so an
    upload gated on success would drop exactly the runs that matter most.
    """

    assert _evidence_step(steps)["if"] == "always()"


def test_preservation_tolerates_a_run_that_produced_nothing(steps):
    """An early stop is a legitimate outcome, not a workflow error."""

    assert _evidence_step(steps)["with"]["if-no-files-found"] in ("warn", "ignore")


# ── 4. the upload cannot widen to secrets or the repository ──────────────────

@pytest.mark.parametrize("forbidden", [".env", "..", "~", "*"])
def test_the_upload_path_cannot_reach_outside_the_run_namespace(steps, forbidden):
    path = _evidence_step(steps)["with"]["path"]
    assert forbidden not in path


def test_the_upload_path_is_not_the_whole_reports_tree(steps):
    path = _evidence_step(steps)["with"]["path"].strip()
    assert path not in ("reports/", "reports", ".", "./")
    assert path.startswith("reports/content_packages/")
    assert path.endswith("/runs/")


# ── 5. secrets stay in the execution step ────────────────────────────────────

def test_the_evidence_step_declares_no_secrets(steps):
    step = _evidence_step(steps)
    assert "env" not in step
    assert "secrets." not in str(step)


def test_live_credentials_still_come_from_github_secrets(steps):
    execution = steps[_index(steps, lambda s: ENTRYPOINT_FRAGMENT in str(s.get("run", "")))]
    env = execution.get("env", {})
    for name in ("NB_WIX_API_KEY", "NB_ZERNIO_API_KEY", "NB_OPENAI_API_KEY"):
        assert name in env, f"{name} must still be supplied to the live run"
        assert "secrets." in str(env[name])


# ── 6. existing behavior is untouched ────────────────────────────────────────

def test_publication_bookkeeping_is_unchanged(steps):
    step = steps[_index(steps, lambda s: s.get("name") == BOOKKEEPING_STEP)]
    assert step["if"] == "success() && inputs.dry_run != 'true'"
    run = step["run"]
    assert "data/research/published_signal_ids.txt" in run
    assert "git push" in run


def test_the_canonical_entrypoint_invocation_is_unchanged(steps):
    execution = steps[_index(steps, lambda s: ENTRYPOINT_FRAGMENT in str(s.get("run", "")))]
    run = execution["run"]
    assert 'python scripts/generate_and_publish.py --signal-id "${{ steps.resolve.outputs.signal_id }}" $FLAGS' in run
    # live unless the caller explicitly asks for a dry run
    assert '[ "${{ inputs.dry_run }}"       = "true" ] && FLAGS="$FLAGS --dry-run"' in run


# ── 6. no production Python is involved in this contract ─────────────────────

def test_the_correction_lives_entirely_in_configuration():
    """The evidence contract is workflow configuration, by design.

    If preserving evidence ever required changing the entrypoint, the run
    would no longer be the canonical production path — which is the one thing
    a Story #21 acceptance run cannot afford.
    """

    import subprocess

    changed = subprocess.run(
        ["git", "diff", "--name-only", "2aabc2fab2539c7e475559175c4ef658b7c6a4d4", "HEAD"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
    )
    if changed.returncode != 0:            # shallow clone or detached CI checkout
        pytest.skip("base commit not available in this checkout")
    files = [f for f in changed.stdout.split() if f]
    production_python = [
        f for f in files
        if f.endswith(".py") and (f.startswith("src/") or f.startswith("scripts/"))
    ]
    assert production_python == [], f"unexpected production change: {production_python}"


# ── the acceptance-execution visual setting ──────────────────────────────────

def test_forced_fresh_visual_is_wired_without_hardcoding_it(steps):
    """Story #21 needs the visual generated by the publish run itself.

    The canonical visual path reuses an ``image_library`` entry when signal
    and design version match, so an acceptance run would otherwise review an
    asset the research run made minutes earlier. The flag is supplied from a
    repository secret rather than a literal, so with the secret unset or
    false the production reuse contract is exactly as before — this is an
    execution setting, never a permanent default.
    """

    execution = steps[_index(steps, lambda s: ENTRYPOINT_FRAGMENT in str(s.get("run", "")))]
    value = execution["env"]["NB_FORCE_REGENERATE_RESEARCH_IMAGES"]
    assert value == "${{ secrets.NB_FORCE_REGENERATE_RESEARCH_IMAGES }}"
    assert "true" not in value.lower()          # never hardcoded on
