"""
Tests for LinkedInCollector.

Covers:
  Filtering:
    - entries without linkedin publication are skipped
    - entries with linkedin publication but no external_id are skipped
    - entries with valid external_id are collected

  HTTP / credential handling:
    - missing NB_ZERNIO_API_KEY raises CollectorError before any API call
    - 401 raises AuthorizationCollectorError (propagates, stops collection)
    - 403 raises AuthorizationCollectorError
    - 5xx is retried; after all retries entry is skipped (non-fatal)
    - network error is non-fatal (entry skipped, collection continues)
    - invalid JSON raises CollectorError (propagates)

  Metrics mapping:
    - impressions / reactions / comments / shares / clicks mapped correctly
    - missing metric fields → None (not 0)
    - non-numeric metric values → None

  Staleness:
    - entry whose analytics_fetched_at is newer than collected_at is skipped

  Multi-entry:
    - auth failure stops all remaining entries
    - per-entry failure does not stop remaining entries

  published_at:
    - uses publications["linkedin"].published_at when set
    - falls back to entry.published_at when publications.published_at is None
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import call, patch

import pytest

from src.analytics.base import (
    AuthorizationCollectorError,
    CollectorError,
    EntryCollectorError,
)
from src.analytics.linkedin import LinkedInCollector, _metric
from src.strategy.models import PlatformPublication, PublishedEntry


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _utc(year=2026, month=7, day=1, hour=12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _entry(
    content_id: str = "content-001",
    li_external_id: Optional[str] = "zernio-post-abc",
    li_published_at: Optional[datetime] = None,
    analytics_fetched_at: Optional[datetime] = None,
) -> PublishedEntry:
    publications = {}
    if li_external_id is not None:
        publications["linkedin"] = PlatformPublication(
            platform="linkedin",
            external_id=li_external_id,
            url="https://www.linkedin.com/feed/",
            published_at=li_published_at,
            status="published",
        )
    return PublishedEntry(
        content_id=content_id,
        strategy_id="strat-001",
        published_at=_utc(day=1),
        analytics_fetched_at=analytics_fetched_at,
        publications=publications,
    )


def _analytics_response(
    impressions=1420,
    reactions=38,
    comments=7,
    shares=4,
    clicks=91,
) -> dict:
    return {
        "analytics": {
            "platforms": {
                "linkedin": {
                    "impressions": impressions,
                    "reactions":   reactions,
                    "comments":    comments,
                    "shares":      shares,
                    "clicks":      clicks,
                }
            }
        }
    }


# ── _metric helper ─────────────────────────────────────────────────────────────

class TestMetricHelper:
    def test_numeric_value(self):
        assert _metric(42) == 42

    def test_string_numeric(self):
        assert _metric("100") == 100

    def test_none_returns_none(self):
        assert _metric(None) is None

    def test_non_numeric_string_returns_none(self):
        assert _metric("N/A") is None

    def test_zero(self):
        assert _metric(0) == 0


# ── Filtering ──────────────────────────────────────────────────────────────────

class TestLinkedInCollectorFiltering:
    def test_entry_without_linkedin_publication_skipped(self):
        collector = LinkedInCollector(api_key="test-key")
        entry = PublishedEntry(
            content_id="content-001",
            strategy_id="strat-001",
            published_at=_utc(),
            publications={
                "blog": PlatformPublication(platform="blog", external_id="wix-001"),
            },
        )
        with patch.object(collector, "_fetch_with_retry") as mock_fetch:
            records = collector.collect([entry])
        assert records == []
        mock_fetch.assert_not_called()

    def test_entry_with_no_external_id_skipped(self):
        collector = LinkedInCollector(api_key="test-key")
        entry = _entry(li_external_id=None)
        with patch.object(collector, "_fetch_with_retry") as mock_fetch:
            records = collector.collect([entry])
        assert records == []
        mock_fetch.assert_not_called()

    def test_entry_with_empty_external_id_skipped(self):
        collector = LinkedInCollector(api_key="test-key")
        entry = _entry(li_external_id="")
        with patch.object(collector, "_fetch_with_retry") as mock_fetch:
            records = collector.collect([entry])
        assert records == []
        mock_fetch.assert_not_called()

    def test_entry_with_valid_external_id_is_collected(self):
        collector = LinkedInCollector(api_key="test-key")
        entry = _entry(li_external_id="zernio-post-abc")
        with patch.object(collector, "_fetch_with_retry", return_value=_analytics_response()):
            records = collector.collect([entry])
        assert len(records) == 1
        assert records[0].content_id == "content-001"


# ── Credential handling ────────────────────────────────────────────────────────

class TestLinkedInCollectorCredentials:
    def test_missing_api_key_raises_collector_error(self, monkeypatch):
        monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
        collector = LinkedInCollector(api_key="")
        with pytest.raises(CollectorError, match="NB_ZERNIO_API_KEY"):
            collector.collect([_entry()])

    def test_missing_api_key_does_not_make_api_calls(self, monkeypatch):
        monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
        collector = LinkedInCollector(api_key="")
        with patch.object(collector, "_fetch_with_retry") as mock_fetch:
            with pytest.raises(CollectorError):
                collector.collect([_entry()])
        mock_fetch.assert_not_called()

    def test_auth_header_uses_bearer_scheme(self):
        collector = LinkedInCollector(api_key="my-key")
        assert collector._headers() == {"Authorization": "Bearer my-key"}


# ── HTTP error handling ────────────────────────────────────────────────────────

class TestLinkedInCollectorHttpErrors:
    def test_401_raises_authorization_error(self):
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(
            collector, "_fetch_with_retry",
            side_effect=AuthorizationCollectorError("linkedin: authorization failed (HTTP 401)")
        ):
            with pytest.raises(AuthorizationCollectorError):
                collector.collect([_entry()])

    def test_403_raises_authorization_error(self):
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(
            collector, "_fetch_with_retry",
            side_effect=AuthorizationCollectorError("linkedin: authorization failed (HTTP 403)")
        ):
            with pytest.raises(AuthorizationCollectorError):
                collector.collect([_entry()])

    def test_5xx_after_retries_skips_entry_non_fatal(self):
        collector = LinkedInCollector(api_key="test-key")
        entry1 = _entry(content_id="c1", li_external_id="post-1")
        entry2 = _entry(content_id="c2", li_external_id="post-2")

        def fake_fetch(url, headers=None):
            if "post-1" in url:
                raise EntryCollectorError("linkedin: all 3 retries exhausted")
            return _analytics_response()

        with patch.object(collector, "_fetch_with_retry", side_effect=fake_fetch):
            records = collector.collect([entry1, entry2])

        assert len(records) == 1
        assert records[0].content_id == "c2"

    def test_network_error_skips_entry_non_fatal(self):
        collector = LinkedInCollector(api_key="test-key")
        entry1 = _entry(content_id="c1", li_external_id="post-1")
        entry2 = _entry(content_id="c2", li_external_id="post-2")

        call_count = 0
        def fake_fetch(url, headers=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise EntryCollectorError("network error")
            return _analytics_response()

        with patch.object(collector, "_fetch_with_retry", side_effect=fake_fetch):
            records = collector.collect([entry1, entry2])

        assert len(records) == 1
        assert records[0].content_id == "c2"

    def test_auth_error_stops_all_remaining_entries(self):
        collector = LinkedInCollector(api_key="test-key")
        entries = [_entry(content_id=f"c{i}", li_external_id=f"post-{i}") for i in range(3)]
        with patch.object(
            collector, "_fetch_with_retry",
            side_effect=AuthorizationCollectorError("401")
        ):
            with pytest.raises(AuthorizationCollectorError):
                collector.collect(entries)

    def test_invalid_json_skips_entry_non_fatal(self):
        """Invalid JSON from one post skips that entry; other entries still collected."""
        collector = LinkedInCollector(api_key="test-key")
        entry1 = _entry(content_id="c1", li_external_id="post-1")
        entry2 = _entry(content_id="c2", li_external_id="post-2")

        call_count = 0
        def fake_fetch(url, headers=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CollectorError("linkedin: invalid JSON response from API")
            return _analytics_response()

        with patch.object(collector, "_fetch_with_retry", side_effect=fake_fetch):
            records = collector.collect([entry1, entry2])

        assert len(records) == 1
        assert records[0].content_id == "c2"


# ── Metrics mapping ────────────────────────────────────────────────────────────

class TestLinkedInCollectorMetrics:
    def test_all_metrics_mapped_correctly(self):
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response(
                              impressions=1420, reactions=38,
                              comments=7, shares=4, clicks=91,
                          )):
            records = collector.collect([_entry()])

        r = records[0]
        assert r.impressions  == 1420
        assert r.likes        == 38    # reactions → likes
        assert r.comments     == 7
        assert r.shares       == 4
        assert r.link_clicks  == 91

    def test_missing_fields_become_none(self):
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value={"analytics": {"platforms": {"linkedin": {}}}}):
            records = collector.collect([_entry()])

        r = records[0]
        assert r.impressions is None
        assert r.likes       is None
        assert r.comments    is None

    def test_non_numeric_metrics_become_none(self):
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response(impressions="N/A", reactions=None)):
            records = collector.collect([_entry()])

        r = records[0]
        assert r.impressions is None
        assert r.likes is None

    def test_unavailable_metrics_are_none(self):
        """Metrics not exposed by Zernio LinkedIn analytics must be None, not 0."""
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect([_entry()])

        r = records[0]
        assert r.reach           is None
        assert r.views           is None
        assert r.saves           is None
        assert r.profile_visits  is None
        assert r.website_sessions is None
        assert r.leads           is None

    def test_platform_field_is_linkedin(self):
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect([_entry()])
        assert records[0].platform == "linkedin"

    def test_content_id_matches_entry(self):
        collector = LinkedInCollector(api_key="test-key")
        entry = _entry(content_id="my-signal-42")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect([entry])
        assert records[0].content_id == "my-signal-42"


# ── Staleness ──────────────────────────────────────────────────────────────────

class TestLinkedInCollectorStaleness:
    def test_stale_entry_skipped(self):
        """Entry whose analytics_fetched_at is in the future is skipped."""
        collector = LinkedInCollector(api_key="test-key")
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        entry = _entry(analytics_fetched_at=future)
        with patch.object(collector, "_fetch_with_retry") as mock_fetch:
            records = collector.collect([entry])
        assert records == []
        mock_fetch.assert_not_called()

    def test_non_stale_entry_collected(self):
        """Entry with no analytics_fetched_at is never considered stale."""
        collector = LinkedInCollector(api_key="test-key")
        entry = _entry(analytics_fetched_at=None)
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect([entry])
        assert len(records) == 1


# ── published_at resolution ────────────────────────────────────────────────────

class TestLinkedInCollectorPublishedAt:
    def test_uses_linkedin_publication_published_at_when_set(self):
        li_pub_dt = _utc(day=15, hour=9)
        entry = _entry(li_published_at=li_pub_dt)
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect([entry])
        assert records[0].published_at == li_pub_dt

    def test_falls_back_to_entry_published_at_when_publication_has_none(self):
        entry_pub = _utc(day=1)
        entry = _entry(li_published_at=None)   # publication.published_at is None
        collector = LinkedInCollector(api_key="test-key")
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect([entry])
        assert records[0].published_at == entry_pub


# ── Multi-entry batch ──────────────────────────────────────────────────────────

class TestLinkedInCollectorBatch:
    def test_collects_all_valid_entries(self):
        collector = LinkedInCollector(api_key="test-key")
        entries = [
            _entry(content_id="c1", li_external_id="post-1"),
            _entry(content_id="c2", li_external_id="post-2"),
            _entry(content_id="c3", li_external_id="post-3"),
        ]
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect(entries)
        assert len(records) == 3
        assert {r.content_id for r in records} == {"c1", "c2", "c3"}

    def test_mixes_valid_and_invalid_entries(self):
        """Invalid entries (no linkedin pub) are filtered; valid ones collected."""
        collector = LinkedInCollector(api_key="test-key")
        valid   = _entry(content_id="valid",   li_external_id="post-v")
        no_pub  = _entry(content_id="no-pub",  li_external_id=None)
        entries = [valid, no_pub]
        with patch.object(collector, "_fetch_with_retry",
                          return_value=_analytics_response()):
            records = collector.collect(entries)
        assert len(records) == 1
        assert records[0].content_id == "valid"

    def test_correct_url_used_per_entry(self):
        """Each entry's own post_id is used in the API call."""
        collector = LinkedInCollector(api_key="test-key")
        entries = [
            _entry(content_id="c1", li_external_id="post-111"),
            _entry(content_id="c2", li_external_id="post-222"),
        ]
        called_urls = []

        def fake_fetch(url, headers=None):
            called_urls.append(url)
            return _analytics_response()

        with patch.object(collector, "_fetch_with_retry", side_effect=fake_fetch):
            collector.collect(entries)

        assert any("post-111" in u for u in called_urls)
        assert any("post-222" in u for u in called_urls)
