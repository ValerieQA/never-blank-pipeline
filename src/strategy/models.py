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

from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# Re-export the single source of truth for CTA mode (decision 45).
from src.models import CTAMode

# Analytics metric: None = unavailable from API, 0 = confirmed zero,
# "not_collected" = data retrieval not yet attempted.
MetricValue = Optional[Union[int, Literal["not_collected"]]]


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


# ── Visibility Intelligence stream enums ───────────────────────────────────────
# ProductCategory = NB's signal type (what the post does for the reader).
# StrategicTopic  = quota-tracking bucket (40% AI Visibility / 60% Brand Concept).
# BrandConcept    = verified Never Blank proprietary terms only; do not add here
#                   until a term is confirmed as part of the brand language.
# content_format  = editorial implementation detail (checklist, how_to, etc.) —
#                   lives as a plain string in visibility_queue.jsonl only, not here.

class ProductCategory(str, Enum):
    PRESENCE_CHECK       = "presence_check"        # audit: is your presence working?
    PRESENCE_SCRIPT      = "presence_script"        # action: exact language / template
    VISIBILITY_FRAMEWORK = "visibility_framework"   # mental model for presence decisions


class StrategicTopic(str, Enum):
    AI_VISIBILITY  = "ai_visibility"   # AI search, LLM findability
    BRAND_CONCEPT  = "brand_concept"   # presence frameworks, NB concepts
    CUSTOMER_TRUST = "customer_trust"  # trust signals, proof


class BrandConcept(str, Enum):
    COMPOUND_PRESENCE    = "compound_presence"      # verified NB term
    PRESENCE_DEBT        = "presence_debt"           # verified NB term
    TRUST_BEFORE_CONTACT = "trust_before_contact"   # verified NB term


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
    # Traceability: machine-readable links back to source research signals.
    source_signal_ids:            list[str] = Field(default_factory=list)
    source_urls:                  list[str] = Field(default_factory=list)
    small_business_situation:     str
    underlying_mechanism:         str
    customer_behavior:            str
    business_risk:                str
    business_opportunity:         str
    sales_relevance:              str
    content_relevance:            str
    compound_presence_relevance:  str
    confidence:                   Confidence

    @field_validator(
        "pattern_name", "underlying_mechanism", "business_risk",
        "sales_relevance", "compound_presence_relevance",
    )
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required PatternRecord field cannot be empty — LLM returned no content")
        return v


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
    primary_cta_intent:       CTAMode
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
    compound_presence_connection: str           # semantic, not structural — what the connection IS
    echo:                         Optional[str] = None  # null allowed as rare exception (decision 43)
    echo_omission_reason:         Optional[str] = None  # required when echo is null
    cta_mode:                     CTAMode = "none"
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
    # Traceability: which pattern generated this item (machine-readable).
    source_pattern_id:            Optional[str] = None
    status:                       str          = "planned"

    # Visibility Intelligence stream metadata (None for recognition posts).
    product_category:             Optional[ProductCategory] = None
    strategic_topic:              Optional[StrategicTopic]  = None
    brand_concept:                Optional[BrandConcept]    = None

    @field_validator("hook", "mechanism", "reframe", "sales_objective")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required content plan field cannot be empty")
        return v


# ── Visibility Intelligence history & quota ────────────────────────────────────

class VisibilityHistoryEntry(BaseModel):
    """Immutable snapshot written to visibility_history.jsonl at publish time.

    Decoupled from PublishedEntry intentionally: recognition and visibility
    streams maintain separate histories so neither contaminates the other.
    """
    content_id:        str
    published_at:      datetime
    product_category:  Optional[ProductCategory] = None
    strategic_topic:   Optional[StrategicTopic]  = None
    brand_concept:     Optional[BrandConcept]     = None
    # Open string — not an enum; new formats added without code change.
    content_format:    str                        = ""
    source_queue_item: dict[str, Any]             = Field(default_factory=dict)

    @field_validator("content_id")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content_id cannot be empty")
        return v


@dataclass
class VisibilityQuotaResult:
    """Result of validate_visibility_quota().  Never raises — always returns this."""
    total_items:             int
    ai_visibility_count:     int
    brand_concept_count:     int
    ai_visibility_required:  int          # ceil(total * 0.40)
    brand_concept_required:  int          # ceil(total * 0.60)
    is_valid:                bool
    warnings:                list[str] = dc_field(default_factory=list)


