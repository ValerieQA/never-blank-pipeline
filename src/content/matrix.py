"""
Content Matrix generator — intermediate layer between topic and platform content.

Topic → ContentBrief → ContentMatrix → all platform content.

No platform content is generated without a ContentMatrix.
One LLM call produces the full matrix.
"""

import json
from datetime import datetime, timezone

from src.models import ContentBrief, ContentMatrix
from src.utils.config_loader import load_prompt
from src.utils.llm_client import chat_json
from src.utils.logger import get_logger

log = get_logger("matrix")

REQUIRED_FIELDS = [
    "core_idea", "observation", "mechanism", "cost_of_ignoring",
    "strategic_question", "hook_type", "primary_hook", "supporting_points",
    "visual_anchor", "sales_angle", "soft_cta",
    "linkedin_angle", "instagram_angle", "facebook_angle",
    "threads_angle", "telegram_angle", "stories_flow",
]

VALID_HOOK_TYPES = {
    "hidden_cost", "contradiction", "false_belief",
    "future_consequence", "comparison", "pattern_interrupt",
}


def _validate(raw: dict, brief: ContentBrief) -> dict:
    """Validate and sanitize the raw LLM response. Returns cleaned dict."""
    for field in REQUIRED_FIELDS:
        if field not in raw or not raw[field]:
            log.warning("ContentMatrix missing field '%s' — using fallback", field)
            raw.setdefault(field, _field_fallback(field, brief))

    # Ensure supporting_points is a list of strings
    sp = raw.get("supporting_points", [])
    if not isinstance(sp, list):
        raw["supporting_points"] = [str(sp)]
    raw["supporting_points"] = [str(p) for p in raw["supporting_points"]][:5]
    if not raw["supporting_points"]:
        raw["supporting_points"] = [brief.observation_statement]

    # Validate hook_type
    if raw.get("hook_type") not in VALID_HOOK_TYPES:
        raw["hook_type"] = "pattern_interrupt"

    return raw


def _field_fallback(field: str, brief: ContentBrief) -> str:
    """Minimal fallback value when LLM omits a field."""
    fallbacks = {
        "core_idea":          brief.angle or brief.title,
        "observation":        brief.observation_statement,
        "mechanism":          "The pattern emerges when the feedback loop is not visible.",
        "cost_of_ignoring":   "Opportunities that require visibility are missed silently.",
        "strategic_question": "Are you watching the pattern or just the events?",
        "hook_type":          "pattern_interrupt",
        "primary_hook":       brief.hook or brief.observation_statement[:120],
        "supporting_points":  brief.observation_statement,
        "visual_anchor":      "signal through pattern",
        "sales_angle":        "This is the kind of signal Never Blank is built to keep visible.",
        "soft_cta":           "The system you are watching here is the product.",
        "linkedin_angle":     "Business implication for founders and operators.",
        "instagram_angle":    "Visual + minimal text expression of the core idea.",
        "facebook_angle":     "Accessible, human reflection on the pattern.",
        "threads_angle":      "Provocation → mechanism → cost → reframe → implication.",
        "telegram_angle":     "One observation, one implication, one question.",
        "stories_flow":       "Hook → poll on the tension → insight → soft CTA.",
    }
    return fallbacks.get(field, "")


def generate_content_matrix(brief: ContentBrief) -> ContentMatrix:
    """
    Generate the Content Matrix from a ContentBrief.
    One LLM call. Returns a ContentMatrix dataclass.
    This must be called before any platform content is generated.
    """
    topic_id = brief.manual_topic_id or brief.wix_slug

    prompt = load_prompt("content_matrix")
    context = {
        "title":                brief.title,
        "angle":                brief.angle,
        "hook":                 brief.hook,
        "observation_statement": brief.observation_statement,
        "observation_type":     brief.observation_type.value,
        "content_goal":         brief.content_goal.value,
        "topic_id":             topic_id,
    }

    import re
    def fill(template: str) -> str:
        def replacer(m):
            v = context.get(m.group(1))
            if v is None:
                return m.group(0)
            return json.dumps(v) if isinstance(v, (list, dict)) else str(v)
        return re.sub(r"\{(\w+)\}", replacer, template)

    system = fill(prompt["system"])
    user   = fill(prompt["user"])

    log.info("Generating ContentMatrix for: %r", brief.title)
    raw = chat_json(system, user)
    raw = _validate(raw, brief)

    log.info("ContentMatrix generated: hook_type=%s visual_anchor=%r",
             raw["hook_type"], raw["visual_anchor"])

    return ContentMatrix(
        topic_id           = topic_id,
        topic              = brief.title,
        core_idea          = raw["core_idea"],
        observation        = raw["observation"],
        mechanism          = raw["mechanism"],
        cost_of_ignoring   = raw["cost_of_ignoring"],
        strategic_question = raw["strategic_question"],
        hook_type          = raw["hook_type"],
        primary_hook       = raw["primary_hook"],
        supporting_points  = raw["supporting_points"],
        visual_anchor      = raw["visual_anchor"],
        sales_angle        = raw["sales_angle"],
        soft_cta           = raw["soft_cta"],
        linkedin_angle     = raw["linkedin_angle"],
        instagram_angle    = raw["instagram_angle"],
        facebook_angle     = raw["facebook_angle"],
        threads_angle      = raw["threads_angle"],
        telegram_angle     = raw["telegram_angle"],
        stories_flow       = raw["stories_flow"],
        created_at         = datetime.now(timezone.utc).isoformat(),
    )


def matrix_to_dict(matrix: ContentMatrix) -> dict:
    """Serialize ContentMatrix to a plain dict for JSON output."""
    return {
        "topic_id":           matrix.topic_id,
        "topic":              matrix.topic,
        "core_idea":          matrix.core_idea,
        "observation":        matrix.observation,
        "mechanism":          matrix.mechanism,
        "cost_of_ignoring":   matrix.cost_of_ignoring,
        "strategic_question": matrix.strategic_question,
        "hook_type":          matrix.hook_type,
        "primary_hook":       matrix.primary_hook,
        "supporting_points":  matrix.supporting_points,
        "visual_anchor":      matrix.visual_anchor,
        "sales_angle":        matrix.sales_angle,
        "soft_cta":           matrix.soft_cta,
        "linkedin_angle":     matrix.linkedin_angle,
        "instagram_angle":    matrix.instagram_angle,
        "facebook_angle":     matrix.facebook_angle,
        "threads_angle":      matrix.threads_angle,
        "telegram_angle":     matrix.telegram_angle,
        "stories_flow":       matrix.stories_flow,
        "created_at":         matrix.created_at,
    }
