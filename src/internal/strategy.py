"""
Strategy Layer — deterministic ContentBrief builder.

Takes a TopicCandidate and produces a fully-specified ContentBrief:
  - slug generated from title
  - tags assigned from observation_type + content_goal via strategy.yaml
  - Wix category_id and tag IDs from platforms.yaml
  - tone_notes pulled from brand.yaml

No LLM calls. All logic is deterministic.
"""

import re
import unicodedata
from src.models import ContentBrief, TopicCandidate
from src.utils.config_loader import load_brand, load_strategy, load_platforms
from src.utils.logger import get_logger

log = get_logger("strategy")


def generate_slug(title: str, max_length: int = 60) -> str:
    """
    Convert a title to a URL-safe slug.
    Example: "Why the busiest businesses look closed" → "why-the-busiest-businesses-look-closed"
    """
    # normalize unicode → ascii
    normalized = unicodedata.normalize("NFKD", title)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    # lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")
    # truncate at word boundary
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug


def assign_tag_names(observation_type: str, content_goal: str, strategy: dict) -> list[str]:
    """
    Return deduplicated list of tag names from strategy.yaml tag_assignment.
    Combines tags from observation_type row and content_goal row.
    """
    ta = strategy.get("tag_assignment", {})
    obs_tags  = ta.get("observation_type", {}).get(observation_type, [])
    goal_tags = ta.get("content_goal", {}).get(content_goal, [])
    seen = set()
    result = []
    for tag in obs_tags + goal_tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def assign_wix_tag_ids(tag_names: list[str], platforms: dict) -> list[str]:
    """Map tag names to Wix tag IDs from platforms.yaml."""
    wix_tags = platforms.get("wix", {}).get("tags", {})
    ids = []
    for name in tag_names:
        tag_id = wix_tags.get(name)
        if tag_id:
            ids.append(tag_id)
        else:
            log.warning("No Wix tag ID found for tag name '%s'", name)
    return ids


def build_content_brief(topic: TopicCandidate) -> ContentBrief:
    """
    Build a fully-specified ContentBrief from a TopicCandidate.
    This is the only entry point into the content generation pipeline.
    """
    brand    = load_brand()
    strategy = load_strategy()
    platforms = load_platforms()

    # slug
    max_slug_len = strategy.get("slug", {}).get("max_length", 60)
    slug = generate_slug(topic.title, max_length=max_slug_len)
    log.debug("Generated slug: %s", slug)

    # tags
    obs_type_value  = topic.observation_type.value
    goal_value      = topic.content_goal.value
    tag_names       = assign_tag_names(obs_type_value, goal_value, strategy)
    wix_tag_ids     = assign_wix_tag_ids(tag_names, platforms)
    log.debug("Tags: %s → IDs: %s", tag_names, wix_tag_ids)

    # Wix metadata
    wix_category_id = platforms.get("wix", {}).get("category_id", "")

    # tone notes from brand voice
    voice = brand.get("voice", {})
    tone_list  = voice.get("tone", [])
    avoid_list = voice.get("avoid", [])
    tone_notes = (
        "Tone: " + ", ".join(tone_list) + ". "
        + "Avoid: " + ", ".join(avoid_list) + "."
        if tone_list else ""
    )

    brief = ContentBrief(
        title=topic.title,
        angle=topic.angle,
        hook=topic.hook,
        content_goal=topic.content_goal,
        observation_statement=topic.observation_statement,
        observation_type=topic.observation_type,
        platforms=topic.platform_fit,
        tone_notes=tone_notes,
        source_signals=[],
        wix_slug=slug,
        wix_category_id=wix_category_id,
        wix_tags=wix_tag_ids,
        observation_id=topic.observation_id,
        manual_topic_id=topic.manual_topic_id,
    )

    log.info(
        "ContentBrief built: title=%r slug=%s goal=%s tags=%s",
        brief.title, brief.wix_slug, brief.content_goal.value, tag_names,
    )
    return brief
