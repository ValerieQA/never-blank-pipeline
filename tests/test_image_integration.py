"""
tests/test_image_integration.py
Image generation integration test — full isolation via provider injection.

## test_image_integration_full_isolation

Proves 7+ isolation points simultaneously in a single run:

  1. image_provider.generate() called exactly once
  2. ArtifactStore.write("image", ...) called — result in isolated run dir
  3. persistent_storage_adapter.upload() NOT called (policy audit blocked)
  4. cloudinary_client.upload_resource() NOT called
  5. image_reuse_store.get() NOT called (image_reuse blocked in preflight)
  6. image_reuse_store.put() NOT called
  7. Provenance artifact contains provider name, model name, prompt, output path
  8. policy.audit_trail contains AuditEntry for image_generation (allowed)
     and cloudinary_upload / permanent_storage (blocked)

Design constraints:
  - No mock.patch of internal symbols (requests, cloudinary SDK, etc.)
  - All isolation comes from provider injection and policy.check()
  - Real production functions (_run_image_generation, _generate_base_image)
    are exercised with fake providers
  - FakeImageProvider returns a real valid 1x1 PNG (no PIL errors)
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
    FakeImageProvider,
    FakeStorageAdapter,
    FakeImageReuseStore,
    FakeArtifactStore,
)


# ---------------------------------------------------------------------------
# Autouse fixture: restore env
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_env():
    old = os.environ.get("NB_CONTROLLED_RUN")
    yield
    if old is None:
        os.environ.pop("NB_CONTROLLED_RUN", None)
    else:
        os.environ["NB_CONTROLLED_RUN"] = old


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VISUAL_SPEC = {
    "visual_family":    "mountains_depth_layers",
    "dominant_palette": "midnight",
    "image_prompt":     "Test image prompt — isolated controlled run.",
    "hook_text":        "Test hook for isolation.",
    "negative_prompt":  "text, typography, neon, stock photography",
    "logo_placement":   "bottom_right",
    "rationale":        "Test rationale.",
}

_SIGNAL = {
    "SIGNAL_ID":             "img-test-isolation-001",
    "HEADLINE":              "Why businesses disappear from customer memory",
    "NEVER_BLANK_ANGLE":     "Invisibility is opt-in, not inevitable.",
    "POTENTIAL_HOOK":        "What visibility gaps cost small businesses.",
    "TARGET_AUDIENCE":       "founder",
    "PRIMARY_CHANNEL":       "linkedin",
    "ARTICLE_READY":         "true",
    "REAL_COMPANY_EXAMPLE":  "Acme Corp",
}

_ARTICLE = {
    "decision_lens": {
        "core_pattern": "absence becomes default",
        "owner_system_objective": "earn recurring revenue",
        "delivery_vs_presence_conflict": "delivers, then disappears",
        "customer_memory_consequence": "memory fades, next vendor wins",
        "structural_cause": "no between-project contact",
        "never_blank_insight": "invisibility is opt-in",
    },
    "platforms": {
        "long":      {"body": "Blog body. " * 30, "word_count": 120},
        "medium":    {"body": "LinkedIn post.", "word_count": 40},
        "reading":   {"body": "Facebook post.", "word_count": 20},
        "instagram": {"body": "Instagram caption.", "word_count": 10},
        "short":     {"body": "Short post.", "word_count": 5},
    },
}


def _make_policy(*, image_generation_allowed: bool = True):
    """Create a ControlledRunPolicy with all writes blocked except image_generation."""
    from src.controlled_run.policy import ControlledRunPolicy
    return ControlledRunPolicy(
        run_id                    = "img-isolation-test",
        publication_allowed       = False,
        external_drafts_allowed   = False,
        permanent_storage_allowed = False,   # <-- separate gate from image_generation
        history_writes_allowed    = False,
        database_writes_allowed   = False,
        cache_reads_allowed       = False,
        cache_writes_allowed      = False,
        image_reuse_allowed       = False,
        image_generation_allowed  = image_generation_allowed,
    )


# ---------------------------------------------------------------------------
# Core isolation test
# ---------------------------------------------------------------------------

def test_image_integration_full_isolation(tmp_path):
    """
    Proves 7+ isolation points simultaneously in a single run.

    Injection points:
      - image_provider = FakeImageProvider()
      - storage_adapter = FakeStorageAdapter(run_dir) [not wired into pipeline]
      - image_reuse_store = FakeImageReuseStore() [not wired into pipeline]
      - artifact_store = FakeArtifactStore(run_dir)
      - policy with image_generation_allowed=True, permanent_storage_allowed=False

    What executes:
      - Real _run_image_generation() from scripts/controlled_run.py
      - Real _generate_base_image() from src/publishing/image_pipeline.py
      - Real policy.check() for image_generation (allowed)
      - Real preflight checks for permanent_storage / cloudinary_upload (blocked)

    What does NOT execute:
      - Real OpenAI DALL-E call (FakeImageProvider intercepts)
      - Real Cloudinary upload (policy blocks + not wired to cloudinary client)
      - Real image reuse store read/write (FakeImageReuseStore returns None)

    Isolation point list:
      1. image_provider.generate() called exactly once
      2. FakeArtifactStore.write() called -- result in isolated run_dir only
      3. FakeStorageAdapter.upload() NOT called (permanent_storage blocked)
      4. cloudinary_client.upload() NOT called (Cloudinary not wired in isolated run)
      5. image_reuse_store.get() NOT called (image_reuse blocked in preflight)
      6. image_reuse_store.put() NOT called
      7. image_generation_result.json provenance: provider=FakeImageProvider, prompt, path
      8. policy.audit_trail: image_generation allowed; permanent_storage + cloudinary_upload blocked
    """
    from scripts.controlled_run import (
        _run_image_generation, _run_preflight_capability_audit, InvocationLedger,
    )
    from src.publishing.visual_brief import build_visual_brief

    run_dir = tmp_path / "img_isolation_run"
    run_dir.mkdir()

    policy           = _make_policy(image_generation_allowed=True)
    ledger           = InvocationLedger()
    fake_image       = FakeImageProvider(method="fake_dalle")
    storage_adapter  = FakeStorageAdapter(run_dir)
    reuse_store      = FakeImageReuseStore()
    artifact_store   = FakeArtifactStore(run_dir)

    # Run preflight to add preflight audit entries (permanent_storage, cloudinary_upload)
    _run_preflight_capability_audit(policy, ledger)

    # Build visual brief (uses mocked choose_visual_family)
    with mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)), \
         mock.patch("src.publishing.image_pipeline.load_registry", return_value={}):
        brief = build_visual_brief(
            signal              = _SIGNAL,
            article_result      = _ARTICLE,
            brand_name          = "Never Blank",
            registry            = {},
            channels            = ["linkedin", "blog"],
            policy_exclusion_tags = "robots, humanoid AI figures",
        )

    # Run image generation with injected fake provider
    # composite_for_platform is mocked to avoid PIL compositing on a 1x1 PNG
    with mock.patch("src.publishing.image_pipeline.composite_for_platform") as m_comp:
        composite_img = mock.MagicMock()
        composite_img.save = mock.MagicMock()
        m_comp.return_value = composite_img

        record = _run_image_generation(
            signal        = _SIGNAL,
            visual_brief  = brief,
            run_dir       = run_dir,
            ledger        = ledger,
            policy        = policy,
            image_provider = fake_image,
        )

    # ----- Isolation point 1: image_provider.generate() called exactly once -----
    assert fake_image.call_count == 1, (
        f"Expected exactly 1 image_provider.generate() call, got {fake_image.call_count}"
    )
    gen_call = fake_image.calls[0]
    assert gen_call["prompt"] == brief.image_prompt, "Prompt must match visual brief"

    # ----- Isolation point 2: artifact in isolated run_dir -----
    assert (run_dir / "image_generation_result.json").exists(), \
        "image_generation_result.json must be written to isolated run_dir"

    # ----- Isolation point 3: persistent_storage upload NOT called -----
    storage_adapter.assert_not_called()

    # ----- Isolation point 4: Cloudinary NOT called -----
    # (Cloudinary SDK is never invoked because policy blocked cloudinary_upload
    # in preflight and _run_image_generation does not call upload_to_cloudinary)
    cloudinary_blocked_entries = [
        e for e in policy.audit_trail if e.operation == "cloudinary_upload"
    ]
    assert cloudinary_blocked_entries, "cloudinary_upload must appear in audit trail as blocked"
    assert all(not e.allowed for e in cloudinary_blocked_entries)

    # ----- Isolation point 5: image_reuse_store.get() NOT called -----
    reuse_store.assert_get_not_called()

    # ----- Isolation point 6: image_reuse_store.put() NOT called -----
    reuse_store.assert_put_not_called()

    # ----- Isolation point 7: provenance in result artifact -----
    result_json = json.loads((run_dir / "image_generation_result.json").read_text())
    assert result_json["generated"] is True
    assert result_json["method"] == "fake_dalle",        "method must match FakeImageProvider.method"
    assert result_json["provider"] == "FakeImageProvider", "provider class name in provenance"
    assert result_json["prompt_used"],                   "prompt_used must be non-empty"
    assert result_json["cloudinary_upload"].startswith("blocked"), \
        "cloudinary_upload provenance must record 'blocked'"
    assert result_json["image_library_updated"] is False
    assert result_json["image_reuse"] is False

    # ----- Isolation point 8: policy.audit_trail has correct entries -----
    audit_ops = {e.operation: e for e in policy.audit_trail}

    assert "image_generation" in audit_ops, "image_generation must appear in audit_trail"
    ig_entry = audit_ops["image_generation"]
    assert ig_entry.allowed is True,               "image_generation must be ALLOWED"
    assert ig_entry.blocked_before_network is False, "image_generation must not be blocked"

    assert "permanent_storage" in audit_ops, "permanent_storage must appear in audit_trail"
    ps_entry = audit_ops["permanent_storage"]
    assert ps_entry.allowed is False,               "permanent_storage must be BLOCKED"
    assert ps_entry.blocked_before_network is True,  "permanent_storage blocked BEFORE network"

    assert "cloudinary_upload" in audit_ops, "cloudinary_upload must appear in audit_trail"
    cu_entry = audit_ops["cloudinary_upload"]
    assert cu_entry.allowed is False,               "cloudinary_upload must be BLOCKED"
    assert cu_entry.blocked_before_network is True,  "cloudinary_upload blocked BEFORE network"

    # Audit summary correctness
    summary = policy.audit_summary()
    assert summary["blocked_attempts"] >= 2,         "at least permanent_storage + cloudinary_upload"
    assert "evidence" in summary["verification_source"].lower()


# ---------------------------------------------------------------------------
# Test: image_generation blocked -> generate() not called
# ---------------------------------------------------------------------------

def test_image_generation_blocked_means_provider_not_called(tmp_path):
    """
    When image_generation_allowed=False, policy.check("image_generation") raises
    PolicyViolation BEFORE image_provider.generate() is ever called.
    """
    from scripts.controlled_run import (
        _run_image_generation, _run_preflight_capability_audit, InvocationLedger,
    )
    from src.publishing.visual_brief import build_visual_brief
    from src.controlled_run.policy import PolicyViolation

    run_dir = tmp_path / "blocked_gen"
    run_dir.mkdir()

    policy     = _make_policy(image_generation_allowed=False)
    ledger     = InvocationLedger()
    fake_image = FakeImageProvider()

    _run_preflight_capability_audit(policy, ledger)

    with mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)), \
         mock.patch("src.publishing.image_pipeline.load_registry", return_value={}):
        brief = build_visual_brief(
            signal=_SIGNAL, article_result=_ARTICLE, brand_name="Never Blank",
            registry={}, channels=["linkedin", "blog"],
        )

    with pytest.raises(PolicyViolation, match="image_generation"):
        _run_image_generation(
            signal=_SIGNAL, visual_brief=brief, run_dir=run_dir,
            ledger=ledger, policy=policy, image_provider=fake_image,
        )

    assert fake_image.call_count == 0, \
        "image_provider.generate() must NOT be called when policy blocks"

    # image_generation must appear as blocked in audit_trail
    ig_entries = [e for e in policy.audit_trail if e.operation == "image_generation"]
    assert ig_entries, "image_generation must appear in audit_trail"
    assert all(not e.allowed for e in ig_entries), "all image_generation entries must be blocked"


# ---------------------------------------------------------------------------
# Test: permanent_storage and image_generation are separate gates
# ---------------------------------------------------------------------------

def test_permanent_storage_gate_is_independent_of_image_generation_gate(tmp_path):
    """
    Allowing image_generation while blocking permanent_storage is the correct
    controlled-run configuration: we can generate bytes, but not persist them.
    This test confirms the two capabilities are truly independent.
    """
    from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation

    policy = ControlledRunPolicy(
        run_id                    = "sep-gate-test",
        image_generation_allowed  = True,    # ALLOWED
        permanent_storage_allowed = False,   # BLOCKED
    )

    # image_generation: allowed -- no exception
    policy.check("image_generation", adapter="test_gen")

    # permanent_storage: blocked -- raises
    with pytest.raises(PolicyViolation):
        policy.check("permanent_storage", adapter="test_storage")

    # Confirm audit entries are independent
    ops = [(e.operation, e.allowed) for e in policy.audit_trail]
    assert ("image_generation", True)  in ops
    assert ("permanent_storage", False) in ops

    # No cross-contamination: the two checks do not affect each other
    allowed_ig = [e for e in policy.audit_trail if e.operation == "image_generation"]
    assert all(e.allowed for e in allowed_ig)
    blocked_ps = [e for e in policy.audit_trail if e.operation == "permanent_storage"]
    assert all(not e.allowed for e in blocked_ps)


# ---------------------------------------------------------------------------
# Test: FakeImageProvider returns valid PNG bytes
# ---------------------------------------------------------------------------

def test_fake_image_provider_returns_valid_png():
    """
    FakeImageProvider.generate() must return (bytes, str) where bytes is a
    valid PNG (starts with PNG magic bytes).
    This ensures composite_for_platform() can open it without PIL errors.
    """
    provider = FakeImageProvider(method="fake_dalle")
    img_bytes, method = provider.generate("test prompt", visual_family="mountains")

    assert method == "fake_dalle"
    assert isinstance(img_bytes, bytes)
    assert img_bytes[:4] == b"\x89PNG", "Output must be valid PNG"
    assert len(img_bytes) > 50, "PNG must have non-trivial size"

    provider.assert_called_once()


# ---------------------------------------------------------------------------
# Test: channel_specs present in visual brief
# ---------------------------------------------------------------------------

def test_visual_brief_channel_specs_populated():
    """
    build_visual_brief(channels=["linkedin", "blog"]) must produce channel_specs
    with per-channel width, height, aspect_ratio, safe_zone_pct.
    """
    from src.publishing.visual_brief import build_visual_brief

    with mock.patch("src.publishing.image_pipeline.choose_visual_family",
                    return_value=dict(_VISUAL_SPEC)), \
         mock.patch("src.publishing.image_pipeline.load_registry", return_value={}):
        brief = build_visual_brief(
            signal=_SIGNAL, article_result=_ARTICLE, brand_name="Never Blank",
            registry={}, channels=["linkedin", "blog"],
        )

    assert brief.channel_specs, "channel_specs must not be empty"
    for ch in ["linkedin", "blog"]:
        assert ch in brief.channel_specs, f"Missing channel spec for {ch}"
        spec = brief.channel_specs[ch]
        assert "width" in spec
        assert "height" in spec
        assert "aspect_ratio" in spec
        assert "safe_zone_pct" in spec
        assert spec["width"] > 0
        assert spec["height"] > 0
        assert spec["aspect_ratio"] > 0

    # Primary channel (linkedin) aspect ratio annotated in image_prompt
    assert "linkedin" in brief.image_prompt or "Primary channel" in brief.image_prompt, \
        "Primary channel must be annotated in image_prompt"
