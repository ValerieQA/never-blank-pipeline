"""
Never Blank Pipeline — Publishing Runner (Phase 5B)

Usage:
    python scripts/publish.py --dry-run                          # validate all channels, no API calls
    python scripts/publish.py --draft-only --channels wix        # create Wix draft only
    python scripts/publish.py --live --channels telegram         # post live to Telegram
    python scripts/publish.py --live                             # post live to all channels

Modes (exactly one required):
    --dry-run     Validate payloads. No API calls. Safe.
    --draft-only  Create drafts where platform supports it (Wix). Skip others.
    --live        Publish live. Requires explicit flag.

Options:
    --channels    Comma-separated list: wix,linkedin,facebook,instagram,threads,telegram
                  Default: all channels

Default behaviour:
    If no mode flag is passed, the script exits with an error.
    This ensures no accidental live publishing.

Report output:
    reports/publish_report.json
    reports/publish_report.md
"""
import sys
import os
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.publishing.base import load_draft, DraftPackage
from src.publishing.publication_markers import (
    PUBLICATION_UNCONFIRMED,
    PublicationGuard,
    content_digest,
    destination_text,
    draft_source_signal_ids,
    proves_publication,
    refused_result,
)
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.wix import WixPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.telegram import TelegramPublisher

REPORTS_DIR = Path(__file__).parent.parent / "reports"

ALL_CHANNELS = ["wix", "linkedin", "facebook", "instagram", "threads", "telegram"]

PUBLISHER_MAP = {
    "wix":       WixPublisher,
    "linkedin":  LinkedInPublisher,
    "facebook":  FacebookPublisher,
    "instagram": InstagramPublisher,
    "threads":   ThreadsPublisher,
    "telegram":  TelegramPublisher,
}

SEP = "─" * 62


def _status_icon(status: PublishStatus) -> str:
    return {
        PublishStatus.PUBLISHED:     "✓ PUBLISHED",
        PublishStatus.DRAFT_CREATED: "◎ DRAFT",
        PublishStatus.SKIPPED:       "○ SKIPPED",
        PublishStatus.FAILED:        "✗ FAILED",
    }.get(status, status.value)


def _print_result(result: PublishResult) -> None:
    icon = _status_icon(result.status)
    print(f"  {icon:<20} {result.platform}")
    if result.url:
        print(f"             url:  {result.url}")
    if result.external_id:
        print(f"             id:   {result.external_id}")
    if result.error_message:
        print(f"             note: {result.error_message}")


def _save_reports(results: list[PublishResult], mode: str, channels: list[str]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    report = {
        "generated_at": now,
        "mode":         mode,
        "channels":     channels,
        "results":      [r.to_dict() for r in results],
        "summary": {
            "published":     sum(1 for r in results if r.status == PublishStatus.PUBLISHED),
            "draft_created": sum(1 for r in results if r.status == PublishStatus.DRAFT_CREATED),
            "skipped":       sum(1 for r in results if r.status == PublishStatus.SKIPPED),
            "failed":        sum(1 for r in results if r.status == PublishStatus.FAILED),
        },
    }

    json_path = REPORTS_DIR / "publish_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown report
    lines = [
        "# Never Blank — Publish Report",
        "",
        f"Generated: {now}  ",
        f"Mode: `{mode}`  ",
        f"Channels: {', '.join(channels)}",
        "",
        "## Results",
        "",
        "| Platform | Status | ID | URL |",
        "|----------|--------|----|-----|",
    ]
    for r in results:
        url_md  = f"[link]({r.url})" if r.url else "—"
        ext_id  = r.external_id or "—"
        status  = r.status.value
        lines.append(f"| {r.platform} | {status} | {ext_id} | {url_md} |")

    lines += [
        "",
        "## Notes",
        "",
    ]
    for r in results:
        if r.error_message:
            lines.append(f"- **{r.platform}**: {r.error_message}")

    s = report["summary"]
    lines += [
        "",
        "## Summary",
        "",
        f"- Published:     {s['published']}",
        f"- Draft created: {s['draft_created']}",
        f"- Skipped:       {s['skipped']}",
        f"- Failed:        {s['failed']}",
        "",
        "*Source: scripts/publish.py*",
    ]

    md_path = REPORTS_DIR / "publish_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  ✓  Report saved: {json_path.relative_to(Path.cwd()) if json_path.is_relative_to(Path.cwd()) else json_path}")
    print(f"  ✓  Report saved: {md_path.relative_to(Path.cwd()) if md_path.is_relative_to(Path.cwd()) else md_path}")


