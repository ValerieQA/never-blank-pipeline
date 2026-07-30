"""
Never Blank — Visibility Intelligence: Generate + Publish

State machine for visibility_queue.jsonl:
  queued → processing → published
                      ↘ published_with_errors
                      ↘ failed

Write order (for durability):
  1. Claim item (queued → processing) + commit
  2. Generate VI package
  3. Publish each platform
  4. Append immutable snapshot to visibility_history.jsonl
  5. Update queue item status
  6. Commit history + queue together

Partial success: each platform is published independently. A failure on one
platform does not retry the others. The history entry records per-platform
results. A subsequent run targeting a published_with_errors item will skip
platforms that already succeeded and retry only the failed ones.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.editorial.vi_pipeline import generate_vi_post, to_generated_package
from src.publishing.base import DraftPackage
from src.publishing.image_pipeline import ImageSpec, generate_and_upload_card
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import WixPublisher
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.strategy.models import (
    VisibilityHistoryEntry,
    VisibilityQueueItem,
)
from src.strategy.validators import validate_visibility_quota
from src.utils.logger import get_logger

log = get_logger("vi.publish")

QUEUE_FILE   = Path("data/strategy/visibility_queue.jsonl")
HISTORY_FILE = Path("data/strategy/visibility_history.jsonl")
PACKAGES_DIR = Path("reports/content_packages")
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

SEP = "─" * 60
_OK_STATUSES = {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable"}

# Items stuck in processing for longer than this are treated as abandoned.
# GitHub Actions jobs have a 20-minute timeout — 90 minutes gives 4.5× headroom
# against the longest plausible stuck-processing window before recovering.
_PROCESSING_TIMEOUT_MINUTES = 90

# HTTP status codes that indicate a transient error worth auto-retrying.
# Permanent errors (schema validation, missing credentials, 4xx except 429) are
# not retried automatically — they require manual intervention.
# TODO(future): parse HTTP status from publisher result and skip retry for permanent errors.
_TRANSIENT_ERROR_SIGNALS = frozenset({
    "429", "timeout", "timed out", "connection", "temporarily", "retry",
    "service unavailable", "503", "502", "504",
})


# ── Queue I/O ──────────────────────────────────────────────────────────────────

def _load_queue() -> list[VisibilityQueueItem]:
    if not QUEUE_FILE.exists():
        return []
    items = []
    for line in QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                items.append(VisibilityQueueItem(**json.loads(line)))
            except Exception as exc:
                log.warning("Skipping malformed queue entry: %s", exc)
    return items


def _save_queue(items: list[VisibilityQueueItem]) -> None:
    """Atomic JSONL write — temp file + os.replace."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=QUEUE_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for item in items:
                f.write(item.model_dump_json() + "\n")
        os.replace(tmp, QUEUE_FILE)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _update_item(items: list[VisibilityQueueItem], updated: VisibilityQueueItem) -> list[VisibilityQueueItem]:
    return [updated if i.id == updated.id else i for i in items]


# ── History I/O ────────────────────────────────────────────────────────────────

def _load_history_for(item_id: str) -> Optional[dict]:
    """Return the most recent history entry for item_id, or None."""
    if not HISTORY_FILE.exists():
        return None
    last = None
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("content_id") == item_id:
                last = entry
        except Exception:
            pass
    return last


