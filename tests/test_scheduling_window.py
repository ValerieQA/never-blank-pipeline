"""Issue #224: a late scheduled firing still publishes, for its own local day.

The forensic record on #159: between 2026-08-28 and 2026-09-04 GitHub delivered
every Never Blank cron 3 to 10 hours late, `due_check`'s single 59-minute
window rejected every one, and Monday, Wednesday and Friday each reported a
green run that published nothing and left no artifact behind.

One number was answering two unrelated questions. Telling two crons an hour
apart apart legitimately needs sub-hour precision; deciding whether a delayed
runner may still publish does not, and must not inherit that precision. So:

* **which firing is this** comes from the cron that actually fired, exactly —
  no tolerance at all;
* **is it still worth publishing** comes from the local calendar day.

Owner's rule, pinned here: a late same-day publication beats silence, and a
firing whose local day has passed is never reinterpreted as another day's slot.

These scenarios make no network call, no model call, and publish nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from scripts.streams import due_check
from scripts.streams.due_check import (
    FORCED,
    NOT_DUE,
    OFF_SEASON_SKIP,
    RUN,
    STALE_SKIP,
    WINDOW_SKIP,
    evaluate,
    intended_firing,
    write_decision,
)

ET = ZoneInfo("America/New_York")
TZ = "America/New_York"
WORKFLOWS = Path(".github/workflows")

#: The three streams as they are actually configured, read from the workflows
#: rather than restated here — a schedule this file merely echoed could drift
#: away from the one that runs.
MONDAY_EDT, MONDAY_EST = "17 8 * * 1", "17 9 * * 1"
WEDNESDAY_EDT, WEDNESDAY_EST = "17 8 * * 3", "17 9 * * 3"
FRIDAY_EDT, FRIDAY_EST = "17 8 * * 5", "17 9 * * 5"


def _at(local: datetime) -> datetime:
    return local.replace(tzinfo=ET)


def _decide(local: datetime, cron: str, day: str, time: str, **kwargs):
    return evaluate(
        _at(local), day=day, time=time, timezone_name=TZ, cron=cron, **kwargs
    )


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _crons(name: str) -> list[str]:
    # PyYAML parses a bare `on:` key as the boolean True.
    return [entry["cron"] for entry in _workflow(name)[True]["schedule"]]


# ===========================================================================
# The product rule: same local day publishes, the next day does not
# ===========================================================================


@pytest.mark.parametrize(
    "when, label",
    [
        (datetime(2026, 8, 31, 4, 17), "on time"),
        (datetime(2026, 8, 31, 4, 37), "+20 min"),
        (datetime(2026, 8, 31, 5, 16), "+59 min — the old cliff edge"),
        (datetime(2026, 8, 31, 10, 17), "+6 h"),
        (datetime(2026, 8, 31, 17, 45), "the delay that actually happened"),
        (datetime(2026, 8, 31, 23, 59), "one minute before local midnight"),
    ],
)
def test_a_late_monday_firing_still_publishes_on_its_own_day(when, label):
    decision = _decide(when, MONDAY_EDT, "monday", "04:17")

    assert decision.decision == RUN, label
    assert decision.publishes
    assert decision.intended_local_date == "2026-08-31"


def test_a_monday_firing_that_crosses_local_midnight_is_stale():
    decision = _decide(datetime(2026, 9, 1, 0, 1), MONDAY_EDT, "monday", "04:17")

    assert decision.decision == STALE_SKIP
    assert not decision.publishes
    # and it is still recorded as Monday's firing — never rebadged as Tuesday
    assert decision.intended_local_date == "2026-08-31"
    assert decision.actual_local_date == "2026-09-01"


def test_the_delay_that_suppressed_2026_08_31_now_publishes():
    """The exact runner clock from the forensic record, both firings."""
    active = _decide(datetime(2026, 8, 31, 13, 15), MONDAY_EDT, "monday", "04:17")
    twin = _decide(datetime(2026, 8, 31, 13, 45), MONDAY_EST, "monday", "04:17")

    assert active.decision == RUN
    assert twin.decision == OFF_SEASON_SKIP    # still exactly one publication


def test_staleness_is_the_local_day_not_an_hour_count():
    """No hidden threshold: 19h42m late runs, 1 minute later does not."""
    assert _decide(datetime(2026, 8, 31, 23, 59), MONDAY_EDT, "monday", "04:17").decision == RUN
    assert _decide(datetime(2026, 9, 1, 0, 0), MONDAY_EDT, "monday", "04:17").decision == STALE_SKIP


# ===========================================================================
# DST: which firing is this? — exact, and never both
# ===========================================================================


@pytest.mark.parametrize(
    "day, time, edt, est",
    [
        ("monday", "04:17", MONDAY_EDT, MONDAY_EST),
        ("wednesday", "04:17", WEDNESDAY_EDT, WEDNESDAY_EST),
        ("friday", "04:17", FRIDAY_EDT, FRIDAY_EST),
    ],
)
def test_exactly_one_cron_owns_the_window_in_each_season(day, time, edt, est):
    summer = {"monday": datetime(2026, 8, 31), "wednesday": datetime(2026, 8, 26),
              "friday": datetime(2026, 8, 28)}[day]
    winter = {"monday": datetime(2026, 1, 5), "wednesday": datetime(2026, 1, 7),
              "friday": datetime(2026, 1, 9)}[day]
    hour, minute = (int(part) for part in time.split(":"))

    for date, active, inactive in ((summer, edt, est), (winter, est, edt)):
        moment = date.replace(hour=hour, minute=minute)
        assert _decide(moment, active, day, time).decision == RUN
        assert _decide(moment, inactive, day, time).decision == OFF_SEASON_SKIP


def test_the_inactive_seasonal_cron_never_publishes_however_late_it_starts():
    """The staleness rule widened the day; it must not widen the season."""
    for hour in (7, 12, 18, 23):
        decision = _decide(
            datetime(2026, 8, 31, hour, 20), MONDAY_EST, "monday", "04:17"
        )
        assert decision.decision == OFF_SEASON_SKIP, hour


@pytest.mark.parametrize("date", [
    datetime(2026, 3, 9),    # the Monday after spring forward (2026-03-08)
    datetime(2026, 11, 2),   # the Monday after fall back (2026-11-01)
])
def test_dst_transition_weeks_are_deterministic(date):
    """Transitions land on Sunday at 02:00, so no publish day has an ambiguous
    04:17 — and 04:17 is clear of the transition hour in either direction.

    The invariant is exactly one publication, not a particular refusal reason:
    in a transition week the dormant cron may not have fired yet today, so its
    most recent real firing is last week's — correctly refused as stale rather
    than as off-season. Either way it publishes nothing, at any hour of the day.
    """
    for hour, minute in ((4, 17), (9, 0), (15, 0), (22, 0)):
        moment = date.replace(hour=hour, minute=minute)
        decisions = [
            _decide(moment, MONDAY_EDT, "monday", "04:17"),
            _decide(moment, MONDAY_EST, "monday", "04:17"),
        ]
        publishing = [d for d in decisions if d.publishes]
        assert len(publishing) == 1, (moment, [d.decision for d in decisions])
        assert publishing[0].intended_local_date == date.date().isoformat()


def test_the_intended_firing_is_read_from_the_cron_not_the_clock():
    """A runner hours late still resolves to its own scheduled instant."""
    late = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)   # +13 h

    assert intended_firing(late, MONDAY_EDT) == datetime(
        2026, 8, 31, 8, 17, tzinfo=timezone.utc
    )


def test_a_firing_delayed_past_utc_midnight_keeps_its_local_day():
    """22:30 local Monday is 02:30 UTC Tuesday — still Monday's publication."""
    decision = _decide(datetime(2026, 8, 31, 22, 30), MONDAY_EDT, "monday", "04:17")

    assert decision.decision == RUN
    assert decision.intended_local_date == decision.actual_local_date == "2026-08-31"


