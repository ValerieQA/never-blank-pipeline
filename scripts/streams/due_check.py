#!/usr/bin/env python3
"""Is this the configured local publish window? (Issue #142)

GitHub cron fires in UTC, so a stream whose schedule is expressed in a local
timezone needs two crons — one that lands correctly under DST and one under
standard time — and something to decide which firing is the real one. That is
the convention the repository already uses for its scheduled publisher; this
is the same decision, made available to a single stream instead of a shared
weekday list.

Generic on purpose: the day, time and timezone are arguments. Nothing here
knows what Monday means, and a business publishing on Sunday at 19:00 in
Europe/Kyiv uses the same script.

Exit code 0 means "publish now"; 78 (EX_TEMPFAIL-ish, chosen so it can never
be mistaken for a real failure) means "not the window, stop cleanly".
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


NOT_DUE = 78

_DAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def is_due(
    now: datetime, *, day: str, time: str, tolerance_minutes: int = 59
) -> tuple[bool, str]:
    """Decide whether ``now`` (already in the target timezone) is the window.

    The tolerance covers the gap between the cron firing and the job actually
    starting; it never spans two crons an hour apart, so exactly one of the
    two scheduled firings can be due.
    """

    expected_day = day.strip().lower()
    if expected_day not in _DAYS:
        raise ValueError(f"unknown day: {day!r}")
    actual_day = _DAYS[now.weekday()]
    if actual_day != expected_day:
        return False, f"not a publish day ({actual_day}; configured {expected_day})"

    hour, _, minute = time.strip().partition(":")
    target = now.replace(
        hour=int(hour), minute=int(minute or 0), second=0, microsecond=0
    )
    delta = (now - target).total_seconds() / 60
    if delta < 0:
        return False, f"too early — window opens at {time} ({-delta:.0f} min away)"
    if delta > tolerance_minutes:
        return False, f"window passed — it opened at {time} ({delta:.0f} min ago)"
    return True, f"due — {now.strftime('%A %Y-%m-%d %H:%M %Z')} is in the window"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True)
    parser.add_argument("--time", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the window check (manual dispatch of a real run)",
    )
    args = parser.parse_args(argv)

    if args.force:
        print("Due check: forced — window not evaluated")
        return 0

    now = datetime.now(ZoneInfo(args.timezone))
    due, reason = is_due(now, day=args.day, time=args.time)
    print(f"Due check: {reason}")
    return 0 if due else NOT_DUE


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
