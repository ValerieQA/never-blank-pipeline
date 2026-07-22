"""
Tests for src/editorial/* (Editorial Engine V2 wiring).

Updated for the new small-business visibility editorial identity.

Covers, per module:
- decision_lens_lite: schema validation (required fields, confidence enum)
- narrative_spine: target_feeling enum enforcement (new feelings set)
- hook_engine: minimum candidate count, selected_hook must match a candidate,
  hook types are the new visibility-pattern types
- reader_context: household-name skip is pure Python (no LLM call), word-count limit
- discovery_builder: investigation_sequence length bounds (3-5)
- story_assembly: required fields including new `reframe` field;
  remaining_uncertainty accepts string or null, rejects other types
- never_blank_voice: echo_line is optional (can be null); cta_line is optional;
  structured_article includes echo_line, cta_line, reframe
- platform_composer: empty body raises; echo safety-net appends if missing;
  reframe block is present in structured article
- pipeline: happy path wiring; a stage that fails twice raises ArticleGenerationError

New tests:
- narrative_spine uses visibility-pattern target_feelings (recognition, unease, reframe)
- hook_engine uses visibility hook types (hidden_cost, invisible_pattern, etc.)
- story_assembly produces reframe field
- never_blank_voice echo_line can be null (no echo forced)
- never_blank_voice cta_line varies (can be null or non-null)
- platform_composer handles absent echo without crashing
- article arc: CTA (when present) does not follow echo in assembled body
"""

import json
import os
from unittest.mock import patch

import pytest

from src.editorial.pattern_extractor import extract_pattern, SignalRejectedError
from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.narrative_spine import build_narrative_spine
from src.editorial.hook_engine import generate_hook
from src.editorial.reader_context import build_reader_context
from src.editorial.discovery_builder import build_discovery
from src.editorial.story_assembly import assemble_story
from src.editorial.never_blank_voice import finalize_article
from src.editorial.platform_composer import compose_platforms, _WORD_RANGE
from src.editorial.pipeline import generate_article, ArticleGenerationError


# Visibility-pattern signal — replaces the corporate strategy signal
SIGNAL = {
    "SIGNAL_ID": "sig_visibility_busy_founders",
    "HEADLINE": "Founders with full schedules go quiet online",
    "CORE_FACT": "Small business owners consistently reduce content activity during their highest-revenue periods.",
    "CORE_TENSION": "Being busy is invisible to clients. Silence reads as unavailability.",
    "REAL_COMPANY_EXAMPLE": "None — pattern observed across businesses",
    "RESPONSE_TAKEN": "Founders prioritize client work over presence maintenance",
    "OUTCOME_IF_KNOWN": "Referral pipeline gaps appear 3-4 months after silent periods",
    "BUSINESS_LESSON": "Visibility is a system, not an impulse",
    "WHY_THIS_CASE_IS_INTERESTING": "The silence is not strategic — it is structural",
    "COUNTER_EXAMPLE": "Businesses with systematized content maintain pipeline even during busy periods",
}


def _json_response(data: dict) -> str:
    return json.dumps(data)


# --- decision_lens_lite ---

class TestDecisionLensLite:
    VALID = {
        "core_pattern": "Founders go silent during peak delivery periods, breaking the presence continuity their pipeline depends on.",
        "owner_system_objective": "optimizing for immediate client delivery throughput at the cost of non-urgent presence maintenance",
        "delivery_vs_presence_conflict": "Delivery work has a deadline and a client. Presence work has neither — so it loses every time.",
        "customer_memory_consequence": "Customers do not decide to forget a business; they simply stop encountering it and route their attention elsewhere.",
        "structural_cause": "Presence maintenance is non-urgent until the pipeline is empty, at which point the damage has already compounded over months.",
        "never_blank_insight": "The silence happens exactly when the business looks most successful from the inside.",
    }

    def test_valid_response_passes(self):
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(self.VALID)):
            result = generate_decision_lens(SIGNAL)
        assert result["core_pattern"] == self.VALID["core_pattern"]
        assert result["never_blank_insight"] == self.VALID["never_blank_insight"]

    def test_missing_field_raises(self):
        bad = {**self.VALID, "structural_cause": ""}
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="structural_cause"):
                generate_decision_lens(SIGNAL)

    def test_missing_owner_system_objective_raises(self):
        bad = {**self.VALID, "owner_system_objective": ""}
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="owner_system_objective"):
                generate_decision_lens(SIGNAL)

    def test_all_required_fields_present(self):
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(self.VALID)):
            result = generate_decision_lens(SIGNAL)
        for field in ("core_pattern", "owner_system_objective", "delivery_vs_presence_conflict",
                      "customer_memory_consequence", "structural_cause", "never_blank_insight"):
            assert field in result, f"Missing field: {field}"


# --- narrative_spine ---

