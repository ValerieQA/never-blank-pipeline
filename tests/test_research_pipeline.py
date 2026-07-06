"""Tests for the Never Blank Signal Research Pipeline."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research.discover import make_signal_id, _normalize_url
from scripts.research.sync_from_sheets import ALLOWED_FIELDS


# --- SIGNAL_ID ---

def test_signal_id_is_deterministic():
    id1 = make_signal_id("https://reuters.com/article?utm_source=feed", "AI Cuts Labor Costs")
    id2 = make_signal_id("https://reuters.com/article?utm_source=feed", "AI Cuts Labor Costs")
    assert id1 == id2


def test_signal_id_is_16_chars():
    assert len(make_signal_id("https://example.com/story", "Test Headline")) == 16


def test_signal_id_differs_for_different_inputs():
    assert make_signal_id("https://a.com", "A") != make_signal_id("https://b.com", "B")


# --- URL normalization ---

def test_normalize_url_strips_utm():
    assert "utm_" not in _normalize_url("https://reuters.com/a?utm_source=feed&utm_medium=rss")


def test_normalize_url_lowercase():
    assert _normalize_url("HTTPS://EXAMPLE.COM/Article") == "https://example.com/article"


# --- Deduplication ---

def test_dedup_skips_seen_ids():
    sid = make_signal_id("https://example.com/story", "Wages Rise as AI Adoption Grows")
    assert sid in {sid}


# --- Scoring formula ---

def test_scoring_max_is_10():
    import yaml
    weights = yaml.safe_load(open("config/scoring_weights.yaml"))
    total = sum(v["weight"] for v in weights["criteria"].values())
    assert total == 10


def test_scoring_weights_are_explainable():
    import yaml
    weights = yaml.safe_load(open("config/scoring_weights.yaml"))
    for key, val in weights["criteria"].items():
        assert "description" in val, f"Missing description: {key}"
        assert "weight" in val


# --- Incomplete signal handling ---

def test_signal_without_case_source_not_article_ready():
    from scripts.research.enrich import enrich_signal
    signal = {"SIGNAL_ID": "abc123", "HEADLINE": "Test Signal", "raw_summary": "trend."}
    with patch("scripts.research.enrich.chat") as mock:
        mock.return_value = json.dumps({"CORE_FACT": "fact", "REAL_COMPANY_EXAMPLE": None, "SOURCE_FOR_CASE": None})
        result = enrich_signal(signal)
    assert result["REAL_COMPANY_EXAMPLE"] is None
    assert result["RECOMMENDED_FOR_ARTICLE"] == "false"
    assert result["CONFIDENCE"] == "low"


def test_signal_with_case_but_no_source_not_ready():
    from scripts.research.enrich import enrich_signal
    signal = {"SIGNAL_ID": "abc", "HEADLINE": "Test", "raw_summary": ""}
    with patch("scripts.research.enrich.chat") as mock:
        mock.return_value = json.dumps({"REAL_COMPANY_EXAMPLE": "Acme Corp", "SOURCE_FOR_CASE": None})
        result = enrich_signal(signal)
    assert result["RECOMMENDED_FOR_ARTICLE"] == "false"


# --- Archive rules ---

def test_archive_moves_old_signals():
    import scripts.research.archive as arch
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        active  = tmp / "signals_active.jsonl"
        archive = tmp / "archive"
        archive.mkdir()

        with open(active, "w") as f:
            f.write(json.dumps({"SIGNAL_ID": "old", "DATE_FOUND": "2024-01-01", "HEADLINE": "Old", "APPROVED_OVERRIDE": ""}) + "\n")
            f.write(json.dumps({"SIGNAL_ID": "new", "DATE_FOUND": "2099-01-01", "HEADLINE": "New", "APPROVED_OVERRIDE": ""}) + "\n")

        orig_active, orig_archive = arch.ACTIVE_FILE, arch.ARCHIVE_DIR
        arch.ACTIVE_FILE, arch.ARCHIVE_DIR = active, archive
        count = arch.run_archive()
        arch.ACTIVE_FILE, arch.ARCHIVE_DIR = orig_active, orig_archive

        assert count == 1
        remaining = [json.loads(l) for l in open(active) if l.strip()]
        assert len(remaining) == 1
        assert remaining[0]["SIGNAL_ID"] == "new"


def test_archive_keeps_approved_old_signals():
    import scripts.research.archive as arch
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        active  = tmp / "signals_active.jsonl"
        archive = tmp / "archive"
        archive.mkdir()

        with open(active, "w") as f:
            f.write(json.dumps({"SIGNAL_ID": "old2", "DATE_FOUND": "2024-01-01", "HEADLINE": "Old Approved", "APPROVED_OVERRIDE": "true"}) + "\n")

        orig_active, orig_archive = arch.ACTIVE_FILE, arch.ARCHIVE_DIR
        arch.ACTIVE_FILE, arch.ARCHIVE_DIR = active, archive
        count = arch.run_archive()
        arch.ACTIVE_FILE, arch.ARCHIVE_DIR = orig_active, orig_archive

        assert count == 0


# --- JSONL integrity ---

def test_valid_jsonl_round_trip():
    signal = {"SIGNAL_ID": "abc", "HEADLINE": "Test"}
    assert json.loads(json.dumps(signal, ensure_ascii=False))["SIGNAL_ID"] == "abc"


def test_selected_signals_created(tmp_path):
    path = tmp_path / "selected_signals.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps({"SIGNAL_ID": "sel001"}) + "\n")
    assert path.exists()
    assert json.loads(open(path).read().strip())["SIGNAL_ID"] == "sel001"


# --- sync_from_sheets allowed fields ---

def test_allowed_fields_whitelist():
    assert "NOTES" in ALLOWED_FIELDS
    assert "APPROVED_OVERRIDE" in ALLOWED_FIELDS
    assert "HEADLINE" not in ALLOWED_FIELDS
    assert "SOURCE_URL" not in ALLOWED_FIELDS
    assert "SIGNAL_ID" not in ALLOWED_FIELDS


# --- Image reuse rules ---

def test_image_reuse_no_most_recent_fallback():
    """_find_existing_image must not fall back to unrelated old images."""
    from scripts.research.prepare_content import _find_existing_image
    signal  = {"SIGNAL_ID": "brand_new_signal", "SIGNAL_TYPE": "layoffs"}
    library = {
        "other_signal_id": {
            "url": "https://cloudinary.com/old_image.png",
            "signal_type": "different_type",
            "headline": "Some old headline",
            "created_at": "2026-01-01",
        }
    }
    url, reason = _find_existing_image(signal, library)
    assert url is None
    assert reason == "none"


def test_image_reuse_same_signal_id():
    """_find_existing_image must reuse when SIGNAL_ID matches AND design_version is current."""
    from scripts.research.prepare_content import _find_existing_image
    from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION
    signal  = {"SIGNAL_ID": "abc123", "SIGNAL_TYPE": "layoffs"}
    library = {
        "abc123": {
            "url":            "https://cloudinary.com/correct_image.png",
            "signal_type":    "layoffs",
            "headline":       "Oracle layoffs",
            "created_at":     "2026-06-22",
            "design_version": CURRENT_DESIGN_VERSION,
        }
    }
    url, reason = _find_existing_image(signal, library)
    assert url == "https://cloudinary.com/correct_image.png"
    assert "same_signal" in reason


def test_hook_text_trim_no_partial_word():
    """trim_hook_text must never produce a partial word and must respect max_words."""
    from src.publishing.image_pipeline import trim_hook_text
    text = "The uncomfortable part of AI compute is that companies may soon need to manage infrastructure"
    result = trim_hook_text(text, max_words=12)
    words = result.split()
    assert len(words) <= 12
    # Every word in result must be a complete word from the original
    original_words = text.split()
    for w in words:
        assert w in original_words

    # No result word should be a truncated version of the next word
    result_no_partial = trim_hook_text("Power is the new i", max_words=12)
    assert result_no_partial == "Power is the new i"   # 5 words, under limit, kept as-is

    short_text = "Power is the new bottleneck"
    assert trim_hook_text(short_text) == short_text


def test_signal_selection_requires_both_conditions():
    """Selected signals must have BOTH RECOMMENDED_FOR_ARTICLE=true AND score >= threshold."""
    # Signal with recommendation but low score → should NOT be selected
    signal_rec_only = {
        "SIGNAL_ID": "sig1",
        "RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "4",
        "APPROVED_OVERRIDE": "",
    }
    # Signal with high score but no recommendation → should NOT be selected
    signal_score_only = {
        "SIGNAL_ID": "sig2",
        "RECOMMENDED_FOR_ARTICLE": "false",
        "ARTICLE_READINESS_SCORE": "9",
        "APPROVED_OVERRIDE": "",
    }
    # Signal with both → SHOULD be selected
    signal_both = {
        "SIGNAL_ID": "sig3",
        "RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "8",
        "APPROVED_OVERRIDE": "",
    }
    # Signal with APPROVED_OVERRIDE → SHOULD be selected regardless
    signal_override = {
        "SIGNAL_ID": "sig4",
        "RECOMMENDED_FOR_ARTICLE": "false",
        "ARTICLE_READINESS_SCORE": "3",
        "APPROVED_OVERRIDE": "true",
    }

    select_min = 7

    def _select(signals):
        return [
            s for s in signals
            if str(s.get("APPROVED_OVERRIDE", "")).lower() == "true"
            or (
                str(s.get("RECOMMENDED_FOR_ARTICLE", "false")).lower() == "true"
                and int(s.get("ARTICLE_READINESS_SCORE", "0") or "0") >= select_min
            )
        ]

    all_signals = [signal_rec_only, signal_score_only, signal_both, signal_override]
    result_ids  = {s["SIGNAL_ID"] for s in _select(all_signals)}

    assert "sig1" not in result_ids   # rec but low score
    assert "sig2" not in result_ids   # score but no rec
    assert "sig3" in result_ids       # both
    assert "sig4" in result_ids       # override


# --- Sheets sync failure is non-fatal ---

def test_sheets_sync_failure_preserves_data(tmp_path):
    from scripts.research import sync_to_sheets as sts
    active = tmp_path / "signals_active.jsonl"
    with open(active, "w") as f:
        f.write(json.dumps({"SIGNAL_ID": "abc", "HEADLINE": "Test"}) + "\n")

    orig = sts.ACTIVE_FILE
    sts.ACTIVE_FILE = active
    with patch("scripts.research.sync_to_sheets._get_service", side_effect=Exception("down")):
        result = sts.sync_to_sheets()
    sts.ACTIVE_FILE = orig

    assert result is False
    assert active.exists()
    lines = [json.loads(l) for l in open(active) if l.strip()]
    assert len(lines) == 1


# --- design_version reuse ---

def test_image_reuse_requires_matching_design_version():
    """_find_existing_image must NOT reuse when design_version is outdated."""
    from scripts.research.prepare_content import _find_existing_image
    from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION

    signal  = {"SIGNAL_ID": "sig_old", "SIGNAL_TYPE": "layoffs"}
    # Library entry with a stale design version
    library = {
        "sig_old": {
            "url":            "https://cloudinary.com/old.png",
            "signal_type":    "layoffs",
            "headline":       "Old Headline",
            "created_at":     "2026-01-01",
            "design_version": "0",   # outdated
        }
    }
    url, reason = _find_existing_image(signal, library)
    assert url is None
    assert reason == "none"


def test_image_reuse_same_signal_id_same_design_version():
    """_find_existing_image reuses when SIGNAL_ID matches AND design_version is current."""
    from scripts.research.prepare_content import _find_existing_image
    from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION

    signal  = {"SIGNAL_ID": "sig_cur", "SIGNAL_TYPE": "layoffs"}
    library = {
        "sig_cur": {
            "url":            "https://cloudinary.com/current.png",
            "signal_type":    "layoffs",
            "headline":       "Current Headline",
            "created_at":     "2026-06-26",
            "design_version": CURRENT_DESIGN_VERSION,
        }
    }
    url, reason = _find_existing_image(signal, library)
    assert url == "https://cloudinary.com/current.png"
    assert "same_signal" in reason


# --- ensure_never_blank_signature ---

def test_ensure_never_blank_signature_no_double_prefix():
    """ensure_never_blank_signature must not produce 'Never Blank: Never Blank: ...'"""
    from scripts.research.publish_packages import ensure_never_blank_signature

    signal = {"POSSIBLE_SIGNATURE_LINE": "Never Blank: The signal is rarely the event itself."}
    text   = "Some post content here."
    result = ensure_never_blank_signature(text, signal)

    import re
    matches = re.findall(r"Never\s+Blank", result, re.IGNORECASE)
    assert len(matches) == 1, f"Expected exactly 1 'Never Blank', got {len(matches)}: {result!r}"


def test_ensure_never_blank_signature_appended_when_missing():
    """ensure_never_blank_signature appends signature when text has none."""
    from scripts.research.publish_packages import ensure_never_blank_signature

    signal = {"POSSIBLE_SIGNATURE_LINE": "Attention is infrastructure."}
    text   = "Founders underestimate reach."
    result = ensure_never_blank_signature(text, signal)

    assert result.endswith("Never Blank: Attention is infrastructure.")


def test_ensure_never_blank_signature_fallback_when_no_sig_line():
    """ensure_never_blank_signature uses fallback when POSSIBLE_SIGNATURE_LINE is empty."""
    from scripts.research.publish_packages import ensure_never_blank_signature

    signal = {"POSSIBLE_SIGNATURE_LINE": ""}
    result = ensure_never_blank_signature("Some text.", signal)
    assert "Never Blank: The signal is rarely the event itself." in result


# --- Sheets canonical columns ---

def test_canonical_columns_count():
    """CANONICAL_COLUMNS must have exactly 42 entries (agreed schema)."""
    from scripts.research.sync_to_sheets import CANONICAL_COLUMNS
    assert len(CANONICAL_COLUMNS) == 42


def test_canonical_columns_starts_with_signal_id():
    from scripts.research.sync_to_sheets import CANONICAL_COLUMNS
    assert CANONICAL_COLUMNS[0] == "SIGNAL_ID"


# --- Quote card rhythm cycle (2026-07-06: previously specced in visual_system.yaml's
# instagram_rhythm.cycle but never wired to any code — every image was photo-led) ---

def test_next_rhythm_slot_follows_cycle_order():
    from src.publishing.image_pipeline import _next_rhythm_slot
    vs = {"instagram_rhythm": {"cycle": ["dark_insight_card", "mountains_depth_layers", "light_paths"]}}
    assert _next_rhythm_slot({"posts": []}, vs) == "dark_insight_card"
    assert _next_rhythm_slot({"posts": [{}]}, vs) is None  # mountains_depth_layers — not a card
    assert _next_rhythm_slot({"posts": [{}, {}]}, vs) is None  # light_paths — not a card
    assert _next_rhythm_slot({"posts": [{}, {}, {}]}, vs) == "dark_insight_card"  # cycle repeats


def test_next_rhythm_slot_returns_none_without_cycle_config():
    from src.publishing.image_pipeline import _next_rhythm_slot
    assert _next_rhythm_slot({"posts": []}, {}) is None


def test_choose_visual_family_uses_rhythm_card_before_ai_or_deterministic():
    """When the rhythm cycle lands on a card slot, choose_visual_family must
    return it directly — it must not call the AI selection or deterministic
    fallback at all (no image_prompt is needed for a card)."""
    from src.publishing import image_pipeline

    registry = {"posts": []}  # position 0
    with patch.object(image_pipeline, "_load_visual_system",
                       return_value={"instagram_rhythm": {"cycle": ["dark_insight_card"]},
                                      "palette": {"dark_core": {"colors": {"deep_navy": "#050B16"}},
                                                  "light_accents": {"colors": {}}}}):
        with patch.object(image_pipeline, "_ai_choose_visual_spec") as mock_ai:
            spec = image_pipeline.choose_visual_family(
                title="Headline", observation="Fact", content_goal="challenge", registry=registry,
            )
    mock_ai.assert_not_called()
    assert spec["visual_family"] == "dark_insight_card"
    assert spec["image_prompt"] == ""


def test_compose_quote_card_dark_card_includes_logo_light_card_skips_it():
    from src.publishing.image_pipeline import compose_quote_card

    with patch("src.publishing.image_pipeline.LOGO_PATH") as mock_logo_path:
        mock_logo_path.exists.return_value = True  # pretend a logo file exists
        # Dark card: should attempt to open+paste the logo. Return a real tiny
        # RGBA image so PIL's paste() has real size/mode data to work with.
        from PIL import Image as PILImage
        real_logo = PILImage.new("RGBA", (20, 20), (255, 255, 255, 255))
        with patch("src.publishing.image_pipeline.Image.open", return_value=real_logo) as mock_open:
            img = compose_quote_card("A short hook line.", "instagram", "dark_insight_card")
            assert mock_open.called
        assert img.size == (1080, 1350)

        # Light card: logo must be skipped even though the file "exists" —
        # the light-colored logo asset is not readable on a light background.
        with patch("src.publishing.image_pipeline.Image.open") as mock_open_light:
            img2 = compose_quote_card("A short hook line.", "instagram", "sand_pause_card")
            mock_open_light.assert_not_called()
        assert img2.size == (1080, 1350)


def test_register_post_persisted_by_build_image_plan(tmp_path, monkeypatch):
    """
    Regression test: _build_image_plan previously popped and discarded
    _registry_update instead of persisting it, so the rhythm/rotation cycle
    never advanced between runs. Verify register_post + save_registry are
    actually invoked with the returned registry_update payload.
    """
    from scripts.research import prepare_content

    fake_registry_update = {
        "content_slug": "research/sig1", "visual_family": "mountains_depth_layers",
        "dominant_palette": "midnight", "hook_text": "hook", "image_url": "https://x/1.png",
        "source_topic": "Some headline",
    }
    fake_result = {
        "platform_images": {}, "new_images": 1, "reused_images": 0, "reuse_rate": "0%",
        "image_method": "programmatic", "reuse_source": "n/a", "visual_family": "mountains_depth_layers",
        "hook_text": "hook", "_library_entry": {"url": "https://x/1.png"},
        "_registry_update": fake_registry_update,
    }

    with patch.object(prepare_content, "_generate_signal_image", return_value=fake_result):
        with patch.object(prepare_content, "_find_existing_image", return_value=(None, "none")):
            with patch("src.publishing.image_pipeline.load_registry", return_value={"posts": []}) as mock_load:
                with patch("src.publishing.image_pipeline.register_post") as mock_register:
                    with patch("src.publishing.image_pipeline.save_registry") as mock_save:
                        mock_register.return_value = {"posts": [fake_registry_update]}
                        result, lib_entry = prepare_content._build_image_plan({"SIGNAL_ID": "sig1"}, {})

    mock_load.assert_called_once()
    mock_register.assert_called_once_with({"posts": []}, **fake_registry_update)
    mock_save.assert_called_once_with({"posts": [fake_registry_update]})
    assert "_registry_update" not in result
    assert lib_entry == {"url": "https://x/1.png"}
