"""Every hosted publishing path must preserve its own evidence (Story #21).

A hosted runner can publish to Wix and LinkedIn for real and then be destroyed
along with the canonical run namespace — leaving a genuine publication that
cannot be verified by Story #16 provenance, Story #20 reporting, or Story #21
closure. That is the failure mode these tests exist to prevent: they hold the
evidence-preservation contract, not any workflow's publishing behavior.

**Subject (#326).** These invariants used to be pinned to
``research_generate_and_publish.yml``, which is now deleted. They were never
that workflow's invariants: they belong to any workflow that runs the canonical
entrypoint and can therefore publish. So each test below is parametrized over
:func:`tests.publishing_workflows.publishing_workflows`, which derives that set
from the workflows themselves — and a new publishing workflow inherits all of
it on the day it is written.

Two assertions were **not** carried over, because their subject really was the
deleted file rather than a safety property:

* the exact legacy invocation line (``$FLAGS`` assembly and its dry-run flag
  construction). Each surviving workflow builds its own invocation — Monday
  passes ``--editorial-role``, Wednesday passes its own retry arguments — so a
  single expected command line would be a statement about one workflow's shell,
  not about publication safety. Membership in the parametrized set already
  proves each one invokes the canonical entrypoint;
* the exact legacy ``if`` string on bookkeeping. The survivors add their own
  window and signal guards, so the property preserved below is what the guard
  must *achieve* — bookkeeping runs only on success, and never on a dry run —
  rather than one literal expression.

They are configuration contract tests. No production Python is involved, which
is itself part of the contract: the run directory layout is owned by
``resolve_run_dir``, and a workflow must follow it rather than invent a second
source of truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.publishing_workflows import (
    ENTRYPOINT,
    entrypoint_step,
    job_steps,
    named,
    publishing_workflows,
    step_index,
)

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_STEP = "Preserve canonical run evidence"
BOOKKEEPING_STEP = "Mark signal as published"

#: Every workflow that can publish. Collected once: a failure to derive it is a
#: failure of the module, not a quiet empty parametrization.
WORKFLOWS = publishing_workflows()


def _evidence(workflow: str) -> dict:
    return named(job_steps(workflow), EVIDENCE_STEP)


def _path(workflow: str) -> str:
    return str(_evidence(workflow)["with"]["path"])


# ── 1. the canonical run namespace is preserved ──────────────────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_canonical_run_namespace_is_uploaded(workflow):
    step = _evidence(workflow)

    assert step["uses"].startswith("actions/upload-artifact@")
    assert "reports/content_packages/" in _path(workflow)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_uploaded_path_follows_the_production_run_layout(workflow):
    """The workflow follows ``resolve_run_dir``; it does not redefine it.

    Asserted as containment rather than as one expected string: a path may be a
    GitHub expression with a fallback — Monday's is — so what has to hold is
    that every literal in it names the layout production writes, not that the
    whole value is a literal.
    """

    from src.artifacts import resolve_run_dir

    produced = resolve_run_dir(Path("reports/content_packages"), "SIG", "RUN")
    assert produced == Path("reports/content_packages/SIG/runs/RUN")

    path = _path(workflow)
    assert "reports/content_packages/" in path
    assert "/runs/" in path


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_run_id_is_not_reconstructed_from_a_second_source(workflow):
    """``run_id`` is generated inside the process and never guessed outside it."""

    step = _evidence(workflow)

    assert "run_id" not in _path(workflow).lower()
    assert "grep" not in str(step) and "sed" not in str(step)


# ── 2. preservation happens after the live attempt ───────────────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_evidence_is_preserved_after_the_canonical_entrypoint_runs(workflow):
    steps = job_steps(workflow)
    entrypoint = step_index(steps, lambda s: ENTRYPOINT in str(s.get("run", "")))
    evidence = step_index(steps, lambda s: s.get("name") == EVIDENCE_STEP)

    assert evidence > entrypoint >= 0


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_canonical_run_precedes_publication_bookkeeping(workflow):
    steps = job_steps(workflow)
    entrypoint = step_index(steps, lambda s: ENTRYPOINT in str(s.get("run", "")))
    bookkeeping = step_index(steps, lambda s: s.get("name") == BOOKKEEPING_STEP)

    assert 0 <= entrypoint < bookkeeping


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_evidence_preservation_cannot_suppress_publication_bookkeeping(workflow):
    """Ordering, not decoration — this is why the evidence step comes last.

    ``Mark signal as published`` is guarded by ``success()``. An evidence
    upload standing in front of it could fail for an unrelated
    artifact-service reason, turn ``success()`` false, and silently skip the
    record of a publication that really happened — leaving a later run free to
    treat an already-published signal as unconsumed. Evidence may never veto
    bookkeeping.
    """

    steps = job_steps(workflow)
    bookkeeping = step_index(steps, lambda s: s.get("name") == BOOKKEEPING_STEP)
    evidence = step_index(steps, lambda s: s.get("name") == EVIDENCE_STEP)

    assert 0 <= bookkeeping < evidence

    # …and the guard that makes the ordering matter is still the one that makes
    # it matter, so this keeps failing if either side of the interaction changes.
    guard = steps[bookkeeping]["if"]
    assert "success()" in guard
    assert "dry_run != 'true'" in guard


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_evidence_survives_a_failed_bookkeeping_step(workflow):
    """Running last must not mean running only on a clean path.

    One assertion covers both reasons the legacy file stated separately: a
    failed bookkeeping step, and a blocked or failed publication. Story #20
    writes ``run_report.json`` on those paths too, so an upload gated on
    success would discard exactly the runs that matter most.
    """

    assert "always()" in _evidence(workflow)["if"]


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_preservation_tolerates_a_run_that_produced_nothing(workflow):
    """An early stop is a legitimate outcome, not a workflow error."""

    assert _evidence(workflow)["with"]["if-no-files-found"] in ("warn", "ignore")


# ── 3. the upload cannot widen to secrets or the repository ──────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("forbidden", [".env", "..", "~", "*"])
def test_the_upload_path_cannot_reach_outside_the_run_namespace(workflow, forbidden):
    assert forbidden not in _path(workflow)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_upload_path_is_not_the_whole_reports_tree(workflow):
    path = _path(workflow).strip()

    assert path not in ("reports/", "reports", ".", "./")
    assert "reports/content_packages/" in path


# ── 4. secrets stay in the execution step ────────────────────────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_evidence_step_declares_no_secrets(workflow):
    step = _evidence(workflow)

    assert "env" not in step
    assert "secrets." not in str(step)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_live_credentials_still_come_from_github_secrets(workflow):
    """The credentials every publishing path needs, from secrets, never literals.

    Only the three the R1 surfaces cannot publish without — the model key, Wix
    and LinkedIn. Which *further* credentials a path needs is that path's own
    business and is held by
    :mod:`tests.test_canonical_publish_credentials`.
    """

    env = entrypoint_step(job_steps(workflow)).get("env", {})

    for name in ("NB_OPENAI_API_KEY", "NB_WIX_API_KEY", "NB_ZERNIO_API_KEY"):
        assert name in env, f"{workflow}: {name} must be supplied to the live run"
        assert "secrets." in str(env[name]), f"{workflow}: {name} is not a secret"


# ── 5. bookkeeping still records the publication ─────────────────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_publication_bookkeeping_still_records_consumption(workflow):
    step = named(job_steps(workflow), BOOKKEEPING_STEP)
    run = str(step["run"])

    assert "data/research/published_signal_ids.txt" in run
    assert "git push" in run


# ── 6. no production Python is involved in this contract ─────────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_evidence_contract_needs_no_production_code(workflow):
    """Evidence preservation is workflow configuration, by design.

    If preserving evidence ever required changing the entrypoint, the
    acceptance run would no longer be the canonical production path — the one
    thing Story #21 cannot afford. Asserted structurally rather than by
    diffing against a fixed base commit, which would have broken on every
    later, unrelated production change.
    """

    entrypoint = (ROOT / "scripts" / "generate_and_publish.py").read_text()
    for artifact_concern in ("upload-artifact", "actions/upload", "GITHUB_OUTPUT"):
        assert artifact_concern not in entrypoint

    step = _evidence(workflow)
    assert "run" not in step  # no script of its own
    assert step["uses"].startswith("actions/upload-artifact@")