def _append_history(entry: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── State machine helpers ──────────────────────────────────────────────────────

def _recover_stuck_processing(items: list[VisibilityQueueItem]) -> list[VisibilityQueueItem]:
    """Return items list after recovering any stuck processing entries.

    An item is "stuck" when it has been in `processing` state for longer than
    _PROCESSING_TIMEOUT_MINUTES. This happens when GitHub Actions is killed or
    times out after _claim_item() but before the final queue update.

    Recovery policy: if attempt_count < 3, requeue (status → queued, last_error set).
    After 3 attempts, mark failed to prevent infinite retry loops.
    Items are updated in-place; the updated list is returned for re-saving.
    """
    now = datetime.now(timezone.utc)
    recovered: list[VisibilityQueueItem] = []
    for item in items:
        if item.status != "processing":
            recovered.append(item)
            continue
        if item.processing_started_at is None:
            # No timestamp — conservatively treat as stuck
            stuck = True
        else:
            elapsed_minutes = (now - item.processing_started_at).total_seconds() / 60
            stuck = elapsed_minutes > _PROCESSING_TIMEOUT_MINUTES

        if not stuck:
            recovered.append(item)
            continue

        # Item is stuck. Decide recovery action.
        if item.attempt_count < 3:
            log.warning(
                "Recovering stuck item %s (attempt %d/3) → queued",
                item.id, item.attempt_count,
            )
            recovered.append(item.model_copy(update={
                "status": "queued",
                "last_error": f"recovered from stuck processing after {_PROCESSING_TIMEOUT_MINUTES}min (attempt {item.attempt_count})",
            }))
        else:
            log.error(
                "Item %s stuck 3 times — marking failed (manual intervention required)",
                item.id,
            )
            recovered.append(item.model_copy(update={
                "status": "failed",
                "last_error": f"exceeded 3 processing attempts without completion",
            }))
    return recovered


def _is_transient_error(error_message: Optional[str]) -> bool:
    """Return True if the error message suggests a transient failure worth auto-retrying.

    Transient: 429 / 5xx / timeout / connection issue — resolved by waiting and retrying.
    Permanent: 4xx auth / schema / missing field — must be fixed before retrying.
    When in doubt, returns False (treat as permanent — safer than infinite retry loops).
    """
    if not error_message:
        return False
    lower = error_message.lower()
    return any(signal in lower for signal in _TRANSIENT_ERROR_SIGNALS)


def _claim_item(
    items: list[VisibilityQueueItem],
    target_id: Optional[str],
) -> Optional[VisibilityQueueItem]:
    """Find the item to process and mark it processing.

    If target_id is given: must match and be in queued or published_with_errors.
    Otherwise: take first queued item.
    Returns the claimed item (already updated in items list), or None.
    """
    for item in items:
        if target_id:
            if item.id != target_id:
                continue
            if item.status not in ("queued", "published_with_errors"):
                log.warning(
                    "Item %s has status=%s — skipping (only queued/published_with_errors can be claimed)",
                    item.id, item.status,
                )
                return None
        else:
            if item.status != "queued":
                continue

        now = datetime.now(timezone.utc)
        claimed = item.model_copy(update={
            "status": "processing",
            "attempt_count": item.attempt_count + 1,
            "processing_started_at": now,
            "last_error": None,
        })
        items[:] = _update_item(items, claimed)
        return claimed

    return None


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


# ── Publishing ─────────────────────────────────────────────────────────────────

def _build_draft(package: dict, image_url: Optional[str]) -> DraftPackage:
    headline = package.get("headline", "")
    return DraftPackage(
        draft_dir=PACKAGES_DIR,
        blog_title=headline,
        blog_body=package.get("blog_article", ""),
        blog_meta={
            "title": headline,
            "wix_slug": _slugify(headline),
            "wix_category_id": os.getenv("NB_WIX_BLOG_CATEGORY_ID", ""),
            "wix_tags": [x.strip() for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",") if x.strip()],
        },
        linkedin_text=package.get("linkedin_post", ""),
        instagram_text=package.get("instagram_caption", ""),
        facebook_text=package.get("facebook_post", ""),
        threads_sequence=package.get("threads_sequence", []),
        telegram_text=package.get("telegram_text", ""),
        image_url=image_url,
        wix_slug=_slugify(headline),
        wix_category_id=os.getenv("NB_WIX_BLOG_CATEGORY_ID", ""),
        wix_tags=[x.strip() for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",") if x.strip()],
        metadata={"queue_item_id": package.get("queue_item_id", "")},
    )


