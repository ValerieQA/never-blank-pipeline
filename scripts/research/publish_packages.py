"""Stage 11 — publish owner-centred Editorial Engine V2 output.

The research workflow may publish only after the complete cross-platform package passes
hard validation.  A failed generation or validation publishes nothing for that signal.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.content.output_guard import (
    repeated_cross_platform_phrases,
    validate_platform_output,
    validate_telegram,
)
from src.strategy.validators import validate_article_for_publish
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.editorial.pipeline import ArticleGenerationError, generate_article
from src.publishing import formatting
from src.publishing.base import DraftPackage
from src.publishing.facebook import FacebookPublisher
from src.publishing.hashtags import generate_hashtags
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import WixPublisher
from src.utils.logger import get_logger

log = get_logger("research.publish_packages")
PACKAGES_DIR = Path("reports/content_packages")

_PUBLISHERS = [
    ("wix", WixPublisher()),
    ("linkedin", LinkedInPublisher()),
    ("facebook", FacebookPublisher()),
    ("instagram", InstagramPublisher()),
    ("threads", ThreadsPublisher()),
    ("telegram", TelegramPublisher()),
]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"[\s_]+", "-", slug)[:80]


def ensure_never_blank_signature(text: str, signal: dict) -> str:
    """Backward-compatible tested helper; publishing no longer forces a signature."""
    raw = signal.get("POSSIBLE_SIGNATURE_LINE", "").strip()
    clean = re.sub(r"^Never\s+Blank[:\s]+", "", raw, flags=re.I).strip()
    clean = clean or "The signal is rarely the event itself."
    text = re.sub(r"\n+Never\s+Blank[^\n]*$", "", text.rstrip(), flags=re.I).rstrip()
    return f"{text}\n\nNever Blank: {clean}"


def _clean_line(value: str, max_words: int = 34) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    words = value.split()
    if len(words) <= max_words:
        return value
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _build_telegram(structured: dict, wix_url: str = "") -> str:
    """Build the Telegram channel's own format, never reuse an article body."""
    discovery = structured.get("discovery", {})
    observation = (
        discovery.get("aha_setup")
        or discovery.get("first_wrong_explanation")
        or structured.get("hook")
        or structured.get("narrative_spine")
    )
    implication = structured.get("business_translation") or structured.get("reframe")
    lines = [_clean_line(observation), _clean_line(implication)]
    if wix_url:
        lines.append(wix_url.strip())
    text = "\n".join(line for line in lines if line)
    validate_telegram(text)
    return text


def _build_threads(structured: dict) -> list[str]:
    """Native 3–5 post arc: Hook → Recognition → Mechanism → Reframe → Echo."""
    discovery = structured.get("discovery", {})
    candidates = [
        structured.get("hook", ""),
        discovery.get("aha_setup") or discovery.get("first_wrong_explanation", ""),
        structured.get("surviving_explanation", ""),
        structured.get("reframe", ""),
        structured.get("echo_line", ""),
    ]
    sequence: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        post = _clean_line(value, max_words=55)
        key = post.lower()
        if post and key not in seen:
            validate_platform_output("threads", post)
            sequence.append(post)
            seen.add(key)
    if not 3 <= len(sequence) <= 5:
        raise ValueError(f"Threads requires 3–5 distinct posts; generated {len(sequence)}")
    return sequence


def _validate_package(texts: dict[str, str], threads: list[str]) -> None:
    for platform, text in texts.items():
        # Blog and LinkedIn also get the Compound Presence semantic check.
        if platform in ("blog", "linkedin"):
            validate_article_for_publish(text, platform=platform)
        else:
            validate_platform_output(platform, text)
    for post in threads:
        validate_platform_output("threads", post)

    # Shared concepts are expected, but one prose sentence copied into three or more
    # channels means the platform layer collapsed back into truncation/copy-paste.
    duplicates = repeated_cross_platform_phrases({**texts, "threads": "\n".join(threads)})
    severe = [d for d in duplicates if len(d.get("platforms", [])) >= 3]
    if severe:
        sample = severe[0]
        raise ValueError(
            "Cross-platform copy detected before publishing: "
            f"{sample['platforms']} repeat {sample['phrase']!r}"
        )


def _build_draft(signal: dict, package: dict, blog_body: str, linkedin_text: str,
                 facebook_text: str, instagram_text: str, threads_seq: list[str],
                 telegram_text: str, image_url_blog: Optional[str] = None) -> DraftPackage:
    preview = package.get("content", {})
    blog_title = preview.get("blog", {}).get("headline") or signal.get("HEADLINE", "")
    wix_category_id = os.getenv("NB_WIX_BLOG_CATEGORY_ID", "")
    wix_tags_raw = os.getenv("NB_WIX_BLOG_TAG_IDS", "")
    wix_tags = [x.strip() for x in wix_tags_raw.split(",") if x.strip()]
    wix_slug = _slugify(blog_title)
    return DraftPackage(
        draft_dir=PACKAGES_DIR,
        blog_title=blog_title,
        blog_body=blog_body,
        blog_meta={
            "title": blog_title,
            "wix_slug": wix_slug,
            "wix_category_id": wix_category_id,
            "wix_tags": wix_tags,
            "meta_description": preview.get("blog", {}).get("angle", "")[:500],
        },
        linkedin_text=linkedin_text,
        instagram_text=instagram_text,
        facebook_text=facebook_text,
        threads_sequence=threads_seq,
        telegram_text=telegram_text,
        image_url=image_url_blog,
        wix_slug=wix_slug,
        wix_category_id=wix_category_id,
        wix_tags=wix_tags,
        metadata={"signal_id": signal.get("SIGNAL_ID"), "published_at": datetime.now(timezone.utc).isoformat()},
    )


