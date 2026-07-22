"""
Tests for src/analytics/base.py and src/analytics/blog.py.

Covers:
  BaseCollector._fetch_with_retry: success, HTTP 429 retry, HTTP 5xx retry,
                                   auth failure (401/403), max retries exhausted,
                                   JSON decode error, network error
  BaseCollector._is_stale: None inputs, older incoming, newer incoming, equal
  BlogCollector.collect: credential check, platform filtering, URL slug extraction,
                         API success, missing URL skip, stale skip, API error skip,
                         Wix response shape normalization

Orchestrator staleness guard tested here too (integration with entry_index).
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.analytics.base import BaseCollector, CollectorError, _RATE_LIMIT_WAIT
from src.analytics.blog import BlogCollector, _slug_from_url
from src.strategy.models import AnalyticsRecord, PublishedEntry


# ── Helpers ────────────────────────────────────────────────────────────────────

def _entry(
    content_id: str = "sig-001",
    platform: str = "blog",
    url: str = "https://www.neverblank.co/post/the-dark-month",
    analytics_fetched_at: Optional[datetime] = None,
) -> PublishedEntry:
    return PublishedEntry(
        content_id=content_id,
        strategy_id="2026-08-test",
        platform=platform,
        url=url,
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
        existing = _ts(day=15)
        incoming = _ts(day=10)  # older
        assert self.bc._is_stale(incoming, existing)

    def test_incoming_newer_than_existing_not_stale(self):
        existing = _ts(day=10)
        incoming = _ts(day=15)  # newer
        assert not self.bc._is_stale(incoming, existing)

    def test_equal_timestamps_not_stale(self):
        ts = _ts()
        assert not self.bc._is_stale(ts, ts)

    def test_naive_timestamps_treated_as_utc(self):
        # Both naive — should not raise
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

    def test_401_raises_immediately_no_retry(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(CollectorError, match="authorization failed"):
                self.bc._fetch_with_retry("https://example.com", {})

    def test_403_raises_immediately_no_retry(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(403)):
            with pytest.raises(CollectorError, match="authorization failed"):
                self.bc._fetch_with_retry("https://example.com", {})

    def test_404_raises_immediately(self):
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
        side_effects = [url_error, success_resp]

        with patch("urllib.request.urlopen", side_effect=side_effects):
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


# ── _slug_from_url ────────────────────────────────────────────────────────────

class TestSlugFromUrl:
    def test_standard_wix_url(self):
        assert _slug_from_url("https://www.neverblank.co/post/the-dark-month") == "the-dark-month"

    def test_trailing_slash(self):
        assert _slug_from_url("https://www.neverblank.co/post/agency-presence/") == "agency-presence"

    def test_query_string_stripped(self):
        assert _slug_from_url("https://www.neverblank.co/post/busy-season?utm=email") == "busy-season"

    def test_empty_url_returns_none(self):
        assert _slug_from_url("") is None

    def test_root_url_returns_domain(self):
        # Edge case: no slug path — should not crash, returns last segment
        result = _slug_from_url("https://www.neverblank.co")
        assert result == "www.neverblank.co"


# ── BlogCollector ─────────────────────────────────────────────────────────────

class TestBlogCollector:
    def _collector(self, api_key="test-key", site_id="test-site"):
        return BlogCollector(api_key=api_key, site_id=site_id)

    def test_missing_credentials_raises(self):
        collector = BlogCollector(api_key="", site_id="")
        with pytest.raises(CollectorError, match="missing required env vars"):
            collector.collect([_entry()])

    def test_filters_to_blog_platform(self):
        collector = self._collector()
        entries = [
            _entry("sig-001", platform="blog"),
            _entry("sig-002", platform="instagram"),
            _entry("sig-003", platform="linkedin"),
        ]
        fake_stats = {"stats": {"views": 100, "likes": 5, "comments": 2}}

        with patch.object(collector, "_fetch_post_stats", return_value=fake_stats):
            records = collector.collect(entries)

        assert len(records) == 1
        assert records[0].content_id == "sig-001"

    def test_success_returns_analytics_record(self):
        collector = self._collector()
        fake_stats = {"stats": {"views": 250, "likes": 18, "comments": 7}}

        with patch.object(collector, "_fetch_post_stats", return_value=fake_stats):
            records = collector.collect([_entry("sig-001")])

        assert len(records) == 1
        r = records[0]
        assert r.platform == "blog"
        assert r.views == 250
        assert r.likes == 18
        assert r.comments == 7
        assert r.collected_at is not None

    def test_missing_url_is_skipped(self):
        collector = self._collector()
        entry = _entry("sig-001", url="")

        with patch.object(collector, "_fetch_post_stats") as mock_fetch:
            records = collector.collect([entry])

        assert records == []
        mock_fetch.assert_not_called()

    def test_stale_entry_is_skipped(self):
        collector = self._collector()
        # Entry already has analytics from yesterday; collected_at would be now
        yesterday = _ts(day=14)
        entry = _entry("sig-001", analytics_fetched_at=_ts(day=15))

        with patch.object(collector, "_now", return_value=yesterday):
            with patch.object(collector, "_fetch_post_stats") as mock_fetch:
                records = collector.collect([entry])

        assert records == []
        mock_fetch.assert_not_called()

    def test_api_error_per_entry_is_non_fatal(self):
        collector = self._collector()
        entries = [
            _entry("sig-001", url="https://neverblank.co/post/post-a"),
            _entry("sig-002", url="https://neverblank.co/post/post-b"),
        ]
        fake_stats = {"stats": {"views": 100}}

        def fetch_with_error(slug):
            if slug == "post-a":
                raise CollectorError("blog: API timeout")
            return fake_stats

        with patch.object(collector, "_fetch_post_stats", side_effect=fetch_with_error):
            records = collector.collect(entries)

        assert len(records) == 1
        assert records[0].content_id == "sig-002"

    def test_wix_stats_flat_response_shape(self):
        # Wix may return stats at top level rather than nested under "stats"
        collector = self._collector()
        fake_stats = {"views": 300, "likes": 20, "comments": 4}

        with patch.object(collector, "_fetch_post_stats", return_value=fake_stats):
            records = collector.collect([_entry("sig-001")])

        assert records[0].views == 300

    def test_unavailable_metrics_are_none(self):
        collector = self._collector()
        fake_stats = {"stats": {"views": 150}}  # no likes/comments in response

        with patch.object(collector, "_fetch_post_stats", return_value=fake_stats):
            records = collector.collect([_entry("sig-001")])

        r = records[0]
        assert r.views == 150
        assert r.likes is None
        assert r.comments is None
        # Fields not exposed by Wix Blog stats must be None
        assert r.reach is None
        assert r.saves is None
        assert r.leads is None

    def test_no_blog_entries_returns_empty(self):
        collector = self._collector()
        entries = [_entry("sig-001", platform="instagram")]

        with patch.object(collector, "_fetch_post_stats") as mock_fetch:
            records = collector.collect(entries)

        assert records == []
        mock_fetch.assert_not_called()


# ── Orchestrator staleness guard (integration) ────────────────────────────────

class TestOrchestratorStalenessGuard:
    def test_stale_record_not_written(self, monkeypatch):
        from src.analytics.orchestrator import run_analytics_pipeline
        from datetime import timezone

        existing_fetch = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        stale_collected = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

        class FakeCollector:
            platform = "blog"
            def collect(self, entries):
                return [AnalyticsRecord(
                    content_id="sig-001",
                    platform="blog",
                    collected_at=stale_collected,
                    views=100,
                )]

        entry = _entry("sig-001", analytics_fetched_at=existing_fetch)
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
        from datetime import timezone

        existing_fetch = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        fresh_collected = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

        class FakeCollector:
            platform = "blog"
            def collect(self, entries):
                return [AnalyticsRecord(
                    content_id="sig-001",
                    platform="blog",
                    collected_at=fresh_collected,
                    views=200,
                )]

        entry = _entry("sig-001", analytics_fetched_at=existing_fetch)
        updates = {}

        import src.analytics.orchestrator as orch
        monkeypatch.setattr(orch, "load_published_index", lambda strategy_id=None: [entry])
        monkeypatch.setattr(orch, "update_entry",
                            lambda cid, patch: updates.update({cid: patch}) or True)

        result = run_analytics_pipeline(collectors=[FakeCollector()])
        assert result.skipped_stale == 0
        assert "sig-001" in updates
