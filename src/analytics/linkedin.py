"""
Never Blank Analytics — LinkedIn Collector (Phase 4D.2).

Fetches post metrics via the Zernio unified social API — the same service
used by LinkedInPublisher to post. Direct LinkedIn REST API access requires
the Community Management API product (restricted to registered legal entities),
so Zernio remains the single auth boundary for both posting and analytics.

Analytics endpoint:
  GET https://zernio.com/api/v1/posts/{postId}/analytics

Response shape (per Zernio docs):
  {
    "analytics": {
      "platforms": {
        "linkedin": {
          "impressions": 1420,
          "reactions":   38,
          "comments":    7,
          "shares":      4,
          "clicks":      91
        }
      }
    }
  }

Each PublishedEntry with publications["linkedin"].external_id is queried.
Entries without a LinkedIn publication record or without an external_id are
skipped with a warning.

Metrics not available via Zernio LinkedIn analytics (reach, saves, profile_visits,
website_sessions, leads, etc.) remain None in AnalyticsRecord.

Env vars required:
  NB_ZERNIO_API_KEY — Zernio API key (same as LinkedInPublisher)

AuthorizationCollectorError is propagated immediately on 401/403.
Per-entry errors are non-fatal — entry is skipped, collection continues.
"""

from __future__ import annotations

import os
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

_ANALYTICS_URL = "https://zernio.com/api/v1/posts/{post_id}/analytics"


class LinkedInCollector(BaseCollector):
    """
    Fetches LinkedIn engagement metrics via the Zernio analytics API.

    Reads the Zernio post ID from entry.publications["linkedin"].external_id
    (populated by LinkedInPublisher at publish time).

    Maps Zernio response fields:
      impressions → AnalyticsRecord.impressions
      reactions   → AnalyticsRecord.likes
      comments    → AnalyticsRecord.comments
      shares      → AnalyticsRecord.shares
      clicks      → AnalyticsRecord.link_clicks

    AuthorizationCollectorError raised immediately on 401/403 — invalid
    credentials affect all entries equally. Per-entry failures are non-fatal.
    """

    platform = "linkedin"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("NB_ZERNIO_API_KEY", "")

    def _check_credentials(self) -> None:
        if not self._api_key:
            raise CollectorError("linkedin: NB_ZERNIO_API_KEY is not set")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _fetch_post_analytics(self, post_id: str) -> dict:
        """
        Fetch analytics for one Zernio post.

        GET /api/v1/posts/{postId}/analytics
        Returns the parsed Zernio response dict.

        AuthorizationCollectorError propagates up (stop the whole collector).
        Other CollectorErrors become EntryCollectorError (skip this entry only).
        """
        url = _ANALYTICS_URL.format(post_id=post_id)
        try:
            return self._fetch_with_retry(url, headers=self._headers())
        except AuthorizationCollectorError:
            raise
        except CollectorError as exc:
            raise EntryCollectorError(str(exc)) from exc

    def collect(self, entries: list[PublishedEntry]) -> list[AnalyticsRecord]:
        """
        Collect LinkedIn analytics for all entries with a LinkedIn publication.

        Args:
            entries: full published index (unfiltered).

        Returns:
            list[AnalyticsRecord]: one record per successfully fetched post.

        Raises:
            CollectorError: if NB_ZERNIO_API_KEY is missing.
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
                log.warning(
                    "linkedin: failed to fetch analytics for %s (post_id=%s): %s",
                    entry.content_id, post_id, exc,
                )
                continue

            li_metrics = (
                raw.get("analytics", {})
                   .get("platforms", {})
                   .get("linkedin", {})
            )

            record = AnalyticsRecord(
                content_id=entry.content_id,
                platform="linkedin",
                published_at=entry.publications["linkedin"].published_at or entry.published_at,
                collected_at=collected_at,
                impressions=_metric(li_metrics.get("impressions")),
                likes=_metric(li_metrics.get("reactions")),
                comments=_metric(li_metrics.get("comments")),
                shares=_metric(li_metrics.get("shares")),
                link_clicks=_metric(li_metrics.get("clicks")),
                # Not available via Zernio LinkedIn analytics
                reach=None,
                views=None,
                saves=None,
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
                "impressions=%s likes=%s comments=%s shares=%s clicks=%s",
                entry.content_id, post_id,
                record.impressions, record.likes,
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
