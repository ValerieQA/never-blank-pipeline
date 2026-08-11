"""
Focused tests for Strategy.strategy_version field (prerequisite gap for Task #26).

Proves:
- active strategy loads with its explicit version;
- missing strategy_version fails closed;
- blank/whitespace strategy_version is rejected;
- ContentAssignment receives the exact version from Strategy.
"""

from __future__ import annotations

from datetime import date, timezone, datetime

import pytest

from src.strategy.models import Strategy, StrategyStatus, ContinuationCriteria, Confidence
from src.intake.content_assignment import ContentAssignment
from src.intake import from_jsonl_signal
from src.strategy.loader import load_active_strategy


def _base_strategy_dict(**overrides) -> dict:
    d = dict(
        strategy_id="2026-08-test",
        strategy_version="1",
        status="active",
        started_at="2026-08-01",
        review_date="2026-08-31",
        strategy_name="Test",
        strategy_summary="Summary",
        market_context="Agencies go dark when busy",
        selected_problem="Owner-dependent presence",
        sales_hypothesis="Pattern recognition leads to interest",
        why_now="Competition is up",
        commercial_goal="Generate leads",
        primary_message="Presence should not depend on your free time",
        compound_presence_role="Demonstrate systematic presence",
        desired_reader_realization="That is us",
        primary_cta_intent="reflection",
        continuation_criteria={"description": "Continue if leads", "indicators": ["1+ leads"]},
        adjustment_criteria={"description": "Adjust", "indicators": ["No leads but trending"]},
        replacement_criteria={"description": "Replace", "indicators": ["0 leads after 4 weeks"]},
        research_references=["strategy/worldview.md"],
        confidence="high",
    )
    d.update(overrides)
    return d


def test_active_strategy_loads_with_explicit_version():
    strategy = load_active_strategy()
    assert strategy is not None
    assert strategy.strategy_version == "1"
    assert strategy.strategy_id == "2026-07-presence-debt-campaign-1"


def test_missing_strategy_version_fails_closed():
    d = _base_strategy_dict()
    del d["strategy_version"]
    with pytest.raises(Exception, match="strategy_version"):
        Strategy(**d)


def test_blank_strategy_version_rejected():
    with pytest.raises(Exception, match="strategy_version"):
        Strategy(**_base_strategy_dict(strategy_version=""))


def test_whitespace_only_strategy_version_rejected():
    with pytest.raises(Exception, match="strategy_version"):
        Strategy(**_base_strategy_dict(strategy_version="   "))


def test_content_assignment_receives_exact_strategy_version():
    strategy = load_active_strategy()
    signal = {
        "SIGNAL_ID": "sig-test-001",
        "HEADLINE": "Test headline",
        "CORE_FACT": "Test fact.",
    }
    ca = from_jsonl_signal(
        signal,
        strategy_ref=strategy.strategy_id,
        strategy_version=strategy.strategy_version,
        submitted_at=datetime(2026, 8, 11, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert ca.strategy_ref == strategy.strategy_id
    assert ca.strategy_version == strategy.strategy_version
    assert ca.strategy_version == "1"
