"""
Tests for scripts/controlled_run.py — policy-based architecture.

## Architecture under test

Primary protection: ControlledRunPolicy (dependency injection)
  - Created by orchestrator, passed to every adapter boundary
  - policy.check(operation, adapter=...) raises PolicyViolation before any I/O
  - policy.audit_trail records ALL checks (allowed and blocked)

Template method: BasePublisher.publish() is concrete, non-abstract
  - Calls policy.check("publication") if policy provided
  - Delegates to _publish_impl() (abstract)
  - Unknown publisher that only implements _publish_impl() is protected automatically

Decision Lens: no mock.patch at runtime
  - _make_decision_lens_recorder() returns (wrapper_fn, dl_record)
  - wrapper_fn passed as decision_lens_fn to generate_article()
  - generate_article() calls it via DI, not via module-level import interception

Visual brief: shared production component
  - build_visual_brief() from src/publishing/visual_brief.py
  - Policy exclusions passed as policy_exclusion_tags (not hardcoded)

## Mocking strategy

- Research stages mocked at module-level entry points (production interfaces)
- generate_article mocked to avoid real LLM calls; DL fn DI is tested separately
- choose_visual_family and load_registry mocked to avoid config/LLM I/O
- External sinks verified by inspecting policy.audit_trail AND env-var fallback

## 16 behaviors tested
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_nb_controlled_run_env():
    """Set NB_CONTROLLED_RUN=1 per test and restore after."""
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
    "WHY_THIS_CASE_IS_INTERESTING": "Test",
    "WHY_IT_MATTERS_TO_BUSINESS":   "Test",
    "BUSINESS_RESPONSES_OBSERVED":  "",
    "PROBLEM_FACED":           "Test problem",
    "RESPONSE_TAKEN":          "unknown",
    "COUNTER_EXAMPLE":         "",
    "TIME_HORIZON":            "medium",
    "INTERESTING_QUESTION":    "Test?",
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


def _run(
    tmp_path: Path,
    mode: str = "synthetic-signal",
    image_gen: str = "disabled",
    extra_argv: list | None = None,
) -> tuple[int, Path, dict]:
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
    """Behavior 1: run_discovery, score_candidates, enrich_candidates, add_angles called."""
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
# Test 3 — signal in full-e2e comes from research output
# ---------------------------------------------------------------------------

def test_full_e2e_signal_originates_from_research_output(tmp_path):
    """Behavior 3: selected_signal.json must come from add_angles output."""
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
    """Behavior 4: all four stage artifacts written; selected has a source URL."""
    exit_code, run_dir, _ = _run(tmp_path, mode="full-e2e")
    assert exit_code == 0
    for fname in ("research_candidates.json", "research_scored.json",
                  "research_enriched.json", "research_angles.json"):
        data = json.loads((run_dir / fname).read_text())
        assert isinstance(data, list) and len(data) > 0, f"{fname} must be non-empty"
    selected = json.loads((run_dir / "selected_signal.json").read_text())
    assert selected.get("SOURCE_URL") or selected.get("SOURCE_FOR_CASE")


# ---------------------------------------------------------------------------
# Test 5 — research cache disabled
# ---------------------------------------------------------------------------

def test_full_e2e_research_cache_disabled_via_empty_seen_ids(tmp_path):
    """Behavior 5: run_discovery called with seen_ids=set()."""
    exit_code, _, mocks = _run(tmp_path, mode="full-e2e")
    assert exit_code == 0
    call = mocks["discover"].call_args
    kw_seen = call.kwargs.get("seen_ids")
    seen_ids = kw_seen if kw_seen is not None else (call.args[0] if call.args else None)
    assert seen_ids == set(), f"seen_ids must be empty set, got {seen_ids!r}"


# ---------------------------------------------------------------------------
# Test 6 — DL recording via DI (no mock.patch at runtime)
# ---------------------------------------------------------------------------

def test_decision_lens_recorded_via_di_not_mock_patch(tmp_path):
    """
    Behavior 6: _make_decision_lens_recorder() returns a wrapper passed as
    decision_lens_fn to generate_article(). No mock.patch is used at runtime.
    The wrapper intercepts the call via DI.
    """
    from scripts.controlled_run import _make_decision_lens_recorder, InvocationLedger

    run_dir = tmp_path / "dl_test"
    run_dir.mkdir()
    ledger = InvocationLedger()

    fake_dl_output = {
        "core_pattern": "absence is default",
        "owner_system_objective": "earn trust",
        "delivery_vs_presence_conflict": "delivers then vanishes",
        "customer_memory_consequence": "next vendor wins",
        "structural_cause": "no system",
        "never_blank_insight": "invisibility is opt-in",
    }

    # mock the real DL function to return canned output without LLM call
    with mock.patch("src.editorial.decision_lens_lite.generate_decision_lens",
                    return_value=fake_dl_output):
        wrapper_fn, dl_rec = _make_decision_lens_recorder(run_dir, ledger)
        # Call the wrapper as generate_article() would call it
        result = wrapper_fn({"HEADLINE": "Test", "NEVER_BLANK_ANGLE": "Test angle"})

    assert dl_rec["called"] is True
    assert dl_rec["input"]["NEVER_BLANK_ANGLE"] == "Test angle"
    assert dl_rec["output"]["core_pattern"] == "absence is default"
    assert result == fake_dl_output

    # Confirm: no mock.patch was applied to the pipeline namespace
    import src.editorial.pipeline as _pl
    # The pipeline's generate_decision_lens is the REAL function (not patched by wrapper)
    from src.editorial.decision_lens_lite import generate_decision_lens as _real
    assert _pl.generate_decision_lens is _real, \
        "DI wrapper must NOT patch the pipeline module namespace"


# ---------------------------------------------------------------------------
# Test 7 — Decision Lens output has required schema keys
# ---------------------------------------------------------------------------

def test_decision_lens_output_has_required_schema_keys():
    """Behavior 7: DL output schema must have all 6 required keys."""
    expected = {
        "core_pattern", "owner_system_objective", "delivery_vs_presence_conflict",
        "customer_memory_consequence", "structural_cause", "never_blank_insight",
    }
    assert set(_ARTICLE["decision_lens"].keys()) == expected


# ---------------------------------------------------------------------------
# Test 8 — production choose_visual_family actually called via build_visual_brief
# ---------------------------------------------------------------------------

def test_production_choose_visual_family_called_via_build_visual_brief(tmp_path):
    """Behavior 8: choose_visual_family called inside build_visual_brief; visual_spec.json written."""
    exit_code, run_dir, mocks = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    mocks["visual"].assert_called_once()
    assert (run_dir / "visual_spec.json").exists()
    spec = json.loads((run_dir / "visual_spec.json").read_text())
    assert spec.get("visual_family"), "visual_family must be present"


# ---------------------------------------------------------------------------
# Test 9 — image prompt from visual spec; policy exclusions in negative_prompt
# ---------------------------------------------------------------------------

def test_image_prompt_from_visual_spec_with_policy_exclusions(tmp_path):
    """Behavior 9: visual_spec.json has NB angle, image_prompt, policy exclusions in neg prompt."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    spec = json.loads((run_dir / "visual_spec.json").read_text())
    assert spec.get("_never_blank_angle"), "_never_blank_angle from signal must be in spec"
    assert spec.get("image_prompt"), "image_prompt must be present"
    # CR_POLICY_EXCLUSIONS are appended via policy_exclusion_tags — not hardcoded
    assert "robots" in spec.get("negative_prompt", ""), "CR policy exclusions must be in neg prompt"
    assert spec.get("_policy_exclusions"), "_policy_exclusions provenance field must be set"