def run(mode: str, channels: list[str]) -> int:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║        Never Blank Pipeline — Publisher                  ║")
    print(f"║        Mode: {mode:<46}║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Load draft
    print(f"\n{SEP}")
    print("  Loading draft…")
    try:
        draft = load_draft()
    except FileNotFoundError as exc:
        print(f"\n  ✗  {exc}")
        print("  Run: python scripts/generate.py --qc")
        return 1

    print(f"  ✓  Draft: {draft.blog_title!r}")
    print(f"       dir: {draft.draft_dir}")
    print(f"     image: {draft.image_url or '(none)'}")

    print(f"\n{SEP}")
    print(f"  Running {len(channels)} channel(s): {', '.join(channels)}")
    print(SEP)

    results: list[PublishResult] = []
    wix_url: str = None

    # ── Publication marker authority (NB-00a, invariant S3-I1) ─────────────
    # Only ``live`` reaches it: a dry run makes no external call, and a Wix
    # draft is not a publication — suppressing on one could leave the article
    # permanently unpublished, the same rule the Wix idempotency scan keeps.
    #
    # This path is driven once per channel by scripts/scheduled_publish.py, so
    # each process performs one destination's transaction. The draft names its
    # own source (the manual topic the legacy generator worked from); a draft
    # that names none has no identity key, so it publishes nothing.
    guard = (
        PublicationGuard(
            source_signal_ids=draft_source_signal_ids(draft), run_id=draft.run_id
        )
        if mode == "live"
        else None
    )

    for channel in channels:
        cls = PUBLISHER_MAP.get(channel)
        if cls is None:
            results.append(PublishResult(
                platform=channel,
                status=PublishStatus.FAILED,
                error_message=f"Unknown channel '{channel}'",
            ))
            continue

        publisher = cls()

        digest = content_digest(destination_text(draft, channel))
        if guard is not None:
            decision = guard.check(channel)
            if decision.proceed:
                decision = guard.record_intent(channel, content_digest=digest)
            if not decision.proceed:
                refused = refused_result(decision, run_id=draft.run_id)
                if channel == "wix" and refused.url:
                    wix_url = refused.url
                results.append(refused)
                _print_result(refused)
                continue

        # Telegram gets the Wix URL if Wix already ran in this session
        if channel == "telegram":
            result = publisher.publish(draft, mode, wix_url=wix_url)
        else:
            result = publisher.publish(draft, mode)

        if guard is not None and proves_publication(result):
            if guard.record_marker(channel, result, content_digest=digest) is None:
                # The post exists and its marker does not. The intent stays,
                # so the next run treats the key as possibly published.
                print(f"  !  {PUBLICATION_UNCONFIRMED}: {channel} "
                      f"({guard.key(channel)})")

        # If Wix published or created a draft with a URL, pass it to Telegram
        if channel == "wix" and result.url:
            wix_url = result.url

        results.append(result)
        _print_result(result)

    print(f"\n{SEP}")
    _save_reports(results, mode, channels)

    failed = [r for r in results if r.status == PublishStatus.FAILED]
    if failed:
        print(f"\n  ✗  {len(failed)} channel(s) failed: {[r.platform for r in failed]}")
        return 1

    print(f"\n  ✓  Done ({mode})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Never Blank publishing runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run",    action="store_true")
    mode_group.add_argument("--draft-only", action="store_true")
    mode_group.add_argument("--live",       action="store_true")
    parser.add_argument(
        "--channels",
        default=",".join(ALL_CHANNELS),
        help=f"Comma-separated channels (default: all). Options: {', '.join(ALL_CHANNELS)}",
    )

    args = parser.parse_args()

    # Enforce explicit mode — no accidental publishing
    if not (args.dry_run or args.draft_only or args.live):
        parser.error(
            "You must specify a mode: --dry-run, --draft-only, or --live.\n"
            "No mode = no action. This is intentional.\n\n"
            "  Safe test:   python scripts/publish.py --dry-run\n"
            "  Wix draft:   python scripts/publish.py --draft-only --channels wix\n"
            "  Live:        python scripts/publish.py --live --channels telegram"
        )

    if args.dry_run:
        mode = "dry_run"
    elif args.draft_only:
        mode = "draft_only"
    else:
        mode = "live"

    channels = [c.strip().lower() for c in args.channels.split(",") if c.strip()]
    invalid = [c for c in channels if c not in PUBLISHER_MAP]
    if invalid:
        parser.error(f"Unknown channel(s): {invalid}. Valid: {ALL_CHANNELS}")

    sys.exit(run(mode, channels))


if __name__ == "__main__":
    main()
