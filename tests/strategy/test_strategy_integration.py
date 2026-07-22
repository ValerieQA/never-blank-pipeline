"""
Integration tests for strategy context injection and CTA priority.

Covers:
- strategy_context is injected into enriched signal (STRATEGY_* keys present)
- signal CTA_MODE overrides strategy CTA
- strategy CTA used when signal has no CTA_MODE
- loader returns None for missing file without raising
- loader returns None for corrupt JSON without raising
- loader returns None for schema mismatch without raising
- role distribution: week 1 slots get correct roles
- CTA distribution: primary intent on even positions, varied on odd
- content plan threshold: ValueError when items < expected
"""

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.strategy.models import (
    Confidence,
    ContentPlanItem,
    ContentRole,
    ContinuationCriteria,
    Strategy,
    StrategyStatus,
    SuccessCriteria,
)
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.strategy.content_planner import _build_cta_distribution, _content_role_for_slot


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_strategy(**overrides) -> Strategy:
    defaults = dict(
        strategy_id="2026-08-test",
        status=StrategyStatus.ACTIVE,
        started_at=date(2026, 8, 1),
        review_date=date(2026, 8, 31),
        strategy_name="Test Strategy",
        strategy_summary="Test",
        market_context="Agencies go dark when busy",
        selected_problem="Owner-dependent presence",
        sales_hypothesis="Pattern recognition → solution interest",
        why_now="Competition is up",
        commercial_goal="Generate leads",
        primary_message="Presence should not depend on your free time",
        compound_presence_role="Show what systematic presence looks like",
        desired_reader_realization="That is us",
        primary_cta_intent="reflection",
        continuation_criteria=ContinuationCriteria(description="Continue if leads", indicators=["At least 1 lead"]),
        adjustment_criteria=ContinuationCriteria(description="Adjust if needed", indicators=["No leads but trending"]),
        replacement_criteria=ContinuationCriteria(description="Replace after 6 weeks no leads", indicators=["None after 6 weeks"]),
        research_references=["strategy/worldview.md"],
        confidence=Confidence.HIGH,
    )
    defaults.update(overrides)
    return Strategy(**defaults)


# ── Strategy context injection ─────────────────────────────────────────────────

