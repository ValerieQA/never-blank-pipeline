"""
Stage 11 — Live publishing.
For each selected signal + its content package, generate full platform content
and publish to all channels.

Voice system: docs/NEVER_BLANK_EDITORIAL_STYLE.md + config/prompts/*.yaml
Research fields: all enriched signal fields used in generation.
Structure enforced: Signal → Tension → Real response → Outcome → Lesson → NB signature → Source.

Guards:
  NB_RESEARCH_PUBLISH_ENABLED              must be 'true' to publish (default: false)
  NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN  cap on signals per run (default: 1)
  NB_PUBLISH_MODE                          'live' | 'dry_run' (default: live)
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

PACKAGES_DIR   = Path("reports/content_packages")
PROMPTS_DIR    = Path("config/prompts")
EDITORIAL_PATH = Path("docs/NEVER_BLANK_EDITORIAL_STYLE.md")

_PUBLISHERS = [
    ("wix",       WixPublisher()),
    ("linkedin",  LinkedInPublisher()),
    ("facebook",  FacebookPublisher()),
    ("instagram", InstagramPublisher()),
    ("threads",   ThreadsPublisher()),
    ("telegram",  TelegramPublisher()),
]


# ── Editorial style loader ─────────────────────────────────────────────────────

def _load_editorial_style() -> str:
    if EDITORIAL_PATH.exists():
        return EDITORIAL_PATH.read_text(encoding="utf-8")
    return ""


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


def _cap_words(text: str, max_words: int) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])


# ── Never Blank signature helper ───────────────────────────────────────────────

def ensure_never_blank_signature(text: str, signal: dict) -> str:
    """
    Guarantee text ends with exactly one Never Blank signature line.
    Normalises POSSIBLE_SIGNATURE_LINE (strips any existing 'Never Blank:' prefix).
    Never produces 'Never Blank: Never Blank: ...'.
    """
    sig_raw   = signal.get("POSSIBLE_SIGNATURE_LINE", "").strip()
    sig_clean = re.sub(r"^Never\s+Blank[:\s]+", "", sig_raw, flags=re.IGNORECASE).strip()
    if not sig_clean:
        sig_clean = "The signal is rarely the event itself."
    signature = f"Never Blank: {sig_clean}"

    # If text already contains the correct signature, return as-is
    if re.search(r"Never\s+Blank[:\s]", text, re.IGNORECASE):
        # Strip any existing NB line and re-append cleanly
        text = re.sub(r"\n+Never\s+Blank[^\n]*$", "", text.rstrip(), flags=re.IGNORECASE).rstrip()

    return text + f"\n\n{signature}"


# ── Blog article ───────────────────────────────────────────────────────────────

def _generate_blog_article(signal: dict, package: dict) -> str:
    editorial = _load_editorial_style()

    system = f"""You write articles for Never Blank, a content practice for founders.

EDITORIAL STYLE (mandatory — follow exactly):
{editorial}

STRUCTURE (must follow in order):
1. Signal — what happened, with the core fact
2. Tension — the hidden business tension this reveals
3. Real business response — what businesses actually did (use BUSINESS_RESPONSES_OBSERVED)
4. Company example — REAL_COMPANY_EXAMPLE: what they faced, what they did (RESPONSE_TAKEN), what resulted (OUTCOME_IF_KNOWN)
5. Business lesson — the transferable insight (BUSINESS_LESSON)
6. Never Blank signature — one line, max 10% of article. Format: "Never Blank: [POSSIBLE_SIGNATURE_LINE]"
7. Source — hyperlinked citation using SOURCE_NAME and SOURCE_URL

Format: Markdown with ## subheadings. 600–900 words. No fluff.
Return only the article — no preamble, no JSON wrapper."""

    angle = package.get("content", {}).get("blog", {}).get("angle", "")

    user = f"""Write a Never Blank article for this signal.

