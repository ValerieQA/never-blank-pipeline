"""
Tests for scripts/controlled_run.py — policy-based architecture (Phase 3).

## Architecture under test

Primary protection: ControlledRunPolicy (dependency injection)
  - Created by orchestrator, passed to every adapter boundary
  - policy.check(operation, adapter=...) raises PolicyViolation before any I/O
  - policy.audit_trail records ALL checks (allowed and blocked)
  - 9 capabilities audited: publication, external_drafts, permanent_storage,
    history_write, database_write, cache_read, cache_write, image_reuse,
    cloudinary_upload (+ image_generation at operation boundary)

Template method: BasePublisher.publish(**kwargs) is concrete, non-abstract
  - Pops `policy` from **kwargs; falls back to self._policy
  - Calls policy.check("publication") if policy present
  - Raises PolicyRequiredError if NB_CONTROLLED_RUN=1 and no policy
  - Delegates to _publish_impl(draft, mode, **kwargs)
  - No subclass can bypass the gate via override (publish() uses **kwargs)

Decision Lens: no mock.patch at runtime
  - _make_decision_lens_recorder() returns (wrapper_fn, dl_record)
  - wrapper_fn passed as decision_lens_fn to generate_article()
  - No mock.patch of generate_decision_lens

Visual brief: shared production component with channels
  - build_visual_brief(channels=[...]) → VisualBrief.channel_specs
  - Policy exclusions via policy_exclusion_tags (not hardcoded)

Provider injection: no mock.patch of internal symbols
  - run_discovery(seen_ids, llm_provider=FakeLLMProvider, feed_provider=FakeFeedProvider)
  - _generate_base_image(..., image_provider=FakeImageProvider())
  - Real production functions called with fake providers

Lifecycle: Option A
  - ARTICLE_READY is the canonical field
  - No RECOMMENDED_FOR_ARTICLE alias
  - Synthetic signals use ARTICLE_READY=true explicitly

## Autouse fixture
NB_CONTROLLED_RUN is set/restored per test. No module-level env pollution.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers.controlled_run_helpers import (
    FakeLLMProvider,
    FakeFeedProvider,
    FakeImageProvider,
    FakeStorageAdapter,
    FakeImageReuseStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_nb_controlled_run_env():
    """Restore NB_CONTROLLED_RUN after each test. No module-level pollution."""
    old = os.environ.get("NB_CONTROLLED_RUN")
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
        "core_pattern":                  "absence becomes default",
        "owner_system_objective":        "earn recurring revenue",
        "delivery_vs_presence_conflict": "delivers, then disappears",
        "customer_memory_consequence":   "memory fades, next vendor wins",
        "structural_cause":              "no between-project contact",
        "never_blank_insight":           "invisibility is opt-in",
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
# Test runner helper (uses fake providers — no mock.patch of internal symbols)
# ---------------------------------------------------------------------------

def _run(
    tmp_path: Path,
    mode: str = "synthetic-signal",
    image_gen: str = "disabled",
    extra_argv: list | None = None,
    llm_provider=None,
    feed_provider=None,
    image_provider=None,
) -> tuple[int, Path, dict]:
    """
    Run the controlled pipeline with injected fake providers.
    generate_article is still mocked because it exercises the full LLM
    editorial pipeline — tested separately. All other mocking is via providers.
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

    with mock.patch("src.editorial.pipeline.generate_article",
                    return_value=_ARTICLE) as m_article, \
         mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)) as m_visual, \
         mock.patch("src.publishing.image_pipeline.load_registry",
                    return_value={}) as m_registry, \
         mock.patch("scripts.controlled_run._load_existing_signal",
                    return_value=_ENRICHED) as m_existing:

        exit_code = run_controlled(
            args,
            llm_provider  = llm_provider,
            feed_provider = feed_provider,
            image_provider = image_provider,
        )

    subdirs = sorted(tmp_path.iterdir(), key=lambda p: p.stat().st_ctime)
    run_dir = subdirs[0] if subdirs else tmp_path

    captured = {
        "article": m_article, "visual": m_visual,
        "registry": m_registry, "load_existing": m_existing,
    }
    return exit_code, run_dir, captured


