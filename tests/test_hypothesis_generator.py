"""
Tests for src/investigation/hypothesis_generator.py

Covers:
- _compute_priority: deterministic, no LLM
- generate_hypothesis_space: with mocked LLM responses
- Toyota validation: "lacked capital" must get test_priority=1
- Schema enforcement: no hypothesis passes without priority_reason
- Priority_reason validation: "model judgment" is rejected
- Sorting: destroys_main_narrative always first
"""

import json
import pytest
from unittest.mock import patch

from src.investigation.hypothesis_generator import (
    Hypothesis,
    _compute_priority,
    generate_hypothesis_space,
    select_for_testing,
    build_hypothesis_space,
)


# --- _compute_priority: pure function, no mocking needed ---

class TestComputePriority:
    def test_destroys_is_priority_1(self):
        assert _compute_priority("destroys_main_narrative", "low") == 1
        assert _compute_priority("destroys_main_narrative", "medium") == 1
        assert _compute_priority("destroys_main_narrative", "high") == 1

    def test_weakens_is_priority_2(self):
        assert _compute_priority("weakens_main_narrative", "low") == 2
        assert _compute_priority("weakens_main_narrative", "high") == 2

    def test_orthogonal_low_is_priority_3(self):
        assert _compute_priority("orthogonal", "low") == 3

    def test_orthogonal_medium_high_is_priority_4(self):
        assert _compute_priority("orthogonal", "medium") == 4
        assert _compute_priority("orthogonal", "high") == 4

    def test_supports_is_priority_5(self):
        assert _compute_priority("supports_main_narrative", "low") == 5
        assert _compute_priority("supports_main_narrative", "high") == 5

    def test_destroys_beats_supports_regardless_of_distance(self):
        assert _compute_priority("destroys_main_narrative", "high") < \
               _compute_priority("supports_main_narrative", "low")

    def test_cost_does_not_override_impact(self):
        # A "cheap" orthogonal hypothesis must not beat a "costly" destroys hypothesis
        priority_destroys_high = _compute_priority("destroys_main_narrative", "high")
        priority_orthogonal_low = _compute_priority("orthogonal", "low")
        assert priority_destroys_high < priority_orthogonal_low


# --- Helpers for mocking LLM responses ---

def _make_llm_response(hypotheses: list[dict]) -> str:
    return json.dumps({"hypotheses": hypotheses})


TOYOTA_Q3_HYPOTHESES = [
    {
        "hypothesis": "Toyota could not afford full EV transition",
        "if_true_impact": "destroys_main_narrative",
        "distance_from_signal": "medium",
        "priority_reason": (
            "If true, this would mean Toyota had no real choice, making destroys_main_narrative "
            "the correct impact level — the deliberate-strategy narrative requires agency."
        ),
    },
    {
        "hypothesis": "Manufacturing lock-in forced Toyota to stay with hybrids",
        "if_true_impact": "weakens_main_narrative",
        "distance_from_signal": "medium",
        "priority_reason": (
            "If true, the strategic-choice framing requires significant qualification, "
            "so weakens_main_narrative applies — choice was partly forced."
        ),
    },
    {
        "hypothesis": "Toyota believed BEV adoption was infrastructure-constrained",
        "if_true_impact": "orthogonal",
        "distance_from_signal": "low",
        "priority_reason": (
            "If true, this is compatible with either a deliberate or forced choice, "
            "so orthogonal applies; distance_from_signal is low because Toyoda's public "
            "statements are directly referenced in the signal."
        ),
    },
    {
        "hypothesis": "Toyota misjudged and got lucky — hybrid demand was not forecast correctly",
        "if_true_impact": "destroys_main_narrative",
        "distance_from_signal": "high",
        "priority_reason": (
            "If true, the outcome is random rather than strategic — "
            "destroys_main_narrative applies; distance_from_signal is high because "
            "this requires inference beyond the signal facts."
        ),
    },
    {
        "hypothesis": "Toyota's deliberate multi-pathway strategy anticipated multiple segments",
        "if_true_impact": "supports_main_narrative",
        "distance_from_signal": "low",
        "priority_reason": (
            "If true, this strengthens the deliberate-choice conclusion, "
            "so supports_main_narrative applies; should be tested last."
        ),
    },
]


