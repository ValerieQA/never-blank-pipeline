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
MONDAY_ROLE = "never-blank-monday-documented-case"
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
        "role_id": MONDAY_ROLE, "configuration_version": "1",
        "decision_policy": "decision_lens",  # the identity's explicit default
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
    # a per-format mapping: the Wix article and the LinkedIn artifact each get
    # their own rendering, carrying their own surface-scoped rules
    assert set(rules) == {"long", "medium"}
    for rendering in rules.values():
        assert MONDAY_ROLE in rendering
        assert "exactly one mechanism actually visible" in rendering.lower()
    assert "sources section" in rules["long"].lower()
    assert "compact source attribution" in rules["medium"].lower()


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


def test_surface_rules_reach_their_surface_and_only_their_surface():
    role = _monday_role_object()
    wix_rendering = render_editorial_role_rules(role, surface="wix")
    linkedin_rendering = render_editorial_role_rules(role, surface="linkedin")

    assert "Sources section" in wix_rendering
    assert "compact source attribution" in linkedin_rendering
    # no cross-surface leak in either direction
    assert "compact source attribution" not in wix_rendering
    assert "Sources section" not in linkedin_rendering


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


def test_the_documented_case_contract_is_present():
    rules = _role_rules().lower()

    # verified facts, one observable mechanism, one bounded consequence
    assert "only documented, verifiable facts" in rules
    assert "exactly one mechanism actually visible" in rules
    assert "one practical question or consequence" in rules
    # the three-way separation the corrected contract demands
    assert "documented facts, the observable mechanism, and the bounded" in rules
    assert (
        "never present this company's outcome as evidence of the reader's likely result"
        in rules
    )


def test_the_anti_listicle_rules_are_present():
    rules = _role_rules().lower()

    for forbidden in (
        "'5 lessons from x'", "'3 takeaways'", "news recap or source summary",
        "generic small-business advice", "more than one mechanism",
        "padding to reach a length",
        # the corrected contract's evidence-boundary prohibitions
        "analogy represented as evidence",
        "citation used as a substitute for verification",
        "unsupported universal pattern",
        "forcing compound presence",
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


def test_the_compound_presence_lens_is_encoded_in_the_profile():
    # the corrected #142 requirement: the Monday product lens must live in the
    # Monday configuration, not lean on the pre-existing universal composer
    # prompt happening to mention it
    rules = _role_rules().lower()

    assert "compound presence lens, explicitly bounded" in rules
    assert "never as a proven law" in rules


def test_source_attribution_is_part_of_the_role():
    rules = _role_rules().lower()

    assert "source attribution" in rules
    assert "published sources" in rules


# ===========================================================================
# H. Monday does not need breaking news
# ===========================================================================


def test_monday_does_not_require_same_day_news():
    rules = _role_rules().lower()
    assert "does not need to be breaking news" in rules

    selector = Path("scripts/streams/select_eligible_signal.py").read_text()
    # selection is "eligible and unused", never "found today"
    assert "published_signal_ids" in selector or "published-path" in selector
    for forbidden in ("DATE_FOUND", "date.today"):
        assert forbidden not in selector


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
        "src/editorial/source_eligibility.py",
        "src/editorial/source_transparency.py",
        "src/editorial/platform_composer.py",
        "src/editorial/pipeline.py",
        "src/strategy/business_config.py",
        "src/intake/assignment_record.py",
        "scripts/streams/due_check.py",
        "scripts/streams/select_eligible_signal.py",
    ],
)
def test_no_engine_module_knows_what_monday_means(module):
    text = Path(module).read_text().lower()

    assert "never-blank-monday" not in text
    if module.endswith("due_check.py"):
        # the generic day gate legitimately enumerates all seven weekday names
        # as argument vocabulary; what it must not contain is any day *logic*
        assert text.count("monday") == 1  # the _DAYS tuple entry only
    else:
        assert "monday" not in text
    # a weekday may appear only as a neutral example or argument name, never as
    # a branch on the day
    assert "if day ==" not in text
    assert "weekday() ==" not in text


def test_the_role_content_lives_only_in_configuration():
    declared = json.loads(CONFIG_PATH.read_text())["editorial_roles"]

    assert [role["role_id"] for role in declared] == [MONDAY_ROLE]
    # the phrases the tests above assert on come from configuration, not code
    role_text = json.dumps(declared).lower()
    assert "one mechanism actually visible" in role_text
    assert "compound presence lens" in role_text


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


#: What the ReadyProvider fixture's single source actually is — the identities
#: a source-transparent article must reference.
FIXTURE_SOURCE_URL = "https://source.example/report"
FIXTURE_SOURCE_TITLE = "Verified report"

def _attributed_article() -> dict:
    import copy

    from tests.test_generate_and_publish import _FAKE_ARTICLE

    article = copy.deepcopy(_FAKE_ARTICLE)
    article["platforms"]["long"]["body"] = (
        f"Blog body text grounded in the case. Source: {FIXTURE_SOURCE_TITLE} "
        f"({FIXTURE_SOURCE_URL})."
    )
    article["platforms"]["medium"]["body"] = (
        f"LinkedIn body text. Case documented by {FIXTURE_SOURCE_TITLE}."
    )
    return article


def _run_with_role(tmp_path, role: str, article: dict | None = None):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", role]
    if article is None:
        article = _attributed_article()
    patches["generate_article"] = mock.MagicMock(return_value=article)
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