def _publish_platforms(
    draft: DraftPackage,
    prior_results: dict,
    dry_run: bool,
) -> tuple[dict, str, str]:
    """Publish to all platforms. Skip platforms that already succeeded in prior_results.

    Returns (results_dict, wix_url, wix_post_id).
    """
    results = dict(prior_results)
    wix_url = ""
    wix_post_id = ""

    publishers = [
        ("wix",       WixPublisher()),
        ("linkedin",  LinkedInPublisher()),
        ("facebook",  FacebookPublisher()),
        ("instagram", InstagramPublisher()),
        ("threads",   ThreadsPublisher()),
        ("telegram",  TelegramPublisher()),
    ]

    for name, publisher in publishers:
        prior = results.get(name, {})
        if prior.get("status") in _OK_STATUSES:
            print(f"  ↩  {name:<12} already published — skipping")
            if name == "wix":
                wix_url     = prior.get("url", "")
                wix_post_id = prior.get("external_id", "")
            continue

        if dry_run:
            print(f"  ○  {name:<12} dry-run — skipped")
            results[name] = {"platform": name, "status": "SKIPPED", "error_message": "dry-run", "external_id": None, "url": None}
            continue

        try:
            result = publisher.publish(draft, "live")
            results[name] = result.to_dict()
            if name == "wix" and result.ok():
                wix_post_id = result.external_id or ""
                wix_url     = result.url or ""
        except Exception as exc:
            log.error("%s publish error: %s", name, exc)
            results[name] = {"platform": name, "status": "FAILED", "error_message": str(exc), "external_id": None, "url": None}

    return results, wix_url, wix_post_id


