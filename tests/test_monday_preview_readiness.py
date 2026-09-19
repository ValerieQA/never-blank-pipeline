"""Monday preview readiness: the defects the successful live text proof exposed,
the canonical headline, and the owner-controlled fresh-image preview.

Controlled live run 35383199073 completed its text path and showed:

1. two source sections in the Wix article — the canonical ``Sources`` section
   the composer wrote from the run's source record, and a system-appended
   ``## Source`` footer naming the signal's SOURCE_NAME ("HubSpot Marketing
   Blog"), a publisher the source record does not hold;
2. hashtag fragments (``#WhenPotentialCustomers``, ``#Fewer``) and an
   automatic ``#CompoundPresence`` (tests/test_hashtags.py);
3. a title that reached ``generated.json`` only as ``headline``, a field that
   silently falls back to the signal's own headline.

Product Owner decision: every content surface carries the same accepted
canonical headline; no social composer invents its own.

And the next owner-controlled preview must exercise a FRESH image — generated,
uploaded and gated — while still publishing nothing and consuming nothing.

No network, no model.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import _lead_with_canonical_title, main
from scripts.streams import run_first_valid
from src.artifacts.provenance import verify_run_provenance
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_monday_stream import MONDAY_ROLE, _attributed_article
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_visual_contract import _pimgs

SIG = legacy._SIGNAL_ID
TITLE = "Why Fewer Clicks on Your Ad Could Mean More Sales for Your Business"
WORKFLOW = Path(".github/workflows/monday_publish.yml")


def _article(title: str | None = TITLE) -> dict:
    article = copy.deepcopy(_attributed_article())
    if title is not None:
        article["platforms"]["long"]["title"] = title
    # the preview composes Facebook too, and it must pass source transparency
    article["platforms"]["reading"]["body"] = article["platforms"]["long"]["body"]
    return article


def _run(tmp_path, *, argv_extra=(), title=TITLE, package_images=None,
         real_formatting=True, images=None):
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, *argv_extra]
    if real_formatting:
        patches.pop("formatting", None)
        patches.pop("generate_hashtags", None)       # the real, deterministic rule
    patches["generate_article"] = mock.MagicMock(return_value=_article(title))
    patches["_load_package_images"] = mock.MagicMock(
        return_value={} if package_images is None else package_images
    )
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output())
    prepare = mock.MagicMock(side_effect=images or (lambda *a, **k: []))
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       prepare):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    generated = list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))
    data = json.loads(generated[0].read_text()) if generated else None
    return code, patches, prepare, data


# ===========================================================================
# A1. One canonical Sources section on Wix
# ===========================================================================


def test_a_branded_echo_article_keeps_only_its_canonical_sources_section(tmp_path):
    code, _, _, data = _run(tmp_path)

    assert code == 0
    body = data["blog_article"]
    assert "## Source" not in body
    # the signal's SOURCE_NAME is not a source-record field: it never appears
    source_name = legacy._RAW_SIGNAL.get("SOURCE_NAME", "")
    assert source_name and f"[{source_name}]" not in body


def test_the_footer_is_skipped_only_for_the_canonical_sources_contract():
    source = Path("scripts/generate_and_publish.py").read_text()

    assert "_role.closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES" in source
    assert "if not _attribution_applied and not _canonical_sources_section:" in source


# ===========================================================================
# A3 + B. The accepted title is canonical, and every surface leads with it
# ===========================================================================


def test_generated_json_carries_the_accepted_title(tmp_path):
    _, _, _, data = _run(tmp_path)

    assert data["title"] == TITLE
    assert data["headline"] == TITLE


def test_no_accepted_title_is_recorded_as_none_never_the_signal_headline(tmp_path):
    _, _, _, data = _run(tmp_path, title=None)

    assert data["title"] is None
    assert data["headline"] == legacy._RAW_SIGNAL["HEADLINE"]


def test_the_linkedin_post_leads_with_the_accepted_title(tmp_path):
    _, _, _, data = _run(tmp_path)

    lines = [line for line in data["linkedin_post"].splitlines() if line.strip()]
    assert lines[0] == TITLE
    assert data["linkedin_post"].count(TITLE) == 1


def test_without_an_accepted_title_nothing_is_invented(tmp_path):
    _, _, _, data = _run(tmp_path, title=None)

    first = next(l for l in data["linkedin_post"].splitlines() if l.strip())
    assert first != legacy._RAW_SIGNAL["HEADLINE"]


@pytest.mark.parametrize("body,expected_first", [
    ("Hook line.\n\nBody.", TITLE),
    (f"{TITLE}\n\nBody.", TITLE),                      # already leads: unchanged
    (f"**{TITLE}**\n\nBody.", f"**{TITLE}**"),         # bold form counts too
    (f"{TITLE} Here is why.\n\nBody.", f"{TITLE} Here is why."),  # #259 review
])
def test_the_title_is_set_once_and_never_duplicated(body, expected_first):
    result = _lead_with_canonical_title(body, TITLE)

    assert result.splitlines()[0] == expected_first
    assert result.replace("*", "").count(TITLE) == 1


def test_no_title_leaves_the_body_untouched():
    assert _lead_with_canonical_title("Body.", None) == "Body."
    assert _lead_with_canonical_title("Body.", "") == "Body."


def test_hashtags_are_the_clean_rule_on_the_real_path(tmp_path):
    _, _, _, data = _run(tmp_path)

    last = data["linkedin_post"].rstrip().splitlines()[-1]
    assert last.startswith("#NeverBlank #CustomerTrust")
    assert "#CompoundPresence" not in last


# ===========================================================================
# E. The owner-controlled fresh-image preview
# ===========================================================================


def _fresh_images(tmp_path):
    def generate(signals, *args, **kwargs):
        return [{"images": {"platform_images": _pimgs(tmp_path)}}]
    return generate


def test_the_preview_generates_a_fresh_image_even_when_one_is_cached(tmp_path):
    cached = {"blog": {"url": "https://cdn.example/cached.png"},
              "_design_version": "test-v1"}
    code, patches, prepare, data = _run(
        tmp_path, argv_extra=("--preview-fresh-images",),
        package_images=cached, images=_fresh_images(tmp_path),
    )

    assert code == 0
    assert prepare.call_count == 1
    kwargs = prepare.call_args.kwargs
    assert kwargs["force_regenerate"] is True       # never the cached image
    assert kwargs["platforms"] is None              # every image surface
    assert not patches["_load_package_images"].called
    # the visual gate judged the fresh image
    assert patches["build_visual_assets_record"].called
    assert list(tmp_path.glob(f"{SIG}/runs/*/visual_assets.json")) or \
        patches["write_visual_assets_json"].called


def test_the_preview_publishes_nothing_and_consumes_nothing(tmp_path):
    code, patches, _, _ = _run(
        tmp_path, argv_extra=("--preview-fresh-images",),
        images=_fresh_images(tmp_path),
    )

    assert code == 0
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob(f"{SIG}/runs/*/publication_results.json"))


def test_a_failed_fresh_image_blocks_at_the_visual_gate_not_text_only(tmp_path):
    """The preview exists to exercise the visual path: a failure is shown,
    never silently downgraded to a text-only run."""
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["build_visual_assets_record"]         # the real gate
    patches["generate_article"] = mock.MagicMock(return_value=_article())
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=RuntimeError("image backend down")):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1
    assert not list(tmp_path.glob(f"{SIG}/runs/*/generated.json"))


def test_a_plain_dry_run_still_never_generates_an_image(tmp_path):
    code, _, prepare, data = _run(tmp_path)

    assert code == 0
    assert not prepare.called


@pytest.mark.parametrize("extra", [
    [],                                                   # not a dry run
    ["--dry-run", "--from-package", "--source-run-id", "r"],
    ["--dry-run", "--legacy-package"],
], ids=["publishing-run", "from-package", "legacy-package"])
def test_the_preview_flag_is_refused_outside_a_generating_dry_run(extra):
    argv = ["prog", "--signal-id", SIG, "--preview-fresh-images", *extra]
    with mock.patch.object(sys, "argv", argv):
        assert main() == 1


def test_the_first_valid_driver_passes_the_preview_flag_through(tmp_path):
    calls = []

    def run(argv):
        calls.append(argv)
        return 0

    run_first_valid.main(
        ["--editorial-role", MONDAY_ROLE, "--first-signal-id", "sig-1",
         "--audit-dir", str(tmp_path), "--dry-run", "--preview-fresh-images"],
        run=run,
    )

    assert "--preview-fresh-images" in calls[0] and "--dry-run" in calls[0]


def test_force_regenerate_bypasses_the_image_library():
    from scripts.research.prepare_content import _find_existing_image
    from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION

    library = {"s": {"url": "https://cdn.example/lib.png",
                     "design_version": CURRENT_DESIGN_VERSION}}

    assert _find_existing_image({"SIGNAL_ID": "s"}, library)[0] == (
        "https://cdn.example/lib.png")
    assert _find_existing_image({"SIGNAL_ID": "s"}, library,
                                force_regenerate=True) == (None, "force_regenerate")


def test_a_preview_with_a_visual_passport_still_verifies_its_chain(tmp_path):
    from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body

    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--preview-fresh-images"]
    del patches["build_visual_assets_record"]
    del patches["write_visual_assets_json"]
    del patches["accept_linkedin_composition"]
    del patches["write_linkedin_composition_json"]
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = ARTICLE_BODY
    article["platforms"]["medium"]["body"] = _native_linkedin_body()
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=_fresh_images(tmp_path)):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0
    run_id = next(tmp_path.glob(f"{SIG}/runs/*/visual_assets.json")).parent.name

    report = verify_run_provenance(tmp_path, SIG, run_id)

    assert "visual_assets" in report.verified_artifacts
    assert report.stopped_after == "generated"


# ===========================================================================
# Workflow wiring
# ===========================================================================


def _generate_step() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text())
    return next(s for s in data["jobs"]["monday-publish"]["steps"]
                if "Generate + Publish" in (s.get("name") or ""))


def test_the_preview_is_a_dispatch_input_defaulting_off():
    inputs = yaml.safe_load(WORKFLOW.read_text())[True]["workflow_dispatch"]["inputs"]

    assert inputs["preview_fresh_images"]["default"] == "false"
    assert inputs["preview_fresh_images"]["options"] == ["false", "true"]


def test_the_workflow_refuses_a_preview_that_is_not_a_dry_run():
    run = _generate_step()["run"]

    assert ('if [ "$DRY_RUN" != "true" ] || [ -n "$SOURCE_RUN_ID" ]; then' in run)
    assert "--preview-fresh-images" in run
    assert _generate_step()["env"]["PREVIEW_FRESH_IMAGES"] == "${{ inputs.preview_fresh_images }}"


def test_the_monday_schedule_is_still_paused():
    assert "schedule" not in yaml.safe_load(WORKFLOW.read_text())[True]
