#!/usr/bin/env python3
"""Check a configured local stream publish window.

Two UTC cron entries cover daylight and standard time. This generic check
allows only the firing that lands in the configured local window.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


NOT_DUE = 78
_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def is_due(
    now: datetime, *, day: str, time: str, tolerance_minutes: int = 59
) -> tuple[bool, str]:
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
        "--force",
        action="store_true",
        help="Skip the window check for a manually dispatched real run",
    )
    args = parser.parse_args(argv)

    if args.force:
        print("Due check: forced — window not evaluated")
        return 0

    now = datetime.now(ZoneInfo(args.timezone))
    due, reason = is_due(now, day=args.day, time=args.time)
    print(f"Due check: {reason}")
    return 0 if due else NOT_DUE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
