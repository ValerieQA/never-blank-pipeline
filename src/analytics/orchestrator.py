"""
Never Blank Analytics — Orchestrator (Phase 4D.4).

Runs the full analytics pipeline in one call:
  1. load_published_index()            — get all published entries
  2. run each registered collector     — fetch raw metrics per platform
  3. score_records()                   — normalize to analytics_score 0.0–1.0
  4. aggregate patches by content_id   — keep max score when multiple platforms
  5. update_entry() per aggregated patch — write back to History (one write per entry)

Each collector runs independently. Authorization failure or configuration error
in one collector is recorded in the run summary but does not prevent other
collectors from running.

Aggregation rationale: PublishedEntry holds a single analytics_score; when an
entry has records on both Blog and LinkedIn, we keep the highest score across
platforms. This represents the content's best reach signal — the value used by
Echo Memory to weight future strategy decisions.

Usage (CLI script will call this):
    from src.analytics.orchestrator import run_analytics_pipeline
    summary = run_analytics_pipeline(collectors=[BlogCollector(), LinkedInCollector()])

Adding a new platform:
    Import its collector and include it in the collectors= list.
    No other changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.analytics.base import AuthorizationCollectorError
from src.analytics.collector_protocol import AnalyticsCollector
from src.analytics.scorer import score_records
from src.strategy.history import load_published_index, update_entry
from src.strategy.models import AnalyticsRecord, PublishedEntry
from src.utils.logger import get_logger


def _is_stale(record: AnalyticsRecord, entry_index: dict[str, PublishedEntry]) -> bool:
    """
    Return True if record.collected_at is older than the entry's analytics_fetched_at.

    Protects against accidental data regression when an API returns cached or
    delayed data that is older than what is already stored in History.
    """
    entry = entry_index.get(record.content_id)
    if entry is None or entry.analytics_fetched_at is None or record.collected_at is None:
        return False
    existing = entry.analytics_fetched_at
    incoming = record.collected_at
    from datetime import timezone
    if existing.tzinfo is None:
        existing = existing.replace(tzinfo=timezone.utc)
    if incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    return incoming < existing


log = get_logger("analytics.orchestrator")


@dataclass
class AnalyticsPipelineResult:
    """Summary of one orchestrator run."""
    entries_loaded:       int = 0
    records_fetched:      int = 0
    records_scored:       int = 0
    entries_updated:      int = 0
    collector_errors:     list[str] = field(default_factory=list)
    skipped_no_score:     int = 0
    skipped_stale:        int = 0
    # Per-collector tracking
    collectors_attempted: list[str] = field(default_factory=list)
    collectors_succeeded: list[str] = field(default_factory=list)
    collectors_failed:    list[str] = field(default_factory=list)
    records_by_platform:  dict[str, int] = field(default_factory=dict)

    def format_summary(self) -> str:
        """Human-readable run summary for CLI output and logging."""
        lines = [
            "── Analytics Pipeline Run ─────────────────────────",
            f"  Entries loaded:     {self.entries_loaded}",
            f"  Collectors run:     {', '.join(self.collectors_attempted) or 'none'}",
        ]
        if self.collectors_succeeded:
            lines.append(f"  Succeeded:          {', '.join(self.collectors_succeeded)}")
        if self.collectors_failed:
            lines.append(f"  Failed:             {', '.join(self.collectors_failed)}")
        for platform, count in sorted(self.records_by_platform.items()):
            lines.append(f"  Records ({platform:<10}): {count}")
        lines += [
            f"  Records fetched:    {self.records_fetched}",
            f"  Records scored:     {self.records_scored}",
            f"  Entries updated:    {self.entries_updated}",
            f"  Skipped (stale):    {self.skipped_stale}",
            f"  Skipped (no score): {self.skipped_no_score}",
        ]
        if self.collector_errors:
            lines.append("  Errors:")
            for err in self.collector_errors:
                lines.append(f"    • {err}")
        lines.append("────────────────────────────────────────────────────")
        return "\n".join(lines)


def run_analytics_pipeline(
    collectors: list[AnalyticsCollector],
    strategy_id: Optional[str] = None,
    dry_run: bool = False,
) -> AnalyticsPipelineResult:
    """
    Run the full analytics pipeline.

    Args:
        collectors:  list of AnalyticsCollector instances to run.
                     Each collector filters by platform independently.
                     Auth/config failure in one does not stop others.
        strategy_id: if set, only process entries for this strategy.
                     If None, processes all entries in the index.
        dry_run:     if True, scores are computed but update_entry() is not called.
                     Useful for testing scorer output without modifying History.

    Returns:
        AnalyticsPipelineResult with counts, per-collector status, and any errors.
    """
    result = AnalyticsPipelineResult()

    entries = load_published_index(strategy_id=strategy_id)
    result.entries_loaded = len(entries)
    entry_index: dict[str, PublishedEntry] = {e.content_id: e for e in entries}
    log.info(
        "orchestrator: loaded %d entries (strategy_id=%s)",
        len(entries), strategy_id or "all",
    )

    if not entries:
        log.info("orchestrator: no entries to process — exiting")
        return result

    # ── Run collectors independently ──────────────────────────────────────────
    all_records: list[AnalyticsRecord] = []

    for collector in collectors:
        result.collectors_attempted.append(collector.platform)
        try:
            records = collector.collect(entries)
            log.info(
                "orchestrator: %s returned %d records",
                collector.platform, len(records),
            )
            result.collectors_succeeded.append(collector.platform)
            result.records_by_platform[collector.platform] = len(records)
            all_records.extend(records)
        except AuthorizationCollectorError as exc:
            msg = f"{collector.platform}: authorization failed — {exc}"
            log.error("orchestrator: %s", msg)
            result.collector_errors.append(msg)
            result.collectors_failed.append(collector.platform)
            result.records_by_platform[collector.platform] = 0
        except Exception as exc:
            msg = f"{collector.platform}: {exc}"
            log.error("orchestrator: collector error — %s", msg)
            result.collector_errors.append(msg)
            result.collectors_failed.append(collector.platform)
            result.records_by_platform[collector.platform] = 0

    result.records_fetched = len(all_records)

    if not all_records:
        log.info("orchestrator: no records collected — exiting")
        return result

    # ── Staleness guard ───────────────────────────────────────────────────────
    fresh_records: list[AnalyticsRecord] = []
    for rec in all_records:
        if _is_stale(rec, entry_index):
            log.info(
                "orchestrator: skipping stale record content_id=%s "
                "(collected_at=%s < existing analytics_fetched_at=%s)",
                rec.content_id,
                rec.collected_at,
                entry_index[rec.content_id].analytics_fetched_at,
            )
            result.skipped_stale += 1
        else:
            fresh_records.append(rec)

    # ── Score ─────────────────────────────────────────────────────────────────
    patches = score_records(fresh_records)
    result.records_scored   = len(patches)
    result.skipped_no_score = len(fresh_records) - len(patches)

    if not patches:
        log.info("orchestrator: no scoreable patches — History unchanged")
        return result

    # ── Aggregate: one patch per content_id, max score wins ──────────────────
    # An entry published on both Blog and LinkedIn produces two AnalyticsRecords.
    # score_records() returns one patch per record; we merge so History is
    # updated exactly once per entry, keeping the highest score across platforms.
    aggregated: dict[str, dict] = {}
    for patch in patches:
        cid   = patch["content_id"]
        score = patch["analytics_score"]
        if cid not in aggregated or score > aggregated[cid]["analytics_score"]:
            aggregated[cid] = patch

    # ── Write back to History ─────────────────────────────────────────────────
    for patch in aggregated.values():
        content_id = patch.pop("content_id")
        if dry_run:
            log.info(
                "orchestrator [dry-run]: would patch content_id=%s %s",
                content_id, patch,
            )
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
        "orchestrator: done — loaded=%d fetched=%d scored=%d updated=%d "
        "stale=%d no_score=%d errors=%d dry_run=%s",
        result.entries_loaded,
        result.records_fetched,
        result.records_scored,
        result.entries_updated,
        result.skipped_stale,
        result.skipped_no_score,
        len(result.collector_errors),
        dry_run,
    )
    return result
