"""Content Generator — ContentBrief → ContentMatrix → ContentPackage.

All platform outputs are generated from the matrix, validated against their platform
contract, and rejected rather than silently published when malformed.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from src.content.output_guard import repeated_cross_platform_phrases, validate_platform_output
from src.models import ContentBrief, ContentMatrix, ContentPackage
from src.utils.config_loader import load_prompt
from src.utils.llm_client import chat_json
from src.utils.logger import get_logger

log = get_logger("generator")
WIX_BASE_URL = "https://www.neverblank.io/blog"


def _require_api_key() -> None:
    if not os.environ.get("NB_OPENAI_API_KEY", "").strip():
        raise EnvironmentError(
            "\n  Phase 3 requires NB_OPENAI_API_KEY to be set.\n"
            "  Add it to your .env file:\n    NB_OPENAI_API_KEY=sk-...\n"
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
    wix_url = f"{WIX_BASE_URL}/{brief.wix_slug}"
    return {
        "title": brief.title,
        "angle": brief.angle,
        "hook": brief.hook,
        "content_goal": brief.content_goal.value,
        "observation_statement": brief.observation_statement,
        "observation_type": brief.observation_type.value,
        "tone_notes": brief.tone_notes,
        "wix_slug": brief.wix_slug,
        "wix_url": wix_url,
        "blog_body": blog_body,
        "observation_id": brief.observation_id or "",
        "statement": brief.observation_statement,
        "cta_mode": getattr(matrix, "cta_mode", "none"),
        "core_idea": matrix.core_idea,
        "observation": matrix.observation,
        "mechanism": matrix.mechanism,
        "cost_of_ignoring": matrix.cost_of_ignoring,
        "strategic_question": matrix.strategic_question,
        "hook_type": matrix.hook_type,
        "primary_hook": matrix.primary_hook,
        "supporting_points": matrix.supporting_points,
        "visual_anchor": matrix.visual_anchor,
        "sales_angle": matrix.sales_angle,
        "soft_cta": matrix.soft_cta,
        "linkedin_angle": matrix.linkedin_angle,
        "instagram_angle": matrix.instagram_angle,
        "facebook_angle": matrix.facebook_angle,
        "threads_angle": matrix.threads_angle,
        "telegram_angle": matrix.telegram_angle,
        "stories_flow": matrix.stories_flow,
        "intelligence_items_json": "[]",
        "existing_observation_statements_json": "[]",
        "portfolio_context_json": "{}",
        "target_platforms_json": json.dumps(brief.platforms),
    }


def _call(prompt_name: str, context: dict[str, Any]) -> dict:
    prompt = load_prompt(prompt_name)
    user = _fill(prompt["user"], context)
    correction = str(context.get("output_correction", "")).strip()
    if correction:
        user += f"\n\nMANDATORY REGENERATION CORRECTION:\n{correction}"
    log.info("Calling OpenAI for: %s", prompt_name)
    return chat_json(prompt["system"], user)


def _call_validated(
    prompt_name: str,
    context: dict[str, Any],
    platform: str,
    text_getter: Callable[[dict], str],
) -> dict:
    result = _call(prompt_name, context)
    try:
        validate_platform_output(platform, text_getter(result))
        return result
    except ValueError as first_error:
        log.warning("%s output failed contract (%s); regenerating once", platform, first_error)
        retry_context = dict(context)
        retry_context["output_correction"] = (
            f"Previous output failed validation: {first_error}. Regenerate from the matrix, "
            "without reusing prior wording. Do not use first-person detective narration."
        )
        result = _call(prompt_name, retry_context)
        validate_platform_output(platform, text_getter(result))
        return result


def _build_image_prompt(matrix: ContentMatrix) -> str:
    return (
        f"Dark editorial photograph visualizing: '{matrix.visual_anchor}'. "
        f"Core idea: {matrix.core_idea}. "
        "Atmosphere: calm, intelligent, dark background, high contrast, no text."
    )


def generate_blog_post(brief: ContentBrief, matrix: ContentMatrix) -> dict:
    ctx = _build_context(brief, matrix)
    result = _call_validated("blog_post", ctx, "blog", lambda x: x.get("body", ""))
    for key in ("title", "body", "meta_description", "hook_sentence"):
        result.setdefault(key, "")
    return result


def generate_linkedin(brief: ContentBrief, matrix: ContentMatrix, blog_body: str) -> dict:
    ctx = _build_context(brief, matrix, blog_body=blog_body)
    result = _call_validated("linkedin_post", ctx, "linkedin", lambda x: x.get("text", ""))
    result.setdefault("text", "")
    result.setdefault("hook_line", "")
    return result


def generate_instagram(brief: ContentBrief, matrix: ContentMatrix) -> dict:
    ctx = _build_context(brief, matrix)
    result = _call_validated("instagram_caption", ctx, "instagram", lambda x: x.get("caption", ""))
    result.setdefault("caption", "")
    result.setdefault("hashtags", [])
    result.setdefault("hook_line", "")
    return result


def generate_facebook(brief: ContentBrief, matrix: ContentMatrix, blog_body: str) -> dict:
    ctx = _build_context(brief, matrix, blog_body=blog_body)
    result = _call_validated("facebook_post", ctx, "facebook", lambda x: x.get("text", ""))
    result.setdefault("text", "")
    return result


def generate_threads(brief: ContentBrief, matrix: ContentMatrix, blog_body: str) -> dict:
    ctx = _build_context(brief, matrix, blog_body=blog_body)
    result = _call("threads_post", ctx)
    sequence = result.get("sequence")
    if not isinstance(sequence, list) or not sequence:
        raise ValueError("Threads output must contain a non-empty sequence")
    if not 3 <= len(sequence) <= 5:
        raise ValueError(f"Threads output must contain 3–5 posts, got {len(sequence)}")
    validate_platform_output("threads", "\n".join(str(item) for item in sequence))
    return result


def generate_telegram(brief: ContentBrief, matrix: ContentMatrix) -> dict:
    ctx = _build_context(brief, matrix)
    result = _call_validated("telegram_post", ctx, "telegram", lambda x: x.get("text", ""))
    return {"text": result.get("text", "").strip()}


def generate_stories(brief: ContentBrief, matrix: ContentMatrix) -> list[dict]:
    ctx = _build_context(brief, matrix)
    result = _call("stories_post", ctx)
    frames = result.get("frames")
    if not isinstance(frames, list) or len(frames) != 4:
        raise ValueError("Stories output must contain exactly four frames")
    expected = ["recognition", "mechanism", "reframe", "cta"]
    actual = [str(frame.get("type", "")) for frame in frames]
    if actual != expected:
        raise ValueError(f"Stories frame order must be {expected}, got {actual}")
    for frame in frames:
        if not str(frame.get("text", "")).strip():
            raise ValueError("Stories frame text cannot be empty")
    return frames


def _validate_cross_platform_outputs(
    blog: str,
    linkedin: str,
    instagram: str,
    facebook: str,
    threads: list[str],
    telegram: str,
) -> None:
    # #221 product decision: Wix↔LinkedIn sentence overlap is ALLOWED. The post
    # is a shorter channel version of the same article, so a shared hook, shared
    # sentences and a shared Never Blank Echo are not defects. The blog and
    # linkedin surfaces are therefore compared against the other channels but
    # never against each other.
    #
    # Every other pair keeps the original rule: a sentence copied verbatim into,
    # say, Instagram and Telegram still means the platform layer collapsed into
    # copy-paste, and that is a real failure this check exists to catch.
    repeated = [
        item for item in repeated_cross_platform_phrases(
            {
                "blog": blog,
                "linkedin": linkedin,
                "instagram": instagram,
                "facebook": facebook,
                "threads": " ".join(threads),
                "telegram": telegram,
            }
        )
        if set(item["platforms"]) != {"blog", "linkedin"}
    ]
    if repeated:
        preview = "; ".join(
            f"{item['platforms']}: {item['phrase'][:80]}" for item in repeated[:3]
        )
        raise ValueError(
            "Cross-platform copy detected. Each platform must receive native wording. " + preview
        )


def generate_content_package(brief: ContentBrief, matrix: ContentMatrix) -> ContentPackage:
    """Generate every platform body and fail closed when any active output is malformed."""
    _require_api_key()
    log.info("Starting content generation for: %r", brief.title)

    blog = generate_blog_post(brief, matrix)
    body = blog.get("body", "")
    li = generate_linkedin(brief, matrix, blog_body=body)
    ig = generate_instagram(brief, matrix)
    fb = generate_facebook(brief, matrix, blog_body=body)
    thr = generate_threads(brief, matrix, blog_body=body)
    tg = generate_telegram(brief, matrix)
    st = generate_stories(brief, matrix)

    _validate_cross_platform_outputs(
        body,
        li.get("text", ""),
        ig.get("caption", ""),
        fb.get("text", ""),
        thr.get("sequence", []),
        tg.get("text", ""),
    )

    log.info(
        "Content generation complete: blog=%d linkedin=%d ig=%d fb=%d threads=%d tg=%d stories=%d",
        len(body), len(li.get("text", "")), len(ig.get("caption", "")),
        len(fb.get("text", "")), len(thr.get("sequence", [])),
        len(tg.get("text", "")), len(st),
    )

    return ContentPackage(
        brief=brief,
        matrix=matrix,
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
        stories_sequence=st,
        image_prompt=_build_image_prompt(matrix),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
