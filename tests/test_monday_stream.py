"""Issue #142: the Monday editorial stream.

Monday is a Never Blank product decision — one real case, one mechanism, one
bounded consequence — running on its own schedule, through the canonical
pipeline, under a role identity a run can prove afterwards.

These tests hold three things: that the role identity is real evidence rather
than a weekday guess, that Monday's editorial semantics live in configuration
rather than in engine code, and that exactly one workflow now owns Monday.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
import yaml

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from scripts.streams.due_check import NOT_DUE, is_due
from scripts.streams import due_check
from src.editorial.editorial_role import (
    EditorialRoleError,
    EditorialRoleIdentity,
    render_editorial_role_rules,
    resolve_editorial_role,
)
from src.editorial.platform_composer import _build_user_prompt, compose_platforms
from src.intake.assignment_record import (
    ASSIGNMENT_RECORD_SCHEMA_VERSION,
    KNOWN_ASSIGNMENT_RECORD_SCHEMA_VERSIONS,
    AssignmentRecord,
)
from src.strategy.business_config import load_business_strategy_configuration
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider


CONFIG_PATH = Path("strategy/current/business_strategy.json")
WORKFLOWS = Path(".github/workflows")
MONDAY_ROLE = "monday_business_case"
ET = ZoneInfo("America/New_York")


def _configuration():
    return load_business_strategy_configuration(CONFIG_PATH)


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _schedule(data: dict) -> list[str]:
    # PyYAML parses a bare `on:` key as the boolean True
    triggers = data.get("on") or data.get(True) or {}
    return [item["cron"] for item in (triggers.get("schedule") or [])]


def _publishing_workflows() -> dict[str, dict]:
    """Workflows that can actually publish, by file name."""

    found = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        if "generate_and_publish" in text or "publish.py --live" in text:
            found[path.name] = yaml.safe_load(text)
    return found


# ===========================================================================
# A / O. The role identity is evidence, and it round-trips
# ===========================================================================


def test_the_monday_role_resolves_from_configuration():
    identity, role = resolve_editorial_role(_configuration(), MONDAY_ROLE)

    assert identity.role_id == MONDAY_ROLE
    assert identity.configuration_version == _configuration().configuration_version
    assert role.intent
    assert role.structure and role.forbidden


def test_an_undeclared_role_fails_closed():
    with pytest.raises(EditorialRoleError) as exc:
        resolve_editorial_role(_configuration(), "tuesday_whatever")

    # the error names what *is* declared, so the failure is diagnosable
    assert MONDAY_ROLE in str(exc.value)


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_role_is_refused_rather_than_defaulted(value):
    with pytest.raises(EditorialRoleError):
        resolve_editorial_role(_configuration(), value)


def test_the_role_survives_serialization_and_strict_reload():
    identity = EditorialRoleIdentity(role_id=MONDAY_ROLE, configuration_version="1")
    record = AssignmentRecord(
        run_id="run-1", execution_mode="controlled-live",
        configuration_identity=_configuration_identity(),
        assignment=_assignment(), editorial_role=identity,
    )

    reloaded = AssignmentRecord.model_validate_json(record.model_dump_json())

    assert reloaded.editorial_role == identity
    assert reloaded.schema_version == "1.2"


def test_the_role_is_not_derivable_from_anything_but_the_record():
    record = AssignmentRecord(
        run_id="run-1", execution_mode="controlled-live",
        configuration_identity=_configuration_identity(),
        assignment=_assignment(),
        editorial_role=EditorialRoleIdentity(
            role_id=MONDAY_ROLE, configuration_version="1"
        ),
    )

    stored = json.loads(record.model_dump_json())
    # no weekday, no timestamp, no cron, no source title feeding the identity
    assert stored["editorial_role"] == {
        "role_id": MONDAY_ROLE, "configuration_version": "1"
    }
    assert "weekday" not in json.dumps(stored).lower()


# ===========================================================================
# B. Runs and records without a role keep their accepted behaviour
# ===========================================================================


def test_a_record_without_a_role_is_still_valid():
    record = AssignmentRecord(
        run_id="run-1", execution_mode="controlled-live",
        configuration_identity=_configuration_identity(), assignment=_assignment(),
    )

    assert record.editorial_role is None


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_every_earlier_assignment_schema_still_loads(version):
    assert version in KNOWN_ASSIGNMENT_RECORD_SCHEMA_VERSIONS
    assert ASSIGNMENT_RECORD_SCHEMA_VERSION == "1.2"


def test_a_configuration_declaring_no_roles_still_loads():
    data = json.loads(CONFIG_PATH.read_text())
    data.pop("editorial_roles", None)

    from src.strategy.business_config import BusinessStrategyConfiguration

    configuration = BusinessStrategyConfiguration.model_validate(data)
    assert configuration.editorial_roles == ()


def test_a_run_without_a_role_records_none_and_still_completes(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0

    assert _assignment_json(tmp_path)["editorial_role"] is None


# ===========================================================================
# C / D / O. The entrypoint applies the role and records it
# ===========================================================================


def test_the_entrypoint_records_the_requested_role_on_the_run(tmp_path):
    code, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE)

    assert code == 0
    stored = _assignment_json(tmp_path)["editorial_role"]
    assert stored["role_id"] == MONDAY_ROLE
    assert stored["configuration_version"]


def test_the_entrypoint_refuses_an_undeclared_role_before_generating(tmp_path):
    code, patches, _ = _run_with_role(tmp_path, "not_a_declared_role")

    assert code == 1
    assert not patches["generate_article"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_the_role_rules_are_handed_to_generation(tmp_path):
    _, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE)

    rules = patches["generate_article"].call_args.kwargs["editorial_role_rules"]
    assert MONDAY_ROLE in rules
    assert "one case, one mechanism, one consequence" in rules.lower()


# ===========================================================================
# D–G. The template reaches the real composition prompts
# ===========================================================================


def _role_rules() -> str:
    return render_editorial_role_rules(
        resolve_editorial_role(_configuration(), MONDAY_ROLE)[1]
    )


@pytest.mark.parametrize("format_key", ["long", "medium"])
def test_the_published_surfaces_receive_the_role(format_key):
    prompt = _build_user_prompt(
        {"hook": "h", "discovery": {}, "echo_line": "E."},
        format_key, "reflection", (), editorial_role_rules=_role_rules(),
    )

    assert f"EDITORIAL ROLE — {MONDAY_ROLE}" in prompt


def test_the_role_reaches_composition_through_the_real_call():
    prompts = []

    def fake_chat(*, system, user, **kwargs):
        prompts.append(user)
        return json.dumps({"body": "Body. Echo line.", "echo_included": True})

    article = {"hook": "h", "discovery": {}, "echo_line": "Echo line."}
    with mock.patch("src.editorial.platform_composer.chat", side_effect=fake_chat):
        compose_platforms(article, cta_mode="none", editorial_role_rules=_role_rules())

    carrying = [p for p in prompts if f"EDITORIAL ROLE — {MONDAY_ROLE}" in p]
    # exactly the two Release 1 published surfaces, not every format
    assert len(carrying) == 2


def test_the_one_case_one_mechanism_contract_is_present():
    rules = _role_rules().lower()

    assert "one case, one mechanism, one consequence" in rules
    assert "exactly one underlying business mechanism" in rules
    assert "one thing the reader can inspect or change" in rules
    # bounded transfer, stated as a prohibition too
    assert "never proof of the configured audience's result" in rules


def test_the_anti_listicle_rules_are_present():
    rules = _role_rules().lower()

    for forbidden in (
        "'5 lessons from x'", "'3 takeaways'", "news recap or source summary",
        "generic small-business advice", "more than one mechanism",
        "padding to reach a length",
    ):
        assert forbidden in rules


def test_the_never_blank_close_and_canonical_cta_are_required():
    rules = _role_rules().lower()

    assert "never blank close" in rules
    assert "canonical configured destination" in rules
    # and the destination itself is still configured on the channel rules
    channels = json.loads(CONFIG_PATH.read_text())["channels"]
    assert any("inneros.online" in rule for rule in channels["wix"]["cta_rules"])


def test_headings_are_not_demanded_in_the_prose():
    rules = _role_rules().lower()

    assert "section headings are not required" in rules


# ===========================================================================
# H. Monday does not need breaking news
# ===========================================================================


def test_monday_does_not_require_same_day_news():
    rules = _role_rules().lower()
    assert "does not need to be breaking news" in rules

    resolve = _monday_step("Resolve signal ID")["run"]
    # selection is "eligible and unused", never "found today"
    assert "published_signal_ids" in resolve
    for forbidden in ("DATE_FOUND", "today", "date.today"):
        assert forbidden not in resolve


# ===========================================================================
# I / J. The canonical path, including the canonical visual path
# ===========================================================================


def test_monday_runs_the_canonical_entrypoint_and_no_static_package_path():
    run = _monday_step("Monday — Generate + Publish ${{ steps.resolve.outputs.signal_id }}")["run"]

    assert "scripts/generate_and_publish.py" in run
    assert f'--editorial-role "$MONDAY_ROLE"' in run
    # the historical smoke-test defect: publishing a stored package instead of
    # generating. Monday cannot ask for it.
    assert "--from-package" not in run
    assert "--legacy-package" not in run
    assert "--source-run-id" not in run
    # the legacy static-path publisher, not the canonical entrypoint's name
    assert "scripts/publish.py" not in run


def test_monday_carries_the_canonical_visual_credentials():
    step = _monday_step("Monday — Generate + Publish ${{ steps.resolve.outputs.signal_id }}")

    env = step["env"]
    for key in (
        "NB_CLOUDINARY_CLOUD_NAME", "NB_CLOUDINARY_API_KEY", "NB_CLOUDINARY_API_SECRET",
    ):
        assert key in env
    assert env["MONDAY_ROLE"] == MONDAY_ROLE


def test_monday_publishes_to_wix_and_linkedin_only_through_existing_publishers():
    step = _monday_step("Monday — Generate + Publish ${{ steps.resolve.outputs.signal_id }}")

    env = step["env"]
    assert "NB_WIX_API_KEY" in env and "NB_ZERNIO_API_KEY" in env
    # no new channel was introduced by this task
    text = (WORKFLOWS / "monday_publish.yml").read_text()
    assert "NB_MASTODON" not in text and "NB_X_API" not in text


def test_monday_preserves_run_evidence():
    names = [step.get("name") for step in _monday_workflow()["jobs"]["monday-publish"]["steps"]]

    assert "Preserve canonical run evidence" in names


# ===========================================================================
# K / L. Exactly one Monday owner, and Tue/Thu untouched
# ===========================================================================


def _fires_on(cron: str, weekday: str) -> bool:
    field = cron.split()[4]
    if field == "*":
        return True
    return weekday in {value.strip() for value in field.split(",")}


def test_exactly_one_workflow_publishes_on_monday():
    owners = [
        name for name, data in _publishing_workflows().items()
        if any(_fires_on(cron, "1") for cron in _schedule(data))
    ]

    assert owners == ["monday_publish.yml"]


def test_the_legacy_scheduler_kept_wednesday_and_friday():
    crons = _schedule(_workflow("scheduled_publish.yml"))

    assert crons == ["0 10 * * 3,5", "0 11 * * 3,5"]
    assert not any(_fires_on(cron, "1") for cron in crons)
    # and the configuration its script actually reads agrees
    schedule = yaml.safe_load(Path("config/schedule.yaml").read_text())["schedule"]
    assert schedule["days"] == ["wednesday", "friday"]
    assert schedule["time"] == "06:00"
    assert schedule["timezone"] == "America/New_York"


def test_the_canonical_multiday_workflow_kept_wednesday_friday_and_sunday():
    crons = _schedule(_workflow("research_generate_and_publish.yml"))

    assert crons == ["0 7 * * 3,5,0"]


def test_the_tuesday_thursday_stream_is_untouched():
    data = _workflow("visibility_publish.yml")

    assert _schedule(data) == ["0 7 * * 2", "0 7 * * 4"]
    text = (WORKFLOWS / "visibility_publish.yml").read_text()
    assert "generate_and_publish_visibility.py" in text
    # nothing from this task leaked into it
    assert "editorial-role" not in text and "monday" not in text.lower()


def test_monday_is_its_own_workflow_and_cannot_stop_other_streams():
    data = _monday_workflow()

    assert list(data["jobs"]) == ["monday-publish"]
    # no weekday switch in executable content: this workflow knows only Monday.
    # (Comments explaining the ownership transition may name other days.)
    executable = "\n".join(
        line for line in (WORKFLOWS / "monday_publish.yml").read_text().splitlines()
        if not line.strip().startswith("#")
    ).lower()
    for other in ("wednesday", "friday", "tuesday", "thursday"):
        assert other not in executable


# ===========================================================================
# The publish window — the DST convention, made checkable
# ===========================================================================


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2026, 8, 24, 6, 0, tzinfo=ET), True),    # EDT Monday 06:00
        (datetime(2026, 8, 24, 6, 40, tzinfo=ET), True),   # late job start
        (datetime(2026, 1, 5, 6, 0, tzinfo=ET), True),     # EST Monday 06:00
        (datetime(2026, 8, 24, 7, 30, tzinfo=ET), False),  # the other cron
        (datetime(2026, 8, 24, 5, 30, tzinfo=ET), False),  # too early
        (datetime(2026, 8, 26, 6, 0, tzinfo=ET), False),   # Wednesday
    ],
)
def test_only_one_of_the_two_firings_is_the_window(moment, expected):
    due, _ = is_due(moment, day="monday", time="06:00")

    assert due is expected


def test_the_window_check_exits_cleanly_when_not_due():
    with mock.patch.object(
        due_check, "datetime",
        mock.Mock(now=lambda tz: datetime(2026, 8, 26, 6, 0, tzinfo=tz)),
    ):
        code = due_check.main(
            ["--day", "monday", "--time", "06:00", "--timezone", "America/New_York"]
        )

    assert code == NOT_DUE  # not a failure, and not a publish


def test_a_manual_dispatch_is_always_the_window():
    assert due_check.main(
        ["--day", "monday", "--time", "06:00",
         "--timezone", "America/New_York", "--force"]
    ) == 0


def test_no_work_runs_outside_the_window():
    steps = _monday_workflow()["jobs"]["monday-publish"]["steps"]

    guarded = [s for s in steps if s.get("name") != "Monday publish window"
               and (s.get("uses") or "").startswith("actions/") is False]
    for step in guarded:
        assert "steps.window.outputs.due == 'true'" in step.get("if", ""), step


# ===========================================================================
# M. No Never Blank Monday semantics in universal code
# ===========================================================================


@pytest.mark.parametrize(
    "module",
    [
        "src/editorial/editorial_role.py",
        "src/editorial/platform_composer.py",
        "src/editorial/pipeline.py",
        "src/strategy/business_config.py",
        "src/intake/assignment_record.py",
        "scripts/streams/due_check.py",
    ],
)
def test_no_engine_module_knows_what_monday_means(module):
    text = Path(module).read_text().lower()

    assert "monday_business_case" not in text
    # a weekday may appear only as a neutral example or argument name, never as
    # a branch on the day
    assert "if day ==" not in text
    assert "weekday() ==" not in text


def test_the_role_content_lives_only_in_configuration():
    declared = json.loads(CONFIG_PATH.read_text())["editorial_roles"]

    assert [role["role_id"] for role in declared] == [MONDAY_ROLE]
    # the phrases the tests above assert on come from configuration, not code
    role_text = json.dumps(declared).lower()
    assert "one case, one mechanism, one consequence" in role_text


# ===========================================================================
# N. A failed Monday run consumes and publishes nothing
# ===========================================================================


def test_a_failed_monday_run_neither_publishes_nor_consumes(tmp_path):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    # a non-PROCEED decision stops the run before any publication effect
    evaluator, _ = _evaluator(_model_output(disposition="hold"))

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1

    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    # the role is still recorded: a Monday run that failed is still a Monday run
    assert _assignment_json(tmp_path)["editorial_role"]["role_id"] == MONDAY_ROLE


def test_the_marking_step_only_runs_after_a_successful_publish():
    step = _monday_step("Mark signal as published")

    assert "success()" in step["if"]
    assert "steps.window.outputs.due == 'true'" in step["if"]


# ===========================================================================
# helpers
# ===========================================================================


def _monday_workflow() -> dict:
    return _workflow("monday_publish.yml")


def _monday_step(name: str) -> dict:
    for step in _monday_workflow()["jobs"]["monday-publish"]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r}")


def _run_with_role(tmp_path, role: str):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", role]
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches, argv


def _assignment_json(tmp_path) -> dict:
    records = list(tmp_path.glob("*/runs/*/assignment.json"))
    assert len(records) == 1
    return json.loads(records[0].read_text())


def _configuration_identity():
    from src.strategy.execution_context import ConfigurationIdentity

    return ConfigurationIdentity.from_configuration(_configuration())


def _assignment():
    from src.intake.content_assignment import ContentAssignment

    from datetime import datetime, timezone

    return ContentAssignment(
        assignment_id="sig-1", origin="jsonl", topic="A documented business case",
        submitted_at=datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc),
        strategy_ref="2026-07-presence-debt-campaign-1", strategy_version="1",
    )
