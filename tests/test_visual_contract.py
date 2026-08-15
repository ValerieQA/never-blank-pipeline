"""Issue #96 / Story #15: canonical visual contract and fail-closed channel gate.

Release 1 rule under test: the Wix visual is required; the LinkedIn visual is
optional (text-only allowed) but an attempted LinkedIn visual that failed or
is invalid never becomes silent text-only success. All scenarios use the real
canonical entrypoint or the real gate functions with deterministic fixtures —
no live provider calls. Real Cloudinary/Wix/LinkedIn asset proof is deferred
live verification (Stories #19/#21).
"""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest
from PIL import Image

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.publishing.image_pipeline import PLATFORM_SIZES
from src.visual.contract import (
    LinkedInVisualState,
    VisualAssetsRecord,
    VisualGateError,
    build_visual_assets_record,
    verify_visual_assets_record,
)
from src.editorial.linkedin_composition import article_digest
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider


DESIGN = "test-v1"  # matches the harness CURRENT_DESIGN_VERSION patch
ARTICLE = "The accepted article body used as the stable current-run source identity."


def _png(tmp_path, name: str, size: tuple[int, int]) -> str:
    path = tmp_path / name
    Image.new("RGB", size, (20, 20, 20)).save(path, "PNG")
    return str(path)


def _pimgs(tmp_path, *, with_linkedin=True, blog_url="https://res.cloudinary.com/nb/blog.png",
           linkedin_url="https://res.cloudinary.com/nb/linkedin.png",
           blog_size=None, linkedin_size=None, design=DESIGN,
           blog_upload_failed=False, linkedin_upload_failed=False,
           blog_format="PNG"):
    blog_dims = blog_size or PLATFORM_SIZES["blog"]
    blog_path = tmp_path / "blog_asset.img"
    Image.new("RGB", blog_dims, (10, 10, 10)).save(blog_path, blog_format)
    images = {
        "blog": {
            "url": blog_url, "path": str(blog_path),
            "size": f"{PLATFORM_SIZES['blog'][0]}x{PLATFORM_SIZES['blog'][1]}",
            "reused": False, "upload_failed": blog_upload_failed,
        },
        "_design_version": design,
        "_method": "quote_card",
    }
    if with_linkedin:
        li_dims = linkedin_size or PLATFORM_SIZES["linkedin"]
        li_path = tmp_path / "linkedin_asset.png"
        Image.new("RGB", li_dims, (10, 10, 10)).save(li_path, "PNG")
        images["linkedin"] = {
            "url": linkedin_url, "path": str(li_path),
            "size": f"{PLATFORM_SIZES['linkedin'][0]}x{PLATFORM_SIZES['linkedin'][1]}",
            "reused": False, "upload_failed": linkedin_upload_failed,
        }
    return images


def _build(tmp_path, **overrides):
    pimgs = overrides.pop("pimgs", None) or _pimgs(tmp_path, **overrides)
    return build_visual_assets_record(
        pimgs, run_id="run-a", signal_id="sig-test-001",
        article_body=ARTICLE, design_version=DESIGN,
    )


# ===========================================================================
# 1+2+11. Valid records and lineage
# ===========================================================================


def test_valid_wix_and_linkedin_assets_produce_valid_records(tmp_path):
    record = _build(tmp_path)
    assert record.status == "valid"
    assert record.linkedin_visual is LinkedInVisualState.VALID
    channels = {d.channel: d for d in record.derivatives}
    assert set(channels) == {"wix", "linkedin"}
    assert (channels["wix"].width, channels["wix"].height) == PLATFORM_SIZES["blog"]
    assert (channels["linkedin"].width, channels["linkedin"].height) == PLATFORM_SIZES["linkedin"]
    assert channels["wix"].format == "png"
    # full truthful lineage (criterion 11)
    assert record.run_id == "run-a"
    assert record.signal_id == "sig-test-001"
    assert record.source_article_digest == article_digest(ARTICLE)
    assert record.provider == "cloudinary"
    assert record.method == "quote_card"
    assert record.design_version == DESIGN
    assert record.master_asset_url == channels["wix"].url


def test_absent_linkedin_visual_is_honest_not_requested(tmp_path):
    record = _build(tmp_path, with_linkedin=False)
    assert record.status == "valid"
    assert record.linkedin_visual is LinkedInVisualState.NOT_REQUESTED
    assert [d.channel for d in record.derivatives] == ["wix"]


# ===========================================================================
# 3–8. Required Wix visual fails closed
# ===========================================================================


def test_missing_wix_visual_is_blocked(tmp_path):
    pimgs = _pimgs(tmp_path)
    del pimgs["blog"]
    with pytest.raises(VisualGateError, match="required Wix visual is missing"):
        _build(tmp_path, pimgs=pimgs)


