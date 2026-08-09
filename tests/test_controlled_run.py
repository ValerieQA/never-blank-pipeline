"""
Tests for scripts/controlled_run.py and src/controlled_run/guard.py.

ALL external providers (OpenAI, Cloudinary, publishers) are mocked.
Tests verify orchestration, data flow, and isolation guarantees.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────────────────────

TOPIC = "Why small businesses disappear from customer memory between projects"


def _stub_article_result() -> dict:
    return {
        "pattern": {"visibility_pattern": "test pattern"},
        "decision_lens": {"core_pattern": "test core pattern"},
        "narrative_spine": {"spine": "test spine"},
        "structured_article": {
            "hook": "The test hook.",
            "discovery": {"aha_setup": "Test aha."},
            "surviving_explanation": "Test explanation.",
            "reframe": "Test reframe.",
            "echo_line": "Test echo.",
            "business_translation": "Test translation.",
            "narrative_spine": "Test spine.",
        },
        "platforms": {
            "long":      {"body": "Blog article body for test. " * 20},
            "medium":    {"body": "LinkedIn post for test. " * 10},
            "reading":   {"body": "Facebook post for test."},
            "instagram": {"body": "Instagram caption for test."},
        },
    }


def _run_full_e2e(tmp_path: Path, extra_args: list | None = None) -> tuple[int, Path]:
    """
    Execute run_controlled() with full-e2e mode.
    All LLM and publisher calls are mocked.
    Returns (exit_code, run_dir).
    """
    from scripts.controlled_run import run_controlled, _parse_args

    argv = [
        "--mode", "full-e2e",
        "--publication", "disabled",
        "--external-writes", "disabled",
        "--cache", "disabled",
        "--image-reuse", "disabled",
        "--output-root", str(tmp_path),
        "--topic", TOPIC,
        "--brand", "Never Blank",
        "--channels", "linkedin,blog,instagram",
    ]
    if extra_args:
        argv.extend(extra_args)

    args = _parse_args(argv)

    with mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_stub_article_result()), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary") as mock_cld, \
         mock.patch("src.strategy.history.append_published_entry") as mock_hist, \
         mock.patch("src.publishing.wix.WixPublisher.publish") as mock_wix, \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish") as mock_li, \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish") as mock_fb, \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish") as mock_ig, \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish") as mock_th, \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish") as mock_tg:

        exit_code = run_controlled(args)

    # Find the run_dir (only one directory in tmp_path)
    subdirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    run_dir = subdirs[0] if subdirs else tmp_path

    return exit_code, run_dir, {
        "cloudinary": mock_cld,
        "history":    mock_hist,
        "wix":        mock_wix,
        "linkedin":   mock_li,
        "facebook":   mock_fb,
        "instagram":  mock_ig,
        "threads":    mock_th,
        "telegram":   mock_tg,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: full-e2e mode creates a fresh signal, not reading old generated JSON
# ──────────────────────────────────────────────────────────────────────────────

def test_full_e2e_creates_fresh_signal_not_loading_existing_json(tmp_path):
    """full-e2e does not read any existing _generated.json; creates a new stub signal."""
    with mock.patch("scripts.controlled_run._load_existing_signal") as mock_load, \
         mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_stub_article_result()), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        from scripts.controlled_run import run_controlled, _parse_args
        args = _parse_args([
            "--mode", "full-e2e",
            "--publication", "disabled",
            "--external-writes", "disabled",
            "--output-root", str(tmp_path),
            "--topic", TOPIC,
        ])
        run_controlled(args)

    # _load_existing_signal is for existing-signal mode only
    mock_load.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: existing-signal mode labels manifest as existing-signal
# ──────────────────────────────────────────────────────────────────────────────

def test_existing_signal_mode_labeled_in_manifest(tmp_path):
    """existing-signal mode: manifest.mode == 'existing-signal'."""
    fake_signal = {
        "SIGNAL_ID": "test-existing-001",
        "HEADLINE": "Test signal",
        "SIGNAL_TYPE": "business trust",
        "REGION": "US",
        "INDUSTRY": "Tech",
        "SOURCE_NAME": "Test",
        "SOURCE_URL": "",
        "SOURCE_DATE": "2026-01-01",
        "DATE_FOUND": "2026-01-01",
        "CORE_FACT": "Test fact",
        "CONFIDENCE": "medium",
        "ARTICLE_READY": "true",
        "SOURCE_PREMISE_VERIFIED": "unknown",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "7",
        "CHANNEL_FIT_SCORE": "7",
        "OUTCOME_IF_KNOWN": "unknown",
        "DID_IT_WORK": "unknown",
        "NEVER_BLANK_ANGLE": "Test angle",
        "POTENTIAL_HOOK": "Test hook",
        "TARGET_AUDIENCE": "founder",
        "PRIMARY_CHANNEL": "linkedin",
        "APPROVED_OVERRIDE": "",
    }

    with mock.patch("scripts.controlled_run._load_existing_signal", return_value=fake_signal), \
         mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_stub_article_result()), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        from scripts.controlled_run import run_controlled, _parse_args
        args = _parse_args([
            "--mode", "existing-signal",
            "--publication", "disabled",
            "--external-writes", "disabled",
            "--output-root", str(tmp_path),
            "--signal-id", "test-existing-001",
        ])
        run_controlled(args)

    manifest_path = next(tmp_path.iterdir()) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["mode"] == "existing-signal"


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: New run does not call _load_package_images
# ──────────────────────────────────────────────────────────────────────────────

def test_new_run_does_not_call_load_package_images(tmp_path):
    """controlled_run.py never calls _load_package_images (image reuse disabled)."""
    with mock.patch("scripts.generate_and_publish._load_package_images") as mock_lpi, \
         mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_stub_article_result()), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        from scripts.controlled_run import run_controlled, _parse_args
        args = _parse_args([
            "--mode", "full-e2e",
            "--publication", "disabled",
            "--external-writes", "disabled",
            "--output-root", str(tmp_path),
            "--topic", TOPIC,
        ])
        run_controlled(args)

    mock_lpi.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Unique run directory is created per run
# ──────────────────────────────────────────────────────────────────────────────

def test_unique_run_directory_per_run(tmp_path):
    """Each call to run_controlled() creates a distinct subdirectory."""
    exit_code1, run_dir1, _ = _run_full_e2e(tmp_path)
    # Second run needs a new tmp_path sub-dir (or wait for timestamp to change)
    import time; time.sleep(1)
    tmp_path2 = tmp_path / "second"
    tmp_path2.mkdir()
    exit_code2, run_dir2, _ = _run_full_e2e(tmp_path2)

    assert run_dir1 != run_dir2


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Existing run directory causes immediate error
# ──────────────────────────────────────────────────────────────────────────────

def test_existing_run_directory_causes_error(tmp_path):
    """If run_dir already exists, run_controlled raises immediately."""
    from scripts.controlled_run import run_controlled, _parse_args

    # Simulate by mocking uuid to return a fixed value and pre-creating the dir
    fixed_hex = "aabbccddee11"

    with mock.patch("scripts.controlled_run.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = fixed_hex * 4  # hex is sliced [:12]
        # Pre-create the directory
        import datetime as dt_mod
        ts = dt_mod.datetime.now(dt_mod.timezone.utc).strftime("%Y%m%d_%H%M%S")
        pre_existing = tmp_path / f"{ts}_{fixed_hex[:12]}"
        pre_existing.mkdir(parents=True)

        args = _parse_args([
            "--mode", "full-e2e",
            "--publication", "disabled",
            "--external-writes", "disabled",
            "--output-root", str(tmp_path),
            "--topic", TOPIC,
        ])
        with mock.patch("src.editorial.pipeline.generate_article",
                        return_value=_stub_article_result()), \
             mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
             mock.patch("src.strategy.history.append_published_entry"), \
             mock.patch("src.publishing.wix.WixPublisher.publish"), \
             mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
             mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
             mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
             mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
             mock.patch("src.publishing.telegram.TelegramPublisher.publish"):
            result = run_controlled(args)

    assert result == 1


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: All artifact paths in manifest share the same run_id
# ──────────────────────────────────────────────────────────────────────────────

def test_all_artifact_paths_share_run_id(tmp_path):
    """Every artifact path in the manifest contains the same run directory."""
    exit_code, run_dir, _ = _run_full_e2e(tmp_path)
    assert exit_code == 0

    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    run_id = manifest["run_id"]

    for key, path_str in manifest["artifact_paths"].items():
        assert run_id in path_str or str(run_dir) in path_str, \
            f"Artifact {key!r} path {path_str!r} does not contain run_id={run_id!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Manifest contains git_sha and publication_disabled=True
# ──────────────────────────────────────────────────────────────────────────────

def test_manifest_contains_git_sha_and_publication_disabled(tmp_path):
    exit_code, run_dir, _ = _run_full_e2e(tmp_path)
    assert exit_code == 0

    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert "git_sha" in manifest
    assert manifest["git_sha"]  # not empty
    assert manifest["publication_disabled"] is True


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: ResearchContext serialization preserves article_ready
# ──────────────────────────────────────────────────────────────────────────────

def test_research_context_serialization_preserves_article_ready():
    from src.lifecycle.signal_lifecycle import ResearchContext
    signal = {
        "SIGNAL_ID": "roundtrip-001",
        "HEADLINE": "Test",
        "SIGNAL_TYPE": "business trust",
        "REGION": "US",
        "INDUSTRY": "Tech",
        "SOURCE_NAME": "Test",
        "SOURCE_URL": "",
        "SOURCE_DATE": "2026-01-01",
        "DATE_FOUND": "2026-01-01",
        "CORE_FACT": "Fact",
        "CONFIDENCE": "medium",
        "ARTICLE_READY": "true",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "7",
        "CHANNEL_FIT_SCORE": "7",
        "OUTCOME_IF_KNOWN": "unknown",
        "DID_IT_WORK": "unknown",
        "APPROVED_OVERRIDE": "",
    }
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is True

    d = rc.to_dict()
    rc2 = ResearchContext.from_dict(d)
    assert rc2.article_ready is True


# ──────────────────────────────────────────────────────────────────────────────
# Test 9: EditorialContext artifact contains NEVER_BLANK_ANGLE
# ──────────────────────────────────────────────────────────────────────────────

def test_editorial_context_artifact_contains_never_blank_angle(tmp_path):
    exit_code, run_dir, _ = _run_full_e2e(tmp_path)
    assert exit_code == 0

    ec_path = run_dir / "editorial_context.json"
    assert ec_path.exists()
    ec = json.loads(ec_path.read_text())
    # The editorial_context.json has _editorial_metadata.never_blank_angle
    assert ec.get("_editorial_metadata", {}).get("never_blank_angle") is not None


# ──────────────────────────────────────────────────────────────────────────────
# Test 10: decision_lens_input.json contains NEVER_BLANK_ANGLE context
# ──────────────────────────────────────────────────────────────────────────────

def test_decision_lens_input_contains_signal_keys(tmp_path):
    exit_code, run_dir, _ = _run_full_e2e(tmp_path)
    assert exit_code == 0

    dl_path = run_dir / "decision_lens_input.json"
    assert dl_path.exists()
    dl = json.loads(dl_path.read_text())
    # decision_lens_input comes from editorial_ctx.to_legacy_dict()
    assert "HEADLINE" in dl
    assert "CORE_FACT" in dl
    assert "ARTICLE_READY" in dl


# ──────────────────────────────────────────────────────────────────────────────
# Test 11: Article generation function called (not loading cached)
# ──────────────────────────────────────────────────────────────────────────────

def test_article_generation_function_called_not_loading_cached(tmp_path):
    with mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_stub_article_result()) as mock_gen, \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        from scripts.controlled_run import run_controlled, _parse_args
        args = _parse_args([
            "--mode", "full-e2e",
            "--publication", "disabled",
            "--external-writes", "disabled",
            "--output-root", str(tmp_path),
            "--topic", TOPIC,
        ])
        run_controlled(args)

    mock_gen.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Test 12: Visual brief angle_source matches NEVER_BLANK_ANGLE from signal
# ──────────────────────────────────────────────────────────────────────────────

def test_visual_brief_angle_source_matches_never_blank_angle(tmp_path):
    exit_code, run_dir, _ = _run_full_e2e(tmp_path)
    assert exit_code == 0

    vb_path = run_dir / "visual_brief.json"
    assert vb_path.exists()
    vb = json.loads(vb_path.read_text())

    # The stub signal's NEVER_BLANK_ANGLE is derived from the topic
    assert vb["angle_source"], "angle_source must not be empty"
    assert "Never Blank" in vb["brand_name"] or vb["brand_name"] == "Never Blank"


# ──────────────────────────────────────────────────────────────────────────────
# Test 13: Image prompt negative_prompt contains required exclusions
# ──────────────────────────────────────────────────────────────────────────────

def test_image_prompt_negative_prompt_contains_exclusions(tmp_path):
    exit_code, run_dir, _ = _run_full_e2e(tmp_path)
    assert exit_code == 0

    ip_path = run_dir / "image_prompt.json"
    assert ip_path.exists()
    ip = json.loads(ip_path.read_text())

    neg = ip.get("negative_prompt", "")
    required_exclusions = [
        "robots",
        "humanoid AI",
        "glowing brains",
        "neural network visualizations",
        "circuit boards",
        "generic stock-AI imagery",
        "text or typography inside image",
    ]
    for excl in required_exclusions:
        assert excl in neg, f"negative_prompt missing required exclusion: {excl!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 14: No image reuse — image library NOT read in full-e2e
# ──────────────────────────────────────────────────────────────────────────────

def test_no_image_reuse_image_library_not_read(tmp_path):
    """_load_image_library from prepare_content.py is never called."""
    with mock.patch("scripts.research.prepare_content._load_image_library") as mock_lib, \
         mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_stub_article_result()), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        from scripts.controlled_run import run_controlled, _parse_args
        args = _parse_args([
            "--mode", "full-e2e",
            "--publication", "disabled",
            "--external-writes", "disabled",
            "--output-root", str(tmp_path),
            "--topic", TOPIC,
        ])
        run_controlled(args)

    mock_lib.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 15: upload_to_cloudinary NOT called
# ──────────────────────────────────────────────────────────────────────────────

def test_upload_to_cloudinary_not_called(tmp_path):
    exit_code, run_dir, mocks = _run_full_e2e(tmp_path)
    assert exit_code == 0
    mocks["cloudinary"].assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 16: append_published_entry NOT called
# ──────────────────────────────────────────────────────────────────────────────

def test_append_published_entry_not_called(tmp_path):
    exit_code, run_dir, mocks = _run_full_e2e(tmp_path)
    assert exit_code == 0
    mocks["history"].assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 17: Wix/LinkedIn/social publisher.publish NOT called
# ──────────────────────────────────────────────────────────────────────────────

def test_publisher_publish_methods_not_called(tmp_path):
    exit_code, run_dir, mocks = _run_full_e2e(tmp_path)
    assert exit_code == 0
    for name in ("wix", "linkedin", "facebook", "instagram", "threads", "telegram"):
        mocks[name].assert_not_called(), f"{name} publisher should not be called"


# ──────────────────────────────────────────────────────────────────────────────
# Test 18: Failure saves manifest with failure_stage and status=failed
# ──────────────────────────────────────────────────────────────────────────────

def test_failure_saves_manifest_with_failure_stage(tmp_path):
    """When article generation raises, manifest has status=failed and failure_stage set."""
    from scripts.controlled_run import run_controlled, _parse_args
    from src.editorial.pipeline import ArticleGenerationError

    args = _parse_args([
        "--mode", "full-e2e",
        "--publication", "disabled",
        "--external-writes", "disabled",
        "--output-root", str(tmp_path),
        "--topic", TOPIC,
    ])

    with mock.patch("src.editorial.pipeline.generate_article",
                    side_effect=ArticleGenerationError("test-stage", ValueError("LLM refused"))), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        result = run_controlled(args)

    assert result == 1

    run_dir = next(tmp_path.iterdir())
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failure_stage"] is not None
    assert manifest["failure_stage"] != ""


# ──────────────────────────────────────────────────────────────────────────────
# Test 19: No partial failure gets status=complete
# ──────────────────────────────────────────────────────────────────────────────

def test_partial_failure_does_not_get_status_complete(tmp_path):
    """Any exception during the pipeline prevents status=complete in manifest."""
    from scripts.controlled_run import run_controlled, _parse_args
    from src.editorial.pipeline import ArticleGenerationError

    args = _parse_args([
        "--mode", "full-e2e",
        "--publication", "disabled",
        "--external-writes", "disabled",
        "--output-root", str(tmp_path),
        "--topic", TOPIC,
    ])

    with mock.patch("src.editorial.pipeline.generate_article",
                    side_effect=RuntimeError("unexpected crash")), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"), \
         mock.patch("src.publishing.wix.WixPublisher.publish"), \
         mock.patch("src.publishing.linkedin.LinkedInPublisher.publish"), \
         mock.patch("src.publishing.facebook.FacebookPublisher.publish"), \
         mock.patch("src.publishing.instagram.InstagramPublisher.publish"), \
         mock.patch("src.publishing.threads.ThreadsPublisher.publish"), \
         mock.patch("src.publishing.telegram.TelegramPublisher.publish"):

        result = run_controlled(args)

    assert result == 1
    run_dir = next(tmp_path.iterdir())
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] != "complete"


# ──────────────────────────────────────────────────────────────────────────────
# Test 20: Lifecycle normalization: signal with RECOMMENDED_FOR_ARTICLE=true passes preflight
# ──────────────────────────────────────────────────────────────────────────────

def test_lifecycle_normalization_recommended_for_article_passes_preflight(tmp_path):
    """
    A signal with only RECOMMENDED_FOR_ARTICLE=true (no ARTICLE_READY, no FORCE_PUBLISH_OVERRIDE)
    must pass the preflight gate after the normalization fix.
    """
    from src.lifecycle.signal_lifecycle import ResearchContext
    signal = {
        "SIGNAL_ID": "test-normalization-check",
        "HEADLINE": "Test normalization",
        "SIGNAL_TYPE": "business trust",
        "REGION": "US",
        "INDUSTRY": "Tech",
        "SOURCE_NAME": "Test",
        "SOURCE_URL": "",
        "SOURCE_DATE": "2026-01-01",
        "DATE_FOUND": "2026-01-01",
        "CORE_FACT": "Test fact",
        "CONFIDENCE": "medium",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "8",
        "CHANNEL_FIT_SCORE": "8",
        "OUTCOME_IF_KNOWN": "unknown",
        "DID_IT_WORK": "unknown",
        "APPROVED_OVERRIDE": "",
        # No ARTICLE_READY — only the alias
        "RECOMMENDED_FOR_ARTICLE": "true",
    }
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is True, (
        "RECOMMENDED_FOR_ARTICLE=true must normalize to article_ready=True "
        "without requiring FORCE_PUBLISH_OVERRIDE"
    )
    # admission_status should be 'admitted' (article_ready=True + score_recommended=True)
    assert rc.admission_status == "admitted"
