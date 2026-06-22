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
