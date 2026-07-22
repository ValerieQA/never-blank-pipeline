"""
Tests for src/strategy/decision_engine.py (Phase 4A).

Covers:
- draft_weekly_review: valid input → WeeklyReview with correct types
- draft_weekly_review: LLM fallback on exception
- draft_weekly_review: unknown decision string → REVIEW_STRATEGY default
- draft_monthly_review: aggregation logic (totals, period dates)
- draft_monthly_review: raises on empty weekly reviews
- draft_monthly_review: unknown decision string → INSUFFICIENT_DATA default
- draft_strategy_recommendation: returns StrategyRecommendation with correct structure
- draft_strategy_recommendation: LLM fallback on exception
- StrategyRecommendation model: human_approved defaults to None
- StrategyChangeRecord model: basic construction and field presence
- WeeklyDecision and MonthlyDecision enum values remain stable
- Review vs Recommendation separation: recommendation_id is distinct from review fields
"""

import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.strategy.models import (
    Confidence,
    ContinuationCriteria,
    MonthlyDecision,
    MonthlyReview,
    StrategyChangeRecord,
    StrategyRecommendation,
    StrategyStatus,
    WeeklyDecision,
    WeeklyReview,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_strategy(**overrides):
    from src.strategy.models import Strategy
    defaults = dict(
        strategy_id="2026-08-test",
        status=StrategyStatus.ACTIVE,
        started_at=date(2026, 8, 4),
        review_date=date(2026, 8, 31),
        strategy_name="Test strategy",
        strategy_summary="Summary",
        market_context="Agencies go dark when busy",
        selected_problem="Owner-dependent presence",
        sales_hypothesis="If owners recognize the pattern, they want a system",
        why_now="Competition is up",
        commercial_goal="Generate qualified leads",
        primary_message="Presence should not depend on your free time",
        compound_presence_role="Demonstrate what systematic presence looks like",
        desired_reader_realization="That is happening to us",
        primary_cta_intent="reflection",
        continuation_criteria=ContinuationCriteria(
            description="At least 1 lead or strong engagement growth",
            indicators=["1+ leads", "growing saves/comments"],
        ),
        adjustment_criteria=ContinuationCriteria(
            description="Direction confirmed but execution weak",
            indicators=["No leads but engagement growing"],
        ),
        replacement_criteria=ContinuationCriteria(
            description="No leads and no positive trend after full cycle",
            indicators=["0 leads after 4 weeks", "declining or flat engagement"],
        ),
        research_references=["strategy/worldview.md"],
        confidence=Confidence.HIGH,
    )
    defaults.update(overrides)
    return Strategy(**defaults)


def _make_weekly_review(week: int = 1, decision: str = "CONTINUE", leads: int = 0) -> WeeklyReview:
    return WeeklyReview(
        strategy_id="2026-08-test",
        week_number=week,
        period_start=date(2026, 8, 4 + (week - 1) * 7),
        period_end=date(2026, 8, 8 + (week - 1) * 7),
        posts_published=3,
        leads_this_week=leads,
        leads_cumulative=leads,
        engagement_trend="flat",
        decision=WeeklyDecision(decision),
        rationale="Test rationale.",
    )


_VALID_WEEKLY_LLM_RESPONSE = json.dumps({
    "decision": "CONTINUE",
    "rationale": "Engagement is growing; criteria met.",
    "adjustments": [],
})

_VALID_MONTHLY_LLM_RESPONSE = json.dumps({
    "hypothesis_confirmed": False,
    "trend": "flat",
    "decision": "CONTINUE_WITH_ADJUSTMENTS",
    "rationale": "No leads but signals suggest the framing can improve.",
    "next_cycle_adjustments": ["More specific hooks"],
    "qualitative_assessment": "Saves are growing slowly.",
    "presence_debt_resonance": "Low",
    "lessons": ["Abstract hooks underperform"],
})

_VALID_RECOMMENDATION_LLM_RESPONSE = json.dumps({
    "recommended_action": "CONTINUE_WITH_ADJUSTMENTS",
    "confidence": "medium",
    "rationale": "Direction is right; execution needs tightening.",
    "proposed_adjustments": ["Sharper hooks for week 1"],
    "proposed_new_strategy_focus": "",
})


# ── WeeklyReview drafting ──────────────────────────────────────────────────────

class TestDraftWeeklyReview:
    def test_valid_inputs_return_weekly_review(self):
        strategy = _make_strategy()
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_WEEKLY_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_weekly_review
            review = draft_weekly_review(
                strategy=strategy,
                week_number=1,
                period_start="2026-08-04",
                period_end="2026-08-08",
                posts_published=3,
                leads_this_week=0,
                leads_cumulative=0,
                engagement_trend="flat",
            )
        assert isinstance(review, WeeklyReview)
        assert review.strategy_id == "2026-08-test"
        assert review.week_number == 1
        assert review.decision == WeeklyDecision.CONTINUE
        assert review.posts_published == 3

    def test_llm_exception_defaults_to_review_strategy(self):
        strategy = _make_strategy()
        with patch("src.strategy.decision_engine.chat", side_effect=RuntimeError("LLM unavailable")):
            from src.strategy.decision_engine import draft_weekly_review
            review = draft_weekly_review(
                strategy=strategy,
                week_number=2,
                period_start="2026-08-11",
                period_end="2026-08-15",
                posts_published=2,
            )
        assert review.decision == WeeklyDecision.REVIEW_STRATEGY
        assert "LLM draft failed" in review.rationale

    def test_unknown_decision_string_defaults_to_review_strategy(self):
        strategy = _make_strategy()
        bad_response = json.dumps({"decision": "UNKNOWN_THING", "rationale": "x", "adjustments": []})
        with patch("src.strategy.decision_engine.chat", return_value=bad_response):
            from src.strategy.decision_engine import draft_weekly_review
            review = draft_weekly_review(
                strategy=strategy,
                week_number=1,
                period_start="2026-08-04",
                period_end="2026-08-08",
                posts_published=3,
            )
        assert review.decision == WeeklyDecision.REVIEW_STRATEGY

    def test_adjustments_populated_for_adjust_execution(self):
        strategy = _make_strategy()
        response = json.dumps({
            "decision": "ADJUST_EXECUTION",
            "rationale": "Hooks too abstract.",
            "adjustments": ["More specific hooks", "Add MSP examples"],
        })
        with patch("src.strategy.decision_engine.chat", return_value=response):
            from src.strategy.decision_engine import draft_weekly_review
            review = draft_weekly_review(
                strategy=strategy,
                week_number=3,
                period_start="2026-08-18",
                period_end="2026-08-22",
                posts_published=3,
            )
        assert review.decision == WeeklyDecision.ADJUST_EXECUTION
        assert len(review.adjustments) == 2

    def test_top_performing_and_notes_passed_through(self):
        strategy = _make_strategy()
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_WEEKLY_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_weekly_review
            review = draft_weekly_review(
                strategy=strategy,
                week_number=1,
                period_start="2026-08-04",
                period_end="2026-08-08",
                posts_published=3,
                top_performing=["2026-08-test-w1-01"],
                qualitative_notes="Strong saves on article 1",
            )
        assert review.top_performing == ["2026-08-test-w1-01"]
        assert review.qualitative_notes == "Strong saves on article 1"


# ── MonthlyReview drafting ─────────────────────────────────────────────────────

class TestDraftMonthlyReview:
    def test_aggregates_leads_and_posts_correctly(self):
        strategy = _make_strategy()
        reviews = [
            _make_weekly_review(week=1, leads=0),
            _make_weekly_review(week=2, leads=1),
            _make_weekly_review(week=3, leads=0),
            _make_weekly_review(week=4, leads=2),
        ]
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_MONTHLY_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_monthly_review
            review = draft_monthly_review(strategy, reviews)
        assert review.total_leads == 3
        assert review.posts_published == 12

    def test_period_spans_first_to_last_week(self):
        strategy = _make_strategy()
        reviews = [
            _make_weekly_review(week=1),
            _make_weekly_review(week=4),
        ]
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_MONTHLY_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_monthly_review
            review = draft_monthly_review(strategy, reviews)
        assert review.period_start == date(2026, 8, 4)
        assert review.period_end == date(2026, 8, 29)

    def test_raises_on_empty_weekly_reviews(self):
        strategy = _make_strategy()
        with pytest.raises(ValueError, match="no weekly reviews"):
            from src.strategy.decision_engine import draft_monthly_review
            draft_monthly_review(strategy, [])

    def test_llm_exception_defaults_to_insufficient_data(self):
        strategy = _make_strategy()
        reviews = [_make_weekly_review(week=1)]
        with patch("src.strategy.decision_engine.chat", side_effect=RuntimeError("LLM down")):
            from src.strategy.decision_engine import draft_monthly_review
            review = draft_monthly_review(strategy, reviews)
        assert review.decision == MonthlyDecision.INSUFFICIENT_DATA

    def test_unknown_decision_defaults_to_insufficient_data(self):
        strategy = _make_strategy()
        reviews = [_make_weekly_review(week=1)]
        bad = json.dumps({"decision": "SOMETHING_ELSE", "rationale": "x", "trend": "flat",
                          "hypothesis_confirmed": None, "next_cycle_adjustments": [],
                          "qualitative_assessment": "", "presence_debt_resonance": "", "lessons": []})
        with patch("src.strategy.decision_engine.chat", return_value=bad):
            from src.strategy.decision_engine import draft_monthly_review
            review = draft_monthly_review(strategy, reviews)
        assert review.decision == MonthlyDecision.INSUFFICIENT_DATA

    def test_strategy_id_matches_input_strategy(self):
        strategy = _make_strategy()
        reviews = [_make_weekly_review(week=1)]
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_MONTHLY_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_monthly_review
            review = draft_monthly_review(strategy, reviews)
        assert review.strategy_id == "2026-08-test"


# ── StrategyRecommendation drafting ───────────────────────────────────────────

class TestDraftStrategyRecommendation:
    def _make_monthly_review(self, decision: str = "CONTINUE_WITH_ADJUSTMENTS") -> MonthlyReview:
        return MonthlyReview(
            strategy_id="2026-08-test",
            period_start=date(2026, 8, 4),
            period_end=date(2026, 8, 31),
            posts_published=12,
            total_leads=0,
            decision=MonthlyDecision(decision),
            rationale="No leads but signals suggest potential.",
            lessons=["Abstract hooks underperform"],
        )

    def test_returns_strategy_recommendation(self):
        strategy = _make_strategy()
        review = self._make_monthly_review()
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_RECOMMENDATION_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_strategy_recommendation
            rec = draft_strategy_recommendation(strategy, review, trigger_ref="strategy/reviews/monthly/test.json")
        assert isinstance(rec, StrategyRecommendation)
        assert rec.strategy_id == "2026-08-test"
        assert rec.recommended_action == MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS
        assert rec.trigger == "monthly_review"
        assert rec.trigger_ref == "strategy/reviews/monthly/test.json"

    def test_human_approved_defaults_to_none(self):
        strategy = _make_strategy()
        review = self._make_monthly_review()
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_RECOMMENDATION_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_strategy_recommendation
            rec = draft_strategy_recommendation(strategy, review)
        assert rec.human_approved is None

    def test_recommendation_id_is_unique(self):
        strategy = _make_strategy()
        review = self._make_monthly_review()
        with patch("src.strategy.decision_engine.chat", return_value=_VALID_RECOMMENDATION_LLM_RESPONSE):
            from src.strategy.decision_engine import draft_strategy_recommendation
            rec1 = draft_strategy_recommendation(strategy, review)
            rec2 = draft_strategy_recommendation(strategy, review)
        assert rec1.recommendation_id != rec2.recommendation_id

    def test_llm_exception_falls_back_to_monthly_decision(self):
        strategy = _make_strategy()
        review = self._make_monthly_review(decision="REPLACE_STRATEGY")
        with patch("src.strategy.decision_engine.chat", side_effect=RuntimeError("LLM down")):
            from src.strategy.decision_engine import draft_strategy_recommendation
            rec = draft_strategy_recommendation(strategy, review)
        assert rec.recommended_action == MonthlyDecision.REPLACE_STRATEGY
        assert rec.confidence == Confidence.LOW

    def test_replace_strategy_includes_new_focus(self):
        strategy = _make_strategy()
        review = self._make_monthly_review(decision="REPLACE_STRATEGY")
        response = json.dumps({
            "recommended_action": "REPLACE_STRATEGY",
            "confidence": "high",
            "rationale": "Hypothesis failed. Switch to case study approach.",
            "proposed_adjustments": [],
            "proposed_new_strategy_focus": "Direct client case studies for MSP segment",
        })
        with patch("src.strategy.decision_engine.chat", return_value=response):
            from src.strategy.decision_engine import draft_strategy_recommendation
            rec = draft_strategy_recommendation(strategy, review)
        assert rec.recommended_action == MonthlyDecision.REPLACE_STRATEGY
        assert "MSP" in rec.proposed_new_strategy_focus


# ── Model structure tests ──────────────────────────────────────────────────────

class TestDecisionModels:
    def test_strategy_recommendation_model_fields(self):
        rec = StrategyRecommendation(
            recommendation_id="rec-test-001",
            strategy_id="2026-08-test",
            generated_at=datetime(2026, 8, 31, 12, 0),
            trigger="monthly_review",
            trigger_ref="strategy/reviews/monthly/2026-08-test_monthly.json",
            recommended_action=MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS,
            confidence=Confidence.MEDIUM,
            rationale="Direction confirmed but hooks need sharpening.",
        )
        assert rec.human_approved is None
        assert rec.approved_at is None
        assert rec.proposed_adjustments == []
        assert rec.proposed_new_strategy_focus == ""

    def test_strategy_change_record_model_fields(self):
        record = StrategyChangeRecord(
            record_id="change-abc123",
            changed_at=datetime(2026, 9, 1, 9, 0),
            from_strategy_id="2026-08-presence-debt",
            decision=MonthlyDecision.REPLACE_STRATEGY,
            rationale="Hypothesis not confirmed after 4 weeks.",
            recommendation_id="rec-2026-08-abc12345",
            trigger_ref="strategy/reviews/monthly/2026-08-presence-debt_monthly.json",
        )
        assert record.to_strategy_id is None  # not yet created
        assert record.archived_to == ""

    def test_review_and_recommendation_are_separate_objects(self):
        review = MonthlyReview(
            strategy_id="2026-08-test",
            period_start=date(2026, 8, 4),
            period_end=date(2026, 8, 31),
            posts_published=12,
            decision=MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS,
            rationale="Analysis.",
        )
        rec = StrategyRecommendation(
            recommendation_id="rec-001",
            strategy_id="2026-08-test",
            generated_at=datetime(2026, 8, 31),
            trigger="monthly_review",
            trigger_ref="",
            recommended_action=MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS,
            confidence=Confidence.HIGH,
            rationale="Proposed action.",
        )
        # Review has no recommendation_id; recommendation has no posts_published
        assert not hasattr(review, "recommendation_id")
        assert not hasattr(rec, "posts_published")

    def test_weekly_decision_values_stable(self):
        assert WeeklyDecision.CONTINUE.value == "CONTINUE"
        assert WeeklyDecision.ADJUST_EXECUTION.value == "ADJUST_EXECUTION"
        assert WeeklyDecision.REVIEW_STRATEGY.value == "REVIEW_STRATEGY"

    def test_monthly_decision_values_stable(self):
        assert MonthlyDecision.CONTINUE_STRATEGY.value == "CONTINUE_STRATEGY"
        assert MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS.value == "CONTINUE_WITH_ADJUSTMENTS"
        assert MonthlyDecision.REPLACE_STRATEGY.value == "REPLACE_STRATEGY"
        assert MonthlyDecision.INSUFFICIENT_DATA.value == "INSUFFICIENT_DATA"