# ── Visibility Intelligence queue & generation models ─────────────────────────

class VisibilityQueueItem(BaseModel):
    """One entry in data/strategy/visibility_queue.jsonl."""
    id:               str
    title:            str
    product_category: ProductCategory
    # content_format is an open string (not an enum) — new formats added in the
    # queue file without changing Python code. Examples: "checklist", "how_to",
    # "myth_bust", "stat_context", "audit", "scorecard".
    content_format:   str
    strategic_topic:  StrategicTopic
    brand_concept:    Optional[BrandConcept]                    = None
    target_audience:  str                                       = ""
    key_points:       list[str]                                 = Field(default_factory=list)
    # State machine: queued → processing → published | published_with_errors | failed | skipped
    # processing is a transient guard against double-claiming the same item.
    status:                  Literal[
                                 "queued",
                                 "processing",
                                 "published",
                                 "published_with_errors",
                                 "failed",
                                 "skipped",
                             ] = "queued"
    # Operational fields — written by the publishing script, not by editorial curation.
    attempt_count:           int              = 0
    last_error:              Optional[str]    = None
    processing_started_at:   Optional[datetime] = None
    published_at:            Optional[datetime]  = None

    @field_validator("id", "title")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required VisibilityQueueItem field cannot be empty")
        return v


class VIGeneratedOutput(BaseModel):
    """Domain model for LLM-generated Visibility Intelligence content.

    Architectural Principle — Partial Regeneration:
        Recognition content is generated as a narrative chain where each stage
        depends on the previous one. Partial regeneration is therefore unsafe.

        Visibility Intelligence content is generated as a structured object.
        Individual platform outputs are independent of each other. A failed
        field may be regenerated individually without regenerating the entire
        package. This is an intentional property of the VI generation design,
        not an implementation detail.

    This model is the LLM output boundary. It does NOT know about _generated.json
    or any downstream transport format. Use to_generated_package() to map it.
    """
    headline:          str
    blog_article:      str
    linkedin_post:     str
    facebook_post:     str
    instagram_caption: str
    threads_sequence:  list[str]
    telegram_text:     str
    echo:              Optional[str] = None

    @field_validator("headline", "blog_article", "linkedin_post",
                     "facebook_post", "instagram_caption", "telegram_text")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("VIGeneratedOutput field cannot be empty — LLM returned no content")
        return v

    @field_validator("threads_sequence")
    @classmethod
    def threads_min_items(cls, v: list[str]) -> list[str]:
        if len(v) < 3:
            raise ValueError(f"threads_sequence must have at least 3 items, got {len(v)}")
        return v


@dataclass
class RepairRequest:
    """Describes one failed constraint to be fixed by a targeted repair call.

    The repair LLM receives current_value + failed_constraints so it knows
    exactly what to fix — not the full generation context. This keeps repair
    calls focused and deterministic.
    """
    field_name:          str
    current_value:       str
    failed_constraints:  list[str]   = dc_field(default_factory=list)


# ── Analytics ──────────────────────────────────────────────────────────────────

NOT_COLLECTED = "not_collected"


class AnalyticsRecord(BaseModel):
    content_id:       str
    platform:         str
    published_at:     Optional[datetime]      = None
    collected_at:     Optional[datetime]      = None
    # Metrics use MetricValue: None = unavailable from API, 0 = confirmed zero,
    # "not_collected" = retrieval not yet attempted for this period.
    impressions:      MetricValue             = None
    reach:            MetricValue             = None
    views:            MetricValue             = None
    likes:            MetricValue             = None
    comments:         MetricValue             = None
    shares:           MetricValue             = None
    saves:            MetricValue             = None
    profile_visits:   MetricValue             = None
    new_followers:    MetricValue             = None
    link_clicks:      MetricValue             = None
    website_sessions: MetricValue             = None
    cta_actions:      MetricValue             = None
    leads:            MetricValue             = None
    qualified_leads:  MetricValue             = None
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


