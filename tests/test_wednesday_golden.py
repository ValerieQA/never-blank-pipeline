"""Issue #143 parallel phase: Never Blank Wednesday product contract.

These tests exercise the strict product profile, deterministic eligibility
boundary, the existing strict editorial-acceptance loader, and the real
platform prompt constructor. They intentionally do not claim that the profile
is selected or persisted by the canonical run yet: those integration points
reuse the generic seam currently under review in Issue #142.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

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


PROFILE_PATH = Path("config/never_blank/wednesday_golden.yaml")
RUBRIC_PATH = Path(
    "config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml"
)
FIXTURE_DIR = Path("tests/fixtures/golden_wednesday")
BUSINESS_CONFIG = Path("strategy/current/business_strategy.json")
WORKFLOW = Path(".github/workflows/wednesday_golden.yml")
SITE = "https://www.inneros.online"


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


# Declarative source eligibility for the pending generic selector -----------------


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
    assert policy.require_compound_presence_relevance is True
    assert policy.required_primary_mechanisms == 1
    assert policy.required_transfer_mode.value == "bounded_business_question"

    rendered = " ".join(profile.source_eligibility_rules()).lower()
    assert "obvious reading x" in rendered
    assert "overlooked y" in rendered
    assert "exactly one primary mechanism" in rendered
    assert "surprise or analogy alone is not eligibility" in rendered
    assert "outcome may transfer only as a bounded question" in rendered


def test_all_authorized_documented_source_classes_are_configured(profile):
    assert set(profile.source_policy.allowed_source_kinds) == set(SourceKind)


# Real existing prompt/acceptance consumers --------------------------------------


def test_golden_rules_reach_the_existing_wix_and_linkedin_prompt_constructor(profile):
    execution = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration(BUSINESS_CONFIG)
    )
    wix_rules = _wix_rules(execution.wix) + profile.generation_rules("wix")
    linkedin_rules = _linkedin_rules(execution.linkedin) + profile.generation_rules(
        "linkedin"
    )

    wix_prompt = _build_user_prompt(_article(), "long", profile.cta_id, wix_rules)
    linkedin_prompt = _build_user_prompt(
        _article(), "medium", profile.cta_id, linkedin_rules
    )

    for prompt in (wix_prompt, linkedin_prompt):
        assert "CONFIGURED CHANNEL RULES:" in prompt
        assert "obvious_reading_x" in prompt
        assert "overlooked_y" in prompt
        assert "evidence_for_y" in prompt
        assert "exactly one primary mechanism" in prompt
        assert "5 lessons from X" in prompt
        assert "3 takeaways" in prompt
        assert profile.text_shape.shared_discovery_key in prompt
        assert SITE in prompt
    assert "WIX rule:" in wix_prompt
    assert "LINKEDIN rule:" in linkedin_prompt


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


def test_prepared_workflow_is_manual_only_and_cannot_publish():
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert "schedule" not in workflow["on"]
    text = WORKFLOW.read_text()
    assert "generate_and_publish.py" not in text
    assert "scripts/publish.py" not in text
    assert "python3 -m pytest tests/test_wednesday_golden.py" in text


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
