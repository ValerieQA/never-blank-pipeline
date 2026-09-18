"""Monday pre-live repair: a genuinely text-only dry run, and first valid wins
through the pre-generation editorial gate.

Before the owner-authorized controlled text-only run, two defects made it
neither text-only nor faithful to #240 D8:

1. ``dry_run=true`` still generated and uploaded images (OpenAI Images +
   Cloudinary) before its dry-run exit.
2. A candidate that passed selection and was then rejected by the Pattern
   Extractor — the pre-generation editorial suitability gate — ended the whole
   Monday run, so the next valid candidate in queue order was never tried.

And, as a temporary safety control, Monday's schedule is paused until the
controlled proof completes and the owner re-authorizes it (pinned in
tests/test_scheduling_window.py).

No network, no model, no publication.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import EXIT_EDITORIALLY_UNSUITABLE, main
from scripts.streams import run_first_valid, select_eligible_signal
from src.artifacts.provenance import verify_run_provenance
from src.editorial.pattern_extractor import SignalRejectedError
from src.editorial.pipeline import ArticleGenerationError
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_monday_stream import MONDAY_ROLE, PolicyTransport, _attributed_article
from tests.test_research_artifact_lifecycle import ReadyProvider

WORKFLOW = Path(".github/workflows/monday_publish.yml")
SIG = legacy._SIGNAL_ID


def _no_image_work():
    """Every image-generation and image-upload seam explodes if reached."""
    boom = AssertionError("image generation or upload was reached on a dry run")
    return (
        mock.patch("scripts.research.prepare_content.prepare_content_packages",
                   side_effect=boom),
        mock.patch("src.publishing.image_pipeline._generate_ai_image", side_effect=boom),
        mock.patch("src.publishing.image_pipeline.upload_to_cloudinary", side_effect=boom),
        mock.patch("src.publishing.image_pipeline.run_image_pipeline", side_effect=boom),
    )


def _dry_run(tmp_path, *, package_images):
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    patches["generate_article"] = mock.MagicMock(return_value=_attributed_article())
    patches["_load_package_images"] = mock.MagicMock(return_value=package_images)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output())
    guards = _no_image_work()
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            guards[0], guards[1], guards[2], guards[3]:
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


# ===========================================================================
# 1. A dry run makes zero image-generation and zero upload calls
# ===========================================================================


@pytest.mark.parametrize("package_images", [
    {},                                                        # no image at all
    {"blog": {"url": "https://cdn.example/old.png"}, "_design_version": "stale"},
], ids=["no-package-image", "stale-package-image"])
def test_a_dry_run_generates_and_uploads_no_image(tmp_path, package_images):
    code, patches = _dry_run(tmp_path, package_images=package_images)

    assert code == 0
    # text generation still ran, and its text artifact exists
    assert patches["generate_article"].called
    generated = list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))
    assert len(generated) == 1
    assert json.loads(generated[0].read_text())["blog_article"].strip()
    # text-only: no visual passport, and the visual gate was never asked
    assert not list(tmp_path.glob(f"{SIG}/runs/*/visual_assets.json"))
    assert not patches["build_visual_assets_record"].called


def test_a_text_only_dry_run_still_proves_its_provenance_chain(tmp_path):
    """The run report depends on it: a text-only run is a complete chain."""
    from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body

    argv, patches = _entry_patches(tmp_path)
    del patches["build_visual_assets_record"]        # real visual gate
    del patches["write_visual_assets_json"]
    del patches["accept_linkedin_composition"]       # real LinkedIn gate
    del patches["write_linkedin_composition_json"]
    patches["_load_package_images"] = mock.MagicMock(return_value={})
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = ARTICLE_BODY
    article["platforms"]["medium"]["body"] = _native_linkedin_body()
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    guards = _no_image_work()
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            guards[0], guards[1], guards[2], guards[3]:
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    assert code == 0
    run_id = next(tmp_path.glob(f"{SIG}/runs/*/generated.json")).parent.name

    report = verify_run_provenance(tmp_path, SIG, run_id)

    assert report.stopped_after == "generated"
    assert "visual_assets" not in report.verified_artifacts


def test_a_dry_run_publishes_nothing_and_consumes_nothing(tmp_path):
    code, patches = _dry_run(tmp_path, package_images={})

    assert code == 0
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob(f"{SIG}/runs/*/publication_results.json"))


def test_a_publishing_run_still_requires_its_visual():
    """The repair is scoped to dry runs: the live visual gate is untouched."""
    source = Path("scripts/generate_and_publish.py").read_text()

    assert "text_only_dry_run = bool(args.dry_run and needs_regen)" in source
    assert "if text_only_dry_run:" in source
    assert "visual gate blocked publication" in source


# ===========================================================================
# 2. The entrypoint distinguishes "editorially unsuitable" from failure
# ===========================================================================


def _generation_raising(tmp_path, exc, *, dry_run=True):
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    patches["generate_article"] = mock.MagicMock(side_effect=exc)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_pattern_extractor_rejection_is_editorially_unsuitable(tmp_path, dry_run):
    rejection = ArticleGenerationError(
        stage="pattern_extractor",
        original=SignalRejectedError("no owner-centered mechanism"),
    )
    code, patches = _generation_raising(tmp_path, rejection, dry_run=dry_run)

    assert code == EXIT_EDITORIALLY_UNSUITABLE == run_first_valid.EDITORIALLY_UNSUITABLE
    records = list(tmp_path.glob(f"{SIG}/runs/*/editorial_rejection.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text()) == {
        "signal_id": SIG, "stage": "pattern_extractor",
        "reason": str(rejection.original),
    }
    # nothing downstream, nothing published, nothing consumed
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called


@pytest.mark.parametrize("exc", [
    ArticleGenerationError(stage="pattern_extractor", original=ValueError("bad schema")),
    ArticleGenerationError(stage="discovery", original=ValueError("bad schema")),
], ids=["pattern-extractor-schema-failure", "later-stage-failure"])
def test_every_other_generation_failure_still_fails_the_run(tmp_path, exc):
    """Only a genuine suitability rejection means "try the next candidate"."""
    code, _ = _generation_raising(tmp_path, exc)

    assert code == 1
    assert not list(tmp_path.glob(f"{SIG}/runs/*/editorial_rejection.json"))


# ===========================================================================
# 3. First valid wins through generation — the driver, end to end
# ===========================================================================


def _signal(signal_id: str) -> dict:
    return {**legacy._RAW_SIGNAL, "SIGNAL_ID": signal_id,
            "HEADLINE": f"Headline {signal_id}"}


class InProcessRunner:
    """Runs the driver's children in process: the REAL selector (scripted
    judgments) and the REAL canonical entrypoint (fake providers)."""

    def __init__(self, tmp_path, *, verdicts, unsuitable, queue):
        self.tmp_path = tmp_path
        self.verdicts = verdicts
        self.unsuitable = set(unsuitable)
        self.active = tmp_path / "signals_active.jsonl"
        self.active.write_text("".join(json.dumps(_signal(s)) + "\n" for s in queue))
        self.published = tmp_path / "published_signal_ids.txt"
        self.published.write_text("")
        self.packages = tmp_path / "packages"
        self.transport = PolicyTransport(verdicts)
        self.calls: list[list[str]] = []
        self.generated: list[str] = []
        self.patches: list[dict] = []

    def select(self, extra: list[str]) -> int:
        return select_eligible_signal.main(
            ["--active-path", str(self.active),
             "--published-path", str(self.published), *extra],
            transport=self.transport,
        )

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        if argv[0].endswith("select_eligible_signal.py"):
            return self.select(argv[1:])
        assert argv[0].endswith("generate_and_publish.py")
        signal_id = argv[argv.index("--signal-id") + 1]
        _, patches = _entry_patches(self.packages)
        patches["_load_signal"] = mock.MagicMock(return_value=_signal(signal_id))

        def generate(*args, **kwargs):
            if signal_id in self.unsuitable:
                raise ArticleGenerationError(
                    stage="pattern_extractor",
                    original=SignalRejectedError(f"{signal_id}: forced connection"),
                )
            self.generated.append(signal_id)
            return _attributed_article()

        patches["generate_article"] = mock.MagicMock(side_effect=generate)
        patches["WixPublisher"] = mock.MagicMock()
        patches["LinkedInPublisher"] = mock.MagicMock()
        self.patches.append(patches)
        evaluator, _ = _evaluator(_model_output())
        with mock.patch.object(sys, "argv", ["prog", *argv[1:]]), \
                mock.patch.multiple(gap, **patches):
            return main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    def rejections(self, signal_id):
        return [json.loads(p.read_text()) for p in
                sorted(self.packages.glob(f"{signal_id}/runs/*/editorial_rejection.json"))]


def _drive(tmp_path, *, queue, verdicts, unsuitable, dry_run=True, monkeypatch):
    runner = InProcessRunner(tmp_path, verdicts=verdicts, unsuitable=unsuitable, queue=queue)
    audit_dir = tmp_path / "stream_selection"
    audit_dir.mkdir()
    first_audit = audit_dir / "monday_selection.json"
    assert runner.select(["--editorial-role", MONDAY_ROLE,
                          "--audit-out", str(first_audit)]) == 0
    first = json.loads(first_audit.read_text())["selected_signal_id"]
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    argv = ["--editorial-role", MONDAY_ROLE, "--first-signal-id", first,
            "--selection-audit", str(first_audit), "--audit-dir", str(audit_dir)]
    if dry_run:
        argv.append("--dry-run")
    with mock.patch.object(run_first_valid, "_rejection_records",
                           side_effect=runner.rejections):
        code = run_first_valid.main(argv, run=runner)
    record = json.loads((audit_dir / "first_valid_attempts.json").read_text())
    return code, runner, record, output.read_text()


def test_a_candidate_rejected_by_pattern_extraction_does_not_end_the_run(
    tmp_path, monkeypatch,
):
    # queue order: an ineligible one, then two that pass selection — the first
    # of which the Pattern Extractor rejects
    code, runner, record, output = _drive(
        tmp_path, monkeypatch=monkeypatch,
        queue=("sig-ineligible", "sig-unsuitable", "sig-valid"),
        verdicts={"sig-ineligible": (False, "no practical angle"),
                  "sig-unsuitable": (True, "looks useful"),
                  "sig-valid": (True, "useful")},
        unsuitable={"sig-unsuitable"},
    )

    assert code == 0
    # the next valid candidate went through text generation
    assert runner.generated == ["sig-valid"]
    assert list(runner.packages.glob("sig-valid/runs/*/generated.json"))
    # and it is the run's outcome, for bookkeeping to follow
    assert output.strip().splitlines()[-1] == "signal_id=sig-valid"
    assert record["outcome"] == "selected"
    assert record["selected_signal_id"] == "sig-valid"
    assert [(a["signal_id"], a["outcome"]) for a in record["attempts"]] == [
        ("sig-unsuitable", "editorially_unsuitable"), ("sig-valid", "completed"),
    ]
    # the rejection's own reason is kept with the attempt
    assert record["attempts"][0]["rejection"][0]["reason"].endswith(
        "sig-unsuitable: forced connection"
    )


def test_reselection_resumes_in_queue_order_and_never_rejudges(tmp_path, monkeypatch):
    code, runner, _, _ = _drive(
        tmp_path, monkeypatch=monkeypatch,
        queue=("sig-ineligible", "sig-unsuitable", "sig-valid"),
        verdicts={"sig-ineligible": (False, "no practical angle"),
                  "sig-unsuitable": (True, "looks useful"),
                  "sig-valid": (True, "useful")},
        unsuitable={"sig-unsuitable"},
    )

    assert code == 0
    judged = [r["source_case"]["SIGNAL_ID"] for r in runner.transport.requests]
    # first selection judged two; the re-selection judged only what was left
    assert judged == ["sig-ineligible", "sig-unsuitable", "sig-valid"]
    reselect = next(c for c in runner.calls if c[0].endswith("select_eligible_signal.py"))
    excluded = Path(reselect[reselect.index("--exclude-path") + 1]).read_text().split()
    assert excluded == ["sig-ineligible", "sig-unsuitable"]


def test_a_dry_run_driver_publishes_nothing_and_consumes_nothing(tmp_path, monkeypatch):
    code, runner, record, _ = _drive(
        tmp_path, monkeypatch=monkeypatch,
        queue=("sig-unsuitable", "sig-valid"),
        verdicts={"sig-unsuitable": (True, "looks useful"), "sig-valid": (True, "useful")},
        unsuitable={"sig-unsuitable"},
    )

    assert code == 0 and record["dry_run"] is True
    for call in runner.calls:
        if call[0].endswith("generate_and_publish.py"):
            assert "--dry-run" in call
    for patches in runner.patches:
        assert not patches["WixPublisher"].called
        assert not patches["LinkedInPublisher"].called
        assert not patches["append_published_entry"].called
    # neither the rejected nor the completed signal was consumed
    assert runner.published.read_text() == ""
    assert not list(runner.packages.glob("*/runs/*/publication_results.json"))


def test_when_every_candidate_is_unsuitable_the_run_ends_clean_and_empty(
    tmp_path, monkeypatch,
):
    code, runner, record, output = _drive(
        tmp_path, monkeypatch=monkeypatch,
        queue=("sig-a", "sig-b"),
        verdicts={"sig-a": (True, "looks useful"), "sig-b": (True, "looks useful")},
        unsuitable={"sig-a", "sig-b"},
    )

    assert code == 0
    assert runner.generated == []
    assert record["outcome"] == "no_usable_candidate"
    assert record["selected_signal_id"] is None
    assert output.strip().splitlines()[-1] == "signal_id="
    assert runner.published.read_text() == ""


# ===========================================================================
# The driver's own contract (scripted children)
# ===========================================================================


class ScriptedRunner:
    def __init__(self, generate_codes: dict, selections: list[tuple[int, str | None]]):
        self.generate_codes = generate_codes
        self.selections = list(selections)
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[0].endswith("select_eligible_signal.py"):
            code, selected = self.selections.pop(0)
            out = Path(argv[argv.index("--audit-out") + 1])
            out.write_text(json.dumps({"selected_signal_id": selected, "dispositions": []}))
            return code
        return self.generate_codes[argv[argv.index("--signal-id") + 1]]


def _scripted(tmp_path, runner, first="sig-1"):
    return run_first_valid.main(
        ["--editorial-role", MONDAY_ROLE, "--first-signal-id", first,
         "--audit-dir", str(tmp_path)], run=runner,
    )


def test_any_other_failure_ends_the_run_without_trying_another_candidate(tmp_path):
    runner = ScriptedRunner({"sig-1": 1}, [])

    assert _scripted(tmp_path, runner) == 1
    assert len(runner.calls) == 1              # no re-selection
    record = json.loads((tmp_path / "first_valid_attempts.json").read_text())
    assert record["outcome"] == "failed" and record["selected_signal_id"] is None


def test_a_failed_reselection_is_never_a_quiet_empty_run(tmp_path):
    runner = ScriptedRunner({"sig-1": 6}, [(select_eligible_signal.ELIGIBILITY_FAILURE, None)])

    assert _scripted(tmp_path, runner) == select_eligible_signal.ELIGIBILITY_FAILURE


def test_the_driver_never_writes_the_consumption_marker():
    source = Path("scripts/streams/run_first_valid.py").read_text()

    assert "published_signal_ids" not in source
    assert "append_published_entry" not in source


# ===========================================================================
# Workflow wiring
# ===========================================================================


def _steps() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text())
    return {s.get("name"): s for s in data["jobs"]["monday-publish"]["steps"]}


def _generate_step() -> dict:
    return next(s for n, s in _steps().items() if n and "Generate + Publish" in n)


def test_an_automatic_run_goes_through_the_first_valid_driver():
    step = _generate_step()
    run = step["run"]

    assert step["id"] == "publish"
    assert 'if [ -z "$SOURCE_RUN_ID" ] && [ -z "$EXPLICIT_SIGNAL_ID" ]; then' in run
    assert "scripts/streams/run_first_valid.py" in run
    assert "--selection-audit reports/stream_selection/monday_selection.json" in run
    assert 'DRIVER_FLAGS="--dry-run"' in run
    # an explicitly chosen signal, or a retry, is never substituted
    assert 'echo "signal_id=$SELECTED_SIGNAL_ID" >> "$GITHUB_OUTPUT"' in run
    assert step["env"]["EXPLICIT_SIGNAL_ID"] == "${{ inputs.signal_id }}"


def test_only_the_candidate_that_completed_is_marked_and_never_on_a_dry_run():
    step = _steps()["Mark signal as published"]

    assert "steps.publish.outputs.signal_id != ''" in step["if"]
    assert "inputs.dry_run != 'true'" in step["if"]
    assert "success()" in step["if"]
    assert "steps.publish.outputs.signal_id }}\" >> data/research/published_signal_ids.txt" in (
        step["run"]
    )
    assert "steps.resolve.outputs.signal_id" not in step["run"]


def test_every_attempt_is_preserved_as_evidence():
    step = _steps()["Preserve first-valid attempts"]

    assert "always()" in step["if"]
    assert "reports/stream_selection/first_valid_attempts.json" in step["with"]["path"]


def test_the_dry_run_input_still_exists():
    inputs = yaml.safe_load(WORKFLOW.read_text())[True]["workflow_dispatch"]["inputs"]

    assert inputs["dry_run"]["options"] == ["false", "true"]
    assert inputs["dry_run"]["default"] == "false"


# ===========================================================================
# Review round 1 (#257)
# ===========================================================================


def test_a_dry_run_chain_claiming_a_publication_still_needs_its_visual(tmp_path):
    """Visuals are optional only for a dry run that published nothing."""
    from src.artifacts.provenance import ProvenanceError
    from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body

    argv, patches = _entry_patches(tmp_path)
    del patches["accept_linkedin_composition"]
    del patches["write_linkedin_composition_json"]
    patches["_load_package_images"] = mock.MagicMock(return_value={})
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = ARTICLE_BODY
    article["platforms"]["medium"]["body"] = _native_linkedin_body()
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0
    run_dir = next(tmp_path.glob(f"{SIG}/runs/*/generated.json")).parent
    run_id = run_dir.name
    configuration = json.loads((run_dir / "assignment.json").read_text())[
        "configuration_identity"]
    (run_dir / "publication_results.json").write_text(json.dumps({
        "run_id": run_id, "signal_id": SIG, "source_run_id": run_id,
        "generation_run_id": run_id, "execution_mode": "controlled_live",
        "results": {}, "completed": True, "configuration_identity": configuration,
    }))

    with pytest.raises(ProvenanceError, match="visual"):
        verify_run_provenance(tmp_path, SIG, run_id)


def _evidence_paths(output: str) -> list[str]:
    block = output.split("evidence_paths<<__NB_EVIDENCE__\n", 1)[1]
    return block.split("\n__NB_EVIDENCE__\n", 1)[0].splitlines()


def test_a_failure_after_a_passed_over_candidate_keeps_both_candidates_evidence(
    tmp_path, monkeypatch,
):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("NB_PACKAGES_DIR", "reports/content_packages")
    runner = ScriptedRunner({"sig-1": 6, "sig-2": 1}, [(0, "sig-2")])

    assert _scripted(tmp_path, runner) == 1

    text = output.read_text()
    assert "signal_id=\n" in text                       # nothing to mark
    assert _evidence_paths(text) == [
        "reports/content_packages/sig-1/runs/",
        "reports/content_packages/sig-1_generated.json",
        "reports/content_packages/sig-2/runs/",
        "reports/content_packages/sig-2_generated.json",
    ]


def test_the_evidence_upload_follows_every_attempt_not_only_the_winner():
    path = _steps()["Preserve canonical run evidence"]["with"]["path"]

    assert "steps.publish.outputs.evidence_paths" in path
    assert "steps.resolve.outputs.signal_id" in path     # the explicit/retry path


def test_a_dry_run_visual_passport_still_needs_its_upstream_chain(tmp_path):
    """Review round 2: optional means "may be absent", never "unchecked"."""
    from src.artifacts.provenance import ProvenanceError
    from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body
    from tests.test_visual_contract import _pimgs

    argv, patches = _entry_patches(tmp_path)
    del patches["build_visual_assets_record"]
    del patches["write_visual_assets_json"]
    del patches["accept_linkedin_composition"]
    del patches["write_linkedin_composition_json"]
    patches["_load_package_images"] = mock.MagicMock(return_value=_pimgs(tmp_path))
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = ARTICLE_BODY
    article["platforms"]["medium"]["body"] = _native_linkedin_body()
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0
    run_dir = next(tmp_path.glob(f"{SIG}/runs/*/visual_assets.json")).parent
    # a dry run with current package images keeps its (verified) passport
    assert "visual_assets" in verify_run_provenance(
        tmp_path, SIG, run_dir.name).verified_artifacts

    # strip the chain down to its anchor plus the passport
    keep = {"assignment.json", "business_strategy.json", "visual_assets.json"}
    for path in run_dir.glob("*.json"):
        if path.name not in keep:
            path.unlink()

    with pytest.raises(ProvenanceError, match="visual_assets exists although"):
        verify_run_provenance(tmp_path, SIG, run_dir.name)
