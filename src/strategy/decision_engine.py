"""
Never Blank Strategy Engine — Decision Engine (Phase 4A).

Responsibilities:
  1. Draft WeeklyReview with LLM-suggested decision + rationale
  2. Draft MonthlyReview by aggregating weekly reviews
  3. Draft StrategyRecommendation as a separate strategic artifact

Review   = analysis of what happened
Recommendation = proposed strategic action
These are different concerns and different models.

LLM does the analysis; human approves the recommendation before any strategy change.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from src.strategy.models import (
    Confidence,
    MonthlyDecision,
    MonthlyReview,
    Strategy,
    StrategyRecommendation,
    WeeklyDecision,
    WeeklyReview,
)
from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("strategy.decision_engine")


# ── Weekly Review ──────────────────────────────────────────────────────────────

_WEEKLY_SYSTEM = """You are a strategy advisor for Never Blank, a B2B content marketing firm.

Never Blank runs month-long content strategies and evaluates them weekly.
Each strategy has three sets of criteria:
  continuation_criteria  → CONTINUE (strategy is working as expected)
  adjustment_criteria    → ADJUST_EXECUTION (direction right, execution needs refinement)
  replacement_criteria   → REVIEW_STRATEGY (strategy itself may be wrong)

Your task: read the weekly performance data and the active strategy criteria.
Suggest a decision and write a concise rationale (2-3 sentences).
If ADJUST_EXECUTION, list specific adjustments.

Return JSON only:
{
  "decision": "CONTINUE" | "ADJUST_EXECUTION" | "REVIEW_STRATEGY",
  "rationale": "...",
  "adjustments": ["...", "..."]
}"""


def draft_weekly_review(
    strategy: Strategy,
    week_number: int,
    period_start: str,
    period_end: str,
    posts_published: int,
    leads_this_week: int = 0,
    leads_cumulative: int = 0,
    engagement_trend: str = "insufficient_data",
    top_performing: Optional[list[str]] = None,
    qualitative_notes: str = "",
) -> WeeklyReview:
    """
    Draft a WeeklyReview with LLM-suggested decision and rationale.

    LLM reads the strategy criteria + performance inputs → suggests
    WeeklyDecision + rationale + adjustments.
    All inputs remain editable — this is a draft, not a final decision.
    """
    from datetime import date as date_type
    period_start_date = date_type.fromisoformat(period_start)
    period_end_date = date_type.fromisoformat(period_end)

    user = f"""Active strategy: {strategy.strategy_name}
Strategy ID: {strategy.strategy_id}
Week {week_number} of the cycle (started {strategy.started_at}, review due {strategy.review_date})

CONTINUATION CRITERIA (→ CONTINUE):
{strategy.continuation_criteria.description}
Indicators: {", ".join(strategy.continuation_criteria.indicators)}

ADJUSTMENT CRITERIA (→ ADJUST_EXECUTION):
{strategy.adjustment_criteria.description}
Indicators: {", ".join(strategy.adjustment_criteria.indicators)}

REPLACEMENT CRITERIA (→ REVIEW_STRATEGY):
{strategy.replacement_criteria.description}
Indicators: {", ".join(strategy.replacement_criteria.indicators)}

WEEK {week_number} PERFORMANCE DATA:
  Posts published this week: {posts_published}
  Leads this week: {leads_this_week}
  Leads cumulative: {leads_cumulative}
  Engagement trend: {engagement_trend}
  Top performing content: {", ".join(top_performing or []) or "none identified yet"}
  Qualitative notes: {qualitative_notes or "none"}