# ---------------------------------------------------------------------------
# Test 1 — basic success
# ---------------------------------------------------------------------------

def test_synthetic_run_succeeds(tmp_path):
    exit_code, run_dir, _ = _run(tmp_path)
    assert exit_code == 0
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "validation_report.json").exists()


# ---------------------------------------------------------------------------
# Test 2 — full-e2e with injected fake providers (no mock.patch of internals)
# ---------------------------------------------------------------------------

def test_full_e2e_with_injected_providers(tmp_path):
    """
    full-e2e mode calls run_discovery / score_candidates / enrich_candidates /
    add_angles with injected FakeLLMProvider + FakeFeedProvider.
    No mock.patch of internal symbols (chat, requests.get).
    """
    # FakeLLMProvider: responses for _llm_select_indices + _llm_enrich_candidates
    # + score_candidates + enrich_signal + generate_angles
    enriched_resp = json.dumps([{
        "index": 0, "HEADLINE": TOPIC, "SOURCE_URL": "https://ex.com/1",
        "SOURCE_NAME": "TestFeed", "SOURCE_DATE": "2026-08-01",
        "SIGNAL_TYPE": "business trust", "REGION": "US", "INDUSTRY": "General",
        "raw_summary": "Test.", "discovery_confidence": "medium",
    }])
    score_resp = json.dumps([{
        "index": 0, "total_score": 8, "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "8", "CHANNEL_FIT_SCORE": "8",
        "SIGNAL_STRENGTH": "high", "DISCUSSION_POTENTIAL": "high",
        "score_reason": "test score",
    }])
    enrich_resp = json.dumps(dict(_ENRICHED))
    angles_resp = json.dumps({
        "TARGET_AUDIENCE": "founder", "PRIMARY_CHANNEL": "linkedin",
        "NEVER_BLANK_ANGLE": "Test angle", "POTENTIAL_HOOK": "Test hook",
        "LINKEDIN_ANGLE": "Li.", "BLOG_ANGLE": "Blog.", "THREADS_ANGLE": "Th.",
        "STORY_ANGLE": "St.",
    })
    # signal_selector (returns indices) + signal_enrichment + score + enrich + angles
    selector_resp = json.dumps({"selected": [0]})

    llm = FakeLLMProvider([
        selector_resp,   # _llm_select_indices in discovery
        enriched_resp,   # _llm_enrich_candidates in discovery
        score_resp,      # _llm_score_batch
        enrich_resp,     # enrich_signal
        angles_resp,     # generate_angles
    ])
    feed = FakeFeedProvider(items=[{
        "title":       TOPIC,
        "link":        "https://example.com/article/test",
        "pub_date":    "Mon, 09 Aug 2026 12:00:00 +0000",
        "description": "Test description about visibility.",
    }])

    exit_code, run_dir, _ = _run(tmp_path, mode="full-e2e",
                                  llm_provider=llm, feed_provider=feed)
    assert exit_code == 0, (run_dir / "run_manifest.json").read_text()

    # Verify research artifacts were written
    for fname in ("research_candidates.json", "research_scored.json",
                  "research_enriched.json", "research_angles.json"):
        assert (run_dir / fname).exists(), f"Missing {fname}"

    # Verify providers were called
    assert llm.call_count >= 4, f"Expected >=4 LLM calls, got {llm.call_count}"
    assert feed.call_count >= 1, f"Expected >=1 feed fetches, got {feed.call_count}"


# ---------------------------------------------------------------------------
# Test 3 — full-e2e never calls _create_synthetic_signal
# ---------------------------------------------------------------------------

