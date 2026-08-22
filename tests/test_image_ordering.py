"""Issue #177: a blocked run has not already paid for its images.

Paid image generation (one billed base image + spec chat + composites and
uploads) used to run BEFORE article generation — so every run blocked at
editorial acceptance, source transparency, validation or LinkedIn
composition had already paid for assets it could not publish. The observed
production shape: run 32427935988 blocked at acceptance with its image
already generated. These scenarios prove the new order: image work happens
only after every text gate that can still block publication has passed,
fails closed before publishers when it fails, and the #174 reuse path
regenerates nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
    _run_entry,
)
from tests.test_monday_stream import MONDAY_ROLE, _run_with_role
from tests.test_research_artifact_lifecycle import ReadyProvider


def _exploding_image_patch():
    return mock.patch(
        "scripts.research.prepare_content.prepare_content_packages",
        side_effect=AssertionError("paid image generation was reached"),
    )


def _blocking_reviewer():
    return FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Remove the unsupported claims."),
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Still unsupported."),
    )


# ===========================================================================
# 1–3. Blocked runs make zero image transports
# ===========================================================================


def test_an_acceptance_blocked_run_pays_for_no_images(tmp_path):
    # REVISE → REVISE through the real acceptance boundary; image generation
    # would explode if reached
    with _exploding_image_patch():
        code, patches = _run_entry(
            tmp_path, reviewer=_blocking_reviewer(),
            revisor=FakeRevisionTransport("Revised body."),
        )

    assert code == 1
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    # the preserved review record honestly shows no visuals were generated
    record = json.loads(
        next(tmp_path.glob("*/runs/*/editorial_review_content.json")).read_text()
    )
    assert record["visuals"] == {}


@pytest.mark.parametrize("role", [MONDAY_ROLE, "never-blank-wednesday-golden"])
def test_a_transparency_blocked_role_run_pays_for_no_images(tmp_path, role):
    # both role streams: an article citing nothing fails source transparency
    # after acceptance — still before any image work
    article = {
        "pattern": {"mechanism": "capacity"},
        "platforms": {
            "long": {"body": "An article that cites nothing at all.", "title": "T"},
            "medium": {"body": "Nor does this LinkedIn body."},
        },
        "structured_article": legacy._FAKE_ARTICLE["structured_article"],
    }
    with _exploding_image_patch():
        code, patches, _ = _run_with_role(tmp_path, role, article)

    assert code == 1
    assert not patches["WixPublisher"].called if "WixPublisher" in patches else True
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_an_early_decision_block_pays_for_no_images(tmp_path):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output(disposition="reject"))
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            _exploding_image_patch():
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1
    assert not patches["generate_article"].called
    assert not patches["WixPublisher"].called


# ===========================================================================
# 4–5. A successful run generates once, for the active surfaces only
# ===========================================================================


def test_a_successful_run_generates_images_exactly_once_after_acceptance(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    calls: list = []

    def fake_images(signals, *args, **kwargs):
        calls.append(kwargs.get("platforms"))
        return [{"images": {"platform_images": {
            "blog": {"url": "https://cdn.example/b.png"},
            "linkedin": {"url": "https://cdn.example/l.png"},
        }}}]

    # cache empty → regeneration path
    patches["_load_package_images"] = mock.MagicMock(return_value={})
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=fake_images):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert calls == [["blog", "linkedin"]]     # once, R1 surfaces only (#175)


def test_the_image_block_sits_after_every_text_gate_in_source():
    source = Path("scripts/generate_and_publish.py").read_text()
    image = source.index("Image preparation (fresh-gen path, after all text gates")
    # every text gate that can block publication comes first
    for gate in ("_acceptance = run_editorial_acceptance(",
                 "validate_source_transparency(\n",
                 "_li_record = accept_linkedin_composition("):
        assert source.index(gate) < image, gate
    # and the visual contract gate + publishers come after
    assert image < source.index("build_visual_assets_record(")
    # the pre-gate section carries only the zero-cost placeholder
    placeholder = source.index("Image preparation deferred (#177)")
    assert placeholder < source.index("_acceptance = run_editorial_acceptance(")


# ===========================================================================
# 6. Image failure after acceptance: fail closed, no publisher, no consumption
# ===========================================================================


def test_image_failure_after_acceptance_blocks_before_publishers(tmp_path):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    patches["_load_package_images"] = mock.MagicMock(return_value={})
    # the REAL visual gate must judge the empty result
    del patches["build_visual_assets_record"]
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=RuntimeError("image backend down")):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1                                   # visual gate fails closed
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called  # nothing consumed


# ===========================================================================
# 7. From-package reuse regenerates nothing
# ===========================================================================


def test_from_package_reuse_makes_zero_new_image_work(tmp_path):
    from tests.test_decision_lifecycle import _build_source_run, _reuse_patches

    source_run_id = _build_source_run(tmp_path)
    argv, patches = _reuse_patches(tmp_path, source_run_id)
    evaluator, transport = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            _exploding_image_patch():
        code = main(decision_evaluator=evaluator)

    assert code == 0
    assert transport.calls == []
    assert patches["generate_article"].called is False


# ===========================================================================
# 8. Cost-safety pins (#170–#176 full suites run in the battery)
# ===========================================================================


def test_cost_safety_contracts_survive_the_reorder():
    import os
    from src.editorial.source_eligibility import SourceEligibilityError
    from src.publishing.hashtags import BRANDED_HASHTAGS, generate_hashtags
    from src.run.call_budget import DEFAULT_CEILING

    assert SourceEligibilityError("x").scope == "candidate"   # #170
    assert DEFAULT_CEILING == 40                               # #171
    assert os.environ.get("NB_OPENAI_API_KEY") is None         # #172
    tags = generate_hashtags({"INDUSTRY": "retail"}, "linkedin",
                             mechanism="capacity", title="The Queue")
    assert tags[:3] == list(BRANDED_HASHTAGS)                  # #176