# ── Decision artifacts ─────────────────────────────────────────────────────────
#
# Review   = analysis of what happened (WeeklyReview / MonthlyReview above)
# Recommendation = proposed strategic action (separate concern)
# StrategyChangeRecord = audit trail when strategy is replaced

class StrategyRecommendation(BaseModel):
    recommendation_id:           str            # e.g. "rec-2026-08-w4"
    strategy_id:                 str
    generated_at:                datetime
    trigger:                     str            # "weekly_review" | "monthly_review" | "manual"
    trigger_ref:                 str            # path to the review JSON that triggered this
    recommended_action:          MonthlyDecision
    confidence:                  Confidence
    rationale:                   str
    proposed_adjustments:        list[str]      = Field(default_factory=list)
    proposed_new_strategy_focus: str            = ""  # populated only when REPLACE_STRATEGY
    human_approved:              Optional[bool] = None
    approved_at:                 Optional[datetime] = None
    notes:                       str            = ""

    @field_validator("approved_at")
    @classmethod
    def approved_at_requires_approval(cls, v: Optional[datetime], info: Any) -> Optional[datetime]:
        if v is not None and info.data.get("human_approved") is False:
            raise ValueError("approved_at cannot be set when human_approved is False")
        return v


class StrategyChangeRecord(BaseModel):
    record_id:          str
    changed_at:         datetime
    from_strategy_id:   str
    to_strategy_id:     Optional[str]  = None  # None until new strategy is created
    decision:           MonthlyDecision
    rationale:          str
    recommendation_id:  Optional[str]  = None
    trigger_ref:        str            = ""    # path to monthly review that triggered change
    archived_to:        str            = ""    # path in strategy/history/strategies/


# ── Published Content Index ────────────────────────────────────────────────────
#
# One entry per published signal (canonical record — not per platform).
# Foundation for Echo Memory (4C) and Analytics Collectors (4D).
#
# Platform-native IDs and per-platform publish metadata live in `publications`
# (a dict keyed by platform name). Collectors read external_id from there;
# publish_packages.py populates it after each publish run.

class PlatformPublication(BaseModel):
    """Metadata for one platform's publish of a content signal."""
    platform:    str
    external_id: Optional[str] = None   # Wix post_id, LinkedIn URN, Instagram media ID, etc.
    url:         str = ""
    published_at: Optional[datetime] = None
    status:      str = "published"       # "published" | "draft_created"


class PublishedEntry(BaseModel):
    content_id:    str
    strategy_id:   str
    pattern_id:    Optional[str] = None   # from content plan; may be absent for ad-hoc signals
    published_at:  datetime
    platform:      str = "blog"           # canonical platform; blog = primary
    url:           str = ""              # blog/Wix URL when available
    platform_content_id: Optional[str] = None  # deprecated alias for publications["blog"].external_id
    publications:  dict[str, PlatformPublication] = Field(default_factory=dict)
    echo:          Optional[str] = None  # echo_line used in the published article
    hook:          str = ""
    topic:         str = ""
    cta_mode:      str = "none"
    strategy_week: Optional[int] = None  # week number in strategy cycle; used by mark_entries_reviewed
    reviewed:      bool = False          # set to True after weekly review covers this entry

    # ── Analytics fields (Phase 4D) ──────────────────────────────────────────
    # Raw metrics from platform APIs are stored elsewhere; only the derived
    # score lands here so that the scoring formula can change independently
    # of the collector. analytics_version identifies which formula produced it.
    analytics_score:      Optional[float] = None  # normalized 0.0–1.0; None = not yet collected
    analytics_fetched_at: Optional[datetime] = None
    analytics_version:    Optional[str] = None    # e.g. "v1", "v2" — tracks formula revision

    @field_validator("content_id", "strategy_id")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required PublishedEntry field cannot be empty")
        return v

    @model_validator(mode="after")
    def _backfill_blog_publication(self) -> "PublishedEntry":
        # Migrate legacy platform_content_id into publications["blog"] on first read.
        # This covers entries written before the publications map was introduced.
        if self.platform_content_id and "blog" not in self.publications:
            self.publications["blog"] = PlatformPublication(
                platform="blog",
                external_id=self.platform_content_id,
                url=self.url,
                published_at=self.published_at,
                status="published",
            )
        return self