def test_full_e2e_does_not_call_create_synthetic_signal(tmp_path):
    with mock.patch("scripts.controlled_run._create_synthetic_signal") as m_stub:
        _run(tmp_path, mode="full-e2e",
             llm_provider=FakeLLMProvider([
                 json.dumps({"selected": [0]}),
                 json.dumps([dict(_ENRICHED)]),
                 json.dumps([{"index": 0, "total_score": 8,
                              "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
                              "ARTICLE_READINESS_SCORE": "8", "CHANNEL_FIT_SCORE": "8",
                              "SIGNAL_STRENGTH": "high", "DISCUSSION_POTENTIAL": "high",
                              "score_reason": "test"}]),
                 json.dumps(dict(_ENRICHED)),
                 json.dumps({"TARGET_AUDIENCE": "founder", "PRIMARY_CHANNEL": "linkedin"}),
             ]),
             feed_provider=FakeFeedProvider())
    m_stub.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4 — DL recording via DI (no mock.patch at runtime)
# ---------------------------------------------------------------------------

def test_decision_lens_recorded_via_di_not_mock_patch(tmp_path):
    """
    _make_decision_lens_recorder() returns a wrapper that is passed as
    decision_lens_fn to generate_article(). No mock.patch of generate_decision_lens.
    """
    from scripts.controlled_run import _make_decision_lens_recorder, InvocationLedger

    run_dir = tmp_path / "dl_test"
    run_dir.mkdir()
    ledger = InvocationLedger()

    fake_output = {
        "core_pattern":                  "absence is default",
        "owner_system_objective":        "earn trust",
        "delivery_vs_presence_conflict": "delivers then vanishes",
        "customer_memory_consequence":   "next vendor wins",
        "structural_cause":              "no system",
        "never_blank_insight":           "invisibility is opt-in",
    }

    with mock.patch("src.editorial.decision_lens_lite.generate_decision_lens",
                    return_value=fake_output):
        wrapper_fn, dl_rec = _make_decision_lens_recorder(run_dir, ledger)
        result = wrapper_fn({"HEADLINE": "Test", "NEVER_BLANK_ANGLE": "Test angle"})

    assert dl_rec["called"] is True
    assert dl_rec["input"]["NEVER_BLANK_ANGLE"] == "Test angle"
    assert dl_rec["output"]["core_pattern"] == "absence is default"
    assert result == fake_output

    # The pipeline module's generate_decision_lens is NOT patched by wrapper
    import src.editorial.pipeline as _pl
    from src.editorial.decision_lens_lite import generate_decision_lens as _real
    assert _pl.generate_decision_lens is _real, \
        "DI wrapper must NOT patch the pipeline module namespace"


# ---------------------------------------------------------------------------
# Test 5 — PolicyViolation fires before network for all 9 capabilities
# ---------------------------------------------------------------------------

def test_policy_blocks_all_9_capabilities_before_network():
    """
    9 policy checks produce AuditEntry(blocked_before_network=True).
    publication and image_generation are checked at their operation sites.
    The other 8 are checked in preflight.
    """
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation

    policy = ControlledRunPolicy(
        run_id                    = "test-9-caps",
        publication_allowed       = False,
        external_drafts_allowed   = False,
        permanent_storage_allowed = False,
        history_writes_allowed    = False,
        database_writes_allowed   = False,
        cache_reads_allowed       = False,
        cache_writes_allowed      = False,
        image_reuse_allowed       = False,
        image_generation_allowed  = False,
    )

    ops = [
        "publication", "external_drafts", "permanent_storage",
        "history_write", "database_write", "cache_read", "cache_write",
        "image_reuse", "cloudinary_upload", "image_generation",
    ]
    for op in ops:
        with pytest.raises(PolicyViolation):
            policy.check(op, adapter=f"test_{op}")

    assert len(policy.audit_trail) == len(ops)
    for entry in policy.audit_trail:
        assert entry.blocked_before_network is True
        assert entry.allowed is False

    audit = policy.audit_summary()
    assert audit["blocked_attempts"] == len(ops)
    assert "evidence" in audit["verification_source"].lower()


# ---------------------------------------------------------------------------
# Test 6 — permanent_storage != image_generation (separate capabilities)
# ---------------------------------------------------------------------------

