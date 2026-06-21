"""
Rewrite module — applies QC feedback to fix failing content.

Takes a ContentPackage, a QCReport, and a ContentBrief.
Identifies which checks failed, rewrites the affected content,
and returns a new ContentPackage with fixes applied.

Strategy:
- Voice failure on blog → rewrite blog body → regenerate all social posts
- Voice failure on social only → rewrite that specific social post
- Factuality failure → rewrite blog body → regenerate all social posts
- Rewrites use low temperature (NB_OPENAI_QC_TEMPERATURE) for consistency

Requires NB_OPENAI_API_KEY. Not called in mock mode.
"""

import json
import re
from src.models import ContentBrief, ContentPackage, QCCheckResult
from src.utils.config_loader import load_brand, load_prompt
from src.utils.llm_client import chat_qc_json
from src.utils.logger import get_logger
from src.content.generator import (
    generate_linkedin, generate_instagram, generate_facebook,
    generate_threads, generate_telegram,
)

log = get_logger("qc.rewrite")


def _fill(template: str, context: dict) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        val = context.get(key)
        if val is None:
            return match.group(0)
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)
    return re.sub(r"\{(\w+)\}", replacer, template)


def _rewrite_text(
    content: str,
    content_type: str,
    failed_check: str,
    failure_reason: str,
    rewrite_guidance: str,
    brief: ContentBrief,
    attempt: int,
) -> str:
    """
    Call rewrite_with_feedback prompt and return the rewritten text.
    Returns original content on failure (never blocks pipeline).
    """
    brand  = load_brand()
    voice  = brand.get("voice", {})
    prompt = load_prompt("rewrite_with_feedback")

    context = {
        "content_type":          content_type,
        "failed_check":          failed_check,
        "observation_statement": brief.observation_statement,
        "original_content":      content,
        "failure_reason":        failure_reason,
        "rewrite_guidance":      rewrite_guidance,
        "tone_list":             ", ".join(voice.get("tone", [])),
        "avoid_list":            ", ".join(voice.get("avoid", [])),
        "attempt_number":        str(attempt),
    }
    system = _fill(prompt["system"], context)
    user   = _fill(prompt["user"], context)

    try:
        result = chat_qc_json(system, user)
        rewritten = result.get("content", "").strip()
        if not rewritten:
            log.warning("Rewrite returned empty content — keeping original")
            return content
        log.info(
            "Rewrite complete: %s attempt=%d original=%d rewritten=%d chars",
            content_type, attempt, len(content), len(rewritten),
        )
        return rewritten
    except Exception as exc:
        log.error("Rewrite call failed: %s — keeping original content", exc)
        return content


def apply_feedback(
    pkg: ContentPackage,
    brief: ContentBrief,
    failing_checks: list[QCCheckResult],
    attempt: int,
) -> ContentPackage:
    """
    Apply QC feedback to a ContentPackage and return an updated package.

    For blog failures: rewrite blog body, then regenerate all social posts.
    For social-only failures: rewrite only the failing social posts.
    """
    blog_body      = pkg.blog_body
    linkedin_text  = pkg.linkedin_text
    instagram_cap  = pkg.instagram_caption
    instagram_hash = pkg.instagram_hashtags
    facebook_text  = pkg.facebook_text
    threads_seq    = pkg.threads_sequence
    telegram_text  = pkg.telegram_text

    blog_rewritten = False

    for check in failing_checks:
        name     = check.check_name
        guidance = check.guidance
        reason   = "; ".join(check.issues) if check.issues else "QC failure"

        if name in ("voice_blog", "factuality"):
            log.info("Rewriting blog body for check=%s attempt=%d", name, attempt)
            blog_body = _rewrite_text(
                content=pkg.blog_body,
                content_type="blog_body",
                failed_check=name.replace("voice_", "voice"),
                failure_reason=reason,
                rewrite_guidance=guidance,
                brief=brief,
                attempt=attempt,
            )
            blog_rewritten = True

        elif name == "voice_linkedin":
            linkedin_text = _rewrite_text(
                content=pkg.linkedin_text,
                content_type="linkedin",
                failed_check="voice",
                failure_reason=reason,
                rewrite_guidance=guidance,
                brief=brief,
                attempt=attempt,
            )

        elif name == "voice_instagram":
            instagram_cap = _rewrite_text(
                content=pkg.instagram_caption,
                content_type="instagram",
                failed_check="voice",
                failure_reason=reason,
                rewrite_guidance=guidance,
                brief=brief,
                attempt=attempt,
            )

        elif name == "voice_facebook":
            facebook_text = _rewrite_text(
                content=pkg.facebook_text,
                content_type="facebook",
                failed_check="voice",
                failure_reason=reason,
                rewrite_guidance=guidance,
                brief=brief,
                attempt=attempt,
            )

        elif name == "voice_threads":
            threads_raw = _rewrite_text(
                content="\n---\n".join(pkg.threads_sequence or []),
                content_type="threads",
                failed_check="voice",
                failure_reason=reason,
                rewrite_guidance=guidance,
                brief=brief,
                attempt=attempt,
            )
            # Rewrite returns the sequence joined by ---; split it back
            parts = [p.strip() for p in threads_raw.split("---") if p.strip()]
            if parts:
                threads_seq = parts

        elif name == "voice_telegram":
            telegram_text = _rewrite_text(
                content=pkg.telegram_text,
                content_type="telegram",
                failed_check="voice",
                failure_reason=reason,
                rewrite_guidance=guidance,
                brief=brief,
                attempt=attempt,
            )

    # If blog was rewritten, regenerate all social posts from new body
    if blog_rewritten:
        log.info("Blog rewritten — regenerating social posts from new body")
        matrix = pkg.matrix
        try:
            li_result  = generate_linkedin(brief, matrix, blog_body=blog_body)
            ig_result  = generate_instagram(brief, matrix)
            fb_result  = generate_facebook(brief, matrix, blog_body=blog_body)
            thr_result = generate_threads(brief, matrix, blog_body=blog_body)
            tg_result  = generate_telegram(brief, matrix)

            linkedin_text  = li_result.get("text", linkedin_text)
            instagram_cap  = ig_result.get("caption", instagram_cap)
            instagram_hash = ig_result.get("hashtags", instagram_hash)
            facebook_text  = fb_result.get("text", facebook_text)
            threads_seq    = thr_result.get("sequence", threads_seq)
            telegram_text  = tg_result.get("text", telegram_text)
        except Exception as exc:
            log.error("Social regeneration after rewrite failed: %s — keeping originals", exc)

    return ContentPackage(
        brief=pkg.brief,
        matrix=pkg.matrix,
        blog_title=pkg.blog_title,
        blog_body=blog_body,
        blog_meta_description=pkg.blog_meta_description,
        blog_hook_sentence=pkg.blog_hook_sentence,
        linkedin_text=linkedin_text,
        linkedin_hook_line=pkg.linkedin_hook_line,
        instagram_caption=instagram_cap,
        instagram_hashtags=instagram_hash,
        facebook_text=facebook_text,
        threads_sequence=threads_seq,
        telegram_text=telegram_text,
        stories_sequence=pkg.stories_sequence,
        image_prompt=pkg.image_prompt,
        generated_at=pkg.generated_at,
    )