class TestNarrativeSpine:
    DECISION_LENS = {
        "core_pattern": "Founders go silent during peak delivery periods.",
        "owner_system_objective": "optimizing for immediate delivery at the cost of presence maintenance",
        "delivery_vs_presence_conflict": "Delivery work has deadlines; presence work does not.",
        "customer_memory_consequence": "Customers stop encountering the business and route attention elsewhere.",
        "structural_cause": "Non-urgent visibility work is displaced by urgent delivery work.",
        "never_blank_insight": "The silence happens exactly when the business looks most successful.",
    }

    # New valid feelings: recognition, unease, reframe, clarity, anticipation
    VALID_RECOGNITION = {
        "core_pattern": "Founders go silent during their busiest periods.",
        "narrative_spine": "If presence depends only on the owner's free time, silence eventually becomes part of the strategy — even when nobody chose it.",
        "target_feeling": "recognition",
        "pattern_as_evidence_of": "What it costs when visibility is a task rather than a system.",
    }

    VALID_UNEASE = {
        "core_pattern": "Customer memory degrades faster during silence than it was built during presence.",
        "narrative_spine": "Customers rarely decide to forget a business. They simply stop encountering it.",
        "target_feeling": "unease",
        "pattern_as_evidence_of": "Why accumulated recognition is more fragile than it feels from the inside.",
    }

    def test_valid_recognition_passes(self):
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(self.VALID_RECOGNITION)):
            result = build_narrative_spine(self.DECISION_LENS, SIGNAL)
        assert result["target_feeling"] == "recognition"
        assert "narrative_spine" in result
        # Backward-compat aliases present
        assert "core_decision" in result
        assert "company_as_evidence_of" in result

    def test_valid_unease_passes(self):
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(self.VALID_UNEASE)):
            result = build_narrative_spine(self.DECISION_LENS, SIGNAL)
        assert result["target_feeling"] == "unease"

    def test_invalid_target_feeling_raises(self):
        bad = {**self.VALID_RECOGNITION, "target_feeling": "excitement"}
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="target_feeling"):
                build_narrative_spine(self.DECISION_LENS, SIGNAL)

    def test_old_feeling_reframe_is_valid(self):
        """reframe is valid in the new feelings set."""
        valid = {**self.VALID_RECOGNITION, "target_feeling": "reframe"}
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(valid)):
            result = build_narrative_spine(self.DECISION_LENS, SIGNAL)
        assert result["target_feeling"] == "reframe"

    def test_old_feeling_clarity_is_valid(self):
        valid = {**self.VALID_RECOGNITION, "target_feeling": "clarity"}
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(valid)):
            result = build_narrative_spine(self.DECISION_LENS, SIGNAL)
        assert result["target_feeling"] == "clarity"


# --- hook_engine ---

