"""
Stage 11 — Live publishing.
For each selected signal + its content package, generate full platform content
and publish to all channels.  No approval gates.  mode='live' by default.

Safety: if NB_PUBLISH_MODE env var is 'dry_run', all publishers run in dry-run.
Default: live.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.logger import get_logger
from src.utils.llm_client import chat
from src.publishing.base import DraftPackage
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.wix import WixPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.telegram import TelegramPublisher

log = get_logger("research.publish_packages")

PACKAGES_DIR = Path("reports/content_packages")

_PUBLISHERS = [
    ("wix",       WixPublisher()),
    ("linkedin",  LinkedInPublisher()),
    ("facebook",  FacebookPublisher()),
    ("instagram", InstagramPublisher()),
    ("threads",   ThreadsPublisher()),
    ("telegram",  TelegramPublisher()),
]

_BLOG_SYSTEM = """You are writing for Never Blank, a content practice for founders.

Never Blank voice: sharp, observational, commercially aware. Not motivational, not academic.
Structure: Signal → Business tension → Real company response → Outcome/Lesson → Never Blank signature
Forbidden words: "in today's world", "let's dive in", "game-changer", "unlock", "leverage", "hustle"

Write a blog article in Markdown. Use ## subheadings. 600–900 words. No fluff.
End with a short "The Never Blank take:" section (2–3 sentences, 10% of article max).

Return only the Markdown article — no preamble, no JSON wrapper."""

_SOCIAL_SYSTEM = """You are writing social posts for Never Blank, a content practice for founders.

Never Blank voice: sharp, observational, commercially aware.
Forbidden: "in today's world", "let's dive in", "game-changer", "unlock", "leverage", "hustle"

Return JSON:
{
  "linkedin": "Full LinkedIn post — hook line \\n\\n 3–5 short paragraphs \\n\\n 1 question at end. 200–300 words.",
  "facebook": "Facebook post — warmer, opens with a real-world observation. 150–250 words.",
  "instagram": "Caption + 5 relevant hashtags. 80–120 words.",
  "threads_1": "Opening thread post — punchy one-liner, no hashtags. Max 250 chars.",
  "threads_2": "Follow-up thread post expanding the tension. Max 250 chars.",
  "threads_3": "Closing thread post — lesson or question. Max 250 chars.",
  "telegram": "Concise summary with the key business lesson. 100–150 words."
}"""


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80]


def _generate_blog_article(signal: dict, package: dict) -> str:
    angle = package.get("content", {}).get("blog", {}).get("angle", "")
    user = f"""Write a Never Blank article for this signal.

HEADLINE: {signal.get('HEADLINE', '')}
BLOG_ANGLE: {angle}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}
BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
NEVER_BLANK_ANGLE: {signal.get('NEVER_BLANK_ANGLE', '')}
POSSIBLE_SIGNATURE_LINE: {signal.get('POSSIBLE_SIGNATURE_LINE', '')}
TARGET_AUDIENCE: {signal.get('TARGET_AUDIENCE', 'founders')}"""

    try:
        return chat(_BLOG_SYSTEM, user, json_mode=False)
    except Exception as exc:
        log.error("Blog generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        # Minimal fallback
        return f"## {signal.get('HEADLINE', '')}\n\n{signal.get('CORE_FACT', '')}\n\n{signal.get('BUSINESS_LESSON', '')}"


def _generate_social_posts(signal: dict, package: dict) -> dict:
    content = package.get("content", {})
    user = f"""Generate social posts for this business signal.