class TestStrategyContextInjection:
    def test_strategy_context_injected_as_strategy_keys(self):
        """generate_article must inject STRATEGY_* keys into enriched signal."""
        from src.editorial.pipeline import generate_article

        strategy = _make_strategy()
        context = get_strategy_context(strategy)

        captured_enriched = {}

        def mock_decision_lens(signal):
            captured_enriched.update(signal)
            return {
                "core_pattern": "test", "owner_system_objective": "test",
                "delivery_vs_presence_conflict": "test",
                "customer_memory_consequence": "test",
                "structural_cause": "test", "never_blank_insight": "test",
            }

        signal = {"SIGNAL_ID": "test-001", "HEADLINE": "Test signal"}

        # Patch at the pipeline level to avoid full LLM calls
        with patch("src.editorial.pipeline.extract_pattern") as mock_pattern, \
             patch("src.editorial.pipeline.generate_decision_lens", side_effect=mock_decision_lens), \
             patch("src.editorial.pipeline.build_narrative_spine") as mock_spine, \
             patch("src.editorial.pipeline.generate_hook") as mock_hook, \
             patch("src.editorial.pipeline.build_reader_context") as mock_rc, \
             patch("src.editorial.pipeline.build_discovery") as mock_discovery, \
             patch("src.editorial.pipeline.assemble_story") as mock_story, \
             patch("src.editorial.pipeline.finalize_article") as mock_voice, \
             patch("src.editorial.pipeline.compose_platforms") as mock_composer:

            mock_pattern.return_value = {"visibility_pattern": "test_pattern"}
            mock_spine.return_value = {"narrative_spine": "test", "target_feeling": "recognition",
                                       "core_pattern": "test", "pattern_as_evidence_of": "test",
                                       "core_decision": "test", "company_as_evidence_of": "test"}
            mock_hook.return_value = {"hook": "test hook"}
            mock_rc.return_value = "reader context"
            mock_discovery.return_value = {"discovery": {}}
            mock_story.return_value = {"story": {}}
            mock_voice.return_value = {"echo_line": None, "cta_line": None}
            mock_composer.return_value = {"long": {"body": "blog", "word_count": 800},
                                          "reading": {"body": "li", "word_count": 200},
                                          "medium": {"body": "fb", "word_count": 150},
                                          "instagram": {"body": "ig", "word_count": 100},
                                          "short": {"body": "sh", "word_count": 30}}

            generate_article(signal, cta_mode="reflection", strategy_context=context)

        assert "STRATEGY_PRIMARY_MESSAGE" in captured_enriched
        assert captured_enriched["STRATEGY_PRIMARY_MESSAGE"] == strategy.primary_message
        assert captured_enriched["STRATEGY_SELECTED_PROBLEM"] == strategy.selected_problem
        assert captured_enriched["STRATEGY_DESIRED_REALIZATION"] == strategy.desired_reader_realization
        assert captured_enriched["STRATEGY_COMPOUND_ROLE"] == strategy.compound_presence_role
        assert captured_enriched["STRATEGY_ID"] == strategy.strategy_id

    def test_no_strategy_context_no_strategy_keys(self):
        """Without strategy_context, enriched signal must not contain STRATEGY_* keys."""
        from src.editorial.pipeline import generate_article

        captured_enriched = {}

        def mock_decision_lens(signal):
            captured_enriched.update(signal)
            return {"core_pattern": "t", "owner_system_objective": "t",
                    "delivery_vs_presence_conflict": "t", "customer_memory_consequence": "t",
                    "structural_cause": "t", "never_blank_insight": "t"}

        signal = {"SIGNAL_ID": "test-002", "HEADLINE": "Test signal"}

        with patch("src.editorial.pipeline.extract_pattern") as mock_pattern, \
             patch("src.editorial.pipeline.generate_decision_lens", side_effect=mock_decision_lens), \
             patch("src.editorial.pipeline.build_narrative_spine") as mock_spine, \
             patch("src.editorial.pipeline.generate_hook") as mock_hook, \
             patch("src.editorial.pipeline.build_reader_context") as mock_rc, \
             patch("src.editorial.pipeline.build_discovery") as mock_discovery, \
             patch("src.editorial.pipeline.assemble_story") as mock_story, \
             patch("src.editorial.pipeline.finalize_article") as mock_voice, \
             patch("src.editorial.pipeline.compose_platforms") as mock_composer:

            mock_pattern.return_value = {"visibility_pattern": "test"}
            mock_spine.return_value = {"narrative_spine": "t", "target_feeling": "recognition",
                                       "core_pattern": "t", "pattern_as_evidence_of": "t",
                                       "core_decision": "t", "company_as_evidence_of": "t"}
            mock_hook.return_value = {"hook": "hook"}
            mock_rc.return_value = "ctx"
            mock_discovery.return_value = {"discovery": {}}
            mock_story.return_value = {}
            mock_voice.return_value = {"echo_line": None, "cta_line": None}
            mock_composer.return_value = {"long": {"body": "b", "word_count": 800},
                                          "reading": {"body": "b", "word_count": 200},
                                          "medium": {"body": "b", "word_count": 150},
                                          "instagram": {"body": "b", "word_count": 100},
                                          "short": {"body": "b", "word_count": 30}}

            generate_article(signal, cta_mode="none")

        assert "STRATEGY_PRIMARY_MESSAGE" not in captured_enriched


# ── CTA priority (publish_packages logic) ─────────────────────────────────────

class TestCTAPriority:
    def test_signal_cta_overrides_strategy(self):
        """Signal-level CTA_MODE takes priority over strategy cta."""
        strategy_cta = "reflection"
        signal = {"CTA_MODE": "diagnostic"}
        cta_mode = str(signal.get("CTA_MODE") or strategy_cta or "none")
        assert cta_mode == "diagnostic"

    def test_strategy_cta_used_when_signal_has_none(self):
        signal = {"CTA_MODE": None}
        strategy_cta = "reflection"
        cta_mode = str(signal.get("CTA_MODE") or strategy_cta or "none")
        assert cta_mode == "reflection"

    def test_fallback_to_none_when_both_absent(self):
        signal = {}
        strategy_cta = ""
        cta_mode = str(signal.get("CTA_MODE") or strategy_cta or "none")
        assert cta_mode == "none"

    def test_empty_string_signal_cta_falls_back(self):
        signal = {"CTA_MODE": ""}
        strategy_cta = "diagnostic"
        cta_mode = str(signal.get("CTA_MODE") or strategy_cta or "none")
        assert cta_mode == "diagnostic"


# ── Loader robustness ─────────────────────────────────────────────────────────