def test_wix_generation_failure_is_blocked(tmp_path):
    # generation failure manifests as no usable image mapping at all
    with pytest.raises(VisualGateError, match="no usable image mapping"):
        build_visual_assets_record(
            None, run_id="run-a", signal_id="sig-test-001",
            article_body=ARTICLE, design_version=DESIGN,
        )


def test_wix_upload_failure_is_blocked_never_successful(tmp_path):
    with pytest.raises(VisualGateError, match="upload failed"):
        _build(tmp_path, blog_upload_failed=True, blog_url="")


def test_local_filesystem_path_never_crosses_as_publishable_url(tmp_path):
    local = _png(tmp_path, "local.png", PLATFORM_SIZES["blog"])
    with pytest.raises(VisualGateError, match="local filesystem path"):
        _build(tmp_path, blog_url=local)


def test_wrong_wix_dimensions_are_blocked(tmp_path):
    with pytest.raises(VisualGateError, match="dimensions"):
        _build(tmp_path, blog_size=(800, 600))


def test_unsupported_wix_format_is_blocked(tmp_path):
    with pytest.raises(VisualGateError, match="unsupported"):
        _build(tmp_path, blog_format="BMP")


def test_stale_design_version_is_blocked(tmp_path):
    with pytest.raises(VisualGateError, match="design version"):
        _build(tmp_path, design="stale-v0")


# ===========================================================================
# 9. Attempted LinkedIn visual failures never become silent text-only
# ===========================================================================


def test_invalid_linkedin_dimensions_fail_closed_not_text_only(tmp_path):
    with pytest.raises(VisualGateError, match="linkedin visual dimensions"):
        _build(tmp_path, linkedin_size=(500, 500))


def test_linkedin_upload_failure_fails_closed_not_text_only(tmp_path):
    with pytest.raises(VisualGateError, match="linkedin visual upload failed"):
        _build(tmp_path, linkedin_upload_failed=True, linkedin_url="")


def test_linkedin_local_path_url_fails_closed(tmp_path):
    local = _png(tmp_path, "li_local.png", PLATFORM_SIZES["linkedin"])
    with pytest.raises(VisualGateError, match="local filesystem path"):
        _build(tmp_path, linkedin_url=local)


# ===========================================================================
# 12–13. Drift and provider failure honesty
# ===========================================================================


def test_cross_run_and_source_mismatch_fail_closed(tmp_path):
    record = _build(tmp_path)
    verify_visual_assets_record(record, run_id="run-a", article_body=ARTICLE)
    with pytest.raises(VisualGateError, match="different run"):
        verify_visual_assets_record(record, run_id="run-b", article_body=ARTICLE)
    with pytest.raises(VisualGateError, match="source article"):
        verify_visual_assets_record(
            record, run_id="run-a", article_body=ARTICLE + " tampered"
        )


def test_provider_failure_cannot_be_recorded_as_success(tmp_path):
    # even a syntactically plausible URL cannot rescue an upload marked failed
    with pytest.raises(VisualGateError, match="never recorded"):
        _build(tmp_path, blog_upload_failed=True)


# ===========================================================================
# 14–15. Entrypoint: persistence, immutability, channel discipline
# ===========================================================================


def _entry(tmp_path, *, pimgs, dry_run=True):
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    del patches["build_visual_assets_record"]     # exercise the real gate
    del patches["write_visual_assets_json"]
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    patches["_load_package_images"] = mock.MagicMock(return_value=pimgs)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


def test_entrypoint_persists_immutable_run_scoped_visual_passport(tmp_path):
    pimgs = _pimgs(tmp_path)
    code, _ = _entry(tmp_path, pimgs=pimgs)
    assert code == 0
    records = list(tmp_path.glob("*/runs/*/visual_assets.json"))
    assert len(records) == 1
    data = json.loads(records[0].read_text())
    assert data["run_id"] == records[0].parent.name  # run-scoped
    assert data["status"] == "valid"
    assert data["linkedin_visual"] == "valid"
    # channel discipline (criterion 15): only Release 1 channels are recorded,
    # no Instagram/Facebook/Threads/Telegram visual behavior introduced
    assert {d["channel"] for d in data["derivatives"]} == {"wix", "linkedin"}
    # create-once immutability
    from src.artifacts import ArtifactCollisionError, write_visual_assets_json
    with pytest.raises(ArtifactCollisionError):
        write_visual_assets_json(records[0].parent, {"status": "tamper"})
    # strict reload
    VisualAssetsRecord.model_validate(data)