def publish_packages(signals: list[dict], packages: list[dict], mode: Optional[str] = None) -> list[dict]:
    if not signals:
        return []
    if os.getenv("NB_RESEARCH_PUBLISH_ENABLED", "false").lower() != "true":
        log.info("Publishing disabled — skipping Stage 11")
        return []

    max_signals = int(os.getenv("NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN", "1"))
    signals = signals[:max_signals]
    mode = mode or os.getenv("NB_PUBLISH_MODE", "live")
    pkg_map = {p.get("SIGNAL_ID"): p for p in packages}
    reports = []

    # Load active strategy once — used for cta_mode and strategy context injection
    active_strategy  = load_active_strategy()
    strategy_cta     = get_cta_mode(active_strategy)
    strategy_context = get_strategy_context(active_strategy)
    log.info("Strategy context: id=%s cta_mode=%s", strategy_context.get("strategy_id"), strategy_cta)

    for signal in signals:
        sig_id = signal.get("SIGNAL_ID", "unknown")
        headline = signal.get("HEADLINE", "")
        package = pkg_map.get(sig_id, {})
        pimgs = package.get("images", {}).get("platform_images", {})
        # Signal-level CTA_MODE overrides strategy (allows per-article override via content plan)
        cta_mode = str(signal.get("CTA_MODE") or strategy_cta or "none")

        # Generate and validate the entire package before the first publisher API call.
        try:
            article = generate_article(signal, cta_mode=cta_mode, strategy_context=strategy_context)
            platforms = article["platforms"]
            structured = article["structured_article"]

            blog_body = platforms["long"]["body"]
            linkedin_text = platforms["medium"]["body"]
            # Facebook gets the conversational reading adaptation, not LinkedIn's medium body.
            facebook_text = platforms["reading"]["body"]
            instagram_text = platforms["instagram"]["body"]
            threads_seq = _build_threads(structured)
            telegram_text = _build_telegram(structured)

            _validate_package({
                "blog": blog_body,
                "linkedin": linkedin_text,
                "facebook": facebook_text,
                "instagram": instagram_text,
                "telegram": telegram_text,
            }, threads_seq)
        except (ArticleGenerationError, ValueError, KeyError) as exc:
            log.error("Signal %s blocked before publishing: %s", sig_id, exc)
            reports.append({
                "signal_id": sig_id,
                "headline": headline,
                "mode": mode,
                "results": {"editorial_gate": PublishResult(
                    platform="editorial_gate", status=PublishStatus.FAILED,
                    error_message=str(exc),
                ).to_dict()},
                "generated_file": "",
            })
            continue

        source_name = signal.get("SOURCE_NAME", "")
        source_url = signal.get("SOURCE_URL", "")
        blog_body += formatting.source_line(source_name, source_url, "blog_markdown")
        linkedin_text = formatting.append_hashtags(
            formatting.bold_signature_prefix(linkedin_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url"),
            generate_hashtags(signal, "linkedin"),
        )
        facebook_text = (
            formatting.bold_signature_prefix(facebook_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url")
        )
        instagram_text = formatting.append_hashtags(
            formatting.bold_signature_prefix(instagram_text, "unicode"),
            generate_hashtags(signal, "instagram"),
        )
        # Threads has no hashtags under the platform strategy.

        draft = _build_draft(
            signal, package, blog_body, linkedin_text, facebook_text,
            instagram_text, threads_seq, telegram_text,
            pimgs.get("blog", {}).get("url") or None,
        )
        generated_path = PACKAGES_DIR / f"{sig_id}_generated.json"
        _save_generated(generated_path, sig_id, headline, blog_body, linkedin_text,
                        facebook_text, instagram_text, threads_seq, telegram_text, "")

        results: dict = {}
        wix_url = ""
        wix_post_id: Optional[str] = None
        for name, publisher in _PUBLISHERS:
            platform_img = pimgs.get(name, {}).get("url") or draft.image_url
            use_draft = _swap_image(draft, platform_img) if name in ("linkedin", "facebook", "instagram") else draft
            try:
                if name == "telegram":
                    final_telegram = _build_telegram(structured, wix_url=wix_url)
                    use_draft.telegram_text = final_telegram
                    result = publisher.publish(use_draft, mode, wix_url=wix_url)
                    telegram_text = final_telegram
                else:
                    result = publisher.publish(use_draft, mode)
                if name == "wix" and result.ok():
                    if result.url:
                        wix_url = result.url
                    if result.external_id:
                        wix_post_id = result.external_id
                result_dict = result.to_dict()
                if result.ok() and not result.url:
                    result_dict["status"] = "published_url_unavailable"
                results[name] = result_dict
            except Exception as exc:
                log.error("%s publish error: %s", name, exc)
                results[name] = PublishResult(
                    platform=name, status=PublishStatus.FAILED, error_message=str(exc)
                ).to_dict()

        _save_generated(generated_path, sig_id, headline, blog_body, linkedin_text,
                        facebook_text, instagram_text, threads_seq, telegram_text, wix_url)
        # Append to published content index (History Engine 4B.3).
        # Non-fatal: index failure must never block a completed publish.
        _pub_strategy_id = strategy_context.get("strategy_id", "")
        if not _pub_strategy_id or _pub_strategy_id == "none":
            log.warning("Published index: skipping entry for %s — no active strategy", sig_id)
        else:
            try:
                from src.strategy.history import append_published_entry
                from src.strategy.models import PublishedEntry
                # pattern_id: check all known field names used across the pipeline
                _pattern_id = (
                    signal.get("source_pattern_id")
                    or signal.get("PATTERN_ID")
                    or pkg_map.get(sig_id, {}).get("source_pattern_id")
                    or None
                )
                # Compute strategy_week from publication date and strategy start
                _strategy_week: Optional[int] = None
                if active_strategy and active_strategy.started_at:
                    _days = (datetime.now(timezone.utc).date() - active_strategy.started_at).days
                    _strategy_week = max(1, (_days // 7) + 1)
                append_published_entry(PublishedEntry(
                    content_id=sig_id,
                    strategy_id=_pub_strategy_id,
                    pattern_id=_pattern_id,
                    published_at=datetime.now(timezone.utc),
                    platform="blog",
                    url=wix_url,
                    platform_content_id=wix_post_id,
                    echo=structured.get("echo_line") or None,
                    hook=structured.get("hook", ""),
                    topic=headline,
                    cta_mode=cta_mode,
                    strategy_week=_strategy_week,
                ))
            except Exception as _index_exc:
                log.warning("Published index append failed (non-fatal): %s", _index_exc)

        reports.append({
            "signal_id": sig_id,
            "headline": headline,
            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode": mode,
            "results": results,
            "wix_url": wix_url,
            "generated_file": str(generated_path),
            "platform_images": {p: {
                "url": pimgs.get(p, {}).get("url", ""),
                "size": pimgs.get(p, {}).get("size", ""),
            } for p in ("blog", "linkedin", "facebook", "instagram", "threads", "stories")},
            "instagram_signature": not bool(structured.get("echo_line")) or bool(structured.get("echo_line") in instagram_text),
            # Telegram intentionally uses signal + implication + optional link, not Echo/signature.
            "telegram_signature": True,
            "wix_cover_image_attached": bool(draft.image_url),
            "image_design_version": package.get("images", {}).get("design_version", ""),
            "image_hook_text": package.get("images", {}).get("hook_text", ""),
            "image_visual_family": package.get("images", {}).get("visual_family", ""),
            "image_method": package.get("images", {}).get("image_method", ""),
        })

    return reports


def _swap_image(draft: DraftPackage, image_url: str) -> DraftPackage:
    return DraftPackage(
        draft_dir=draft.draft_dir, blog_title=draft.blog_title, blog_body=draft.blog_body,
        blog_meta=draft.blog_meta, linkedin_text=draft.linkedin_text,
        instagram_text=draft.instagram_text, facebook_text=draft.facebook_text,
        threads_sequence=draft.threads_sequence, telegram_text=draft.telegram_text,
        image_url=image_url, wix_slug=draft.wix_slug,
        wix_category_id=draft.wix_category_id, wix_tags=draft.wix_tags,
        metadata=draft.metadata,
    )


def _save_generated(path: Path, sig_id, headline, blog_body, linkedin, facebook,
                    instagram, threads, telegram, wix_url):
    path.write_text(json.dumps({
        "signal_id": sig_id,
        "headline": headline,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "wix_url": wix_url,
        "blog_article": blog_body,
        "linkedin_post": linkedin,
        "facebook_post": facebook,
        "instagram_caption": instagram,
        "threads_sequence": threads,
        "telegram_text": telegram,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def format_publish_summary(reports: list[dict]) -> str:
    if not reports:
        return "No signals published."
    lines = ["\n## Publishing Summary\n"]
    for report in reports:
        lines.append(f"### {report.get('headline', '')[:70]}")
        for platform, result in report.get("results", {}).items():
            status = result.get("status", "")
            error = result.get("error_message", "")
            icon = "✅" if status in ("PUBLISHED", "DRAFT_CREATED", "published_url_unavailable") else "❌"
            lines.append(f"- {icon} **{platform.title()}** {status}{' — ' + error if error else ''}")
        lines.append("")
    return "\n".join(lines)
