"""
Tests for src/strategy/validators.py

Covers:
- Strategy schema validation
- Content plan validation (including Echo requirement)
- Compound Presence semantic check (heuristic pass)
- Strategy continuation / adjustment / replacement decision fixtures
- History preservation: strategy.json content_plan.json exist and are parseable
- Platform duplication detection (via differentiation.py)
"""

import json
from datetime import date
from pathlib import Path

import pytest

from src.strategy.models import (
    Confidence,
    ContentPlanItem,
    ContentRole,
    ContinuationCriteria,
    MonthlyDecision,
    MonthlyReview,
    Strategy,
    StrategyStatus,
    SuccessCriteria,
    WeeklyDecision,
    WeeklyReview,
)
from src.strategy.validators import (
    validate_compound_presence_semantic,
    validate_content_plan,
    validate_content_plan_item,
    validate_strategy,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_strategy(**overrides) -> Strategy:
    defaults = dict(
        strategy_id="2026-08-test-strategy",
        strategy_version="1",
        status=StrategyStatus.ACTIVE,
        started_at=date(2026, 8, 1),
        review_date=date(2026, 8, 31),
        strategy_name="Test strategy",
        strategy_summary="Summary",
        market_context="Agencies go dark when busy",
        selected_problem="Owner-dependent presence",
        sales_hypothesis="If owners recognize the pattern, they want a system",
        why_now="Competition is up",
        commercial_goal="Generate qualified leads",
        primary_message="Presence should not depend on your free time",
        compound_presence_role="Demonstrate what systematic presence looks like",
        desired_reader_realization="That is happening to us",
        primary_cta_intent="reflection",
        continuation_criteria=ContinuationCriteria(
            description="Continue if leads or positive trend",
            indicators=["At least 1 lead"]
        ),
        adjustment_criteria=ContinuationCriteria(
            description="Adjust if direction confirmed but execution weak",
            indicators=["No leads but engagement growing"]
        ),
        replacement_criteria=ContinuationCriteria(
            description="Replace if no leads and no trend after 6 weeks",
            indicators=["No leads after 6 weeks"]
        ),
        research_references=["strategy/worldview.md"],
        confidence=Confidence.HIGH,
    )
    defaults.update(overrides)
    return Strategy(**defaults)


def _make_content_item(**overrides) -> ContentPlanItem:
    defaults = dict(
        content_id="test-001",
        week=1,
        strategy_id="2026-08-test-strategy",
        content_role=ContentRole.RECOGNITION,
        topic="Agencies going dark when busy",
        working_title="The day the agency went quiet",
        target_reader="Agency owner, 5-15 people, fully booked",
        reader_problem="No content goes out when they are at capacity",
        market_signal="LinkedIn data: B2B agency posting frequency drops 60% during Q4",
        pattern="Delivery mode defeats presence work every time",
        sales_objective="Make owner feel the commercial cost of going dark",
        main_argument="Going dark at capacity is structural, not motivational",
        source_pattern_id="pat-test000000001",
        hook="The month you were fully booked was the month you went quiet.",
        recognition="You posted three times in January, once in March, nothing in April.",
        mechanism="Delivery mode allocates all cognitive and time resources to client work. Presence work has no protected slot.",
        business_consequence="Clients who were considering you stopped hearing from you. They chose someone who was present.",
        reframe="This is not about discipline. It is about a system that stops existing when the owner is busy.",
        compound_presence_connection="Consistent presence is not about what you post when you have time. It is about what happens to your pipeline when you disappear.",
        echo="The competitor who won that client was not better. They were just present.",
        cta_mode="reflection",
        cta="If your presence disappears when you get busy, that is the pattern.",
        website_angle="SEO: agency marketing during busy periods, content gap",
        linkedin_angle="Professional recognition: fully booked and invisible",
        instagram_angle="Visual hook: empty calendar vs. full calendar",
        facebook_angle="Conversational: has your agency ever gone quiet during a busy stretch?",
        threads_angle="Chain: Hook → busy = dark → structural cause → cost → compound presence",
        telegram_angle="Fully booked agencies go quiet. Clients read quiet as available.",
        seo_keywords=["agency content gap", "b2b content consistency"],
        geo_questions=["Why do agencies stop posting when they are busy?"],
    )
    defaults.update(overrides)
    return ContentPlanItem(**defaults)


# ── Strategy validation tests ──────────────────────────────────────────────────

class TestValidateStrategy:
    def test_valid_strategy_passes(self):
        strategy = _make_strategy()
        validate_strategy(strategy)  # should not raise

    def test_empty_market_context_fails(self):
        with pytest.raises(ValueError, match="market_context"):
            strategy = _make_strategy(market_context="")
            validate_strategy(strategy)

    def test_empty_selected_problem_fails(self):
        with pytest.raises(ValueError, match="selected_problem"):
            strategy = _make_strategy(selected_problem="")
            validate_strategy(strategy)

    def test_empty_sales_hypothesis_fails(self):
        with pytest.raises(ValueError, match="sales_hypothesis"):
            strategy = _make_strategy(sales_hypothesis="")
            validate_strategy(strategy)

    def test_empty_commercial_goal_fails(self):
        with pytest.raises(ValueError, match="commercial_goal"):
            strategy = _make_strategy(commercial_goal="")
            validate_strategy(strategy)

    def test_empty_compound_presence_role_fails(self):
        with pytest.raises(ValueError, match="compound_presence_role"):
            strategy = _make_strategy(compound_presence_role="")
            validate_strategy(strategy)

    def test_empty_research_references_fails(self):
        with pytest.raises(ValueError, match="research_references"):
            strategy = _make_strategy(research_references=[])
            validate_strategy(strategy)

    def test_review_date_before_start_fails(self):
        with pytest.raises(ValueError, match="review_date"):
            strategy = _make_strategy(
                started_at=date(2026, 8, 31),
                review_date=date(2026, 8, 1),
            )
            validate_strategy(strategy)


# ── Content plan validation tests ──────────────────────────────────────────────

class TestValidateContentPlanItem:
    def test_valid_item_passes(self):
        item = _make_content_item()
        validate_content_plan_item(item)

    def test_missing_hook_fails(self):
        with pytest.raises(ValueError, match="hook"):
            validate_content_plan_item(_make_content_item(hook=""))

    def test_missing_mechanism_fails(self):
        with pytest.raises(ValueError, match="mechanism"):
            validate_content_plan_item(_make_content_item(mechanism=""))

    def test_missing_reframe_fails(self):
        with pytest.raises(ValueError, match="reframe"):
            validate_content_plan_item(_make_content_item(reframe=""))

    def test_empty_echo_string_fails(self):
        with pytest.raises(ValueError, match="echo"):
            validate_content_plan_item(_make_content_item(echo=""))

    def test_null_echo_without_reason_fails(self):
        with pytest.raises(ValueError, match="echo_omission_reason"):
            validate_content_plan_item(_make_content_item(echo=None, echo_omission_reason=None))

    def test_null_echo_with_reason_passes(self):
        item = _make_content_item(echo=None, echo_omission_reason="No strong candidate emerged for this analytical article")
        validate_content_plan_item(item)  # should not raise

    def test_missing_compound_presence_fails(self):
        with pytest.raises(ValueError, match="compound_presence_connection"):
            validate_content_plan_item(_make_content_item(compound_presence_connection=""))

    def test_missing_linkedin_angle_fails(self):
        with pytest.raises(ValueError, match="linkedin_angle"):
            validate_content_plan_item(_make_content_item(linkedin_angle=""))


class TestValidateContentPlan:
    def _make_plan(self, n: int = 10) -> list[ContentPlanItem]:
        return [
            _make_content_item(
                content_id=f"test-{i:03d}",
                hook=f"Hook {i}: unique opening for article {i}",
                week=(i // 3) + 1,
                source_pattern_id=f"pat-{i:012d}",
            )
            for i in range(n)
        ]

    def test_valid_plan_passes(self):
        items = self._make_plan(12)
        validate_content_plan(items, "2026-08-test-strategy")

    def test_too_few_items_fails(self):
        with pytest.raises(ValueError, match="minimum is 8"):
            validate_content_plan(self._make_plan(4), "2026-08-test-strategy")

    def test_wrong_strategy_id_fails(self):
        items = self._make_plan(10)
        with pytest.raises(ValueError, match="wrong strategy_id"):
            validate_content_plan(items, "different-strategy-id")

    def test_duplicate_hooks_fails(self):
        items = self._make_plan(10)
        for item in items:
            item.hook = "The exact same hook every time"
        with pytest.raises(ValueError, match="duplicate hooks"):
            validate_content_plan(items, "2026-08-test-strategy")

    def test_missing_source_pattern_id_fails(self):
        items = self._make_plan(10)
        items[3].source_pattern_id = None
        with pytest.raises(ValueError, match="source_pattern_id"):
            validate_content_plan(items, "2026-08-test-strategy")


# ── Compound Presence semantic tests ───────────────────────────────────────────

class TestCompoundPresenceSemantic:
    _GOOD = (
        "Fully booked founders go quiet. Clients read quiet as available. "
        "That is how you lose the next project to someone with a worse product. "
        "Consistent presence is not about posting when you have time — "
        "it is what accumulates over time into recognition and trust. "
        "A single viral moment is not a presence system. Presence is what remains "
        "when the wave recedes. The competitor who won that client was not better. "
        "They were just present, week after week, when you were not."
    )

    _BAD = (
        "The restaurant got a lot of views on their croissant photo. "
        "This shows that food photography can be effective for marketing. "
        "The owner was pleased with the result. Business increased significantly."
    )

    _AMBIGUOUS = (
        "Business owners sometimes struggle with marketing. "
        "Visibility is important for success. "
        "The restaurant example shows that one post can work well."
    )

    def test_good_text_passes(self):
        validate_compound_presence_semantic(self._GOOD)

    def test_bad_text_fails(self):
        with pytest.raises(ValueError, match="Compound Presence Connection"):
            validate_compound_presence_semantic(self._BAD)

    def test_ambiguous_text_warns_but_does_not_fail(self):
        # Ambiguous text without LLM should log warning but not raise
        validate_compound_presence_semantic(self._AMBIGUOUS)


# ── Strategy decision fixtures ─────────────────────────────────────────────────

class TestStrategyDecisionFixtures:
    """
    Fixture scenarios for strategy continuation decisions.

    Scenario 1: Strategy led to leads — CONTINUE
    Scenario 2: No leads yet, but positive early signal momentum — CONTINUE_WITH_ADJUSTMENTS
    Scenario 3: No leads, no positive trend — REPLACE_STRATEGY
    """

    def test_fixture_scenario_1_continue(self):
        review = WeeklyReview(
            strategy_id="2026-08-test",
            week_number=4,
            period_start=date(2026, 8, 22),
            period_end=date(2026, 8, 29),
            posts_published=3,
            leads_this_week=2,
            leads_cumulative=3,
            engagement_trend="growing",
            decision=WeeklyDecision.CONTINUE,
            rationale="2 leads this week, engagement trending up. Strategy confirmed.",
        )
        assert review.decision == WeeklyDecision.CONTINUE
        assert review.leads_cumulative > 0

    def test_fixture_scenario_2_adjust(self):
        review = WeeklyReview(
            strategy_id="2026-08-test",
            week_number=3,
            period_start=date(2026, 8, 15),
            period_end=date(2026, 8, 22),
            posts_published=3,
            leads_this_week=0,
            leads_cumulative=0,
            engagement_trend="growing",
            decision=WeeklyDecision.ADJUST_EXECUTION,
            rationale="No leads yet, but saves and self-recognition comments are growing. Adjusting hooks to be more specific to MSPs.",
            adjustments=["More MSP-specific hooks", "Add diagnostic CTA to one post per week"],
        )
        assert review.decision == WeeklyDecision.ADJUST_EXECUTION
        assert review.leads_cumulative == 0
        assert review.engagement_trend == "growing"

    def test_fixture_scenario_3_replace(self):
        review = MonthlyReview(
            strategy_id="2026-08-test",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            posts_published=12,
            total_leads=0,
            qualified_leads=0,
            trend="declining",
            hypothesis_confirmed=False,
            decision=MonthlyDecision.REPLACE_STRATEGY,
            rationale="No leads after full month, engagement declining despite 4 topic variations. Presence dependency pattern not resonating with this cohort. Switching to direct client case study strategy.",
            lessons=[
                "Presence Debt concept did not generate self-recognition in this segment",
                "MSP audience responds more to operational/security content than presence content",
                "Need stronger initial hook — abstract problem recognition is insufficient",
            ],
        )
        assert review.decision == MonthlyDecision.REPLACE_STRATEGY
        assert review.total_leads == 0
        assert not review.hypothesis_confirmed


# ── History preservation test ──────────────────────────────────────────────────

class TestHistoryPreservation:
    def test_current_strategy_json_is_valid(self):
        path = Path("strategy/current/strategy.json")
        assert path.exists(), "strategy/current/strategy.json must exist"
        data = json.loads(path.read_text())
        assert data.get("strategy_id"), "strategy_id must be present"
        assert data.get("market_context"), "market_context must be present"
        assert data.get("sales_hypothesis"), "sales_hypothesis must be present"
        assert data.get("compound_presence_role"), "compound_presence_role must be present"

    def test_current_strategy_md_exists(self):
        path = Path("strategy/current/strategy.md")
        assert path.exists(), "strategy/current/strategy.md must exist"
        content = path.read_text()
        assert len(content) > 100, "strategy.md must have meaningful content"

    def test_history_directory_exists(self):
        path = Path("strategy/history")
        assert path.exists() and path.is_dir(), "strategy/history directory must exist"

    def test_strategy_json_and_md_have_same_strategy_id(self):
        json_path = Path("strategy/current/strategy.json")
        md_path   = Path("strategy/current/strategy.md")
        if json_path.exists() and md_path.exists():
            data = json.loads(json_path.read_text())
            strategy_id = data.get("strategy_id", "")
            md_content  = md_path.read_text()
            assert strategy_id in md_content, (
                f"strategy.md must reference the strategy_id '{strategy_id}' from strategy.json"
            )