def test_entrypoint_blocks_run_when_wix_visual_is_missing(tmp_path):
    pimgs = _pimgs(tmp_path)
    del pimgs["blog"]
    code, patches = _entry(tmp_path, pimgs=pimgs, dry_run=False)
    assert code == 1
    assert not list(tmp_path.glob("*/runs/*/visual_assets.json"))
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called


def test_entrypoint_continues_text_only_when_linkedin_visual_absent(tmp_path):
    pimgs = _pimgs(tmp_path, with_linkedin=False)
    code, _ = _entry(tmp_path, pimgs=pimgs)
    assert code == 0
    data = json.loads(next(tmp_path.glob("*/runs/*/visual_assets.json")).read_text())
    assert data["linkedin_visual"] == "not_requested"
    assert {d["channel"] for d in data["derivatives"]} == {"wix"}
    assert list(tmp_path.glob("*/runs/*/generated.json"))  # run continued


def test_entrypoint_fails_closed_for_attempted_invalid_linkedin_visual(tmp_path):
    pimgs = _pimgs(tmp_path, linkedin_size=(500, 500))
    code, patches = _entry(tmp_path, pimgs=pimgs, dry_run=False)
    assert code == 1
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    assert not patches["LinkedInPublisher"].called


# ===========================================================================
# Review follow-up: truthful --from-package reuse provenance
# ===========================================================================


def test_fresh_generation_record_is_its_own_origin(tmp_path):
    record = _build(tmp_path)
    assert record.reused is False
    assert record.origin_run_id == record.run_id


def _reuse_entry(tmp_path, source_run_id):
    """Real canonical --from-package run with the real visual reuse gate."""

    from tests.test_decision_lifecycle import _reuse_patches

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    del patches["load_visual_assets_json"]        # exercise the real seam
    del patches["reuse_visual_assets_record"]
    del patches["write_visual_assets_json"]
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main()
    return code, patches


def _build_source_run_with_visuals(tmp_path):
    pimgs = _pimgs(tmp_path)
    code, _ = _entry(tmp_path, pimgs=pimgs)
    assert code == 0
    passport = next(tmp_path.glob("*/runs/*/visual_assets.json"))
    return passport.parent.name


def test_from_package_reuse_preserves_true_visual_origin(tmp_path):
    """Mandated: publication run B reuses run A's visuals with truthful lineage."""

    run_a = _build_source_run_with_visuals(tmp_path)
    code, _ = _reuse_entry(tmp_path, run_a)
    assert code == 0
    records = {
        p.parent.name: json.loads(p.read_text())
        for p in tmp_path.glob("*/runs/*/visual_assets.json")
    }
    assert len(records) == 2
    run_b = next(r for r in records if r != run_a)
    reuse = records[run_b]
    # publication run stays B; visual origin stays A; B never claims production
    assert reuse["run_id"] == run_b
    assert reuse["origin_run_id"] == run_a
    assert reuse["reused"] is True
    original = records[run_a]
    assert original["origin_run_id"] == run_a and original["reused"] is False
    # article/source linkage and derivatives match run A's passport
    assert reuse["source_article_digest"] == original["source_article_digest"]
    assert reuse["derivatives"] == original["derivatives"]
    VisualAssetsRecord.model_validate(reuse)  # strict contract holds


def test_from_package_fails_closed_without_source_visual_passport(tmp_path):
    """Mandated: unprovable legacy reuse fails closed with no fabricated record."""

    run_a = _build_source_run_with_visuals(tmp_path)
    passport = next(tmp_path.glob(f"*/runs/{run_a}/visual_assets.json"))
    passport.unlink()  # legacy-style source run without a visual passport

    code, patches = _reuse_entry(tmp_path, run_a)
    assert code == 1
    # no fabricated visual_assets.json claiming the publication run as origin
    assert not list(tmp_path.glob("*/runs/*/visual_assets.json"))
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called


def test_cross_run_visual_laundering_is_rejected(tmp_path):
    """Mandated: run C's passport is not accepted for run A merely because
    signal/content shape matches."""

    run_a = _build_source_run_with_visuals(tmp_path)
    # a second, independent fresh run C of the same signal/content
    pimgs = _pimgs(tmp_path)
    code, _ = _entry(tmp_path, pimgs=pimgs)
    assert code == 0
    run_c = next(
        p.parent.name
        for p in tmp_path.glob("*/runs/*/visual_assets.json")
        if p.parent.name != run_a
    )
    # substitute C's passport into A's namespace (same signal, same digest)
    passport_a = next(tmp_path.glob(f"*/runs/{run_a}/visual_assets.json"))
    passport_c = next(tmp_path.glob(f"*/runs/{run_c}/visual_assets.json"))
    passport_a.unlink()
    passport_a.write_bytes(passport_c.read_bytes())

    code, patches = _reuse_entry(tmp_path, run_a)
    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