Suggest the weekly decision. Return JSON only."""

    try:
        raw = chat(_WEEKLY_SYSTEM, user, json_mode=True, model=model_article())
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        log.error("Weekly review LLM call failed: %s — defaulting to REVIEW_STRATEGY", exc)
        data = {
            "decision": "REVIEW_STRATEGY",
            "rationale": f"LLM draft failed ({exc}). Manual review required.",
            "adjustments": [],
        }

    decision_str = data.get("decision", "REVIEW_STRATEGY")
    try:
        decision = WeeklyDecision(decision_str)
    except ValueError:
        log.warning("LLM returned unknown decision %r — defaulting to REVIEW_STRATEGY", decision_str)
        decision = WeeklyDecision.REVIEW_STRATEGY

    review = WeeklyReview(
        strategy_id=strategy.strategy_id,
        week_number=week_number,
        period_start=period_start_date,
        period_end=period_end_date,
        posts_published=posts_published,
        leads_this_week=leads_this_week,
        leads_cumulative=leads_cumulative,
        engagement_trend=engagement_trend,
        top_performing=top_performing or [],
        decision=decision,
        rationale=data.get("rationale", ""),
        adjustments=data.get("adjustments", []),
        qualitative_notes=qualitative_notes,
    )
    log.info(
        "Weekly review drafted: strategy=%s week=%d decision=%s",
        strategy.strategy_id, week_number, decision.value,
    )
    return review


# ── Monthly Review ─────────────────────────────────────────────────────────────

_MONTHLY_SYSTEM = """You are a strategy advisor for Never Blank.

Your task: read all weekly reviews for the strategy cycle and produce a monthly assessment.

Evaluate:
1. Was the hypothesis confirmed? (did the content generate leads or qualified pipeline?)
2. What is the overall trend? (growing / flat / declining / insufficient_data)
3. What is the strategic decision?
   CONTINUE_STRATEGY          — hypothesis confirmed, strategy is working
   CONTINUE_WITH_ADJUSTMENTS  — direction right, execution or framing needs change
   REPLACE_STRATEGY           — hypothesis not confirmed after full cycle, need new strategy
   INSUFFICIENT_DATA          — fewer than 3 weeks of data, cannot evaluate

Return JSON:
{
  "hypothesis_confirmed": true | false | null,
  "trend": "growing" | "flat" | "declining" | "insufficient_data",
  "decision": "CONTINUE_STRATEGY" | "CONTINUE_WITH_ADJUSTMENTS" | "REPLACE_STRATEGY" | "INSUFFICIENT_DATA",
  "rationale": "2-4 sentences",
  "next_cycle_adjustments": ["...", "..."],
  "qualitative_assessment": "...",
  "presence_debt_resonance": "...",
  "lessons": ["...", "..."]
}"""


def draft_monthly_review(
    strategy: Strategy,
    weekly_reviews: list[WeeklyReview],
) -> MonthlyReview:
    """
    Draft a MonthlyReview by aggregating all weekly reviews with LLM assistance.

    Aggregates lead counts, trend patterns, adjustments, and qualitative notes.
    LLM synthesizes MonthlyDecision + lessons + assessment.
    """
    if not weekly_reviews:
        raise ValueError("Cannot draft monthly review: no weekly reviews provided")

    # Validate: all reviews must reference the same strategy
    wrong_sid = [r.strategy_id for r in weekly_reviews if r.strategy_id != strategy.strategy_id]
    if wrong_sid:
        raise ValueError(
            f"Weekly reviews contain wrong strategy_id: {wrong_sid}. "
            f"Expected: {strategy.strategy_id}"
        )

    # Validate: no duplicate week numbers
    week_numbers = [r.week_number for r in weekly_reviews]
    duplicates = [w for w in set(week_numbers) if week_numbers.count(w) > 1]
    if duplicates:
        raise ValueError(f"Duplicate week_number(s) in weekly reviews: {duplicates}")

    # Sort by week number for consistent ordering
    reviews = sorted(weekly_reviews, key=lambda r: r.week_number)

    # Deterministic INSUFFICIENT_DATA guard: < 3 unique weeks → LLM cannot reliably decide.
    # This is a code rule, not an LLM suggestion — LLM can write the rationale but not override it.
    unique_weeks = {r.week_number for r in reviews}
    if len(unique_weeks) < 3:
        rationale = (
            f"Insufficient data: only {len(unique_weeks)} week(s) of data available "
            f"(minimum 3 required for a reliable monthly decision). "
            f"Continue collecting data before making a strategic decision."
        )
        log.info(
            "Monthly review forced to INSUFFICIENT_DATA: %d unique week(s) for strategy %s",
            len(unique_weeks), strategy.strategy_id,
        )
        return MonthlyReview(
            strategy_id=strategy.strategy_id,
            period_start=reviews[0].period_start,
            period_end=reviews[-1].period_end,
            posts_published=sum(r.posts_published for r in reviews),
            total_leads=sum(r.leads_this_week for r in reviews),
            decision=MonthlyDecision.INSUFFICIENT_DATA,
            rationale=rationale,
        )

    total_leads = sum(r.leads_this_week for r in reviews)
    total_posts = sum(r.posts_published for r in reviews)
    period_start = reviews[0].period_start
    period_end = reviews[-1].period_end
    cumulative_leads = max((r.leads_cumulative for r in reviews), default=0)
    trends = [r.engagement_trend for r in reviews if r.engagement_trend]
    weekly_decisions = [r.decision.value for r in reviews]
    all_adjustments = [a for r in reviews for a in r.adjustments]

    weeks_summary = "\n".join(
        f"  Week {r.week_number}: {r.decision.value} | leads={r.leads_this_week} | "
        f"trend={r.engagement_trend} | notes={r.qualitative_notes[:100] if r.qualitative_notes else 'none'}"
        for r in reviews
    )

    user = f"""Strategy: {strategy.strategy_name} ({strategy.strategy_id})