SIGNAL DATA:
- HEADLINE: {signal.get('HEADLINE', '')}
- SOURCE_NAME: {signal.get('SOURCE_NAME', '')}
- SOURCE_URL: {signal.get('SOURCE_URL', '')}
- CORE_FACT: {signal.get('CORE_FACT', '')}
- CORE_TENSION: {signal.get('CORE_TENSION', '')}
- BUSINESS_RESPONSES_OBSERVED: {signal.get('BUSINESS_RESPONSES_OBSERVED', '')}
- REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
- PROBLEM_FACED: {signal.get('PROBLEM_FACED', '')}
- RESPONSE_TAKEN: {signal.get('RESPONSE_TAKEN', '')}
- OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}
- BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
- WHY_THIS_CASE_IS_INTERESTING: {signal.get('WHY_THIS_CASE_IS_INTERESTING', '')}
- NEVER_BLANK_ANGLE: {signal.get('NEVER_BLANK_ANGLE', '')}
- POSSIBLE_SIGNATURE_LINE: {signal.get('POSSIBLE_SIGNATURE_LINE', '')}
- TARGET_AUDIENCE: {signal.get('TARGET_AUDIENCE', 'founders')}
- BLOG_ANGLE: {angle}"""

    try:
        return chat(system, user, json_mode=False)
    except Exception as exc:
        log.error("Blog generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        return (
            f"## {signal.get('HEADLINE', '')}\n\n"
            f"{signal.get('CORE_FACT', '')}\n\n"
            f"**Tension:** {signal.get('CORE_TENSION', '')}\n\n"
            f"**Example:** {signal.get('REAL_COMPANY_EXAMPLE', '')} — {signal.get('OUTCOME_IF_KNOWN', '')}\n\n"
            f"**Lesson:** {signal.get('BUSINESS_LESSON', '')}\n\n"
            f"Never Blank: {signal.get('POSSIBLE_SIGNATURE_LINE', '')}\n\n"
            f"Source: [{signal.get('SOURCE_NAME', '')}]({signal.get('SOURCE_URL', '')})"
        )


# ── Social content generators ─────────────────────────────────────────────────

def _research_context(signal: dict) -> str:
    """Shared research table context block injected into every social prompt."""
    return f"""RESEARCH TABLE DATA (use all fields — do not ignore):
- CORE_FACT: {signal.get('CORE_FACT', '')}
- CORE_TENSION: {signal.get('CORE_TENSION', '')}
- BUSINESS_RESPONSES_OBSERVED: {signal.get('BUSINESS_RESPONSES_OBSERVED', '')}
- REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
- PROBLEM_FACED: {signal.get('PROBLEM_FACED', '')}
- RESPONSE_TAKEN: {signal.get('RESPONSE_TAKEN', '')}
- OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}
- BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
- WHY_THIS_CASE_IS_INTERESTING: {signal.get('WHY_THIS_CASE_IS_INTERESTING', '')}
- NEVER_BLANK_ANGLE: {signal.get('NEVER_BLANK_ANGLE', '')}
- POSSIBLE_SIGNATURE_LINE: {signal.get('POSSIBLE_SIGNATURE_LINE', '')}
- SOURCE_NAME: {signal.get('SOURCE_NAME', '')}
- SOURCE_URL: {signal.get('SOURCE_URL', '')}