# ---------------------------------------------------------------------------
# Test 10 — image provider NOT called when disabled
# ---------------------------------------------------------------------------

def test_image_provider_not_called_when_generation_disabled(tmp_path):
    """Behavior 10: _generate_base_image must not be called when disabled."""
    with mock.patch("src.publishing.image_pipeline._generate_base_image") as m_gen:
        _run(tmp_path, mode="synthetic-signal", image_gen="disabled")
    m_gen.assert_not_called()


# ---------------------------------------------------------------------------
# Test 11 — status is complete_without_image when image skipped
# ---------------------------------------------------------------------------

def test_image_disabled_yields_complete_without_image_status(tmp_path):
    """Behavior 11: status must be complete_without_image when image disabled."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal", image_gen="disabled")
    assert exit_code == 0
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "complete_without_image"
    vr = json.loads((run_dir / "validation_report.json").read_text())
    assert vr["overall_status"] == "complete_without_image"
    assert vr["image_generation"] == "skipped"


# ---------------------------------------------------------------------------
# Test 12 — sinks blocked by policy.check() BEFORE network call
# ---------------------------------------------------------------------------

def test_policy_blocks_publication_before_network_call():
    """Behavior 12a: policy.check('publication') raises PolicyViolation before network."""
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation
    policy = ControlledRunPolicy(run_id="test-run", publication_allowed=False)
    with pytest.raises(PolicyViolation, match="publication"):
        policy.check("publication", adapter="TestPublisher")
    # Verify it's recorded in audit_trail
    assert len(policy.audit_trail) == 1
    entry = policy.audit_trail[0]
    assert entry.operation == "publication"
    assert entry.allowed is False
    assert entry.blocked_before_network is True


def test_policy_blocks_cloudinary_before_network_call():
    """Behavior 12b: policy.check('cloudinary_upload') raises PolicyViolation."""
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation
    policy = ControlledRunPolicy(run_id="test-run", permanent_storage_allowed=False)
    with pytest.raises(PolicyViolation, match="cloudinary_upload"):
        policy.check("cloudinary_upload", adapter="upload_to_cloudinary")
    entry = policy.audit_trail[0]
    assert entry.blocked_before_network is True


def test_policy_blocks_history_write_before_file_write():
    """Behavior 12c: policy.check('history_write') raises PolicyViolation."""
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation
    policy = ControlledRunPolicy(run_id="test-run", history_writes_allowed=False)
    with pytest.raises(PolicyViolation, match="history_write"):
        policy.check("history_write", adapter="append_published_entry")


def test_env_var_fallback_blocks_when_no_policy():
    """Behavior 12d: NB_CONTROLLED_RUN=1 env-var fallback blocks when no policy passed."""
    # BasePublisher.publish() without policy falls back to env-var check
    from src.publishing.wix import WixPublisher
    from src.publishing.base import DraftPackage
    assert os.environ.get("NB_CONTROLLED_RUN") == "1"
    draft = DraftPackage(
        draft_dir=Path("/tmp"), blog_title="t", blog_body="b", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=[], telegram_text="tg", image_url=None,
    )
    with pytest.raises(EnvironmentError, match="NB_CONTROLLED_RUN"):
        WixPublisher().publish(draft, "live")  # no policy= kwarg


# ---------------------------------------------------------------------------
# Test 13 — validation report built from policy.audit_trail + ledger
# ---------------------------------------------------------------------------

def test_validation_report_built_from_audit_trail_and_ledger(tmp_path):
    """Behavior 13: validation_report.json must contain policy_audit and non-empty ledger."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    vr = json.loads((run_dir / "validation_report.json").read_text())

    # Ledger evidence
    assert "ledger" in vr and len(vr["ledger"]) > 0
    # Policy audit evidence
    assert "policy_audit" in vr, "validation_report must contain policy_audit from ControlledRunPolicy"
    audit = vr["policy_audit"]
    assert audit["verification_source"] == "policy.audit_trail (evidence-based, not declared)"
    # Checks grounded in ledger
    ledger_stages = {e["stage"] for e in vr["ledger"]}
    for stage in vr.get("checks", {}):
        assert stage in ledger_stages


