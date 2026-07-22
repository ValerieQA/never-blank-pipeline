"""
Never Blank Analytics — Collector Protocol (Phase 4D.1).

Defines the contract every platform collector must satisfy.
Collectors are stateless: they receive a list of PublishedEntry objects
and return a list of AnalyticsRecord objects. They do not write to History.

Adding a new platform:
  1. Create src/analytics/<platform>.py
  2. Implement AnalyticsCollector Protocol (platform str + collect() method)
  3. Register in src/analytics/orchestrator.py

Platforms planned: instagram, facebook, linkedin, blog (Wix), threads, telegram.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.strategy.models import AnalyticsRecord, PublishedEntry


@runtime_checkable
class AnalyticsCollector(Protocol):
    """
    Contract for all platform analytics collectors.

    Each collector is responsible for one platform only.
    It must not know about History, Scoring, or other collectors.

    Attributes:
        platform: canonical platform name matching PublishedEntry.platform
                  (e.g. "instagram", "facebook", "linkedin", "blog")

    collect() receives the full list of PublishedEntry objects so that
    the collector can filter by platform itself — this avoids the orchestrator
    having to know which platforms each collector handles.

    Returns AnalyticsRecord objects — one per successfully fetched entry.
    Entries the collector cannot reach (wrong platform, API error, no URL)
    are silently skipped; the orchestrator handles missing coverage.
    """

    platform: str

    def collect(
        self,
        entries: list[PublishedEntry],
    ) -> list[AnalyticsRecord]:
        """
        Fetch analytics for relevant entries and return normalized records.

        Args:
            entries: all PublishedEntry objects from the index (unfiltered).
                     Collector filters to self.platform internally.

        Returns:
            list[AnalyticsRecord]: one record per successfully fetched entry.
            Empty list is valid (e.g. API unavailable, no entries for this platform).
        """
        ...
