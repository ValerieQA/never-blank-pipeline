"""
Tests for src/editorial/* (Editorial Engine V2 wiring).

Covers, per module:
- decision_lens_lite: schema validation (required fields, confidence enum)
- narrative_spine: target_feeling enum enforcement
- hook_engine: minimum candidate count, selected_hook must match a candidate
- reader_context: household-name skip is pure Python (no LLM call), word-count limit
- discovery_builder: investigation_sequence length bounds (3-5)
- story_assembly: remaining_uncertainty accepts string or null, rejects other types
- never_blank_voice: signature required; checklist_pass=False does not raise
- platform_composer: empty body raises; signature safety-net appends if missing
- pipeline: happy path wiring; a stage that fails twice raises ArticleGenerationError
"""

import json
from unittest.mock import patch

import pytest

from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.narrative_spine import build_narrative_spine
from src.editorial.hook_engine import generate_hook
from src.editorial.reader_context import build_reader_context
from src.editorial.discovery_builder import build_discovery
from src.editorial.story_assembly import assemble_story
from src.editorial.never_blank_voice import finalize_article
from src.editorial.platform_composer import compose_platforms, _WORD_RANGE
from src.editorial.pipeline import generate_article, ArticleGenerationError


SIGNAL = {
    "SIGNAL_ID": "sig123",
    "HEADLINE": "Acme Corp raises prices 20%",
    "CORE_FACT": "Acme raised prices after a supplier dispute.",
    "CORE_TENSION": "Protect margin vs. protect customer trust.",
    "REAL_COMPANY_EXAMPLE": "Acme Corp",
    "RESPONSE_TAKEN": "Raised prices and renegotiated supplier contracts.",
    "OUTCOME_IF_KNOWN": "Churn rose 3%.",
    "BUSINESS_LESSON": "Pricing power is a proxy for supplier leverage.",
    "WHY_THIS_CASE_IS_INTERESTING": "The price hike preceded the dispute becoming public.",
    "COUNTER_EXAMPLE": "A competitor absorbed the cost instead.",
}


def _json_response(data: dict) -> str:
    return json.dumps(data)


# --- decision_lens_lite ---

class TestDecisionLensLite:
    VALID = {
        "core_decision": "Whether to pass supplier cost onto customers now or absorb it.",
        "strategic_objective": "Protect gross margin over near-term retention.",
        "strategic_objective_evidence": ["Price hike preceded public dispute."],
        "strategic_objective_confidence": "medium",
        "business_lesson": "Margin protection can outrank retention risk.",
        "never_blank_insight": "The timing reveals the real priority.",
    }

    def test_valid_response_passes(self):
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(self.VALID)):
            result = generate_decision_lens(SIGNAL)
        assert result["core_decision"] == self.VALID["core_decision"]
        assert result["strategic_objective_confidence"] == "medium"

    def test_missing_field_raises(self):
        bad = {**self.VALID, "business_lesson": ""}
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="business_lesson"):
                generate_decision_lens(SIGNAL)

    def test_invalid_confidence_raises(self):
        bad = {**self.VALID, "strategic_objective_confidence": "very_high"}
        with patch("src.editorial.decision_lens_lite.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="strategic_objective_confidence"):
                generate_decision_lens(SIGNAL)


# --- narrative_spine ---

class TestNarrativeSpine:
    DECISION_LENS = {
        "core_decision": "Whether to raise prices before the dispute became public.",
        "strategic_objective": "Protect gross margin over near-term retention.",
        "strategic_objective_confidence": "medium",
        "business_lesson": "Margin protection can outrank retention risk.",
        "never_blank_insight": "The timing reveals the real priority.",
    }
    VALID = {
        "core_decision": "Whether to raise prices before the dispute became public.",
        "narrative_spine": "Protecting margin quietly is still a choice to spend trust.",
        "target_feeling": "unease",
        "company_as_evidence_of": "What it costs to protect margin before anyone is watching.",
    }

    def test_valid_response_passes(self):
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(self.VALID)):
            result = build_narrative_spine(self.DECISION_LENS, SIGNAL)
        assert result["target_feeling"] == "unease"

    def test_invalid_target_feeling_raises(self):
        bad = {**self.VALID, "target_feeling": "excitement"}
        with patch("src.editorial.narrative_spine.chat", return_value=_json_response(bad)):
            with pytest.raises(ValueError, match="target_feeling"):
                build_narrative_spine(self.DECISION_LENS, SIGNAL)


