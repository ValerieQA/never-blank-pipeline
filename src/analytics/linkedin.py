"""
Never Blank Analytics — LinkedIn Collector (Phase 4D.2).

Fetches post metrics via the Zernio unified social API — the same service
used by LinkedInPublisher to post. Direct LinkedIn REST API access requires
the Community Management API product (restricted to registered legal entities),
so Zernio remains the single auth boundary for both posting and analytics.

Analytics endpoint (Zernio docs: https://docs.zernio.com/analytics/get-analytics):
  GET https://zernio.com/v1/analytics?postId={urlencoded_post_id}

Zernio resolves both its internal post ID and external platform post IDs
automatically, so publications["linkedin"].external_id (the Zernio _id stored
at publish time) is used without modification.

Response shape:
  {
    "postId": "...",
    "analytics": {
      "impressions": 15420,
      "reach":       12350,
      "likes":       342,
      "comments":    28,
      "shares":      45,
      "saves":       0,
      "clicks":      189,
      "views":       0
    },
    "platformAnalytics": [...]
  }

Special HTTP status codes (per Zernio docs):
  202 → analytics sync pending: skip entry, will be available on next run
  402 → analytics add-on not enabled: collector-level configuration failure
  424 → platform analytics failed for this post: per-entry failure, skip

Standard:
  401/403 → AuthorizationCollectorError (propagates, stops the whole collector)
  5xx     → retried with backoff; per-entry failure after exhaustion
  429     → rate limit; waits _RATE_LIMIT_WAIT seconds before retry

Env vars required:
  NB_ZERNIO_API_KEY — same key as LinkedInPublisher
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Optional

from src.analytics.base import (
    AuthorizationCollectorError,
    BaseCollector,
    CollectorError,
    EntryCollectorError,
)
from src.strategy.models import AnalyticsRecord, PublishedEntry
from src.utils.logger import get_logger

log = get_logger("analytics.linkedin")

_ANALYTICS_URL = "https://zernio.com/v1/analytics"

# Zernio HTTP status codes requiring special handling
_STATUS_PENDING    = 202   # analytics sync in progress — skip, retry next run
_STATUS_ADDON      = 402   # analytics add-on not enabled — collector-level config error
_STATUS_FAILED     = 424   # platform analytics failed for this post — per-entry skip


class LinkedInCollector(BaseCollector):
    """
    Fetches LinkedIn engagement metrics via the Zernio analytics API.

    Reads the Zernio post ID from entry.publications["linkedin"].external_id
    (populated by LinkedInPublisher at publish time).

    Maps Zernio response fields directly:
      impressions → impressions
      reach       → reach
      likes       → likes
      comments    → comments
      shares      → shares
      saves       → saves
      clicks      → link_clicks
      views       → views
    """

    platform = "linkedin"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("NB_ZERNIO_API_KEY", "")

    def _check_credentials(self) -> None:
        if not self._api_key:
            raise CollectorError("linkedin: NB_ZERNIO_API_KEY is not set")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _fetch_post_analytics(self, post_id: str) -> Optional[dict]:
        """
        Fetch analytics for one Zernio post.

        Returns:
          dict  — analytics data (HTTP 200)
          None  — analytics pending (HTTP 202); caller should skip this entry

        Raises:
          CollectorError             — HTTP 402 (add-on required); collector-level
          EntryCollectorError        — HTTP 424 or other per-entry failure
          AuthorizationCollectorError — HTTP 401/403; propagates to stop the collector
        """
        url = _ANALYTICS_URL + "?" + urllib.parse.urlencode({"postId": post_id})
        try:
            code, data = self._fetch_with_status(url, headers=self._headers())
        except AuthorizationCollectorError:
            raise
        except CollectorError as exc:
            # _fetch_with_status raises CollectorError for non-retried 4xx.
            # Detect 402 by message so we can propagate it as collector-level.
            if f"HTTP {_STATUS_ADDON}" in str(exc):
                raise CollectorError(
                    "linkedin: Zernio analytics add-on is not enabled for this account "
                    "(HTTP 402) — enable it in the Zernio dashboard"
                ) from exc
            raise EntryCollectorError(str(exc)) from exc

        if code == _STATUS_PENDING:
            return None  # analytics sync still in progress

        if code == _STATUS_FAILED:
            raise EntryCollectorError(
                f"linkedin: platform analytics failed for post {post_id!r} (HTTP 424)"
            )

        if code != 200:
            raise EntryCollectorError(
                f"linkedin: unexpected HTTP {code} from Zernio analytics"
            )

        return data

    def collect(self, entries: list[PublishedEntry]) -> list[AnalyticsRecord]:
        """
        Collect LinkedIn analytics for all entries with a LinkedIn publication.

        Args:
            entries: full published index (unfiltered).

        Returns:
            list[AnalyticsRecord]: one record per successfully fetched post.

        Raises:
            CollectorError: if NB_ZERNIO_API_KEY is missing or Zernio returns 402.
            AuthorizationCollectorError: on 401/403 from Zernio.
        """
        self._check_credentials()

        li_entries = [
            e for e in entries
            if "linkedin" in e.publications and e.publications["linkedin"].external_id
        ]
        if not li_entries:
            log.info("linkedin: no entries with a Zernio post ID — nothing to collect")
            return []

        records: list[AnalyticsRecord] = []
        collected_at = self._now()

        for entry in li_entries:
            post_id = entry.publications["linkedin"].external_id

            if self._is_stale(collected_at, entry.analytics_fetched_at):
                log.info(
                    "linkedin: entry %s already has fresher analytics (%s) — skipping",
                    entry.content_id, entry.analytics_fetched_at,
                )
                continue

            try:
                raw = self._fetch_post_analytics(post_id)
            except AuthorizationCollectorError:
                raise
            except EntryCollectorError as exc:
                # Per-entry failure (424, network, 5xx exhausted, bad JSON).
                # Must be caught before CollectorError (it's a subclass).
                log.warning(
                    "linkedin: failed to fetch analytics for %s (post_id=%s): %s",
                    entry.content_id, post_id, exc,
                )
                continue
            except CollectorError:
                raise   # 402 add-on error — collector-level, stop processing

            if raw is None:
                log.info(
                    "linkedin: analytics pending for %s (post_id=%s) — will retry on next run",
                    entry.content_id, post_id,
                )
                continue

            analytics = raw.get("analytics", {})
            record = AnalyticsRecord(
                content_id=entry.content_id,
                platform="linkedin",
                published_at=entry.publications["linkedin"].published_at or entry.published_at,
                collected_at=collected_at,
                impressions=_metric(analytics.get("impressions")),
                reach=_metric(analytics.get("reach")),
                likes=_metric(analytics.get("likes")),
                comments=_metric(analytics.get("comments")),
                shares=_metric(analytics.get("shares")),
                saves=_metric(analytics.get("saves")),
                link_clicks=_metric(analytics.get("clicks")),
                views=_metric(analytics.get("views")),
                # Not available via Zernio LinkedIn analytics
                profile_visits=None,
                new_followers=None,
                website_sessions=None,
                cta_actions=None,
                leads=None,
                qualified_leads=None,
            )
            records.append(record)
            log.info(
                "linkedin: collected content_id=%s post_id=%s "
                "impressions=%s reach=%s likes=%s comments=%s shares=%s clicks=%s",
                entry.content_id, post_id,
                record.impressions, record.reach, record.likes,
                record.comments, record.shares, record.link_clicks,
            )

        log.info("linkedin: collected %d/%d linkedin entries", len(records), len(li_entries))
        return records


def _metric(value) -> Optional[int]:
    """Normalize a Zernio metric value. None/missing → None. Numeric → int."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
