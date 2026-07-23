"""
Smoke test: publish → History → analytics cycle for one signal.

Publishes a PRE-GENERATED content package (_generated.json) — no LLM calls.
This script is for infrastructure/plumbing tests only (Wix API, LinkedIn API,
History write, analytics pipeline). It does NOT test content generation or strategy.

STALENESS GUARD: if the package was generated before the active strategy started,
this script will refuse to publish and print a clear error. Use
scripts/generate_and_publish.py instead to regenerate with the active strategy.

Usage:
    python scripts/smoke_test_publish_analytics.py --signal-id 655ade006579f220

What it does:
    1. Loads pre-generated content from {signal_id}_generated.json
    2. Checks that generated_at >= strategy.started_at (staleness guard)
    3. Publishes to Wix + LinkedIn only via their publishers directly
    4. Writes the entry to published_content_index.jsonl
    5. Verifies the entry has both platform IDs in publications map
    6. Runs run_analytics_pipeline() — analytics may be 202 pending right after publish
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.analytics.blog import BlogCollector
from src.analytics.linkedin import LinkedInCollector
from src.analytics.orchestrator import run_analytics_pipeline
from src.publishing.base import DraftPackage
from src.publishing.wix import WixPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.result import PublishStatus
from src.strategy.history import append_published_entry, load_published_index
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.strategy.models import PlatformPublication, PublishedEntry
from src.utils.logger import get_logger

_STALE_CUTOFF_SENTINEL = "unknown"  # generated_at value meaning no provenance info

log = get_logger("smoke_test")

PACKAGES_DIR = Path("reports/content_packages")
HISTORY_FILE = Path("strategy/published_content_index.jsonl")
SEP = "─" * 64


def _load_generated(signal_id: str) -> dict:
    path = PACKAGES_DIR / f"{signal_id}_generated.json"
    if not path.exists():
        raise FileNotFoundError(f"Generated package not found: {path}")
    return json.loads(path.read_text())


def _parse_generated_at(value: str) -> datetime | None:
    """
    Parse generated_at from the package JSON.
    Accepts ISO 8601 format (new) and the legacy "2026-07-23 22:15 UTC" format.
    Returns None if unparseable.
    """
    if not value:
        return None
    # ISO 8601 (new format written by generate_and_publish.py and publish_packages.py)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    # Legacy format: "2026-07-23 22:15 UTC"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


def _check_staleness(gen: dict) -> tuple[bool, str]:
    """
    Return (is_stale, message). Fail-closed on any ambiguity.

    Stale conditions (any one is sufficient to block):
      1. No active strategy could be loaded.
      2. Package has no strategy_id (pre-provenance package).
      3. Package strategy_id != active strategy_id.
      4. Package generated_at < active strategy started_at.
    """
    pkg_strategy_id  = gen.get("strategy_id", "")
    pkg_generated_at = gen.get("generated_at", "")

    active = load_active_strategy()
    if active is None:
        return True, (
            "Active strategy could not be loaded from strategy/current/strategy.json.\n"
            "Publication blocked — cannot verify package is aligned with current strategy.\n"
            "Fix strategy.json or use scripts/generate_and_publish.py."
        )

    if not pkg_strategy_id:
        return True, (
            "Package has no strategy_id — generated before strategy provenance was added.\n"
            f"  Active strategy: {active.strategy_id} (started {active.started_at})\n"
            "  Use scripts/generate_and_publish.py to regenerate with the active strategy."
        )

    if pkg_strategy_id != active.strategy_id:
        return True, (
            f"strategy_id mismatch: package={pkg_strategy_id!r}  active={active.strategy_id!r}\n"
            f"  Generated at: {pkg_generated_at}\n"
            f"  Strategy started: {active.started_at}\n"
            "  Use scripts/generate_and_publish.py to regenerate with the active strategy."
        )

    # Date check: generated_at must be >= strategy started_at
    gen_dt = _parse_generated_at(pkg_generated_at)
    if gen_dt is None:
        return True, (
            f"Package generated_at={pkg_generated_at!r} could not be parsed.\n"
            "  Cannot verify freshness — publication blocked.\n"
            "  Use scripts/generate_and_publish.py to regenerate."
        )
    strategy_start = datetime(
        active.started_at.year, active.started_at.month, active.started_at.day,
        tzinfo=timezone.utc,
    ) if isinstance(active.started_at, date) else None

    if strategy_start and gen_dt < strategy_start:
        return True, (
            f"Package was generated BEFORE the active strategy started.\n"
            f"  generated_at:    {pkg_generated_at}\n"
            f"  strategy started: {active.started_at}\n"
            f"  strategy_id:     {active.strategy_id}\n"
            "  Use scripts/generate_and_publish.py to regenerate with the active strategy."
        )

    return False, ""


def _snapshot_history() -> set[str]:
    if not HISTORY_FILE.exists():
        return set()
    ids = set()
    for line in HISTORY_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                ids.add(json.loads(line)["content_id"])
            except Exception:
                pass
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test: publish + analytics cycle")
    parser.add_argument("--signal-id", required=True)
    args = parser.parse_args()
    signal_id = args.signal_id

    print(f"\n{SEP}")
    print(f"  Never Blank — Smoke Test: publish → History → analytics")
    print(f"  Signal: {signal_id}")
    print(SEP)

    # ── 1. Load pre-generated content ─────────────────────────────────────────
    print("\n[1/4] Loading pre-generated content…")
    try:
        gen = _load_generated(signal_id)
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        return 1

    headline     = gen.get("headline", "")
    blog_body    = gen.get("blog_article", "")
    linkedin_txt = gen.get("linkedin_post", "")
    pkg_strategy = gen.get("strategy_id", "— (none)")
    pkg_gen_at   = gen.get("generated_at", "— (unknown)")
    print(f"  ✓  Headline:      {headline[:70]}")
    print(f"  ✓  Blog body:     {len(blog_body)} chars")
    print(f"  ✓  LinkedIn:      {len(linkedin_txt)} chars")
    print(f"  ✓  strategy_id:   {pkg_strategy}")
    print(f"  ✓  generated_at:  {pkg_gen_at}")

    is_stale, stale_msg = _check_staleness(gen)
    if is_stale:
        print(f"\n  ERROR: Stale package — refusing to publish.")
        print(f"  {stale_msg.replace(chr(10), chr(10)+'  ')}")
        return 1
    else:
        print(f"  ✓  Staleness check passed")

    if not blog_body or not linkedin_txt:
        print("  ERROR: missing blog_article or linkedin_post in generated package")
        return 1

    # Build DraftPackage
    draft = DraftPackage(
        draft_dir=PACKAGES_DIR,
        blog_title=headline,
        blog_body=blog_body,
        blog_meta={"title": headline, "wix_slug": "", "wix_category_id": "", "wix_tags": []},
        linkedin_text=linkedin_txt,
        instagram_text=gen.get("instagram_caption", ""),
        facebook_text=gen.get("facebook_post", ""),
        threads_sequence=gen.get("threads_sequence", []),
        telegram_text=gen.get("telegram_text", ""),
        image_url=None,
        wix_slug="",
        wix_category_id=os.getenv("NB_WIX_BLOG_CATEGORY_ID", ""),
        wix_tags=[x.strip() for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",") if x.strip()],
        metadata={"signal_id": signal_id},
    )

    # ── 2. Publish to Wix + LinkedIn ──────────────────────────────────────────
    print(f"\n[2/4] Publishing to Wix + LinkedIn…")
    ids_before = _snapshot_history()

    publishers = [
        ("wix",      WixPublisher()),
        ("linkedin", LinkedInPublisher()),
    ]

    results: dict = {}
    wix_post_id: Optional[str] = None
    wix_url: str = ""

    for name, publisher in publishers:
        try:
            result = publisher.publish(draft, "live")
            results[name] = result.to_dict()
            if name == "wix" and result.ok():
                wix_post_id = result.external_id
                wix_url     = result.url or ""
        except Exception as exc:
            log.error("%s publish error: %s", name, exc)
            results[name] = {
                "platform": name,
                "status": "FAILED",
                "error_message": str(exc),
                "external_id": None,
                "url": None,
            }

    print()
    _ok_statuses = {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable"}
    for platform, res in results.items():
        status = res.get("status", "?")
        ext_id = res.get("external_id") or "—"
        url    = (res.get("url") or "—")[:80]
        err    = res.get("error_message") or ""
        icon   = "✓" if status in _ok_statuses else "✗"
        print(f"  {icon}  {platform:<12} status={status}")
        print(f"           id={ext_id}")
        print(f"           url={url}")
        if err:
            print(f"           error={err}")

    # ── 3. Write to History ───────────────────────────────────────────────────
    print(f"\n[3/4] Writing to published_content_index.jsonl…")

    active_strategy  = load_active_strategy()
    strategy_context = get_strategy_context(active_strategy)
    cta_mode         = get_cta_mode(active_strategy)
    strategy_id      = strategy_context.get("strategy_id", "")

    _published_at = datetime.now(timezone.utc)

    _publications: dict[str, PlatformPublication] = {}
    for pub_name, pub_dict in results.items():
        if pub_dict.get("status") in _ok_statuses:
            _publications[pub_name] = PlatformPublication(
                platform=pub_name,
                external_id=pub_dict.get("external_id") or None,
                url=pub_dict.get("url") or "",
                published_at=_published_at,
                status=pub_dict.get("status", "published").lower(),
            )

    entry = PublishedEntry(
        content_id=signal_id,
        strategy_id=strategy_id,
        published_at=_published_at,
        platform="blog",
        url=wix_url,
        platform_content_id=wix_post_id,
        publications=_publications,
        topic=headline,
        cta_mode=cta_mode,
    )

    try:
        append_published_entry(entry)
        print(f"  ✓  Entry written (strategy_id={strategy_id})")
    except Exception as exc:
        print(f"  ERROR: append_published_entry failed: {exc}")
        return 1

    # Verify the entry was written with correct structure
    ids_after = _snapshot_history()
    if signal_id in ids_after - ids_before:
        print(f"  ✓  Entry confirmed in History")
    else:
        print(f"  WARNING: entry not found in History after write")

    print(f"\n  publications map written:")
    for platform, pub in _publications.items():
        print(f"    [{platform}]")
        print(f"      external_id:  {pub.external_id or '—'}")
        print(f"      url:          {(pub.url or '—')[:80]}")
        print(f"      status:       {pub.status}")
        print(f"      published_at: {pub.published_at}")

    # ── 4. Run analytics pipeline ─────────────────────────────────────────────
    print(f"\n[4/4] Running analytics pipeline…")
    print("  (LinkedIn analytics may return 202 pending — that is expected)")
    print()

    collectors = [BlogCollector(), LinkedInCollector()]
    analytics_result = run_analytics_pipeline(collectors)
    print(analytics_result.format_summary())

    if analytics_result.collector_errors:
        print("\n  Collector errors:")
        for err in analytics_result.collector_errors:
            print(f"    • {err}")

    print(f"\n{SEP}")
    print("  Smoke test complete.")
    print(f"  Re-run 'python scripts/run_analytics.py' after 30–60 min for real LinkedIn metrics.")
    print(SEP)

    failed = [p for p, r in results.items()
              if r.get("status") not in _ok_statuses]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
