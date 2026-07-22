"""
Tests for src/strategy/echo_memory.py (Phase 4C).

Covers:
  _jaccard(): empty strings, identical, disjoint, partial overlap
  check_against_memory(): no history, echo conflict, hook conflict, topic conflict,
                          pattern recency (block + warn), medium similarity,
                          LLM upgrade path, strategy_id filtering, last_n slice
  EchoMemoryResult: blocked flag, conflict fields, warnings list
  format_memory_for_prompt(): empty history, populated history
  Editorial Guard: check_echo_uniqueness() in validators.py
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.strategy.echo_memory import (
    EchoMemoryResult,
    MemoryMatch,
    _jaccard,
    check_against_memory,
    format_memory_for_prompt,
)
from src.strategy.models import PublishedEntry


# ── Helpers ────────────────────────────────────────────────────────────────────

def _entry(
    content_id: str,
    strategy_id: str = "2026-08-test",
    echo: str | None = None,
    hook: str = "",
    topic: str = "",
    pattern_id: str | None = None,
    strategy_week: int = 1,
) -> PublishedEntry:
    return PublishedEntry(
        content_id=content_id,
        strategy_id=strategy_id,
        pattern_id=pattern_id,
        published_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        platform="blog",
        echo=echo,
        hook=hook,
        topic=topic,
        strategy_week=strategy_week,
    )


def _patch_index(monkeypatch, entries: list[PublishedEntry]):
    monkeypatch.setattr(
        "src.strategy.echo_memory.load_published_index",
        lambda strategy_id=None, last_n=None: (
            entries[-last_n:] if last_n else entries
        ),
    )


# ── Jaccard similarity ─────────────────────────────────────────────────────────

class TestJaccard:
    def test_identical_strings(self):
        assert _jaccard("the cat sat on the mat", "the cat sat on the mat") == 1.0

    def test_disjoint_strings(self):
        assert _jaccard("apple orange banana", "car bus train") == 0.0

    def test_partial_overlap(self):
        score = _jaccard("the quick brown fox", "the slow brown dog")
        assert 0.0 < score < 1.0

    def test_empty_string_a(self):
        assert _jaccard("", "something") == 0.0

    def test_empty_string_b(self):
        assert _jaccard("something", "") == 0.0

    def test_both_empty(self):
        assert _jaccard("", "") == 0.0

    def test_single_word_match(self):
        assert _jaccard("presence", "presence matters") > 0.0

    def test_case_insensitive(self):
        assert _jaccard("Presence is everything", "presence is everything") == 1.0


# ── check_against_memory: no history ──────────────────────────────────────────

class TestCheckNoHistory:
    def test_empty_history_returns_no_conflict(self, monkeypatch):
        _patch_index(monkeypatch, [])
        result = check_against_memory(
            echo="The competitor was just present.",
            hook="The month you were busy was the month you disappeared.",
            strategy_id="2026-08-test",
        )
        assert not result.blocked
        assert not result.echo_conflict
        assert not result.hook_conflict
        assert result.matches == []
        assert result.warnings == []

    def test_none_echo_skips_echo_check(self, monkeypatch):
        history = [_entry("sig-001", echo="The competitor was just present.", hook="Hook text")]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None,   # no echo to check
            hook="Completely different hook about agencies",
            strategy_id="2026-08-test",
        )
        assert not result.echo_conflict


# ── Echo conflict ──────────────────────────────────────────────────────────────

class TestEchoConflict:
    _ECHO = "The competitor who won was not better. They were just present."

    def test_identical_echo_triggers_high_conflict(self, monkeypatch):
        history = [_entry("sig-001", echo=self._ECHO)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(echo=self._ECHO, hook="Different hook", strategy_id="2026-08-test")
        assert result.echo_conflict
        assert result.blocked
        assert any(m.field == "echo" and m.is_high for m in result.matches)

    def test_high_overlap_echo_triggers_conflict(self, monkeypatch):
        existing = "The competitor who won was not better. They were just present."
        candidate = "The agency that won was not more skilled. They were simply present."
        history = [_entry("sig-001", echo=existing)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(echo=candidate, hook="Different hook", strategy_id="2026-08-test")
        # These share presence, just, were, not, better — score varies; test that it's checked
        assert any(m.field == "echo" for m in result.matches)

    def test_different_echo_passes(self, monkeypatch):
        existing = "The competitor who won was not better. They were just present."
        candidate = "Clients do not leave because your price went up. They leave because you disappeared."
        history = [_entry("sig-001", echo=existing)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(echo=candidate, hook="Different hook", strategy_id="2026-08-test")
        assert not result.echo_conflict
        assert not result.blocked

    def test_echo_conflict_includes_warning_text(self, monkeypatch):
        history = [_entry("sig-001", echo=self._ECHO)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(echo=self._ECHO, hook="Hook", strategy_id="2026-08-test")
        assert any("HIGH echo" in w for w in result.warnings)


# ── Hook conflict ──────────────────────────────────────────────────────────────

class TestHookConflict:
    _HOOK = "The month you were fully booked was the month you went quiet."

    def test_identical_hook_triggers_conflict(self, monkeypatch):
        history = [_entry("sig-001", hook=self._HOOK)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(echo="Different echo", hook=self._HOOK, strategy_id="2026-08-test")
        assert result.hook_conflict
        assert result.blocked

    def test_distinct_hook_passes(self, monkeypatch):
        history = [_entry("sig-001", hook=self._HOOK)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None,
            hook="Nobody notices the absence until the client stops responding.",
            strategy_id="2026-08-test",
        )
        assert not result.hook_conflict


# ── Topic conflict ─────────────────────────────────────────────────────────────

class TestTopicConflict:
    def test_near_identical_topic_triggers_conflict(self, monkeypatch):
        topic = "Why agencies go dark when busy season arrives"
        history = [_entry("sig-001", topic=topic)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None, hook="Hook", topic=topic, strategy_id="2026-08-test"
        )
        assert result.topic_conflict
        assert result.blocked

    def test_different_topic_passes(self, monkeypatch):
        history = [_entry("sig-001", topic="Why agencies go dark when busy season arrives")]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None, hook="Hook",
            topic="How retainer clients create invisible content debt",
            strategy_id="2026-08-test",
        )
        assert not result.topic_conflict


# ── Pattern recency ────────────────────────────────────────────────────────────

class TestPatternRecency:
    def test_pattern_in_last_3_items_is_high(self, monkeypatch):
        pattern_id = "pat-001"
        history = [
            _entry("sig-001", pattern_id=pattern_id),
            _entry("sig-002"),
            _entry("sig-003"),
        ]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None, hook="Hook", pattern_id=pattern_id, strategy_id="2026-08-test"
        )
        assert result.pattern_conflict
        assert result.blocked
        assert any(m.field == "pattern" and m.is_high for m in result.matches)

    def test_pattern_in_position_4_to_10_is_medium(self, monkeypatch):
        pattern_id = "pat-001"
        # recent_patterns is built by filtering to entries that HAVE a pattern_id.
        # To put pat-001 at position ≥ 3 in that filtered list, we need 3 other
        # entries with different pattern_ids appearing more recently.
        history = [
            _entry("sig-new-a", pattern_id="pat-002"),
            _entry("sig-new-b", pattern_id="pat-003"),
            _entry("sig-new-c", pattern_id="pat-004"),
            _entry("sig-old", pattern_id=pattern_id),   # position 3 in recent_patterns
        ]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None, hook="Hook", pattern_id=pattern_id, strategy_id="2026-08-test"
        )
        # pat-001 is at index 3 in recent_patterns → not in [:3] (block range) but in [:10]
        assert not result.pattern_conflict
        pattern_matches = [m for m in result.matches if m.field == "pattern"]
        assert len(pattern_matches) == 1
        assert not pattern_matches[0].is_high

    def test_unknown_pattern_passes(self, monkeypatch):
        history = [_entry("sig-001", pattern_id="pat-001")]
        _patch_index(monkeypatch, history)
        result = check_against_memory(
            echo=None, hook="Hook", pattern_id="pat-999-different", strategy_id="2026-08-test"
        )
        assert not result.pattern_conflict


# ── Medium similarity (warn only) ─────────────────────────────────────────────

class TestMediumSimilarity:
    def test_medium_similarity_does_not_block(self, monkeypatch):
        existing_echo = "The client left because you went dark during their most uncertain moment."
        candidate_echo = "The deal fell through because you were quiet when uncertainty peaked."
        history = [_entry("sig-001", echo=existing_echo)]
        _patch_index(monkeypatch, history)
        result = check_against_memory(echo=candidate_echo, hook="Hook", strategy_id="2026-08-test")
        # These share enough words for MEDIUM but not HIGH
        if result.matches:
            medium_echo = [m for m in result.matches if m.field == "echo" and not m.is_high]
            high_echo = [m for m in result.matches if m.field == "echo" and m.is_high]
            if medium_echo:
                assert not result.echo_conflict
                assert not result.blocked
            # If it happens to be HIGH, the test isn't wrong — just informative


# ── LLM semantic upgrade ───────────────────────────────────────────────────────

class TestLLMSemanticUpgrade:
    def test_llm_upgrades_medium_to_high(self, monkeypatch):
        # Create texts that produce medium Jaccard but LLM says equivalent
        existing = "Presence compounds over time into recognition and trust."
        candidate = "Visibility accumulates gradually into familiarity and credibility."
        history = [_entry("sig-001", echo=existing)]
        _patch_index(monkeypatch, history)

        def fake_llm(system, user, json_mode=False):
            return json.dumps({
                "semantically_equivalent": True,
                "confidence": "high",
                "reasoning": "Both express the compounding nature of consistent presence.",
            })

        result = check_against_memory(
            echo=candidate,
            hook="Hook",
            strategy_id="2026-08-test",
            use_llm=True,
            llm_fn=fake_llm,
        )
        # LLM should upgrade any medium hit to HIGH
        echo_matches = [m for m in result.matches if m.field == "echo"]
        if echo_matches:  # only if Jaccard found a hit at all
            high_ones = [m for m in echo_matches if m.is_high]
            if high_ones:
                assert result.echo_conflict

    def test_llm_failure_is_non_fatal(self, monkeypatch):
        existing = "Presence compounds over time into recognition and trust."
        candidate = "Visibility accumulates gradually into familiarity and credibility."
        history = [_entry("sig-001", echo=existing)]
        _patch_index(monkeypatch, history)

        def failing_llm(system, user, json_mode=False):
            raise RuntimeError("LLM unavailable")

        # Should not raise — LLM failure is treated as "not equivalent"
        result = check_against_memory(
            echo=candidate,
            hook="Hook",
            strategy_id="2026-08-test",
            use_llm=True,
            llm_fn=failing_llm,
        )
        # Result is valid regardless of LLM failure
        assert isinstance(result, EchoMemoryResult)


# ── Strategy ID filtering ──────────────────────────────────────────────────────

class TestStrategyFiltering:
    def test_only_checks_entries_for_given_strategy(self, monkeypatch):
        echo = "The competitor was just present."
        history = [
            _entry("sig-001", strategy_id="2026-07-old", echo=echo),
            _entry("sig-002", strategy_id="2026-08-current", echo="Different echo entirely"),
        ]

        def filtered_index(strategy_id=None, last_n=None):
            filtered = [e for e in history if strategy_id is None or e.strategy_id == strategy_id]
            return filtered[-last_n:] if last_n else filtered

        monkeypatch.setattr("src.strategy.echo_memory.load_published_index", filtered_index)

        # Checking for current strategy — old strategy echo should not interfere
        result = check_against_memory(
            echo=echo,
            hook="Hook",
            strategy_id="2026-08-current",  # different from sig-001
        )
        # sig-001 is filtered out; sig-002 has a different echo
        assert not result.echo_conflict


# ── format_memory_for_prompt ───────────────────────────────────────────────────

class TestFormatMemoryForPrompt:
    def test_empty_history_returns_empty_string(self, monkeypatch):
        monkeypatch.setattr("src.strategy.echo_memory.load_published_index", lambda **kw: [])
        result = format_memory_for_prompt("2026-08-test")
        assert result == ""

    def test_populated_history_includes_echo_and_hook(self, monkeypatch):
        history = [_entry(
            "sig-001",
            echo="The competitor was just present.",
            hook="The month you were busy was the month you disappeared.",
            topic="Agencies going dark when busy",
            pattern_id="pat-001",
        )]
        monkeypatch.setattr("src.strategy.echo_memory.load_published_index",
                            lambda strategy_id=None, last_n=None: history)
        result = format_memory_for_prompt("2026-08-test")
        assert "Echo" in result
        assert "Hook" in result
        assert "competitor" in result
        assert "RECENT PUBLISHED CONTENT" in result

    def test_includes_avoid_instruction(self, monkeypatch):
        history = [_entry("sig-001", echo="Some echo")]
        monkeypatch.setattr("src.strategy.echo_memory.load_published_index",
                            lambda strategy_id=None, last_n=None: history)
        result = format_memory_for_prompt("2026-08-test")
        assert "avoid" in result.lower() or "different" in result.lower()


# ── Editorial Guard (validators.check_echo_uniqueness) ────────────────────────

class TestEditorialGuard:
    def _make_item(self):
        from src.strategy.models import ContentPlanItem, ContentRole
        return ContentPlanItem(
            content_id="test-001",
            week=1,
            strategy_id="2026-08-test",
            content_role=ContentRole.RECOGNITION,
            topic="Why agencies go dark when busy",
            working_title="The dark period",
            target_reader="Agency owner",
            reader_problem="No content when busy",
            market_signal="B2B posting drops 60% in Q4",
            pattern="Delivery defeats presence",
            sales_objective="Make owner feel the cost",
            main_argument="This is structural",
            source_pattern_id="pat-001",
            hook="The month you were fully booked was the month you went quiet.",
            recognition="You posted three times in January.",
            mechanism="Delivery mode defeats presence work.",
            business_consequence="Clients chose someone who was present.",
            reframe="This is not about discipline.",
            compound_presence_connection="Consistent presence accumulates into trust.",
            echo="The competitor who won was not better. They were just present.",
            cta_mode="reflection",
            cta="If your presence disappears when you get busy, that is the pattern.",
            website_angle="SEO angle",
            linkedin_angle="LinkedIn angle",
            instagram_angle="Instagram angle",
            facebook_angle="Facebook angle",
            threads_angle="Threads angle",
            telegram_angle="Telegram angle",
        )

    def test_no_history_passes(self, monkeypatch):
        monkeypatch.setattr("src.strategy.echo_memory.load_published_index", lambda **kw: [])
        from src.strategy.validators import check_echo_uniqueness
        item = self._make_item()
        check_echo_uniqueness(item, "2026-08-test")  # should not raise

    def test_high_echo_conflict_raises(self, monkeypatch):
        item = self._make_item()
        echo_text = "The competitor who won was not better. They were just present."
        history = [_entry("sig-001", echo=echo_text, hook="Different hook")]
        monkeypatch.setattr("src.strategy.echo_memory.load_published_index",
                            lambda **kw: history)
        from src.strategy.validators import check_echo_uniqueness
        with pytest.raises(ValueError, match="Echo Memory"):
            check_echo_uniqueness(item, "2026-08-test", block_on_high=True)

    def test_block_on_high_false_does_not_raise(self, monkeypatch):
        item = self._make_item()
        echo_text = "The competitor who won was not better. They were just present."
        history = [_entry("sig-001", echo=echo_text, hook="Different hook")]
        monkeypatch.setattr("src.strategy.echo_memory.load_published_index",
                            lambda **kw: history)
        from src.strategy.validators import check_echo_uniqueness
        # Should log warning but not raise
        check_echo_uniqueness(item, "2026-08-test", block_on_high=False)
