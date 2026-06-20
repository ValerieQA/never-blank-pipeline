"""
Never Blank Pipeline — Scheduled Publisher (Phase 6)

Checks whether a publish is due per config/schedule.yaml, then runs the
full pipeline: generate → QC → image → publish.

Usage:
    python scripts/scheduled_publish.py              # run if due, skip otherwise
    python scripts/scheduled_publish.py --force      # run immediately regardless of schedule
    python scripts/scheduled_publish.py --check-only # report whether a publish is due, then exit
"""

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml  # PyYAML

REPO_ROOT   = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "schedule.yaml"
REPORTS_DIR = REPO_ROOT / "reports"

DAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

PUBLISH_WINDOW_MINUTES = 30  # accept up to 30 min after scheduled time


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def is_due(cfg: dict, now: datetime.datetime | None = None) -> tuple[bool, str]:
    """Return (due, reason). now is in the schedule timezone if provided."""
    sched   = cfg["schedule"]
    tz      = ZoneInfo(sched["timezone"])
    now     = now or datetime.datetime.now(tz)
    day_num = now.weekday()

    allowed_days = [DAY_NAMES[d.lower()] for d in sched["days"]]
    if day_num not in allowed_days:
        day_name = now.strftime("%A")
        return False, f"Not a publish day ({day_name}); scheduled days: {', '.join(sched['days'])}"

    sched_h, sched_m = map(int, sched["time"].split(":"))
    sched_dt = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
    delta    = (now - sched_dt).total_seconds() / 60

    if delta < 0:
        return False, f"Too early — publish window opens at {sched['time']} {sched['timezone']} ({-delta:.0f} min away)"
    if delta > PUBLISH_WINDOW_MINUTES:
        return False, f"Window passed — publish was at {sched['time']} {sched['timezone']} ({delta:.0f} min ago)"

    return True, f"Due — {now.strftime('%A %Y-%m-%d %H:%M %Z')} is within the publish window"


def run_step(label: str, cmd: list[str]) -> tuple[int, str]:
    print(f"\n{'─'*60}")
    print(f"  STEP: {label}")
    print(f"  CMD : {' '.join(cmd)}")
    print(f"{'─'*60}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    rc = result.returncode
    status = "✓ OK" if rc == 0 else f"✗ FAILED (exit {rc})"
    print(f"  {status}: {label}")
    return rc, status


def build_report(steps: list[dict], publish_json_path: Path | None) -> dict:
    tz  = ZoneInfo("America/New_York")
    now = datetime.datetime.now(datetime.timezone.utc)

    publish_results = []
    if publish_json_path and publish_json_path.exists():
        with open(publish_json_path) as f:
            data = json.load(f)
        publish_results = data.get("results", [])

    return {
        "run_at":         now.isoformat(),
        "run_at_eastern": now.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z"),
        "steps":          steps,
        "publish_results": publish_results,
        "summary": {
            "steps_ok":     sum(1 for s in steps if s["rc"] == 0),
            "steps_failed": sum(1 for s in steps if s["rc"] != 0),
            "published":    sum(1 for r in publish_results if r.get("status") == "PUBLISHED"),
            "failed":       sum(1 for r in publish_results if r.get("status") == "FAILED"),
        },
    }


def write_report(report: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "scheduled_publish_report.json"
    md_path   = REPORTS_DIR / "scheduled_publish_report.md"

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    lines = [
        "# Never Blank — Scheduled Publish Report",
        "",
        f"Run at: {report['run_at_eastern']}",
        "",
        "## Pipeline Steps",
        "",
        "| Step | Result |",
        "|------|--------|",
    ]
    for s in report["steps"]:
        lines.append(f"| {s['label']} | {s['status']} |")

    if report["publish_results"]:
        lines += [
            "",
            "## Publish Results",
            "",
            "| Platform | Status | URL |",
            "|----------|--------|-----|",
        ]
        for r in report["publish_results"]:
            url = f"[link]({r['url']})" if r.get("url") else "—"
            lines.append(f"| {r['platform']} | {r['status']} | {url} |")

    summary = report["summary"]
    lines += [
        "",
        "## Summary",
        "",
        f"- Steps OK: {summary['steps_ok']} / {summary['steps_ok'] + summary['steps_failed']}",
        f"- Published: {summary['published']}",
        f"- Failed:    {summary['failed']}",
    ]

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Never Blank scheduled publisher")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--force",      action="store_true", help="Run immediately, bypassing schedule check")
    group.add_argument("--check-only", action="store_true", help="Report whether a publish is due, then exit")
    args = parser.parse_args()

    cfg       = load_config()
    due, why  = is_due(cfg)

    print(f"\nNever Blank — Scheduled Publisher")
    print(f"Schedule: {', '.join(cfg['schedule']['days'])} at {cfg['schedule']['time']} {cfg['schedule']['timezone']}")
    print(f"Due check: {why}")

    if args.check_only:
        print(f"\nStatus: {'DUE' if due else 'NOT DUE'}")
        return 0

    if not due and not args.force:
        print("\nNot due — exiting cleanly. Use --force to run immediately.")
        return 0

    if args.force:
        print("\n--force flag set — running pipeline immediately.")

    steps: list[dict] = []

    def step(label: str, cmd: list[str], abort_on_fail: bool = False) -> int:
        rc, status = run_step(label, cmd)
        steps.append({"label": label, "rc": rc, "status": status})
        if rc != 0 and abort_on_fail:
            print(f"\n✗ Aborting pipeline — {label} failed (exit {rc})")
            report = build_report(steps, None)
            write_report(report)
            sys.exit(rc)
        return rc

    python = sys.executable

    # 1. Generate content + QC
    step("Generate content + QC", [python, "scripts/generate.py", "--qc"], abort_on_fail=True)

    # 2. Generate and upload image
    step("Generate + upload image", [python, "scripts/generate_image.py", "--upload"], abort_on_fail=False)

    # 3. Publish — Wix first
    wix_rc = step("Publish Wix", [python, "scripts/publish.py", "--live", "--channels", "wix"], abort_on_fail=False)

    # 4. Social channels — each runs independently; Telegram skipped if Wix failed
    social_channels = ["linkedin", "facebook", "instagram", "threads"]
    for ch in social_channels:
        step(f"Publish {ch}", [python, "scripts/publish.py", "--live", "--channels", ch], abort_on_fail=False)

    if wix_rc == 0:
        step("Publish telegram", [python, "scripts/publish.py", "--live", "--channels", "telegram"], abort_on_fail=False)
    else:
        steps.append({"label": "Publish telegram", "rc": -1, "status": "SKIPPED (Wix failed — no article URL)"})
        print("\n  SKIPPED: telegram — Wix failed, no article URL available")

    publish_json = REPORTS_DIR / "publish_report.json"
    report = build_report(steps, publish_json)
    json_path = write_report(report)

    print(f"\n{'═'*60}")
    print(f"  Run complete: {report['run_at_eastern']}")
    print(f"  Steps OK:     {report['summary']['steps_ok']} / {report['summary']['steps_ok'] + report['summary']['steps_failed']}")
    print(f"  Published:    {report['summary']['published']}")
    print(f"  Failed:       {report['summary']['failed']}")
    print(f"  Report:       {json_path}")
    print(f"{'═'*60}\n")

    return 1 if report["summary"]["steps_failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
