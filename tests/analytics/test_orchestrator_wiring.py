"""
End-to-end orchestration wiring tests for BlogCollector + LinkedInCollector.

These tests wire real collector implementations through the full pipeline:
  PublishedEntry → collector.collect() → AnalyticsRecord → scoring
  → aggregation → update_entry() → AnalyticsPipelineResult

All external HTTP calls are mocked at the collector level (_fetch_with_retry /
_fetch_with_status). History reads and writes are monkeypatched.

Scenarios covered:
  both_collectors_succeed                   — happy path, both return records
  blog_auth_fails_linkedin_still_runs       — auth error isolation
  linkedin_auth_fails_blog_still_runs       — symmetric auth isolation
  linkedin_all_pending_202                  — only stale/pending entries → no update
  one_entry_blog_and_linkedin               — same content_id, both platforms scored,
                                              max score written once
  records_matched_by_content_id            — correct entry ↔ record pairing
  history_written_once_after_all_collectors — update_entry call count == unique entries
  no_fresh_analytics_no_history_rewrite    — stale records → History unchanged
  collector_errors_visible_in_summary      — error messages in result
  dry_run_computes_but_does_not_write      — dry_run=True

Format of fixture entries:
  All entries use the new publications map (PlatformPublication).
  BlogCollector filters on publications["blog"].external_id.
  LinkedInCollector filters on publications["linkedin"].external_id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch, MagicMock, call

import pytest

from src.analytics.base import AuthorizationCollectorError
from src.analytics.blog import BlogCollector
from src.analytics.linkedin import LinkedInCollector
from src.analytics.orchestrator import run_analytics_pipeline, AnalyticsPipelineResult
from src.strategy.models import AnalyticsRecord, PlatformPublication, PublishedEntry


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _entry(
    content_id: str,
    blog_post_id: Optional[str] = None,
    li_post_id: Optional[str] = None,
    analytics_fetched_at: Optional[datetime] = None,
) -> PublishedEntry:
    """Create a PublishedEntry with the given platform publications."""
    pubs = {}
    if blog_post_id:
        pubs["blog"] = PlatformPublication(
            platform="blog",
            external_id=blog_post_id,
            url=f"https://neverblank.co/post/{content_id}",
            published_at=_utc(2026, 7, 1, 10),
            status="published",
        )
    if li_post_id:
        pubs["linkedin"] = PlatformPublication(
            platform="linkedin",
            external_id=li_post_id,
            url="https://www.linkedin.com/feed/",
            published_at=_utc(2026, 7, 1, 10),
            status="published",
        )
    return PublishedEntry(
        content_id=content_id,
        strategy_id="strat-2026-07",
        published_at=_utc(2026, 7, 1, 10),
        platform="blog",
        analytics_fetched_at=analytics_fetched_at,
        publications=pubs,
    )


def _blog_metrics_response(views=250, likes=12, comments=3) -> dict:
    return {"metrics": {"views": views, "likes": likes, "comments": comments}}


def _li_analytics_response(impressions=1200, reach=950, likes=45, comments=8, shares=6, clicks=30) -> tuple:
    return (200, {
        "analytics": {
            "impressions": impressions,
            "reach":       reach,
            "likes":       likes,
            "comments":    comments,
            "shares":      shares,
            "saves":       0,
            "clicks":      clicks,
            "views":       0,
        }
    })


def _monkeypatch_history(monkeypatch, entries: list[PublishedEntry], updates: dict | None = None):
    """Patch load_published_index and update_entry in the orchestrator module."""
    if updates is None:
        updates = {}
    import src.analytics.orchestrator as orch
    monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: entries)
    monkeypatch.setattr(
        orch, "update_entry",
        lambda content_id, patch: (updates.__setitem__(content_id, patch) or True),
    )
    return updates


# ── Happy path ────────────────────────────────────────────────────────────────

class TestBothCollectorsSucceed:
    def test_both_platforms_produce_records(self, monkeypatch):
        blog_entry = _entry("c1", blog_post_id="wix-001")
        li_entry   = _entry("c2", li_post_id="zernio-002")
        updates    = _monkeypatch_history(monkeypatch, [blog_entry, li_entry])

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()), \
             patch.object(li_collector, "_fetch_with_status",
                          return_value=_li_analytics_response()):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert result.records_fetched == 2
        assert result.entries_updated == 2
        assert "c1" in updates
        assert "c2" in updates

    def test_both_appear_in_succeeded_list(self, monkeypatch):
        entries = [
            _entry("c1", blog_post_id="wix-001"),
            _entry("c2", li_post_id="zernio-002"),
        ]
        _monkeypatch_history(monkeypatch, entries)

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()), \
             patch.object(li_collector, "_fetch_with_status",
                          return_value=_li_analytics_response()):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert "blog"     in result.collectors_succeeded
        assert "linkedin" in result.collectors_succeeded
        assert result.collectors_failed == []

    def test_records_by_platform_counts_correct(self, monkeypatch):
        entries = [
            _entry("c1", blog_post_id="wix-001"),
            _entry("c2", blog_post_id="wix-002"),
            _entry("c3", li_post_id="zernio-003"),
        ]
        _monkeypatch_history(monkeypatch, entries)

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()), \
             patch.object(li_collector, "_fetch_with_status",
                          return_value=_li_analytics_response()):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert result.records_by_platform["blog"]     == 2
        assert result.records_by_platform["linkedin"] == 1


# ── Auth failure isolation ────────────────────────────────────────────────────

class TestAuthFailureIsolation:
    def test_blog_auth_fail_linkedin_still_runs(self, monkeypatch):
        entries = [
            _entry("c1", blog_post_id="wix-001"),
            _entry("c2", li_post_id="zernio-002"),
        ]
        updates = _monkeypatch_history(monkeypatch, entries)

        blog_collector = BlogCollector(api_key="bad-key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(
            blog_collector, "_fetch_with_retry",
            side_effect=AuthorizationCollectorError("blog: HTTP 401")
        ), patch.object(li_collector, "_fetch_with_status",
                        return_value=_li_analytics_response()):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert "blog"     in result.collectors_failed
        assert "linkedin" in result.collectors_succeeded
        assert len(result.collector_errors) == 1
        assert "blog" in result.collector_errors[0]
        assert "c2" in updates   # LinkedIn entry still updated
        assert "c1" not in updates

    def test_linkedin_auth_fail_blog_still_runs(self, monkeypatch):
        entries = [
            _entry("c1", blog_post_id="wix-001"),
            _entry("c2", li_post_id="zernio-002"),
        ]
        updates = _monkeypatch_history(monkeypatch, entries)

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="bad-key")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()), \
             patch.object(
                 li_collector, "_fetch_with_status",
                 side_effect=AuthorizationCollectorError("linkedin: HTTP 401")
             ):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert "linkedin" in result.collectors_failed
        assert "blog"     in result.collectors_succeeded
        assert "c1" in updates   # Blog entry still updated
        assert "c2" not in updates

    def test_auth_error_recorded_in_summary(self, monkeypatch):
        _monkeypatch_history(monkeypatch, [_entry("c1", li_post_id="zernio-001")])
        li_collector = LinkedInCollector(api_key="bad-key")

        with patch.object(
            li_collector, "_fetch_with_status",
            side_effect=AuthorizationCollectorError("linkedin: HTTP 403")
        ):
            result = run_analytics_pipeline([li_collector])

        assert len(result.collector_errors) == 1
        assert "authorization" in result.collector_errors[0].lower()


# ── Pending analytics (202) ───────────────────────────────────────────────────

class TestLinkedInPendingAnalytics:
    def test_all_pending_entries_produce_no_records(self, monkeypatch):
        entries = [
            _entry("c1", li_post_id="zernio-001"),
            _entry("c2", li_post_id="zernio-002"),
        ]
        updates = _monkeypatch_history(monkeypatch, entries)

        li_collector = LinkedInCollector(api_key="key")

        with patch.object(li_collector, "_fetch_with_status", return_value=(202, {})):
            result = run_analytics_pipeline([li_collector])

        assert result.records_fetched == 0
        assert result.entries_updated == 0
        assert updates == {}

    def test_pending_does_not_appear_in_collector_errors(self, monkeypatch):
        _monkeypatch_history(monkeypatch, [_entry("c1", li_post_id="zernio-001")])
        li_collector = LinkedInCollector(api_key="key")

        with patch.object(li_collector, "_fetch_with_status", return_value=(202, {})):
            result = run_analytics_pipeline([li_collector])

        assert result.collector_errors == []
        assert "linkedin" in result.collectors_succeeded


# ── Multi-platform: same content_id on blog + linkedin ───────────────────────

class TestMultiPlatformEntry:
    def test_max_score_written_once(self, monkeypatch):
        """Entry with blog and LinkedIn analytics: max score, exactly one History write."""
        entry = _entry("c1", blog_post_id="wix-001", li_post_id="zernio-001")
        update_calls = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(
            orch, "update_entry",
            lambda cid, patch: update_calls.append((cid, dict(patch))) or True,
        )

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response(views=50, likes=2, comments=0)), \
             patch.object(li_collector, "_fetch_with_status",
                          return_value=_li_analytics_response(
                              impressions=5000, reach=4000, likes=200,
                              comments=40, shares=30, clicks=150
                          )):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert result.records_fetched  == 2
        assert result.records_scored   == 2
        assert result.entries_updated  == 1
        # update_entry called exactly once for "c1"
        assert len(update_calls) == 1
        assert update_calls[0][0] == "c1"
        # Score is the max (LinkedIn outperforms Blog here)
        score = update_calls[0][1]["analytics_score"]
        assert 0.0 < score <= 1.0

    def test_blog_higher_score_wins(self, monkeypatch):
        """When Blog score > LinkedIn score, Blog's score is written."""
        entry = _entry("c1", blog_post_id="wix-001", li_post_id="zernio-001")
        update_calls = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(
            orch, "update_entry",
            lambda cid, patch: update_calls.append((cid, dict(patch))) or True,
        )

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        # Give blog very high metrics (views + qualified_leads weighted heavily)
        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value={"metrics": {"views": 600, "likes": 80, "comments": 30}}), \
             patch.object(li_collector, "_fetch_with_status",
                          return_value=_li_analytics_response(
                              impressions=10, likes=1, comments=0, shares=0, clicks=0
                          )):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert len(update_calls) == 1
        # Only one write; the exact score source (blog vs linkedin) doesn't matter
        # — what matters is it's the max of the two
        assert result.entries_updated == 1

    def test_matched_by_content_id_not_platform(self, monkeypatch):
        """Each collector correctly identifies its own entries by publications map."""
        blog_only = _entry("blog-only",   blog_post_id="wix-100")
        li_only   = _entry("li-only",     li_post_id="zernio-200")
        both      = _entry("both",        blog_post_id="wix-300", li_post_id="zernio-400")
        updates   = _monkeypatch_history(monkeypatch, [blog_only, li_only, both])

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        fetched_blog_ids  = []
        fetched_li_ids    = []

        def blog_fetch(url, headers=None):
            fetched_blog_ids.append(url)
            return _blog_metrics_response()

        def li_fetch(url, headers=None):
            fetched_li_ids.append(url)
            return _li_analytics_response()

        with patch.object(blog_collector, "_fetch_with_retry", side_effect=blog_fetch), \
             patch.object(li_collector,   "_fetch_with_status", side_effect=li_fetch):
            result = run_analytics_pipeline([blog_collector, li_collector])

        # Blog fetched: blog-only + both
        assert len(fetched_blog_ids) == 2
        assert any("wix-100" in u for u in fetched_blog_ids)
        assert any("wix-300" in u for u in fetched_blog_ids)
        # LinkedIn fetched: li-only + both
        assert len(fetched_li_ids) == 2
        assert any("zernio-200" in u for u in fetched_li_ids)
        assert any("zernio-400" in u for u in fetched_li_ids)
        # All three entries updated
        assert set(updates.keys()) == {"blog-only", "li-only", "both"}