# --- hook_engine ---

class TestHookEngine:
    SPINE = {"narrative_spine": "Protecting margin quietly is still a choice to spend trust."}
    DECISION_LENS = {"never_blank_insight": "x", "strategic_objective": "y"}

    def _candidates(self, n=5):
        types = ["contradiction", "invisible_signal", "surprising_question", "wrong_consensus", "hidden_decision"]
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
        Regression test for a production bug (2026-07-06 Klarna signal):
        REAL_COMPANY_EXAMPLE frequently holds a comparison/precedent company
        (e.g. "Varo Money" cited as the first fintech to get a bank charter),
        not the subject of the article. build_reader_context must not treat
        REAL_COMPANY_EXAMPLE as "the company" — it must not appear in the
        prompt sent to the LLM at all, and the household-name check must be
        driven by HEADLINE only, not by REAL_COMPANY_EXAMPLE.
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
    HOOK = {"selected_hook": "Acme raised prices. Then it blamed the supplier."}
    SPINE = {"narrative_spine": "Protecting margin quietly is still a choice to spend trust."}
    DECISION_LENS = {"strategic_objective": "Protect margin"}

    VALID = {
        "first_wrong_explanation": "Acme raised prices purely because of supplier costs.",
        "puzzle": "The price hike was announced before the supplier dispute became public.",
        "investigation_sequence": ["Prices rose in March.", "The dispute surfaced in May.", "Churn data lagged both."],
        "aha_setup": "The margin protection was already in motion before anyone could blame the supplier.",
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
        "first_wrong_explanation": "x", "puzzle": "y",
        "investigation_sequence": ["a", "b", "c"], "aha_setup": "z",
    }
    SPINE = {"narrative_spine": "s"}
    DECISION_LENS = {"strategic_objective": "o", "business_lesson": "l"}

    def test_null_remaining_uncertainty_accepted(self):
        data = {
            "surviving_explanation": "Acme protected margin deliberately.",
            "remaining_uncertainty": None,
            "business_translation": "Founders should watch pricing timing, not just pricing level.",
        }
        with patch("src.editorial.story_assembly.chat", return_value=_json_response(data)):
            result = assemble_story(self.DISCOVERY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["remaining_uncertainty"] is None

    def test_non_string_remaining_uncertainty_raises(self):
        data = {
            "surviving_explanation": "Acme protected margin deliberately.",
            "remaining_uncertainty": 123,
            "business_translation": "Founders should watch pricing timing, not just pricing level.",
        }
        with patch("src.editorial.story_assembly.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="remaining_uncertainty"):
                assemble_story(self.DISCOVERY, self.SPINE, self.DECISION_LENS, SIGNAL)


# --- never_blank_voice ---

class TestNeverBlankVoice:
    HOOK = {"selected_hook": "hook text"}
    DISCOVERY = {"first_wrong_explanation": "a", "puzzle": "b", "investigation_sequence": ["c"], "aha_setup": "d"}
    STORY = {"surviving_explanation": "e", "remaining_uncertainty": None, "business_translation": "f"}
    SPINE = {"narrative_spine": "s"}
    DECISION_LENS = {}

    def test_missing_signature_raises(self):
        data = {"signature": "", "checklist_pass": True, "checklist_notes": ""}
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            with pytest.raises(ValueError, match="signature"):
                finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)

    def test_checklist_fail_does_not_raise(self):
        data = {
            "signature": "Never Blank: Margin protection is a timing decision, not a cost decision.",
            "checklist_pass": False,
            "checklist_notes": "Ending is not stronger than the hook.",
        }
        with patch("src.editorial.never_blank_voice.chat", return_value=_json_response(data)):
            result = finalize_article(self.HOOK, None, self.DISCOVERY, self.STORY, self.SPINE, self.DECISION_LENS, SIGNAL)
        assert result["checklist_pass"] is False
        assert result["signature"].startswith("Never Blank:")


# --- platform_composer ---

class TestPlatformComposer:
    STRUCTURED_ARTICLE = {
        "signal_id": "sig123",
        "narrative_spine": "s",
        "hook": "hook text",
        "reader_context": None,
        "discovery": {
            "first_wrong_explanation": "a", "puzzle": "b",
            "investigation_sequence": ["c1", "c2", "c3"], "aha_setup": "d",
        },
        "surviving_explanation": "e",
        "remaining_uncertainty": None,
        "business_translation": "f",
        "signature": "Never Blank: the timing is the tell.",
    }

    def test_empty_body_raises(self):
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": ""})):
            with pytest.raises(ValueError, match="body"):
                compose_platforms(self.STRUCTURED_ARTICLE)

    def test_signature_appended_if_missing(self):
        body_without_signature = "A body that forgot to include the signature line."
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": body_without_signature})):
            result = compose_platforms(self.STRUCTURED_ARTICLE)
        for fmt in ("long", "reading", "medium", "instagram", "short"):
            assert self.STRUCTURED_ARTICLE["signature"] in result[fmt]["body"]

    def test_all_five_formats_present(self):
        with patch("src.editorial.platform_composer.chat", return_value=_json_response({"body": "some body text " * 20})):
            result = compose_platforms(self.STRUCTURED_ARTICLE)
        assert set(result.keys()) == set(_WORD_RANGE.keys())


# --- pipeline ---

class TestPipeline:
    def _patch_all_stages(self):
        """Patch every stage function inside src.editorial.pipeline's namespace."""
        return patch.multiple(
            "src.editorial.pipeline",
            generate_decision_lens=lambda signal: {
                "core_decision": "d", "strategic_objective": "o",
                "strategic_objective_evidence": [], "strategic_objective_confidence": "high",
                "business_lesson": "l", "never_blank_insight": "i",
            },
            build_narrative_spine=lambda dl, signal: {
                "core_decision": "d", "narrative_spine": "spine sentence",
                "target_feeling": "clarity", "company_as_evidence_of": "x",
            },
            generate_hook=lambda spine, dl, signal: {
                "hook_candidates": [{"type": "contradiction", "text": "hook"}],
                "selected_hook": "hook",
            },
            build_reader_context=lambda signal: None,
            build_discovery=lambda hook, spine, dl, signal: {
                "first_wrong_explanation": "a", "puzzle": "b",
                "investigation_sequence": ["c1", "c2", "c3"], "aha_setup": "d",
            },
            assemble_story=lambda discovery, spine, dl, signal: {
                "surviving_explanation": "e", "remaining_uncertainty": None, "business_translation": "f",
            },
            finalize_article=lambda hook, ctx, discovery, story, spine, dl, signal: {
                "signal_id": signal.get("SIGNAL_ID", ""), "narrative_spine": "spine sentence",
                "hook": "hook", "reader_context": None, "discovery": discovery,
                "surviving_explanation": "e", "remaining_uncertainty": None,
                "business_translation": "f", "signature": "Never Blank: x", "checklist_pass": True,
            },
            compose_platforms=lambda structured_article: {
                fmt: {"word_count": 10, "body": f"{fmt} body Never Blank: x"}
                for fmt in ("long", "reading", "medium", "instagram", "short")
            },
        )

    def test_happy_path_returns_full_result(self):
        with self._patch_all_stages():
            result = generate_article(SIGNAL)
        assert result["structured_article"]["signature"] == "Never Blank: x"
        assert set(result["platforms"].keys()) == {"long", "reading", "medium", "instagram", "short"}

    def test_stage_failing_twice_raises_article_generation_error(self):
        def _always_fails(signal):
            raise ValueError("LLM returned garbage")

        with patch("src.editorial.pipeline.generate_decision_lens", side_effect=_always_fails):
            with pytest.raises(ArticleGenerationError) as exc_info:
                generate_article(SIGNAL)
        assert exc_info.value.stage == "decision_lens_lite"
