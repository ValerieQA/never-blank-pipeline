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

def _setup_current_strategy(tmp_path, monkeypatch, strategy_id="2026-08-old"):
    """Helper: patch history module paths and write a current strategy file."""
    import src.strategy.history as h
    monkeypatch.setattr(h, "CURRENT_DIR", tmp_path / "current")
    monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "current" / "strategy.json")
    monkeypatch.setattr(h, "CURRENT_STRATEGY_MD", tmp_path / "current" / "strategy.md")
    monkeypatch.setattr(h, "HISTORY_STRATEGIES_DIR", tmp_path / "history" / "strategies")
    (tmp_path / "current").mkdir(parents=True)
    (tmp_path / "current" / "strategy.json").write_text(json.dumps(_strategy_json(strategy_id)))
    return h


class TestArchiveCurrentStrategy:
    def test_archives_json_to_history(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        archive_path = h.archive_current_strategy()
        assert archive_path.exists()
        archived = json.loads(archive_path.read_text())
        assert archived["strategy_id"] == "2026-08-old"

    def test_archive_filename_contains_timestamp_and_id(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch, "2026-08-presence-debt")
        archive_path = h.archive_current_strategy()
        assert "2026-08-presence-debt" in archive_path.name
        assert "T" in archive_path.name   # timestamp contains 'T' separator
        assert archive_path.suffix == ".json"

    def test_archives_md_alongside_json(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        (tmp_path / "current" / "strategy.md").write_text("# Old strategy md")
        h.archive_current_strategy()
        md_files = list((tmp_path / "history" / "strategies").glob("*2026-08-old.md"))
        assert len(md_files) == 1
        assert "Old strategy md" in md_files[0].read_text()

    def test_raises_if_no_current_strategy(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError, match="does not exist"):
            h.archive_current_strategy()

    def test_raises_on_archive_collision(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        h2 = _setup_current_strategy(tmp_path, monkeypatch)
        # Patch timestamp to always return the same value → force collision on second call
        fixed_ts = "2026-08-01T120000"
        monkeypatch.setattr(
            "src.strategy.history.datetime",
            type("dt", (), {
                "now": staticmethod(lambda tz=None: type("dtnow", (), {
                    "strftime": lambda self, fmt: fixed_ts
                })()),
            })()
        )
        # Write archive at the expected collision path first
        (tmp_path / "history" / "strategies").mkdir(parents=True, exist_ok=True)
        collision = tmp_path / "history" / "strategies" / f"{fixed_ts}_2026-08-old.json"
        collision.write_text("{}")
        with pytest.raises(FileExistsError, match="Archive collision"):
            h2.archive_current_strategy()


class TestActivateNewStrategy:
    def test_writes_new_strategy_atomically(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        h.activate_new_strategy(_strategy_json("2026-09-new"))
        current = json.loads((tmp_path / "current" / "strategy.json").read_text())
        assert current["strategy_id"] == "2026-09-new"

    def test_validates_new_strategy_before_writing(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="invalid"):
            h.activate_new_strategy({"strategy_id": "bad", "strategy_name": "Missing required fields"})
        # Current strategy should be unchanged
        current = json.loads((tmp_path / "current" / "strategy.json").read_text())
        assert current["strategy_id"] == "2026-08-old"

    def test_raises_if_new_strategy_missing_id(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="strategy_id"):
            h.activate_new_strategy({"strategy_name": "No ID here"})


class TestRotateStrategy:
    def test_archives_current_and_writes_new(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        archive_path = h.rotate_strategy(_strategy_json("2026-09-new"))
        assert archive_path.exists()
        archived = json.loads(archive_path.read_text())
        assert archived["strategy_id"] == "2026-08-old"
        current = json.loads((tmp_path / "current" / "strategy.json").read_text())
        assert current["strategy_id"] == "2026-09-new"

    def test_raises_if_no_current_strategy(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "CURRENT_STRATEGY_JSON", tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError):
            h.rotate_strategy(_strategy_json("2026-09-new"))

    def test_raises_if_new_strategy_invalid(self, tmp_path, monkeypatch):
        h = _setup_current_strategy(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            h.rotate_strategy({"strategy_id": "bad-only"})
        # Current should be unchanged
        current = json.loads((tmp_path / "current" / "strategy.json").read_text())
        assert current["strategy_id"] == "2026-08-old"


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

def _entry_with_week(content_id: str, strategy_week: int, strategy_id: str = "2026-08-test") -> PublishedEntry:
    return PublishedEntry(
        content_id=content_id,
        strategy_id=strategy_id,
        published_at=datetime(2026, 8, 7 + (strategy_week - 1) * 7, 10, 0, tzinfo=timezone.utc),
        platform="blog",
        strategy_week=strategy_week,
    )


class TestMarkEntriesReviewed:
    def test_marks_entries_with_matching_week(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        h.append_published_entry(_entry_with_week("sig-w1", strategy_week=1))
        h.append_published_entry(_entry_with_week("sig-w2", strategy_week=2))
        h.append_published_entry(_entry_with_week("sig-w3", strategy_week=3))

        count = h.mark_entries_reviewed("2026-08-test", week_number=2)

        assert count == 2  # week 1 and 2 only
        entries = h.load_published_index()
        assert entries[0].reviewed is True   # week 1
        assert entries[1].reviewed is True   # week 2
        assert entries[2].reviewed is False  # week 3 — future, not marked

    def test_marks_legacy_entries_without_strategy_week(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        # Entry without strategy_week (legacy) should always be marked
        legacy = PublishedEntry(
            content_id="sig-legacy",
            strategy_id="2026-08-test",
            published_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            platform="blog",
            strategy_week=None,
        )
        h.append_published_entry(legacy)
        count = h.mark_entries_reviewed("2026-08-test", week_number=1)
        assert count == 1
        assert h.load_published_index()[0].reviewed is True

    def test_skips_already_reviewed_entries(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        h.append_published_entry(_entry_with_week("sig-001", strategy_week=1))
        h.mark_entries_reviewed("2026-08-test", week_number=2)
        count = h.mark_entries_reviewed("2026-08-test", week_number=2)
        assert count == 0

    def test_only_marks_entries_for_given_strategy(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        index_path = tmp_path / "published_content_index.jsonl"
        monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)

        h.append_published_entry(_entry_with_week("sig-001", strategy_week=1, strategy_id="2026-08-test"))
        h.append_published_entry(_entry_with_week("sig-002", strategy_week=1, strategy_id="2026-09-other"))

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


# ── update_entry (Phase 4D.0) ─────────────────────────────────────────────────

class TestUpdateEntry:
    def test_updates_analytics_fields(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")
        h.append_published_entry(_published_entry("sig-001"))

        result = h.update_entry("sig-001", {
            "analytics_score": 0.74,
            "analytics_fetched_at": "2026-08-15T12:00:00+00:00",
            "analytics_version": "v1",
        })

        assert result is True
        data = json.loads((tmp_path / "published_content_index.jsonl").read_text().strip())
        assert data["analytics_score"] == 0.74
        assert data["analytics_version"] == "v1"
        assert data["analytics_fetched_at"] == "2026-08-15T12:00:00+00:00"

    def test_preserves_unpatched_fields(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")
        h.append_published_entry(_published_entry("sig-001"))

        h.update_entry("sig-001", {"analytics_score": 0.5})

        data = json.loads((tmp_path / "published_content_index.jsonl").read_text().strip())
        assert data["content_id"] == "sig-001"
        assert data["strategy_id"] == "2026-08-test"
        assert data["echo"] == "The competitor was just present."

    def test_only_updates_matching_entry(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")
        h.append_published_entry(_published_entry("sig-001"))
        h.append_published_entry(_published_entry("sig-002"))

        h.update_entry("sig-001", {"analytics_score": 0.9})

        lines = [l for l in (tmp_path / "published_content_index.jsonl").read_text().splitlines() if l.strip()]
        data = [json.loads(l) for l in lines]
        sig1 = next(d for d in data if d["content_id"] == "sig-001")
        sig2 = next(d for d in data if d["content_id"] == "sig-002")
        assert sig1["analytics_score"] == 0.9
        assert sig2.get("analytics_score") is None

    def test_returns_false_when_content_id_not_found(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")
        h.append_published_entry(_published_entry("sig-001"))

        result = h.update_entry("nonexistent-id", {"analytics_score": 0.5})
        assert result is False

    def test_returns_false_when_no_index(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "nonexistent.jsonl")
        assert h.update_entry("sig-001", {"analytics_score": 0.5}) is False

    def test_patch_overwrites_existing_analytics(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")
        h.append_published_entry(_published_entry("sig-001"))

        h.update_entry("sig-001", {"analytics_score": 0.3, "analytics_version": "v1"})
        h.update_entry("sig-001", {"analytics_score": 0.6, "analytics_version": "v2"})

        data = json.loads((tmp_path / "published_content_index.jsonl").read_text().strip())
        assert data["analytics_score"] == 0.6
        assert data["analytics_version"] == "v2"

    def test_analytics_fields_round_trip_through_published_entry(self, tmp_path, monkeypatch):
        import src.strategy.history as h
        monkeypatch.setattr(h, "PUBLISHED_INDEX", tmp_path / "published_content_index.jsonl")
        h.append_published_entry(_published_entry("sig-001"))

        from datetime import timezone
        fetched = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        h.update_entry("sig-001", {
            "analytics_score": 0.72,
            "analytics_fetched_at": fetched.isoformat(),
            "analytics_version": "v1",
        })

        entries = h.load_published_index()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.analytics_score == 0.72
        assert entry.analytics_version == "v1"
        assert entry.analytics_fetched_at is not None
