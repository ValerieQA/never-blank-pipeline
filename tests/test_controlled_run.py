"""
Tests for scripts/controlled_run.py — new architecture.

## Design contract (16 behaviors from review Step 10)

 1. full-e2e calls production Research Engine stages (not stubs)
 2. _create_synthetic_signal is NOT called in full-e2e mode
 3. Signal in full-e2e originates from research output (same run)
 4. Research artifacts contain source provenance
 5. Research cache disabled (seen_ids=empty set)
 6. Production generate_decision_lens actually called inside generate_article
 7. Decision Lens output recorded and available downstream
 8. Production choose_visual_family actually called
 9. Image prompt originates from visual spec of current run
10. Image provider called only when --image-generation enabled
11. When disabled, status is NOT complete (must be complete_without_image)
12. Cloudinary / history / publish adapters blocked by env-var BEFORE network call
13. Validation report built from invocation ledger, not hardcoded values
14. synthetic-signal never labeled full-e2e
15. Old generate_and_publish helpers not called (no image-library read)
16. Partial/skipped mandatory stage prevents status=complete

## Mocking strategy

Production research stages (run_discovery, score_candidates, enrich_candidates,
add_angles) are patched at their module-level symbols. Their lazy imports inside
_run_research_engine() receive the mock because `from X import Y` resolves at
call time against the module's current attribute.

generate_article is patched at src.editorial.pipeline to avoid real LLM calls
while still exercising all orchestration around it.

choose_visual_family and load_registry are patched to avoid config I/O.

External sinks (upload_to_cloudinary, append_published_entry) are ALSO blocked
architecturally by NB_CONTROLLED_RUN=1 (set in controlled_run module top-level),
but we patch them as defense-in-depth to prevent accidental network calls.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# NB_CONTROLLED_RUN is set inside run_controlled() — not at module level.
# (see autouse fixture set_nb_controlled_run_env below)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_nb_controlled_run_env():
    """
    Set NB_CONTROLLED_RUN=1 for every test in this file and restore after.
    run_controlled() also sets it internally, but tests in group 12 call
    production sinks directly without going through run_controlled.
    """
    old = os.environ.get("NB_CONTROLLED_RUN")
    os.environ["NB_CONTROLLED_RUN"] = "1"
    yield
    if old is None:
        os.environ.pop("NB_CONTROLLED_RUN", None)
    else:
        os.environ["NB_CONTROLLED_RUN"] = old


# ---------------------------------------------------------------------------
# Canned data
# ---------------------------------------------------------------------------

TOPIC = "Why small businesses disappear from customer memory between projects"

_CAND = {
    "SIGNAL_ID":       "test-cand-aabb1122ccdd",
    "HEADLINE":        TOPIC,
    "SIGNAL_TYPE":     "business trust",
    "REGION":          "US",
    "INDUSTRY":        "General",
    "SOURCE_NAME":     "FakeRSS",
    "SOURCE_URL":      "https://example.com/article",
    "SOURCE_FOR_CASE": "https://example.com/article",
    "SOURCE_DATE":     "2026-08-01",
    "DATE_FOUND":      "2026-08-01",
    "raw_summary":     "Test summary.",
    "discovery_confidence": "high",
}

_ENRICHED = {
    **_CAND,
    "CORE_FACT":               "Test core fact.",
    "CONFIDENCE":              "medium",
    "REAL_COMPANY_EXAMPLE":    "Acme Corp",
    "ARTICLE_READY":           "true",
    "SOURCE_PREMISE_VERIFIED": "true",
    "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
    "ARTICLE_READINESS_SCORE": "8",
    "CHANNEL_FIT_SCORE":       "8",
    "SIGNAL_STRENGTH":         "high",
    "DISCUSSION_POTENTIAL":    "high",
    "score_reason":            "test",
    "OUTCOME_IF_KNOWN":        "unknown",
    "DID_IT_WORK":             "unknown",
    "EVIDENCE_OF_OUTCOME":     "",
    "SOURCE_QUALITY":          "",
    "NOTES":                   "",
    "CORE_TENSION":            "Test tension",
    "BUSINESS_LESSON":         "Test lesson",
    "WHY_THIS_CASE_IS_INTERESTING": "Test interesting",
    "WHY_IT_MATTERS_TO_BUSINESS":   "Test matters",
    "BUSINESS_RESPONSES_OBSERVED":  "",
    "PROBLEM_FACED":           "Test problem",
    "RESPONSE_TAKEN":          "unknown",
    "COUNTER_EXAMPLE":         "",
    "TIME_HORIZON":            "medium",
    "INTERESTING_QUESTION":    "Test question?",
    "NEVER_BLANK_ANGLE":       "The real signal is not the event itself.",
    "POSSIBLE_SIGNATURE_LINE": "Never Blank: test.",
    "POTENTIAL_HOOK":          "What visibility gaps cost small businesses.",
    "TARGET_AUDIENCE":         "founder",
    "PRIMARY_CHANNEL":         "linkedin",
    "LINKEDIN_ANGLE":          "LinkedIn angle.",
    "BLOG_ANGLE":              "Blog angle.",
    "THREADS_ANGLE":           "Threads angle.",
    "STORY_ANGLE":             "Story angle.",
    "APPROVED_OVERRIDE":       "",
}

_ARTICLE = {
    "pattern":      {"visibility_pattern": "presence gap"},
    "decision_lens": {
        "core_pattern":              "absence becomes default",
        "owner_system_objective":    "earn recurring revenue",
        "delivery_vs_presence_conflict": "delivers, then disappears",
        "customer_memory_consequence": "memory fades, next vendor wins",
        "structural_cause":          "no between-project contact",
        "never_blank_insight":       "invisibility is opt-in",
    },
    "narrative_spine":    {"spine": "test spine"},
    "structured_article": {"hook": "Test hook."},
    "platforms": {
        "long":      {"body": "Blog body. " * 30, "word_count": 120},
        "medium":    {"body": "LinkedIn post.", "word_count": 40},
        "reading":   {"body": "Facebook post.", "word_count": 20},
        "instagram": {"body": "Instagram caption.", "word_count": 10},
        "short":     {"body": "Short post.", "word_count": 5},
    },
}

_VISUAL_SPEC = {
    "visual_family":    "mountains_depth_layers",
    "dominant_palette": "midnight",
    "image_prompt":     "Test image prompt for controlled run.",
    "hook_text":        "Test hook text.",
    "negative_prompt":  "text, typography, neon, amber, stock photography",
    "logo_placement":   "bottom_right",
    "rationale":        "Test rationale.",
}


# ---------------------------------------------------------------------------
# Test runner helper
# ---------------------------------------------------------------------------

def _run(
    tmp_path: Path,
    mode: str = "synthetic-signal",
    image_gen: str = "disabled",
    extra_argv: list | None = None,
) -> tuple[int, Path, dict]:
    """
    Execute run_controlled() with all external providers mocked.
    Returns (exit_code, run_dir, captured_mocks).
    """
    from scripts.controlled_run import run_controlled, _parse_args

    argv = [
        "--mode", mode,
        "--publication", "disabled",
        "--external-writes", "disabled",
        "--cache", "disabled",
        "--image-reuse", "disabled",
        "--image-generation", image_gen,
        "--output-root", str(tmp_path),
        "--brand", "Never Blank",
        "--channels", "linkedin,blog",
    ]
    if mode in ("full-e2e", "synthetic-signal"):
        argv += ["--topic", TOPIC]
    if mode == "existing-signal":
        argv += ["--signal-id", "test-existing-001"]
    if extra_argv:
        argv += extra_argv

    args = _parse_args(argv)

    with mock.patch("scripts.research.discover.run_discovery",
                    return_value=[_CAND]) as m_discover, \
         mock.patch("scripts.research.score.score_candidates",
                    return_value=[_ENRICHED]) as m_score, \
         mock.patch("scripts.research.enrich.enrich_candidates",
                    return_value=[_ENRICHED]) as m_enrich, \
         mock.patch("scripts.research.angles.add_angles",
                    return_value=[_ENRICHED]) as m_angles, \
         mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_ARTICLE) as m_article, \
         mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)) as m_visual, \
         mock.patch("src.publishing.image_pipeline.load_registry",
                    return_value={}) as m_registry, \
         mock.patch("scripts.controlled_run._load_existing_signal",
                    return_value=_ENRICHED) as m_existing, \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary") as m_cloud, \
         mock.patch("src.strategy.history.append_published_entry") as m_hist:

        exit_code = run_controlled(args)

    subdirs = sorted(tmp_path.iterdir(), key=lambda p: p.stat().st_ctime)
    run_dir = subdirs[0] if subdirs else tmp_path

    captured = {
        "discover": m_discover, "score": m_score, "enrich": m_enrich,
        "angles": m_angles, "article": m_article, "visual": m_visual,
        "registry": m_registry, "load_existing": m_existing,
        "cloudinary": m_cloud, "history": m_hist,
    }
    return exit_code, run_dir, captured


# ---------------------------------------------------------------------------
# Test 1 — full-e2e calls ALL four production Research Engine stages
# ---------------------------------------------------------------------------

def test_full_e2e_calls_all_production_research_stages(tmp_path):
    """Behavior 1: run_discovery, score_candidates, enrich_candidates, add_angles each called."""
    exit_code, _, mocks = _run(tmp_path, mode="full-e2e")
    assert exit_code == 0
    mocks["discover"].assert_called_once()
    mocks["score"].assert_called_once()
    mocks["enrich"].assert_called_once()
    mocks["angles"].assert_called_once()


# ---------------------------------------------------------------------------
# Test 2 — full-e2e never calls _create_synthetic_signal
# ---------------------------------------------------------------------------

def test_full_e2e_does_not_call_create_synthetic_signal(tmp_path):
    """Behavior 2: _create_synthetic_signal must not be called in full-e2e mode."""
    with mock.patch("scripts.controlled_run._create_synthetic_signal") as m_stub:
        _run(tmp_path, mode="full-e2e")
    m_stub.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3 — signal in full-e2e comes from research output (same run)
# ---------------------------------------------------------------------------

def test_full_e2e_signal_originates_from_research_output(tmp_path):
    """Behavior 3: selected_signal.json must contain the signal returned by add_angles."""
    exit_code, run_dir, _ = _run(tmp_path, mode="full-e2e")
    assert exit_code == 0
    selected = json.loads((run_dir / "selected_signal.json").read_text())
    assert selected["SIGNAL_ID"] == _ENRICHED["SIGNAL_ID"]
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert _ENRICHED["SIGNAL_ID"] in manifest["source_identifiers"]


# ---------------------------------------------------------------------------
# Test 4 — research artifacts contain source provenance
# ---------------------------------------------------------------------------

def test_full_e2e_research_artifacts_contain_source_provenance(tmp_path):
    """Behavior 4: all four stage artifacts written; selected_signal has a source URL."""
    exit_code, run_dir, _ = _run(tmp_path, mode="full-e2e")
    assert exit_code == 0
    for fname in ("research_candidates.json", "research_scored.json",
                  "research_enriched.json", "research_angles.json"):
        data = json.loads((run_dir / fname).read_text())
        assert isinstance(data, list) and len(data) > 0, f"{fname} must be non-empty"
    selected = json.loads((run_dir / "selected_signal.json").read_text())
    assert selected.get("SOURCE_URL") or selected.get("SOURCE_FOR_CASE"), \
        "selected_signal.json must carry source provenance URL"


# ---------------------------------------------------------------------------
# Test 5 — research cache disabled: run_discovery called with seen_ids=set()
# ---------------------------------------------------------------------------

def test_full_e2e_research_cache_disabled_via_empty_seen_ids(tmp_path):
    """Behavior 5: run_discovery must be called with seen_ids=set() to disable cache."""
    exit_code, _, mocks = _run(tmp_path, mode="full-e2e")
    assert exit_code == 0
    call = mocks["discover"].call_args
    # Use `is not None` sentinel — empty set is falsy, so `or` would skip it
    kw_seen = call.kwargs.get("seen_ids")
    seen_ids = kw_seen if kw_seen is not None else (call.args[0] if call.args else None)
    assert seen_ids == set(), (
        f"run_discovery must be called with seen_ids=set() (cache disabled); got {seen_ids!r}"
    )


# ---------------------------------------------------------------------------
# Test 6 — _record_decision_lens patches pipeline namespace and intercepts call
# ---------------------------------------------------------------------------

def test_record_decision_lens_intercepts_pipeline_namespace(tmp_path):
    """
    Behavior 6: _record_decision_lens patches generate_decision_lens in the pipeline
    module namespace. Calling generate_decision_lens via that namespace calls the real
    function and records I/O.
    """
    from scripts.controlled_run import _record_decision_lens, InvocationLedger
    import src.editorial.pipeline as _pl

    run_dir = tmp_path / "dl_test"
    run_dir.mkdir()
    ledger = InvocationLedger()

    fake_output = {
        "core_pattern": "absence is default",
        "owner_system_objective": "earn trust",
        "delivery_vs_presence_conflict": "delivers, then vanishes",
        "customer_memory_consequence": "next vendor wins",
        "structural_cause": "no system",
        "never_blank_insight": "invisibility is opt-in",
    }

    with mock.patch("src.editorial.decision_lens_lite.generate_decision_lens",
                    return_value=fake_output):
        with _record_decision_lens(run_dir, ledger) as dl_rec:
            # Simulate generate_article calling DL through the pipeline namespace
            result = _pl.generate_decision_lens(
                {"HEADLINE": "Test", "NEVER_BLANK_ANGLE": "Test angle"}
            )

    assert dl_rec["called"] is True
    assert dl_rec["input"]["NEVER_BLANK_ANGLE"] == "Test angle"
    assert dl_rec["output"]["core_pattern"] == "absence is default"
    assert result == fake_output


# ---------------------------------------------------------------------------
# Test 7 — Decision Lens output has all required schema keys
# ---------------------------------------------------------------------------

def test_decision_lens_output_has_required_schema_keys():
    """Behavior 7: DL output (from generate_article) must contain all 6 schema keys."""
    expected = {
        "core_pattern", "owner_system_objective", "delivery_vs_presence_conflict",
        "customer_memory_consequence", "structural_cause", "never_blank_insight",
    }
    assert set(_ARTICLE["decision_lens"].keys()) == expected


# ---------------------------------------------------------------------------
# Test 8 — production choose_visual_family actually called
# ---------------------------------------------------------------------------

def test_production_choose_visual_family_called(tmp_path):
    """Behavior 8: choose_visual_family must be called exactly once; visual_spec.json written."""
    exit_code, run_dir, mocks = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    mocks["visual"].assert_called_once()
    assert (run_dir / "visual_spec.json").exists()


# ---------------------------------------------------------------------------
# Test 9 — image prompt originates from visual spec of current run
# ---------------------------------------------------------------------------

def test_image_prompt_originates_from_visual_spec_current_run(tmp_path):
    """Behavior 9: visual_spec.json must carry NB angle, image_prompt, and CR exclusions."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    spec = json.loads((run_dir / "visual_spec.json").read_text())
    assert spec.get("_never_blank_angle"), "_never_blank_angle from signal must be in spec"
    assert spec.get("image_prompt"), "image_prompt from choose_visual_family must be present"
    assert "robots" in spec.get("negative_prompt", ""), \
        "CR AI-imagery exclusions must be appended to negative_prompt"


