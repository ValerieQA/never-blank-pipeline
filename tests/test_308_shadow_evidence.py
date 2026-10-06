"""The canonical shadow run must preserve the evidence #308 is judged on.

Acceptance run 1 (`37460768845`, head `73d10a90`) was non-qualifying twice
over. It stopped at S-04 — and its evidence was destroyed with the runner,
because `canonical_shadow.yml` uploaded nothing. Only the committed summary
survived, and four of #308's acceptance items are statements about the trace,
the manifest and the StageRecords:

* the `PASS_THROUGH_MARKER` count is 0;
* lineage binds one input to specific S-* outputs by **ID and version** through
  the manifest;
* every model-deciding StageRecord carries a `request_digest`;
* the call trace and counters.

None of those can be read from a summary, so three green runs would still have
been `0/3`. These tests hold the repair: the shadow workflow preserves the run
namespace and the early-stop record, and the evidence really lands where the
workflow uploads from.

**What is proved here and what is not.** The absence of a legacy
`generated.json` read cannot be shown by an artifact — no file proves a file
was not opened. It is proved structurally instead, the same way this repository
already proves that no publisher is reachable from the shadow path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "canonical_shadow.yml"

EVIDENCE_STEP = "Preserve canonical run evidence"

#: What the workflow uploads. The run namespace and the early-stop ledger.
RUN_NAMESPACE = "reports/editorial_runs/"
EARLY_STOPS = "data/editorial/early_stops/"


def _steps() -> list[dict]:
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = spec["jobs"]
    assert len(jobs) == 1, f"the shadow workflow has {len(jobs)} jobs; one expected"
    return list(next(iter(jobs.values()))["steps"])


def _evidence_step() -> dict:
    found = [step for step in _steps() if step.get("name") == EVIDENCE_STEP]
    assert len(found) == 1, (
        f"expected exactly one {EVIDENCE_STEP!r} step; got {len(found)}"
    )
    return found[0]


def _paths() -> list[str]:
    raw = _evidence_step()["with"]["path"]
    return [line.strip() for line in str(raw).splitlines() if line.strip()]


# ===========================================================================
# 1 · the upload exists, on every outcome, for long enough
# ===========================================================================


def test_the_shadow_run_uploads_its_evidence() -> None:
    step = _evidence_step()

    assert step["uses"].startswith("actions/upload-artifact@")


def test_the_evidence_is_preserved_on_every_outcome() -> None:
    """`always()` — an early stop and a failure are the evidence that matters.

    Run 1 is the case: it stopped at S-04. An upload gated on success would
    discard exactly the runs #308 has to diagnose.
    """

    condition = str(_evidence_step()["if"])

    assert "always()" in condition
    assert "success()" not in condition
    # And it does not run when the gate refused, where there is no run at all.
    assert "steps.gate.outputs.run == 'true'" in condition


def test_the_evidence_is_kept_for_ninety_days() -> None:
    assert int(_evidence_step()["with"]["retention-days"]) == 90


def test_a_legitimate_early_stop_is_not_turned_into_a_failed_workflow() -> None:
    """`if-no-files-found` must never be `error`.

    A run that reaches S-14 writes **no** early-stop record, so one of the two
    uploaded paths is legitimately empty on a complete run — and a complete run
    is the outcome #308 wants most. `error` would fail it.
    """

    assert _evidence_step()["with"]["if-no-files-found"] in ("warn", "ignore")


# ===========================================================================
# 2 · what it uploads, and why those paths need no run_id
# ===========================================================================


def test_both_halves_of_the_evidence_are_uploaded() -> None:
    paths = _paths()

    assert RUN_NAMESPACE in paths, "the run namespace holds the trace and manifest"
    assert EARLY_STOPS in paths, "the early-stop record holds the terminal reasoning"


def test_the_uploaded_paths_are_untracked_so_only_this_run_is_collected() -> None:
    """Why the paths carry no `run_id`, and why that is still containment.

    `run_id` is generated inside the process and is deliberately never
    reconstructed from a log or a marker file. Uploading the two directories is
    safe instead because both are **untracked**: a clean checkout contains
    neither, so whatever is in them was produced by this run. The run's own
    summary asserts the checkout was clean (`tracked_worktree_clean`).

    If either path ever becomes tracked, this fails — and it should, because the
    upload would then collect files the run did not produce.
    """

    for path in _paths():
        listed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", path],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert listed.returncode != 0, (
            f"{path} is tracked in git, so the upload would collect files this "
            f"run did not produce: {listed.stdout.strip()[:200]}"
        )

    from src.run.run_summary import RunSummary

    assert "code_identity" in RunSummary.model_fields


def test_the_upload_reaches_no_further_than_those_two_trees() -> None:
    """Containment, parsed rather than assumed.

    Each entry is one of the two declared roots exactly — not a parent, not a
    glob, not a traversal. The run namespace must not widen to `reports/`, which
    holds every content package the repository has.
    """

    for path in _paths():
        assert path in (RUN_NAMESPACE, EARLY_STOPS), path
        for forbidden in ("..", "~", "*", "?", "$(", "`", ".env"):
            assert forbidden not in path, (path, forbidden)
        assert path not in ("reports/", "data/", "./", ".")


# ===========================================================================
# 3 · the step cannot publish, mark, or change the run
# ===========================================================================


def test_the_evidence_step_publishes_nothing_and_marks_nothing() -> None:
    """Requirement 6: it preserves evidence and does nothing else.

    One `upload-artifact`, with no script of its own, no environment and no
    secret — so it cannot publish, write a marker, touch bookkeeping or alter
    engine behaviour.
    """

    step = _evidence_step()

    assert "run" not in step
    assert "env" not in step
    assert "secrets." not in str(step)
    for forbidden in ("persist_publication_markers", "publish", "marker"):
        assert forbidden not in str(step).lower(), forbidden


def test_the_evidence_step_cannot_fail_in_front_of_the_run_or_its_commits() -> None:
    """Placed last, and that ordering is the same rule Story #21 holds.

    The run commits its own durable records. An upload standing in front of
    that could fail for an unrelated artifact-service reason and suppress them.
    """

    names = [step.get("name") for step in _steps()]
    run_step = names.index("Run the canonical chain in shadow")
    evidence = names.index(EVIDENCE_STEP)

    assert run_step < evidence
    assert evidence == len(names) - 1, "the evidence upload is the last step"


def test_the_workflow_still_publishes_nothing_at_all() -> None:
    """The repair did not make the shadow path a publisher."""

    text = WORKFLOW.read_text(encoding="utf-8")

    for forbidden in (
        "persist_publication_markers",
        "published_signal_ids",
        "WixPublisher",
        "generate_image",
        "generate_and_publish.py",
    ):
        assert forbidden not in text, forbidden


# ===========================================================================
# 4 · the evidence really lands where the workflow uploads from
# ===========================================================================


class _RefusingEligibility:
    """S-00's judgement, refusing. The verdict schema is two fields and closed.

    Authored so the run stops at S-00 and writes an early-stop record: the
    *shape* run 1 produced at S-04, reached without a provider call.
    """

    name = "eligibility"

    def __init__(self, ledger) -> None:
        self.ledger = ledger

    def answer(self, *, instructions: str, request: str) -> str:
        return json.dumps(
            {
                "eligible": False,
                "reason": "the source is a listicle with no new mechanism.",
            }
        )

    def complete(self, *, instructions: str, request: str) -> str:
        self.ledger.record(self.name, request)
        return self.answer(instructions=instructions, request=request)


def _execute(tmp_path: Path, **kwargs):
    """One canonical run through the production entrypoint, on doubles."""

    from src.run.walking_skeleton import run_golden_engine
    from tests.golden_engine_boundary import canonical_run

    run = canonical_run(tmp_path, **kwargs)
    ledger = tmp_path / "ledger"
    sealed = run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        ledger_dir=ledger,
        started_at=run.now,
        now=run.now,
        model="gpt-6.1-sol",
    )
    return run, sealed, ledger


def test_an_early_stop_writes_its_record_under_the_uploaded_path(
    tmp_path: Path,
) -> None:
    """The early-stop shape, end to end, with no provider call.

    This is run 1's shape: a run that stops before S-14. The record must exist
    under `early_stops/`, which is the second path the workflow uploads — and
    it must carry the terminal reasoning, because that is what run 1 could not
    produce.
    """

    from tests.golden_engine_boundary import Ledger

    run, sealed, ledger = _execute(
        tmp_path, eligibility=_RefusingEligibility(Ledger())
    )

    assert sealed.execution.stopped_at == "S-00"
    assert sealed.early_stop_path is not None

    written = Path(sealed.early_stop_path)
    assert written.is_file()
    # The uploaded path is `data/editorial/early_stops/`; the ledger root is
    # relocated here, so compare the part the workflow's path selects.
    assert "early_stops" in written.relative_to(ledger).parts[0]

    body = json.loads(written.read_text(encoding="utf-8"))
    assert body["stage"] == "S-00"
    assert body["state_code"]
    assert body["model"] == "gpt-6.1-sol"
    assert body.get("rationale") or body.get("rationale_absent_reason")


def test_the_early_stop_run_still_leaves_its_namespace_to_upload(
    tmp_path: Path,
) -> None:
    """A stopped run has a trace too, and that is the point.

    Run 1 stopped at S-04 having made six calls across five stages. Those
    StageRecords are the measurement, and they lived only on the runner.
    """

    from tests.golden_engine_boundary import Ledger

    run, sealed, _ = _execute(
        tmp_path, eligibility=_RefusingEligibility(Ledger())
    )

    workspace = next(Path(run.runs_root).iterdir())

    assert workspace.is_dir()
    records = sorted(workspace.glob("trace/*.json"))
    assert records, "the stopped run wrote no StageRecord to preserve"


def test_a_complete_run_preserves_the_evidence_the_acceptance_items_read(
    tmp_path: Path,
) -> None:
    """And on a complete run, every trace-level acceptance item is readable.

    Each assertion below is one of the items run 1 could not answer. They are
    checked against the files the workflow uploads, so a green acceptance run
    will have the evidence a reviewer needs rather than a summary.
    """

    from src.run.run_workspace import MANIFEST_NAME

    run, sealed, ledger = _execute(tmp_path)

    assert sealed.execution.stopped_at is None
    workspace = next(Path(run.runs_root).iterdir())

    # the manifest, for ID + version lineage
    manifest = workspace / MANIFEST_NAME
    assert manifest.is_file()
    body = json.loads(manifest.read_text(encoding="utf-8"))
    entities = body.get("entities") or body.get("entity_index") or []
    assert entities, "the manifest lists no entity, so lineage is unresolvable"
    assert any("version" in str(item) for item in entities)

    # the StageRecords, for PASS_THROUGH_MARKER and request_digest
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(workspace.glob("trace/*.json"))
    ]
    assert records

    from src.run.walking_skeleton import PASS_THROUGH_MARKER

    pass_through = [
        record for record in records
        if PASS_THROUGH_MARKER in str(record.get("created_by", ""))
    ]
    assert pass_through == [], (
        f"{len(pass_through)} StageRecord(s) name the pass-through marker; "
        "#308 requires a count of 0, and this is where it is counted"
    )
    # Countable at all only because every record carries the attribution.
    assert all(record["created_by"]["component"] for record in records)

    deciding = [
        record for record in records
        if str(record["created_by"].get("decider", "")).lower() == "model"
    ]
    assert deciding, "no model-deciding record in the preserved trace"
    for record in deciding:
        # The **field** is what preservation has to deliver; whether it is
        # filled is a fact about the provider. #308 is explicit that the
        # skeleton's fake provider produces no digest, and this run is driven
        # by doubles on purpose — no provider call is made to test an upload.
        # So the acceptance check "every model-deciding StageRecord carries a
        # request_digest" is answered from this same preserved file on the real
        # run; what is proved here is that the file carries the field to answer
        # it with, which run 1 could not because the file was destroyed.
        assert "request_digest" in record["created_by"], record["stage"]

    # a complete run writes no early stop, which is why `error` is forbidden
    assert sealed.early_stop_path is None
    assert not (ledger / "early_stops").exists()


# ===========================================================================
# 5 · the one thing no artifact can prove
# ===========================================================================


def test_the_canonical_shadow_path_never_reads_legacy_generated_json() -> None:
    """Proved structurally, because absence of a read is not an artifact.

    `generated.json` is E-15's *"current mapping"* and is read by `package.py`,
    `idempotency.py`, `src/artifacts/`, `run_report.py` and `provenance.py`.
    S-14 packaging from it would produce canonical-looking output made by the
    old pipeline — #308 calls this *"the most likely false green"*.

    Asserted the same way this repository already asserts that no publisher is
    reachable from the shadow path: over the source of the entrypoint and the
    stage modules the canonical run can reach.
    """

    from tests.test_308_model_routing_and_rationale import executable_source

    subjects = [
        ROOT / "scripts" / "run_canonical_shadow.py",
        ROOT / "src" / "run" / "walking_skeleton.py",
        ROOT / "src" / "run" / "golden_engine.py",
        ROOT / "src" / "editorial_core" / "publication.py",
    ]
    for path in subjects:
        assert "generated.json" not in executable_source(path), path.name