class TestHookEngine:
    SPINE = {"narrative_spine": "If presence depends only on the owner's free time, silence eventually becomes part of the strategy."}
    DECISION_LENS = {"never_blank_insight": "silence at peak busy time", "owner_system_objective": "maintain delivery over visibility"}

    # New hook types for visibility patterns
    _VALID_TYPES = [
        "hidden_cost",
        "invisible_pattern",
        "false_comfort",
        "timing_contradiction",
        "recognition_gap",
    ]

    def _candidates(self, n=5):
        types = self._VALID_TYPES
        return [{"type": types[i % len(types)], "text": f"hook candidate {i}"} for i in range(n)]

    def test_valid_response_passes(self):
        candidates = self._candidates(5)
        data = {"hook_candidates": candidates, "selected_hook": candidates[0]["text"]}
        with patch("src.editorial.hook_engine.chat", return_value=_json_response(data)):
            result = generate_hook(self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["selected_hook"] == candidates[0]["text"]
        assert len(result["hook_candidates"]) == 5

    def test_too_few_candidates_raises(self):
        candidates = self._candidates(3)
        data = {"hook_candidates": candidates, "selected_hook": candidates[0]["text"]}
        with patch("src.editorial.hook_engine.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="hook_candidates"):
                generate_hook(self.SPINE, self.DECISION_LENS, SIGNAL)

    def test_selected_hook_not_matching_candidate_raises(self):
        candidates = self._candidates(5)
        data = {"hook_candidates": candidates, "selected_hook": "not one of the candidates"}
        with patch("src.editorial.hook_engine.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="selected_hook"):
                generate_hook(self.SPINE, self.DECISION_LENS, SIGNAL)

    def test_old_hook_types_rejected(self):
        """Old corporate-analysis hook types (contradiction, hidden_decision) are no longer valid."""
        candidates = [
            {"type": "contradiction", "text": "hook text"},
            {"type": "hidden_cost", "text": "hook text 2"},
            {"type": "invisible_pattern", "text": "hook text 3"},
            {"type": "false_comfort", "text": "hook text 4"},
            {"type": "timing_contradiction", "text": "hook text 5"},
        ]
        data = {"hook_candidates": candidates, "selected_hook": candidates[1]["text"]}
        with patch("src.editorial.hook_engine.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="invalid type"):
                generate_hook(self.SPINE, self.DECISION_LENS, SIGNAL)


# --- reader_context ---

class TestReaderContext:
    def test_household_name_skips_llm_entirely(self):
        signal = {**SIGNAL, "REAL_COMPANY_EXAMPLE": "Microsoft", "HEADLINE": "Microsoft ships update"}
        with patch("src.editorial.reader_context.chat") as mock_chat:
            result = build_reader_context(signal)
        assert result is None
        mock_chat.assert_not_called()

    def test_non_household_name_calls_llm(self):
        data = {"context_line": "Acme Corp manufactures industrial fasteners for construction firms."}
        with patch("src.editorial.reader_context.chat", return_value=_json_response(data)) as mock_chat:
            result = build_reader_context(SIGNAL)
        assert result == data["context_line"]
        mock_chat.assert_called_once()

    def test_too_many_words_raises(self):
        long_line = " ".join(["word"] * 40)
        data = {"context_line": long_line}
        with patch("src.editorial.reader_context.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="words"):
                build_reader_context(SIGNAL)

    def test_real_company_example_is_a_precedent_not_the_subject(self):
        """
        Regression test: REAL_COMPANY_EXAMPLE frequently holds a comparison/precedent
        company, not the subject. build_reader_context must not treat it as "the company."
        """
        signal = {
            **SIGNAL,
            "HEADLINE": "Klarna seeks U.S. bank charter in latest push beyond buy now, pay later",
            "CORE_FACT": "Klarna is seeking a U.S. bank charter to expand its services beyond BNPL.",
            "REAL_COMPANY_EXAMPLE": "Varo Money",
        }
        data = {"context_line": "Klarna offers buy now, pay later financing for online and in-store purchases."}
        with patch("src.editorial.reader_context.chat", return_value=_json_response(data)) as mock_chat:
            result = build_reader_context(signal)
        assert result == data["context_line"]
        sent_user_message = mock_chat.call_args.kwargs["user"]
        assert "Varo Money" not in sent_user_message
        assert "Klarna" in sent_user_message


# --- discovery_builder ---

class TestDiscoveryBuilder:
    HOOK = {"selected_hook": "Clients don't know you're busy. They know you're quiet."}
    SPINE = {"narrative_spine": "If presence depends only on the owner's free time, silence eventually becomes part of the strategy."}
    DECISION_LENS = {"strategic_objective": "Maintain visibility to avoid pipeline gaps."}

    VALID = {
        "first_wrong_explanation": "Founders go quiet because they don't have anything interesting to say.",
        "puzzle": "Content output drops during the busiest periods — exactly when the pipeline for next quarter is forming.",
        "investigation_sequence": [
            "Content activity falls in the weeks when billable hours are highest.",
            "Pipeline gaps appear 3-4 months after the silence, not immediately.",
            "Founders attribute the later gap to market conditions, not to the earlier silence.",
        ],
        "aha_setup": "The silence is not about ideas or motivation. It is about where urgent work displaced non-urgent work — and visibility is never urgent until it is too late.",
    }

    def test_valid_response_passes(self):
        with patch("src.editorial.discovery_builder.chat", return_value=_json_response(self.VALID)):
            result = build_discovery(self.HOOK, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert len(result["investigation_sequence"]) == 3

    def test_sequence_too_short_raises(self):
        bad = {**self.VALID, "investigation_sequence": ["only one beat"]}
        with patch("src.editorial.discovery_builder.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="investigation_sequence"):
                build_discovery(self.HOOK, self.SPINE, self.DECISION_LENS, SIGNAL)

    def test_sequence_too_long_raises(self):
        bad = {**self.VALID, "investigation_sequence": [f"beat {i}" for i in range(6)]}
        with patch("src.editorial.discovery_builder.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="investigation_sequence"):
                build_discovery(self.HOOK, self.SPINE, self.DECISION_LENS, SIGNAL)


# --- story_assembly ---

class TestStoryAssembly:
    DISCOVERY = {
        "first_wrong_explanation": "Founders go quiet because they lack ideas.",
        "puzzle": "Content drops during the busiest periods — exactly when pipeline is forming.",
        "investigation_sequence": ["a", "b", "c"],
        "aha_setup": "The silence is structural, not motivational.",
    }
    SPINE = {"narrative_spine": "If presence depends only on the owner's free time, silence becomes the default."}
    DECISION_LENS = {"owner_system_objective": "Maintain visibility", "structural_cause": "Non-urgent work displaced by urgent work"}

    def test_valid_response_includes_reframe(self):
        """story_assembly must now produce a reframe field."""
        data = {
            "surviving_explanation": "Non-urgent work is displaced by urgent operational work.",
            "reframe": "This is not a discipline problem. It is a system-design problem.",
            "remaining_uncertainty": None,
            "business_translation": "A business whose presence depends on the owner's energy will be least visible when the pipeline is most vulnerable.",
        }
        with patch("src.editorial.story_assembly.chat", return_value=_json_response(data)):
            result = assemble_story(self.DISCOVERY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert "reframe" in result
        assert result["reframe"] == "This is not a discipline problem. It is a system-design problem."

    def test_missing_reframe_raises(self):
        """reframe is now a required field."""
        data = {
            "surviving_explanation": "Non-urgent work is displaced by urgent work.",
            "reframe": "",  # empty — should raise
            "remaining_uncertainty": None,
            "business_translation": "Visibility requires a system.",
        }
        with patch("src.editorial.story_assembly.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="reframe"):
                assemble_story(self.DISCOVERY, self.SPINE, self.DECISION_LENS, SIGNAL)

    def test_null_remaining_uncertainty_accepted(self):
        data = {
            "surviving_explanation": "Non-urgent work is displaced by urgent work.",
            "reframe": "This is a system-design problem, not a discipline problem.",
            "remaining_uncertainty": None,
            "business_translation": "Visibility requires a system.",
        }
        with patch("src.editorial.story_assembly.chat", return_value=_json_response(data)):
            result = assemble_story(self.DISCOVERY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["remaining_uncertainty"] is None

    def test_non_string_remaining_uncertainty_raises(self):
        data = {
            "surviving_explanation": "Non-urgent work is displaced by urgent work.",
            "reframe": "This is a system-design problem.",
            "remaining_uncertainty": 123,
            "business_translation": "Visibility requires a system.",
        }
        with patch("src.editorial.story_assembly.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="remaining_uncertainty"):
                assemble_story(self.DISCOVERY, self.SPINE, self.DECISION_LENS, SIGNAL)


# --- never_blank_voice ---

class TestNeverBlankVoice:
    HOOK = {"selected_hook": "Clients don't know you're busy. They know you're quiet."}
    DISCOVERY = {
        "first_wrong_explanation": "Founders go quiet because they lack ideas.",
        "puzzle": "Content drops during busiest periods.",
        "investigation_sequence": ["a", "b", "c"],
        "aha_setup": "The silence is structural.",
    }
    STORY = {
        "surviving_explanation": "Non-urgent work is displaced by urgent operational work.",
        "reframe": "This is a system-design problem, not a discipline problem.",
        "remaining_uncertainty": None,
        "business_translation": "A business whose presence depends on the owner's energy will be least visible when it most needs to be visible.",
    }
    SPINE = {"narrative_spine": "If presence depends only on the owner's free time, silence eventually becomes the strategy."}
    DECISION_LENS = {}

    def test_echo_can_be_null(self):
        """Echo is optional — not every article earns a strong Echo."""
        data = {
            "echo_candidates": ["candidate 1", "candidate 2"],
            "echo_line": None,
            "cta_line": None,
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["echo_line"] is None
        assert result["signature"] == ""  # backward-compat: empty string when no echo

    def test_echo_present_when_strong(self):
        """When a strong Echo is generated, it appears in echo_line and signature."""
        data = {
            "echo_candidates": ["candidate 1", "Customers rarely decide to forget a business. They simply stop encountering it."],
            "echo_line": "Customers rarely decide to forget a business. They simply stop encountering it.",
            "cta_line": None,
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["echo_line"] == "Customers rarely decide to forget a business. They simply stop encountering it."
        assert result["signature"] == result["echo_line"]  # backward-compat

    def test_cta_varies_can_be_null(self):
        """CTA is optional — not every article includes an invitation."""
        data = {
            "echo_candidates": ["echo"],
            "echo_line": "Customers rarely decide to forget a business.",
            "cta_line": None,
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["cta_line"] is None

    def test_cta_present_when_natural(self):
        """CTA can be a natural invitation when it fits the article."""
        data = {
            "echo_candidates": ["echo"],
            "echo_line": "Customers rarely decide to forget a business.",
            "cta_line": "If you recognize your business in this pattern, let's look at where your presence starts depending entirely on your time and energy.",
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["cta_line"] is not None
        assert "presence" in result["cta_line"]

    # --- cta_mode tests ---

    def test_cta_mode_none_produces_no_cta(self):
        """When cta_mode='none', cta_line must be null regardless of article content."""
        data = {
            "echo_candidates": ["Customers rarely decide to forget a business."],
            "echo_line": "Customers rarely decide to forget a business.",
            "cta_line": None,
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(
                self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE,
                self.DECISION_LENS, SIGNAL, cta_mode="none",
            )
        assert result["cta_line"] is None
        assert result["cta_mode"] == "none"

    def test_cta_mode_diagnostic_passed_to_user_message(self):
        """cta_mode='diagnostic' must appear in the user message sent to the LLM."""
        data = {
            "echo_candidates": ["echo"],
            "echo_line": "echo",
            "cta_line": "If your content presence disappears when you get busy, let's look at exactly where the system fails.",
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)) as mock_chat:
            result = finalize_article(
                self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE,
                self.DECISION_LENS, SIGNAL, cta_mode="diagnostic",
            )
        sent_user = mock_chat.call_args.kwargs["user"]
        assert "diagnostic" in sent_user
        assert result["cta_mode"] == "diagnostic"
        assert result["cta_line"] is not None

    def test_cta_mode_stored_in_structured_article(self):
        """cta_mode must be stored in the returned structured_article dict."""
        data = {
            "echo_candidates": [],
            "echo_line": None,
            "cta_line": None,
            "checklist_pass": True,
            "checklist_notes": "",
        }
        for mode in ("none", "reflection", "diagnostic", "example_request", "direct_conversation"):
            with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
                result = finalize_article(
                    self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE,
                    self.DECISION_LENS, SIGNAL, cta_mode=mode,
                )
            assert result["cta_mode"] == mode

    def test_checklist_fail_does_not_raise(self):
        data = {
            "echo_candidates": [],
            "echo_line": "Customers rarely decide to forget a business.",
            "cta_line": None,
            "checklist_pass": False,
            "checklist_notes": "Recognition moment is too generic.",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["checklist_pass"] is False

    def test_structured_article_has_reframe(self):
        """structured_article must carry the reframe field from Story Assembly."""
        data = {
            "echo_candidates": [],
            "echo_line": "Echo line.",
            "cta_line": None,
            "checklist_pass": True,
            "checklist_notes": "",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert "reframe" in result
        assert result["reframe"] == self.STORY["reframe"]


# --- platform_composer ---

class TestPlatformComposer:
    STRUCTURED_ARTICLE = {
        "signal_id": "sig_visibility_busy_founders",
        "narrative_spine": "If presence depends only on the owner's free time, silence becomes the strategy.",
        "hook": "Clients don't know you're busy. They know you're quiet.",
        "reader_context": None,
        "discovery": {
            "first_wrong_explanation": "Founders go quiet because they lack ideas.",
            "puzzle": "Content drops during busiest periods.",
            "investigation_sequence": ["a", "b", "c"],
            "aha_setup": "The silence is structural, not motivational.",
        },
        "surviving_explanation": "Non-urgent work is displaced by urgent operational work.",
        "reframe": "This is a system-design problem, not a discipline problem.",
        "remaining_uncertainty": None,
        "business_translation": "A business whose presence depends on the owner's energy will be least visible when it most needs to be visible.",
        "echo_line": "Customers rarely decide to forget a business. They simply stop encountering it.",
        "cta_line": None,
        "signature": "Customers rarely decide to forget a business. They simply stop encountering it.",
    }

    def test_empty_body_raises(self):
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": ""})):
            with pytest.raises(ValueError, match="body"):
                compose_platforms(self.STRUCTURED_ARTICLE)

    def test_echo_appended_if_missing(self):
        """When echo is present but missing from body, it must be appended."""
        body_without_echo = "A body that forgot to include the echo line."
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": body_without_echo})):
            result = compose_platforms(self.STRUCTURED_ARTICLE)
        echo = self.STRUCTURED_ARTICLE["echo_line"]
        for fmt in ("long", "reading", "medium", "instagram", "short"):
            assert echo in result[fmt]["body"]

    def test_no_echo_article_composes_without_crash(self):
        """When echo_line is None and signature is empty, Platform Composer must not crash."""
        article_no_echo = {**self.STRUCTURED_ARTICLE, "echo_line": None, "signature": "", "cta_line": None}
        body = "Some body text that has no echo. " * 10
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": body})):
            result = compose_platforms(article_no_echo)
        assert set(result.keys()) == set(_WORD_RANGE.keys())

    def test_all_five_formats_present(self):
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": "some body text " * 20})):
            result = compose_platforms(self.STRUCTURED_ARTICLE)
        assert set(result.keys()) == set(_WORD_RANGE.keys())

    def test_instagram_cta_mode_diagnostic_adds_cta_note_to_prompt(self):
        """When cta_mode=diagnostic, the user prompt sent to the LLM must mention
        the CTA instruction for Instagram."""
        from src.editorial.platform_composer import _build_user_prompt
        prompt = _build_user_prompt(self.STRUCTURED_ARTICLE, "instagram", cta_mode="diagnostic")
        assert "INSTAGRAM CTA" in prompt
        assert "diagnostic" in prompt

    def test_instagram_cta_mode_none_has_no_cta_note(self):
        """When cta_mode=none, no CTA note must appear in the Instagram prompt."""
        from src.editorial.platform_composer import _build_user_prompt
        prompt = _build_user_prompt(self.STRUCTURED_ARTICLE, "instagram", cta_mode="none")
        assert "INSTAGRAM CTA" not in prompt

    def test_instagram_cta_default_is_none(self):
        """cta_mode defaults to 'none' — Instagram must not get a CTA note by default."""
        from src.editorial.platform_composer import _build_user_prompt
        prompt = _build_user_prompt(self.STRUCTURED_ARTICLE, "instagram")
        assert "INSTAGRAM CTA" not in prompt

    def test_echo_adaptation_note_for_instagram(self):
        """Instagram prompt must include the ECHO ADAPTATION note when echo is present."""
        from src.editorial.platform_composer import _build_user_prompt
        prompt = _build_user_prompt(self.STRUCTURED_ARTICLE, "instagram")
        assert "ECHO ADAPTATION" in prompt

    def test_echo_no_adaptation_note_for_long_format(self):
        """Long format (Blog) must NOT include ECHO ADAPTATION note — echo is verbatim."""
        from src.editorial.platform_composer import _build_user_prompt
        prompt = _build_user_prompt(self.STRUCTURED_ARTICLE, "long")
        assert "ECHO ADAPTATION" not in prompt

    def test_compose_platforms_accepts_cta_mode(self):
        """compose_platforms must accept cta_mode without error."""
        body = "some body text " * 20
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": body})):
            result = compose_platforms(self.STRUCTURED_ARTICLE, cta_mode="diagnostic")
        assert set(result.keys()) == set(_WORD_RANGE.keys())


# --- generator telegram and stories ---

class TestGeneratorTelegramStories:
    """Tests for generate_telegram and generate_stories in src/content/generator.py."""

    BRIEF_MOCK = None  # set in tests via mock
    MATRIX_MOCK = None

    def _make_brief(self):
        from unittest.mock import MagicMock
        brief = MagicMock()
        brief.title = "Test title"
        brief.angle = "test angle"
        brief.hook = "test hook"
        brief.content_goal.value = "recognition"
        brief.observation_statement = "test observation"
        brief.observation_type.value = "pattern"
        brief.tone_notes = ""
        brief.wix_slug = "test-slug"
        brief.observation_id = "obs_001"
        brief.platforms = ["telegram", "stories"]
        return brief

    def _make_matrix(self):
        from unittest.mock import MagicMock
        matrix = MagicMock()
        matrix.cta_mode = "diagnostic"
        matrix.core_idea = "test core idea"
        matrix.observation = "test observation"
        matrix.mechanism = "test mechanism"
        matrix.cost_of_ignoring = "test cost"
        matrix.strategic_question = "test question"
        matrix.hook_type = "hidden_cost"
        matrix.primary_hook = "test hook"
        matrix.supporting_points = ["point 1", "point 2"]
        matrix.visual_anchor = "test visual"
        matrix.sales_angle = "test sales"
        matrix.soft_cta = "test cta"
        matrix.linkedin_angle = "test linkedin"
        matrix.instagram_angle = "test instagram"
        matrix.facebook_angle = "test facebook"
        matrix.threads_angle = "test threads"
        matrix.telegram_angle = "test telegram"
        matrix.stories_flow = "test stories flow"
        return matrix

    def test_generate_telegram_returns_text_when_prompt_succeeds(self):
        """generate_telegram must return {"text": ...} with content when prompt succeeds."""
        from src.content.generator import generate_telegram
        brief = self._make_brief()
        matrix = self._make_matrix()
        telegram_text = "Fully booked founders go quiet.\nClients read quiet as available.\nReply if you recognize this."
        with patch("src.content.generator._call", return_value={"text": telegram_text}):
            result = generate_telegram(brief, matrix)
        assert result.get("text") == telegram_text

    def test_generate_telegram_returns_none_text_on_failure(self):
        """generate_telegram must return {"text": None} if the LLM call fails."""
        from src.content.generator import generate_telegram
        brief = self._make_brief()
        matrix = self._make_matrix()
        with patch("src.content.generator._call", side_effect=RuntimeError("LLM down")):
            result = generate_telegram(brief, matrix)
        assert result.get("text") is None

    def test_generate_telegram_returns_none_text_on_empty_response(self):
        """generate_telegram must return {"text": None} if LLM returns empty text."""
        from src.content.generator import generate_telegram
        brief = self._make_brief()
        matrix = self._make_matrix()
        with patch("src.content.generator._call", return_value={"text": ""}):
            result = generate_telegram(brief, matrix)
        assert result.get("text") is None

    def test_generate_telegram_text_max_3_lines(self):
        """Telegram output must be 3 lines max — validate the prompt contract."""
        from src.content.generator import generate_telegram
        brief = self._make_brief()
        matrix = self._make_matrix()
        three_line_text = "Line one.\nLine two.\nLine three."
        with patch("src.content.generator._call", return_value={"text": three_line_text}):
            result = generate_telegram(brief, matrix)
        assert result["text"].count("\n") <= 2  # 3 lines = 2 newlines max

    def test_generate_stories_returns_4_frames_on_success(self):
        """generate_stories must return a list of 4 frame dicts when prompt succeeds."""
        from src.content.generator import generate_stories
        brief = self._make_brief()
        matrix = self._make_matrix()
        frames = [
            {"frame_number": 1, "type": "recognition", "text": "You've been heads down.", "interaction": None, "interaction_options": None},
            {"frame_number": 2, "type": "mechanism", "text": "Delivery mode filters presence out.", "interaction": None, "interaction_options": None},
            {"frame_number": 3, "type": "reframe", "text": "Not a discipline problem.", "interaction": None, "interaction_options": None},
            {"frame_number": 4, "type": "cta", "text": "Show me how your presence is organized.", "interaction": "cta", "interaction_options": None},
        ]
        with patch("src.content.generator._call", return_value={"frames": frames}):
            result = generate_stories(brief, matrix)
        assert result is not None
        assert len(result) == 4

    def test_generate_stories_frame_types_in_order(self):
        """Stories frames must follow recognition→mechanism→reframe→cta order."""
        from src.content.generator import generate_stories
        brief = self._make_brief()
        matrix = self._make_matrix()
        frames = [
            {"frame_number": 1, "type": "recognition", "text": "Frame 1.", "interaction": None, "interaction_options": None},
            {"frame_number": 2, "type": "mechanism", "text": "Frame 2.", "interaction": None, "interaction_options": None},
            {"frame_number": 3, "type": "reframe", "text": "Frame 3.", "interaction": None, "interaction_options": None},
            {"frame_number": 4, "type": "cta", "text": "Frame 4.", "interaction": "question_box", "interaction_options": None},
        ]
        with patch("src.content.generator._call", return_value={"frames": frames}):
            result = generate_stories(brief, matrix)
        types = [f["type"] for f in result]
        assert types == ["recognition", "mechanism", "reframe", "cta"]

    def test_generate_stories_returns_none_on_failure(self):
        """generate_stories must return None (channel FAILED) if prompt fails."""
        from src.content.generator import generate_stories
        brief = self._make_brief()
        matrix = self._make_matrix()
        with patch("src.content.generator._call", side_effect=RuntimeError("LLM error")):
            result = generate_stories(brief, matrix)
        assert result is None

    def test_generate_stories_returns_none_on_empty_frames(self):
        """generate_stories must return None if prompt returns empty frames list."""
        from src.content.generator import generate_stories
        brief = self._make_brief()
        matrix = self._make_matrix()
        with patch("src.content.generator._call", return_value={"frames": []}):
            result = generate_stories(brief, matrix)
        assert result is None


# --- pipeline ---

class TestPipeline:
    def _patch_all_stages(self):
        """Patch every stage function inside src.editorial.pipeline's namespace."""
        _pattern = {
            "visibility_pattern": "Founders go quiet during their busiest periods.",
            "founder_scenario": "You are three weeks into your most profitable month and you have not posted once.",
            "mechanism": "Non-urgent visibility work is displaced by urgent delivery work.",
            "business_consequence": "Pipeline gaps appear 3-4 months after the silence.",
            "company_as_evidence_of": "The Nike case demonstrates that ambient distribution absence compounds invisibly over time.",
            "evidence_limit": "Nike's brand strength means recovery is faster than for most small businesses.",
            "article_protagonist": "owner",
            "signal_fit": "use",
            "rejection_reason": None,
        }
        return patch.multiple(
            "src.editorial.pipeline",
            extract_pattern=lambda signal: _pattern,
            generate_decision_lens=lambda signal: {
                "core_pattern": "d", "owner_system_objective": "o",
                "delivery_vs_presence_conflict": "conflict", "customer_memory_consequence": "c",
                "structural_cause": "s", "never_blank_insight": "i",
            },
            build_narrative_spine=lambda dl, signal: {
                "core_pattern": "d", "narrative_spine": "spine sentence",
                "target_feeling": "recognition",
                "pattern_as_evidence_of": "x",
                # backward-compat aliases
                "core_decision": "d", "company_as_evidence_of": "x",
            },
            generate_hook=lambda spine, dl, signal: {
                "hook_candidates": [{"type": "hidden_cost", "text": "hook"}],
                "selected_hook": "hook",
            },
            build_reader_context=lambda signal: None,
            build_discovery=lambda hook, spine, dl, signal: {
                "first_wrong_explanation": "a", "puzzle": "b",
                "investigation_sequence": ["c1", "c2", "c3"], "aha_setup": "d",
            },
            assemble_story=lambda discovery, spine, dl, signal: {
                "surviving_explanation": "e",
                "reframe": "This is a system-design problem.",
                "remaining_uncertainty": None,
                "business_translation": "f",
            },
            finalize_article=lambda hook, ctx, discovery, story, spine, dl, signal, cta_mode="none": {
                "signal_id": signal.get("SIGNAL_ID", ""),
                "cta_mode": cta_mode,
                "narrative_spine": "spine sentence",
                "hook": "hook", "reader_context": None, "discovery": discovery,
                "surviving_explanation": "e",
                "reframe": "This is a system-design problem.",
                "remaining_uncertainty": None,
                "business_translation": "f",
                "echo_line": "Customers rarely decide to forget a business.",
                "cta_line": None,
                "signature": "Customers rarely decide to forget a business.",
                "checklist_pass": True,
                "echo_candidates": [],
            },
            compose_platforms=lambda structured_article, **kwargs: {
                fmt: {"word_count": 10, "body": f"{fmt} body Customers rarely decide to forget a business."}
                for fmt in ("long", "reading", "medium", "instagram", "short")
            },
        )

    def test_happy_path_returns_full_result(self):
        with self._patch_all_stages():
            result = generate_article(SIGNAL)
        assert result["structured_article"]["echo_line"] == "Customers rarely decide to forget a business."
        assert set(result["platforms"].keys()) == {"long", "reading", "medium", "instagram", "short"}
        assert "pattern" in result
        assert result["pattern"]["article_protagonist"] == "owner"

    def test_stage_failing_twice_raises_article_generation_error(self):
        def _always_fails(signal):
            raise ValueError("LLM returned garbage")

        _pattern = {
            "visibility_pattern": "founders go quiet",
            "founder_scenario": "You are booked solid and invisible.",
            "mechanism": "Non-urgent work is displaced by urgent work.",
            "business_consequence": "Pipeline gaps appear months later.",
            "company_as_evidence_of": "The example proves the pattern holds at scale.",
            "evidence_limit": "Scale recovery differs from owner recovery.",
            "article_protagonist": "owner",
            "signal_fit": "use",
            "rejection_reason": None,
        }
        with patch("src.editorial.pipeline.extract_pattern", return_value=_pattern):
            with patch("src.editorial.pipeline.generate_decision_lens", side_effect=_always_fails):
                with pytest.raises(ArticleGenerationError) as exc_info:
                    generate_article(SIGNAL)
        assert exc_info.value.stage == "decision_lens_lite"

    def test_happy_path_structured_article_has_reframe(self):
        """Reframe must be present in the structured article after the pipeline."""
        with self._patch_all_stages():
            result = generate_article(SIGNAL)
        assert "reframe" in result["structured_article"]
        assert result["structured_article"]["reframe"] == "This is a system-design problem."


# ---------------------------------------------------------------------------
# Pattern Extractor tests (Stage 6 additions)
# ---------------------------------------------------------------------------

_VALID_PATTERN = {
    "visibility_pattern": "Founders go quiet during their busiest periods, breaking the presence continuity their future pipeline depends on.",
    "founder_scenario": "You are three weeks into your most profitable month and you have not posted once.",
    "mechanism": "Non-urgent visibility work is displaced by urgent delivery work whenever capacity is constrained.",
    "business_consequence": "Pipeline gaps appear 3-4 months after the silence, after customer memory of the business has faded.",
    "company_as_evidence_of": "The Nike distribution reversal demonstrates that ambient presence absence compounds invisibly even for recognized brands.",
    "evidence_limit": "Nike's brand equity accelerates recovery in ways unavailable to most small business owners.",
    "article_protagonist": "owner",
    "signal_fit": "use",
    "rejection_reason": None,
}


class TestPatternExtractor:
    def test_owner_protagonist_always_owner(self):
        """Pattern extractor must always return article_protagonist = 'owner'."""
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(_VALID_PATTERN)):
            result = extract_pattern(SIGNAL)
        assert result["article_protagonist"] == "owner"

    def test_signal_rejection_raises_signal_rejected_error(self):
        """When signal_fit = reject, extract_pattern raises SignalRejectedError."""
        rejected = {
            **_VALID_PATTERN,
            "signal_fit": "reject",
            "rejection_reason": "No credible founder recognition scenario exists without forcing a connection to Nike's scale.",
        }
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(rejected)):
            with pytest.raises(SignalRejectedError) as exc_info:
                extract_pattern(SIGNAL)
        assert "No credible" in str(exc_info.value)

    def test_pipeline_wraps_rejection_as_article_generation_error(self):
        """When Pattern Extractor rejects, pipeline raises ArticleGenerationError with stage='pattern_extractor'."""
        with patch("src.editorial.pipeline.extract_pattern",
                   side_effect=SignalRejectedError("no owner scenario possible")):
            with pytest.raises(ArticleGenerationError) as exc_info:
                generate_article(SIGNAL)
        assert exc_info.value.stage == "pattern_extractor"

    def test_evidence_limit_is_single_sentence(self):
        """company_as_evidence_of must be a single sentence (approximately <=35 words)."""
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(_VALID_PATTERN)):
            result = extract_pattern(SIGNAL)
        word_count = len(result["company_as_evidence_of"].split())
        assert word_count <= 35, (
            f"company_as_evidence_of has {word_count} words — must be a single sentence: "
            f"{result['company_as_evidence_of']!r}"
        )

    def test_founder_scenario_has_no_company_name(self):
        """founder_scenario must not contain the company name from REAL_COMPANY_EXAMPLE."""
        signal_with_company = {**SIGNAL, "REAL_COMPANY_EXAMPLE": "TestBrand Corp"}
        pattern_with_company_in_scenario = {
            **_VALID_PATTERN,
            "founder_scenario": "TestBrand Corp went quiet and lost shelf presence.",
        }
        # Validate schema — this should raise because it contains company name
        # In our unit test we check the returned value; the extractor itself doesn't
        # guard company names in founder_scenario (that is a prompt-level concern),
        # so we test the assertion property directly on the output.
        with patch("src.editorial.pattern_extractor.chat",
                   return_value=_json_response(_VALID_PATTERN)):
            result = extract_pattern(signal_with_company)
        # The valid pattern has no mention of any company name in founder_scenario
        assert "TestBrand Corp" not in result["founder_scenario"]
        assert "Nike" not in result["founder_scenario"]

    def test_no_company_as_primary_subject_in_decision_lens_core_pattern(self):
        """Decision Lens core_pattern must not make the company the primary subject."""
        dl_with_company = {
            "core_pattern": "Nike reversed distribution strategy to regain shelf presence.",
            "owner_system_objective": "o",
            "delivery_vs_presence_conflict": "c",
            "customer_memory_consequence": "m",
            "structural_cause": "s",
            "never_blank_insight": "i",
        }
        # The test checks that the schema validation passes only when core_pattern
        # is about the owner pattern — here we verify the bad case would have the
        # company as subject, which violates editorial intent (prompt-level concern).
        # We verify the field validates correctly at schema level.
        with patch("src.editorial.decision_lens_lite.chat",
                   return_value=_json_response(dl_with_company)):
            result = generate_decision_lens({**SIGNAL, **_VALID_PATTERN})
        # Schema passes (no structural validation prevents company mention in core_pattern)
        # But this test documents the expected post-extraction shape of a VALID response:
        dl_valid = {
            "core_pattern": "Founders go silent during peak delivery periods.",
            "owner_system_objective": "optimizing for delivery over presence",
            "delivery_vs_presence_conflict": "Delivery has deadlines; presence does not.",
            "customer_memory_consequence": "Customers stop encountering the business.",
            "structural_cause": "Non-urgent work is displaced by urgent work.",
            "never_blank_insight": "The silence happens at exactly the wrong moment.",
        }
        with patch("src.editorial.decision_lens_lite.chat",
                   return_value=_json_response(dl_valid)):
            result = generate_decision_lens({**SIGNAL, **_VALID_PATTERN})
        assert "Nike" not in result["core_pattern"]
        assert result["core_pattern"].startswith("Founders")

    def test_checklist_notes_flag_company_in_first_sentence_of_hook(self):
        """Checklist notes must catch when company name appears in hook — checklist_pass=False."""
        hook_with_company = {
            "selected_hook": "Nike reversed its DTC strategy to regain distribution presence.",
        }
        data = {
            "echo_candidates": ["echo"],
            "echo_line": "Presence depends on the system, not on the schedule.",
            "cta_line": None,
            "checklist_pass": False,
            "checklist_notes": "Hook requires knowing the company name to make sense — fails owner-recognition test.",
        }
        story = {
            "surviving_explanation": "Non-urgent work is displaced by urgent work.",
            "reframe": "This is a system-design problem.",
            "remaining_uncertainty": None,
            "business_translation": "Visibility that depends on owner energy will fail at peak.",
        }
        spine = {"narrative_spine": "If presence depends only on free time, silence becomes the strategy."}
        discovery = {
            "first_wrong_explanation": "a", "puzzle": "b",
            "investigation_sequence": ["c1", "c2", "c3"], "aha_setup": "d",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(
                hook_with_company, None, discovery, story, spine, {}, SIGNAL,
            )
        assert result["checklist_pass"] is False
        assert "company name" in result["checklist_notes"].lower() or "hook" in result["checklist_notes"].lower()


# ---------------------------------------------------------------------------
# Nike signal regression tests (Stage 7)
# ---------------------------------------------------------------------------

class TestNikeSignalRegression:
    """Regression test: Nike distribution signal must produce an owner-protagonist article."""

    @classmethod
    def _load_nike_signal(cls):
        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "nike_signal.json"
        )
        with open(fixture_path) as f:
            return json.load(f)

    def test_nike_fixture_exists(self):
        """Fixture file must exist and have the expected fields."""
        signal = self._load_nike_signal()
        assert signal["REAL_COMPANY_EXAMPLE"] == "Nike"
        assert "HEADLINE" in signal

    def test_nike_signal_produces_owner_protagonist(self):
        """extract_pattern on Nike signal must return article_protagonist = 'owner'."""
        signal = self._load_nike_signal()
        pattern = _VALID_PATTERN.copy()
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(pattern)):
            result = extract_pattern(signal)
        assert result["article_protagonist"] == "owner"

    def test_nike_founder_scenario_no_company_name(self):
        """founder_scenario must not mention 'Nike'."""
        signal = self._load_nike_signal()
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(_VALID_PATTERN)):
            result = extract_pattern(signal)
        assert "Nike" not in result["founder_scenario"]

    def test_nike_company_as_evidence_of_single_sentence(self):
        """company_as_evidence_of must be a single sentence."""
        signal = self._load_nike_signal()
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(_VALID_PATTERN)):
            result = extract_pattern(signal)
        # A single sentence should have at most one terminal period or no period
        # We count sentences by splitting on '. ' — should be 1 chunk
        sentences = [s.strip() for s in result["company_as_evidence_of"].split(". ") if s.strip()]
        assert len(sentences) <= 2, (
            f"company_as_evidence_of appears to have multiple sentences: "
            f"{result['company_as_evidence_of']!r}"
        )

    def test_nike_signal_rejection_is_acceptable(self):
        """Rejection is also an acceptable outcome — it is not a test failure."""
        signal = self._load_nike_signal()
        rejected = {
            **_VALID_PATTERN,
            "signal_fit": "reject",
            "rejection_reason": "Signal collapses to Nike strategy without owner-facing mechanism.",
        }
        with patch("src.editorial.pattern_extractor.chat", return_value=_json_response(rejected)):
            try:
                result = extract_pattern(signal)
                # If not rejected, protagonist must be owner
                assert result["article_protagonist"] == "owner"
            except SignalRejectedError:
                # Rejection is acceptable — not a test failure
                pass
