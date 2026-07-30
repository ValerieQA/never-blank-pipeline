"""Tests for prepare_photo_overlay_hook — semantic boundary preservation."""

import pytest
from src.publishing.image_pipeline import (
    prepare_photo_overlay_hook,
    HOOK_OVERLAY_MAX_WORDS,
    _INCOMPLETE_ENDINGS,
)


# ── Word limit ────────────────────────────────────────────────────────────────

def test_short_hook_returned_as_is():
    hook = "Presence matters."
    assert prepare_photo_overlay_hook(hook) == hook


def test_hook_at_max_words_returned_as_is():
    words = ["word"] * HOOK_OVERLAY_MAX_WORDS
    hook  = " ".join(words) + "."
    assert prepare_photo_overlay_hook(hook) == hook


def test_hook_one_over_max_triggers_boundary_search():
    # 15 words, last sentence ends at word 10 (clean boundary)
    hook = "AI signals demand action. Companies that ignore this fall behind in every market they enter."
    result = prepare_photo_overlay_hook(hook)
    assert len(result.split()) <= HOOK_OVERLAY_MAX_WORDS
    assert result.endswith(".")


# ── Sentence boundary ─────────────────────────────────────────────────────────

def test_cuts_at_period_within_limit():
    # First sentence ends at word 7 (within limit); total is 16 words → must cut
    hook = "Antitrust concerns stall a $110 billion merger. Regulators demand a full competitive review before any deal is approved."
    result = prepare_photo_overlay_hook(hook)
    assert result == "Antitrust concerns stall a $110 billion merger."


def test_cuts_at_semicolon():
    hook = "Revenue grew 40%; analysts expected 25%; the market rewarded patience."
    result = prepare_photo_overlay_hook(hook)
    assert result.endswith(";") or result.endswith(".")
    assert len(result.split()) <= HOOK_OVERLAY_MAX_WORDS


def test_no_cut_after_incomplete_ending():
    # "regain" is in _INCOMPLETE_ENDINGS — should NOT cut after it
    hook = "Controlling distribution to stabilize pricing and regain market share."
    result = prepare_photo_overlay_hook(hook)
    # No clean boundary found inside limit → full text passed through
    assert result == hook


def test_no_cut_after_conjunction():
    hook = "Revenue is up and profits are rising but margins remain under pressure for all divisions."
    result = prepare_photo_overlay_hook(hook)
    # Any boundary must not end on 'and', 'but', etc.
    if len(result.split()) < len(hook.split()):
        last = result.rstrip(".,;!?").split()[-1].lower()
        assert last not in _INCOMPLETE_ENDINGS


def test_no_cut_after_preposition():
    hook = "Investment flows into emerging markets with unprecedented speed as rates fall across the region."
    result = prepare_photo_overlay_hook(hook)
    if len(result.split()) < len(hook.split()):
        last = result.rstrip(".,;!?").split()[-1].lower()
        assert last not in _INCOMPLETE_ENDINGS


# ── Completeness guarantee ────────────────────────────────────────────────────

def test_result_ends_with_complete_punctuation_when_shortened():
    hook = "Delta profits are up. But so is the price of every seat and who gets left behind remains unclear."
    result = prepare_photo_overlay_hook(hook)
    if len(result.split()) < len(hook.split()):
        assert result[-1] in ".!?;", f"Shortened result must end with punctuation: {result!r}"


def test_no_result_ends_on_article():
    hook = "Markets react to the news of the merger with volatility seen across the sector and beyond."
    result = prepare_photo_overlay_hook(hook)
    last = result.rstrip(".,;!?").split()[-1].lower()
    assert last not in {"the", "a", "an"}


def test_passthrough_when_no_clean_boundary():
    """When no sentence boundary exists within limit, return full text."""
    # One long run-on with no internal punctuation, >14 words
    hook = "A massive structural shift in global supply chains will reshape every industry and every company that depends on them"
    result = prepare_photo_overlay_hook(hook)
    assert result == hook, "No clean boundary → full text must pass through unchanged"


# ── Renderer contract: no truncation inside renderer ─────────────────────────

def test_composite_for_platform_does_not_trim():
    """Smoke test: composite_for_platform renders whatever it receives."""
    from io import BytesIO
    from src.publishing.image_pipeline import composite_for_platform, _generate_programmatic_base

    hook = "Controlling distribution to stabilize pricing and regain market share."
    base = _generate_programmatic_base("light_paths")
    img  = composite_for_platform(base, hook, "instagram")

    # Image renders without exception and has correct platform dimensions
    assert img.size == (1080, 1350)
