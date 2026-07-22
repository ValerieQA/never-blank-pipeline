"""
Never Blank Analytics — Blog/Wix Collector (Phase 4D.1).

Fetches post metrics from the Wix Blog Posts Stats API v3:
  GET https://www.wixapis.com/blog/v3/posts/{postId}/metrics

Response shape:
  {"metrics": {"comments": 5, "likes": 8, "views": 31}}

Each PublishedEntry with platform="blog" and a non-empty platform_content_id
is queried. Entries without platform_content_id are skipped with a warning
(platform_content_id is populated by publish_packages.py from PublishResult.external_id
at the time of Wix publication).

Metrics not available from Wix Blog metrics API (reach, saves, shares,
link_clicks, leads, etc.) remain None in AnalyticsRecord. The scoring
layer handles None gracefully (skips unavailable metrics).

Env vars required:
  NB_WIX_API_KEY   — Wix API key (same as used by WixPublisher)
  NB_WIX_SITE_ID   — Wix site ID

AuthorizationCollectorError is propagated to the orchestrator immediately
(invalid credentials affect all entries equally — no point continuing).
Per-entry API errors (network timeout, 5xx) are non-fatal — entry is skipped.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from src.analytics.base import (
    AuthorizationCollectorError,
    BaseCollector,
    CollectorError,
    EntryCollectorError,
)
from src.strategy.models import AnalyticsRecord, PublishedEntry
from src.utils.logger import get_logger

log = get_logger("analytics.blog")

_API_BASE   = "https://www.wixapis.com"
_METRICS_URL = _API_BASE + "/blog/v3/posts/{post_id}/metrics"


class BlogCollector(BaseCollector):
    """
    Fetches view/like/comment counts from Wix Blog Posts Stats API v3.

    Requires PublishedEntry.publications["blog"].external_id (Wix post ID).
    Entries without a blog publication record or without an external_id are skipped.
    Legacy entries with only platform_content_id are backfilled automatically by
    the PublishedEntry model validator.

    AuthorizationCollectorError is raised immediately on 401/403 so the
    orchestrator can record the whole-collector failure and stop retrying.
    Per-entry errors (network, 5xx, 404) are caught and logged; remaining
    entries continue to be collected.
    """

    platform = "blog"

    def __init__(
        self,
        api_key: Optional[str] = None,
        site_id: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.getenv("NB_WIX_API_KEY", "")
        self._site_id = site_id or os.getenv("NB_WIX_SITE_ID", "")

    def _check_credentials(self) -> None:
        missing = [k for k, v in {
            "NB_WIX_API_KEY": self._api_key,
            "NB_WIX_SITE_ID": self._site_id,
        }.items() if not v]
        if missing:
            raise CollectorError(f"blog: missing required env vars: {missing}")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key,
            "wix-site-id":   self._site_id,
            "Content-Type":  "application/json",
        }

    def _fetch_post_metrics(self, post_id: str) -> dict:
        """
        Fetch metrics for one Wix blog post by its native post ID.

        GET /blog/v3/posts/{postId}/metrics
        Returns raw Wix API response dict.

        AuthorizationCollectorError propagates up (stop the whole collector).
        Other CollectorErrors become EntryCollectorError (skip this entry only).
        """
        url = _METRICS_URL.format(post_id=post_id)
        try:
            return self._fetch_with_retry(url, headers=self._headers())
        except AuthorizationCollectorError:
            raise   # propagate — invalid credentials affect all entries
        except CollectorError as exc:
            raise EntryCollectorError(str(exc)) from exc

    def collect(self, entries: list[PublishedEntry]) -> list[AnalyticsRecord]:
        """
        Collect blog metrics for all platform="blog" entries with a platform_content_id.

        Args:
            entries: full published index (unfiltered).

        Returns:
            list[AnalyticsRecord]: one record per successfully fetched post.

        Raises:
            CollectorError: if credentials are missing (checked before any API call).
            AuthorizationCollectorError: if Wix returns 401/403 (propagated from first call).
        """
        self._check_credentials()

        blog_entries = [
            e for e in entries
            if "blog" in e.publications and e.publications["blog"].external_id
        ]
        if not blog_entries:
            log.info("blog: no blog entries with a Wix post ID in index — nothing to collect")
            return []

        records: list[AnalyticsRecord] = []
        collected_at = self._now()

        for entry in blog_entries:
            post_id = entry.publications["blog"].external_id

            if self._is_stale(collected_at, entry.analytics_fetched_at):
                log.info(
                    "blog: entry %s already has fresher analytics (%s) — skipping",
                    entry.content_id, entry.analytics_fetched_at,
                )
                continue

            try:
                raw = self._fetch_post_metrics(post_id)
            except AuthorizationCollectorError:
                raise   # stop the whole collector
            except EntryCollectorError as exc:
                log.warning(
                    "blog: failed to fetch metrics for %s (post_id=%s): %s",
                    entry.content_id, post_id, exc,
                )
                continue

            metrics = raw.get("metrics", raw)

            record = AnalyticsRecord(
                content_id=entry.content_id,
                platform="blog",
                published_at=entry.published_at,
                collected_at=collected_at,
                views=_metric(metrics.get("views")),
                likes=_metric(metrics.get("likes")),
                comments=_metric(metrics.get("comments")),
                # Not available via Wix Blog metrics API
                impressions=None,
                reach=None,
                shares=None,
                saves=None,
                profile_visits=None,
                new_followers=None,
                link_clicks=None,
                website_sessions=None,
                cta_actions=None,
                leads=None,
                qualified_leads=None,
            )
            records.append(record)
            log.info(
                "blog: collected content_id=%s post_id=%s views=%s likes=%s comments=%s",
                entry.content_id, post_id, record.views, record.likes, record.comments,
            )

        log.info("blog: collected %d/%d blog entries", len(records), len(blog_entries))
        return records


def _metric(value) -> Optional[int]:
    """Normalize a Wix API metric value. None/missing → None. Numeric → int."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