class TestGenerateHypothesisSpace:
    def test_returns_hypothesis_objects(self):
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(TOYOTA_Q3_HYPOTHESES)):
            result = generate_hypothesis_space(
                question_id="Q3",
                question="What constraint did they see?",
                headline="Toyota outsells GM as hybrid demand outpaces EV forecasts",
                core_fact="Toyota hybrid sales exceed forecasts as BEV adoption slows industrywide",
            )
        assert all(isinstance(h, Hypothesis) for h in result)

    def test_sorted_by_priority_ascending(self):
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(TOYOTA_Q3_HYPOTHESES)):
            result = generate_hypothesis_space("Q3", "What constraint?", "H", "CF")
        priorities = [h.test_priority for h in result]
        assert priorities == sorted(priorities)

    def test_hypothesis_ids_use_question_prefix(self):
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(TOYOTA_Q3_HYPOTHESES)):
            result = generate_hypothesis_space("Q3", "What constraint?", "H", "CF")
        assert all(h.hypothesis_id.startswith("H-Q3-") for h in result)

    def test_priority_is_computed_not_llm_assigned(self):
        """test_priority must match _compute_priority output — not whatever LLM might have said."""
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(TOYOTA_Q3_HYPOTHESES)):
            result = generate_hypothesis_space("Q3", "What constraint?", "H", "CF")
        for h in result:
            expected = _compute_priority(h.if_true_impact, h.distance_from_signal)
            assert h.test_priority == expected, (
                f"{h.hypothesis_id}: test_priority={h.test_priority}, "
                f"expected={expected} from impact={h.if_true_impact} distance={h.distance_from_signal}"
            )

    def test_too_few_hypotheses_raises(self):
        two_only = TOYOTA_Q3_HYPOTHESES[:2]
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(two_only)):
            with pytest.raises(ValueError, match="only 2 hypotheses"):
                generate_hypothesis_space("Q3", "What constraint?", "H", "CF")

    def test_invalid_json_raises(self):
        with patch("src.investigation.hypothesis_generator.chat", return_value="not json"):
            with pytest.raises(ValueError, match="invalid JSON"):
                generate_hypothesis_space("Q3", "What constraint?", "H", "CF")

    def test_missing_priority_reason_raises(self):
        bad = [dict(h) for h in TOYOTA_Q3_HYPOTHESES]
        bad[0]["priority_reason"] = ""
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(bad)):
            with pytest.raises(ValueError, match="no priority_reason"):
                generate_hypothesis_space("Q3", "What constraint?", "H", "CF")

    def test_invalid_impact_value_raises(self):
        bad = [dict(h) for h in TOYOTA_Q3_HYPOTHESES]
        bad[0]["if_true_impact"] = "maybe_bad"
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(bad)):
            with pytest.raises(ValueError, match="invalid if_true_impact"):
                generate_hypothesis_space("Q3", "What constraint?", "H", "CF")

    def test_invalid_distance_value_raises(self):
        bad = [dict(h) for h in TOYOTA_Q3_HYPOTHESES]
        bad[0]["distance_from_signal"] = "very_far"
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(bad)):
            with pytest.raises(ValueError, match="invalid distance_from_signal"):
                generate_hypothesis_space("Q3", "What constraint?", "H", "CF")

    def test_model_judgment_reason_raises(self):
        bad = [dict(h) for h in TOYOTA_Q3_HYPOTHESES]
        bad[0]["priority_reason"] = "Model judgment based on training data."
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(bad)):
            with pytest.raises(ValueError, match="priority_reason is invalid"):
                generate_hypothesis_space("Q3", "What constraint?", "H", "CF")


# --- Toyota validation test ---

