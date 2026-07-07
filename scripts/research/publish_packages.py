"""
Stage 11 — Live publishing.
For each selected signal + its content package, generate full platform content
and publish to all channels.

Voice system: docs/EDITORIAL_ENGINE_V2.md + docs/NARRATIVE_SPINE.md, via
src.editorial.pipeline.generate_article(). See that module for the full
Decision Lens Lite -> Narrative Spine -> ... -> Platform Composer sequence.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.logger import get_logger
from src.editorial.pipeline import generate_article, ArticleGenerationError
from src.publishing import formatting
from src.publishing.hashtags import generate_hashtags
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


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80]


# ── Never Blank signature helper ───────────────────────────────────────────────
#
# Not called from publish_packages() anymore — Platform Composer guarantees
# signature presence per format itself, keyed to the Editorial Engine's freshly
# generated signature rather than the (now unused for this purpose) signal field
# POSSIBLE_SIGNATURE_LINE. Kept as a tested utility (tests/test_research_pipeline.py).

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


# ── Editorial Engine V2 generation ─────────────────────────────────────────────
#
# All body text (blog + 5 platform adaptations) is produced by a single call to
# src.editorial.pipeline.generate_article(), which runs Decision Lens Lite ->
# Narrative Spine -> Hook Engine -> Reader Context -> Discovery Builder ->
# Story Assembly -> Never Blank Voice -> Platform Composer. See
# docs/EDITORIAL_ENGINE_V2.md and docs/NARRATIVE_SPINE.md.
#
# Presentation/platform-dressing (bold signature, source attribution, hashtags)
# is applied here, not inside the Editorial Engine — see src/publishing/formatting.py
# and src/publishing/hashtags.py. The article's thinking is Editorial Engine's job;
# platform dressing is the Publisher's.

def _insert_wix_url(text: str, wix_url: str, signature: str) -> str:
    """Insert the published Wix URL just before the signature line, or append
    at the end if the signature text isn't found verbatim in `text`."""
    if signature and signature in text:
        return text.replace(signature, f"{wix_url}\n\n{signature}", 1)
    return f"{text}\n\n{wix_url}"


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

        # Editorial Engine V2 — single generation pass for all 6 outputs.
        # See src/editorial/pipeline.py.
        try:
            article = generate_article(signal)
        except ArticleGenerationError as exc:
            log.error("Editorial generation failed for %s (stage=%s): %s", sig_id, exc.stage, exc)
            continue  # do not publish degraded content — skip this signal this run

        platforms = article["platforms"]
        signature = article["structured_article"].get("signature", "")

        source_name = signal.get("SOURCE_NAME", "")
        source_url  = signal.get("SOURCE_URL", "")

        wix_url   = ""

        blog_body = platforms["long"]["body"] + formatting.source_line(source_name, source_url, "blog_markdown")
        blog_body = formatting.bold_signature_prefix(blog_body, "markdown")

        linkedin_text = platforms["medium"]["body"]
        linkedin_text = formatting.bold_signature_prefix(linkedin_text, "unicode")
        linkedin_text += formatting.source_line(source_name, source_url, "bare_url")
        linkedin_text = formatting.append_hashtags(linkedin_text, generate_hashtags(signal, "linkedin"))

        facebook_text = platforms["medium"]["body"]
        facebook_text = formatting.bold_signature_prefix(facebook_text, "unicode")
        facebook_text += formatting.source_line(source_name, source_url, "bare_url")
        facebook_text = formatting.append_hashtags(facebook_text, generate_hashtags(signal, "facebook"))

        instagram_text = platforms["instagram"]["body"]
        instagram_text = formatting.bold_signature_prefix(instagram_text, "unicode")
        instagram_text = formatting.append_hashtags(instagram_text, generate_hashtags(signal, "instagram"))

        threads_body = platforms["short"]["body"]
        threads_body = formatting.bold_signature_prefix(threads_body, "unicode")
        threads_body = formatting.append_hashtags(threads_body, generate_hashtags(signal, "threads"))
        threads_seq  = [threads_body]

        # telegram_text stays unbolded/unattributed here — _insert_wix_url() below
        # matches the raw `signature` string verbatim once Wix publishes. Bold +
        # source are applied right before telegram publishes (telegram is always
        # last in _PUBLISHERS).
        telegram_text = platforms["reading"]["body"]

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
                    # regenerated with wix_url after Wix publisher ran). Bold +
                    # source attribution applied last, right before publish, so
                    # earlier `signature` string matching (_insert_wix_url) still
                    # works against the unbolded text.
                    final_telegram_text = formatting.bold_signature_prefix(telegram_text, "telegram")
                    final_telegram_text += formatting.source_line(source_name, source_url, "telegram")
                    use_draft.telegram_text = final_telegram_text
                    result = publisher.publish(use_draft, mode, wix_url=wix_url)
                else:
                    result = publisher.publish(use_draft, mode)

                if name == "wix" and result.ok() and result.url:
                    wix_url = result.url
                    # Insert the now-known Wix URL deterministically (mechanical,
                    # not creative — no need to re-run the Editorial Engine).
                    telegram_text = _insert_wix_url(telegram_text, wix_url, signature)
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

        ig_sig  = formatting.bold_unicode("Never Blank") in instagram_text
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