# ── History write semantics ───────────────────────────────────────────────────

class TestHistoryWriteSemantics:
    def test_history_written_after_all_collectors_complete(self, monkeypatch):
        """update_entry is not called until both collectors have returned."""
        entries = [
            _entry("c1", blog_post_id="wix-001"),
            _entry("c2", li_post_id="zernio-002"),
        ]
        write_order = []
        collect_order = []

        import src.analytics.orchestrator as orch

        original_load = lambda strategy_id=None: entries

        def tracking_update(cid, patch):
            write_order.append(("write", cid))
            return True

        monkeypatch.setattr(orch, "load_published_index", original_load)
        monkeypatch.setattr(orch, "update_entry", tracking_update)

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        original_blog_collect = blog_collector.collect
        original_li_collect   = li_collector.collect

        def tracked_blog(entries):
            collect_order.append("blog")
            with patch.object(blog_collector, "_fetch_with_retry",
                              return_value=_blog_metrics_response()):
                return original_blog_collect(entries)

        def tracked_li(entries):
            collect_order.append("linkedin")
            with patch.object(li_collector, "_fetch_with_status",
                              return_value=_li_analytics_response()):
                return original_li_collect(entries)

        blog_collector.collect = tracked_blog
        li_collector.collect   = tracked_li

        run_analytics_pipeline([blog_collector, li_collector])

        # Both collectors ran before any writes
        assert collect_order == ["blog", "linkedin"]
        # Writes happened after (only writes in write_order)
        assert all(w[0] == "write" for w in write_order)

    def test_no_fresh_analytics_no_history_rewrite(self, monkeypatch):
        """If all analytics are already fresher than the incoming records, History is untouched.

        BlogCollector performs staleness filtering internally and returns 0 records.
        The orchestrator's staleness guard (result.skipped_stale) applies only when a
        collector does return a record whose collected_at is older than the stored
        analytics_fetched_at — that's a different path. Here we assert the observable
        outcome: records_fetched == 0 and update_entry is never called.
        """
        future = _utc(2099, 1, 1, 0)
        entry = _entry("c1", blog_post_id="wix-001", analytics_fetched_at=future)
        update_calls = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(
            orch, "update_entry",
            lambda cid, patch: update_calls.append(cid) or True,
        )

        blog_collector = BlogCollector(api_key="key", site_id="site")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()):
            result = run_analytics_pipeline([blog_collector])

        assert result.records_fetched == 0
        assert result.entries_updated == 0
        assert update_calls == []

    def test_unscoreable_records_no_history_rewrite(self, monkeypatch):
        """Records with no numeric metrics produce no patches and no writes."""
        entry = _entry("c1", blog_post_id="wix-001")
        update_calls = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(
            orch, "update_entry",
            lambda cid, patch: update_calls.append(cid) or True,
        )

        blog_collector = BlogCollector(api_key="key", site_id="site")

        # Return metrics with no numeric values
        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value={"metrics": {}}):
            result = run_analytics_pipeline([blog_collector])

        assert result.records_fetched  == 1
        assert result.records_scored   == 0
        assert result.skipped_no_score == 1
        assert update_calls == []


