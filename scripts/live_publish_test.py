"""
Never Blank Pipeline — Phase 5D: Controlled Live Publish Test

Publishes one content package live across all channels in two waves.

Wave 1: Wix, Telegram, Facebook, Instagram
Wave 2: LinkedIn, Threads  (only if Wave 1 fully passes)

Preflight checks:
  1. Draft exists at data/drafts/latest/
  2. QC status is GREEN (qc_report.json)
  3. image_url.txt exists (required for Instagram + Facebook photo)

Reports saved to:
  reports/live_publish_test.json
  reports/live_publish_test.md
  reports/raw/  (per-platform raw response stubs)

Usage:
    python scripts/live_publish_test.py
    python scripts/live_publish_test.py --wave1-only   # stop after Wix/Telegram/FB/IG
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
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.wix import WixPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.telegram import TelegramPublisher

REPORTS_DIR = Path(__file__).parent.parent / "reports"
RAW_DIR     = REPORTS_DIR / "raw"
DRAFT_BASE  = Path(__file__).parent.parent / "data" / "drafts" / "latest"

WAVE1 = ["wix", "telegram", "facebook", "instagram"]
WAVE2 = ["linkedin", "threads"]

SEP  = "─" * 66
SEP2 = "═" * 66


# ── Preflight ──────────────────────────────────────────────────────────────────

def preflight(draft_dir: Path) -> tuple[bool, list[str]]:
    """
    Returns (ok, issues).
    Checks: draft exists, QC GREEN, image_url.txt present.
    """
    issues: list[str] = []

    # 1. Draft exists
    if not (draft_dir / "metadata.json").exists():
        issues.append(f"Draft not found at {draft_dir}. Run scripts/create_fixture.py or scripts/generate.py.")
        return False, issues

    meta      = json.loads((draft_dir / "metadata.json").read_text())
    blog_meta = json.loads((draft_dir / "blog_meta.json").read_text())
    title     = meta.get("title", "?")
    slug      = meta.get("wix_slug", "?")
    gen_at    = meta.get("generated_at", "?")
    platforms = meta.get("platforms", [])

    print(f"  ✓  Draft:      {title!r}")
    print(f"  ✓  Slug:       {slug}")
    print(f"  ✓  Generated:  {gen_at}")
    print(f"  ✓  Platforms:  {', '.join(platforms)}")
    print(f"  ✓  Hook:       {blog_meta.get('hook_sentence', '?')[:70]}")

    # 2. QC status
    qc_file = draft_dir / "qc_report.json"
    if qc_file.exists():
        qc = json.loads(qc_file.read_text())
        qc_status = qc.get("final_status", qc.get("overall_status", "UNKNOWN"))
        if qc_status == "GREEN":
            note = qc.get("_note", "")
            print(f"  ✓  QC status:  {qc_status}{' (' + note + ')' if note else ''}")
        else:
            issues.append(f"QC status is {qc_status!r} — must be GREEN before live publish.")
            print(f"  ✗  QC status:  {qc_status} — BLOCKED")
    else:
        issues.append("qc_report.json missing — run scripts/generate.py --qc first.")
        print(f"  ✗  QC report:  not found")

    # 3. image_url.txt
    url_file = draft_dir / "image_url.txt"
    if url_file.exists():
        image_url = url_file.read_text().strip()
        if image_url:
            print(f"  ✓  image_url:  {image_url[:80]}…")
        else:
            issues.append("image_url.txt exists but is empty. Run scripts/generate_image.py --upload.")
            print(f"  ✗  image_url:  file empty")
    else:
        issues.append("image_url.txt missing — run scripts/generate_image.py --upload first.")
        print(f"  ✗  image_url:  not found")

    return len(issues) == 0, issues


# ── Publishing ─────────────────────────────────────────────────────────────────

PUBLISHER_MAP = {
    "wix":       WixPublisher,
    "telegram":  TelegramPublisher,
    "facebook":  FacebookPublisher,
    "instagram": InstagramPublisher,
    "linkedin":  LinkedInPublisher,
    "threads":   ThreadsPublisher,
}


def publish_wave(
    channels: list[str],
    draft: DraftPackage,
    wave_label: str,
    wix_url: str = "",
) -> tuple[list[PublishResult], str]:
    """
    Publish one wave. Returns (results, wix_url_if_published).
    """
    print(f"\n{SEP}")
    print(f"  {wave_label}: {', '.join(channels)}")
    print(SEP)
    results: list[PublishResult] = []
    current_wix_url = wix_url

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
        try:
            if channel == "telegram":
                result = publisher.publish(draft, "live", wix_url=current_wix_url)
            else:
                result = publisher.publish(draft, "live")
        except Exception as exc:
            result = PublishResult(
                platform=channel,
                status=PublishStatus.FAILED,
                error_message=f"Unhandled exception: {exc}",
            )

        if channel == "wix" and result.url:
            current_wix_url = result.url

        _print_result(result)
        results.append(result)

    return results, current_wix_url


def _print_result(r: PublishResult) -> None:
    icons = {
        PublishStatus.PUBLISHED:     "✓ PUBLISHED",
        PublishStatus.DRAFT_CREATED: "◎ DRAFT",
        PublishStatus.SKIPPED:       "○ SKIPPED",
        PublishStatus.FAILED:        "✗ FAILED",
    }
    icon = icons.get(r.status, r.status.value)
    print(f"\n  {icon:<22} {r.platform.upper()}")
    if r.external_id:
        print(f"    id:     {r.external_id}")
    if r.url:
        print(f"    url:    {r.url}")
    if r.raw_response_path:
        print(f"    note:   {r.raw_response_path}")
    if r.error_message:
        print(f"    error:  {r.error_message}")


# ── Reporting ──────────────────────────────────────────────────────────────────

def save_reports(
    all_results: list[PublishResult],
    preflight_ok: bool,
    wave1_ok: bool,
    run_id: str,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    published = [r for r in all_results if r.status == PublishStatus.PUBLISHED]
    failed    = [r for r in all_results if r.status == PublishStatus.FAILED]
    skipped   = [r for r in all_results if r.status == PublishStatus.SKIPPED]

    report = {
        "run_id":       run_id,
        "generated_at": now,
        "preflight_ok": preflight_ok,
        "wave1_passed": wave1_ok,
        "summary": {
            "published": len(published),
            "failed":    len(failed),
            "skipped":   len(skipped),
        },
        "results": [r.to_dict() for r in all_results],
    }

    json_path = REPORTS_DIR / "live_publish_test.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown
    lines = [
        "# Never Blank — Phase 5D Live Publish Test",
        "",
        f"Run ID:    `{run_id}`  ",
        f"Generated: {now}  ",
        f"Preflight: {'✓ PASS' if preflight_ok else '✗ FAIL'}  ",
        f"Wave 1:    {'✓ PASS' if wave1_ok else '✗ FAIL'}  ",
        "",
        "## Results",
        "",
        "| Platform | Status | External ID | URL |",
        "|----------|--------|-------------|-----|",
    ]
    for r in all_results:
        url_md   = f"[link]({r.url})" if r.url else "—"
        ext_id   = r.external_id or "—"
        status   = r.status.value
        lines.append(f"| {r.platform} | {status} | {ext_id} | {url_md} |")

    if failed:
        lines += ["", "## Errors", ""]
        for r in failed:
            lines.append(f"- **{r.platform}**: {r.error_message}")

    if skipped:
        lines += ["", "## Skipped", ""]
        for r in skipped:
            lines.append(f"- **{r.platform}**: {r.error_message}")

    phase6_safe = len(failed) == 0
    lines += [
        "",
        "## Summary",
        "",
        f"- Published: {len(published)} — {', '.join(r.platform for r in published) or 'none'}",
        f"- Failed:    {len(failed)} — {', '.join(r.platform for r in failed) or 'none'}",
        f"- Skipped:   {len(skipped)} — {', '.join(r.platform for r in skipped) or 'none'}",
        "",
        f"**Phase 6 scheduling safe to start: {'YES' if phase6_safe else 'NO — fix failures first'}**",
        "",
        "*Source: scripts/live_publish_test.py*",
    ]

    md_path = REPORTS_DIR / "live_publish_test.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n  ✓  {json_path}")
    print(f"  ✓  {md_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5D live publish test")
    parser.add_argument("--wave1-only", action="store_true",
                        help="Stop after Wave 1 (Wix, Telegram, Facebook, Instagram)")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print(f"\n{SEP2}")
    print("║  Never Blank — Phase 5D: Controlled Live Publish Test       ║")
    print(f"║  Run ID: {run_id:<53}║")
    print(SEP2)

    # ── Preflight ──────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Preflight checks")
    print(SEP)

    draft_dir = DRAFT_BASE / "final" if (DRAFT_BASE / "final" / "metadata.json").exists() else DRAFT_BASE
    ok, issues = preflight(draft_dir)

    if not ok:
        print(f"\n  ✗  Preflight FAILED:")
        for issue in issues:
            print(f"       • {issue}")
        save_reports([], False, False, run_id)
        sys.exit(1)

    # ── Load draft ─────────────────────────────────────────────────────────────
    draft = load_draft(DRAFT_BASE)

    # ── Wave 1 ─────────────────────────────────────────────────────────────────
    wave1_results, wix_url = publish_wave(WAVE1, draft, "Wave 1", wix_url="")

    wave1_ok = all(
        r.status in (PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED)
        for r in wave1_results
    )

    print(f"\n{SEP}")
    if wave1_ok:
        print(f"  ✓  Wave 1 PASSED  ({sum(1 for r in wave1_results if r.status == PublishStatus.PUBLISHED)} published)")
    else:
        failed_w1 = [r.platform for r in wave1_results if r.status == PublishStatus.FAILED]
        print(f"  ✗  Wave 1 FAILED  — {failed_w1}")

    # ── Wave 2 ─────────────────────────────────────────────────────────────────
    wave2_results: list[PublishResult] = []

    if args.wave1_only:
        print(f"\n  --wave1-only: stopping after Wave 1.")
        wave2_results = [
            PublishResult(platform=p, status=PublishStatus.SKIPPED,
                          error_message="--wave1-only flag set")
            for p in WAVE2
        ]
    elif not wave1_ok:
        print(f"\n  Wave 2 SKIPPED — Wave 1 did not fully pass.")
        wave2_results = [
            PublishResult(platform=p, status=PublishStatus.SKIPPED,
                          error_message="Wave 1 failed — Wave 2 not attempted")
            for p in WAVE2
        ]
    else:
        wave2_results, _ = publish_wave(WAVE2, draft, "Wave 2", wix_url=wix_url)

    all_results = wave1_results + wave2_results

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  FINAL SUMMARY")
    print(SEP2)

    published = [r for r in all_results if r.status == PublishStatus.PUBLISHED]
    failed    = [r for r in all_results if r.status == PublishStatus.FAILED]
    skipped   = [r for r in all_results if r.status == PublishStatus.SKIPPED]

    print(f"\n  Published ({len(published)}):  {', '.join(r.platform for r in published) or 'none'}")
    for r in published:
        url_display = r.url or "—"
        print(f"    {r.platform:<12} id={r.external_id or '?'}  url={url_display}")

    if failed:
        print(f"\n  Failed ({len(failed)}):     {', '.join(r.platform for r in failed)}")
        for r in failed:
            print(f"    {r.platform:<12} {r.error_message}")

    if skipped:
        print(f"\n  Skipped ({len(skipped)}):    {', '.join(r.platform for r in skipped)}")

    phase6_safe = len(failed) == 0
    print(f"\n  Phase 6 scheduling safe: {'YES' if phase6_safe else 'NO — fix failures above'}")

    # ── Save reports ────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Saving reports")
    print(SEP)
    save_reports(all_results, True, wave1_ok, run_id)

    sys.exit(0 if phase6_safe else 1)


if __name__ == "__main__":
    main()