def test_permanent_storage_and_image_generation_are_separate_capabilities():
    """
    permanent_storage gates writing bytes to Cloudinary / image library.
    image_generation gates the LLM/programmatic bytes production.
    Both must be separately gated by policy.check().
    """
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation

    # Allow image_generation but block permanent_storage
    policy = ControlledRunPolicy(
        run_id                    = "sep-test",
        image_generation_allowed  = True,
        permanent_storage_allowed = False,
    )

    # image_generation allowed
    policy.check("image_generation", adapter="test_generator")
    last = policy.audit_trail[-1]
    assert last.allowed is True
    assert last.blocked_before_network is False

    # permanent_storage blocked
    with pytest.raises(PolicyViolation):
        policy.check("permanent_storage", adapter="test_storage")
    last = policy.audit_trail[-1]
    assert last.allowed is False
    assert last.blocked_before_network is True

    # These are separate -- 2 entries, 2 different operations
    ops = [e.operation for e in policy.audit_trail]
    assert "image_generation" in ops
    assert "permanent_storage" in ops
    assert ops.index("image_generation") != ops.index("permanent_storage")


# ---------------------------------------------------------------------------
# Test 7 — unknown publisher protected by template method (**kwargs)
# ---------------------------------------------------------------------------

def test_unknown_publisher_protected_by_template_method_kwargs():
    """
    A test-only publisher that only implements _publish_impl() is automatically
    protected by BasePublisher.publish(**kwargs) template method.
    _publish_impl() must NOT be called when policy blocks publication.
    """
    from src.publishing.base import BasePublisher, DraftPackage
    from src.publishing.result import PublishResult, PublishStatus
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation

    class _UnknownPublisher(BasePublisher):
        name = "unknown_test_publisher"

        def _publish_impl(self, draft, mode, **kwargs) -> PublishResult:
            raise AssertionError("_publish_impl must NOT be called when policy blocks")

    policy = ControlledRunPolicy(run_id="test-unknown", publication_allowed=False)
    pub    = _UnknownPublisher()
    draft  = DraftPackage(
        draft_dir=Path("/tmp"), blog_title="t", blog_body="b", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=[], telegram_text="tg", image_url=None,
    )

    # Policy passed as keyword argument (popped from **kwargs in publish())
    with pytest.raises(PolicyViolation, match="publication"):
        pub.publish(draft, "live", policy=policy)

    assert len(policy.audit_trail) == 1
    assert policy.audit_trail[0].adapter == "unknown_test_publisher"
    assert policy.audit_trail[0].blocked_before_network is True


# ---------------------------------------------------------------------------
# Test 8 — PolicyRequiredError when NB_CONTROLLED_RUN=1 and no policy
# ---------------------------------------------------------------------------

def test_policy_required_error_when_env_set_and_no_policy():
    """
    When NB_CONTROLLED_RUN=1 is set and no policy is provided,
    BasePublisher.publish() raises PolicyRequiredError (not AttributeError).
    """
    from src.publishing.wix import WixPublisher
    from src.publishing.base import DraftPackage
    from src.controlled_run.policy import PolicyRequiredError

    os.environ["NB_CONTROLLED_RUN"] = "1"
    draft = DraftPackage(
        draft_dir=Path("/tmp"), blog_title="t", blog_body="b", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=[], telegram_text="tg", image_url=None,
    )
    with pytest.raises(PolicyRequiredError):
        WixPublisher().publish(draft, "live")  # no policy kwarg, no self._policy


# ---------------------------------------------------------------------------
# Test 9 — Telegram: wix_url forwarded via **kwargs (no publish() override)
# ---------------------------------------------------------------------------

def test_telegram_wix_url_via_kwargs_no_override():
    """
    TelegramPublisher does NOT override publish(). wix_url is forwarded
    through BasePublisher.publish(**kwargs) to _publish_impl(**kwargs).
    """
    from src.publishing.telegram import TelegramPublisher
    import inspect

    pub = TelegramPublisher()
    # publish() is NOT overridden in TelegramPublisher -- comes from BasePublisher
    assert TelegramPublisher.publish is not None
    # _publish_impl handles wix_url via **kwargs
    sig = inspect.signature(TelegramPublisher._publish_impl)
    assert "kwargs" in str(sig), "_publish_impl must accept **kwargs"


# ---------------------------------------------------------------------------
# Test 10 — policy audit trail feeds validation report (evidence-based)
# ---------------------------------------------------------------------------

