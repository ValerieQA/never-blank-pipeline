from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ObservationType(str, Enum):
    PATTERN = "pattern"
    PARADOX = "paradox"
    REVERSAL = "reversal"
    GAP = "gap"
    BEHAVIOR_DELTA = "behavior_delta"
    SIGNAL_CLUSTER = "signal_cluster"
    IMPLICATION = "implication"


class ContentGoal(str, Enum):
    EDUCATE = "educate"
    CHALLENGE = "challenge"
    DEMONSTRATE = "demonstrate"
    INVITE = "invite"


class ChannelStatus(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    SKIPPED = "skipped"
    FAILED = "failed"
    PENDING = "pending"


class RunStatus(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    PARTIAL = "partial"
    ORANGE = "orange"
    RED = "red"


class QCFailureType(str, Enum):
    TYPE1 = "type1"  # technical
    TYPE2 = "type2"  # quality
    TYPE3 = "type3"  # factual risk


@dataclass
class Observation:
    statement: str
    observation_type: ObservationType
    non_obviousness_score: float
    specificity_score: float
    source_refs: list[str] = field(default_factory=list)
    evergreen: bool = True
    use_count: int = 0
    last_used_date: Optional[str] = None
    used_in: list[str] = field(default_factory=list)
    id: Optional[str] = None


@dataclass
class TopicCandidate:
    observation_id: str
    observation_statement: str
    observation_type: ObservationType
    title: str
    angle: str
    hook: str
    content_goal: ContentGoal
    platform_fit: list[str]
    evergreen: bool
    relevance_score: float = 0.0
    diversity_adjustment: float = 0.0
    final_score: float = 0.0
    source: str = "intelligence"  # "manual" or "intelligence"
    manual_topic_id: Optional[str] = None


@dataclass
class ContentBrief:
    title: str
    angle: str
    hook: str
    content_goal: ContentGoal
    observation_statement: str
    observation_type: ObservationType
    platforms: list[str]
    tone_notes: str
    source_signals: list[str]
    wix_slug: str
    wix_category_id: str
    wix_tags: list[str]
    observation_id: Optional[str] = None
    manual_topic_id: Optional[str] = None


@dataclass
class QCResult:
    passed: bool
    status: str  # green, yellow, orange
    failure_type: Optional[QCFailureType] = None
    failed_check: Optional[str] = None
    reason: Optional[str] = None
    rewrite_guidance: Optional[str] = None
    voice_score: Optional[float] = None


@dataclass
class QCCheckResult:
    """Result of a single QC check (voice, factuality, duplication)."""
    check_name: str          # "duplication" | "factuality" | "voice_blog" | "voice_linkedin"
    status: str              # "green" | "yellow" | "orange" | "red"
    score: float             # 0.0–1.0 (1.0 = perfect)
    issues: list[str]        # specific problems found
    guidance: str            # feedback text for rewriter
    checked_at: str          # ISO timestamp
    risk_level: str = "low"  # for factuality: "low" | "medium" | "high"
    legal_risk: bool = False


@dataclass
class QCReport:
    """Full QC report for one content package."""
    overall_status: str           # "GREEN" | "YELLOW" | "ORANGE" | "RED"
    checks: list[QCCheckResult]
    rewrite_count: int            # how many rewrites happened
    final_status: str             # status after all rewrites
    quarantined: bool
    quarantine_reason: str
    quarantine_path: Optional[str]
    generated_at: str


@dataclass
class ChannelResult:
    channel: str
    status: ChannelStatus
    url: Optional[str] = None
    post_id: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0


@dataclass
class ContentMatrix:
    """Intermediate layer: one topic → structured matrix → all platform content."""
    topic_id:           str
    topic:              str
    core_idea:          str
    observation:        str
    mechanism:          str
    cost_of_ignoring:   str
    strategic_question: str
    hook_type:          str   # hidden_cost | contradiction | false_belief | future_consequence | comparison | pattern_interrupt
    primary_hook:       str
    supporting_points:  list[str]
    visual_anchor:      str
    sales_angle:        str
    soft_cta:           str
    linkedin_angle:     str
    instagram_angle:    str
    facebook_angle:     str
    threads_angle:      str
    telegram_angle:     str
    stories_flow:       str
    created_at:         str


@dataclass
class ContentPackage:
    """All generated content for one publication run."""
    brief: "ContentBrief"
    matrix: "ContentMatrix"
    blog_title: str
    blog_body: str                  # Markdown
    blog_meta_description: str
    blog_hook_sentence: str
    linkedin_text: str
    linkedin_hook_line: str
    instagram_caption: str
    instagram_hashtags: list[str]
    facebook_text: str
    threads_sequence: list[str]     # 5 posts
    telegram_text: str
    stories_sequence: list[dict]    # 4-story JSON sequence for IG/FB Stories
    image_prompt: str               # derived from matrix.visual_anchor
    generated_at: str               # ISO datetime


@dataclass
class RunResult:
    run_id: str
    topic_title: str
    observation_id: Optional[str]
    qc_result: Optional[QCResult]
    channels: list[ChannelResult] = field(default_factory=list)
    overall_status: RunStatus = RunStatus.GREEN
    errors: list[str] = field(default_factory=list)
    timestamp: Optional[str] = None
