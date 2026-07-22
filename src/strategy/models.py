"""
Never Blank Strategy Engine — data models.

All strategy artifacts are defined here. These models are the source of truth
for JSON schema in strategy/current/ and strategy/history/.

Key design decisions:
- cta_mode uses the existing CTAMode enum from src/models.py (decisions 18, 45)
- target_audience is always the segment from decision 34 (agencies/consultants/MSPs)
- Analytics uses None for unavailable data, 0 for confirmed zero (not_collected = string sentinel)
- Strategy does not auto-replace monthly — continuation_criteria controls this
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class Confidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class WeeklyDecision(str, Enum):
    CONTINUE          = "CONTINUE"
    ADJUST_EXECUTION  = "ADJUST_EXECUTION"
    REVIEW_STRATEGY   = "REVIEW_STRATEGY"


class MonthlyDecision(str, Enum):
    CONTINUE_STRATEGY       = "CONTINUE_STRATEGY"
    CONTINUE_WITH_ADJUSTMENTS = "CONTINUE_WITH_ADJUSTMENTS"
    REPLACE_STRATEGY        = "REPLACE_STRATEGY"
    INSUFFICIENT_DATA       = "INSUFFICIENT_DATA"


class ContentRole(str, Enum):
    RECOGNITION = "recognition"
    EDUCATION   = "education"
    PROOF       = "proof"
    REFRAME     = "reframe"
    OBJECTION   = "objection"
    CONVERSION  = "conversion"


class StrategyStatus(str, Enum):
    ACTIVE    = "active"
    PAUSED    = "paused"
    COMPLETED = "completed"
    REPLACED  = "replaced"


# ── Market signals ─────────────────────────────────────────────────────────────

class MarketSignal(BaseModel):
    signal:                        str
    source:                        str
    source_date:                   Optional[str] = None
    market_area:                   str
    affected_audience:             str
    change_detected:               str
    why_it_matters:                str
    business_implication:          str
    sales_implication:             str
    compound_presence_implication: str
    confidence:                    Confidence
    freshness:                     str
    evidence:                      list[str] = Field(default_factory=list)


# ── Pattern Extractor ──────────────────────────────────────────────────────────

class PatternRecord(BaseModel):
    pattern_id:                   str
    pattern_name:                 str
    observed_signals:             list[str] = Field(default_factory=list)
    small_business_situation:     str
    underlying_mechanism:         str
    customer_behavior:            str
    business_risk:                str
    business_opportunity:         str
    sales_relevance:              str
    content_relevance:            str
    compound_presence_relevance:  str
    confidence:                   Confidence


# ── Monthly Sales Strategy ─────────────────────────────────────────────────────

class SuccessCriteria(BaseModel):
    leads_target:             int = 1
    early_signal_description: str = ""
    min_weeks_to_evaluate:    int = 4


class ContinuationCriteria(BaseModel):
    description: str
    indicators:  list[str] = Field(default_factory=list)


class Strategy(BaseModel):
    strategy_id:              str            # e.g. "2026-08-presence-debt"
    status:                   StrategyStatus = StrategyStatus.ACTIVE
    started_at:               date
    review_date:              date
    strategy_name:            str
    strategy_summary:         str
    market_context:           str
    selected_problem:         str
    target_audience:          str = "Small B2B service businesses with a single decision-maker — agencies, consultants, MSPs"
    sales_hypothesis:         str
    why_now:                  str
    commercial_goal:          str
    primary_message:          str
    supporting_messages:      list[str]      = Field(default_factory=list)
    compound_presence_role:   str
    desired_reader_realization: str
    primary_cta_intent:       str
    success_criteria:         SuccessCriteria = Field(default_factory=SuccessCriteria)
    continuation_criteria:    ContinuationCriteria
    adjustment_criteria:      ContinuationCriteria
    replacement_criteria:     ContinuationCriteria
    research_references:      list[str]      = Field(default_factory=list)
    confidence:               Confidence
    presence_debt_focus:      bool           = False  # Campaign 1 flagship concept

    @field_validator("market_context", "selected_problem", "sales_hypothesis",
                     "commercial_goal", "compound_presence_role")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required strategy field cannot be empty")
        return v


# ── Content Plan ───────────────────────────────────────────────────────────────

class ContentPlanItem(BaseModel):
    content_id:                   str
    week:                         int
    publication_date:             Optional[date] = None
    strategy_id:                  str
    content_role:                 ContentRole
    topic:                        str
    working_title:                str
    target_reader:                str
    reader_problem:               str
    market_signal:                str
    pattern:                      str
    sales_objective:              str
    main_argument:                str
    hook:                         str
    recognition:                  str
    mechanism:                    str
    business_consequence:         str
    reframe:                      str
    compound_presence_connection: str          # semantic, not structural — what the connection IS
    echo:                         str          # required (null only in rare exception, decision 43)
    cta_mode:                     str          # maps to CTAMode enum in src/models.py
    cta:                          str
    website_angle:                str
    linkedin_angle:               str
    instagram_angle:              str
    facebook_angle:               str
    threads_angle:                str
    telegram_angle:               str
    seo_keywords:                 list[str]    = Field(default_factory=list)
    geo_questions:                list[str]    = Field(default_factory=list)
    internal_links:               list[str]    = Field(default_factory=list)
    status:                       str          = "planned"

    @field_validator("hook", "mechanism", "reframe", "sales_objective")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required content plan field cannot be empty")
        return v


# ── Analytics ──────────────────────────────────────────────────────────────────

NOT_COLLECTED = "not_collected"


class AnalyticsRecord(BaseModel):
    content_id:       str
    platform:         str
    published_at:     Optional[datetime]      = None
    collected_at:     Optional[datetime]      = None
    # Metrics: None = unavailable from API, 0 = confirmed zero, NOT_COLLECTED = not yet retrieved
    impressions:      Optional[int]           = None
    reach:            Optional[int]           = None
    views:            Optional[int]           = None
    likes:            Optional[int]           = None
    comments:         Optional[int]           = None
    shares:           Optional[int]           = None
    saves:            Optional[int]           = None
    profile_visits:   Optional[int]           = None
    new_followers:    Optional[int]           = None
    link_clicks:      Optional[int]           = None
    website_sessions: Optional[int]           = None
    cta_actions:      Optional[int]           = None
    leads:            Optional[int]           = None
    qualified_leads:  Optional[int]           = None
    notes:            str                     = ""


# ── Weekly and Monthly Reviews ─────────────────────────────────────────────────

class WeeklyReview(BaseModel):
    strategy_id:       str
    week_number:       int
    period_start:      date
    period_end:        date
    posts_published:   int
    leads_this_week:   int                    = 0
    leads_cumulative:  int                    = 0
    engagement_trend:  str                    = ""   # "growing" | "flat" | "declining" | "insufficient_data"
    top_performing:    list[str]              = Field(default_factory=list)  # content_ids
    decision:          WeeklyDecision
    rationale:         str
    adjustments:       list[str]              = Field(default_factory=list)
    qualitative_notes: str                    = ""   # human or LLM-assisted reading of comments


class MonthlyReview(BaseModel):
    strategy_id:                str
    period_start:               date
    period_end:                 date
    posts_published:            int
    total_leads:                int                   = 0
    qualified_leads:            int                   = 0
    top_hooks:                  list[str]             = Field(default_factory=list)
    top_echoes:                 list[str]             = Field(default_factory=list)
    top_cta_modes:              list[str]             = Field(default_factory=list)
    top_platforms:              list[str]             = Field(default_factory=list)
    outlier_posts:              list[str]             = Field(default_factory=list)
    hypothesis_confirmed:       Optional[bool]        = None
    trend:                      str                   = ""
    decision:                   MonthlyDecision
    rationale:                  str
    next_cycle_adjustments:     list[str]             = Field(default_factory=list)
    qualitative_assessment:     str                   = ""
    presence_debt_resonance:    str                   = ""   # Campaign 1 specific
    lessons:                    list[str]             = Field(default_factory=list)