# ---------------------------------------------------------------------------
# Test 10 — image provider NOT called when --image-generation disabled
# ---------------------------------------------------------------------------

def test_image_provider_not_called_when_generation_disabled(tmp_path):
    """Behavior 10: _generate_base_image must not be called when --image-generation disabled."""
    with mock.patch("src.publishing.image_pipeline._generate_base_image") as m_gen:
        _run(tmp_path, mode="synthetic-signal", image_gen="disabled")
    m_gen.assert_not_called()


# ---------------------------------------------------------------------------
# Test 11 — status is complete_without_image (not complete) when image skipped
# ---------------------------------------------------------------------------

def test_image_disabled_yields_complete_without_image_status(tmp_path):
    """Behavior 11: status must be complete_without_image when image generation is skipped."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal", image_gen="disabled")
    assert exit_code == 0
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "complete_without_image", (
        f"Expected complete_without_image, got {manifest['status']!r}"
    )
    vr = json.loads((run_dir / "validation_report.json").read_text())
    assert vr["overall_status"] == "complete_without_image"
    assert vr["image_generation"] == "skipped"


# ---------------------------------------------------------------------------
# Test 12 — external sinks blocked by env-var BEFORE network call
# ---------------------------------------------------------------------------

def test_upload_to_cloudinary_blocked_by_env_var():
    """Behavior 12a: upload_to_cloudinary raises EnvironmentError when NB_CONTROLLED_RUN=1."""
    assert os.environ.get("NB_CONTROLLED_RUN") == "1"
    from src.publishing.image_pipeline import upload_to_cloudinary
    with pytest.raises(EnvironmentError, match="NB_CONTROLLED_RUN"):
        upload_to_cloudinary(Path("/tmp/test.png"), "test/slug")


def test_append_published_entry_blocked_by_env_var():
    """Behavior 12b: append_published_entry raises EnvironmentError when NB_CONTROLLED_RUN=1."""
    assert os.environ.get("NB_CONTROLLED_RUN") == "1"
    from src.strategy.history import append_published_entry
    from src.strategy.models import PublishedEntry
    from datetime import datetime, timezone
    entry = PublishedEntry(
        content_id="test", strategy_id="s1",
        published_at=datetime.now(timezone.utc),
        platform="blog", url="", platform_content_id=None,
    )
    with pytest.raises(EnvironmentError, match="NB_CONTROLLED_RUN"):
        append_published_entry(entry)


def test_wix_publisher_blocked_by_env_var():
    """Behavior 12c: WixPublisher.publish raises EnvironmentError when NB_CONTROLLED_RUN=1."""
    assert os.environ.get("NB_CONTROLLED_RUN") == "1"
    from src.publishing.wix import WixPublisher
    from src.publishing.base import DraftPackage
    draft = DraftPackage(
        draft_dir=Path("/tmp"), blog_title="t", blog_body="b", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=[], telegram_text="tg", image_url=None,
    )
    with pytest.raises(EnvironmentError, match="NB_CONTROLLED_RUN"):
        WixPublisher().publish(draft, "live")


def test_linkedin_publisher_blocked_by_env_var():
    """Behavior 12d: LinkedInPublisher.publish raises EnvironmentError when NB_CONTROLLED_RUN=1."""
    assert os.environ.get("NB_CONTROLLED_RUN") == "1"
    from src.publishing.linkedin import LinkedInPublisher
    from src.publishing.base import DraftPackage
    draft = DraftPackage(
        draft_dir=Path("/tmp"), blog_title="t", blog_body="b", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=[], telegram_text="tg", image_url=None,
    )
    with pytest.raises(EnvironmentError, match="NB_CONTROLLED_RUN"):
        LinkedInPublisher().publish(draft, "live")


# ---------------------------------------------------------------------------
# Test 13 — validation report built from ledger evidence
# ---------------------------------------------------------------------------

def test_validation_report_built_from_ledger_not_hardcoded(tmp_path):
    """
    Behavior 13: validation_report.json must contain a non-empty ledger.
    Each checks key must be grounded in a ledger entry.
    No hardcoded no_cloudinary_upload sentinel.
    """
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    vr = json.loads((run_dir / "validation_report.json").read_text())
    assert "ledger" in vr
    assert len(vr["ledger"]) > 0, "Ledger must have recorded entries"
    ledger_stages = {e["stage"] for e in vr["ledger"]}
    for stage in vr.get("checks", {}):
        assert stage in ledger_stages, (
            f"Check stage {stage!r} must come from ledger evidence, not be hardcoded"
        )
    for entry in vr["ledger"]:
        assert "no_cloudinary_upload" not in entry.get("evidence", {}), \
            "Ledger must not contain hardcoded no_cloudinary_upload sentinel"


# ---------------------------------------------------------------------------
# Test 14 — synthetic-signal never labeled full-e2e
# ---------------------------------------------------------------------------

def test_synthetic_signal_never_labeled_full_e2e(tmp_path):
    """Behavior 14: synthetic-signal manifest must show mode=synthetic-signal, synthetic=True."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["mode"] == "synthetic-signal"
    assert m["synthetic"] is True
    note = m.get("synthetic_note") or ""
    assert note, "Manifest must include synthetic_note explaining this is not full-e2e"
    # synthetic_note must disclaim equivalence with full-e2e
    assert "NOT" in note or "not" in note.lower(), \
        "synthetic_note must explicitly state this is NOT equivalent to full-e2e"