# ===========================================================================
# Wednesday and Friday carry the same semantics
# ===========================================================================


@pytest.mark.parametrize("day, time, cron, same_day, next_day", [
    ("wednesday", "04:17", WEDNESDAY_EDT,
     datetime(2026, 9, 2, 14, 51), datetime(2026, 9, 3, 0, 5)),
    ("friday", "04:17", FRIDAY_EDT,
     datetime(2026, 9, 4, 14, 51), datetime(2026, 9, 5, 0, 5)),
])
def test_every_stream_runs_late_same_day_and_skips_the_next(
    day, time, cron, same_day, next_day
):
    assert _decide(same_day, cron, day, time).decision == RUN
    assert _decide(next_day, cron, day, time).decision == STALE_SKIP


def test_the_friday_stream_uses_the_same_seam():
    """`scheduled_publish.py` had its own 30-minute window and no DST logic."""
    from scripts.scheduled_publish import evaluate_schedule, load_config

    cfg = load_config()
    late = evaluate_schedule(
        cfg, now=_at(datetime(2026, 9, 4, 14, 51)), cron=FRIDAY_EDT
    )
    stale = evaluate_schedule(
        cfg, now=_at(datetime(2026, 9, 5, 0, 5)), cron=FRIDAY_EDT
    )

    assert late.decision == RUN and late.publishes
    assert stale.decision == STALE_SKIP and not stale.publishes
    assert "PUBLISH_WINDOW_MINUTES" not in Path("scripts/scheduled_publish.py").read_text()