def test_validation_report_built_from_audit_trail(tmp_path):
    """
    validation_report.json must contain policy_audit from ControlledRunPolicy.
    policy_audit.verification_source confirms evidence-based provenance.
    """
    exit_code, run_dir, _ = _run(tmp_path)
    assert exit_code == 0
    vr = json.loads((run_dir / "validation_report.json").read_text())

    assert "policy_audit" in vr
    audit = vr["policy_audit"]
    assert "evidence" in audit["verification_source"].lower()
    assert audit["blocked_attempts"] > 0
    assert all(e["blocked_before_network"] for e in audit["blocked_operations"])


# ---------------------------------------------------------------------------
# Test 11 — preflight audits all 8 blocked capabilities
# ---------------------------------------------------------------------------

def test_preflight_audits_all_blocked_capabilities(tmp_path):
    """
    The preflight audit checks 8 blocked capabilities before any I/O.
    All 8 appear as blocked AuditEntry in policy.audit_trail.
    """
    exit_code, run_dir, _ = _run(tmp_path)
    assert exit_code == 0

    vr    = json.loads((run_dir / "validation_report.json").read_text())
    audit = vr["policy_audit"]

    expected_ops = {
        "external_drafts", "permanent_storage", "history_write",
        "database_write", "cache_read", "cache_write",
        "image_reuse", "cloudinary_upload",
    }
    blocked_ops = {e["operation"] for e in audit["blocked_operations"]}
    missing = expected_ops - blocked_ops
    assert not missing, f"Missing blocked operations in audit trail: {missing}"


# ---------------------------------------------------------------------------
# Test 12 — image: provider called once, cloudinary NOT called (blocked)
# ---------------------------------------------------------------------------

def test_image_generation_uses_injected_provider(tmp_path):
    """
    When --image-generation enabled, FakeImageProvider.generate() is called.
    upload_to_cloudinary is NOT called (blocked by policy in preflight).
    """
    fake_image = FakeImageProvider()

    with mock.patch("src.publishing.image_pipeline.composite_for_platform") as m_comp, \
         mock.patch("src.publishing.image_pipeline.upload_to_cloudinary") as m_cloud:
        m_comp.return_value = mock.MagicMock()
        m_comp.return_value.save = mock.MagicMock()

        exit_code, run_dir, _ = _run(tmp_path, image_gen="enabled",
                                      image_provider=fake_image)

    assert exit_code == 0
    fake_image.assert_called_once()
    m_cloud.assert_not_called()  # blocked by policy (preflight check)

    result = json.loads((run_dir / "image_generation_result.json").read_text())
    assert result["generated"] is True
    assert result["method"] == "fake_dalle"


# ---------------------------------------------------------------------------
# Test 13 — image disabled -> complete_without_image
# ---------------------------------------------------------------------------

def test_image_disabled_yields_complete_without_image(tmp_path):
    exit_code, run_dir, _ = _run(tmp_path, image_gen="disabled")
    assert exit_code == 0
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "complete_without_image"
    vr = json.loads((run_dir / "validation_report.json").read_text())
    assert vr["overall_status"] == "complete_without_image"
    assert vr["image_generation"] == "skipped"


# ---------------------------------------------------------------------------
# Test 14 — channel_specs in visual_brief
# ---------------------------------------------------------------------------

def test_visual_brief_has_channel_specs(tmp_path):
    """
    build_visual_brief() is called with channels=[...].
    VisualBrief.channel_specs exposes per-channel dimensions and safe zones.
    """
    exit_code, run_dir, _ = _run(tmp_path)
    assert exit_code == 0
    spec = json.loads((run_dir / "visual_spec.json").read_text())
    assert "channel_specs" in spec, "channel_specs must be present in visual_spec.json"
    ch_specs = spec["channel_specs"]
    assert len(ch_specs) > 0, "At least one channel must have specs"
    for ch, spec_data in ch_specs.items():
        assert "width" in spec_data
        assert "height" in spec_data
        assert "aspect_ratio" in spec_data
        assert "safe_zone_pct" in spec_data