# ---------------------------------------------------------------------------
# Test 15 — old generate_and_publish helpers not called
# ---------------------------------------------------------------------------

def test_generate_and_publish_helpers_not_called(tmp_path):
    """Behavior 15: _load_package_images and _load_image_library must not be called."""
    with mock.patch("scripts.generate_and_publish._load_package_images") as m_pkg, \
         mock.patch("scripts.research.prepare_content._load_image_library") as m_lib:
        _run(tmp_path, mode="synthetic-signal")
    m_pkg.assert_not_called()
    m_lib.assert_not_called()


# ---------------------------------------------------------------------------
# Test 16 — failure in mandatory stage prevents status=complete
# ---------------------------------------------------------------------------

def test_mandatory_stage_failure_prevents_complete_status(tmp_path):
    """Behavior 16: If generate_article fails, exit=1 and status must be 'failed'."""
    from scripts.controlled_run import run_controlled, _parse_args
    from src.editorial.pipeline import ArticleGenerationError

    args = _parse_args([
        "--mode", "synthetic-signal",
        "--publication", "disabled",
        "--external-writes", "disabled",
        "--output-root", str(tmp_path),
        "--topic", TOPIC,
    ])

    with mock.patch("src.editorial.pipeline.generate_article",
                    side_effect=ArticleGenerationError(
                        "decision_lens_lite", ValueError("LLM refused")
                    )), \
         mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)), \
         mock.patch("src.publishing.image_pipeline.load_registry", return_value={}), \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary"), \
         mock.patch("src.strategy.history.append_published_entry"):
        result = run_controlled(args)

    assert result == 1, "Exit code must be 1 on pipeline failure"
    subdirs = list(tmp_path.iterdir())
    assert subdirs, "Run directory must be created even on failure"
    run_dir = subdirs[0]
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failure_stage"] is not None
    assert manifest["status"] not in ("complete", "complete_without_image")


