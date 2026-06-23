"""
Stage 11 — Live publishing.
For each selected signal + its content package, generate full platform content
and publish to all channels.

Content generation uses config/prompts/*.yaml — same voice system as the main pipeline.
Social posts are saved to disk alongside content packages for auditability.

Guards:
  NB_RESEARCH_PUBLISH_ENABLED          — must be 'true' to publish (default: false)
  NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN — cap on signals per run (default: 1)
  NB_PUBLISH_MODE                      — 'live' | 'dry_run' (default: live)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

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

PACKAGES_DIR  = Path("reports/content_packages")
PROMPTS_DIR   = Path("config/prompts")
EDITORIAL_DOC = Path("docs/NEVER_BLANK_EDITORIAL_STYLE.md")

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
Forbidden: "in today's world", "let's dive in", "game-changer", "unlock", "leverage", "hustle"

Write a blog article in Markdown. Use ## subheadings. 600–900 words. No fluff.
End with a short "The Never Blank take:" section (2–3 sentences, max 10% of article).

Return only the Markdown article — no preamble, no JSON wrapper."""


# ── Prompt loading ─────────────────────────────────────────────────────────────

def _load_prompt(name: str) -> dict:
    path = PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80]


# ── Per-platform content generation ───────────────────────────────────────────

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
        return f"## {signal.get('HEADLINE', '')}\n\n{signal.get('CORE_FACT', '')}\n\n{signal.get('BUSINESS_LESSON', '')}"


def _generate_linkedin_post(signal: dict, blog_body: str, wix_url: str = "") -> str:
    prompt = _load_prompt("linkedin_post")
    content_pkg = {}  # angles from content package aren't needed — signal has LINKEDIN_ANGLE
    user = prompt["user"].format(
        core_idea           = signal.get("BUSINESS_LESSON", ""),
        mechanism           = signal.get("CORE_TENSION", ""),
        cost_of_ignoring    = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        strategic_question  = signal.get("INTERESTING_QUESTION", ""),
        primary_hook        = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        linkedin_angle      = signal.get("LINKEDIN_ANGLE", ""),
        soft_cta            = "",
        sales_angle         = "",
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal        = "challenge",
        wix_url             = wix_url,
        blog_body           = blog_body[:3000],
    )
    try:
        raw = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed.get("text", "") if isinstance(parsed, dict) else ""
    except Exception as exc:
        log.error("LinkedIn generation failed: %s", exc)
        return ""


def _generate_facebook_post(signal: dict, blog_body: str, wix_url: str = "") -> str:
    prompt = _load_prompt("facebook_post")
    user = prompt["user"].format(
        core_idea           = signal.get("BUSINESS_LESSON", ""),
        observation         = signal.get("CORE_FACT", ""),
        cost_of_ignoring    = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        facebook_angle      = signal.get("BLOG_ANGLE", ""),
        supporting_points   = signal.get("CORE_TENSION", ""),
        soft_cta            = "",
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal        = "challenge",
        wix_url             = wix_url,
        blog_body           = blog_body[:3000],
    )
    # Facebook API has a payload size limit — cap at 1800 chars to stay safe
    try:
        raw = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        text = parsed.get("text", "") if isinstance(parsed, dict) else ""
        return _cap_words(text, max_words=220)
    except Exception as exc:
        log.error("Facebook generation failed: %s", exc)
        return ""


def _generate_instagram_caption(signal: dict) -> tuple[str, list[str]]:
    prompt = _load_prompt("instagram_caption")
    user = prompt["user"].format(
        core_idea           = signal.get("BUSINESS_LESSON", ""),
        primary_hook        = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        visual_anchor       = signal.get("POSSIBLE_SIGNATURE_LINE", ""),
        instagram_angle     = signal.get("STORY_ANGLE", ""),
        supporting_points   = signal.get("CORE_TENSION", ""),
        soft_cta            = "",
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal        = "challenge",
    )
    try:
        raw = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            caption   = parsed.get("caption", "")
            hashtags  = parsed.get("hashtags", [])
            tag_line  = " ".join(f"#{t.lstrip('#')}" for t in hashtags)
            full_text = f"{caption}\n\n{tag_line}" if tag_line else caption
            return full_text, hashtags
        return "", []
    except Exception as exc:
        log.error("Instagram generation failed: %s", exc)
        return "", []


