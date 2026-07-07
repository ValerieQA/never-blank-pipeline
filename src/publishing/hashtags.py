"""
Publisher-layer hashtag generation - a narrow, dedicated LLM call scoped to
producing hashtags only. Kept out of src/editorial/: the Editorial Engine's job
is the article's thinking, not platform dressing (EDITORIAL_ENGINE_V2.md defines
no hashtag concept for any format).
"""

import json

from src.utils.llm_client import chat, model_social
from src.utils.logger import get_logger

log = get_logger("publishing.hashtags")

# Per-platform hashtag matrix. (0, 0) means "no hashtags on this platform" -
# blog and telegram are intentionally absent (not "social post" formats per
# the platform formatting matrix).
_COUNT_RANGE = {
    "linkedin":  (3, 6),
    "facebook":  (3, 6),
    "instagram": (3, 6),
    "threads":   (0, 2),
}

_SYSTEM_PROMPT = """You generate hashtags for one social media post. You do not
write or alter post content - only hashtags.

Rules:
- Include the company name (if given) as its own hashtag, one hashtag for the
  industry, and 1-2 hashtags specific to the actual topic of this signal - not
  generic filler like #Business, #News, or #Innovation.
- No repeated concepts, no spam stacking.
- Each hashtag: a single word or CamelCase phrase, starts with #, no spaces or
  punctuation besides the #.

Return ONLY valid JSON: {"hashtags": ["#Example1", "#Example2"]}"""


def generate_hashtags(signal: dict, platform: str) -> list[str]:
    """
    Generate hashtags for `platform` from signal context. Returns [] if the
    platform takes no hashtags, or on any generation/validation failure -
    hashtags are a nice-to-have, never worth failing or degrading a publish
    over.
    """
    lo, hi = _COUNT_RANGE.get(platform, (0, 0))
    if hi == 0:
        return []

    company  = signal.get("REAL_COMPANY_EXAMPLE") or ""
    industry = signal.get("INDUSTRY", "")
    headline = signal.get("HEADLINE", "")
    lesson   = signal.get("BUSINESS_LESSON", "")

    user = f"""COMPANY: {company}
INDUSTRY: {industry}
HEADLINE: {headline}
BUSINESS_LESSON: {lesson}
PLATFORM: {platform}

Produce between {lo} and {hi} hashtags for this post."""

    try:
        raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_social())
        data = json.loads(raw)
        tags = data.get("hashtags", [])
        if not isinstance(tags, list):
            return []

        clean = []
        seen = set()
        for tag in tags:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if not tag.startswith("#") or " " in tag or len(tag) < 2:
                continue
            if tag.lower() in seen:
                continue
            seen.add(tag.lower())
            clean.append(tag)
            if len(clean) >= hi:
                break
        return clean
    except Exception as exc:
        log.warning(
            "Hashtag generation failed for %s/%s: %s",
            signal.get("SIGNAL_ID", "unknown"), platform, exc,
        )
        return []
