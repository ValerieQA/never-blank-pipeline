"""
PROVISIONAL BACKWARD-COMPATIBILITY RULE

Tests for ResearchContext.from_dict() RECOMMENDED_FOR_ARTICLE → article_ready
normalization introduced to unblock pre-Stage-1A signals.

OPEN QUESTION FOR PRODUCT OWNER:
Does the product owner confirm that legacy RECOMMENDED_FOR_ARTICLE=true
is semantically equivalent to canonical ARTICLE_READY=true?
These tests assume equivalence. If they are NOT equivalent, the normalization
rule and these tests must be revisited before merging.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from src.lifecycle.signal_lifecycle import ResearchContext


def _base_signal(**overrides) -> dict:
    """Minimal valid signal dict. Override any field via kwargs."""
    base = {
        "SIGNAL_ID": "test-signal-001",
        "HEADLINE": "Test Headline",
        "SIGNAL_TYPE": "business trust",
        "REGION": "US",
        "INDUSTRY": "Retail",
        "SOURCE_NAME": "Test Source",
        "SOURCE_URL": "https://example.com",
        "SOURCE_DATE": "2026-01-01",
        "DATE_FOUND": "2026-01-01",
        "CORE_FACT": "Test fact",
        "CONFIDENCE": "medium",
        "OUTCOME_IF_KNOWN": "unknown",
        "DID_IT_WORK": "unknown",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "7",
        "CHANNEL_FIT_SCORE": "7",
    }
    base.update(overrides)
    return base


# ── Test 1: Legacy — RECOMMENDED_FOR_ARTICLE=true, no ARTICLE_READY ────────

def test_legacy_recommended_true_no_article_ready():
    """RECOMMENDED_FOR_ARTICLE=true with ARTICLE_READY absent → article_ready=True."""
    signal = _base_signal(RECOMMENDED_FOR_ARTICLE="true")
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is True


# ── Test 2: Legacy — RECOMMENDED_FOR_ARTICLE=false, no ARTICLE_READY ───────

def test_legacy_recommended_false_no_article_ready():
    """RECOMMENDED_FOR_ARTICLE=false with ARTICLE_READY absent → article_ready=False."""
    signal = _base_signal(RECOMMENDED_FOR_ARTICLE="false")
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is False


# ── Test 3: New canonical — ARTICLE_READY=true ─────────────────────────────

def test_canonical_article_ready_true():
    """ARTICLE_READY=true → article_ready=True."""
    signal = _base_signal(ARTICLE_READY="true")
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is True


# ── Test 4: New canonical — ARTICLE_READY=false ────────────────────────────

def test_canonical_article_ready_false():
    """ARTICLE_READY=false (explicit false) wins; never silently flipped."""
    signal = _base_signal(ARTICLE_READY="false")
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is False


# ── Test 5: Conflict — ARTICLE_READY wins over RECOMMENDED_FOR_ARTICLE ─────

def test_conflict_article_ready_true_recommended_false():
    """ARTICLE_READY=true wins even when RECOMMENDED_FOR_ARTICLE=false."""
    signal = _base_signal(ARTICLE_READY="true", RECOMMENDED_FOR_ARTICLE="false")
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is True


# ── Test 6: Conflict — ARTICLE_READY=false wins over RECOMMENDED_FOR_ARTICLE=true

def test_conflict_article_ready_false_recommended_true():
    """ARTICLE_READY=false wins even when RECOMMENDED_FOR_ARTICLE=true."""
    signal = _base_signal(ARTICLE_READY="false", RECOMMENDED_FOR_ARTICLE="true")
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is False


# ── Test 7: Both absent → fail-closed ──────────────────────────────────────

def test_both_absent_fail_closed():
    """Neither ARTICLE_READY nor RECOMMENDED_FOR_ARTICLE → article_ready=False."""
    signal = _base_signal()
    # Ensure neither field is present
    signal.pop("ARTICLE_READY", None)
    signal.pop("RECOMMENDED_FOR_ARTICLE", None)
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is False


# ── Test 8: score_recommended is NOT a veto on article_ready ───────────────

def test_article_ready_true_despite_score_recommended_false():
    """ARTICLE_READY=true with SCORE_RECOMMENDED_FOR_ARTICLE=false → article_ready=True, score_recommended=False."""
    signal = _base_signal(
        ARTICLE_READY="true",
        SCORE_RECOMMENDED_FOR_ARTICLE="false",
    )
    rc = ResearchContext.from_dict(signal)
    assert rc.article_ready is True
    assert rc.score_recommended is False


# ── Test 9: Round-trip preserves article_ready ─────────────────────────────

def test_roundtrip_preserves_article_ready():
    """ResearchContext → to_dict() → from_dict() preserves article_ready."""
    signal = _base_signal(ARTICLE_READY="true", SCORE_RECOMMENDED_FOR_ARTICLE="true")
    rc1 = ResearchContext.from_dict(signal)
    assert rc1.article_ready is True

    # to_dict() writes ARTICLE_READY canonically
    d2 = rc1.to_dict()
    assert d2["ARTICLE_READY"] == "true"

    rc2 = ResearchContext.from_dict(d2)
    assert rc2.article_ready is True


def test_roundtrip_preserves_article_ready_false():
    """Round-trip also preserves explicit False."""
    signal = _base_signal(ARTICLE_READY="false", SCORE_RECOMMENDED_FOR_ARTICLE="false")
    rc1 = ResearchContext.from_dict(signal)
    assert rc1.article_ready is False

    d2 = rc1.to_dict()
    rc2 = ResearchContext.from_dict(d2)
    assert rc2.article_ready is False


# ── Test 10: Real signal 215284813eae82ce loads with article_ready=True ────

def test_real_signal_215284813eae82ce_passes_preflight():
    """
    Signal 215284813eae82ce (RECOMMENDED_FOR_ARTICLE=true, no ARTICLE_READY)
    must load with article_ready=True after the normalization fix.
    """
    signals_file = Path(__file__).resolve().parents[1] / "data/research/signals_active.jsonl"
    if not signals_file.exists():
        pytest.skip("signals_active.jsonl not available in this environment")

    target_id = "215284813eae82ce"
    record = None
    for line in signals_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("SIGNAL_ID") == target_id:
                record = obj
                break
        except Exception:
            pass

    if record is None:
        pytest.skip(f"Signal {target_id} not found in signals_active.jsonl")

    assert record.get("ARTICLE_READY") is None, \
        "Test premise: ARTICLE_READY must be absent in this record"
    assert record.get("RECOMMENDED_FOR_ARTICLE") == "true", \
        "Test premise: RECOMMENDED_FOR_ARTICLE must be 'true'"

    rc = ResearchContext.from_dict(record)
    assert rc.article_ready is True, (
        f"Signal {target_id} must pass preflight after normalization fix; "
        f"got article_ready={rc.article_ready}"
    )
