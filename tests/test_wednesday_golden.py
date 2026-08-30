"""Issue #143: Never Blank Wednesday Golden stream.

These tests exercise the strict product profile, explicit persisted role,
canonical composition and acceptance paths, workflow ownership, and the
Wednesday-only product/Engine boundary.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from scripts.streams import due_check, select_eligible_signal
from scripts.streams.due_check import NOT_DUE, is_due
from src.editorial.editorial_role import (
    EditorialRoleError,
    EditorialRoleIdentity,
    render_editorial_role_rules,
    resolve_editorial_role,
)
from src.editorial.editorial_acceptance import (
    EditorialAcceptanceRubric,
    _review_article,
)
from src.editorial.platform_composer import _build_user_prompt, _linkedin_rules, _wix_rules
from src.never_blank.wednesday_golden import (
    GOLDEN_STAGE_ORDER,
    GoldenReference,
    SourceKind,
    WednesdayGoldenProfile,
    load_golden_reference,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_generate_and_publish import _FAKE_ARTICLE
from tests.test_monday_stream import WEDNESDAY_SUPPLY


PROFILE_PATH = Path("config/never_blank/wednesday_golden.yaml")
RUBRIC_PATH = Path(
    "config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml"
)
FIXTURE_DIR = Path("tests/fixtures/golden_wednesday")
BUSINESS_CONFIG = Path("strategy/current/business_strategy.json")
WORKFLOW = Path(".github/workflows/wednesday_golden.yml")
SITE = "https://www.inneros.online"
ROLE_ID = "never-blank-wednesday-golden"
ET = ZoneInfo("America/New_York")



@pytest.fixture(scope="module")
def profile() -> WednesdayGoldenProfile:
    return WednesdayGoldenProfile.load(PROFILE_PATH)


def _article() -> dict:
    return {
        "hook": "A documented tension",
        "narrative_spine": "X turns toward Y",
        "surviving_explanation": "One mechanism",
        "reframe": "The overlooked observation",
        "business_translation": "A bounded question",
        "discovery": {},
        "echo_line": "A contextual close.",
        "cta_line": "Continue the reflection.",
    }


def _attributed_article() -> dict:
    article = deepcopy(_FAKE_ARTICLE)
    article["platforms"]["long"]["body"] = (
        "The documented case shows one mechanism. Source: Verified report "
        "(https://source.example/report)."
    )
    article["platforms"]["medium"]["body"] = (
        "The same discovery, documented by Verified report."
    )
    return article


def _workflow(name: str) -> dict:
    return yaml.safe_load((Path(".github/workflows") / name).read_text())


def _schedule(workflow: dict) -> list[str]:
    triggers = workflow.get("on") or workflow.get(True) or {}
    return [item["cron"] for item in (triggers.get("schedule") or [])]


def _fires_on(cron: str, weekday: str) -> bool:
    field = cron.split()[4]
    return field == "*" or weekday in {item.strip() for item in field.split(",")}


# Product structure and strictness -------------------------------------------------


def test_profile_is_strict_immutable_and_has_explicit_role(profile):
    assert profile.profile_id == "never-blank-wednesday-golden"
    assert profile.editorial_role_id == "never-blank-wednesday-golden"
    with pytest.raises(ValidationError):
        profile.profile_id = "changed"

    raw = yaml.safe_load(PROFILE_PATH.read_text())
    raw["unreviewed_escape_hatch"] = True
    with pytest.raises(ValidationError):
        WednesdayGoldenProfile.model_validate(raw)


def test_golden_structure_is_complete_once_and_in_order(profile):
    assert tuple(stage.stage_id for stage in profile.reasoning_movement) == (
        GOLDEN_STAGE_ORDER
    )
    assert profile.text_shape.central_discoveries == 1
    assert profile.text_shape.primary_mechanisms == 1

    raw = profile.model_dump(mode="json")
    raw["reasoning_movement"][1], raw["reasoning_movement"][3] = (
        raw["reasoning_movement"][3],
        raw["reasoning_movement"][1],
    )
    with pytest.raises(ValidationError, match="canonical stages"):
        WednesdayGoldenProfile.model_validate(raw)


def test_x_and_y_are_distinct_editorial_functions(profile):
    stages = {stage.stage_id.value: stage.editorial_function for stage in profile.reasoning_movement}
    assert stages["obvious_reading_x"] != stages["overlooked_y"]
    assert "surface interpretation" in stages["obvious_reading_x"].lower()
    assert "defensible from the accepted evidence" in stages["overlooked_y"].lower()

    reference = load_golden_reference(FIXTURE_DIR / "versant_full_swing.yaml")
    bad = reference.model_dump(mode="json")
    bad["overlooked_y"] = bad["obvious_reading_x"].upper()
    with pytest.raises(ValidationError, match="X and overlooked Y must be distinct"):
        GoldenReference.model_validate(bad)


def test_anti_flattening_and_title_contract_are_explicit(profile):
    ids = {item.prohibition_id for item in profile.prohibitions}
    assert {
        "news-recap",
        "five-lessons",
        "three-takeaways",
        "generic-smb-advice",
        "multiple-mechanisms",
        "manufactured-contrarianism",
        "unsupported-y",
        "outcome-transfer",
        "generic-ai-language",
        "long-background",
        "source-headline-title",
        "reveal-y-title",
    } <= ids
    title_text = " ".join((profile.title.intent, *profile.title.required, *profile.title.forbidden)).lower()
    assert "curiosity" in title_text
    assert "source headline" in title_text
    assert "reveal the complete overlooked y" in title_text
    assert "cheap clickbait" in title_text
    assert "manufacture a contradiction" in title_text


# Declarative source eligibility ---------------------------------------------------


def test_policy_allows_historical_and_large_company_cases_without_same_day_news(profile):
    assert profile.source_policy.same_day_required is False
    assert profile.source_policy.large_company_cases_allowed is True
    assert SourceKind.HISTORICAL_CASE in profile.source_policy.allowed_source_kinds
    assert SourceKind.CORPORATE_CASE in profile.source_policy.allowed_source_kinds

    rendered = " ".join(profile.source_eligibility_rules()).lower()
    assert "same-day or breaking-news status is not required" in rendered
    assert "credible large-company case may qualify" in rendered


def test_policy_requires_x_y_one_mechanism_evidence_and_bounded_transfer(profile):
    policy = profile.source_policy
    assert policy.require_documented_fact is True
    assert policy.require_obvious_reading_x is True
    assert policy.require_overlooked_y is True
    assert policy.require_evidence_supporting_y is True
    assert policy.required_primary_mechanisms == 1
    assert policy.required_transfer_mode.value == "bounded_business_question"

    rendered = " ".join(profile.source_eligibility_rules()).lower()
    assert "obvious reading x" in rendered
    assert "overlooked y" in rendered
    assert "exactly one primary mechanism" in rendered
    assert "surprise or analogy alone is not eligibility" in rendered
    assert "outcome may transfer only as a bounded question" in rendered


def test_compound_presence_is_not_a_mandatory_wednesday_mechanism(profile):
    # #157: the Golden mechanism may be Compound Presence, but it may equally
    # be another supported business mechanism. The mandate is gone from the
    # strict policy model, the profile and the eligibility rules.
    from src.never_blank.wednesday_golden import WednesdaySourcePolicy

    assert "require_compound_presence_relevance" not in WednesdaySourcePolicy.model_fields

    rendered = " ".join(profile.source_eligibility_rules()).lower()
    assert "genuine documented connection to compound presence" not in rendered
    for alternative in ("pricing", "capacity", "supply", "regulation",
                        "distribution", "operations"):
        assert alternative in rendered


def test_compound_presence_remains_available_and_forcing_it_stays_prohibited(profile):
    rendered = " ".join(profile.source_eligibility_rules()).lower()

    assert "compound presence when the material genuinely carries it" in rendered
    assert "do not force compound presence onto a case that does not support it" in rendered
    assert "do not force an unrelated interesting story into the role" in rendered


def test_the_golden_movement_and_its_guarantees_are_unchanged(profile):
    # the approved contract survives the eligibility change intact
    stages = [stage.stage_id.value for stage in profile.reasoning_movement]
    assert stages == [
        "event", "obvious_reading_x", "turn", "overlooked_y", "primary_mechanism",
        "evidence_for_y", "bounded_business_question", "never_blank_insight",
        "close_and_cta",
    ]
    assert profile.text_shape.primary_mechanisms == 1
    assert profile.text_shape.central_discoveries == 1
    assert profile.source_policy.required_transfer_mode.value == "bounded_business_question"

    prohibitions = " ".join(item.rule for item in profile.prohibitions).lower()
    for forbidden in ("5 lessons", "3 takeaways", "recap", "generic"):
        assert forbidden in prohibitions


def test_all_authorized_documented_source_classes_are_configured(profile):
    assert set(profile.source_policy.allowed_source_kinds) == set(SourceKind)


# Generic role seam and canonical run evidence ------------------------------------


def test_wednesday_role_resolves_explicitly_from_strict_configuration(profile):
    configuration = load_business_strategy_configuration(BUSINESS_CONFIG)
    identity, role = resolve_editorial_role(configuration, ROLE_ID)

    assert identity == EditorialRoleIdentity(
        role_id=ROLE_ID,
        configuration_version=configuration.configuration_version,
        # #209: Wednesday's business reasoning is the restored July path, so
        # the current canonical Decision Lens does not gate it. The bypass is
        # this declared policy — auditable in configuration, on the
        # assignment anchor and in decision_policy.json — never a silence.
        decision_policy="role_bounded_r1",
    )
    assert role.role_id == profile.editorial_role_id
    assert tuple(role.eligibility_criteria) == profile.source_eligibility_rules()
    assert role.decision_policy == "role_bounded_r1"
    assert role.require_source_transparency is True
    assert role.acceptance_rubric_path == profile.acceptance_rubric_path
    assert role.acceptance_rubric_identity == profile.acceptance_rubric_identity


def test_unknown_or_blank_editorial_role_fails_closed():
    configuration = load_business_strategy_configuration(BUSINESS_CONFIG)
    for requested in ("", "   ", "never-blank-unknown"):
        with pytest.raises(EditorialRoleError):
            resolve_editorial_role(configuration, requested)


def render_editorial_role_rules_for_both_surfaces() -> dict:
    """The per-surface role rules, still rendered and still contract-tested."""
    configuration = load_business_strategy_configuration(BUSINESS_CONFIG)
    _identity, role = resolve_editorial_role(configuration, ROLE_ID)
    return {
        "long": render_editorial_role_rules(role, surface="wix"),
        "medium": render_editorial_role_rules(role, surface="linkedin"),
    }


def test_canonical_entrypoint_records_role_and_routes_real_rules(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    # #209: Wednesday generates through the restored July package, so the
    # routing seam is what the harness stands in for. The shared engine is
    # left in place and asserted unused below.
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=_attributed_article()
    )
    # #211: Wednesday supplies its own signal through the restored July
    # research. These scenarios are about role rules and transparency, so
    # the supply is stood in for here; the real supply route is proven in
    # tests/test_wednesday_supply.py.
    patches["supply_wednesday_signal"] = mock.MagicMock(
        return_value=dict(WEDNESDAY_SUPPLY)
    )
    argv += ["--editorial-role", ROLE_ID]
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0

    assignment_path = next(tmp_path.glob("*/runs/*/assignment.json"))
    assignment = json.loads(assignment_path.read_text())
    assert assignment["schema_version"] == "1.2"
    assert assignment["editorial_role"] == {
        "role_id": ROLE_ID,
        "configuration_version": load_business_strategy_configuration(
            BUSINESS_CONFIG
        ).configuration_version,
        "decision_policy": "role_bounded_r1",
    }

    # #209: Wednesday routes to the restored July path and NOT to the shared
    # engine. July's pipeline takes only the signal, so role rules no longer
    # reach Wednesday generation — they are still rendered and are still
    # exercised against the prompt constructor by the tests below.
    assert patches["generate_for_wednesday"].called
    assert not patches["generate_article"].called
    signal = patches["generate_for_wednesday"].call_args.args[0]
    assert isinstance(signal, dict)

    role_rules = render_editorial_role_rules_for_both_surfaces()
    assert set(role_rules) == {"long", "medium"}
    assert "obvious public interpretation X" in role_rules["long"]
    assert "exactly one primary mechanism" in role_rules["medium"]
    assert "evidence-grounded title tension" in role_rules["long"]
    assert "native compressed LinkedIn" in role_rules["medium"]
    # NOTE (#209): the sources-of-record block is appended by the entrypoint
    # onto the role rules it passes to the SHARED engine. Wednesday no longer
    # takes that path, so those assertions moved out of this routing test.
    # Their rendering is still covered by tests/test_monday_stream.py and by
    # the prompt-constructor tests below; the consequence for Wednesday —
    # role rules and the sources block no longer shape its prose — is
    # recorded as a deviation in #209.

    rubric = patches["run_editorial_acceptance"].call_args.kwargs["rubric"]
    assert rubric.identity == "never-blank-golden-wednesday-acceptance/1.1"
    revision_sources = patches["run_editorial_acceptance"].call_args.kwargs[
        "sources_of_record"
    ]
    assert "Verified report" in revision_sources
    assert "https://source.example/report" in revision_sources


def test_wednesday_source_transparency_blocks_before_publish_and_consumption(tmp_path):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    # #209: Wednesday generates through the restored July package
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=deepcopy(_FAKE_ARTICLE)
    )
    patches["supply_wednesday_signal"] = mock.MagicMock(
        return_value=dict(WEDNESDAY_SUPPLY)
    )
    argv += ["--editorial-role", ROLE_ID]
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(
            research_provider=ReadyProvider(), decision_evaluator=evaluator
        ) == 1

    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_unknown_role_stops_before_generation_and_run_artifacts(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    argv += ["--editorial-role", "never-blank-unknown"]
    evaluator, _ = _evaluator(_model_output())

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 1

    assert not patches["generate_article"].called
    assert not list(tmp_path.glob("*/runs/*"))


# Real existing prompt/acceptance consumers --------------------------------------


def test_golden_rules_reach_the_existing_wix_and_linkedin_prompt_constructor(profile):
    execution = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration(BUSINESS_CONFIG)
    )
    role = resolve_editorial_role(
        load_business_strategy_configuration(BUSINESS_CONFIG), ROLE_ID
    )[1]
    wix_role = render_editorial_role_rules(role, surface="wix")
    linkedin_role = render_editorial_role_rules(role, surface="linkedin")

    wix_prompt = _build_user_prompt(
        _article(),
        "long",
        profile.cta_id,
        _wix_rules(execution.wix),
        editorial_role_rules=wix_role,
    )
    linkedin_prompt = _build_user_prompt(
        _article(),
        "medium",
        profile.cta_id,
        _linkedin_rules(execution.linkedin),
        editorial_role_rules=linkedin_role,
    )

    for prompt in (wix_prompt, linkedin_prompt):
        assert "CONFIGURED CHANNEL RULES:" in prompt
        assert f"EDITORIAL ROLE — {ROLE_ID}" in prompt
        assert "obvious public interpretation X" in prompt
        assert "overlooked Y" in prompt
        assert "what supports Y" in prompt
        assert "exactly one primary mechanism" in prompt
        assert "5 lessons from X" in prompt
        assert "3 takeaways" in prompt
    assert "evidence-grounded title tension" in wix_prompt
    assert "native compressed LinkedIn" in linkedin_prompt
    # #203: the destination is surface-scoped — the article names it, the
    # social derivative never does (the system appends the canonical link)
    assert SITE in wix_prompt
    assert SITE not in linkedin_prompt


class _AcceptingReviewer:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls.append({"instructions": instructions, "request": request})
        return json.dumps(
            {
                "disposition": "accept",
                "failed_criterion_ids": [],
                "rationale": "Deterministic contract test.",
                "revision_guidance": "",
            }
        )


class _ResearchStub:
    evidence: tuple = ()


def test_golden_rubric_reaches_the_real_acceptance_review_boundary(profile):
    rubric = EditorialAcceptanceRubric.load(RUBRIC_PATH)
    reviewer = _AcceptingReviewer()
    review = _review_article(
        reviewer,
        rubric,
        article_body="A deterministic test article.",
        research=_ResearchStub(),  # type: ignore[arg-type]
        run_id="00000000-0000-4000-8000-000000000143",
    )

    assert rubric.identity == profile.acceptance_rubric_identity
    assert review.rubric_id == rubric.rubric_id
    assert len(reviewer.calls) == 1
    instruction_text = reviewer.calls[0]["instructions"]
    request = reviewer.calls[0]["request"]
    assert "obvious reading X" in instruction_text
    assert "overlooked Y" in instruction_text
    assert "exactly one" in instruction_text
    assert "5 lessons from X" in instruction_text
    assert "evidence-supported-y" in request
    assert "bounded-business-question" in request


def test_existing_r1_cta_and_surface_contract_are_reused(profile):
    config = json.loads(BUSINESS_CONFIG.read_text())
    cta = next(item for item in config["calls_to_action"] if item["cta_id"] == profile.cta_id)
    assert SITE == profile.website_destination
    assert SITE in " ".join(cta["rules"])
    assert profile.text_shape.shared_discovery_key in profile.generation_rules("wix")[-2]
    assert profile.text_shape.shared_discovery_key in profile.generation_rules("linkedin")[-2]


# References, workflow safety, and universal boundary ----------------------------


def test_golden_reference_fixtures_are_reasoning_annotations_not_prose_templates(profile):
    primary = load_golden_reference(FIXTURE_DIR / "versant_full_swing.yaml")
    secondary = load_golden_reference(FIXTURE_DIR / "gm_v8.yaml")
    assert primary.reference_kind.value == "primary"
    assert secondary.reference_kind.value == "secondary"
    for reference in (primary, secondary):
        assert reference.usage_rule == "reasoning_reference_only_do_not_imitate_wording"
        assert reference.obvious_reading_x != reference.overlooked_y
        assert len(reference.evidence_basis) >= 3

    negative = yaml.safe_load((FIXTURE_DIR / "invisalign_negative.yaml").read_text())
    assert negative["usage_rule"] == "counterexample_only_do_not_imitate_wording"
    assert any("without a defensible X-to-Y" in item for item in negative["diagnosis"])


def test_wednesday_has_its_own_canonical_workflow_and_role():
    workflow = _workflow("wednesday_golden.yml")
    assert list(workflow["jobs"]) == ["wednesday-golden"]
    assert _schedule(workflow) == ["0 10 * * 3", "0 11 * * 3"]

    text = WORKFLOW.read_text()
    assert "scripts/generate_and_publish.py" in text
    assert '--editorial-role "$WEDNESDAY_ROLE"' in text
    assert "WEDNESDAY_ROLE: never-blank-wednesday-golden" in text
    # #174: from-package is reachable only behind the dispatched
    # source_run_id guard — never on the scheduled path
    assert '--from-package --source-run-id $SOURCE_RUN_ID' in text
    assert 'if [ -n "$SOURCE_RUN_ID" ]' in text
    assert "--legacy-package" not in text
    assert "scripts/publish.py" not in text


def test_wednesday_workflow_uses_canonical_visual_and_r1_publish_surfaces():
    workflow = _workflow("wednesday_golden.yml")
    steps = workflow["jobs"]["wednesday-golden"]["steps"]
    generation = next(
        step for step in steps
        if str(step.get("name", "")).startswith("Wednesday Golden — Generate")
    )
    env = generation["env"]
    for name in (
        "NB_CLOUDINARY_CLOUD_NAME",
        "NB_CLOUDINARY_API_KEY",
        "NB_CLOUDINARY_API_SECRET",
        "NB_WIX_API_KEY",
        "NB_ZERNIO_API_KEY",
    ):
        assert name in env
    for excluded in ("NB_META", "NB_THREADS", "NB_TELEGRAM"):
        assert excluded not in json.dumps(env)


def test_exactly_one_authoritative_scheduled_wednesday_publisher():
    owners = []
    for name in ("wednesday_golden.yml", "scheduled_publish.yml", "research_generate_and_publish.yml"):
        if any(_fires_on(cron, "3") for cron in _schedule(_workflow(name))):
            owners.append(name)
    assert owners == ["wednesday_golden.yml"]

    # Daily discovery still fires, but its optional non-canonical publication
    # is deterministically disabled on Wednesday local time.
    daily = Path(".github/workflows/daily_signal_research.yml").read_text()
    assert 'TZ=America/New_York date +%u)" = "3"' in daily
    assert "export NB_RESEARCH_PUBLISH_ENABLED=false" in daily


def test_legacy_owners_remove_only_wednesday_and_preserve_other_days():
    assert _schedule(_workflow("scheduled_publish.yml")) == [
        "0 10 * * 5",
        "0 11 * * 5",
    ]
    assert _schedule(_workflow("research_generate_and_publish.yml")) == [
        "0 7 * * 5,0"
    ]
    schedule = yaml.safe_load(Path("config/schedule.yaml").read_text())["schedule"]
    assert schedule["days"] == ["friday"]
    assert schedule["time"] == "06:00"
    assert schedule["timezone"] == "America/New_York"

    visibility = _workflow("visibility_publish.yml")
    assert _schedule(visibility) == ["0 7 * * 2", "0 7 * * 4"]
    assert "wednesday" not in Path(
        ".github/workflows/visibility_publish.yml"
    ).read_text().lower()


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2026, 8, 26, 6, 0, tzinfo=ET), True),
        (datetime(2026, 1, 7, 6, 0, tzinfo=ET), True),
        (datetime(2026, 8, 26, 6, 40, tzinfo=ET), True),
        (datetime(2026, 8, 26, 5, 30, tzinfo=ET), False),
        (datetime(2026, 8, 26, 7, 30, tzinfo=ET), False),
        (datetime(2026, 8, 24, 6, 0, tzinfo=ET), False),
    ],
)
def test_wednesday_dst_window(moment, expected):
    assert is_due(moment, day="wednesday", time="06:00")[0] is expected


def test_due_check_not_due_and_manual_force_are_unambiguous():
    with mock.patch.object(
        due_check,
        "datetime",
        mock.Mock(now=lambda tz: datetime(2026, 8, 24, 6, 0, tzinfo=tz)),
    ):
        assert due_check.main(
            ["--day", "wednesday", "--time", "06:00", "--timezone", "America/New_York"]
        ) == NOT_DUE
    assert due_check.main(
        [
            "--day", "wednesday", "--time", "06:00",
            "--timezone", "America/New_York", "--force",
        ]
    ) == 0


def test_wednesday_reuses_shared_eligibility_and_consumption_without_monday_policy():
    text = WORKFLOW.read_text()
    assert "data/research/published_signal_ids.txt" in text
    assert "wednesday_published_signal_ids.txt" not in text
    assert "monday_selection" not in text
    # #211: the shared eligibility selector is gone from the Wednesday path.
    # It reads the shared research store, which the 2026-07-21 supply changes
    # retargeted at small-business feeds — the regression #206 identified.
    # Wednesday now discovers its own signal inside the entrypoint, so the
    # workflow must NOT reach the shared selector or its audit artifact.
    assert "select_eligible_signal.py" not in text
    assert "wednesday_selection.json" not in text
    assert '--editorial-role "$WEDNESDAY_ROLE"' in text
    assert "never-blank-monday" not in text
    # the shared consumption marker is still canonical infrastructure and is
    # deliberately unchanged: a signal published once is never eligible again
    assert "wednesday_signal_id=" in text


def _signal(signal_id: str) -> dict[str, str]:
    return {
        "SIGNAL_ID": signal_id,
        "HEADLINE": f"Documented case {signal_id}",
        "CORE_FACT": "A documented decision changed one operating assumption.",
        "SOURCE_URL": f"https://source.example/{signal_id}",
    }


def _write_selection_inputs(tmp_path, signal_ids: tuple[str, ...]):
    active = tmp_path / "signals_active.jsonl"
    active.write_text(
        "".join(json.dumps(_signal(signal_id)) + "\n" for signal_id in signal_ids)
    )
    return active, tmp_path / "published_signal_ids.txt"


class _EligibleTransport:
    def complete(self, *, instructions: str, request: str) -> str:
        return json.dumps(
            {"eligible": True, "reason": "Documented Wednesday source class."}
        )


def test_shared_consumption_hides_a_monday_published_signal_from_wednesday(tmp_path):
    active, published = _write_selection_inputs(tmp_path, ("shared-case", "next-case"))
    published.write_text("shared-case\n")

    candidates = select_eligible_signal._load_candidates(active, published)

    assert [item["SIGNAL_ID"] for item in candidates] == ["next-case"]


def test_wednesday_consumption_is_visible_to_other_canonical_selectors(tmp_path):
    active, published = _write_selection_inputs(tmp_path, ("wednesday-case",))
    published.write_text("wednesday-case\n")

    assert select_eligible_signal._load_candidates(active, published) == []
    for workflow_name in (
        "monday_publish.yml",
        "research_generate_and_publish.yml",
        "wednesday_golden.yml",
    ):
        assert "data/research/published_signal_ids.txt" in Path(
            ".github/workflows", workflow_name
        ).read_text()


def test_blocked_wednesday_does_not_consume_and_explicit_retry_remains_possible(
    tmp_path,
):
    active, published = _write_selection_inputs(tmp_path, ("blocked-case",))
    audit = tmp_path / "selection.json"

    code = select_eligible_signal.main(
        [
            "--editorial-role", ROLE_ID,
            "--signal-id", "blocked-case",
            "--active-path", str(active),
            "--published-path", str(published),
            "--audit-out", str(audit),
        ],
        transport=_EligibleTransport(),
    )

    assert code == 0
    assert json.loads(audit.read_text())["selected_signal_id"] == "blocked-case"
    assert not published.exists()  # selection/gates never consume; success step does
    mark_step = next(
        step for step in _workflow("wednesday_golden.yml")["jobs"]
        ["wednesday-golden"]["steps"]
        if step.get("name") == "Mark signal as published"
    )
    assert "success()" in mark_step["if"]
    assert "inputs.dry_run != 'true'" in mark_step["if"]


def test_explicit_retry_cannot_pretend_a_consumed_signal_is_unused(tmp_path):
    active, published = _write_selection_inputs(tmp_path, ("published-case",))
    published.write_text("published-case\n")

    code = select_eligible_signal.main(
        [
            "--editorial-role", ROLE_ID,
            "--signal-id", "published-case",
            "--active-path", str(active),
            "--published-path", str(published),
        ],
        transport=_EligibleTransport(),
    )

    assert code == 1


def test_wednesday_semantics_do_not_leak_into_frozen_universal_modules():
    frozen_paths = [
        Path("scripts/generate_and_publish.py"),
        *Path("src/editorial").glob("*.py"),
        *Path("src/strategy").glob("*.py"),
        Path("src/intake/assignment_record.py"),
    ]
    forbidden = (
        "never-blank-wednesday-golden",
        "wednesday golden",
        "obvious reading x",
        "overlooked y",
        "5 lessons from x",
    )
    for path in frozen_paths:
        text = path.read_text(encoding="utf-8").lower()
        assert not any(term in text for term in forbidden), path


def test_wednesday_workflow_does_not_import_monday_product_policy():
    text = WORKFLOW.read_text().lower()
    assert "never-blank-monday-documented-case" not in text
    assert "monday_selection" not in text
    assert "monday_publish" not in text
    assert "small-business evidence" not in text
    assert Path(".github/workflows/monday_publish.yml").exists()


# ===========================================================================
# Issue #203: the social CTA invites in prose; the system owns the destination
#
# The Wednesday audit found the LinkedIn prompt carrying two instructions no
# output could satisfy at once — "invite the reader to continue at
# <landing page>" against #196's "never write any URL in the post". Following
# the first put a competing URL in the body, which the social-lineage gate
# then refused *after* Wix had already published. Wednesday keeps its CTA;
# only the destination moved to the system.
# ===========================================================================


def _wednesday_linkedin_prompt():
    """The prompt the entrypoint actually composes for the social surface."""
    from src.editorial.sources_of_record import render_sources_of_record
    from src.strategy.execution_context import StrategyExecutionContext
    from tests.test_monday_stream import _research_artifact

    configuration = load_business_strategy_configuration(BUSINESS_CONFIG)
    _, role = resolve_editorial_role(configuration, ROLE_ID)
    execution = StrategyExecutionContext.from_configuration(configuration)
    rules = (
        render_editorial_role_rules(role, surface="linkedin")
        + render_sources_of_record(_research_artifact(), surface="linkedin")
    )
    return _build_user_prompt(
        {"hook": "h", "discovery": {}, "echo_line": "E.", "cta_line": "Continue."},
        "medium", role.cta_mode or "reflection",
        _linkedin_rules(execution.linkedin), editorial_role_rules=rules,
        closing_contract=role.closing_contract,
    )


def test_the_social_prompt_names_no_destination_url():
    import re

    prompt = _wednesday_linkedin_prompt()
    offending = [
        line.strip() for line in prompt.splitlines()
        if re.search(r"https?://", line)
    ]
    assert offending == [], offending


def test_the_social_prompt_still_asks_for_invitation_prose():
    # the CTA behaviour is kept — only the URL moved to the system
    prompt = _wednesday_linkedin_prompt().lower()
    assert "invite the reader onward in prose" in prompt
    assert "appended by the system after publication" in prompt
    # and a supplied CTA line carrying a URL has an unambiguous instruction
    assert "keep its invitation prose and leave the url out" in prompt


def test_wednesday_keeps_its_cta_mode():
    configuration = load_business_strategy_configuration(BUSINESS_CONFIG)
    _, role = resolve_editorial_role(configuration, ROLE_ID)
    # deliberately NOT switched to "none" — Wednesday still invites
    assert role.cta_mode is None          # inherits the strategy default
    assert role.closing_contract == "invitation_last"


def test_the_article_surface_still_owns_its_destination():
    # the correction is social-scoped: the Wix invitation is untouched
    channels = json.loads(BUSINESS_CONFIG.read_text())["channels"]
    assert any("inneros.online" in rule for rule in channels["wix"]["cta_rules"])
    assert not any("http" in rule for rule in channels["linkedin"]["cta_rules"])
    assert not any("http" in rule for rule in channels["linkedin"]["link_rules"])


def test_the_landing_page_url_would_still_fail_the_lineage_gate():
    # the #196 gate is untouched — this is why the contradiction mattered
    from src.editorial.source_transparency import (
        SocialLineageError,
        validate_social_lineage,
    )
    from src.publishing.formatting import append_canonical_article_link

    canonical = f"{SITE}/post/a-wednesday-article"
    body = append_canonical_article_link(
        "Post prose.\n\nContinue at https://www.inneros.online.\n\n"
        "Never Blank: an adapted close.",
        canonical,
    )
    with pytest.raises(SocialLineageError):
        validate_social_lineage(social_body=body, canonical_url=canonical)
    # while the corrected shape — prose CTA, one system-supplied link — passes
    clean = append_canonical_article_link(
        "Post prose.\n\nIf that pattern is familiar, it is worth a look.\n\n"
        "Never Blank: an adapted close.",
        canonical,
    )
    validate_social_lineage(social_body=clean, canonical_url=canonical)


def test_monday_social_prompt_is_unaffected():
    from src.editorial.sources_of_record import render_sources_of_record
    from src.strategy.execution_context import StrategyExecutionContext
    from tests.test_monday_stream import MONDAY_ROLE, _research_artifact

    configuration = load_business_strategy_configuration(BUSINESS_CONFIG)
    _, role = resolve_editorial_role(configuration, MONDAY_ROLE)
    execution = StrategyExecutionContext.from_configuration(configuration)
    assert role.cta_mode == "none"          # Monday's own contract untouched
    rules = (
        render_editorial_role_rules(role, surface="linkedin")
        + render_sources_of_record(_research_artifact(), surface="linkedin")
    )
    prompt = _build_user_prompt(
        {"hook": "h", "discovery": {}, "echo_line": "E."},
        "medium", role.cta_mode, _linkedin_rules(execution.linkedin),
        editorial_role_rules=rules, closing_contract=role.closing_contract,
    )
    import re

    assert not re.search(r"https?://", prompt)
