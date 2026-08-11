"""
Never Blank — Canonical Release 1 entry point.

This script is the single authorized controlled execution path for Release 1.

Canonical call flow
-------------------
  CLI --signal-id
  → load active strategy (required)
  → load JSONL signal
  → from_jsonl_signal(...)        → ContentAssignment
  → RunContext.from_assignment()  → one RunContext per execution
  → _build_legacy_research_context()  [compatibility boundary, remove by Task #27]
  → existing generation / package path
  → validation
  → dry-run stop  OR  controlled Wix + LinkedIn publishing only

Release 1 publishing scope: Wix and LinkedIn.
Facebook, Instagram, Threads, and Telegram are excluded from this path
and reported as [skipped-not-r1].

Usage (local):
    NB_OPENAI_API_KEY=... python scripts/generate_and_publish.py --signal-id <id> [--dry-run]

Args:
    --signal-id    : SIGNAL_ID from data/research/selected_signals.jsonl or signals_active.jsonl
    --dry-run      : Generate and validate content, save _generated.json, but do NOT publish
    --from-package : Skip LLM generation — publish the existing _generated.json as-is
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.intake import ContentAssignment, from_jsonl_signal
from src.lifecycle.signal_lifecycle import ResearchContext
from src.run import ExecutionMode, RunContext
from src.analytics.blog import BlogCollector
from src.analytics.linkedin import LinkedInCollector
from src.analytics.orchestrator import run_analytics_pipeline
from src.editorial.pipeline import ArticleGenerationError, generate_article
from src.publishing import formatting
from src.publishing.base import DraftPackage
from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION
from src.publishing.hashtags import generate_hashtags
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.result import PublishStatus
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import WixPublisher
from src.strategy.history import append_published_entry
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.strategy.models import PlatformPublication, PublishedEntry
from src.strategy.validators import validate_article_for_publish
from src.utils.logger import get_logger

log = get_logger("generate_and_publish")

PACKAGES_DIR   = Path("reports/content_packages")
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
SIGNALS_FILES  = [
    Path("data/research/selected_signals.jsonl"),
    Path("data/research/signals_active.jsonl"),
]
HISTORY_FILE   = Path("strategy/published_content_index.jsonl")
SEP            = "─" * 64
_OK_STATUSES   = {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable"}


def _load_signal(signal_id: str) -> dict:
    for path in SIGNALS_FILES:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("SIGNAL_ID") == signal_id:
                    return obj
            except Exception:
                pass
    raise FileNotFoundError(
        f"Signal {signal_id!r} not found in:\n"
        + "\n".join(f"  {p}" for p in SIGNALS_FILES)
    )


def _load_package_images(signal_id: str) -> dict:
    path = PACKAGES_DIR / f"{signal_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("images", {}).get("platform_images", {})
        except Exception:
            pass
    return {}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"[\s_]+", "-", slug)[:80]


def _build_threads(structured: dict) -> list[str]:
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
        post = re.sub(r"\s+", " ", (value or "").strip())
        words = post.split()
        if len(words) > 55:
            post = " ".join(words[:55]).rstrip(" ,;:") + "."
        key = post.lower()
        if post and key not in seen:
            sequence.append(post)
            seen.add(key)
    if not 3 <= len(sequence) <= 5:
        raise ValueError(f"Threads requires 3–5 distinct posts; generated {len(sequence)}")
    return sequence


def _clean_line(value: str, max_words: int = 34) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    words = value.split()
    if len(words) <= max_words:
        return value
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _build_telegram(structured: dict, wix_url: str = "") -> str:
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
    return "\n".join(line for line in lines if line)


def _save_generated(
    path: Path,
    signal_id: str,
    headline: str,
    blog_body: str,
    linkedin: str,
    facebook: str,
    instagram: str,
    threads: list[str],
    telegram: str,
    wix_url: str,
    strategy_id: str,
    strategy_started_at: str,
) -> None:
    path.write_text(json.dumps({
        "signal_id":           signal_id,
        "headline":            headline,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "strategy_id":         strategy_id,
        "strategy_started_at": strategy_started_at,
        "wix_url":             wix_url,
        "blog_article":        blog_body,
        "linkedin_post":       linkedin,
        "facebook_post":       facebook,
        "instagram_caption":   instagram,
        "threads_sequence":    threads,
        "telegram_text":       telegram,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


# Release 1 publishing scope — only these two publishers are invoked.
_R1_PUBLISHERS = ("wix", "linkedin")
_NON_R1_PUBLISHERS = ("facebook", "instagram", "threads", "telegram")


def _build_legacy_research_context(
    assignment: ContentAssignment,
    raw_signal: dict,
) -> ResearchContext:
    """
    Compatibility boundary — converts a ContentAssignment + raw JSONL signal dict
    into the legacy ResearchContext expected by downstream pipeline stages.

    The assignment_id must match the raw signal's SIGNAL_ID.  Mismatched identifiers
    are rejected to prevent stale or unrelated signal data from being injected.

    TODO Task #27: remove this boundary once downstream stages accept
    ContentAssignment directly.
    """
    raw_signal_id = raw_signal.get("SIGNAL_ID", "")
    if assignment.assignment_id != raw_signal_id:
        raise ValueError(
            f"assignment.assignment_id {assignment.assignment_id!r} does not match "
            f"raw_signal SIGNAL_ID {raw_signal_id!r}. "
            "Mismatched identifiers are not allowed at the compatibility boundary."
        )
    return ResearchContext.from_dict(raw_signal)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate + publish one signal end-to-end")
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--dry-run",   action="store_true",
                        help="Generate and validate, save _generated.json, but do not publish")
    parser.add_argument("--from-package", action="store_true",
                        help="Skip LLM generation — publish the existing _generated.json as-is (must pass staleness check)")
    parser.add_argument("--delete-wix-post-id",
                        help="Delete this Wix post ID before publishing (use when replacing an existing post)")
    args = parser.parse_args()
    signal_id = args.signal_id

    mode = "dry-run (no publish)" if args.dry_run else ("from-package" if args.from_package else "live (LLM generate)")
    print(f"\n{SEP}")
    print("  Never Blank — Generate + Publish")
    print(f"  Signal: {signal_id}")
    print(f"  Mode:   {mode}")
    print(SEP)

    # ── 1. Load active strategy (required) ────────────────────────────────────
    print("\n[1/6] Loading active strategy…")
    active_strategy = load_active_strategy()
    if active_strategy is None:
        print("  ERROR: No active strategy found at strategy/current/strategy.json")
        print("  Cannot generate content without an active strategy.")
        return 1

    strategy_context    = get_strategy_context(active_strategy)
    cta_mode            = get_cta_mode(active_strategy)
    strategy_id         = strategy_context.get("strategy_id", "")
    strategy_started_at = str(active_strategy.started_at) if active_strategy.started_at else ""

    print(f"  ✓  strategy_id:   {strategy_id}")
    print(f"  ✓  started_at:    {strategy_started_at}")
    print(f"  ✓  cta_mode:      {cta_mode}")

    # ── 2. Load signal ─────────────────────────────────────────────────────────
    print(f"\n[2/6] Loading signal {signal_id}…")
    try:
        signal = _load_signal(signal_id)
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        return 1

    headline = signal.get("HEADLINE", signal_id)
    print(f"  ✓  Headline: {headline[:70]}")

    # ── Normalized intake + run identity ──────────────────────────────────────
    execution_mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.CONTROLLED_LIVE
    assignment = from_jsonl_signal(
        signal,
        strategy_ref=active_strategy.strategy_id,
        strategy_version=active_strategy.strategy_version,
        submitted_at=datetime.now(timezone.utc),
    )
    run_ctx = RunContext.from_assignment(assignment, execution_mode)
    print(f"  ✓  run_id:        {run_ctx.run_id}")
    print(f"  ✓  assignment_id: {run_ctx.assignment_id}")
    print(f"  ✓  execution_mode:{run_ctx.execution_mode.value}")

    # ── Compatibility boundary: ContentAssignment → legacy ResearchContext ────
    # TODO Task #27: remove once downstream stages accept ContentAssignment directly.
    rc = _build_legacy_research_context(assignment, signal)

    # Preflight: fail-closed readiness check via typed ResearchContext.
    #
    # Publish gate checks ARTICLE_READY (factual readiness) only — NOT score.
    # Score was already applied at selection time (run_daily_research.py).
    # A signal admitted to selected_signals.jsonl with ARTICLE_READY=true
    # must be publishable regardless of its SCORE_RECOMMENDED value.
    #
    # FORCE_PUBLISH_OVERRIDE bypasses factual readiness with a warning.
    # This preserves the exact semantics of the pre-Stage-1.5 preflight:
    #   blocked = (ARTICLE_READY != "true") and not force_override
    if not rc.article_ready:
        if rc.force_override:
            print(
                f"  WARNING: FORCE_PUBLISH_OVERRIDE active for {signal_id!r} "
                f"(factual_readiness={rc.factual_readiness!r}, "
                f"SOURCE_PREMISE_VERIFIED={rc.source_premise_verified}). "
                "Bypassing readiness check — ensure this signal was manually reviewed."
            )
        else:
            field_note = (
                "field absent (pre-dates readiness gate)"
                if not signal.get("ARTICLE_READY")
                else f"ARTICLE_READY={rc.article_ready!r}"
            )
            print(
                f"  ERROR: Signal {signal_id!r} blocked by preflight — {field_note} "
                f"(SOURCE_PREMISE_VERIFIED={rc.source_premise_verified}). "
                "This signal did not pass enrichment verification and cannot be published. "
                "Set FORCE_PUBLISH_OVERRIDE=true in the signal record to override."
            )
            return 1

    pimgs = _load_package_images(signal_id)
    editorial_package: dict = {"images": {"platform_images": pimgs}}
    pkg_design_version = pimgs.get("_design_version") if pimgs else None
    needs_regen = (
        not pimgs.get("blog", {}).get("url")
        or pkg_design_version != CURRENT_DESIGN_VERSION
    )

    if needs_regen:
        reason = "no pre-generated image" if not pimgs else f"stale design v{pkg_design_version} (current: v{CURRENT_DESIGN_VERSION})"
        print(f"  — {reason} — generating images for all platforms…")
        try:
            from scripts.research.prepare_content import prepare_content_packages
            pkgs = prepare_content_packages([signal])
            if pkgs:
                editorial_package = pkgs[0]
                pimgs = pkgs[0].get("images", {}).get("platform_images", {})
                blog_url = pimgs.get("blog", {}).get("url") or ""
                print(f"  ✓  Images generated: {blog_url[:60] if blog_url else '(none)'}")
            else:
                print(f"  ⚠  Image generation returned no packages — visual platforms will skip")
        except Exception as exc:
            print(f"  ⚠  Image generation failed ({exc}) — visual platforms will skip")

    blog_image_url: Optional[str] = pimgs.get("blog", {}).get("url") or None
    platform_image_urls = {
        p: (pimgs.get(p, {}).get("url") or None)
        for p in ("blog", "linkedin", "facebook", "instagram", "threads", "stories")
        if pimgs.get(p, {}).get("url")
    }
    print(f"  ✓  Blog image: {blog_image_url[:60] if blog_image_url else '— (none)'}")
    print(f"  ✓  Platform images: {list(platform_image_urls.keys())}")

    generated_path = PACKAGES_DIR / f"{signal_id}_generated.json"
    echo_line = ""

    if args.from_package:
        # ── 3a. Load existing package (skip LLM) ─────────────────────────────
        print(f"\n[3/6] Loading existing package (--from-package, no LLM)…")
        if not generated_path.exists():
            print(f"  ERROR: {generated_path} not found — run without --from-package to generate")
            return 1
        pkg = json.loads(generated_path.read_text(encoding="utf-8"))

        # Staleness check (fail-closed)
        pkg_strategy_id = pkg.get("strategy_id", "")
        if not pkg_strategy_id:
            print("  ERROR: Package has no strategy_id — cannot verify staleness")
            return 1
        if pkg_strategy_id != strategy_id:
            print(f"  ERROR: strategy_id mismatch: package={pkg_strategy_id!r} active={strategy_id!r}")
            return 1
        raw_gen_at = pkg.get("generated_at", "")
        try:
            from datetime import date
            gen_dt = datetime.fromisoformat(raw_gen_at).date() if raw_gen_at else None
        except ValueError:
            gen_dt = None
        if gen_dt is None:
            print(f"  ERROR: generated_at {raw_gen_at!r} could not be parsed")
            return 1
        strategy_start = active_strategy.started_at if active_strategy and active_strategy.started_at else None
        if strategy_start and isinstance(strategy_start, str):
            from datetime import date
            strategy_start = date.fromisoformat(strategy_start)
        if strategy_start and gen_dt < strategy_start:
            print(f"  ERROR: Package generated BEFORE active strategy started ({gen_dt} < {strategy_start})")
            return 1

        headline       = pkg.get("headline", headline)
        blog_body      = pkg.get("blog_article", "")
        linkedin_text  = pkg.get("linkedin_post", "")
        facebook_text  = pkg.get("facebook_post", "")
        instagram_text = pkg.get("instagram_caption", "")
        threads_seq    = pkg.get("threads_sequence", [])
        telegram_text  = pkg.get("telegram_text", "")
        echo_line      = pkg.get("echo_line", "")

        print(f"  ✓  headline:  {headline[:70]}")
        print(f"  ✓  blog:      {len(blog_body)} chars")
        print(f"  ✓  linkedin:  {len(linkedin_text)} chars")
        print(f"  ✓  strategy_id matches, generated_at={raw_gen_at[:10]}")
        print(f"\n  LinkedIn preview (first 400 chars):")
        print(f"  {linkedin_text[:400].replace(chr(10), chr(10)+'  ')}")

    else:
        # ── 3b. Generate content via LLM ─────────────────────────────────────
        print(f"\n[3/6] Generating content (LLM — Editorial Engine V2)…")
        print(f"  strategy context injected: strategy_id={strategy_id}")
        try:
            editorial = rc.to_editorial(editorial_package)
            article    = generate_article(
                editorial.to_legacy_dict(),
                cta_mode=cta_mode,
                strategy_context=strategy_context,
            )
            platforms  = article["platforms"]
            structured = article["structured_article"]
        except ArticleGenerationError as exc:
            print(f"  ERROR: Editorial Engine failed at stage {exc.stage!r}: {exc.original}")
            return 1

        blog_body      = platforms["long"]["body"]
        linkedin_text  = platforms["medium"]["body"]
        facebook_text  = platforms["reading"]["body"]
        instagram_text = platforms["instagram"]["body"]
        threads_seq    = _build_threads(structured)
        telegram_text  = _build_telegram(structured)
        echo_line      = structured.get("echo_line", "")

        print(f"  ✓  blog:      {len(blog_body)} chars")
        print(f"  ✓  linkedin:  {len(linkedin_text)} chars")
        print(f"  ✓  threads:   {len(threads_seq)} posts")
        print(f"\n  LinkedIn preview (first 400 chars):")
        print(f"  {linkedin_text[:400].replace(chr(10), chr(10)+'  ')}")

        # ── 4. Validate ───────────────────────────────────────────────────────
        print(f"\n[4/6] Validating generated content…")
        errors: list[str] = []
        for platform, text in [("blog", blog_body), ("linkedin", linkedin_text)]:
            try:
                validate_article_for_publish(text, platform=platform)
                print(f"  ✓  {platform} validation passed")
            except Exception as exc:
                print(f"  ✗  {platform} validation FAILED: {exc}")
                errors.append(f"{platform}: {exc}")

        if errors:
            print(f"\n  ERROR: {len(errors)} validation error(s) — not publishing")
            return 1

        # ── 5. Apply formatting + save ─────────────────────────────────────────
        source_name = signal.get("SOURCE_NAME", "")
        source_url  = signal.get("SOURCE_URL", "")
        blog_body      += formatting.source_line(source_name, source_url, "blog_markdown")
        linkedin_text   = formatting.append_hashtags(
            formatting.bold_signature_prefix(linkedin_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url"),
            generate_hashtags(signal, "linkedin"),
        )
        facebook_text   = (
            formatting.bold_signature_prefix(facebook_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url")
        )
        instagram_text  = formatting.append_hashtags(
            formatting.bold_signature_prefix(instagram_text, "unicode"),
            generate_hashtags(signal, "instagram"),
        )

        _save_generated(
            generated_path, signal_id, headline,
            blog_body, linkedin_text, facebook_text, instagram_text,
            threads_seq, telegram_text, "",
            strategy_id, strategy_started_at,
        )
        print(f"\n  ✓  Saved {generated_path}")
        print(f"       strategy_id={strategy_id}  generated_at=now")

    if args.dry_run:
        print(f"\n{SEP}")
        print("  DRY RUN — generation + validation complete, not publishing.")
        print(f"  run_id: {run_ctx.run_id}  [COMPLETE]")
        print(SEP)
        return 0

    # ── 6. Publish: Wix + LinkedIn ────────────────────────────────────────────
    print(f"\n[5/6] Publishing…")

    # Delete old Wix post if requested (e.g. when republishing with corrections)
    if args.delete_wix_post_id:
        print(f"  Deleting old Wix post {args.delete_wix_post_id}…")
        try:
            import requests
            wix_api_key  = os.getenv("NB_WIX_API_KEY", "")
            wix_site_id  = os.getenv("NB_WIX_SITE_ID", "")
            del_resp = requests.delete(
                f"https://www.wixapis.com/blog/v3/posts/{args.delete_wix_post_id}",
                headers={
                    "Authorization": wix_api_key,
                    "wix-site-id": wix_site_id,
                },
                timeout=15,
            )
            if del_resp.status_code in (200, 204):
                print(f"  ✓  Deleted Wix post {args.delete_wix_post_id}")
            else:
                print(f"  WARNING: Wix delete returned {del_resp.status_code} — continuing anyway")
        except Exception as exc:
            print(f"  WARNING: Wix delete failed ({exc}) — continuing anyway")

    wix_slug = _slugify(headline)
    draft = DraftPackage(
        draft_dir=PACKAGES_DIR,
        blog_title=headline,
        blog_body=blog_body,
        blog_meta={
            "title": headline,
            "wix_slug": wix_slug,
            "wix_category_id": os.getenv("NB_WIX_BLOG_CATEGORY_ID", ""),
            "wix_tags": [x.strip() for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",") if x.strip()],
        },
        linkedin_text=linkedin_text,
        instagram_text=instagram_text,
        facebook_text=facebook_text,
        threads_sequence=threads_seq,
        telegram_text=telegram_text,
        image_url=blog_image_url,
        platform_image_urls=platform_image_urls,
        wix_slug=wix_slug,
        wix_category_id=os.getenv("NB_WIX_BLOG_CATEGORY_ID", ""),
        wix_tags=[x.strip() for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",") if x.strip()],
        metadata={"signal_id": signal_id},
    )

    results: dict = {}
    wix_post_id: Optional[str] = None
    wix_url = ""

    # Release 1 scope: Wix and LinkedIn only.
    for name, publisher in [
        ("wix",      WixPublisher()),
        ("linkedin", LinkedInPublisher()),
    ]:
        try:
            result = publisher.publish(draft, "live")
            results[name] = result.to_dict()
            if name == "wix" and result.ok():
                wix_post_id = result.external_id
                wix_url     = result.url or ""
        except Exception as exc:
            log.error("%s publish error: %s", name, exc)
            results[name] = {
                "platform": name, "status": "FAILED",
                "error_message": str(exc), "external_id": None, "url": None,
            }

    print()
    for platform, res in results.items():
        status = res.get("status", "?")
        icon   = "✓" if status in _OK_STATUSES else "✗"
        print(f"  {icon}  {platform:<12} status={status}")
        print(f"           id={res.get('external_id') or '—'}")
        print(f"           url={(res.get('url') or '—')[:80]}")
        if res.get("error_message"):
            print(f"           error={res['error_message']}")
    print(f"  —  [skipped-not-r1] {', '.join(_NON_R1_PUBLISHERS)}")

    # Update generated JSON with final wix_url
    _save_generated(
        generated_path, signal_id, headline,
        blog_body, linkedin_text, facebook_text, instagram_text,
        threads_seq, telegram_text, wix_url,
        strategy_id, strategy_started_at,
    )

    # ── Write to History ──────────────────────────────────────────────────────
    published_at    = datetime.now(timezone.utc)
    publications: dict[str, PlatformPublication] = {}
    for pub_name, pub_dict in results.items():
        if pub_dict.get("status") in _OK_STATUSES:
            publications[pub_name] = PlatformPublication(
                platform=pub_name,
                external_id=pub_dict.get("external_id") or None,
                url=pub_dict.get("url") or "",
                published_at=published_at,
                status=pub_dict.get("status", "published").lower(),
            )

    entry = PublishedEntry(
        content_id=signal_id,
        strategy_id=strategy_id,
        published_at=published_at,
        platform="blog",
        url=wix_url,
        platform_content_id=wix_post_id,
        publications=publications,
        topic=headline,
        cta_mode=cta_mode,
        echo=echo_line or None,
        hook=structured.get("hook", "") if not args.from_package else "",
    )
    try:
        append_published_entry(entry)
        print(f"\n  ✓  History entry written (strategy_id={strategy_id})")
    except Exception as exc:
        print(f"\n  WARNING: History write failed (non-fatal): {exc}")

    # ── Run analytics ─────────────────────────────────────────────────────────
    print(f"\n[6/6] Running analytics…")
    print("  (LinkedIn analytics may return 404 immediately after publish — expected)")
    print()
    analytics_result = run_analytics_pipeline([BlogCollector(), LinkedInCollector()])
    print(analytics_result.format_summary())

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    failed = [p for p, r in results.items() if r.get("status") not in _OK_STATUSES]
    if failed:
        print(f"  PARTIAL — failed R1 channels: {failed}")
        print(f"  run_id: {run_ctx.run_id}  [FAILED]")
        print(SEP)
        return 1
    print("  DONE — Release 1 channels published (Wix + LinkedIn).")
    print(f"  Wix:     {wix_url or wix_post_id or '—'}")
    print(f"  strategy_id: {strategy_id}")
    print(f"  run_id:      {run_ctx.run_id}  [COMPLETE]")
    print(SEP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
