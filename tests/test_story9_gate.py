"""
Story #9 acceptance gate — orchestration-level coverage (Issue #30).

These tests exercise the canonical Release 1 entry point ``main()`` directly.
They complement the unit-level contract suites (which are marked ``story9``
in place) by proving the end-to-end behaviour the product owner must verify:

  1. the same assignment executed twice;
  2. two distinct run_ids;
  3. two preserved immutable artifact locations;
  4. one run_id unchanged across every non-live stage boundary;
  5. a mismatched-run package rejected before any external side effect.

Run the full gate with:

    python3 -m pytest -m story9

No production credentials, no network access, no real publishing. External
publishers are faked at the contract boundary; every filesystem write is
redirected into pytest's ``tmp_path``.

Lines prefixed ``STORY9-EVIDENCE:`` are printed so the manual verification
checklist can be filled from a real run (``python3 -m pytest -m story9 -s``).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Shared harness — reused rather than duplicated so the gate cannot drift
# from the fixtures the focused suites already validate.
import test_generate_and_publish as _h

from scripts.generate_and_publish import _build_legacy_research_context, main
from src.lifecycle.signal_lifecycle import ResearchContext
from src.strategy.validators import ValidationResult
from src.visual import VisualArtifactRequest

import scripts.generate_and_publish as _gap_module


_SIGNAL_ID = _h._SIGNAL_ID

# A fixed, valid UUID v4 used where a deterministic run_id is required.
_FIXED_RUN_ID = "7c9e1b2a-3d4f-4a5b-8c6d-9e0f1a2b3c4d"


def _run_dirs(packages_dir: Path) -> list[Path]:
    """Return every run directory recorded for the test signal, sorted."""
    runs_root = packages_dir / _SIGNAL_ID / "runs"
    if not runs_root.exists():
        return []
    return sorted(p for p in runs_root.iterdir() if p.is_dir())


def _evidence(label: str, value: object) -> None:
    print(f"STORY9-EVIDENCE: {label} = {value}")


# ---------------------------------------------------------------------------
# Scenario: same signal, two distinct runs, two preserved artifacts
# ---------------------------------------------------------------------------

@pytest.mark.story9
def test_same_assignment_twice_creates_two_distinct_preserved_runs(tmp_path):
    """
    Execute the canonical entry point twice for one assignment.

    Proves checklist items 1-3: two executions, two distinct run_ids, and two
    independently preserved artifact locations. The first run's generated.json
    must be byte-for-byte unchanged after the second execution completes.
    """
    argv, patches = _h._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path

    # First execution.
    with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
        assert main() == 0

    dirs_after_first = _run_dirs(tmp_path)
    assert len(dirs_after_first) == 1, "first execution must create exactly one run directory"
    first_dir = dirs_after_first[0]
    first_bytes = (first_dir / "generated.json").read_bytes()

    # Second execution — same assignment, same signal, fresh RunContext.
    argv2, patches2 = _h._base_patches(dry_run=True)
    patches2["PACKAGES_DIR"] = tmp_path
    with mock.patch("sys.argv", argv2), mock.patch.multiple(_gap_module, **patches2):
        assert main() == 0

    dirs_after_second = _run_dirs(tmp_path)
    assert len(dirs_after_second) == 2, "second execution must create a second run directory"

    run_ids = []
    for d in dirs_after_second:
        payload = json.loads((d / "generated.json").read_text(encoding="utf-8"))
        # The directory name is the addressing key and must equal the serialized identity.
        assert payload["run_id"] == d.name
        assert payload["signal_id"] == _SIGNAL_ID
        run_ids.append(payload["run_id"])

    # Two distinct run identities.
    assert len(set(run_ids)) == 2, f"expected two distinct run_ids, got {run_ids}"

    # The first artifact was not touched by the second execution.
    assert (first_dir / "generated.json").read_bytes() == first_bytes

    _evidence("run_id_1", run_ids[0])
    _evidence("run_id_2", run_ids[1])
    _evidence("artifact_1", dirs_after_second[0] / "generated.json")
    _evidence("artifact_2", dirs_after_second[1] / "generated.json")


# ---------------------------------------------------------------------------
# Scenario: one run_id across every non-live stage boundary
# ---------------------------------------------------------------------------

@pytest.mark.story9
def test_one_run_id_unchanged_across_all_non_live_boundaries(tmp_path):
    """
    Trace a single known run_id through every non-live stage boundary of one
    canonical dry-run execution.

    Boundaries covered: intake (RunContext) -> ResearchContext ->
    EditorialContext -> VisualArtifactRequest -> ValidationResult ->
    persisted generated.json -> R1RunReport.

    Proves checklist item 4 and the "immutable run ID across every Release 1
    stage boundary" scenario at orchestration level.
    """
    fixed_uuid = uuid.UUID(_FIXED_RUN_ID)

    argv, patches = _h._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    # Spy on the run report instead of swallowing it.
    del patches["_emit_run_report"]

    trace: dict[str, str] = {}

    orig_blrc = _build_legacy_research_context

    def spy_blrc(assignment, raw_signal, run_ctx):
        trace["intake"] = run_ctx.run_id
        rc = orig_blrc(assignment, raw_signal, run_ctx)
        trace["research-context"] = rc.run_id
        return rc

    orig_to_editorial = ResearchContext.to_editorial

    def spy_to_editorial(self, *args, **kwargs):
        ec = orig_to_editorial(self, *args, **kwargs)
        trace["editorial-context"] = ec.run_id
        return ec

    class SpyVisual(VisualArtifactRequest):
        def __init__(self, **kw):
            super().__init__(**kw)
            trace["visual-request"] = self.run_id

    class SpyValidation(ValidationResult):
        def __init__(self, **kw):
            super().__init__(**kw)
            trace["validation-result"] = self.run_id

    def spy_emit(report):
        trace["run-report"] = report.run_id

    with mock.patch("uuid.uuid4", return_value=fixed_uuid), \
         mock.patch("sys.argv", argv), \
         mock.patch.multiple(_gap_module, **patches), \
         mock.patch.object(_gap_module, "_build_legacy_research_context", spy_blrc), \
         mock.patch.object(ResearchContext, "to_editorial", spy_to_editorial), \
         mock.patch.object(_gap_module, "VisualArtifactRequest", SpyVisual), \
         mock.patch.object(_gap_module, "ValidationResult", SpyValidation), \
         mock.patch.object(_gap_module, "_emit_run_report", spy_emit):
        assert main() == 0

    # The persisted artifact is the final non-live boundary.
    dirs = _run_dirs(tmp_path)
    assert len(dirs) == 1
    payload = json.loads((dirs[0] / "generated.json").read_text(encoding="utf-8"))
    trace["generated-json"] = payload["run_id"]
    trace["artifact-path-key"] = dirs[0].name

    expected_boundaries = {
        "intake",
        "research-context",
        "editorial-context",
        "visual-request",
        "validation-result",
        "generated-json",
        "artifact-path-key",
        "run-report",
    }
    missing = expected_boundaries - set(trace)
    assert not missing, f"boundaries never reached: {sorted(missing)}"

    distinct = set(trace.values())
    assert distinct == {_FIXED_RUN_ID}, (
        f"run_id changed across boundaries: {trace}"
    )

    for boundary in sorted(trace):
        _evidence(f"boundary[{boundary}]", trace[boundary])


# ---------------------------------------------------------------------------
# Scenario: mismatched-run package rejected before external side effects
# ---------------------------------------------------------------------------

@pytest.mark.story9
def test_mismatched_source_run_package_rejected_before_side_effects(tmp_path, capsys):
    """
    Address a run-scoped artifact whose serialized run_id does not match the
    requested --source-run-id.

    Proves checklist item 5: the mismatch is rejected before image
    preparation, before any publisher is constructed, before any external
    publish call, and before any new artifact is committed.
    """
    requested_source_run = "11111111-2222-4333-8444-555555555555"
    serialized_run_id = "99999999-8888-4777-8666-555555555555"

    # Artifact lives at runs/<requested_source_run>/ but carries a different
    # run_id inside — a corrupt or relocated package.
    pkg = _h._valid_package(run_id=serialized_run_id)
    artifact = tmp_path / _SIGNAL_ID / "runs" / requested_source_run / "generated.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(pkg), encoding="utf-8")
    artifact_bytes = artifact.read_bytes()

    argv = [
        "prog", "--signal-id", _SIGNAL_ID,
        "--from-package", "--source-run-id", requested_source_run,
    ]
    _, patches = _h._base_patches(dry_run=False, from_package=True)
    patches["PACKAGES_DIR"] = tmp_path

    image_prep = mock.MagicMock(return_value={})
    patches["_load_package_images"] = image_prep

    wix_cls = mock.MagicMock()
    li_cls = mock.MagicMock()

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(_gap_module, **patches), \
         mock.patch.object(_gap_module, "WixPublisher", wix_cls), \
         mock.patch.object(_gap_module, "LinkedInPublisher", li_cls):
        exit_code = main()

    # Fails closed, and specifically because of the identity mismatch — this
    # pins the rejection reason so the test cannot pass for an unrelated error.
    assert exit_code == 1
    stdout = capsys.readouterr().out
    assert "source identity mismatch" in stdout
    assert serialized_run_id in stdout
    assert requested_source_run in stdout

    # No image preparation.
    image_prep.assert_not_called()

    # No publisher constructed, therefore no external call.
    wix_cls.assert_not_called()
    li_cls.assert_not_called()

    # No new artifact committed anywhere under the signal.
    assert list(tmp_path.rglob("publication_results.json")) == []

    # The addressed source artifact is untouched.
    assert artifact.read_bytes() == artifact_bytes

    _evidence("mismatch_requested_source_run_id", requested_source_run)
    _evidence("mismatch_serialized_run_id", serialized_run_id)
    _evidence("mismatch_exit_code", exit_code)
    _evidence("mismatch_publication_results_written", False)