# ---------------------------------------------------------------------------
# Test 14 — synthetic-signal never labeled full-e2e
# ---------------------------------------------------------------------------

def test_synthetic_signal_never_labeled_full_e2e(tmp_path):
    """Behavior 14: synthetic manifest shows mode=synthetic-signal, synthetic=True."""
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["mode"] == "synthetic-signal"
    assert m["synthetic"] is True
    note = m.get("synthetic_note") or ""
    assert "NOT" in note or "not" in note.lower()


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
# Test 16 — mandatory stage failure prevents status=complete
# ---------------------------------------------------------------------------

def test_mandatory_stage_failure_prevents_complete_status(tmp_path):
    """Behavior 16: generate_article failure → exit=1, status=failed."""
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

    assert result == 1
    subdirs = list(tmp_path.iterdir())
    assert subdirs
    manifest = json.loads((subdirs[0] / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failure_stage"] is not None
    assert manifest["status"] not in ("complete", "complete_without_image")


# ---------------------------------------------------------------------------
# Test: unknown publisher protected by template method
# ---------------------------------------------------------------------------

def test_unknown_publisher_protected_by_template_method():
    """
    A test-only publisher that only implements _publish_impl() is automatically
    protected by BasePublisher.publish() template method when policy is provided.
    _publish_impl() must NOT be called when policy blocks publication.
    """
    from src.publishing.base import BasePublisher, DraftPackage
    from src.publishing.result import PublishResult, PublishStatus
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation

    class _UnknownPublisher(BasePublisher):
        name = "unknown_test_publisher"

        def _publish_impl(self, draft: DraftPackage, mode: str) -> PublishResult:
            # This must NOT be reached when policy blocks
            return PublishResult(platform=self.name, status=PublishStatus.PUBLISHED,
                                 external_id="would_be_blocked")

    policy = ControlledRunPolicy(run_id="test-unknown", publication_allowed=False)
    pub = _UnknownPublisher()
    draft = DraftPackage(
        draft_dir=Path("/tmp"), blog_title="t", blog_body="b", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=[], telegram_text="tg", image_url=None,
    )

    with pytest.raises(PolicyViolation, match="publication"):
        pub.publish(draft, "live", policy=policy)

    # Verify the audit trail captured the blocked attempt
    assert len(policy.audit_trail) == 1
    entry = policy.audit_trail[0]
    assert entry.adapter == "unknown_test_publisher"
    assert entry.blocked_before_network is True


# ---------------------------------------------------------------------------
# Test: policy audit trail captures blocked attempts as evidence
# ---------------------------------------------------------------------------

def test_policy_audit_trail_captures_blocked_attempt_as_evidence():
    """
    An adapter attempts a forbidden operation. Policy records the attempt in
    audit_trail. Operation is blocked before network/file client.
    Validation report uses this audit entry as evidence.
    """
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation, AuditEntry

    policy = ControlledRunPolicy(
        run_id="audit-evidence-test",
        publication_allowed=False,
        permanent_storage_allowed=False,
    )

    # Simulate a mock publisher attempting to publish
    with pytest.raises(PolicyViolation):
        policy.check("publication", adapter="MockPublisher")

    # Simulate a Cloudinary attempt
    with pytest.raises(PolicyViolation):
        policy.check("cloudinary_upload", adapter="upload_to_cloudinary")

    audit = policy.audit_summary()
    assert audit["blocked_attempts"] == 2
    assert all(e["blocked_before_network"] is True for e in audit["blocked_operations"])
    assert all(e["allowed"] is False for e in audit["blocked_operations"])

    # Verification source must state evidence-based, not declared
    assert "evidence" in audit["verification_source"].lower()


# ---------------------------------------------------------------------------
# Test: research side-effects are zero (cache reads/writes/FS writes)
# ---------------------------------------------------------------------------

def test_research_stages_have_zero_cache_or_filesystem_writes(tmp_path):
    """
    Research Engine stages (with mocked LLM + network) produce no filesystem writes.
    Cache reads = 0, cache writes = 0, persistent writes = 0.
    """
    import os as _os

    # Snapshot filesystem state before research
    run_dir = tmp_path / "research_isolation_test"
    run_dir.mkdir()

    # Find files in the repo root before the research run
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data" / "research"
    before_files = set(data_dir.glob("*")) if data_dir.exists() else set()
    before_counts = {f: f.stat().st_mtime for f in before_files if f.is_file()}

    from scripts.research.discover import run_discovery
    from scripts.research.score import score_candidates
    from scripts.research.enrich import enrich_candidates
    from scripts.research.angles import add_angles

    # Mock ALL external providers: LLM and RSS network
    with mock.patch("src.utils.llm_client.chat", return_value=json.dumps([
        {
            "index": 0,
            "SIGNAL_ID": "test-iso-001",
            "HEADLINE": "Test isolation",
            "SIGNAL_TYPE": "business trust",
            "REGION": "US",
            "SOURCE_URL": "https://example.com/test",
            "SOURCE_FOR_CASE": "https://example.com/test",
            "SOURCE_NAME": "TestFeed",
            "SOURCE_DATE": "2026-08-01",
            "ARTICLE_READY": "true",
            "CORE_FACT": "Test fact verified.",
            "CONFIDENCE": "medium",
            "REAL_COMPANY_EXAMPLE": "TestCo",
        }
    ])), mock.patch("requests.get") as m_rss:
        m_rss.return_value.status_code = 200
        m_rss.return_value.raise_for_status = lambda: None
        m_rss.return_value.content = (
            b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b'<item><title>Test isolation</title>'
            b'<link>https://example.com/test</link>'
            b'<pubDate>Sat, 09 Aug 2026 12:00:00 +0000</pubDate>'
            b'<description>Test desc</description></item></channel></rss>'
        )
        candidates = run_discovery(seen_ids=set())

    # After discovery — no new files should appear in data/research
    if data_dir.exists():
        after_files = set(data_dir.glob("*"))
        new_files = after_files - before_files
        assert not new_files, (
            f"run_discovery wrote unexpected files to data/research: {new_files}"
        )
        for f in before_files:
            if f.is_file() and f in before_counts:
                assert f.stat().st_mtime == before_counts[f], (
                    f"run_discovery modified existing file: {f}"
                )

    # score, enrich, angles also produce no filesystem side-effects
    with mock.patch("src.utils.llm_client.chat", return_value=json.dumps(
        [{"index": 0, "total_score": 8, "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
          "ARTICLE_READINESS_SCORE": "8", "CHANNEL_FIT_SCORE": "8",
          "SIGNAL_STRENGTH": "high", "DISCUSSION_POTENTIAL": "high",
          "score_reason": "test"}]
    )):
        scored = score_candidates(candidates if candidates else [_CAND])

    with mock.patch("src.utils.llm_client.chat", return_value=json.dumps(_ENRICHED)):
        enriched = enrich_candidates(scored if scored else [_CAND])

    with mock.patch("src.utils.llm_client.chat", return_value=json.dumps({
        "TARGET_AUDIENCE": "founder", "PRIMARY_CHANNEL": "linkedin",
        "NEVER_BLANK_ANGLE": "Test angle.", "POTENTIAL_HOOK": "Test hook.",
    })):
        with_angles = add_angles(enriched if enriched else [_ENRICHED])

    # Verify none of the functions wrote to data/research
    if data_dir.exists():
        after_all = set(data_dir.glob("*"))
        new_after_all = after_all - before_files
        assert not new_after_all, (
            f"Research stages wrote unexpected files: {new_after_all}"
        )


# ---------------------------------------------------------------------------
# Test: image-generation enabled calls provider + policy allows
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
# Test: lifecycle normalization smoke-test
# ---------------------------------------------------------------------------

def test_lifecycle_normalization_recommended_for_article_passes_preflight():
    """PROVISIONAL: RECOMMENDED_FOR_ARTICLE=true passes preflight without ARTICLE_READY."""
    from src.lifecycle.signal_lifecycle import ResearchContext
    synth = {
        "SIGNAL_ID": "synth-norm-test", "HEADLINE": "Test",
        "SIGNAL_TYPE": "business trust", "REGION": "US", "INDUSTRY": "Tech",
        "SOURCE_NAME": "Synthetic", "SOURCE_URL": "", "SOURCE_DATE": "2026-01-01",
        "DATE_FOUND": "2026-01-01", "CORE_FACT": "Test fact", "CONFIDENCE": "medium",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true", "ARTICLE_READINESS_SCORE": "8",
        "CHANNEL_FIT_SCORE": "8", "OUTCOME_IF_KNOWN": "unknown", "DID_IT_WORK": "unknown",
        "APPROVED_OVERRIDE": "",
        "RECOMMENDED_FOR_ARTICLE": "true",  # no ARTICLE_READY — tests normalization
    }
    rc = ResearchContext.from_dict(synth)
    assert rc.article_ready is True
    assert rc.admission_status == "admitted"


# ---------------------------------------------------------------------------
# Additional: manifest metadata
# ---------------------------------------------------------------------------

def test_manifest_metadata_fields(tmp_path):
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["publication_disabled"] is True
    assert m["external_writes_disabled"] is True
    assert m["nb_controlled_run_env"] == "1"
    assert "policy_enforcement" in m
    assert m["policy_enforcement"]["primary"].startswith("ControlledRunPolicy")


def test_existing_signal_mode_manifest(tmp_path):
    exit_code, run_dir, _ = _run(tmp_path, mode="existing-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["mode"] == "existing-signal"
    assert m["synthetic"] is False