# ===========================================================================
# The schedules themselves
# ===========================================================================


# Monday's schedule is paused (pre-live repair); its restoration pair is pinned
# by test_the_paused_monday_schedule_documents_its_exact_restoration below.
@pytest.mark.parametrize("name, pair", [
    ("wednesday_golden.yml", (WEDNESDAY_EDT, WEDNESDAY_EST)),
    ("scheduled_publish.yml", (FRIDAY_EDT, FRIDAY_EST)),
])
def test_every_canonical_stream_fires_at_04_17_off_the_top_of_the_hour(name, pair):
    """#232: all three canonical streams on one paired UTC schedule. GitHub
    delays :00 the most, and the earlier hour leaves more of the local day for
    a delayed firing to still publish in."""
    assert _crons(name) == list(pair)
    for cron in _crons(name):
        minute, hour, _, _, _ = cron.split()
        assert minute == "17", f"{name}: {cron}"
        assert hour in ("8", "9"), f"{name}: {cron} is not the 04:17 ET pair"


def test_the_paused_monday_schedule_documents_its_exact_restoration():
    """Temporary safety control: Monday runs only by manual dispatch until the
    owner re-authorizes the schedule. The paused block keeps the exact 04:17
    pair, so restoring it cannot drift from the window seam."""
    text = (WORKFLOWS / "monday_publish.yml").read_text()
    triggers = _workflow("monday_publish.yml")[True]

    assert "schedule" not in triggers
    assert "workflow_dispatch" in triggers
    assert "SCHEDULE PAUSED" in text
    for cron in (MONDAY_EDT, MONDAY_EST):
        assert f'#     - cron: "{cron}"' in text


@pytest.mark.parametrize("name, env_key, cron_pair", [
    ("monday_publish.yml", "MONDAY_TIME", (MONDAY_EDT, MONDAY_EST)),
    ("wednesday_golden.yml", "WEDNESDAY_TIME", (WEDNESDAY_EDT, WEDNESDAY_EST)),
])
def test_the_configured_local_time_matches_the_cron_that_fires(
    name, env_key, cron_pair
):
    """The seam matches the cron's local time against this string exactly, so
    a cron edited without its config would skip the stream forever."""
    window = next(
        step for step in _workflow(name)["jobs"].popitem()[1]["steps"]
        if step.get("id") == "window"
    )
    configured = window["env"][env_key]
    day = window["env"][env_key.replace("_TIME", "_ROLE")].split("-")[2]

    seasons = {
        _decide(
            datetime(2026, 8, 26 if day == "wednesday" else 31, 12, 0),
            cron, day, configured,
        ).decision
        for cron in cron_pair
    }
    assert seasons == {RUN, OFF_SEASON_SKIP}


def test_the_friday_config_time_matches_the_friday_cron():
    from scripts.scheduled_publish import load_config

    configured = load_config()["schedule"]["time"]
    seasons = {
        _decide(datetime(2026, 8, 28, 12, 0), cron, "friday", configured).decision
        for cron in (FRIDAY_EDT, FRIDAY_EST)
    }
    assert configured == "04:17"
    assert seasons == {RUN, OFF_SEASON_SKIP}


@pytest.mark.parametrize("edt, est, summer, winter", [
    (MONDAY_EDT, MONDAY_EST, datetime(2026, 8, 31), datetime(2026, 1, 5)),
    (WEDNESDAY_EDT, WEDNESDAY_EST, datetime(2026, 8, 26), datetime(2026, 1, 7)),
    (FRIDAY_EDT, FRIDAY_EST, datetime(2026, 8, 28), datetime(2026, 1, 9)),
])
def test_the_paired_crons_land_on_04_17_local_in_their_own_season(
    edt, est, summer, winter
):
    """#232: the point of the pair is that each half is 04:17 America/New_York
    in the season it owns — the UTC hour differs, the local time does not."""
    for cron, season_date in ((edt, summer), (est, winter)):
        intended = intended_firing(
            season_date.replace(hour=23, tzinfo=ET).astimezone(timezone.utc), cron
        ).astimezone(ET)
        assert (intended.hour, intended.minute) == (4, 17), cron
        assert intended.date() == season_date.date(), cron


# ===========================================================================
# Manual dispatch is untouched
# ===========================================================================


