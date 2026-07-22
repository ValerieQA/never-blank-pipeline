"""
Tests for src/analytics/ (Phase 4D.1–4D.4):
  collector_protocol.py — Protocol conformance check
  scorer.py             — score_records(), per-platform weights, None handling
  orchestrator.py       — full pipeline: collect → score → update_entry
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from src.analytics.collector_protocol import AnalyticsCollector
from src.analytics.scorer import SCORER_VERSION, score_records
from src.strategy.models import AnalyticsRecord, PublishedEntry


# ── Helpers ────────────────────────────────────────────────────────────────────

def _entry(
    content_id: str = "2026-08-test-w1-01",
    strategy_id: str = "2026-08-test",
    platform: str = "instagram",
) -> PublishedEntry:
    return PublishedEntry(
        content_id=content_id,
        strategy_id=strategy_id,
        platform=platform,
        published_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )


def _record(
    content_id: str = "2026-08-test-w1-01",
    platform: str = "instagram",
    **metrics,
) -> AnalyticsRecord:
    return AnalyticsRecord(
        content_id=content_id,
        platform=platform,
        collected_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        **metrics,
    )


# ── Collector Protocol ─────────────────────────────────────────────────────────

class TestCollectorProtocol:
    def test_protocol_is_runtime_checkable(self):
        # AnalyticsCollector is @runtime_checkable
        class GoodCollector:
            platform = "instagram"
            def collect(self, entries):
                return []

        assert isinstance(GoodCollector(), AnalyticsCollector)

    def test_missing_collect_method_fails_protocol(self):
        class BadCollector:
            platform = "instagram"
            # no collect()

        assert not isinstance(BadCollector(), AnalyticsCollector)

    def test_missing_platform_fails_protocol(self):
        class BadCollector:
            def collect(self, entries):
                return []

        assert not isinstance(BadCollector(), AnalyticsCollector)

    def test_stub_collector_returns_empty_list(self):
        class StubCollector:
            platform = "instagram"
            def collect(self, entries):
                return []

        collector = StubCollector()
        result = collector.collect([_entry()])
        assert result == []


# ── Scorer ─────────────────────────────────────────────────────────────────────

class TestScorer:
    def test_score_returns_float_in_range(self):
        record = _record(reach=800, saves=40, likes=100, comments=15)
        patches = score_records([record])
        assert len(patches) == 1
        score = patches[0]["analytics_score"]
        assert 0.0 <= score <= 1.0

    def test_score_version_matches_constant(self):
        patches = score_records([_record(reach=800, likes=100)])
        assert patches[0]["analytics_version"] == SCORER_VERSION

    def test_score_includes_fetched_at(self):
        patches = score_records([_record(reach=800)])
        assert "analytics_fetched_at" in patches[0]

    def test_no_scoreable_metrics_excluded_from_output(self):
        # All metrics are None or not_collected — no score possible
        record = _record(reach=None, saves=None, likes="not_collected")
        patches = score_records([record])
        assert patches == []

    def test_zero_metrics_produce_zero_score(self):
        record = _record(reach=0, saves=0, likes=0, comments=0)
        patches = score_records([record])
        assert len(patches) == 1
        assert patches[0]["analytics_score"] == 0.0

    def test_ceiling_caps_score_at_1(self):
        # Extremely high metrics — score should cap at 1.0
        record = _record(reach=999999, saves=999999, likes=999999, comments=999999)
        patches = score_records([record])
        assert patches[0]["analytics_score"] <= 1.0

    def test_mixed_none_and_numeric_uses_available_metrics(self):
        # Some metrics None, some numeric — should still score
        record = _record(reach=None, saves=40, likes=None)
        patches = score_records([record])
        assert len(patches) == 1

    def test_linkedin_uses_different_weights_than_instagram(self):
        # Same absolute numbers; LinkedIn weights comments and link_clicks higher
        ig_record = _record("c1", "instagram", reach=500, comments=20, link_clicks=30)
        li_record = _record("c2", "linkedin", impressions=500, comments=20, link_clicks=30)
        ig_patches = score_records([ig_record])
        li_patches = score_records([li_record])
        # They should differ (different platform ceilings + weights)
        assert ig_patches[0]["analytics_score"] != li_patches[0]["analytics_score"]

    def test_multiple_records_scored_independently(self):
        records = [
            _record("c1", reach=1500, saves=80, likes=200),   # at ceiling
            _record("c2", reach=100,  saves=5,  likes=10),    # below ceiling
        ]
        patches = score_records(records)
        assert len(patches) == 2
        c1 = next(p for p in patches if p["content_id"] == "c1")
        c2 = next(p for p in patches if p["content_id"] == "c2")
        assert c1["analytics_score"] > c2["analytics_score"]

    def test_unknown_platform_uses_default_weights(self):
        record = _record("c1", platform="substack", views=100, likes=20)
        patches = score_records([record])
        # Should not raise; uses _DEFAULT_WEIGHTS
        assert len(patches) == 1

    def test_blog_qualified_leads_heavily_weighted(self):
        # blog: qualified_leads has weight 5.0 — even 1 lead should push score up
        without_leads = _record("c1", "blog", views=100, website_sessions=80)
        with_leads    = _record("c2", "blog", views=100, website_sessions=80, qualified_leads=2)
        p_without = score_records([without_leads])
        p_with    = score_records([with_leads])
        assert p_with[0]["analytics_score"] > p_without[0]["analytics_score"]


# ── Orchestrator ───────────────────────────────────────────────────────────────

class TestOrchestrator:
    def _monkeypatch_history(self, monkeypatch, entries, updates=None):
        if updates is None:
            updates = {}
        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: entries)
        monkeypatch.setattr(
            orch, "update_entry",
            lambda content_id, patch: updates.update({content_id: patch}) or True
        )

    def test_full_pipeline_updates_history(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        class FakeInstagram:
            platform = "instagram"
            def collect(self, entries):
                return [_record(e.content_id, reach=800, saves=40, likes=100)
                        for e in entries if e.platform == "instagram"]

        entries = [_entry("sig-001", platform="instagram")]
        updates = {}
        self._monkeypatch_history(monkeypatch, entries, updates)

        result = run_analytics_pipeline(collectors=[FakeInstagram()])
        assert result.entries_loaded == 1
        assert result.records_fetched == 1
        assert result.records_scored == 1
        assert result.entries_updated == 1
        assert "sig-001" in updates
        assert "analytics_score" in updates["sig-001"]

    def test_dry_run_does_not_call_update_entry(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        class FakeCollector:
            platform = "instagram"
            def collect(self, entries):
                return [_record(e.content_id, reach=800, saves=40) for e in entries]

        update_called = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [_entry()])
        monkeypatch.setattr(orch, "update_entry", lambda cid, patch: update_called.append(cid) or True)

        result = run_analytics_pipeline(collectors=[FakeCollector()], dry_run=True)
        assert update_called == []   # update_entry never called
        assert result.entries_updated == 1  # counted as "would update"

    def test_collector_error_is_non_fatal(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        class BrokenCollector:
            platform = "instagram"
            def collect(self, entries):
                raise RuntimeError("API timeout")

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [_entry()])

        result = run_analytics_pipeline(collectors=[BrokenCollector()])
        assert len(result.collector_errors) == 1
        assert "API timeout" in result.collector_errors[0]
        assert result.records_fetched == 0

    def test_no_entries_returns_early(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        class FakeCollector:
            platform = "instagram"
            def collect(self, entries):
                return []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [])

        result = run_analytics_pipeline(collectors=[FakeCollector()])
        assert result.entries_loaded == 0
        assert result.records_fetched == 0
        assert result.entries_updated == 0

    def test_unscoreable_records_not_written(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        class FakeCollector:
            platform = "instagram"
            def collect(self, entries):
                # Returns records with no numeric metrics
                return [AnalyticsRecord(content_id=entry.content_id, platform="instagram")
                        for entry in entries]

        updates = {}
        self._monkeypatch_history(monkeypatch, [_entry()], updates)

        result = run_analytics_pipeline(collectors=[FakeCollector()])
        assert result.records_fetched == 1
        assert result.records_scored == 0
        assert result.entries_updated == 0
        assert updates == {}

    def test_multiple_collectors_combined(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        class IGCollector:
            platform = "instagram"
            def collect(self, entries):
                return [_record(e.content_id, "instagram", reach=800, saves=40)
                        for e in entries if e.platform == "instagram"]

        class LICollector:
            platform = "linkedin"
            def collect(self, entries):
                return [_record(e.content_id, "linkedin", impressions=2000, comments=20)
                        for e in entries if e.platform == "linkedin"]

        entries = [
            _entry("sig-ig", platform="instagram"),
            _entry("sig-li", platform="linkedin"),
        ]
        updates = {}
        self._monkeypatch_history(monkeypatch, entries, updates)

        result = run_analytics_pipeline(collectors=[IGCollector(), LICollector()])
        assert result.records_fetched == 2
        assert result.entries_updated == 2
        assert "sig-ig" in updates
        assert "sig-li" in updates

    def test_strategy_id_filter_passed_to_load(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline
        loaded_kwargs = {}

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(
            orch, "load_published_index",
            lambda strategy_id=None: (loaded_kwargs.update({"strategy_id": strategy_id}) or [])
        )

        run_analytics_pipeline(collectors=[], strategy_id="2026-08-test")
        assert loaded_kwargs["strategy_id"] == "2026-08-test"