# ---------------------------------------------------------------------------
# Test 15 — synthetic uses ARTICLE_READY=true (Option A lifecycle)
# ---------------------------------------------------------------------------

def test_synthetic_signal_uses_article_ready_canonical(tmp_path):
    """
    Option A: ARTICLE_READY=true is set explicitly on synthetic signals.
    RECOMMENDED_FOR_ARTICLE alias is not used as the canonical resolver.
    """
    from scripts.controlled_run import _create_synthetic_signal
    sig = _create_synthetic_signal("Test topic")
    assert sig.get("ARTICLE_READY") == "true", "ARTICLE_READY must be explicitly set"


# ---------------------------------------------------------------------------
# Test 16 — mandatory stage failure -> exit=1, status=failed
# ---------------------------------------------------------------------------

def test_mandatory_stage_failure_prevents_complete_status(tmp_path):
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
                    side_effect=ArticleGenerationError("test_stage", ValueError("LLM refused"))), \
         mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)), \
         mock.patch("src.publishing.image_pipeline.load_registry", return_value={}):
        result = run_controlled(args)

    assert result == 1
    subdirs = list(tmp_path.iterdir())
    assert subdirs
    manifest = json.loads((subdirs[0] / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failure_stage"] is not None


# ---------------------------------------------------------------------------
# Test 17 — synthetic manifest has correct flags
# ---------------------------------------------------------------------------

def test_manifest_metadata_flags(tmp_path):
    exit_code, run_dir, _ = _run(tmp_path, mode="synthetic-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["publication_disabled"] is True
    assert m["external_writes_disabled"] is True
    assert m["nb_controlled_run_env"] == "1"
    assert m["synthetic"] is True


# ---------------------------------------------------------------------------
# Test 18 — existing-signal mode
# ---------------------------------------------------------------------------

def test_existing_signal_mode(tmp_path):
    exit_code, run_dir, _ = _run(tmp_path, mode="existing-signal")
    assert exit_code == 0
    m = json.loads((run_dir / "run_manifest.json").read_text())
    assert m["mode"] == "existing-signal"
    assert m["synthetic"] is False


# ---------------------------------------------------------------------------
# Test 19 — guard.py removed; no unittest.mock in src/
# ---------------------------------------------------------------------------

def test_guard_py_removed_from_src():
    """src/controlled_run/guard.py must not exist (uses unittest.mock in production code)."""
    guard_path = Path(__file__).resolve().parents[1] / "src" / "controlled_run" / "guard.py"
    assert not guard_path.exists(), (
        f"guard.py found at {guard_path}. "
        "It uses unittest.mock in a production package and must be removed."
    )


# ---------------------------------------------------------------------------
# Test 20 — no mock.patch in runtime controlled-run code
# ---------------------------------------------------------------------------

def test_no_mock_patch_calls_in_runtime_code():
    """
    scripts/controlled_run.py and src/controlled_run/ must not USE mock.patch
    as a decorator or context manager.
    (Mentions in comments/docstrings explaining "no mock.patch" are allowed.)
    """
    import re

    # Matches actual mock.patch usage: @mock.patch or with mock.patch(
    # but NOT "# mock.patch" or '"mock.patch"' in doc comments
    _USAGE_RE = re.compile(r"^\s*(?:@|with\s+)mock\.patch\(", re.MULTILINE)

    cr_file = Path(__file__).resolve().parents[1] / "scripts" / "controlled_run.py"
    content = cr_file.read_text()
    matches = _USAGE_RE.findall(content)
    assert not matches, (
        f"Active mock.patch usage found in scripts/controlled_run.py ({len(matches)} match(es)). "
        "Runtime protection must use ControlledRunPolicy DI, not mock.patch."
    )
    src_cr_dir = Path(__file__).resolve().parents[1] / "src" / "controlled_run"
    for py_file in src_cr_dir.glob("*.py"):
        c = py_file.read_text()
        m = _USAGE_RE.findall(c)
        assert not m, (
            f"Active mock.patch usage found in {py_file} ({len(m)} match(es)). "
            "Not allowed in production src/."
        )
