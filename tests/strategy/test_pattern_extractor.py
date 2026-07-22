"""
Tests for src/strategy/pattern_extractor.py

Covers:
- Valid signal → PatternRecord
- Rejected signal → SignalRejectedError
- Invalid JSON from LLM → ValueError
- Missing required fields in LLM response → ValidationError
- Empty required fields in LLM response → ValidationError
- LLM exception → appears in rejected log (extract_patterns_from_signals)
- Batch processing: mixed accepted and rejected
- Confidence fallback on unknown value
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.strategy.models import Confidence, MarketSignal, PatternRecord
from src.strategy.pattern_extractor import (
    SignalRejectedError,
    extract_patterns_from_signals,
    extract_strategic_pattern,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_market_signal(**overrides) -> MarketSignal:
    defaults = dict(
        signal="Agencies go dark when fully booked",
        source="https://example.com/report",
        source_date="2026-07-01",
        market_area="small business services",
        affected_audience="digital agencies — US",
        change_detected="Agency content drops 60% during peak delivery months",
        why_it_matters="Clients stop hearing from the agency exactly when they might look elsewhere",
        business_implication="Silent periods erode trust and reduce referral activity",
        sales_implication="Owners who recognize the pattern are ready for a presence system",
        compound_presence_implication="Consistent presence cannot depend on available time",
        confidence=Confidence.HIGH,
        freshness="2026-07-01",
        evidence=["https://example.com/report"],
    )
    defaults.update(overrides)
    return MarketSignal(**defaults)


def _valid_llm_response(**overrides) -> dict:
    defaults = dict(
        signal_fit="use",
        rejection_reason=None,
        pattern_name="Delivery Mode Kills Presence",
        small_business_situation="Agency owner posts nothing for 6 weeks while fully booked",
        underlying_mechanism="Delivery tasks consume all cognitive budget; presence work has no protected slot",
        customer_behavior="Clients interpret silence as lower demand or disengagement",
        business_risk="Next project goes to the agency that stayed visible",
        business_opportunity="Systematic presence keeps the agency top of mind between projects",
        sales_relevance="Owners immediately recognize this and want a solution",
        content_relevance="Enables recognition articles with high save rates",
        compound_presence_relevance="Illustrates exactly why compound presence is a system, not a mood",
        confidence="high",
    )
    defaults.update(overrides)
    return defaults


# ── Single signal extraction ───────────────────────────────────────────────────

class TestExtractStrategicPattern:
    def test_valid_signal_returns_pattern_record(self):
        signal = _make_market_signal()
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(_valid_llm_response())
            result = extract_strategic_pattern(signal)

        assert isinstance(result, PatternRecord)
        assert result.pattern_name == "Delivery Mode Kills Presence"
        assert result.confidence == Confidence.HIGH
        assert result.pattern_id.startswith("pat-")
        assert signal.signal in result.observed_signals

    def test_rejected_signal_raises_signal_rejected_error(self):
        signal = _make_market_signal(signal="Apple released new iPhone model")
        llm_resp = {
            "signal_fit": "reject",
            "rejection_reason": "product launch with no presence/visibility mechanism",
        }
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(llm_resp)
            with pytest.raises(SignalRejectedError, match="product launch"):
                extract_strategic_pattern(signal)

    def test_rejected_signal_without_reason_uses_default_message(self):
        signal = _make_market_signal()
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps({"signal_fit": "reject"})
            with pytest.raises(SignalRejectedError, match="strategic territory"):
                extract_strategic_pattern(signal)

    def test_invalid_json_raises_value_error(self):
        signal = _make_market_signal()
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = "not valid json {"
            with pytest.raises(ValueError, match="invalid JSON"):
                extract_strategic_pattern(signal)

    def test_missing_required_field_raises_validation_error(self):
        signal = _make_market_signal()
        # pattern_name is required and has a validator — empty string should fail
        bad_response = _valid_llm_response(pattern_name="")
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(bad_response)
            with pytest.raises(Exception):
                extract_strategic_pattern(signal)

    def test_missing_underlying_mechanism_fails(self):
        signal = _make_market_signal()
        bad_response = _valid_llm_response(underlying_mechanism="")
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(bad_response)
            with pytest.raises(Exception):
                extract_strategic_pattern(signal)

    def test_missing_compound_presence_relevance_fails(self):
        signal = _make_market_signal()
        bad_response = _valid_llm_response(compound_presence_relevance="")
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(bad_response)
            with pytest.raises(Exception):
                extract_strategic_pattern(signal)

    def test_unknown_confidence_falls_back_to_medium(self):
        signal = _make_market_signal()
        response = _valid_llm_response(confidence="extreme")
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(response)
            result = extract_strategic_pattern(signal)
        assert result.confidence == Confidence.MEDIUM

    def test_llm_exception_propagates(self):
        signal = _make_market_signal()
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.side_effect = RuntimeError("LLM timeout")
            with pytest.raises(RuntimeError, match="LLM timeout"):
                extract_strategic_pattern(signal)


# ── Batch processing ───────────────────────────────────────────────────────────

class TestExtractPatternsFromSignals:
    def test_empty_signals_returns_empty(self):
        accepted, rejected = extract_patterns_from_signals([])
        assert accepted == []
        assert rejected == []

    def test_all_accepted(self):
        signals = [_make_market_signal(), _make_market_signal(signal="Consultants ghost clients during busy months")]
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps(_valid_llm_response())
            accepted, rejected = extract_patterns_from_signals(signals)
        assert len(accepted) == 2
        assert rejected == []

    def test_all_rejected(self):
        signals = [_make_market_signal()]
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps({"signal_fit": "reject", "rejection_reason": "off-territory"})
            accepted, rejected = extract_patterns_from_signals(signals)
        assert accepted == []
        assert len(rejected) == 1
        assert "off-territory" in rejected[0]["reason"]

    def test_mixed_accepted_and_rejected(self):
        signals = [
            _make_market_signal(signal="Good signal about agency presence"),
            _make_market_signal(signal="Bad signal about stock market"),
        ]
        responses = [
            json.dumps(_valid_llm_response()),
            json.dumps({"signal_fit": "reject", "rejection_reason": "macro-economic, no presence angle"}),
        ]
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.side_effect = responses
            accepted, rejected = extract_patterns_from_signals(signals)
        assert len(accepted) == 1
        assert len(rejected) == 1

    def test_llm_exception_goes_to_rejected_log(self):
        signals = [_make_market_signal()]
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.side_effect = RuntimeError("API error")
            accepted, rejected = extract_patterns_from_signals(signals)
        assert accepted == []
        assert len(rejected) == 1
        assert "extraction error" in rejected[0]["reason"]
        assert "API error" in rejected[0]["reason"]

    def test_rejected_log_contains_signal_text(self):
        signal = _make_market_signal(signal="Irrelevant news about hardware")
        with patch("src.strategy.pattern_extractor.chat") as mock_chat:
            mock_chat.return_value = json.dumps({"signal_fit": "reject", "rejection_reason": "hardware"})
            _, rejected = extract_patterns_from_signals([signal])
        assert "Irrelevant news about hardware" in rejected[0]["signal"]