def _generate_threads_sequence(signal: dict, blog_body: str) -> list[str]:
    prompt = _load_prompt("threads_post")
    user = prompt["user"].format(
        primary_hook        = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        mechanism           = signal.get("CORE_TENSION", ""),
        cost_of_ignoring    = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        threads_angle       = signal.get("THREADS_ANGLE", ""),
        supporting_points   = signal.get("BUSINESS_LESSON", ""),
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal        = "challenge",
        blog_body           = blog_body[:2000],
    )
    try:
        raw = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            seq = parsed.get("sequence", [])
            return [s for s in seq if isinstance(s, str) and s.strip()]
        return []
    except Exception as exc:
        log.error("Threads generation failed: %s", exc)
        return []


def _generate_telegram_text(signal: dict, wix_url: str = "") -> str:
    prompt = _load_prompt("telegram_post")
    user = prompt["user"].format(
        primary_hook        = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        telegram_angle      = signal.get("THREADS_ANGLE", ""),   # closest analogue
        cost_of_ignoring    = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        soft_cta            = "",
        observation_statement = signal.get("CORE_FACT", ""),
        wix_url             = wix_url or "",
    )
    try:
        raw = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        text = parsed.get("text", "") if isinstance(parsed, dict) else ""
    except Exception as exc:
        log.error("Telegram generation failed: %s", exc)
        text = f"{signal.get('CORE_FACT', signal.get('HEADLINE', ''))}"

    # Append Never Blank signature line — always present
    sig_line = signal.get("POSSIBLE_SIGNATURE_LINE", "")
    if sig_line:
        signature = f"\nNever Blank: {sig_line}"
    else:
        signature = "\nNever Blank."

    # Ensure signature is not already in text
    if "Never Blank:" not in text and "Never Blank." not in text:
        text = text.rstrip() + signature

    return text