# ===========================================================================
# Eligibility (corrected #142): the allowed R1 Monday source class
# ===========================================================================
#
# What a deterministic test can prove here, and what it cannot: it proves the
# policy is declared, that the judgment mechanism fails closed, and that the
# selector honours verdicts — skipping ineligible candidates, stopping at an
# eligible one, and publishing nothing when none exists. It cannot prove the
# live model classifies a given real company correctly; that judgment is made
# by the production transport against the configured criteria, and the
# criteria themselves are what these tests pin.

from src.editorial.source_eligibility import (
    SourceEligibilityError,
    SourceEligibilityVerdict,
    judge_source_eligibility,
)
from scripts.streams import select_eligible_signal


SPACEX_FIXTURE = {
    "SIGNAL_ID": "4c39b34194e08b43",
    "HEADLINE": "The average SpaceX buyer post-IPO is almost under water after a two-day slide",
    "CORE_FACT": "SpaceX shares slid for two sessions after the IPO.",
    "REAL_COMPANY_EXAMPLE": "SpaceX",
    "SOURCE_NAME": "Market wire",
}

ELIGIBLE_FIXTURES = {
    "small": {
        "SIGNAL_ID": "sig-small-bakery",
        "HEADLINE": "A neighbourhood bakery doubled repeat orders after posting its baking schedule",
        "CORE_FACT": "A three-person bakery documented its weekly schedule publicly.",
        "REAL_COMPANY_EXAMPLE": "Corner bakery",
    },
    "owner_led": {
        "SIGNAL_ID": "sig-owner-led-agency",
        "HEADLINE": "An owner-led design agency published every project retro for a year",
        "CORE_FACT": "The founder runs delivery and wrote each retro personally.",
        "REAL_COMPANY_EXAMPLE": "Owner-led agency",
    },
    "early_stage": {
        "SIGNAL_ID": "sig-early-stage",
        "HEADLINE": "A two-year-old bookkeeping startup grew through weekly client teardowns",
        "CORE_FACT": "The early-stage firm documented its client acquisition path.",
        "REAL_COMPANY_EXAMPLE": "Early-stage bookkeeping firm",
    },
    "founder_stage_episode": {
        "SIGNAL_ID": "sig-founder-episode",
        "HEADLINE": "Before it was a household name, the company's founder answered every order email",
        "CORE_FACT": "The documented episode occurred while the company was founder-led and small.",
        "REAL_COMPANY_EXAMPLE": "Now-large company, founder-stage episode",
    },
}


class PolicyTransport:
    """Scripted judgment: verdicts keyed by SIGNAL_ID; records every request."""

    def __init__(self, verdicts: dict, failures: set | None = None) -> None:
        self.verdicts = verdicts
        self.failures = failures or set()
        self.requests: list[dict] = []

    def complete(self, *, instructions: str, request: str) -> str:
        payload = json.loads(request)
        self.requests.append(payload)
        signal_id = payload["source_case"].get("SIGNAL_ID", "")
        if signal_id in self.failures:
            raise RuntimeError("judgment transport failed")
        eligible, reason = self.verdicts[signal_id]
        return json.dumps({"eligible": eligible, "reason": reason})


def _monday_role_object():
    return resolve_editorial_role(_configuration(), MONDAY_ROLE)[1]


def test_the_eligibility_policy_names_the_disallowed_classes():
    criteria = " ".join(_monday_role_object().eligibility_criteria).lower()

    # the classes the correction rules out, by name — including the class the
    # current queue head belongs to
    assert "public-company/major-corporate" in criteria
    assert "only by analogy" in criteria
    assert "unknown is ineligible" in criteria
    assert "never classify an unestablished company as small" in criteria
    # and the classes it allows
    for allowed in ("small business", "owner-led", "founder-led", "early-stage"):
        assert allowed in criteria
    assert "only when the documented episode occurred" in criteria


