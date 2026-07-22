"""
Content Generator — Phase 3 + Content Matrix layer.

Pipeline:
  ContentBrief → ContentMatrix → ContentPackage

No platform content is generated without a ContentMatrix.
All platform prompts receive matrix fields as primary input.

Requires NB_OPENAI_API_KEY. Raises EnvironmentError if missing.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from src.models import ContentBrief, ContentMatrix, ContentPackage
from src.utils.config_loader import load_prompt
from src.utils.llm_client import chat_json
from src.utils.logger import get_logger

log = get_logger("generator")

WIX_BASE_URL = "https://www.neverblank.io/blog"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_api_key() -> None:
    if not os.environ.get("NB_OPENAI_API_KEY", "").strip():
        raise EnvironmentError(
            "\n"
            "  Phase 3 requires NB_OPENAI_API_KEY to be set.\n"
            "  Add it to your .env file:\n"
            "    NB_OPENAI_API_KEY=sk-...\n"
        )


def _fill(template: str, context: dict[str, Any]) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        val = context.get(key)
        if val is None:
            return match.group(0)
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)
    return re.sub(r"\{(\w+)\}", replacer, template)


def _build_context(brief: ContentBrief, matrix: ContentMatrix, blog_body: str = "") -> dict[str, Any]:
    """Build template variable context from both ContentBrief and ContentMatrix."""
    wix_url = f"{WIX_BASE_URL}/{brief.wix_slug}"
    return {
        # Brief fields
        "title":                 brief.title,
        "angle":                 brief.angle,
        "hook":                  brief.hook,
        "content_goal":          brief.content_goal.value,
        "observation_statement": brief.observation_statement,
        "observation_type":      brief.observation_type.value,
        "tone_notes":            brief.tone_notes,
        "wix_slug":              brief.wix_slug,
        "wix_url":               wix_url,
        "blog_body":             blog_body,
        "observation_id":        brief.observation_id or "",
        "statement":             brief.observation_statement,
        # Matrix fields — primary inputs for all platform prompts
        "cta_mode":              getattr(matrix, "cta_mode", "none"),
        "core_idea":             matrix.core_idea,
        "observation":           matrix.observation,
        "mechanism":             matrix.mechanism,
        "cost_of_ignoring":      matrix.cost_of_ignoring,
        "strategic_question":    matrix.strategic_question,
        "hook_type":             matrix.hook_type,
        "primary_hook":          matrix.primary_hook,
        "supporting_points":     matrix.supporting_points,
        "visual_anchor":         matrix.visual_anchor,
        "sales_angle":           matrix.sales_angle,
        "soft_cta":              matrix.soft_cta,
        "linkedin_angle":        matrix.linkedin_angle,
        "instagram_angle":       matrix.instagram_angle,
        "facebook_angle":        matrix.facebook_angle,
        "threads_angle":         matrix.threads_angle,
        "telegram_angle":        matrix.telegram_angle,
        "stories_flow":          matrix.stories_flow,
        # Compatibility fields for old prompt patterns
        "intelligence_items_json":              "[]",
        "existing_observation_statements_json": "[]",
        "portfolio_context_json":               "{}",
        "target_platforms_json":                json.dumps(brief.platforms),
    }


def _call(prompt_name: str, context: dict[str, Any]) -> dict:
    prompt = load_prompt(prompt_name)
    system = prompt["system"]
    user   = _fill(prompt["user"], context)
    log.info("Calling OpenAI for: %s", prompt_name)
    return chat_json(system, user)


# ── Image prompt (derived from matrix visual_anchor) ──────────────────────────

def _build_image_prompt(matrix: ContentMatrix) -> str:
    """
    Build image prompt from matrix.visual_anchor.
    The image pipeline uses visual_system.yaml for full family selection;
    this prompt is the fallback human-readable description.
    """
    return (
        f"Dark editorial photograph visualizing: '{matrix.visual_anchor}'. "
        f"Core idea: {matrix.core_idea}. "
        f"Atmosphere: calm, intelligent, dark background, high contrast, no text."
    )


# ── Platform generators ────────────────────────────────────────────────────────

def generate_blog_post(brief: ContentBrief, matrix: ContentMatrix) -> dict:
    ctx = _build_context(brief, matrix)
    result = _call("blog_post", ctx)
    for key in ["title", "body", "meta_description", "hook_sentence"]:
        result.setdefault(key, "")
    return result


def generate_linkedin(brief: ContentBrief, matrix: ContentMatrix, blog_body: str) -> dict:
    ctx = _build_context(brief, matrix, blog_body=blog_body)
    result = _call("linkedin_post", ctx)
    result.setdefault("text", "")
    result.setdefault("hook_line", "")
    return result


def generate_instagram(brief: ContentBrief, matrix: ContentMatrix) -> dict:
    ctx = _build_context(brief, matrix)
    result = _call("instagram_caption", ctx)
    result.setdefault("caption", "")
    result.setdefault("hashtags", [])
    result.setdefault("hook_line", "")
    return result


def generate_facebook(brief: ContentBrief, matrix: ContentMatrix, blog_body: str) -> dict:
    ctx = _build_context(brief, matrix, blog_body=blog_body)
    result = _call("facebook_post", ctx)
    result.setdefault("text", "")
    return result


def generate_threads(brief: ContentBrief, matrix: ContentMatrix, blog_body: str) -> dict:
    ctx = _build_context(brief, matrix, blog_body=blog_body)
    result = _call("threads_post", ctx)
    if "sequence" not in result or not isinstance(result["sequence"], list):
        log.warning("threads_post missing 'sequence' list — using primary_hook")
        result["sequence"] = [matrix.primary_hook]
    return result


def generate_telegram(brief: ContentBrief, matrix: ContentMatrix) -> dict:
    """Generate a Telegram signal post (3 lines max) from telegram_post.yaml."""
    try:
        ctx = _build_context(brief, matrix)
        result = _call("telegram_post", ctx)
        if not result.get("text"):
            log.error("generate_telegram: prompt returned empty text — channel FAILED")
            return {"text": None}
        return result
    except Exception as exc:
        log.error("generate_telegram: failed — %s", exc)
        return {"text": None}


def generate_stories(brief: ContentBrief, matrix: ContentMatrix) -> list[dict] | None:
    """Generate a 4-frame Stories sequence from stories_post.yaml."""
    try:
        ctx = _build_context(brief, matrix)
        result = _call("stories_post", ctx)
        frames = result.get("frames")
        if not frames or not isinstance(frames, list) or len(frames) == 0:
            log.error("generate_stories: prompt returned no frames — channel FAILED")
            return None
        return frames
    except Exception as exc:
        log.error("generate_stories: failed — %s", exc)
        return None


# ── Full package ───────────────────────────────────────────────────────────────

def generate_content_package(brief: ContentBrief, matrix: ContentMatrix) -> ContentPackage:
    """
    Generate all platform content from a ContentBrief + ContentMatrix.

    Pipeline:
      1. Blog post (uses matrix as backbone)
      2. LinkedIn (uses matrix linkedin_angle + blog body)
      3. Instagram (uses matrix instagram_angle)
      4. Facebook (uses matrix facebook_angle + blog body)
      5. Threads (uses matrix threads_angle + blog body)
      6. Telegram (uses matrix telegram_angle)
      7. Stories (uses matrix stories_flow)
      8. Image prompt (derived from matrix visual_anchor)

    7 LLM calls. Matrix was generated separately (1 additional call before this).
    Requires NB_OPENAI_API_KEY.
    """
    _require_api_key()
    log.info("Starting content generation for: %r", brief.title)

    blog = generate_blog_post(brief, matrix)
    body = blog.get("body", "")

    li   = generate_linkedin(brief, matrix, blog_body=body)
    ig   = generate_instagram(brief, matrix)
    fb   = generate_facebook(brief, matrix, blog_body=body)
    thr  = generate_threads(brief, matrix, blog_body=body)
    tg   = generate_telegram(brief, matrix)
    st   = generate_stories(brief, matrix)

    img_prompt = _build_image_prompt(matrix)

    log.info(
        "Content generation complete: blog=%d linkedin=%d ig=%d fb=%d threads=%d tg=%d stories=%d",
        len(body), len(li.get("text", "")), len(ig.get("caption", "")),
        len(fb.get("text", "")), len(thr.get("sequence", [])),
        len(tg.get("text") or ""), len(st) if st is not None else 0,
    )

    return ContentPackage(
        brief              = brief,
        matrix             = matrix,
        blog_title         = blog.get("title", brief.title),
        blog_body          = body,
        blog_meta_description = blog.get("meta_description", ""),
        blog_hook_sentence = blog.get("hook_sentence", ""),
        linkedin_text      = li.get("text", ""),
        linkedin_hook_line = li.get("hook_line", ""),
        instagram_caption  = ig.get("caption", ""),
        instagram_hashtags = ig.get("hashtags", []),
        facebook_text      = fb.get("text", ""),
        threads_sequence   = thr.get("sequence", []),
        telegram_text      = tg.get("text", None),   # None = SKIPPED
        stories_sequence   = st,                        # None = SKIPPED
        image_prompt       = img_prompt,
        generated_at       = datetime.now(timezone.utc).isoformat(),
    )