Cycle: {strategy.started_at} → {strategy.review_date}
Hypothesis: {strategy.sales_hypothesis}
Primary message: {strategy.primary_message}

WEEKLY REVIEW SUMMARY:
{weeks_summary}

AGGREGATED METRICS:
  Total posts published: {total_posts}
  Total leads: {total_leads} (cumulative per last week: {cumulative_leads})
  Weekly decisions: {" → ".join(weekly_decisions)}
  Adjustments made during cycle: {", ".join(all_adjustments) or "none"}
  Engagement trends by week: {" → ".join(trends) or "insufficient_data"}

STRATEGY CRITERIA:
  Continuation: {strategy.continuation_criteria.description}
  Adjustment:   {strategy.adjustment_criteria.description}
  Replacement:  {strategy.replacement_criteria.description}

Synthesize the monthly assessment. Return JSON only."""

    try:
        raw = chat(_MONTHLY_SYSTEM, user, json_mode=True, model=model_article())
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        log.error("Monthly review LLM call failed: %s", exc)
        data = {
            "hypothesis_confirmed": None,
            "trend": "insufficient_data",
            "decision": "INSUFFICIENT_DATA",
            "rationale": f"LLM draft failed ({exc}). Manual review required.",
            "next_cycle_adjustments": [],
            "qualitative_assessment": "",
            "presence_debt_resonance": "",
            "lessons": [],
        }

    decision_str = data.get("decision", "INSUFFICIENT_DATA")
    try:
        decision = MonthlyDecision(decision_str)
    except ValueError:
        log.warning("LLM returned unknown monthly decision %r — defaulting to INSUFFICIENT_DATA", decision_str)
        decision = MonthlyDecision.INSUFFICIENT_DATA

    review = MonthlyReview(
        strategy_id=strategy.strategy_id,
        period_start=period_start,
        period_end=period_end,
        posts_published=total_posts,
        total_leads=total_leads,
        qualified_leads=0,  # requires manual input or analytics adapter (Phase 4D)
        hypothesis_confirmed=data.get("hypothesis_confirmed"),
        trend=data.get("trend", "insufficient_data"),
        decision=decision,
        rationale=data.get("rationale", ""),
        next_cycle_adjustments=data.get("next_cycle_adjustments", []),
        qualitative_assessment=data.get("qualitative_assessment", ""),
        presence_debt_resonance=data.get("presence_debt_resonance", ""),
        lessons=data.get("lessons", []),
    )
    log.info(
        "Monthly review drafted: strategy=%s decision=%s hypothesis_confirmed=%s",
        strategy.strategy_id, decision.value, review.hypothesis_confirmed,
    )
    return review


# ── Strategy Recommendation ────────────────────────────────────────────────────

_RECOMMENDATION_SYSTEM = """You are a strategy advisor for Never Blank.