def test_a_manual_dispatch_never_evaluates_the_window():
    for kwargs in ({"event": "workflow_dispatch"}, {"force": True}):
        decision = evaluate(
            _at(datetime(2026, 9, 5, 14, 0)), day="monday", time="04:17",
            timezone_name=TZ, cron=MONDAY_EDT, **kwargs,
        )
        assert decision.decision == FORCED
        assert decision.publishes
        assert decision.intended_local is None


def test_the_forced_cli_still_exits_zero():
    assert due_check.main(
        ["--day", "monday", "--time", "04:17", "--timezone", TZ, "--force"]
    ) == 0


def test_every_workflow_still_forces_on_manual_dispatch():
    for name in ("monday_publish.yml", "wednesday_golden.yml"):
        window = next(
            step for step in _workflow(name)["jobs"].popitem()[1]["steps"]
            if step.get("id") == "window"
        )
        assert "workflow_dispatch" in window["run"]
        assert "--force" in window["run"]


# ===========================================================================
# --check-only is a schedule check, not a forced run (#226 review)
# ===========================================================================


def test_a_saturday_manual_check_reports_not_due():
    """The regression the review caught: the workflow's check_only branch
    passes --event workflow_dispatch, which made every manual check FORCED and
    therefore DUE — on a Saturday, at midnight, always. A check that cannot say
    "no" is not a check."""
    decision = evaluate(
        _at(datetime(2026, 9, 5, 10, 0)),  # a Saturday
        day="friday", time="04:17", timezone_name=TZ,
        event="workflow_dispatch", check_only=True,
    )
    assert decision.decision != FORCED
    assert not decision.publishes
    assert "saturday" in decision.reason


def test_a_manual_check_evaluates_the_same_window_a_scheduled_run_would():
    """Same instants as the Friday seam test: check-only answers what the
    schedule would answer, it just answers it from a workflow_dispatch."""
    from scripts.scheduled_publish import evaluate_schedule, load_config

    cfg = load_config()
    late = evaluate_schedule(
        cfg, now=_at(datetime(2026, 9, 4, 14, 51)), cron=FRIDAY_EDT,
        event="workflow_dispatch", check_only=True,
    )
    saturday = evaluate_schedule(
        cfg, now=_at(datetime(2026, 9, 5, 0, 5)), cron=FRIDAY_EDT,
        event="workflow_dispatch", check_only=True,
    )

    assert late.decision == RUN and late.publishes
    assert saturday.decision == STALE_SKIP and not saturday.publishes


def test_a_forced_manual_publish_remains_forced():
    """check_only widens nothing else: --force still bypasses the window by
    explicit instruction, and a plain manual publish still forces as before."""
    forced = evaluate(
        _at(datetime(2026, 9, 5, 10, 0)), day="friday", time="04:17",
        timezone_name=TZ, event="workflow_dispatch", force=True, check_only=True,
    )
    plain_manual = evaluate(
        _at(datetime(2026, 9, 5, 10, 0)), day="friday", time="04:17",
        timezone_name=TZ, event="workflow_dispatch",
    )
    assert forced.decision == FORCED and forced.publishes
    assert plain_manual.decision == FORCED and plain_manual.publishes


def test_the_friday_workflow_check_branch_carries_no_force():
    """The workflow seam itself: the check_only branch must invoke --check-only
    with the real event name and never --force, so the fix above is actually
    reachable from the button that exposed the bug."""
    steps = _workflow("scheduled_publish.yml")["jobs"].popitem()[1]["steps"]
    run = next(s for s in steps if s["name"] == "Run scheduled publisher")["run"]
    check_branch = run.split("inputs.check_only")[1].split("else")[0]
    assert "--check-only" in check_branch
    assert "--event" in check_branch
    assert "--force" not in check_branch


# ===========================================================================
# Observability — no skip path leaves nothing behind
# ===========================================================================


def _record(tmp_path: Path, argv: list[str]) -> tuple[int, dict]:
    out = tmp_path / "decision.json"
    code = due_check.main(argv + ["--decision-out", str(out)])
    return code, json.loads(out.read_text())


REQUIRED_FIELDS = (
    "event", "cron", "stream", "role", "timezone",
    "intended_local", "intended_local_date", "actual_local", "actual_local_date",
    "decision", "reason",
)