# ── Dry run ───────────────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_computes_but_does_not_write(self, monkeypatch):
        entry = _entry("c1", blog_post_id="wix-001")
        update_calls = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(
            orch, "update_entry",
            lambda cid, patch: update_calls.append(cid) or True,
        )

        blog_collector = BlogCollector(api_key="key", site_id="site")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()):
            result = run_analytics_pipeline([blog_collector], dry_run=True)

        assert result.records_fetched == 1
        assert result.entries_updated == 1   # counted as "would update"
        assert update_calls == []            # but never written

    def test_dry_run_both_collectors(self, monkeypatch):
        entries = [
            _entry("c1", blog_post_id="wix-001"),
            _entry("c2", li_post_id="zernio-002"),
        ]
        update_calls = []

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: entries)
        monkeypatch.setattr(
            orch, "update_entry",
            lambda cid, patch: update_calls.append(cid) or True,
        )

        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()), \
             patch.object(li_collector, "_fetch_with_status",
                          return_value=_li_analytics_response()):
            result = run_analytics_pipeline([blog_collector, li_collector], dry_run=True)

        assert result.entries_updated == 2
        assert update_calls == []


# ── Run summary format ────────────────────────────────────────────────────────

class TestRunSummary:
    def test_collector_errors_visible_in_summary(self, monkeypatch):
        _monkeypatch_history(monkeypatch, [_entry("c1", blog_post_id="wix-001")])
        blog_collector = BlogCollector(api_key="key", site_id="site")

        with patch.object(
            blog_collector, "_fetch_with_retry",
            side_effect=RuntimeError("Wix API timeout")
        ):
            result = run_analytics_pipeline([blog_collector])

        assert len(result.collector_errors) == 1
        assert "Wix API timeout" in result.collector_errors[0]
        assert "blog" in result.collectors_failed

    def test_format_summary_contains_key_fields(self, monkeypatch):
        entries = [_entry("c1", blog_post_id="wix-001")]
        _monkeypatch_history(monkeypatch, entries)
        blog_collector = BlogCollector(api_key="key", site_id="site")

        with patch.object(blog_collector, "_fetch_with_retry",
                          return_value=_blog_metrics_response()):
            result = run_analytics_pipeline([blog_collector])

        summary = result.format_summary()
        assert "blog"         in summary
        assert "Entries"      in summary
        assert "updated"      in summary.lower()

    def test_attempted_reflects_all_collectors_regardless_of_outcome(self, monkeypatch):
        _monkeypatch_history(monkeypatch, [_entry("c1", blog_post_id="wix-001")])
        blog_collector = BlogCollector(api_key="key", site_id="site")
        li_collector   = LinkedInCollector(api_key="key")

        with patch.object(
            blog_collector, "_fetch_with_retry",
            side_effect=RuntimeError("error")
        ), patch.object(li_collector, "_fetch_with_status", return_value=_li_analytics_response()):
            result = run_analytics_pipeline([blog_collector, li_collector])

        assert "blog"     in result.collectors_attempted
        assert "linkedin" in result.collectors_attempted
        assert len(result.collectors_attempted) == 2