# ── Main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate + publish one VI post")
    parser.add_argument("--item-id", help="Specific queue item ID (default: auto-select first queued)")
    parser.add_argument("--dry-run", action="store_true", help="Generate only, do not publish")
    args = parser.parse_args(argv)

    print(f"\n{SEP}")
    print("  Never Blank — Visibility Intelligence: Generate + Publish")
    print(f"  Mode: {'dry-run' if args.dry_run else 'live'}")
    print(SEP)

    # ── 1. Load strategy ──────────────────────────────────────────────────────
    print("\n[1/8] Loading active strategy…")
    active_strategy = load_active_strategy()
    if active_strategy is None:
        print("  ERROR: No active strategy at strategy/current/strategy.json")
        return 1
    strategy_context   = get_strategy_context(active_strategy)
    cta_mode           = get_cta_mode(active_strategy)
    strategy_id        = strategy_context.get("strategy_id", "")
    strategy_started   = strategy_context.get("started_at", "")
    print(f"  ✓ Strategy: {strategy_id}")

    # ── 2. Claim item (queued → processing) ───────────────────────────────────
    print("\n[2/8] Claiming queue item…")
    items = _load_queue()
    if not items:
        print("  ERROR: visibility_queue.jsonl is empty or missing")
        return 1

    # Recover any items stuck in processing from a previous aborted run
    items = _recover_stuck_processing(items)

    claimed = _claim_item(items, args.item_id)
    if claimed is None:
        print("  Nothing to publish — no queued items found")
        return 0

    _save_queue(items)
    print(f"  ✓ Claimed: {claimed.id} — {claimed.title[:60]}")
    print(f"    category={claimed.product_category.value} format={claimed.content_format}")

    # ── 3. Quota check (warn, never block) ────────────────────────────────────
    print("\n[3/8] Quota check…")
    # Reconstruct published queue items from history snapshots (source_queue_item field)
    this_month_history: list[VisibilityQueueItem] = []
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                source = entry.get("source_queue_item")
                if source:
                    this_month_history.append(VisibilityQueueItem(**source))
            except Exception:
                pass
    # Include current candidate — check projected state after this publish
    quota_items: list[VisibilityQueueItem] = this_month_history + [claimed]
    quota_result = validate_visibility_quota(quota_items)
    if quota_result.warnings:
        for w in quota_result.warnings:
            print(f"  ⚠  {w}")
        print("  (quota warnings are advisory — publishing continues)")
    else:
        print(f"  ✓ Quota OK ({quota_result.ai_visibility_count} AI / {quota_result.brand_concept_count} Brand)")

    # ── 4. Generate VI package ────────────────────────────────────────────────
    print("\n[4/8] Generating VI content (LLM)…")
    try:
        package = generate_vi_post(claimed, strategy_context, cta_mode)
    except Exception as exc:
        log.error("Generation failed: %s", exc)
        items = _load_queue()
        failed_item = claimed.model_copy(update={"status": "failed", "last_error": str(exc)[:500]})
        _save_queue(_update_item(items, failed_item))
        print(f"  ERROR: generation failed — item marked failed\n  {exc}")
        return 1

    print(f"  ✓ Generated: {package.get('headline', '')[:60]}")

    # Save generated package to disk (for audit trail + --from-package retry)
    pkg_path = PACKAGES_DIR / f"{claimed.id}_generated.json"
    pkg_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ Package saved: {pkg_path.name}")

    # ── 5. Generate image ─────────────────────────────────────────────────────
    print("\n[5/7] Generating image…")
    image_url: Optional[str] = None
    if not args.dry_run:
        try:
            img_spec = ImageSpec(
                title        = package.get("headline", claimed.headline),
                hook_text    = package.get("hook_text", package.get("headline", "")),
                content_goal = "challenge",
                slug         = f"vi/{claimed.id}",
            )
            image_url = generate_and_upload_card(img_spec, log=print)
            print(f"  ✓ Image: {image_url[:80]}")
        except Exception as exc:
            print(f"  ⚠  Image generation failed ({exc.__class__.__name__}: {str(exc)[:200]})"
                  " — continuing without image (Facebook/Instagram will skip)")

    # ── 6. Publish platforms ──────────────────────────────────────────────────
    print("\n[6/7] Publishing platforms…")
    prior_history = _load_history_for(claimed.id)
    prior_results = prior_history.get("platform_results", {}) if prior_history else {}

    draft = _build_draft(package, image_url=image_url)
    results, wix_url, wix_post_id = _publish_platforms(draft, prior_results, args.dry_run)

    print()
    for platform, res in results.items():
        status = res.get("status", "?")
        icon   = "✓" if status in _OK_STATUSES else ("↩" if status == "SKIPPED" else "✗")
        print(f"  {icon}  {platform:<12} {status}")
        if res.get("url"):
            print(f"           url={res['url'][:80]}")
        if res.get("error_message") and res.get("error_message") != "dry-run":
            print(f"           error={res['error_message'][:120]}")

    # ── 7. Append immutable history snapshot ──────────────────────────────────
    if not args.dry_run:
        print("\n[7/8] Writing history snapshot…")
        now = datetime.now(timezone.utc)
        history_entry = {
            "content_id":       claimed.id,
            "published_at":     now.isoformat(),
            "strategy_id":      strategy_id,
            "strategy_started_at": strategy_started,
            "wix_url":          wix_url,
            "wix_post_id":      wix_post_id,
            "headline":         package.get("headline", ""),
            "vi_metadata":      package.get("vi_metadata", {}),
            "platform_results": results,
            "generated_package_path": str(pkg_path),
            "quota_warnings":   quota_result.warnings,
            "attempt_count":    claimed.attempt_count,
            "source_queue_item": claimed.model_dump(mode="json"),
        }
        _append_history(history_entry)
        print("  ✓ History appended")

        # ── 8. Update queue status ────────────────────────────────────────────
        print("\n[8/8] Updating queue status…")
        failed_platforms = [p for p, r in results.items() if r.get("status") not in _OK_STATUSES | {"SKIPPED"}]
        final_status = "published" if not failed_platforms else "published_with_errors"
        if all(r.get("status") not in _OK_STATUSES for r in results.values() if r.get("status") != "SKIPPED"):
            final_status = "failed"

        items = _load_queue()
        finished = claimed.model_copy(update={
            "status":       final_status,
            "published_at": now,
            "last_error":   f"failed platforms: {failed_platforms}" if failed_platforms else None,
        })
        _save_queue(_update_item(items, finished))
        print(f"  ✓ Queue item status: {final_status}")

        if failed_platforms:
            print(f"  ⚠  Failed platforms: {failed_platforms}")
            print("  Re-run with --item-id to retry only failed platforms")
    else:
        print("\n[7/8] Skipped (dry-run)")
        print("[8/8] Skipped (dry-run)")

    print(f"\n{SEP}")
    print(f"  Done — {claimed.id}")
    print(SEP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