def _cap_words(text: str, max_words: int) -> str:
    """Trim text at a word boundary to max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


# ── DraftPackage assembly ─────────────────────────────────────────────────────

def _build_draft_package(
    signal: dict,
    package: dict,
    blog_body: str,
    linkedin_text: str,
    facebook_text: str,
    instagram_text: str,
    threads_seq: list[str],
    telegram_text: str,
) -> DraftPackage:
    content    = package.get("content", {})
    blog_title = content.get("blog", {}).get("headline") or signal.get("HEADLINE", "")
    pimgs      = package.get("images", {}).get("platform_images", {})

    # Use platform-specific image URL where available
    image_url_blog = pimgs.get("blog", {}).get("url") or None

    wix_category_id = os.getenv("NB_WIX_BLOG_CATEGORY_ID", "")
    wix_tags_raw    = os.getenv("NB_WIX_BLOG_TAG_IDS", "")
    wix_tags        = [t.strip() for t in wix_tags_raw.split(",") if t.strip()] if wix_tags_raw else []
    wix_slug        = _slugify(blog_title)

    return DraftPackage(
        draft_dir        = PACKAGES_DIR,
        blog_title       = blog_title,
        blog_body        = blog_body,
        blog_meta        = {
            "title":           blog_title,
            "wix_slug":        wix_slug,
            "wix_category_id": wix_category_id,
            "wix_tags":        wix_tags,
            "meta_description": content.get("blog", {}).get("angle", "")[:500],
        },
        linkedin_text    = linkedin_text,
        instagram_text   = instagram_text,
        facebook_text    = facebook_text,
        threads_sequence = threads_seq,
        telegram_text    = telegram_text,
        image_url        = image_url_blog,
        wix_slug         = wix_slug,
        wix_category_id  = wix_category_id,
        wix_tags         = wix_tags,
        metadata         = {
            "signal_id":    signal.get("SIGNAL_ID"),
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# ── Main entry ────────────────────────────────────────────────────────────────

def publish_packages(
    signals: list[dict],
    packages: list[dict],
    mode: Optional[str] = None,
) -> list[dict]:
    """
    Publishes each signal (up to NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN) across all platforms.
    Returns list of per-signal publish reports.
    """
    if not signals:
        return []

    publish_enabled = os.getenv("NB_RESEARCH_PUBLISH_ENABLED", "false").lower() == "true"
    if not publish_enabled:
        log.info("Publishing disabled (NB_RESEARCH_PUBLISH_ENABLED != true) — skipping Stage 11")
        return []

    max_signals = int(os.getenv("NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN", "1"))
    if len(signals) > max_signals:
        log.info(
            "Capping signals to publish: %d → %d (NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN=%d)",
            len(signals), max_signals, max_signals,
        )
        signals = signals[:max_signals]

    if mode is None:
        mode = os.getenv("NB_PUBLISH_MODE", "live")

    log.info("Publishing %d signal(s) in mode=%s", len(signals), mode)

    pkg_map = {p.get("SIGNAL_ID"): p for p in packages}
    reports = []

    for signal in signals:
        sig_id   = signal.get("SIGNAL_ID", "unknown")
        headline = signal.get("HEADLINE", "")
        package  = pkg_map.get(sig_id, {})

        log.info("Publishing signal: %s", headline[:60])

        # Generate blog article first (used as source for social)
        blog_body = _generate_blog_article(signal, package)

        # Platform content — using config/prompts/*.yaml
        wix_url = ""  # filled in after wix publishes
        linkedin_text  = _generate_linkedin_post(signal, blog_body, wix_url)
        facebook_text  = _generate_facebook_post(signal, blog_body, wix_url)
        instagram_text, _ = _generate_instagram_caption(signal)
        threads_seq    = _generate_threads_sequence(signal, blog_body)
        telegram_text  = _generate_telegram_text(signal, wix_url)

        draft = _build_draft_package(
            signal, package,
            blog_body, linkedin_text, facebook_text,
            instagram_text, threads_seq, telegram_text,
        )

        # Save generated content to disk for auditability
        generated_path = PACKAGES_DIR / f"{sig_id}_generated.json"
        generated_path.write_text(json.dumps({
            "signal_id":      sig_id,
            "headline":       headline,
            "generated_at":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "blog_article":   blog_body,
            "linkedin_post":  linkedin_text,
            "facebook_post":  facebook_text,
            "instagram_caption": instagram_text,
            "threads_sequence":  threads_seq,
            "telegram_text":  telegram_text,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        results: dict = {}
        pimgs = package.get("images", {}).get("platform_images", {})

        for name, publisher in _PUBLISHERS:
            # Use platform-specific image URL for LinkedIn and Instagram publishers
            # by temporarily patching draft.image_url for each call
            if name in ("linkedin", "facebook", "instagram"):
                platform_img = pimgs.get(name, {}).get("url") or draft.image_url
                # Build a minimal override draft with the right image URL
                img_draft = DraftPackage(
                    draft_dir=draft.draft_dir,
                    blog_title=draft.blog_title,
                    blog_body=draft.blog_body,
                    blog_meta=draft.blog_meta,
                    linkedin_text=draft.linkedin_text,
                    instagram_text=draft.instagram_text,
                    facebook_text=draft.facebook_text,
                    threads_sequence=draft.threads_sequence,
                    telegram_text=draft.telegram_text,
                    image_url=platform_img,
                    wix_slug=draft.wix_slug,
                    wix_category_id=draft.wix_category_id,
                    wix_tags=draft.wix_tags,
                    metadata=draft.metadata,
                )
                use_draft = img_draft
            else:
                use_draft = draft

            try:
                if name == "telegram":
                    result = publisher.publish(use_draft, mode, wix_url=wix_url)
                else:
                    result = publisher.publish(use_draft, mode)

                if name == "wix" and result.ok() and result.url:
                    wix_url = result.url
                    # Regenerate telegram text with the now-known Wix URL
                    telegram_text = _generate_telegram_text(signal, wix_url)
                    # Update saved generated content
                    try:
                        saved = json.loads(generated_path.read_text())
                        saved["telegram_text"] = telegram_text
                        saved["wix_url"] = wix_url
                        generated_path.write_text(json.dumps(saved, indent=2, ensure_ascii=False))
                    except Exception:
                        pass

                res_dict = result.to_dict()
                if result.ok() and not result.url:
                    res_dict["status"] = "published_url_unavailable"
                results[name] = res_dict

                log.info("%s → %s (url=%s)", name, result.status.value, result.url or "none")
            except Exception as exc:
                log.error("%s publish error: %s", name, exc)
                results[name] = PublishResult(
                    platform=name,
                    status=PublishStatus.FAILED,
                    error_message=str(exc),
                ).to_dict()

        # Reporting metadata
        pimgs_summary = {
            p: {"url": pimgs.get(p, {}).get("url", ""), "size": pimgs.get(p, {}).get("size", "")}
            for p in ("blog", "linkedin", "facebook", "instagram", "threads", "stories")
        }

        reports.append({
            "signal_id":        sig_id,
            "headline":         headline,
            "published_at":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode":             mode,
            "results":          results,
            "wix_url":          wix_url,
            "generated_file":   str(generated_path),
            "platform_images":  pimgs_summary,
            "telegram_signature_included": "Never Blank" in telegram_text,
            "wix_cover_image":  "published_without_cover_image" in (results.get("wix", {}).get("error_message") or ""),
        })

    return reports


def format_publish_summary(reports: list[dict]) -> str:
    if not reports:
        return "No signals published."

    lines = ["\n## Publishing Summary\n"]

    for i, report in enumerate(reports, 1):
        headline = report.get("headline", "")
        results  = report.get("results", {})
        mode     = report.get("mode", "live")
        wix_url  = report.get("wix_url", "")

        lines.append(f"### Signal #{i}: {headline[:70]}")
        lines.append(f"_Mode: {mode}_")
        lines.append("")

        for platform, res in results.items():
            status = res.get("status", "")
            url    = res.get("url", "")
            err    = res.get("error_message", "")

            if status in ("PUBLISHED", "DRAFT_CREATED"):
                url_part = f" — [{url}]({url})" if url else ""
                lines.append(f"- ✅ **{platform.title()}** {status}{url_part}")
            elif status == "published_url_unavailable":
                lines.append(f"- ✅ **{platform.title()}** published — URL unavailable (check platform directly)")
            elif status == "SKIPPED":
                lines.append(f"- ⏭️ **{platform.title()}** skipped — {err}")
            else:
                lines.append(f"- ❌ **{platform.title()}** FAILED — {err}")

        lines.append("")
        lines.append(f"- Wix cover image: {'⚠️ not attached (external URL not supported)' if report.get('wix_cover_image') else '✅ n/a'}")
        lines.append(f"- Telegram signature: {'✅ included' if report.get('telegram_signature_included') else '❌ missing'}")
        lines.append(f"- Generated content saved: `{report.get('generated_file', '—')}`")
        lines.append("")

    # Platform image sizes
    lines.append("### Platform Images")
    for report in reports:
        pimgs = report.get("platform_images", {})
        if pimgs:
            lines.append(f"**{report['headline'][:50]}**")
            for p, info in pimgs.items():
                url  = info.get("url", "")
                size = info.get("size", "")
                icon = "✅" if url else "❌"
                lines.append(f"- {icon} {p} ({size}): {url[:70] if url else 'no URL'}")
            lines.append("")

    lines.append("---")
    lines.append("## Validation Notes")
    issues = []
    for report in reports:
        results = report.get("results", {})
        failed  = [p for p, r in results.items() if r.get("status") == "FAILED"]
        skipped = [p for p, r in results.items() if r.get("status") == "SKIPPED"]
        if failed:
            issues.append(f"- **{report['headline'][:50]}**: FAILED on {', '.join(failed)}")
        if skipped:
            issues.append(f"- **{report['headline'][:50]}**: skipped {', '.join(skipped)} (missing credentials)")
        if report.get("wix_cover_image"):
            issues.append("- Wix cover image: requires Wix Media Manager upload — not yet implemented")
    if issues:
        lines.extend(issues)
    else:
        lines.append("- No issues.")

    return "\n".join(lines)
