"""
Never Blank Analytics — Blog/Wix Collector (Phase 4D.1).

Fetches post statistics from the Wix Blog Statistics API v2.
Each PublishedEntry with platform="blog" and a non-empty url is queried.

API used:
  POST https://www.wixapis.com/blog/v2/stats/post
  Headers: Authorization: <NB_WIX_API_KEY>
           wix-site-id:   <NB_WIX_SITE_ID>

The post slug is extracted from PublishedEntry.url (last path segment, no query string).
If PublishedEntry.url is empty, the entry is skipped with a warning.

Metrics returned by Wix Blog stats:
  - views (total post views)
  - likes
  - comments

Wix Blog v2 stats do not expose reach, saves, shares, link_clicks, or leads —
those fields remain None in the AnalyticsRecord. The scoring layer handles
None gracefully (skips unavailable metrics).

Env vars required:
  NB_WIX_API_KEY   — Wix API key (same as used by WixPublisher)
  NB_WIX_SITE_ID   — Wix site ID

If env vars are missing, collect() raises CollectorError immediately (no API calls).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from src.analytics.base import BaseCollector, CollectorError
from src.strategy.models import AnalyticsRecord, PublishedEntry
from src.utils.logger import get_logger

log = get_logger("analytics.blog")

_API_BASE = "https://www.wixapis.com"
_STATS_URL = f"{_API_BASE}/blog/v2/stats/post"


def _slug_from_url(url: str) -> Optional[str]:
    """
    Extract post slug from a Wix blog URL.

    Examples:
      https://www.neverblank.co/post/the-dark-month  → the-dark-month
      https://www.neverblank.co/post/agency-presence/ → agency-presence
    """
    url = url.rstrip("/").split("?")[0]
    segments = [s for s in url.split("/") if s]
    return segments[-1] if segments else None


class BlogCollector(BaseCollector):
    """
    Fetches view/like/comment counts from Wix Blog Statistics API.

    Filters PublishedEntry list to platform="blog" entries with non-empty url.
    Skips entries with missing url (warns); raises CollectorError on auth failure.
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
            raise CollectorError(
                f"blog: missing required env vars: {missing}"
            )

    def _fetch_post_stats(self, slug: str) -> dict:
        """
        Fetch statistics for one blog post by slug.
        Returns raw Wix API response dict.
        Raises CollectorError on API or network failure.
        """
        url = f"{_STATS_URL}?postSlug={slug}"
        headers = {
            "Authorization": self._api_key,
            "wix-site-id":   self._site_id,
            "Content-Type":  "application/json",
        }
        return self._fetch_with_retry(url, headers=headers)

    def collect(self, entries: list[PublishedEntry]) -> list[AnalyticsRecord]:
        """
        Collect blog statistics for all platform="blog" entries with a url.

        Args:
            entries: full published index (unfiltered).

        Returns:
            list[AnalyticsRecord]: one record per successfully fetched post.
            Entries without a URL or with API errors are skipped (logged).
        """
        self._check_credentials()

        blog_entries = [e for e in entries if e.platform == "blog"]
        if not blog_entries:
            log.info("blog: no blog entries in index — nothing to collect")
            return []

        records: list[AnalyticsRecord] = []
        collected_at = self._now()

        for entry in blog_entries:
            if not entry.url:
                log.warning("blog: entry %s has no URL — skipping", entry.content_id)
                continue

            slug = _slug_from_url(entry.url)
            if not slug:
                log.warning(
                    "blog: cannot extract slug from URL %r (content_id=%s) — skipping",
                    entry.url, entry.content_id,
                )
                continue

            if self._is_stale(collected_at, entry.analytics_fetched_at):
                log.info(
                    "blog: entry %s already has fresher analytics (%s) — skipping",
                    entry.content_id, entry.analytics_fetched_at,
                )
                continue

            try:
                raw = self._fetch_post_stats(slug)
            except CollectorError as exc:
                log.warning("blog: failed to fetch stats for %s (%s): %s",
                            entry.content_id, slug, exc)
                continue

            stats = raw.get("stats", raw)  # Wix returns {"stats": {...}} or the object directly

            record = AnalyticsRecord(
                content_id=entry.content_id,
                platform="blog",
                published_at=entry.published_at,
                collected_at=collected_at,
                views=_metric(stats.get("views")),
                likes=_metric(stats.get("likes")),
                comments=_metric(stats.get("comments")),
                # Not available via Wix Blog stats API
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
                "blog: collected content_id=%s slug=%s views=%s likes=%s comments=%s",
                entry.content_id, slug, record.views, record.likes, record.comments,
            )

        log.info("blog: collected %d/%d blog entries", len(records), len(blog_entries))
        return records


def _metric(value) -> Optional[int]:
    """
    Normalize a Wix API metric value.
    None/missing → None (not collected, not zero).
    Numeric → int.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
