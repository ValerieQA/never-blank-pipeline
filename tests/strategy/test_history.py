"""
Tests for src/strategy/history.py (Phase 4B).

Covers:
  4B.1 Strategy Rotation: rotate_strategy() archives current, writes new
  4B.2 Decision History: append_decision_log(), load_decision_log()
  4B.3 Published Index: append_published_entry(), load_published_index()
  4B.4 Review Archive: archive_weekly_reviews(), archive_monthly_review()
  mark_entries_reviewed()
  Edge cases: missing files, empty index, malformed lines
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.strategy.models import (
    Confidence,
    MonthlyDecision,
    PublishedEntry,
    StrategyChangeRecord,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strategy_json(strategy_id: str = "2026-08-test") -> dict:
    return {
        "strategy_id": strategy_id,
        "status": "active",
        "started_at": "2026-08-04",
        "review_date": "2026-08-31",
        "strategy_name": "Test Strategy",
        "strategy_summary": "Summary",
        "market_context": "Agencies go dark when busy",
        "selected_problem": "Owner-dependent presence",
        "sales_hypothesis": "If owners recognize the pattern, they want a system",
        "why_now": "Competition is up",
        "commercial_goal": "Generate qualified leads",
        "primary_message": "Presence should not depend on your free time",
        "compound_presence_role": "Demonstrate what systematic presence looks like",
        "desired_reader_realization": "That is happening to us",
        "primary_cta_intent": "reflection",
        "continuation_criteria": {"description": "At least 1 lead", "indicators": ["1+ leads"]},
        "adjustment_criteria": {"description": "No leads but growing", "indicators": ["Growing engagement"]},
        "replacement_criteria": {"description": "No leads, no trend", "indicators": ["0 leads after 4 weeks"]},
        "research_references": ["strategy/worldview.md"],
        "confidence": "high",
    }


def _published_entry(
    content_id: str = "sig-001",
    strategy_id: str = "2026-08-test",
    echo: str | None = "The competitor was just present.",
) -> PublishedEntry:
    return PublishedEntry(
        content_id=content_id,
        strategy_id=strategy_id,
        pattern_id="pat-001",
        published_at=datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
        platform="blog",
        url="https://example.com/article",
        echo=echo,
        hook="The month you were fully booked was the month you went quiet.",
        topic="Why agencies go dark when busy",
        cta_mode="reflection",
    )


def _change_record(strategy_id: str = "2026-08-test") -> StrategyChangeRecord:
    return StrategyChangeRecord(
        record_id="change-abc123",
        changed_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        from_strategy_id=strategy_id,
        to_strategy_id=None,
        decision=MonthlyDecision.REPLACE_STRATEGY,
        rationale="Hypothesis not confirmed after full cycle.",
        recommendation_id="rec-2026-08-abc12345",
        trigger_ref="strategy/reviews/monthly/2026-08-test_monthly.json",
    )


# ── 4B.1 Strategy Rotation ─────────────────────────────────────────────────────

class TestRotateStrategy:
    def test_archives_current_and_writes_new(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_DIR", tmp_path / "current")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "current" / "strategy.json")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_MD", tmp_path / "current" / "strategy.md")
        monkeypatch.setattr(h, "HISTORY_STRATEGIES_DIR", tmp_path / "history" / "strategies")

        (tmp_path / "current").mkdir(parents=True)
        current_data = _strategy_json("2026-08-old")
        (tmp_path / "current" / "strategy.json").write_text(json.dumps(current_data))
        (tmp_path / "current" / "strategy.md").write_text("# Old strategy")

        new_data = _strategy_json("2026-09-new")
        archive_path = h.rotate_strategy(new_data)

        # Archive exists and contains old strategy_id
        assert archive_path.exists()
        archived = json.loads(archive_path.read_text())
        assert archived["strategy_id"] == "2026-08-old"

        # Current file now contains new strategy
        current = json.loads((tmp_path / "current" / "strategy.json").read_text())
        assert current["strategy_id"] == "2026-09-new"

    def test_archives_md_alongside_json(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_DIR", tmp_path / "current")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "current" / "strategy.json")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_MD", tmp_path / "current" / "strategy.md")
        monkeypatch.setattr(h, "HISTORY_STRATEGIES_DIR", tmp_path / "history" / "strategies")

        (tmp_path / "current").mkdir(parents=True)
        (tmp_path / "current" / "strategy.json").write_text(json.dumps(_strategy_json("2026-08-old")))
        (tmp_path / "current" / "strategy.md").write_text("# Old strategy md content")

        h.rotate_strategy(_strategy_json("2026-09-new"))

        md_files = list((tmp_path / "history" / "strategies").glob("*2026-08-old.md"))
        assert len(md_files) == 1
        assert "Old strategy md content" in md_files[0].read_text()

    def test_raises_if_no_current_strategy(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "nonexistent.json")

        with pytest.raises(FileNotFoundError, match="does not exist"):
            h.rotate_strategy(_strategy_json("2026-09-new"))

    def test_raises_if_new_strategy_missing_id(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_DIR", tmp_path / "current")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "current" / "strategy.json")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_MD", tmp_path / "current" / "strategy.md")
        monkeypatch.setattr(h, "HISTORY_STRATEGIES_DIR", tmp_path / "history" / "strategies")

        (tmp_path / "current").mkdir(parents=True)
        (tmp_path / "current" / "strategy.json").write_text(json.dumps(_strategy_json()))

        with pytest.raises(ValueError, match="strategy_id"):
            h.rotate_strategy({"strategy_name": "No ID here"})

    def test_archive_filename_contains_date_and_strategy_id(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_DIR", tmp_path / "current")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "current" / "strategy.json")
        monkeypatch.setattr(h, "CURRENT_STRATEGY_MD", tmp_path / "current" / "strategy.md")
        monkeypatch.setattr(h, "HISTORY_STRATEGIES_DIR", tmp_path / "history" / "strategies")

        (tmp_path / "current").mkdir(parents=True)
        (tmp_path / "current" / "strategy.json").write_text(json.dumps(_strategy_json("2026-08-presence-debt")))

        archive_path = h.rotate_strategy(_strategy_json("2026-09-new"))

        assert "2026-08-presence-debt" in archive_path.name
        assert archive_path.suffix == ".json"


# ── 4B.2 Decision History ──────────────────────────────────────────────────────

class TestDecisionLog:
    def test_append_creates_file_and_writes_entry(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "DECISIONS_DIR", tmp_path / "decisions")
        monkeypatch.setattr(h, "DECISION_LOG", tmp_path / "decisions" / "decision_log.jsonl")

        record = _change_record()
        h.append_decision_log(record)

        log_path = tmp_path / "decisions" / "decision_log.jsonl"
        assert log_path.exists()
        lines = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["from_strategy_id"] == "2026-08-test"
        assert data["decision"] == "REPLACE_STRATEGY"

    def test_append_multiple_records_in_order(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "DECISIONS_DIR", tmp_path / "decisions")
        monkeypatch.setattr(h, "DECISION_LOG", tmp_path / "decisions" / "decision_log.jsonl")

        h.append_decision_log(_change_record("2026-07-first"))
        h.append_decision_log(_change_record("2026-08-second"))

        entries = h.load_decision_log()
        assert len(entries) == 2
        assert entries[0]["from_strategy_id"] == "2026-07-first"
        assert entries[1]["from_strategy_id"] == "2026-08-second"

    def test_load_decision_log_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "DECISION_LOG", tmp_path / "nonexistent.jsonl")

        assert h.load_decision_log() == []

    def test_load_decision_log_skips_malformed_lines(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        log_path = tmp_path / "decision_log.jsonl"
        log_path.write_text('{"from_strategy_id": "valid"}\n{invalid json}\n{"from_strategy_id": "also_valid"}\n')
        monkeypatch.setattr(h, "DECISION_LOG", log_path)

        entries = h.load_decision_log()
        assert len(entries) == 2
        assert entries[0]["from_strategy_id"] == "valid"


# ── 4B.3 Published Index ───────────────────────────────────────────────────────

class TestPublishedIndex:
    def test_append_creates_file_and_writes_entry(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")

        h.append_published_entry(_published_entry())

        index_path = tmp_path / "published_content_index.jsonl"
        assert index_path.exists()
        lines = [l for l in index_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["content_id"] == "sig-001"
        assert data["echo"] == "The competitor was just present."

    def test_append_multiple_entries_in_order(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")

        h.append_published_entry(_published_entry("sig-001"))
        h.append_published_entry(_published_entry("sig-002"))
        h.append_published_entry(_published_entry("sig-003"))

        entries = h.load_published_index()
        assert len(entries) == 3
        assert entries[0].content_id == "sig-001"
        assert entries[2].content_id == "sig-003"

    def test_load_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "nonexistent.jsonl")

        assert h.load_published_index() == []

    def test_filter_by_strategy_id(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")

        h.append_published_entry(_published_entry("sig-001", strategy_id="2026-07-old"))
        h.append_published_entry(_published_entry("sig-002", strategy_id="2026-08-new"))
        h.append_published_entry(_published_entry("sig-003", strategy_id="2026-08-new"))

        entries = h.load_published_index(strategy_id="2026-08-new")
        assert len(entries) == 2
        assert all(e.strategy_id == "2026-08-new" for e in entries)

    def test_last_n_returns_most_recent(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")

        for i in range(5):
            h.append_published_entry(_published_entry(f"sig-{i:03d}"))

        entries = h.load_published_index(last_n=3)
        assert len(entries) == 3
        assert entries[0].content_id == "sig-002"
        assert entries[2].content_id == "sig-004"

    def test_null_echo_stored_as_null(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")

        h.append_published_entry(_published_entry("sig-no-echo", echo=None))

        entries = h.load_published_index()
        assert entries[0].echo is None

    def test_reviewed_defaults_to_false(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")

        h.append_published_entry(_published_entry())
        entries = h.load_published_index()
        assert entries[0].reviewed is False

    def test_skips_malformed_lines(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        valid = json.dumps({
            "content_id": "sig-001", "strategy_id": "2026-08-test",
            "published_at": "2026-08-07T10:00:00+00:00", "platform": "blog",
            "url": "", "hook": "", "topic": "", "cta_mode": "none", "reviewed": False,
        })
        index_path.write_text(f"{valid}\n{{invalid json}}\n")
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        entries = h.load_published_index()
        assert len(entries) == 1
        assert entries[0].content_id == "sig-001"


# ── 4B.4 Review Archive ────────────────────────────────────────────────────────

class TestReviewArchive:
    def test_archive_weekly_reviews_moves_files(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        weekly_dir = tmp_path / "reviews" / "weekly"
        history_reviews_dir = tmp_path / "history" / "reviews"
        monkeypatch.setattr(h, "WEEKLY_REVIEWS_DIR", weekly_dir)
        monkeypatch.setattr(h, "HISTORY_REVIEWS_DIR", history_reviews_dir)

        weekly_dir.mkdir(parents=True)
        (weekly_dir / "2026-08-test_w01.json").write_text('{"week_number": 1}')
        (weekly_dir / "2026-08-test_w02.json").write_text('{"week_number": 2}')
        (weekly_dir / "other-strategy_w01.json").write_text('{"week_number": 1}')

        h.archive_weekly_reviews("2026-08-test")

        dest = history_reviews_dir / "2026-08-test"
        assert (dest / "2026-08-test_w01.json").exists()
        assert (dest / "2026-08-test_w02.json").exists()
        assert not (weekly_dir / "2026-08-test_w01.json").exists()
        assert (weekly_dir / "other-strategy_w01.json").exists()  # untouched

    def test_archive_weekly_reviews_no_files_is_safe(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        weekly_dir = tmp_path / "reviews" / "weekly"
        weekly_dir.mkdir(parents=True)
        monkeypatch.setattr(h, "WEEKLY_REVIEWS_DIR", weekly_dir)
        monkeypatch.setattr(h, "HISTORY_REVIEWS_DIR", tmp_path / "history" / "reviews")

        # Should not raise
        h.archive_weekly_reviews("2026-08-nonexistent")

    def test_archive_weekly_reviews_missing_dir_is_safe(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "WEEKLY_REVIEWS_DIR", tmp_path / "nonexistent")
        monkeypatch.setattr(h, "HISTORY_REVIEWS_DIR", tmp_path / "history" / "reviews")

        h.archive_weekly_reviews("2026-08-test")  # should not raise

    def test_archive_monthly_review_moves_file(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monthly_dir = tmp_path / "reviews" / "monthly"
        history_reviews_dir = tmp_path / "history" / "reviews"
        monkeypatch.setattr(h, "MONTHLY_REVIEWS_DIR", monthly_dir)
        monkeypatch.setattr(h, "HISTORY_REVIEWS_DIR", history_reviews_dir)

        monthly_dir.mkdir(parents=True)
        (monthly_dir / "2026-08-test_monthly.json").write_text('{"decision": "REPLACE_STRATEGY"}')

        h.archive_monthly_review("2026-08-test")

        dest = history_reviews_dir / "2026-08-test" / "2026-08-test_monthly.json"
        assert dest.exists()
        assert not (monthly_dir / "2026-08-test_monthly.json").exists()

    def test_archive_monthly_review_missing_file_is_safe(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monthly_dir = tmp_path / "reviews" / "monthly"
        monthly_dir.mkdir(parents=True)
        monkeypatch.setattr(h, "MONTHLY_REVIEWS_DIR", monthly_dir)
        monkeypatch.setattr(h, "HISTORY_REVIEWS_DIR", tmp_path / "history" / "reviews")

        h.archive_monthly_review("2026-08-nonexistent")  # should not raise


# ── mark_entries_reviewed ──────────────────────────────────────────────────────

class TestMarkEntriesReviewed:
    def test_marks_unreviewed_entries(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        h.append_published_entry(_published_entry("sig-001"))
        h.append_published_entry(_published_entry("sig-002"))

        count = h.mark_entries_reviewed("2026-08-test", week_number=1)

        assert count == 2
        entries = h.load_published_index()
        assert all(e.reviewed for e in entries)

    def test_skips_already_reviewed_entries(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        entry = _published_entry("sig-001")
        h.append_published_entry(entry)
        h.mark_entries_reviewed("2026-08-test", week_number=1)

        count = h.mark_entries_reviewed("2026-08-test", week_number=2)
        assert count == 0

    def test_only_marks_entries_for_given_strategy(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        h.append_published_entry(_published_entry("sig-001", strategy_id="2026-08-test"))
        h.append_published_entry(_published_entry("sig-002", strategy_id="2026-09-other"))

        h.mark_entries_reviewed("2026-08-test", week_number=1)

        entries = h.load_published_index()
        test_entry = next(e for e in entries if e.strategy_id == "2026-08-test")
        other_entry = next(e for e in entries if e.strategy_id == "2026-09-other")
        assert test_entry.reviewed is True
        assert other_entry.reviewed is False

    def test_returns_zero_when_no_index(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "nonexistent.jsonl")

        assert h.mark_entries_reviewed("2026-08-test", week_number=1) == 0