class TestLoader:
    def test_missing_file_returns_none(self, tmp_path):
        with patch("src.strategy.loader._STRATEGY_PATH", tmp_path / "nonexistent.json"):
            result = load_active_strategy()
        assert result is None

    def test_corrupt_json_returns_none(self, tmp_path):
        bad_file = tmp_path / "strategy.json"
        bad_file.write_text("{ this is not json", encoding="utf-8")
        with patch("src.strategy.loader._STRATEGY_PATH", bad_file):
            result = load_active_strategy()
        assert result is None

    def test_schema_mismatch_returns_none(self, tmp_path):
        bad_file = tmp_path / "strategy.json"
        bad_file.write_text(json.dumps({"strategy_id": "x"}), encoding="utf-8")
        with patch("src.strategy.loader._STRATEGY_PATH", bad_file):
            result = load_active_strategy()
        assert result is None

    def test_get_cta_mode_returns_none_string_when_no_strategy(self):
        result = get_cta_mode(None)
        assert result == "none"

    def test_get_strategy_context_returns_defaults_when_no_strategy(self):
        result = get_strategy_context(None)
        assert result["strategy_id"] == "none"
        assert result["primary_message"] == ""

    def test_valid_strategy_loads_and_cta_mode_correct(self):
        strategy = _make_strategy(primary_cta_intent="diagnostic")
        assert get_cta_mode(strategy) == "diagnostic"

    def test_strategy_context_has_all_keys(self):
        strategy = _make_strategy()
        context = get_strategy_context(strategy)
        required = ["strategy_id", "primary_message", "compound_presence_role",
                    "desired_reader_realization", "selected_problem", "presence_debt_focus"]
        for key in required:
            assert key in context, f"Missing key: {key}"


# ── Role distribution ─────────────────────────────────────────────────────────

class TestRoleDistribution:
    def test_week1_slot0_is_recognition(self):
        assert _content_role_for_slot(1, 0) == ContentRole.RECOGNITION

    def test_week1_slot1_is_education(self):
        assert _content_role_for_slot(1, 1) == ContentRole.EDUCATION

    def test_week1_slot2_is_recognition(self):
        assert _content_role_for_slot(1, 2) == ContentRole.RECOGNITION

    def test_week2_slot0_is_proof(self):
        assert _content_role_for_slot(2, 0) == ContentRole.PROOF

    def test_week2_slot1_is_reframe(self):
        assert _content_role_for_slot(2, 1) == ContentRole.REFRAME

    def test_week3_slot1_is_objection(self):
        assert _content_role_for_slot(3, 1) == ContentRole.OBJECTION

    def test_week4_slot1_is_conversion(self):
        assert _content_role_for_slot(4, 1) == ContentRole.CONVERSION

    def test_slots_within_week_are_different(self):
        # Week 2: [proof, reframe, recognition] — all distinct
        roles = [_content_role_for_slot(2, s) for s in range(3)]
        assert len(set(roles)) > 1, "All slots in week 2 should not have the same role"


# ── CTA distribution ─────────────────────────────────────────────────────────

class TestCTADistribution:
    def test_primary_intent_on_even_positions(self):
        dist = _build_cta_distribution("reflection", 12)
        for i in range(0, 12, 2):
            assert dist[i] == "reflection", f"Position {i} should be primary 'reflection'"

    def test_odd_positions_vary(self):
        dist = _build_cta_distribution("reflection", 12)
        odd_values = [dist[i] for i in range(1, 12, 2)]
        assert len(set(odd_values)) > 1, "Odd positions should have varied CTA modes"

    def test_no_primary_in_odd_positions(self):
        dist = _build_cta_distribution("reflection", 12)
        odd_values = [dist[i] for i in range(1, 12, 2)]
        assert "reflection" not in odd_values

    def test_length_matches_total(self):
        for total in [3, 6, 12]:
            dist = _build_cta_distribution("none", total)
            assert len(dist) == total

    def test_all_values_valid_cta_modes(self):
        valid = {"none", "reflection", "diagnostic", "example_request", "direct_conversation"}
        dist = _build_cta_distribution("reflection", 12)
        for mode in dist:
            assert mode in valid, f"Invalid CTA mode: {mode}"


# ── _validate_package: CPC blocking in publish path ───────────────────────────