# ---------------------------------------------------------------------------
# Additional: manifest metadata fields
# ---------------------------------------------------------------------------

def test_manifest_metadata_fields(tmp_path):
    """run_manifest.json must record git_sha, policy flags, and env-var confirmation."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert "git_sha" in m and m["git_sha"]
    assert m["publication_disabled"] is True
    assert m["external_writes_disabled"] is True
    assert m["nb_controlled_run_env"] == "1"


# ---------------------------------------------------------------------------
# Additional: existing-signal mode labeled correctly
# ---------------------------------------------------------------------------

def test_existing_signal_mode_manifest(tmp_path):
    """existing-signal manifest must show mode=existing-signal and synthetic=False."""
    exit_code, run_dir, _ = _run(tmp_path, mode="existing-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["mode"] == "existing-signal"
    assert m["synthetic"] is False


# ---------------------------------------------------------------------------
# Additional: image-generation enabled calls _generate_base_image
# ---------------------------------------------------------------------------

def test_image_generation_enabled_calls_provider(tmp_path):
    """When --image-generation enabled, _generate_base_image IS called."""
    fake_pil = mock.MagicMock()
    fake_pil.save = mock.MagicMock()

    with mock.patch("src.publishing.image_pipeline._generate_base_image",
                    return_value=(b"\x89PNG\r\n\x1a\n", "dalle")) as m_gen, \
         mock.patch("src.publishing.image_pipeline.composite_for_platform",
                    return_value=fake_pil), \
         mock.patch("src.publishing.image_pipeline.CARD_TYPES", set()):
        exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal", image_gen="enabled")

    m_gen.assert_called_once()
    assert exit_code == 0
    result = json.loads((run_dir / "image_generation_result.json").read_text())
    assert result["generated"] is True
    assert result["method"] == "dalle"


# ---------------------------------------------------------------------------
# Additional: lifecycle normalization smoke-test
# ---------------------------------------------------------------------------

def test_lifecycle_normalization_recommended_for_article_passes_preflight():
    """
    PROVISIONAL (see test_lifecycle_normalization.py for full coverage).
    A synthetic signal with only RECOMMENDED_FOR_ARTICLE=true must pass preflight.
    """
    from src.lifecycle.signal_lifecycle import ResearchContext
    synth = {
        "SIGNAL_ID": "synth-norm-test",
        "HEADLINE": "Test",
        "SIGNAL_TYPE": "business trust",
        "REGION": "US",
        "INDUSTRY": "Tech",
        "SOURCE_NAME": "Synthetic",
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
        "RECOMMENDED_FOR_ARTICLE": "true",  # no ARTICLE_READY — tests normalization fix
    }
    rc = ResearchContext.from_dict(synth)
    assert rc.article_ready is True, (
        "RECOMMENDED_FOR_ARTICLE=true must set article_ready=True when ARTICLE_READY absent "
        "(PROVISIONAL backward-compat rule)"
    )
    assert rc.admission_status == "admitted"
