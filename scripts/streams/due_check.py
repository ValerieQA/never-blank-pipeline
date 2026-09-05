#!/usr/bin/env python3
"""Should this scheduled firing publish? (Issues #142, #224)

GitHub cron fires in UTC, so a stream whose schedule is expressed in a local
timezone needs two crons — one that lands correctly under DST and one under
standard time — and something to decide which firing is the real one.

Two decisions, deliberately separate (#224)
-------------------------------------------
The original implementation answered both with one 59-minute window, and that
coupling is what broke: a window narrow enough to tell two crons an hour apart
apart is also narrow enough that a GitHub scheduling backlog silently cancels
the week's publication. Between 2026-08-28 and 2026-09-04 every firing of every
Never Blank stream arrived 3 to 10 hours late and every one was discarded, with
a green run and no artifacts.

So the two questions are now answered by two different facts:

1. **Which firing is this?** — answered from the cron that actually fired
   (``github.event.schedule``), not from the runner's clock. Its intended UTC
   instant converts to exactly one local time; the seasonal twin that maps to
   05:00 or 07:00 local is not this stream's window and stops here. This is
   exact, so no tolerance is involved at all.

2. **Is it still worth publishing?** — answered by the local calendar day.
   A firing may execute at any later time on its intended local date. Once the
   local date has advanced it is stale and publishes nothing. The owner's rule:
   a late same-day publication is better than silence, and a stale firing is
   never reinterpreted as another day's slot.

Generic on purpose: the day, time and timezone are arguments. Nothing here
knows what any particular day means, and a business publishing at 19:00 in
Europe/Kyiv uses the same script.

Every evaluation writes a scheduling-decision record when ``--decision-out`` is
given — including the ones that publish nothing, which are exactly the runs
that previously left no trace.

Exit code 0 means "publish now"; 78 (EX_TEMPFAIL-ish, chosen so it can never be
mistaken for a real failure) means "not this firing's window, stop cleanly".
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


NOT_DUE = 78

_DAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)

#: Cron counts the week from Sunday (0, and 7 again); Python's ``weekday()``
#: counts from the start of the ISO week. Pure vocabulary translation — this
#: table is the only place the two conventions meet.
_CRON_DOW_TO_PY = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}

#: Only used when a scheduled firing cannot be identified — see
#: ``_unidentified_firing``. Never used to decide staleness.
FALLBACK_TOLERANCE_MINUTES = 59

#: The firing is this stream's, and it is still its local day.
RUN = "RUN"
#: The firing is this stream's, but the local day has advanced past it.
STALE_SKIP = "STALE_SKIP"
#: The seasonal twin: this cron lands at the wrong local time today, so the
#: other one owns the window. Not stale — it was never this firing's turn.
OFF_SEASON_SKIP = "OFF_SEASON_SKIP"
#: The cron could not be identified, so the degraded fallback window decided.
#: Distinct from STALE_SKIP so the record never claims a staleness judgement
#: it did not make.
WINDOW_SKIP = "WINDOW_SKIP"
#: Manual dispatch, or any non-schedule event. The window is not evaluated.
FORCED = "FORCED"


@dataclass(frozen=True)
class SchedulingDecision:
    """Why this runner did or did not publish — the durable record.

    Written on every path, including the skips. A green workflow that published
    nothing must still be able to say which firing it was and why it stopped.
    """

    decision: str
    reason: str
    event: str
    cron: "str | None"
    stream: str
    role: "str | None"
    timezone: str
    intended_local: "str | None"
    intended_local_date: "str | None"
    actual_local: str
    actual_local_date: str

    @property
    def publishes(self) -> bool:
        return self.decision in (RUN, FORCED)


def _parse_cron(expression: str) -> "tuple[int, int, int] | None":
    """``"0 10 * * 1"`` → (minute, hour, python weekday). None if not a fixed
    weekly slot this module can reason about."""
    fields = expression.split()
    if len(fields) != 5:
        return None
    minute, hour, dom, month, dow = fields
    if dom != "*" or month != "*":
        return None
    try:
        minute_i, hour_i, dow_i = int(minute), int(hour), int(dow)
    except ValueError:
        return None
    if not (0 <= minute_i <= 59 and 0 <= hour_i <= 23 and 0 <= dow_i <= 7):
        return None
    return minute_i, hour_i, _CRON_DOW_TO_PY[dow_i]


def intended_firing(now_utc: datetime, cron: str) -> "datetime | None":
    """The most recent instant at or before ``now_utc`` that ``cron`` names.

    This is what makes a late runner able to say which publication it is: the
    delivery time is unreliable, the cron identity is not.
    """
    parsed = _parse_cron(cron)
    if parsed is None:
        return None
    minute, hour, weekday = parsed
    candidate = now_utc.astimezone(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate > now_utc:
        candidate -= timedelta(days=1)
    candidate -= timedelta(days=(candidate.weekday() - weekday) % 7)
    return candidate


def _normalize_days(day: "str | list[str] | tuple[str, ...]") -> tuple[str, ...]:
    values = (day,) if isinstance(day, str) else tuple(day)
    normalized = tuple(value.strip().lower() for value in values if str(value).strip())
    if not normalized:
        raise ValueError("no publish day configured")
    for value in normalized:
        if value not in _DAYS:
            raise ValueError(f"unknown day: {value!r}")
    return normalized


def _decide(
    *,
    now_local: datetime,
    intended_local: "datetime | None",
    days: tuple[str, ...],
    time: str,
    event: str,
    cron: "str | None",
    stream: str,
    role: "str | None",
    tz_name: str,
    reason: "str | None" = None,
    decision: "str | None" = None,
) -> SchedulingDecision:
    return SchedulingDecision(
        decision=decision or RUN,
        reason=reason or "",
        event=event,
        cron=cron,
        stream=stream,
        role=role,
        timezone=tz_name,
        intended_local=intended_local.isoformat() if intended_local else None,
        intended_local_date=intended_local.date().isoformat() if intended_local else None,
        actual_local=now_local.isoformat(),
        actual_local_date=now_local.date().isoformat(),
    )


def _unidentified_firing(
    now_local: datetime, *, days: tuple[str, ...], time: str
) -> "tuple[bool, str]":
    """Fall back to the pre-#224 exact window when the cron is unknown.

    Without the cron identity there is nothing to tell the two seasonal firings
    apart, and a widened window would publish twice. Publishing the same
    article twice is worse than missing it, so this degrades to the narrow
    window rather than to the new same-day rule. GitHub always sets
    ``github.event.schedule`` on a scheduled event, so this is a guard, not a
    path the streams take.
    """
    actual_day = _DAYS[now_local.weekday()]
    if actual_day not in days:
        return False, (
            f"not a publish day ({actual_day}; configured {', '.join(days)})"
        )
    hour, _, minute = time.strip().partition(":")
    target = now_local.replace(
        hour=int(hour), minute=int(minute or 0), second=0, microsecond=0
    )
    delta = (now_local - target).total_seconds() / 60
    if delta < 0:
        return False, f"too early — window opens at {time} ({-delta:.0f} min away)"
    if delta > FALLBACK_TOLERANCE_MINUTES:
        return False, (
            f"firing not identified (no cron on the event) and the "
            f"{FALLBACK_TOLERANCE_MINUTES}-minute fallback window has passed — "
            f"it opened at {time} ({delta:.0f} min ago)"
        )
    return True, f"firing not identified; inside the fallback window at {time}"


def evaluate(
    now: datetime,
    *,
    day: "str | list[str] | tuple[str, ...]",
    time: str,
    timezone_name: str,
    event: str = "schedule",
    cron: "str | None" = None,
    role: "str | None" = None,
    force: bool = False,
) -> SchedulingDecision:
    """Decide whether this runner publishes, and record why.

    ``now`` may be in any timezone; it is converted to ``timezone_name``.
    """
    days = _normalize_days(day)
    tz = ZoneInfo(timezone_name)
    now_local = now.astimezone(tz)
    stream = "/".join(days)
    common = dict(
        now_local=now_local, days=days, time=time, event=event, cron=cron,
        stream=stream, role=role, tz_name=timezone_name,
    )

    if force or event != "schedule":
        return _decide(
            **common, intended_local=None, decision=FORCED,
            reason=f"{event} run — the schedule window is not evaluated",
        )

    intended_utc = intended_firing(now, cron) if cron else None
    if intended_utc is None:
        due, reason = _unidentified_firing(now_local, days=days, time=time)
        return _decide(
            **common, intended_local=None,
            decision=RUN if due else WINDOW_SKIP, reason=reason,
        )

    intended_local = intended_utc.astimezone(tz)

    # 1. Which firing is this? Exact, so no tolerance is involved.
    intended_day = _DAYS[intended_local.weekday()]
    intended_time = intended_local.strftime("%H:%M")
    if intended_day not in days or intended_time != time:
        return _decide(
            **common, intended_local=intended_local, decision=OFF_SEASON_SKIP,
            reason=(
                f"cron {cron!r} lands on {intended_day} {intended_time} "
                f"{timezone_name}; this stream publishes {', '.join(days)} at "
                f"{time}. The seasonal twin owns this window today."
            ),
        )

    # 2. Is it still worth publishing? The local calendar day decides.
    if now_local.date() != intended_local.date():
        return _decide(
            **common, intended_local=intended_local, decision=STALE_SKIP,
            reason=(
                f"intended {intended_day} {intended_local.date()} at {time} "
                f"{timezone_name}, but the runner started on "
                f"{now_local.date()} — the local day has advanced, so this "
                f"firing is stale and is not republished into another slot."
            ),
        )

    late = (now_local - intended_local).total_seconds() / 60
    return _decide(
        **common, intended_local=intended_local, decision=RUN,
        reason=(
            f"{intended_day} {intended_local.date()} {time} {timezone_name} "
            f"firing, started {late:.0f} min late — still its local day."
        ),
    )


def write_decision(decision: SchedulingDecision, path: "str | Path") -> Path:
    """Persist the record. Deterministic, no model call, always written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(decision), indent=2, sort_keys=True) + "\n")
    return target


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True, action="append",
                        help="Publish day; repeat for a multi-day stream")
    parser.add_argument("--time", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--event", default="schedule",
                        help="github.event_name")
    parser.add_argument("--cron", default="",
                        help="github.event.schedule — the cron that fired")
    parser.add_argument("--role", default="", help="Editorial role, for the record")
    parser.add_argument("--decision-out", default="",
                        help="Where to write the scheduling-decision record")
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the window check (manual dispatch of a real run)",
    )
    args = parser.parse_args(argv)

    decision = evaluate(
        datetime.now(timezone.utc),
        day=args.day,
        time=args.time,
        timezone_name=args.timezone,
        event=args.event,
        cron=args.cron or None,
        role=args.role or None,
        force=args.force,
    )

    print(f"Scheduling decision: {decision.decision} — {decision.reason}")
    if decision.cron:
        print(f"  cron={decision.cron!r} intended={decision.intended_local} "
              f"actual={decision.actual_local}")
    if args.decision_out:
        written = write_decision(decision, args.decision_out)
        print(f"  record: {written}")

    return 0 if decision.publishes else NOT_DUE


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