HEADLINE: {signal.get('HEADLINE', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
NEVER_BLANK_ANGLE: {signal.get('NEVER_BLANK_ANGLE', '')}
POSSIBLE_SIGNATURE_LINE: {signal.get('POSSIBLE_SIGNATURE_LINE', '')}
LINKEDIN_ANGLE: {content.get('linkedin', {}).get('angle', '')}
THREADS_HOOK: {content.get('threads', {}).get('thread_hook', '')}
INSTAGRAM_ANCHOR: {content.get('instagram', {}).get('headline', '')}"""

    try:
        raw = chat(_SOCIAL_SYSTEM, user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        log.error("Social posts generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        return {}


def _build_draft_package(signal: dict, package: dict, blog_body: str, social: dict) -> DraftPackage:
    content = package.get("content", {})
    blog_content = content.get("blog", {})
    blog_title = blog_content.get("headline") or signal.get("HEADLINE", "")
    image_url  = (package.get("images", {})
                         .get("platform_images", {})
                         .get("blog", {})
                         .get("url") or None)

    wix_category_id = os.getenv("NB_WIX_BLOG_CATEGORY_ID", "")
    wix_tags_raw    = os.getenv("NB_WIX_BLOG_TAG_IDS", "")
    wix_tags        = [t.strip() for t in wix_tags_raw.split(",") if t.strip()] if wix_tags_raw else []
    wix_slug        = _slugify(blog_title)

    threads_seq = [
        social.get("threads_1", ""),
        social.get("threads_2", ""),
        social.get("threads_3", ""),
    ]
    threads_seq = [t for t in threads_seq if t]

    return DraftPackage(
        draft_dir       = PACKAGES_DIR,
        blog_title      = blog_title,
        blog_body       = blog_body,
        blog_meta       = {
            "title":            blog_title,
            "wix_slug":         wix_slug,
            "wix_category_id":  wix_category_id,
            "wix_tags":         wix_tags,
            "meta_description": blog_content.get("angle", "")[:500],
        },
        linkedin_text   = social.get("linkedin", blog_title),
        instagram_text  = social.get("instagram", blog_title),
        facebook_text   = social.get("facebook", blog_title),
        threads_sequence= threads_seq,
        telegram_text   = social.get("telegram", blog_title),
        image_url       = image_url,
        wix_slug        = wix_slug,
        wix_category_id = wix_category_id,
        wix_tags        = wix_tags,
        metadata        = {
            "signal_id": signal.get("SIGNAL_ID"),
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def publish_packages(
    signals: list[dict],
    packages: list[dict],
    mode: str | None = None,
) -> list[dict]:
    """
    Main entry point.  Publishes each signal across all platforms.
    Returns list of per-signal publish reports.
    """
    if not signals:
        return []

    if mode is None:
        mode = os.getenv("NB_PUBLISH_MODE", "live")

    log.info("Publishing %d signals in mode=%s", len(signals), mode)

    # Build a lookup by SIGNAL_ID for fast package access
    pkg_map = {p.get("SIGNAL_ID"): p for p in packages}

    reports = []
    for signal in signals:
        sig_id  = signal.get("SIGNAL_ID", "unknown")
        headline = signal.get("HEADLINE", "")
        package  = pkg_map.get(sig_id, {})

        log.info("Publishing signal: %s", headline[:60])

        blog_body = _generate_blog_article(signal, package)
        social    = _generate_social_posts(signal, package)
        draft     = _build_draft_package(signal, package, blog_body, social)

        results = {}
        wix_url: Optional[str] = None

        for name, publisher in _PUBLISHERS:
            try:
                if name == "telegram":
                    result = publisher.publish(draft, mode, wix_url=wix_url)
                else:
                    result = publisher.publish(draft, mode)

                if name == "wix" and result.ok():
                    wix_url = result.url

                results[name] = result.to_dict()
                log.info("%s → %s", name, result.status.value)
            except Exception as exc:
                log.error("%s publish error: %s", name, exc)
                results[name] = PublishResult(
                    platform=name,
                    status=PublishStatus.FAILED,
                    error_message=str(exc),
                ).to_dict()

        reports.append({
            "signal_id": sig_id,
            "headline":  headline,
            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode":      mode,
            "results":   results,
        })

    return reports


def format_publish_summary(reports: list[dict]) -> str:
    """Return markdown publish summary for daily report / step summary."""
    if not reports:
        return "No signals published."

    lines = ["\n## Publishing Summary\n"]

    # Per-signal per-platform results
    for i, report in enumerate(reports, 1):
        headline = report.get("headline", "")
        results  = report.get("results", {})
        lines.append(f"### Signal #{i}: {headline[:70]}")
        lines.append("")

        ok_platforms   = []
        fail_platforms = []

        for platform, res in results.items():
            status = res.get("status", "")
            icon   = "✅" if status in ("PUBLISHED", "DRAFT_CREATED") else ("⏭️" if status == "SKIPPED" else "❌")
            url    = res.get("url", "")
            err    = res.get("error_message", "")
            label  = platform.title()

            if status in ("PUBLISHED", "DRAFT_CREATED"):
                ok_platforms.append(platform)
                detail = f" — [{url}]({url})" if url else ""
                lines.append(f"- {icon} **{label}** {status}{detail}")
            elif status == "SKIPPED":
                lines.append(f"- {icon} **{label}** skipped — {err}")
            else:
                fail_platforms.append(platform)
                lines.append(f"- {icon} **{label}** FAILED — {err}")

        lines.append("")

    # Global asset summary
    lines.append("---")
    lines.append("## Validation Notes")
    for report in reports:
        results = report.get("results", {})
        failed = [p for p, r in results.items() if r.get("status") == "FAILED"]
        skipped = [p for p, r in results.items() if r.get("status") == "SKIPPED"]
        if failed:
            lines.append(f"- **{report['headline'][:50]}**: failed on {', '.join(failed)}")
        if skipped:
            lines.append(f"- **{report['headline'][:50]}**: skipped {', '.join(skipped)} (missing credentials)")

    if not any(
        r.get("status") == "FAILED"
        for report in reports
        for r in report.get("results", {}).values()
    ):
        lines.append("- All platforms published without errors.")

    return "\n".join(lines)