def test_the_spacex_candidate_is_rejected_and_skipped(tmp_path):
    # under the declared policy a current public-company market story is
    # ineligible; the scripted transport applies exactly that policy
    code, audit = _select(
        tmp_path,
        [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"]],
        verdicts={
            SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case."),
            "sig-small-bakery": (True, "Documented small business."),
        },
    )

    assert code == 0
    assert audit["selected_signal_id"] == "sig-small-bakery"
    dispositions = {d["signal_id"]: d["disposition"] for d in audit["dispositions"]}
    assert dispositions[SPACEX_FIXTURE["SIGNAL_ID"]] == "ineligible"


@pytest.mark.parametrize("kind", sorted(ELIGIBLE_FIXTURES))
def test_each_eligible_class_passes_selection(tmp_path, kind):
    fixture = ELIGIBLE_FIXTURES[kind]

    code, audit = _select(
        tmp_path, [fixture],
        verdicts={fixture["SIGNAL_ID"]: (True, f"Documented {kind} case.")},
    )

    assert code == 0
    assert audit["selected_signal_id"] == fixture["SIGNAL_ID"]


def test_unknown_scale_fails_closed_at_the_judgment():
    # the judgment contract: uncertainty is ineligibility, stated in the
    # instructions the model receives
    from src.editorial.source_eligibility import _INSTRUCTIONS

    assert "Uncertainty is ineligibility" in _INSTRUCTIONS
    assert "Never manufacture, assume or infer facts" in _INSTRUCTIONS


def test_a_failed_judgment_is_a_rejection_never_an_eligibility(tmp_path):
    code, audit = _select(
        tmp_path,
        [ELIGIBLE_FIXTURES["small"], ELIGIBLE_FIXTURES["owner_led"]],
        verdicts={"sig-owner-led-agency": (True, "Documented owner-led case.")},
        failures={"sig-small-bakery"},
    )

    assert code == 0
    assert audit["selected_signal_id"] == "sig-owner-led-agency"
    dispositions = {d["signal_id"]: d["disposition"] for d in audit["dispositions"]}
    # distinguishable from a real ineligibility finding
    assert dispositions["sig-small-bakery"] == "judgment_failed"


def test_malformed_judgment_output_never_becomes_a_verdict():
    class Malformed:
        def complete(self, *, instructions, request):
            return json.dumps({"eligible": "yes", "reason": "shape is wrong"})

    with pytest.raises(SourceEligibilityError):
        judge_source_eligibility(
            ELIGIBLE_FIXTURES["small"], _monday_role_object(), Malformed()
        )


def test_eligibility_runs_before_any_canonical_stage():
    # analogy cannot enter merely because the Decision Lens could later bound
    # it: selection happens in a standalone script that never imports the
    # decision machinery, and the workflow orders it before generation
    selector = Path("scripts/streams/select_eligible_signal.py").read_text()
    assert "decision" not in selector.lower()

    steps = [s.get("name") for s in _monday_workflow()["jobs"]["monday-publish"]["steps"]]
    assert steps.index("Select eligible signal") < steps.index(
        "Monday — Generate + Publish ${{ steps.resolve.outputs.signal_id }}"
    )


def test_no_eligible_candidate_means_no_publication_attempt(tmp_path):
    code, audit = _select(
        tmp_path, [SPACEX_FIXTURE],
        verdicts={SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case.")},
    )

    assert code == select_eligible_signal.NO_ELIGIBLE
    assert audit["selected_signal_id"] is None
    # and the workflow turns exit 3 into "no signal", which every downstream
    # step is guarded on
    resolve = _monday_step("Select eligible signal")["run"]
    assert 'if [ "$RC" = "3" ]' in resolve
    for name in ("Check OpenAI secret",
                 "Monday — Generate + Publish ${{ steps.resolve.outputs.signal_id }}",
                 "Mark signal as published"):
        assert "steps.resolve.outputs.signal_id != ''" in _monday_step(name)["if"]


def test_rejected_candidates_are_not_marked_published(tmp_path):
    published = tmp_path / "published_signal_ids.txt"
    published.write_text("already-done\n")

    _select(
        tmp_path, [SPACEX_FIXTURE],
        verdicts={SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case.")},
        published=published,
    )

    # skipping is not consuming
    assert published.read_text() == "already-done\n"


def test_an_explicitly_dispatched_ineligible_signal_is_still_refused(tmp_path):
    code, audit = _select(
        tmp_path,
        [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"]],
        verdicts={
            SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case."),
            "sig-small-bakery": (True, "Documented small business."),
        },
        signal_id=SPACEX_FIXTURE["SIGNAL_ID"],
    )

    # explicitness is not a bypass — and the selector does not silently
    # substitute the eligible candidate the operator did not ask for
    assert code == select_eligible_signal.NO_ELIGIBLE
    assert audit["selected_signal_id"] is None


def test_the_audit_records_why_each_candidate_was_judged(tmp_path):
    _, audit = _select(
        tmp_path,
        [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"]],
        verdicts={
            SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case."),
            "sig-small-bakery": (True, "Documented small business."),
        },
    )

    assert audit["role_id"] == MONDAY_ROLE
    reasons = {d["signal_id"]: d.get("reason") for d in audit["dispositions"]}
    assert reasons[SPACEX_FIXTURE["SIGNAL_ID"]] == "Current public-company case."
    assert reasons["sig-small-bakery"] == "Documented small business."


def test_the_judgment_sees_source_material_not_pipeline_scores():
    transport = PolicyTransport({"sig-small-bakery": (True, "ok")})
    signal = {**ELIGIBLE_FIXTURES["small"], "ARTICLE_READINESS_SCORE": "9",
              "SCORE_RECOMMENDED_FOR_ARTICLE": "true"}

    judge_source_eligibility(signal, _monday_role_object(), transport)

    shown = transport.requests[0]["source_case"]
    assert "ARTICLE_READINESS_SCORE" not in shown
    assert "SCORE_RECOMMENDED_FOR_ARTICLE" not in shown
    assert shown["HEADLINE"]


def test_a_role_without_criteria_cannot_be_eligibility_judged():
    from src.strategy.business_config import EditorialRole

    role = EditorialRole(
        role_id="role-without-criteria", intent="i",
        structure=("s",), forbidden=("f",),
    )

    with pytest.raises(SourceEligibilityError):
        judge_source_eligibility(
            ELIGIBLE_FIXTURES["small"], role, PolicyTransport({})
        )


# ===========================================================================
# Source transparency reaches the output rules
# ===========================================================================


def test_wix_source_transparency_reaches_the_monday_prompt():
    prompt = _build_user_prompt(
        {"hook": "h", "discovery": {}, "echo_line": "E."},
        "long", "reflection", (),
        editorial_role_rules=render_editorial_role_rules(
            _monday_role_object(), surface="wix"
        ),
    ).lower()

    assert "visible sources section" in prompt
    assert "attribution never substitutes for verification" in prompt
    assert "no source or url is ever invented" in prompt


def test_linkedin_source_attribution_reaches_the_monday_prompt():
    prompt = _build_user_prompt(
        {"hook": "h", "discovery": {}, "echo_line": "E."},
        "medium", "reflection", (),
        editorial_role_rules=render_editorial_role_rules(
            _monday_role_object(), surface="linkedin"
        ),
    ).lower()

    assert "compact source attribution" in prompt
    assert "not citation-heavy prose" in prompt


def test_monday_source_rules_do_not_leak_into_shared_channel_composition():
    # a run without the Monday role — any other stream, today's Tue/Thu
    # included — composes from the shared channel rules alone, and those must
    # not have inherited Monday's #142 source semantics
    from src.editorial.platform_composer import _linkedin_rules, _wix_rules
    from src.strategy.execution_context import StrategyExecutionContext

    execution = StrategyExecutionContext.from_configuration(_configuration())
    article = {"hook": "h", "discovery": {}, "echo_line": "E."}
    wix_prompt = _build_user_prompt(
        article, "long", "reflection", _wix_rules(execution.wix)
    ).lower()
    linkedin_prompt = _build_user_prompt(
        article, "medium", "reflection", _linkedin_rules(execution.linkedin)
    ).lower()

    for prompt in (wix_prompt, linkedin_prompt):
        assert "visible sources section" not in prompt
        assert "compact source attribution" not in prompt
        assert "editorial role" not in prompt
    # the shared channel configuration itself stayed as it was
    channels = json.loads(CONFIG_PATH.read_text())["channels"]
    shared = json.dumps(channels).lower()
    assert "sources section" not in shared
    assert "compact source attribution" not in shared


# ===========================================================================
# selector harness
# ===========================================================================


def _select(tmp_path, signals, *, verdicts, failures=None, signal_id="",
            published=None, max_candidates=None):
    active = tmp_path / "signals_active.jsonl"
    active.write_text("\n".join(json.dumps(s) for s in signals) + "\n")
    if published is None:
        published = tmp_path / "published_signal_ids.txt"
        published.write_text("")
    audit_path = tmp_path / "audit.json"

    argv = [
        "--editorial-role", MONDAY_ROLE,
        "--active-path", str(active),
        "--published-path", str(published),
        "--audit-out", str(audit_path),
    ]
    if signal_id:
        argv += ["--signal-id", signal_id]
    if max_candidates is not None:
        argv += ["--max-candidates", str(max_candidates)]
    code = select_eligible_signal.main(
        argv, transport=PolicyTransport(verdicts, failures)
    )
    return code, json.loads(audit_path.read_text())


# ===========================================================================
# Selector outcomes (review round 1): failure is never a clean empty result
# ===========================================================================


def test_all_judgments_failing_is_infrastructure_failure_not_empty_queue(tmp_path):
    code, audit = _select(
        tmp_path,
        [ELIGIBLE_FIXTURES["small"], ELIGIBLE_FIXTURES["owner_led"]],
        verdicts={},
        failures={"sig-small-bakery", "sig-owner-led-agency"},
    )

    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["outcome"] == "eligibility_failure"
    assert audit["selected_signal_id"] is None


def test_mixed_ineligible_and_failed_judgments_still_fail_visibly(tmp_path):
    # one candidate genuinely ineligible, one judgment that never completed:
    # "no eligible candidate" is a claim the evidence does not support
    code, audit = _select(
        tmp_path,
        [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"]],
        verdicts={SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case.")},
        failures={"sig-small-bakery"},
    )

    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["outcome"] == "eligibility_failure"


def test_a_completed_all_ineligible_search_is_a_clean_empty_result(tmp_path):
    code, audit = _select(
        tmp_path,
        [SPACEX_FIXTURE],
        verdicts={SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case.")},
    )

    assert code == select_eligible_signal.NO_ELIGIBLE
    assert audit["outcome"] == "no_eligible_complete"
    assert audit["truncated"] is False


def test_a_truncated_all_ineligible_search_is_not_a_clean_empty_monday(tmp_path):
    # candidate 2 is eligible but sits beyond the search bound: the run must
    # NOT report the same healthy nothing-to-publish as an exhausted queue
    fixtures = [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"]]

    code, audit = _select(
        tmp_path, fixtures,
        verdicts={SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case.")},
        max_candidates=1,
    )

    assert code == select_eligible_signal.SEARCH_TRUNCATED
    assert audit["outcome"] == "search_truncated"
    assert audit["truncated"] is True
    assert audit["candidates_available"] == 2
    assert audit["evaluated"] == 1
    assert audit["remaining"] == 1


def test_a_failed_judgment_followed_by_an_eligible_candidate_still_selects(tmp_path):
    code, audit = _select(
        tmp_path,
        [ELIGIBLE_FIXTURES["small"], ELIGIBLE_FIXTURES["owner_led"]],
        verdicts={"sig-owner-led-agency": (True, "Documented owner-led case.")},
        failures={"sig-small-bakery"},
    )

    assert code == 0
    assert audit["outcome"] == "selected"
    assert audit["selected_signal_id"] == "sig-owner-led-agency"


def test_the_workflow_fails_visibly_on_eligibility_failure():
    resolve = _monday_step("Select eligible signal")["run"]

    # exit 3 alone becomes a green nothing-to-publish; every other nonzero
    # code — 4 included — propagates and fails the run
    assert 'if [ "$RC" = "3" ]' in resolve
    assert 'exit "$RC"' in resolve
    assert '"$RC" = "4"' not in resolve  # no special-casing failure into success


# ===========================================================================
# R1 publish secrets (review round 1): Wix + LinkedIn only
# ===========================================================================


def test_the_required_publish_secrets_are_wix_and_linkedin_only():
    gate = _monday_step("Check publish secrets")["run"]

    for required in ("NB_WIX_API_KEY", "NB_WIX_SITE_ID", "NB_WIX_POST_OWNER_ID",
                     "NB_ZERNIO_API_KEY", "NB_ZERNIO_LINKEDIN_ACCOUNT_ID"):
        assert required in gate
    # a missing non-R1 credential must never block a Monday Wix/LinkedIn run
    text = (WORKFLOWS / "monday_publish.yml").read_text()
    for absent in ("NB_META_FB_PAGE_ID", "NB_META_FB_PAGE_TOKEN",
                   "NB_META_IG_USER_ID", "NB_THREADS_ACCESS_TOKEN",
                   "NB_TELEGRAM_BOT_TOKEN", "NB_TELEGRAM_CHANNEL_ID"):
        assert absent not in text


def test_the_execution_step_keeps_the_credentials_the_r1_path_needs():
    env = _monday_step(
        "Monday — Generate + Publish ${{ steps.resolve.outputs.signal_id }}"
    )["env"]

    for required in ("NB_OPENAI_API_KEY", "NB_EXA_API_KEY", "NB_WIX_API_KEY",
                     "NB_WIX_SITE_ID", "NB_WIX_POST_OWNER_ID", "NB_WIX_SITE_BASE_URL",
                     "NB_ZERNIO_API_KEY", "NB_ZERNIO_LINKEDIN_ACCOUNT_ID",
                     "NB_CLOUDINARY_CLOUD_NAME", "NB_CLOUDINARY_API_KEY",
                     "NB_CLOUDINARY_API_SECRET"):
        assert required in env, required


# ===========================================================================
# Blocker 1 (final review round): truncation matrix
# ===========================================================================


def test_an_eligible_candidate_beyond_the_cap_is_never_a_clean_empty_result(tmp_path):
    # 16 candidates: first 15 ineligible, candidate 16 eligible. The bounded
    # search must not report the queue as holding nothing eligible.
    fixtures = [
        {**SPACEX_FIXTURE, "SIGNAL_ID": f"sig-large-{i}"} for i in range(15)
    ] + [ELIGIBLE_FIXTURES["small"]]
    verdicts = {f"sig-large-{i}": (False, "Current public-company case.")
                for i in range(15)}
    verdicts["sig-small-bakery"] = (True, "Documented small business.")

    code, audit = _select(tmp_path, fixtures, verdicts=verdicts, max_candidates=15)

    assert code == select_eligible_signal.SEARCH_TRUNCATED
    assert audit["outcome"] == "search_truncated"
    assert audit["evaluated"] == 15 and audit["remaining"] == 1


def test_exactly_the_cap_all_ineligible_is_a_clean_complete_search(tmp_path):
    fixtures = [
        {**SPACEX_FIXTURE, "SIGNAL_ID": f"sig-large-{i}"} for i in range(15)
    ]
    verdicts = {f"sig-large-{i}": (False, "Current public-company case.")
                for i in range(15)}

    code, audit = _select(tmp_path, fixtures, verdicts=verdicts, max_candidates=15)

    # every available candidate was actually evaluated — this one may be green
    assert code == select_eligible_signal.NO_ELIGIBLE
    assert audit["outcome"] == "no_eligible_complete"
    assert audit["truncated"] is False
    assert audit["remaining"] == 0


def test_an_eligible_candidate_inside_the_window_is_selected(tmp_path):
    fixtures = [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"]]

    code, audit = _select(
        tmp_path, fixtures,
        verdicts={
            SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case."),
            "sig-small-bakery": (True, "Documented small business."),
        },
        max_candidates=15,
    )

    assert code == 0
    assert audit["outcome"] == "selected"


def test_judgment_failure_outranks_truncation(tmp_path):
    # a failed judgment inside a truncated window is infrastructure failure,
    # not a truncation report — the stronger signal wins
    fixtures = [SPACEX_FIXTURE, ELIGIBLE_FIXTURES["small"], ELIGIBLE_FIXTURES["owner_led"]]

    code, audit = _select(
        tmp_path, fixtures,
        verdicts={SPACEX_FIXTURE["SIGNAL_ID"]: (False, "Current public-company case.")},
        failures={"sig-small-bakery"},
        max_candidates=2,
    )

    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["outcome"] == "eligibility_failure"
    assert audit["truncated"] is True  # the fact is still recorded


def test_the_workflow_propagates_the_truncated_outcome_as_a_failure():
    resolve = _monday_step("Select eligible signal")["run"]

    # only exit 3 becomes a green nothing-to-publish; 5 propagates
    assert 'if [ "$RC" = "3" ]' in resolve
    assert '"$RC" = "5"' not in resolve


# ===========================================================================
# Blocker 2 (final review round): source transparency is enforced
# ===========================================================================

from src.editorial.source_transparency import (
    SourceTransparencyError,
    validate_source_transparency,
)


def _research_artifact():
    # a validated artifact with one real source: url
    # https://advocacy.sba.gov/report, publisher "SBA Office of Advocacy",
    # title "Small-business operating constraints"
    from tests import test_decision_lens_evaluator as evaluator_fixtures

    return evaluator_fixtures._research()  # noqa: SLF001


ATTRIBUTED_BODY = (
    "The documented case shows one mechanism. "
    "Source: SBA Office of Advocacy (https://advocacy.sba.gov/report)."
)
UNATTRIBUTED_BODY = "A confident article that cites nothing at all."
FABRICATED_BODY = (
    "According to the Global Business Institute (https://invented.example/study), "
    "small firms behave this way."
)


def test_valid_attribution_on_both_surfaces_passes():
    validate_source_transparency(
        article_body=ATTRIBUTED_BODY,
        linkedin_body="Case documented by the SBA Office of Advocacy.",
        research=_research_artifact(),
    )


@pytest.mark.parametrize(
    "article, linkedin, failing_surface",
    [
        (UNATTRIBUTED_BODY, "Case documented by the SBA Office of Advocacy.", "article"),
        (ATTRIBUTED_BODY, UNATTRIBUTED_BODY, "linkedin"),
    ],
)
def test_a_surface_without_attribution_blocks(article, linkedin, failing_surface):
    with pytest.raises(SourceTransparencyError) as exc:
        validate_source_transparency(
            article_body=article, linkedin_body=linkedin,
            research=_research_artifact(),
        )

    assert failing_surface in str(exc.value)


def test_a_fabricated_source_does_not_satisfy_the_rule():
    # it "looks cited" — named institute, plausible URL — but neither belongs
    # to this run's sources
    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body=FABRICATED_BODY,
            linkedin_body="Case documented by the SBA Office of Advocacy.",
            research=_research_artifact(),
        )


def test_an_invented_link_beside_real_attribution_still_blocks():
    body = ATTRIBUTED_BODY + " See also https://invented.example/extra."

    with pytest.raises(SourceTransparencyError) as exc:
        validate_source_transparency(
            article_body=body, linkedin_body="Per the SBA Office of Advocacy.",
            research=_research_artifact(),
        )

    assert "invented" in str(exc.value) or "not one of this run's sources" in str(exc.value)


def test_the_configured_site_destination_is_not_treated_as_invented():
    body = ATTRIBUTED_BODY + " Continue at https://www.inneros.online/about."

    validate_source_transparency(
        article_body=body, linkedin_body="Per the SBA Office of Advocacy.",
        research=_research_artifact(),
        allowed_destinations=("https://www.inneros.online",),
    )


def test_a_monday_run_with_attribution_publishes_normally(tmp_path):
    code, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE)

    assert code == 0
    assert list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_monday_run_without_attribution_blocks_before_any_publisher(tmp_path):
    import copy

    from tests.test_generate_and_publish import _FAKE_ARTICLE

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    patches["generate_article"] = mock.MagicMock(
        return_value=copy.deepcopy(_FAKE_ARTICLE)  # "Blog body text." — cites nothing
    )
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1
    # 7. no publisher was called; 8. nothing was consumed
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    # truthful run evidence: the report records the editorial-stage block
    report = json.loads(next(tmp_path.glob("*/runs/*/run_report.json")).read_text())
    assert report["terminal_stage"] == "editorial"
    assert report["completed"] is False


def test_a_non_monday_run_is_not_subjected_to_the_source_rule(tmp_path):
    # the exact article that blocks a Monday run publishes normally with no
    # role — prior behaviour, byte for byte
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert list(tmp_path.glob("*/runs/*/generated.json"))


def test_the_requirement_is_declared_by_the_role_not_by_code():
    role = _monday_role_object()

    assert role.require_source_transparency is True
    # and the flag is generic: a role without it is never checked
    from src.strategy.business_config import EditorialRole

    plain = EditorialRole(role_id="r", intent="i", structure=("s",), forbidden=("f",))
    assert plain.require_source_transparency is False


# ===========================================================================
# Blocking review (comment 5359239851): URL structure and attribution contract
# ===========================================================================


def test_sibling_and_lookalike_hosts_are_refused_structurally():
    body = ATTRIBUTED_BODY + " Continue at https://www.inneros.online.evil.test/phish."

    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body=body, linkedin_body="Per the SBA Office of Advocacy.",
            research=_research_artifact(),
            allowed_destinations=("https://www.inneros.online",),
        )


@pytest.mark.parametrize("attack", [
    "https://www.inneros.online.evil.test/phish",
    "https://www.inneros.online@evil.test/",
    "https://evil.test/https://www.inneros.online",
    "https://inneros.online.evil.test/",
    "https://www.inneros.online:444/",
    "//evil.test/phish",
    "HTTPS://evil.test/phish",
])
def test_url_confusion_attacks_fail(attack):
    body = ATTRIBUTED_BODY + f" See {attack} for more."

    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body=body, linkedin_body="Per the SBA Office of Advocacy.",
            research=_research_artifact(),
            allowed_destinations=("https://www.inneros.online",),
        )


@pytest.mark.parametrize("legitimate", [
    "https://www.inneros.online",
    "https://www.inneros.online/",
    "https://www.inneros.online/some/path",
])
def test_the_exact_configured_origin_and_subpaths_pass(legitimate):
    body = ATTRIBUTED_BODY + f" Continue at {legitimate} today."

    validate_source_transparency(
        article_body=body, linkedin_body="Per the SBA Office of Advocacy.",
        research=_research_artifact(),
        allowed_destinations=("https://www.inneros.online",),
    )


def test_a_generic_publisher_is_never_satisfied_by_ordinary_prose():
    # publisher "Research": "our research shows" is lexical overlap, not
    # attribution — and a fully generic name is excluded from name matching
    research = _research_with(publisher="Research", title="Research")

    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body="Our research shows steady gains for small firms.",
            linkedin_body="Our research shows the same.",
            research=research,
        )


def test_a_generic_publisher_is_refused_even_inside_an_attribution_construction():
    research = _research_with(publisher="Research", title="Research")

    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body="According to Research, firms grow.",
            linkedin_body="Per Research.",
            research=research,
        )


def test_a_generic_publisher_can_still_be_attested_by_its_exact_url():
    research = _research_with(publisher="Research", title="Research")

    validate_source_transparency(
        article_body="The case is documented at https://advocacy.sba.gov/report.",
        linkedin_body="Details: https://advocacy.sba.gov/report",
        research=research,
    )


def test_an_unambiguous_publisher_needs_an_explicit_construction():
    # boundary-matched mention without an attribution construction is not
    # attribution either
    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body="We visited the SBA Office of Advocacy building last week.",
            linkedin_body="A nice building.",
            research=_research_artifact(),
        )


@pytest.mark.parametrize("body", [
    "According to SBA Office of Advocacy Evil Institute, firms grow.",
    "Per SBA Office of Advocacy Evil Institute, firms grow.",
    "Sources:\nFake SBA Office of Advocacy Institute",
])
def test_a_real_source_identity_cannot_prefix_a_fabricated_identity(body):
    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body=body,
            linkedin_body="Per the SBA Office of Advocacy.",
            research=_research_artifact(),
        )


@pytest.mark.parametrize("body", [
    "Source: SBA Office of Advocacy",
    "According to SBA Office of Advocacy",
    "According to the SBA Office of Advocacy, firms grow.",
    "Per SBA Office of Advocacy.",
    "SBA Office of Advocacy reported steady gains.",
    "SBA Office of Advocacy documented the case.",
    "The case was documented by SBA Office of Advocacy.",
    "Sources:\n- SBA Office of Advocacy",
])
def test_declared_exact_attribution_constructions_remain_valid(body):
    validate_source_transparency(
        article_body=body,
        linkedin_body="Per the SBA Office of Advocacy.",
        research=_research_artifact(),
    )


def _research_with(**source_overrides):
    raw = json.loads(_research_artifact().model_dump_json())
    raw["sources"][0].update(source_overrides)
    from src.research.evidence import NormalizedResearchArtifact

    return NormalizedResearchArtifact.model_validate(raw)


# --- the same attacks through the real canonical entrypoint ---------------


class _GenericPublisherProvider(ReadyProvider):
    """ReadyProvider whose single source has an unusably generic identity."""

    def research(self, request):
        result = super().research(request)
        raw = json.loads(result.artifact.model_dump_json())
        raw["sources"][0]["publisher"] = "Research"
        raw["sources"][0]["title"] = "Research"
        from src.research.evidence import NormalizedResearchArtifact

        artifact = NormalizedResearchArtifact.model_validate(raw)
        return result.model_copy(update={"artifact": artifact})


def _blocked_monday_run(tmp_path, article, provider=None, env=None):
    import copy

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    patches["generate_article"] = mock.MagicMock(return_value=copy.deepcopy(article))
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    evaluator, _ = _evaluator(_model_output())
    import os as _os

    with mock.patch.object(sys, "argv", argv), \
         mock.patch.dict(_os.environ, env or {}, clear=False), \
         mock.patch.multiple(gap, **patches):
        code = main(
            research_provider=provider or ReadyProvider(),
            decision_evaluator=evaluator,
        )
    return code, patches


def test_entrypoint_blocks_a_sibling_domain_cta_before_any_publisher(tmp_path):
    article = _attributed_article()
    article["platforms"]["long"]["body"] += (
        " Continue at https://www.inneros.online.evil.test/phish today."
    )

    code, patches = _blocked_monday_run(
        tmp_path, article,
        env={"NB_WIX_SITE_BASE_URL": "https://www.inneros.online"},
    )

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_entrypoint_blocks_generic_publisher_prose(tmp_path):
    import copy

    from tests.test_generate_and_publish import _FAKE_ARTICLE

    article = copy.deepcopy(_FAKE_ARTICLE)
    article["platforms"]["long"]["body"] = (
        "Our research shows small firms benefit from clear paths."
    )
    article["platforms"]["medium"]["body"] = "Our research shows the same."

    code, patches = _blocked_monday_run(
        tmp_path, article, provider=_GenericPublisherProvider(),
    )

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["append_published_entry"].called


def test_entrypoint_passes_the_exact_configured_cta_and_source_url(tmp_path):
    article = _attributed_article()  # attributes via the exact fixture source URL
    article["platforms"]["long"]["body"] += (
        " Continue at https://www.inneros.online/some/path today."
    )

    argv, patches = _entry_patches(tmp_path)
    patches["generate_article"] = mock.MagicMock(return_value=article)
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    evaluator, _ = _evaluator(_model_output())
    import os as _os

    with mock.patch.object(sys, "argv", argv), \
         mock.patch.dict(_os.environ,
                         {"NB_WIX_SITE_BASE_URL": "https://www.inneros.online"}), \
         mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert list(tmp_path.glob("*/runs/*/generated.json"))


def test_entrypoint_passes_explicit_publisher_attribution(tmp_path):
    # no URL anywhere: attribution rests on the explicit construction alone
    article = _attributed_article()
    article["platforms"]["long"]["body"] = (
        "One documented mechanism. Case documented by Verified report."
    )
    article["platforms"]["medium"]["body"] = "According to Verified report, it held."

    code, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE, article=article)

    assert code == 0


def test_entrypoint_blocks_a_fabricated_link_beside_real_attribution(tmp_path):
    article = _attributed_article()
    article["platforms"]["long"]["body"] += (
        " See also https://invented.example/study for context."
    )

    code, patches = _blocked_monday_run(tmp_path, article)

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["append_published_entry"].called


@pytest.mark.parametrize("attack", [
    "[malicious](//evil.test/phish)",
    "HTTPS://evil.test/phish",
])
def test_entrypoint_blocks_alternate_external_link_spellings(tmp_path, attack):
    article = _attributed_article()
    article["platforms"]["long"]["body"] += f" Continue at {attack}."

    code, patches = _blocked_monday_run(
        tmp_path,
        article,
        env={"NB_WIX_SITE_BASE_URL": "https://www.inneros.online"},
    )

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


@pytest.mark.parametrize("construction", [
    "According to Verified report Evil Institute, the result held.",
    "Per Verified report Evil Institute, the result held.",
    "Sources:\nFake Verified report Institute",
])
def test_entrypoint_blocks_fabricated_identity_extending_a_real_title(
    tmp_path, construction,
):
    article = _attributed_article()
    article["platforms"]["long"]["body"] = construction
    article["platforms"]["medium"]["body"] = (
        "Case documented by Verified report."
    )

    code, patches = _blocked_monday_run(tmp_path, article)

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


# ===========================================================================
# R1 decision policy (#152): explicit, role-scoped, auditable — never silent
# ===========================================================================


def test_the_monday_role_declares_the_r1_decision_policy():
    identity, role = resolve_editorial_role(_configuration(), MONDAY_ROLE)

    assert role.decision_policy == "role_bounded_r1"
    assert identity.decision_policy == "role_bounded_r1"
    # and the default is today's behaviour, for every role that doesn't ask
    from src.strategy.business_config import EditorialRole

    plain = EditorialRole(role_id="r", intent="i", structure=("s",), forbidden=("f",))
    assert plain.decision_policy == "decision_lens"


def test_a_monday_run_proceeds_past_the_decision_point_on_ready_research(tmp_path):
    code, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE)

    assert code == 0
    # the Decision Lens was never consulted; the policy record is the chain link
    run_dir = next(tmp_path.glob("*/runs/*/"))
    assert not (run_dir / "decision.json").exists()
    policy = json.loads((run_dir / "decision_policy.json").read_text())
    assert policy["decision_policy"] == "role_bounded_r1"
    assert policy["role_id"] == MONDAY_ROLE
    assert policy["run_id"] == run_dir.name
    assert policy["research_readiness"] == "ready"
    assert policy["reconciliation"] == "#151"
    # and assignment.json records which policy governed the run
    assert _assignment_json(tmp_path)["editorial_role"]["decision_policy"] == "role_bounded_r1"


def test_the_policy_run_is_provenance_verifiable(tmp_path):
    # verified at the transparency-blocked point, where the on-disk chain is
    # complete (the dry-run harness mocks the later channel writers away)
    import copy

    from src.artifacts.provenance import verify_run_provenance
    from tests.test_generate_and_publish import _FAKE_ARTICLE

    _blocked_monday_run(tmp_path, copy.deepcopy(_FAKE_ARTICLE))
    run_dir = next(tmp_path.glob("*/runs/*/"))

    report = verify_run_provenance(tmp_path, run_dir.parent.parent.name, run_dir.name)

    assert "decision_policy" in report.verified_artifacts
    assert "decision" not in report.verified_artifacts
    assert report.stopped_after == "editorial_acceptance"


def test_acceptance_without_any_decision_authority_is_still_corruption(tmp_path):
    import copy

    from src.artifacts.provenance import ProvenanceError, verify_run_provenance
    from tests.test_generate_and_publish import _FAKE_ARTICLE

    _blocked_monday_run(tmp_path, copy.deepcopy(_FAKE_ARTICLE))
    run_dir = next(tmp_path.glob("*/runs/*/"))
    (run_dir / "decision_policy.json").unlink()  # simulate the silent bypass

    with pytest.raises(ProvenanceError) as exc:
        verify_run_provenance(tmp_path, run_dir.parent.parent.name, run_dir.name)

    assert "cannot exist without its upstream chain" in str(exc.value)


def test_a_run_cannot_carry_both_decision_authorities(tmp_path):
    from src.artifacts import write_decision_policy_json
    from src.artifacts.provenance import ProvenanceError, verify_run_provenance

    # a normal decision-lens run (no role)…
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0
    run_dir = next(tmp_path.glob("*/runs/*/"))
    assert (run_dir / "decision.json").exists()
    # …with a policy record smuggled in beside the decision
    write_decision_policy_json(run_dir, {"run_id": run_dir.name})

    with pytest.raises(ProvenanceError) as exc:
        verify_run_provenance(tmp_path, run_dir.parent.parent.name, run_dir.name)

    assert "exactly one decision authority" in str(exc.value)


def test_a_run_without_the_monday_role_still_takes_the_decision_lens(tmp_path):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    # a non-PROCEED disposition must still block the role-less run
    evaluator, transport = _evaluator(_model_output(disposition="hold"))

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1

    assert len(transport.calls) == 1  # the lens WAS consulted
    assert not patches["WixPublisher"].called
    run_dir = next(tmp_path.glob("*/runs/*/"))
    assert (run_dir / "decision.json").exists()
    assert not (run_dir / "decision_policy.json").exists()


def test_non_ready_research_still_blocks_the_monday_role(tmp_path):
    from src.research.lifecycle import ResearchGateError

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    patches["generate_article"] = mock.MagicMock(return_value=_attributed_article())
    # the canonical research gate refuses (non-READY) — the policy must
    # authorize nothing on top of that
    patches["execute_and_persist_research"] = mock.MagicMock(
        side_effect=ResearchGateError("research readiness is needs_review")
    )
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 1
    assert not patches["generate_article"].called
    assert not patches["WixPublisher"].called
    assert not list(tmp_path.glob("*/runs/*/decision_policy.json"))


def test_the_policy_does_not_relax_acceptance_or_source_transparency(tmp_path):
    import copy

    from tests.test_generate_and_publish import _FAKE_ARTICLE

    # unattributed article under the Monday role: the run passes the decision
    # point on policy, then source transparency still blocks the publishers
    code, patches = _blocked_monday_run(tmp_path, copy.deepcopy(_FAKE_ARTICLE))

    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["append_published_entry"].called
    # and the blocked run now has an authoritative report again
    report = json.loads(next(tmp_path.glob("*/runs/*/run_report.json")).read_text())
    assert report["terminal_stage"] == "editorial"
    assert report["completed"] is False
    assert any(a["name"] == "decision_policy.json" for a in report["artifacts"])
