"""
Content Generator — Phase 3.

Takes a ContentBrief and generates a full ContentPackage:
  blog_post, linkedin, instagram, facebook, threads, telegram, image_prompt.

All text generation uses OpenAI Chat (NB_OPENAI_CHAT_MODEL, NB_OPENAI_TEMPERATURE).
Image prompt is built deterministically — no LLM call.

Requires NB_OPENAI_API_KEY. Raises EnvironmentError if missing.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from src.models import ContentBrief, ContentPackage
from src.utils.config_loader import load_prompt
from src.utils.llm_client import chat_json
from src.utils.logger import get_logger

log = get_logger("generator")

WIX_BASE_URL = "https://www.neverblank.io/blog"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_api_key() -> None:
    """Fail loudly if NB_OPENAI_API_KEY is absent — Phase 3 cannot run without it."""
    if not os.environ.get("NB_OPENAI_API_KEY", "").strip():
        raise EnvironmentError(
            "\n"
            "  Phase 3 requires NB_OPENAI_API_KEY to be set.\n"
            "  Add it to your .env file:\n"
            "    NB_OPENAI_API_KEY=sk-...\n"
            "  Then re-run: python scripts/generate.py\n"
        )


def _fill(template: str, context: dict[str, Any]) -> str:
    """
    Fill {variable} placeholders in a template string.
    Unknown placeholders are left as-is. Safe for YAML prompt templates.
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        val = context.get(key)
        if val is None:
            return match.group(0)  # leave unknown placeholders
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)
    return re.sub(r"\{(\w+)\}", replacer, template)


def _build_context(brief: ContentBrief, blog_body: str = "") -> dict[str, Any]:
    """Build the template variable context from a ContentBrief."""
    wix_url = f"{WIX_BASE_URL}/{brief.wix_slug}"
    return {
        "title":                brief.title,
        "angle":                brief.angle,
        "hook":                 brief.hook,
        "content_goal":         brief.content_goal.value,
        "observation_statement": brief.observation_statement,
        "observation_type":     brief.observation_type.value,
        "tone_notes":           brief.tone_notes,
        "wix_slug":             brief.wix_slug,
        "wix_url":              wix_url,
        "blog_body":            blog_body,
        # for Intelligence Engine prompts (Phase 7)
        "intelligence_items_json":              "[]",
        "existing_observation_statements_json": "[]",
        "portfolio_context_json":               "{}",
        "target_platforms_json":                json.dumps(brief.platforms),
        "observation_id":       brief.observation_id or "",
        "statement":            brief.observation_statement,
    }


def _call(prompt_name: str, context: dict[str, Any]) -> dict:
    """Load a prompt YAML, fill templates, call OpenAI, return parsed dict."""
    prompt = load_prompt(prompt_name)
    system = prompt["system"]
    user   = _fill(prompt["user"], context)
    log.info("Calling OpenAI for: %s", prompt_name)
    return chat_json(system, user)


# ── Image prompt (deterministic) ───────────────────────────────────────────────

def _build_image_prompt(brief: ContentBrief) -> str:
    """
    Build a text-to-image prompt from the ContentBrief without an LLM call.
    Goal: dark, minimal, typographic — consistent with Never Blank brand.
    """
    obs_type_labels = {
        "pattern":        "repeating pattern",
        "paradox":        "contradiction",
        "reversal":       "unexpected reversal",
        "gap":            "missing element",
        "behavior_delta": "behavioral shift",
        "signal_cluster": "signal convergence",
        "implication":    "downstream consequence",
    }
    obs_label = obs_type_labels.get(brief.observation_type.value, "observation")
    hook_short = brief.hook[:80] if brief.hook else brief.title[:80]

    return (
        f"Dark minimal editorial photograph. Black background. "
        f"A single visual metaphor for '{obs_label}'. "
        f"No text overlay. No people. Abstract geometry or still life. "
        f"High contrast. Matte finish. "
        f"Concept: {hook_short}"
    )


# ── Platform generators ────────────────────────────────────────────────────────

def generate_blog_post(brief: ContentBrief) -> dict:
    """Returns: {title, body, meta_description, hook_sentence}"""
    result = _call("blog_post", _build_context(brief))
    required = ["title", "body", "meta_description", "hook_sentence"]
    for key in required:
        if key not in result:
            log.warning("blog_post response missing key '%s' — using fallback", key)
            result.setdefault(key, "")
    return result


def generate_linkedin(brief: ContentBrief, blog_body: str) -> dict:
    """Returns: {text, hook_line}"""
    result = _call("linkedin_post", _build_context(brief, blog_body=blog_body))
    result.setdefault("text", "")
    result.setdefault("hook_line", "")
    return result


def generate_instagram(brief: ContentBrief) -> dict:
    """Returns: {caption, hashtags, hook_line}"""
    result = _call("instagram_caption", _build_context(brief))
    result.setdefault("caption", "")
    result.setdefault("hashtags", [])
    result.setdefault("hook_line", "")
    return result


def generate_facebook(brief: ContentBrief, blog_body: str) -> dict:
    """Returns: {text}"""
    result = _call("facebook_post", _build_context(brief, blog_body=blog_body))
    result.setdefault("text", "")
    return result


def generate_threads(brief: ContentBrief, blog_body: str) -> dict:
    """Returns: {sequence: list[str]}"""
    result = _call("threads_post", _build_context(brief, blog_body=blog_body))
    if "sequence" not in result or not isinstance(result["sequence"], list):
        log.warning("threads_post response missing 'sequence' list — using fallback")
        result["sequence"] = [brief.hook]
    return result


def generate_telegram(brief: ContentBrief) -> dict:
    """Returns: {text}"""
    result = _call("telegram_post", _build_context(brief))
    result.setdefault("text", "")
    return result


# ── Full package ───────────────────────────────────────────────────────────────

def generate_content_package(brief: ContentBrief) -> ContentPackage:
    """
    Generate all platform content for one ContentBrief.

    Calls OpenAI 6 times (one per platform). Image prompt is deterministic.
    Requires NB_OPENAI_API_KEY — raises EnvironmentError if absent.
    """
    _require_api_key()

    log.info("Starting content generation for: %r", brief.title)

    # 1. Blog post first — used as source for social adaptations
    blog   = generate_blog_post(brief)
    body   = blog.get("body", "")

    # 2. Social adaptations (use blog body as source material)
    li     = generate_linkedin(brief, blog_body=body)
    ig     = generate_instagram(brief)
    fb     = generate_facebook(brief, blog_body=body)
    thr    = generate_threads(brief, blog_body=body)
    tg     = generate_telegram(brief)

    # 3. Image prompt (deterministic)
    img_prompt = _build_image_prompt(brief)

    log.info("Content generation complete: blog=%d chars, linkedin=%d chars",
             len(body), len(li.get("text", "")))

    return ContentPackage(
        brief=brief,
        blog_title=blog.get("title", brief.title),
        blog_body=body,
        blog_meta_description=blog.get("meta_description", ""),
        blog_hook_sentence=blog.get("hook_sentence", ""),
        linkedin_text=li.get("text", ""),
        linkedin_hook_line=li.get("hook_line", ""),
        instagram_caption=ig.get("caption", ""),
        instagram_hashtags=ig.get("hashtags", []),
        facebook_text=fb.get("text", ""),
        threads_sequence=thr.get("sequence", []),
        telegram_text=tg.get("text", ""),
        image_prompt=img_prompt,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