REQUIRED STRUCTURE: Signal → Tension → Real business response → Outcome → Lesson → Never Blank signature"""


def _generate_linkedin_post(signal: dict, blog_body: str, wix_url: str = "") -> str:
    prompt = _load_prompt("linkedin_post")
    user = prompt["user"].format(
        core_idea             = signal.get("BUSINESS_LESSON", ""),
        mechanism             = signal.get("CORE_TENSION", ""),
        cost_of_ignoring      = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        strategic_question    = signal.get("INTERESTING_QUESTION", ""),
        primary_hook          = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        linkedin_angle        = signal.get("LINKEDIN_ANGLE", ""),
        soft_cta              = "",
        sales_angle           = "",
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal          = "challenge",
        wix_url               = wix_url,
        blog_body             = blog_body[:3000],
    ) + f"\n\n{_research_context(signal)}"
    try:
        raw    = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed.get("text", "") if isinstance(parsed, dict) else ""
    except Exception as exc:
        log.error("LinkedIn generation failed: %s", exc)
        return ""


def _generate_facebook_post(signal: dict, blog_body: str, wix_url: str = "") -> str:
    prompt = _load_prompt("facebook_post")
    user = prompt["user"].format(
        core_idea             = signal.get("BUSINESS_LESSON", ""),
        observation           = signal.get("CORE_FACT", ""),
        cost_of_ignoring      = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        facebook_angle        = signal.get("BLOG_ANGLE", ""),
        supporting_points     = signal.get("CORE_TENSION", ""),
        soft_cta              = "",
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal          = "challenge",
        wix_url               = wix_url,
        blog_body             = blog_body[:2000],
    ) + f"\n\n{_research_context(signal)}"
    try:
        raw    = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        text   = parsed.get("text", "") if isinstance(parsed, dict) else ""
        return _cap_words(text, max_words=220)
    except Exception as exc:
        log.error("Facebook generation failed: %s", exc)
        return ""


def _generate_instagram_caption(signal: dict) -> str:
    prompt = _load_prompt("instagram_caption")
    user = prompt["user"].format(
        core_idea             = signal.get("BUSINESS_LESSON", ""),
        primary_hook          = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        visual_anchor         = signal.get("POSSIBLE_SIGNATURE_LINE", ""),
        instagram_angle       = signal.get("STORY_ANGLE", ""),
        supporting_points     = signal.get("CORE_TENSION", ""),
        soft_cta              = "",
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal          = "challenge",
    ) + f"\n\n{_research_context(signal)}"
    try:
        raw    = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            caption  = parsed.get("caption", "")
            hashtags = parsed.get("hashtags", [])
            tag_line = " ".join(f"#{t.lstrip('#')}" for t in hashtags)
            text     = f"{caption}\n\n{tag_line}" if tag_line else caption
            return ensure_never_blank_signature(text, signal)
        return ""
    except Exception as exc:
        log.error("Instagram generation failed: %s", exc)
        return ""


def _generate_threads_sequence(signal: dict, blog_body: str) -> list[str]:
    prompt = _load_prompt("threads_post")
    user = prompt["user"].format(
        primary_hook          = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        mechanism             = signal.get("CORE_TENSION", ""),
        cost_of_ignoring      = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        threads_angle         = signal.get("THREADS_ANGLE", ""),
        supporting_points     = signal.get("BUSINESS_LESSON", ""),
        observation_statement = signal.get("CORE_FACT", ""),
        content_goal          = "challenge",
        blog_body             = blog_body[:2000],
    ) + f"\n\n{_research_context(signal)}"
    try:
        raw    = chat(prompt["system"], user, json_mode=True)
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
        primary_hook          = signal.get("POTENTIAL_HOOK", signal.get("HEADLINE", "")),
        telegram_angle        = signal.get("THREADS_ANGLE", ""),
        cost_of_ignoring      = signal.get("WHY_IT_MATTERS_TO_BUSINESS", ""),
        soft_cta              = "",
        observation_statement = signal.get("CORE_FACT", ""),
        wix_url               = wix_url or "",
    ) + f"\n\n{_research_context(signal)}"
    try:
        raw    = chat(prompt["system"], user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        text   = parsed.get("text", "") if isinstance(parsed, dict) else ""
    except Exception as exc:
        log.error("Telegram generation failed: %s", exc)
        text = signal.get("CORE_FACT", signal.get("HEADLINE", ""))

    return ensure_never_blank_signature(text, signal)


# ── DraftPackage assembly ─────────────────────────────────────────────────────

def _build_draft(
    signal: dict,
    package: dict,
    blog_body: str,
    linkedin_text: str,
    facebook_text: str,
    instagram_text: str,
    threads_seq: list[str],
    telegram_text: str,
    image_url_blog: Optional[str] = None,
) -> DraftPackage:
    content    = package.get("content", {})
    blog_title = content.get("blog", {}).get("headline") or signal.get("HEADLINE", "")
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
    if not signals:
        return []

    publish_enabled = os.getenv("NB_RESEARCH_PUBLISH_ENABLED", "false").lower() == "true"
    if not publish_enabled:
        log.info("Publishing disabled (NB_RESEARCH_PUBLISH_ENABLED != true) — skipping Stage 11")
        return []

    max_signals = int(os.getenv("NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN", "1"))
    if len(signals) > max_signals:
        log.info("Capping signals: %d → %d", len(signals), max_signals)
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
        pimgs    = package.get("images", {}).get("platform_images", {})

        log.info("Publishing signal: %s", headline[:60])

        # Blog article first — used as source material for social posts
        blog_body = _generate_blog_article(signal, package)

        # Social content — using config/prompts/*.yaml + research table fields
        wix_url        = ""
        linkedin_text  = _generate_linkedin_post(signal, blog_body, wix_url)
        facebook_text  = _generate_facebook_post(signal, blog_body, wix_url)
        instagram_text = _generate_instagram_caption(signal)
        threads_seq    = _generate_threads_sequence(signal, blog_body)
        telegram_text  = _generate_telegram_text(signal, wix_url)

        image_url_blog = pimgs.get("blog", {}).get("url") or None
        draft = _build_draft(
            signal, package,
            blog_body, linkedin_text, facebook_text,
            instagram_text, threads_seq, telegram_text,
            image_url_blog,
        )

        # Save generated content to disk before publishing
        generated_path = PACKAGES_DIR / f"{sig_id}_generated.json"
        _save_generated(generated_path, sig_id, headline, blog_body,
                        linkedin_text, facebook_text, instagram_text,
                        threads_seq, telegram_text, wix_url="")

        results: dict = {}

        for name, publisher in _PUBLISHERS:
            # Use platform-specific image URL
            platform_img = pimgs.get(name, {}).get("url") or draft.image_url
            if name in ("linkedin", "facebook", "instagram") and platform_img != draft.image_url:
                use_draft = _swap_image(draft, platform_img)
            else:
                use_draft = draft

            try:
                if name == "telegram":
                    # Always use the most up-to-date telegram_text (may have been
                    # regenerated with wix_url after Wix publisher ran)
                    use_draft.telegram_text = telegram_text
                    result = publisher.publish(use_draft, mode, wix_url=wix_url)
                else:
                    result = publisher.publish(use_draft, mode)

                if name == "wix" and result.ok() and result.url:
                    wix_url = result.url
                    # Regenerate Telegram text with the now-known Wix URL so
                    # TelegramPublisher receives the final version
                    telegram_text = _generate_telegram_text(signal, wix_url)
                    draft.telegram_text = telegram_text
                    _save_generated(generated_path, sig_id, headline, blog_body,
                                    linkedin_text, facebook_text, instagram_text,
                                    threads_seq, telegram_text, wix_url=wix_url)

                res_dict = result.to_dict()
                if result.ok() and not result.url:
                    res_dict["status"] = "published_url_unavailable"
                results[name] = res_dict
                log.info("%s → %s (url=%s)", name, result.status.value, result.url or "none")

            except Exception as exc:
                log.error("%s publish error: %s", name, exc)
                results[name] = PublishResult(
                    platform=name, status=PublishStatus.FAILED, error_message=str(exc),
                ).to_dict()

        ig_sig  = "Never Blank" in instagram_text
        tg_sig  = "Never Blank" in telegram_text
        wix_cov = "published_without_cover_image" in (results.get("wix", {}).get("error_message") or "")

        reports.append({
            "signal_id":                  sig_id,
            "headline":                   headline,
            "published_at":               datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode":                       mode,
            "results":                    results,
            "wix_url":                    wix_url,
            "generated_file":             str(generated_path),
            "platform_images":            {p: {"url": pimgs.get(p, {}).get("url", ""), "size": pimgs.get(p, {}).get("size", "")} for p in ("blog","linkedin","facebook","instagram","threads","stories")},
            "instagram_signature":        ig_sig,
            "telegram_signature":         tg_sig,
            "wix_cover_image_attached":   not wix_cov,
            "image_design_version":       package.get("images", {}).get("design_version", ""),
            "image_hook_text":            package.get("images", {}).get("hook_text", ""),
            "image_visual_family":        package.get("images", {}).get("visual_family", ""),
            "image_method":               package.get("images", {}).get("image_method", ""),
        })

    return reports


def _swap_image(draft: DraftPackage, image_url: str) -> DraftPackage:
    """Return a shallow copy of draft with a different image_url."""
    return DraftPackage(
        draft_dir=draft.draft_dir,
        blog_title=draft.blog_title,
        blog_body=draft.blog_body,
        blog_meta=draft.blog_meta,
        linkedin_text=draft.linkedin_text,
        instagram_text=draft.instagram_text,
        facebook_text=draft.facebook_text,
        threads_sequence=draft.threads_sequence,
        telegram_text=draft.telegram_text,
        image_url=image_url,
        wix_slug=draft.wix_slug,
        wix_category_id=draft.wix_category_id,
        wix_tags=draft.wix_tags,
        metadata=draft.metadata,
    )


def _save_generated(path: Path, sig_id, headline, blog_body,
                    linkedin, facebook, instagram, threads, telegram, wix_url):
    path.write_text(json.dumps({
        "signal_id":          sig_id,
        "headline":           headline,
        "generated_at":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "wix_url":            wix_url,
        "blog_article":       blog_body,
        "linkedin_post":      linkedin,
        "facebook_post":      facebook,
        "instagram_caption":  instagram,
        "threads_sequence":   threads,
        "telegram_text":      telegram,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def format_publish_summary(reports: list[dict]) -> str:
    if not reports:
        return "No signals published."

    lines = ["\n## Publishing Summary\n"]
    for i, report in enumerate(reports, 1):
        headline = report.get("headline", "")
        results  = report.get("results", {})
        mode     = report.get("mode", "live")
        lines.append(f"### Signal #{i}: {headline[:70]}")
        lines.append(f"_Mode: {mode}_  |  _Design version: {report.get('image_design_version','—')}_  |  _Visual: {report.get('image_visual_family','—')}_")
        lines.append(f"_Hook text: {report.get('image_hook_text','—')}_")
        lines.append("")

        for platform, res in results.items():
            status = res.get("status", "")
            url    = res.get("url", "")
            err    = res.get("error_message", "")
            if status in ("PUBLISHED", "DRAFT_CREATED"):
                lines.append(f"- ✅ **{platform.title()}** {status}{' — [' + url + '](' + url + ')' if url else ''}")
            elif status == "published_url_unavailable":
                lines.append(f"- ✅ **{platform.title()}** published — URL unavailable")
            elif status == "SKIPPED":
                lines.append(f"- ⏭️ **{platform.title()}** skipped — {err}")
            else:
                lines.append(f"- ❌ **{platform.title()}** FAILED — {err}")

        lines.append("")
        lines.append(f"- Wix cover image: {'❌ not attached (external URL not supported by Wix Blog v3)' if not report.get('wix_cover_image_attached') else '✅ attached'}")
        lines.append(f"- Instagram signature: {'✅ included' if report.get('instagram_signature') else '❌ missing'}")
        lines.append(f"- Telegram signature: {'✅ included' if report.get('telegram_signature') else '❌ missing'}")
        lines.append(f"- Generated content: `{report.get('generated_file','—')}`")
        lines.append("")

        pimgs = report.get("platform_images", {})
        if pimgs:
            lines.append("**Platform images:**")
            for p, info in pimgs.items():
                url  = info.get("url", "")
                size = info.get("size", "")
                lines.append(f"  - {'✅' if url else '❌'} {p} ({size}): {url[:70] if url else 'no URL'}")
            lines.append("")

    lines.append("---")
    lines.append("## Validation Notes")
    issues = []
    for report in reports:
        results = report.get("results", {})
        failed  = [p for p, r in results.items() if r.get("status") == "FAILED"]
        skipped = [p for p, r in results.items() if r.get("status") == "SKIPPED"]
        if failed:
            issues.append(f"- FAILED platforms for '{report['headline'][:50]}': {', '.join(failed)}")
        if skipped:
            issues.append(f"- Skipped (no creds): {', '.join(skipped)}")
        if not report.get("wix_cover_image_attached"):
            issues.append("- Wix: cover image not attached — Wix Blog v3 requires Wix Media Manager ID")
        if not report.get("instagram_signature"):
            issues.append("- Instagram: Never Blank signature missing")
        if not report.get("telegram_signature"):
            issues.append("- Telegram: Never Blank signature missing")
    if not issues:
        issues.append("- No issues.")
    lines.extend(issues)

    return "\n".join(lines)