class TestToyotaValidation:
    """
    Validate the Toyota Q3 case from EVIDENCE_COLLECTOR_MVP.md.

    H-Q3-01 "Toyota could not afford full EV transition" must:
    - have if_true_impact = destroys_main_narrative
    - have test_priority = 1
    - have a non-empty priority_reason referencing the impact level

    This is the spec's own example of correct prioritization.
    """

    def _get_result(self):
        with patch("src.investigation.hypothesis_generator.chat",
                   return_value=_make_llm_response(TOYOTA_Q3_HYPOTHESES)):
            return generate_hypothesis_space(
                question_id="Q3",
                question="What constraint did they see?",
                headline="Toyota outsells GM as hybrid demand outpaces EV forecasts",
                core_fact="Toyota hybrid sales exceed forecasts as BEV adoption slows industrywide",
            )

    def test_lacked_capital_is_priority_1(self):
        result = self._get_result()
        capital_hyp = next(
            (h for h in result if "afford" in h.hypothesis.lower() or "capital" in h.hypothesis.lower()),
            None,
        )
        assert capital_hyp is not None, "Expected a 'lacked capital / could not afford' hypothesis"
        assert capital_hyp.test_priority == 1, (
            f"'Lacked capital' hypothesis must be test_priority=1 "
            f"(if true, destroys deliberate-strategy narrative). Got: {capital_hyp.test_priority}"
        )

    def test_lacked_capital_is_destroys_narrative(self):
        result = self._get_result()
        capital_hyp = next(
            (h for h in result if "afford" in h.hypothesis.lower() or "capital" in h.hypothesis.lower()),
            None,
        )
        assert capital_hyp is not None
        assert capital_hyp.if_true_impact == "destroys_main_narrative"

    def test_supports_narrative_is_tested_last(self):
        result = self._get_result()
        supports = [h for h in result if h.if_true_impact == "supports_main_narrative"]
        if supports:
            destroys = [h for h in result if h.if_true_impact == "destroys_main_narrative"]
            assert all(
                d.test_priority < s.test_priority
                for d in destroys
                for s in supports
            ), "All destroys_main_narrative hypotheses must have lower test_priority than supports_main_narrative"

    def test_all_hypotheses_have_priority_reason(self):
        result = self._get_result()
        for h in result:
            assert h.priority_reason, f"{h.hypothesis_id} has no priority_reason"

    def test_first_hypothesis_in_output_is_highest_priority(self):
        result = self._get_result()
        assert result[0].test_priority == min(h.test_priority for h in result)


# --- select_for_testing ---

class TestSelectForTesting:
    def _make_hypotheses(self):
        specs = [
            ("destroys_main_narrative", "medium"),
            ("destroys_main_narrative", "high"),
            ("weakens_main_narrative", "low"),
            ("orthogonal", "low"),
            ("supports_main_narrative", "low"),
        ]
        return [
            Hypothesis(
                hypothesis_id=f"H-Q1-{i+1:02d}",
                hypothesis=f"Hypothesis {i+1}",
                origin_type="initial",
                if_true_impact=impact,
                distance_from_signal=distance,
                test_priority=_compute_priority(impact, distance),
                priority_reason="References if_true_impact explicitly.",
            )
            for i, (impact, distance) in enumerate(specs)
        ]

    def test_returns_at_most_max_count(self):
        hyps = self._make_hypotheses()
        hyps.sort(key=lambda h: h.test_priority)
        selected = select_for_testing(hyps, max_count=3)
        assert len(selected) <= 3

    def test_selected_are_highest_priority(self):
        hyps = self._make_hypotheses()
        hyps.sort(key=lambda h: h.test_priority)
        selected = select_for_testing(hyps, max_count=3)
        selected_priorities = [h.test_priority for h in selected]
        all_priorities = sorted(h.test_priority for h in hyps)
        assert selected_priorities == sorted(selected_priorities)
        assert max(selected_priorities) <= all_priorities[2]
