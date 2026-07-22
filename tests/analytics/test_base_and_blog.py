"""
Tests for src/analytics/base.py and src/analytics/blog.py (hardened).

Covers:
  BaseCollector._fetch_with_retry: success, 429 retry, 5xx retry,
                                   401/403 → AuthorizationCollectorError,
                                   max retries exhausted, JSON error, network error
  BaseCollector._is_stale: None inputs, older/newer/equal timestamps, naive UTC
  BlogCollector.collect: credential check, platform filtering, platform_content_id
                         required, correct API endpoint (/blog/v3/posts/{id}/metrics),
                         auth error propagates (not swallowed), per-entry error is
                         non-fatal, stale skip, metrics normalization, None for
                         Wix-unavailable fields

Orchestrator staleness guard + skipped_no_score double-count fix tested here.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.analytics.base import (
    AuthorizationCollectorError,
    BaseCollector,
    CollectorError,
    EntryCollectorError,
    _RATE_LIMIT_WAIT,
)
from src.analytics.blog import BlogCollector, _METRICS_URL
from src.strategy.models import AnalyticsRecord, PublishedEntry


# ── Helpers ────────────────────────────────────────────────────────────────────

def _entry(
    content_id: str = "sig-001",
    platform: str = "blog",
    platform_content_id: Optional[str] = None,
    analytics_fetched_at: Optional[datetime] = None,
) -> PublishedEntry:
    return PublishedEntry(
        content_id=content_id,
        strategy_id="2026-08-test",
        platform=platform,
        url="https://www.neverblank.co/post/the-dark-month",
        platform_content_id=platform_content_id,
        published_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        analytics_fetched_at=analytics_fetched_at,
    )


def _ts(year=2026, month=8, day=15) -> datetime:
    return datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="", code=code, msg="", hdrs=None, fp=None)


# ── BaseCollector._is_stale ────────────────────────────────────────────────────

class TestIsStale:
    def setup_method(self):
        self.bc = BaseCollector()

    def test_none_data_timestamp_not_stale(self):
        assert not self.bc._is_stale(None, _ts())

    def test_none_existing_not_stale(self):
        assert not self.bc._is_stale(_ts(), None)

    def test_both_none_not_stale(self):
        assert not self.bc._is_stale(None, None)

    def test_incoming_older_than_existing_is_stale(self):
        assert self.bc._is_stale(_ts(day=10), _ts(day=15))

    def test_incoming_newer_than_existing_not_stale(self):
        assert not self.bc._is_stale(_ts(day=15), _ts(day=10))

    def test_equal_timestamps_not_stale(self):
        ts = _ts()
        assert not self.bc._is_stale(ts, ts)

    def test_naive_timestamps_treated_as_utc(self):
        naive_existing = datetime(2026, 8, 15, 12, 0, 0)
        naive_incoming = datetime(2026, 8, 10, 12, 0, 0)
        assert self.bc._is_stale(naive_incoming, naive_existing)


# ── BaseCollector._fetch_with_retry ───────────────────────────────────────────

class TestFetchWithRetry:
    def setup_method(self):
        self.bc = BaseCollector()
        self.bc.platform = "test"

    def _mock_urlopen(self, response_data: dict):
        body = json.dumps(response_data).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_success_returns_parsed_json(self):
        mock_resp = self._mock_urlopen({"views": 100})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = self.bc._fetch_with_retry("https://example.com", {})
        assert result == {"views": 100}

    def test_401_raises_authorization_error(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(AuthorizationCollectorError, match="authorization failed"):
                self.bc._fetch_with_retry("https://example.com", {})

    def test_403_raises_authorization_error(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(403)):
            with pytest.raises(AuthorizationCollectorError, match="authorization failed"):
                self.bc._fetch_with_retry("https://example.com", {})

    def test_401_does_not_retry(self):
        call_count = []
        def track(req, timeout=None):
            call_count.append(1)
            raise _http_error(401)
        with patch("urllib.request.urlopen", side_effect=track):
            with pytest.raises(AuthorizationCollectorError):
                self.bc._fetch_with_retry("https://example.com", {})
        assert len(call_count) == 1   # no retries on auth failure

    def test_404_raises_collector_error_immediately(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(404)):
            with pytest.raises(CollectorError, match="HTTP 404"):
                self.bc._fetch_with_retry("https://example.com", {})

    def test_500_retries_and_raises_after_exhaustion(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
            with patch("time.sleep"):
                with pytest.raises(CollectorError, match="retries exhausted"):
                    self.bc._fetch_with_retry("https://example.com", {})

    def test_429_waits_before_retry(self):
        success_resp = self._mock_urlopen({"ok": True})
        side_effects = [_http_error(429), success_resp]
        sleep_calls = []
        with patch("urllib.request.urlopen", side_effect=side_effects):
            with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
                result = self.bc._fetch_with_retry("https://example.com", {})
        assert result == {"ok": True}
        assert any(s == _RATE_LIMIT_WAIT for s in sleep_calls)

    def test_network_error_retries(self):
        import urllib.error as ue
        url_error = ue.URLError("connection reset")
        success_resp = self._mock_urlopen({"data": 1})
        with patch("urllib.request.urlopen", side_effect=[url_error, success_resp]):
            with patch("time.sleep"):
                result = self.bc._fetch_with_retry("https://example.com", {})
        assert result == {"data": 1}

    def test_invalid_json_raises_collector_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json {"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(CollectorError, match="invalid JSON"):
                self.bc._fetch_with_retry("https://example.com", {})


# ── BlogCollector ─────────────────────────────────────────────────────────────

class TestBlogCollector:
    def _collector(self):
        return BlogCollector(api_key="test-key", site_id="test-site")

    def _wix_metrics(self, views=100, likes=5, comments=2) -> dict:
        return {"metrics": {"views": views, "likes": likes, "comments": comments}}

    def test_missing_credentials_raises(self):
        collector = BlogCollector(api_key="", site_id="")
        with pytest.raises(CollectorError, match="missing required env vars"):
            collector.collect([_entry(platform_content_id="wix-123")])

    def test_filters_to_blog_platform(self):
        collector = self._collector()
        entries = [
            _entry("sig-001", platform="blog", platform_content_id="wix-001"),
            _entry("sig-002", platform="instagram"),
            _entry("sig-003", platform="linkedin"),
        ]
        with patch.object(collector, "_fetch_post_metrics", return_value=self._wix_metrics()):
            records = collector.collect(entries)
        assert len(records) == 1
        assert records[0].content_id == "sig-001"

    def test_uses_correct_api_endpoint(self):
        collector = self._collector()
        post_id = "wix-post-abc123"
        captured_url = []

        def fake_fetch(url, headers=None, timeout=15):
            captured_url.append(url)
            return self._wix_metrics()

        with patch.object(collector, "_fetch_with_retry", side_effect=fake_fetch):
            collector.collect([_entry(platform_content_id=post_id)])

        expected = _METRICS_URL.format(post_id=post_id)
        assert captured_url[0] == expected
        assert "/blog/v3/posts/" in captured_url[0]
        assert "/metrics" in captured_url[0]

    def test_success_returns_analytics_record(self):
        collector = self._collector()
        with patch.object(collector, "_fetch_post_metrics", return_value=self._wix_metrics(250, 18, 7)):
            records = collector.collect([_entry(platform_content_id="wix-123")])
        assert len(records) == 1
        r = records[0]
        assert r.platform == "blog"
        assert r.views == 250
        assert r.likes == 18
        assert r.comments == 7
        assert r.collected_at is not None

    def test_missing_platform_content_id_is_skipped(self):
        collector = self._collector()
        with patch.object(collector, "_fetch_post_metrics") as mock_fetch:
            records = collector.collect([_entry(platform_content_id=None)])
        assert records == []
        mock_fetch.assert_not_called()

    def test_auth_error_propagates_not_swallowed(self):
        """401/403 must bubble up to orchestrator — not silently skipped."""
        collector = self._collector()
        entries = [
            _entry("sig-001", platform_content_id="wix-001"),
            _entry("sig-002", platform_content_id="wix-002"),
        ]
        with patch.object(
            collector, "_fetch_post_metrics",
            side_effect=AuthorizationCollectorError("test: authorization failed (HTTP 401)")
        ):
            with pytest.raises(AuthorizationCollectorError):
                collector.collect(entries)

    def test_per_entry_error_is_non_fatal(self):
        """Network/5xx for one entry should not stop collection of others."""
        collector = self._collector()
        entries = [
            _entry("sig-001", platform_content_id="wix-001"),
            _entry("sig-002", platform_content_id="wix-002"),
        ]

        def fetch_with_error(post_id):
            if post_id == "wix-001":
                raise EntryCollectorError("blog: connection timeout")
            return self._wix_metrics()

        with patch.object(collector, "_fetch_post_metrics", side_effect=fetch_with_error):
            records = collector.collect(entries)

        assert len(records) == 1
        assert records[0].content_id == "sig-002"

    def test_stale_entry_is_skipped(self):
        collector = self._collector()
        yesterday = _ts(day=14)
        entry = _entry(platform_content_id="wix-123", analytics_fetched_at=_ts(day=15))
        with patch.object(collector, "_now", return_value=yesterday):
            with patch.object(collector, "_fetch_post_metrics") as mock_fetch:
                records = collector.collect([entry])
        assert records == []
        mock_fetch.assert_not_called()

    def test_wix_metrics_flat_response_shape(self):
        # Wix may omit the "metrics" wrapper in some response variants
        collector = self._collector()
        flat = {"views": 300, "likes": 20, "comments": 4}
        with patch.object(collector, "_fetch_post_metrics", return_value=flat):
            records = collector.collect([_entry(platform_content_id="wix-123")])
        assert records[0].views == 300

    def test_unavailable_metrics_are_none(self):
        collector = self._collector()
        with patch.object(collector, "_fetch_post_metrics",
                          return_value={"metrics": {"views": 150}}):
            records = collector.collect([_entry(platform_content_id="wix-123")])
        r = records[0]
        assert r.views == 150
        assert r.likes is None
        assert r.comments is None
        assert r.reach is None
        assert r.saves is None
        assert r.leads is None

    def test_no_blog_entries_returns_empty(self):
        collector = self._collector()
        with patch.object(collector, "_fetch_post_metrics") as mock_fetch:
            records = collector.collect([_entry(platform="instagram")])
        assert records == []
        mock_fetch.assert_not_called()


# ── Orchestrator: staleness guard + skipped_no_score fix ─────────────────────

class TestOrchestratorStalenessGuard:
    def test_stale_record_not_written_and_counted(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        stale_collected = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        existing_fetch  = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

        class FakeCollector:
            platform = "blog"
            def collect(self, entries):
                return [AnalyticsRecord(
                    content_id="sig-001", platform="blog",
                    collected_at=stale_collected, views=100,
                )]

        entry = _entry("sig-001", platform_content_id="wix-123",
                       analytics_fetched_at=existing_fetch)
        updates = {}

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(orch, "update_entry",
                            lambda cid, patch: updates.update({cid: patch}) or True)

        result = run_analytics_pipeline(collectors=[FakeCollector()])
        assert result.skipped_stale == 1
        assert updates == {}

    def test_fresh_record_is_written(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline

        fresh_collected = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        existing_fetch  = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

        class FakeCollector:
            platform = "blog"
            def collect(self, entries):
                return [AnalyticsRecord(
                    content_id="sig-001", platform="blog",
                    collected_at=fresh_collected, views=200,
                )]

        entry = _entry("sig-001", platform_content_id="wix-123",
                       analytics_fetched_at=existing_fetch)
        updates = {}

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(orch, "update_entry",
                            lambda cid, patch: updates.update({cid: patch}) or True)

        result = run_analytics_pipeline(collectors=[FakeCollector()])
        assert result.skipped_stale == 0
        assert "sig-001" in updates

    def test_skipped_no_score_does_not_double_count_stale(self, monkeypatch):
        """stale records must not appear in both skipped_stale and skipped_no_score."""
        from src.analytics.orchestrator import run_analytics_pipeline

        stale_collected = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        existing_fetch  = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

        class FakeCollector:
            platform = "blog"
            def collect(self, entries):
                return [AnalyticsRecord(
                    content_id="sig-001", platform="blog",
                    collected_at=stale_collected, views=100,
                )]

        entry = _entry("sig-001", platform_content_id="wix-123",
                       analytics_fetched_at=existing_fetch)
        updates = {}

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(orch, "update_entry",
                            lambda cid, patch: updates.update({cid: patch}) or True)

        result = run_analytics_pipeline(collectors=[FakeCollector()])
        # stale goes into skipped_stale only
        assert result.skipped_stale == 1
        assert result.skipped_no_score == 0   # fresh_records is empty → no "unscoreable" records

    def test_auth_error_recorded_as_collector_error(self, monkeypatch):
        """AuthorizationCollectorError must surface as collector_errors entry, not silently dropped."""
        from src.analytics.orchestrator import run_analytics_pipeline

        class BrokenAuthCollector:
            platform = "blog"
            def collect(self, entries):
                raise AuthorizationCollectorError("blog: authorization failed (HTTP 401)")

        entry = _entry(platform_content_id="wix-123")
        updates = {}

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(orch, "update_entry",
                            lambda cid, patch: updates.update({cid: patch}) or True)

        result = run_analytics_pipeline(collectors=[BrokenAuthCollector()])
        assert len(result.collector_errors) == 1
        assert "authorization" in result.collector_errors[0].lower()
        assert updates == {}
