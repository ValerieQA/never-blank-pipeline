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

from tests.evidence_path_contract import PathContractError, assert_contained
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
def test_every_path_the_upload_can_yield_is_inside_the_run_namespace(workflow):
    """Parsed, not matched — the second review of PR #388.

    ``upload-artifact`` takes a newline-separated **list** of paths, so a value
    can contain ``reports/content_packages/`` and ``/runs/``, contain no
    traversal token, and still upload a second tree on a second line. Substring
    containment is not namespace containment.

    :func:`tests.evidence_path_contract.assert_contained` parses every entry and
    every ``||`` alternative and fails closed on any shape it cannot account
    for. Accepting nothing would also be a failure, so the result is checked to
    be non-empty: a contract that proved an empty path would prove nothing.
    """

    accepted = assert_contained(_path(workflow), where=f"{workflow} evidence path")

    assert accepted.total >= 1


@pytest.mark.parametrize(
    "widening",
    [
        pytest.param(
            "reports/content_packages/${{ steps.publish.outputs.signal_id }}/runs/\nreports/",
            id="a-second-tree-on-a-second-line",
        ),
        pytest.param(
            "reports/content_packages/${{ steps.a.outputs.s }}/runs/\n"
            "reports/content_packages/other/runs/",
            id="a-sibling-signals-namespace",
        ),
        pytest.param("reports/content_packages/other/runs/", id="a-hardcoded-signal-id"),
        pytest.param("reports/content_packages/", id="the-whole-packages-root"),
        pytest.param("reports/content_packages/*/runs/", id="a-glob-over-every-signal"),
        pytest.param("reports/content_packages/../../etc/runs/", id="traversal"),
        pytest.param("reports/content_packages/$(whoami)/runs/", id="command-substitution"),
        pytest.param(
            "reports/content_packages/${{ steps.a.outputs.s }}/runs/\n.env",
            id="a-dotfile-beside-it",
        ),
        pytest.param("${{ steps.publish.outputs.whatever }}", id="an-unproven-step-output"),
        pytest.param(
            "${{ steps.publish.outputs.whatever || "
            "format('reports/content_packages/{0}/runs/', steps.r.outputs.s) }}",
            id="an-unproven-output-behind-a-good-fallback",
        ),
        pytest.param(
            "${{ format('reports/{0}/runs/', steps.r.outputs.s) }}",
            id="a-format-template-outside-the-namespace",
        ),
        pytest.param("${{ github.workspace }}", id="an-unrecognised-expression"),
        pytest.param(
            "${{ format('reports/content_packages/{0}/runs/', steps.r.outputs.s) }}/../..",
            id="an-expression-with-a-trailing-literal",
        ),
        pytest.param("\n  \n", id="nothing-at-all"),
    ],
)
def test_the_contract_rejects_a_widened_upload_path(widening):
    """Testing the test: a contract nobody tried to break proves nothing.

    Each case here would have passed the lexical check this replaced. The
    sibling-namespace one is why a literal signal id is refused outright: it is
    canonical in shape while naming a signal the run never attempted, so the
    segment has to be derived from the run.
    """

    with pytest.raises(PathContractError):
        assert_contained(widening, where="widening probe")


def test_the_evidence_emitter_builds_only_canonical_entries(tmp_path, monkeypatch):
    """The one alternative a workflow cannot state is proved beside its emitter.

    Monday's path falls back to ``steps.publish.outputs.evidence_paths``, whose
    value no workflow states — so the contract accepts that alternative only
    because of this test. ``run_first_valid`` emits, per attempted candidate,
    its run namespace and its generated package: both under
    ``reports/content_packages/``, both keyed by the signal id.

    **The limit, stated rather than implied:** the emitter interpolates the
    signal id without a charset guard, so an id containing ``..`` would escape.
    Guarding it is a change to production code, which this slice may not make;
    the finding is reported on #326. What is proved here is the shape for a
    well-formed id, which is the guarantee that exists today.
    """

    from scripts.streams import run_first_valid

    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("NB_PACKAGES_DIR", "reports/content_packages")

    run_first_valid._emit_evidence_paths(["sig-a", "sig-b"])

    body = output.read_text().split("evidence_paths<<__NB_EVIDENCE__\n", 1)[1]
    lines = body.split("\n__NB_EVIDENCE__\n", 1)[0].splitlines()

    assert lines == [
        "reports/content_packages/sig-a/runs/",
        "reports/content_packages/sig-a_generated.json",
        "reports/content_packages/sig-b/runs/",
        "reports/content_packages/sig-b_generated.json",
    ]
    # Every line the emitter produced is an entry the contract accepts, with the
    # id standing where the workflow's expression would put it.
    for line in lines:
        rebuilt = line.replace("sig-a", "${{ s }}").replace("sig-b", "${{ s }}")
        assert assert_contained(rebuilt, where=f"emitted {line}").total == 1


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
