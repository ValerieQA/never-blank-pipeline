"""
Never Blank Analytics — Orchestrator (Phase 4D.4).

Runs the full analytics pipeline in one call:
  1. load_published_index()            — get all published entries
  2. run each registered collector     — fetch raw metrics per platform
  3. score_records()                   — normalize to analytics_score 0.0–1.0
  4. update_entry() per scored result  — write back to History

Usage (CLI script will call this):
    from src.analytics.orchestrator import run_analytics_pipeline
    summary = run_analytics_pipeline(collectors=[...])

Adding a new platform:
    Import its collector and include it in the collectors= list.
    No other changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.analytics.collector_protocol import AnalyticsCollector
from src.analytics.scorer import score_records
from src.strategy.history import load_published_index, update_entry
from src.strategy.models import AnalyticsRecord, PublishedEntry
from src.utils.logger import get_logger

log = get_logger("analytics.orchestrator")


@dataclass
class AnalyticsPipelineResult:
    """Summary of one orchestrator run."""
    entries_loaded:   int = 0
    records_fetched:  int = 0
    records_scored:   int = 0
    entries_updated:  int = 0
    collector_errors: list[str] = field(default_factory=list)
    skipped_no_score: int = 0


def run_analytics_pipeline(
    collectors: list[AnalyticsCollector],
    strategy_id: Optional[str] = None,
    dry_run: bool = False,
) -> AnalyticsPipelineResult:
    """
    Run the full analytics pipeline.

    Args:
        collectors:  list of AnalyticsCollector instances to run.
                     Order does not matter — each collector filters by platform.
        strategy_id: if set, only process entries for this strategy.
                     If None, processes all entries in the index.
        dry_run:     if True, scores are computed but update_entry() is not called.
                     Useful for testing scorer output without modifying History.

    Returns:
        AnalyticsPipelineResult with counts and any collector errors.
    """
    result = AnalyticsPipelineResult()

    entries = load_published_index(strategy_id=strategy_id)
    result.entries_loaded = len(entries)
    log.info(
        "orchestrator: loaded %d entries (strategy_id=%s)",
        len(entries), strategy_id or "all",
    )

    if not entries:
        log.info("orchestrator: no entries to process — exiting")
        return result

    # ── Run collectors ────────────────────────────────────────────────────────
    all_records: list[AnalyticsRecord] = []

    for collector in collectors:
        try:
            records = collector.collect(entries)
            log.info(
                "orchestrator: %s returned %d records",
                collector.platform, len(records),
            )
            all_records.extend(records)
        except Exception as exc:
            msg = f"{collector.platform}: {exc}"
            log.error("orchestrator: collector error — %s", msg)
            result.collector_errors.append(msg)

    result.records_fetched = len(all_records)

    if not all_records:
        log.info("orchestrator: no records collected — exiting")
        return result

    # ── Score ─────────────────────────────────────────────────────────────────
    patches = score_records(all_records)
    result.records_scored  = len(patches)
    result.skipped_no_score = len(all_records) - len(patches)

    # ── Write back to History ─────────────────────────────────────────────────
    for patch in patches:
        content_id = patch.pop("content_id")
        if dry_run:
            log.info("orchestrator [dry-run]: would patch content_id=%s %s", content_id, patch)
            result.entries_updated += 1
        else:
            found = update_entry(content_id, patch)
            if found:
                result.entries_updated += 1
            else:
                log.warning(
                    "orchestrator: update_entry returned False for content_id=%s "
                    "(entry may have been removed from index)",
                    content_id,
                )

    log.info(
        "orchestrator: done — loaded=%d fetched=%d scored=%d updated=%d errors=%d dry_run=%s",
        result.entries_loaded,
        result.records_fetched,
        result.records_scored,
        result.entries_updated,
        len(result.collector_errors),
        dry_run,
    )
    return result