A monthly review has been completed. Your task: draft a StrategyRecommendation —
a concrete proposed action for the next cycle.

Review = analysis of what happened.
Recommendation = what to do next. These are different.

Based on the monthly decision:
  CONTINUE_STRATEGY         → rationale for continuing, reinforcement focus
  CONTINUE_WITH_ADJUSTMENTS → specific adjustments to framing, hooks, or CTA approach
  REPLACE_STRATEGY          → proposed new strategic focus (what problem/audience/hypothesis to try next)
  INSUFFICIENT_DATA         → propose extending the current cycle by N weeks

Return JSON:
{
  "recommended_action": "CONTINUE_STRATEGY" | "CONTINUE_WITH_ADJUSTMENTS" | "REPLACE_STRATEGY" | "INSUFFICIENT_DATA",
  "confidence": "high" | "medium" | "low",
  "rationale": "2-3 sentences",
  "proposed_adjustments": ["...", "..."],
  "proposed_new_strategy_focus": "..."
}"""


def draft_strategy_recommendation(
    strategy: Strategy,
    monthly_review: MonthlyReview,
    trigger_ref: str = "",
) -> StrategyRecommendation:
    """
    Draft a StrategyRecommendation from a completed MonthlyReview.

    This is a separate artifact from the review itself.
    Human approval (human_approved field) is required before any strategy change.
    """
    user = f"""Strategy: {strategy.strategy_name} ({strategy.strategy_id})
Hypothesis: {strategy.sales_hypothesis}

MONTHLY REVIEW OUTCOME:
  Decision: {monthly_review.decision.value}
  Rationale: {monthly_review.rationale}
  Hypothesis confirmed: {monthly_review.hypothesis_confirmed}
  Trend: {monthly_review.trend}
  Total leads: {monthly_review.total_leads}
  Lessons: {", ".join(monthly_review.lessons) or "none"}
  Next cycle adjustments proposed by review: {", ".join(monthly_review.next_cycle_adjustments) or "none"}
  Qualitative assessment: {monthly_review.qualitative_assessment or "none"}

Draft the strategic recommendation. Return JSON only."""

    try:
        raw = chat(_RECOMMENDATION_SYSTEM, user, json_mode=True, model=model_article())
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        log.error("Recommendation LLM call failed: %s", exc)
        data = {
            "recommended_action": monthly_review.decision.value,
            "confidence": "low",
            "rationale": f"LLM draft failed ({exc}). Manual review required.",
            "proposed_adjustments": [],
            "proposed_new_strategy_focus": "",
        }

    action_str = data.get("recommended_action", monthly_review.decision.value)
    try:
        action = MonthlyDecision(action_str)
    except ValueError:
        action = monthly_review.decision

    confidence_str = data.get("confidence", "low")
    try:
        confidence = Confidence(confidence_str)
    except ValueError:
        confidence = Confidence.LOW

    rec_id = f"rec-{strategy.strategy_id}-{uuid.uuid4().hex[:8]}"
    recommendation = StrategyRecommendation(
        recommendation_id=rec_id,
        strategy_id=strategy.strategy_id,
        generated_at=datetime.now(),
        trigger="monthly_review",
        trigger_ref=trigger_ref,
        recommended_action=action,
        confidence=confidence,
        rationale=data.get("rationale", ""),
        proposed_adjustments=data.get("proposed_adjustments", []),
        proposed_new_strategy_focus=data.get("proposed_new_strategy_focus", ""),
    )
    log.info(
        "Strategy recommendation drafted: id=%s action=%s confidence=%s",
        rec_id, action.value, confidence.value,
    )
    return recommendation