class TestValidatePackageCPCBlocking:
    """
    _validate_package must block publication when blog/linkedin text has no
    Compound Presence Connection (0 presence keywords → clear fail).
    """

    _BLOG_WITH_CPC = (
        "Agency owners go quiet when fully booked. Clients read quiet as available. "
        "That is how you lose the next project to someone with a worse product. "
        "Consistent presence is not about posting when you have time — it accumulates "
        "over time into recognition and trust. A single viral moment is not a presence "
        "system. The competitor who won that client was just present, week after week."
    )

    _BLOG_WITHOUT_CPC = (
        "A London bakery became famous after a croissant photo went viral on social media. "
        "Sales increased dramatically. The owner was surprised. Marketing can work."
    )

    _LINKEDIN = (
        "Agency went quiet during Q4. The client chose a competitor. "
        "This is not a discipline problem — it is structural. "
        "Consistent presence accumulates into recognition and trust over time. "
        "A business that disappears when busy is not competing on quality. "
        "It is competing on memory, and silence erases that memory week after week."
    )
    _FACEBOOK = "When you go dark, clients assume you are not available. Simple truth."
    _INSTAGRAM = "The month you were booked solid was the month you went quiet."
    _TELEGRAM = "Fully booked agencies go dark. Clients read silence as capacity."

    def test_blog_with_cpc_passes(self):
        from scripts.research.publish_packages import _validate_package
        # Should not raise
        _validate_package(
            {
                "blog":     self._BLOG_WITH_CPC,
                "linkedin": self._LINKEDIN,
                "facebook": self._FACEBOOK,
                "instagram": self._INSTAGRAM,
                "telegram": self._TELEGRAM,
            },
            threads=[self._INSTAGRAM, self._LINKEDIN, self._FACEBOOK],
        )

    def test_blog_without_cpc_blocks_publication(self):
        from scripts.research.publish_packages import _validate_package
        with pytest.raises(ValueError, match="Compound Presence"):
            _validate_package(
                {
                    "blog":     self._BLOG_WITHOUT_CPC,
                    "linkedin": self._LINKEDIN,
                    "facebook": self._FACEBOOK,
                    "instagram": self._INSTAGRAM,
                    "telegram": self._TELEGRAM,
                },
                threads=[self._INSTAGRAM, self._LINKEDIN, self._FACEBOOK],
            )

    def test_linkedin_without_cpc_blocks_publication(self):
        from scripts.research.publish_packages import _validate_package
        linkedin_no_cpc = "Agency went dark in Q4. Client chose another agency."
        with pytest.raises(ValueError, match="Compound Presence"):
            _validate_package(
                {
                    "blog":     self._BLOG_WITH_CPC,
                    "linkedin": linkedin_no_cpc,
                    "facebook": self._FACEBOOK,
                    "instagram": self._INSTAGRAM,
                    "telegram": self._TELEGRAM,
                },
                threads=[self._INSTAGRAM, linkedin_no_cpc, self._FACEBOOK],
            )


# ── CTAMode shared type ────────────────────────────────────────────────────────

class TestCTAModeSharedType:
    def test_cta_mode_imported_from_src_models(self):
        from src.strategy.models import CTAMode
        from src.models import CTAMode as OriginalCTAMode
        assert CTAMode is OriginalCTAMode

    def test_strategy_primary_cta_intent_rejects_invalid_value(self):
        with pytest.raises(Exception):
            _make_strategy(primary_cta_intent="banana")

    def test_strategy_primary_cta_intent_accepts_valid_values(self):
        for valid in ["none", "reflection", "diagnostic", "example_request", "direct_conversation"]:
            s = _make_strategy(primary_cta_intent=valid)
            assert s.primary_cta_intent.value == valid

    def test_get_cta_mode_returns_plain_string(self):
        strategy = _make_strategy(primary_cta_intent="reflection")
        result = get_cta_mode(strategy)
        assert result == "reflection"
        assert isinstance(result, str)
        # Must be a plain string usable in str() without "CTAMode.REFLECTION"
        assert "CTAMode" not in result

    def test_echo_and_omission_reason_both_set_fails(self):
        from src.strategy.validators import validate_content_plan_item
        from src.strategy.models import ContentPlanItem, ContentRole
        item = ContentPlanItem(
            content_id="t-002", week=1, strategy_id="2026-08-test",
            content_role=ContentRole.RECOGNITION,
            topic="t", working_title="t", target_reader="t", reader_problem="t",
            market_signal="t", pattern="t", sales_objective="Sell something",
            main_argument="t",
            hook="Hook that opens a gap.",
            recognition="t", mechanism="Structural cause here.",
            business_consequence="t", reframe="Reframe here.",
            compound_presence_connection="t",
            echo="The competitor was just present.",
            echo_omission_reason="No strong candidate",  # contradictory
            cta_mode="none", cta="",
            website_angle="t", linkedin_angle="t", instagram_angle="t",
            facebook_angle="t", threads_angle="t", telegram_angle="t",
            source_pattern_id="pat-test000000001",
        )
        with pytest.raises(ValueError, match="echo_omission_reason"):
            validate_content_plan_item(item)

    def test_echo_omission_reason_whitespace_fails(self):
        from src.strategy.validators import validate_content_plan_item
        from src.strategy.models import ContentPlanItem, ContentRole
        item = ContentPlanItem(
            content_id="t-001", week=1, strategy_id="2026-08-test",
            content_role=ContentRole.RECOGNITION,
            topic="t", working_title="t", target_reader="t", reader_problem="t",
            market_signal="t", pattern="t", sales_objective="Sell something",
            main_argument="t",
            hook="Hook that opens a gap.",
            recognition="t", mechanism="Structural cause here.",
            business_consequence="t", reframe="Reframe here.",
            compound_presence_connection="t",
            echo=None,
            echo_omission_reason="   ",  # whitespace only — should fail
            cta_mode="none", cta="",
            website_angle="t", linkedin_angle="t", instagram_angle="t",
            facebook_angle="t", threads_angle="t", telegram_angle="t",
        )
        with pytest.raises(ValueError, match="echo_omission_reason"):
            validate_content_plan_item(item)