@pytest.mark.parametrize("frozen, expected", [
    (datetime(2026, 8, 31, 13, 15, tzinfo=ET), RUN),          # late, same day
    (datetime(2026, 9, 1, 0, 30, tzinfo=ET), STALE_SKIP),     # next local day
    (datetime(2026, 8, 25, 4, 17, tzinfo=ET), STALE_SKIP),    # a Tuesday
])
def test_every_scheduled_outcome_writes_a_decision_record(
    tmp_path, monkeypatch, frozen, expected
):
    monkeypatch.setattr(
        due_check, "datetime",
        type("_Frozen", (), {"now": staticmethod(lambda tz=None: frozen)}),
    )
    code, record = _record(tmp_path, [
        "--day", "monday", "--time", "04:17", "--timezone", TZ,
        "--event", "schedule", "--cron", MONDAY_EDT,
        "--role", "never-blank-monday-documented-case",
    ])

    assert record["decision"] == expected
    assert code == (0 if expected == RUN else NOT_DUE)
    for field in REQUIRED_FIELDS:
        assert field in record, field
    assert record["cron"] == MONDAY_EDT
    assert record["role"] == "never-blank-monday-documented-case"
    assert record["timezone"] == TZ
    assert record["reason"]


def test_the_record_is_deterministic_and_needs_no_model(tmp_path, monkeypatch):
    frozen = datetime(2026, 9, 1, 3, 0, tzinfo=ET)
    monkeypatch.setattr(
        due_check, "datetime",
        type("_Frozen", (), {"now": staticmethod(lambda tz=None: frozen)}),
    )
    first = _record(tmp_path / "a", [
        "--day", "monday", "--time", "04:17", "--timezone", TZ,
        "--cron", MONDAY_EDT])[1]
    second = _record(tmp_path / "b", [
        "--day", "monday", "--time", "04:17", "--timezone", TZ,
        "--cron", MONDAY_EDT])[1]

    assert first == second
    assert "llm" not in json.dumps(first).lower()


def test_the_record_survives_a_missing_directory(tmp_path):
    decision = _decide(datetime(2026, 8, 31, 9, 0), MONDAY_EDT, "monday", "04:17")
    written = write_decision(decision, tmp_path / "deep" / "nested" / "d.json")

    assert json.loads(written.read_text())["decision"] == RUN


@pytest.mark.parametrize("name, artifact", [
    ("monday_publish.yml", "monday-scheduling-decision"),
    ("wednesday_golden.yml", "wednesday-scheduling-decision"),
    ("scheduled_publish.yml", "friday-scheduling-decision"),
])
def test_the_decision_artifact_is_uploaded_regardless_of_the_outcome(name, artifact):
    """The defect that hid this: every upload step was gated on `due`, so the
    runs that published nothing were the runs that proved nothing."""
    steps = _workflow(name)["jobs"].popitem()[1]["steps"]
    step = next(s for s in steps if s.get("with", {}).get("name") == artifact)

    condition = str(step.get("if", ""))
    assert "always()" in condition
    assert "due" not in condition, "a skipped firing must still upload its record"


@pytest.mark.parametrize("name", [
    "monday_publish.yml", "wednesday_golden.yml", "scheduled_publish.yml",
])
def test_every_stream_passes_the_firing_identity_to_the_seam(name):
    text = (WORKFLOWS / name).read_text()

    assert "github.event.schedule" in text
    assert "github.event_name" in text
    assert "--decision-out" in text


# ===========================================================================
# Regression: nothing here reaches a provider
# ===========================================================================


def test_the_seam_makes_no_call_of_any_kind():
    source = Path("scripts/streams/due_check.py").read_text()

    for forbidden in ("requests", "httpx", "openai", "llm_client",
                      "urllib.request", "subprocess"):
        assert forbidden not in source, forbidden


def test_an_unidentified_firing_falls_back_rather_than_publishing_twice():
    """Without a cron there is nothing to tell the seasonal twins apart, so the
    narrow window returns — missing an article beats publishing it twice."""
    inside = evaluate(
        _at(datetime(2026, 8, 31, 4, 40)), day="monday", time="04:17",
        timezone_name=TZ, cron=None,
    )
    outside = evaluate(
        _at(datetime(2026, 8, 31, 13, 15)), day="monday", time="04:17",
        timezone_name=TZ, cron=None,
    )

    assert inside.decision == RUN
    assert outside.decision == WINDOW_SKIP     # never mislabelled as stale
    assert "not identified" in outside.reason


@pytest.mark.parametrize("cron", ["", "nonsense", "0 10 * *", "* * * * *", "0 10 5 * 1"])
def test_an_unparseable_cron_degrades_instead_of_crashing(cron):
    decision = evaluate(
        _at(datetime(2026, 8, 31, 13, 15)), day="monday", time="04:17",
        timezone_name=TZ, cron=cron or None,
    )

    assert decision.decision == WINDOW_SKIP
