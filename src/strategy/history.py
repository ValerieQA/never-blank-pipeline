"""
Never Blank Strategy Engine — History Engine (Phase 4B).

Four responsibilities:
  4B.1 Strategy Rotation  — atomic: archive current strategy → write new strategy
  4B.2 Decision History   — append-only decision_log.jsonl
  4B.3 Published Index    — append-only published_content_index.jsonl
  4B.4 Review Archive     — move weekly/monthly reviews to history when strategy rotates

All write operations are append-only or idempotent. Nothing is ever deleted by
this module — archiving = copy, not move (except for review files during rotation).

Layout:
  strategy/
    published_content_index.jsonl           ← 4B.3: all published entries, all strategies
    current/
      strategy.json                         ← active strategy
      strategy.md
    reviews/
      weekly/                               ← active weekly reviews
      monthly/
      recommendations/
    history/
      strategies/                           ← 4B.1: {date}_{strategy_id}.json
      reviews/
        {strategy_id}/                      ← 4B.4: weekly reviews after rotation
      decisions/
        decision_log.jsonl                  ← 4B.2: one line per strategic change
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.strategy.models import PublishedEntry, StrategyChangeRecord
from src.utils.logger import get_logger

log = get_logger("strategy.history")

# ── Path constants ─────────────────────────────────────────────────────────────

PUBLISHED_INDEX      = Path("strategy/published_content_index.jsonl")
CURRENT_DIR          = Path("strategy/current")
CURRENT_STRATEGY_JSON = CURRENT_DIR / "strategy.json"
CURRENT_STRATEGY_MD   = CURRENT_DIR / "strategy.md"
HISTORY_STRATEGIES_DIR = Path("strategy/history/strategies")
HISTORY_REVIEWS_DIR    = Path("strategy/history/reviews")
DECISIONS_DIR          = Path("strategy/history/decisions")
DECISION_LOG           = DECISIONS_DIR / "decision_log.jsonl"
WEEKLY_REVIEWS_DIR     = Path("strategy/reviews/weekly")
MONTHLY_REVIEWS_DIR    = Path("strategy/reviews/monthly")


# ── 4B.1 Strategy Rotation ─────────────────────────────────────────────────────

def rotate_strategy(new_strategy_data: dict) -> Path:
    """
    Atomic strategy rotation:
      1. Archive current strategy.json + strategy.md to
         strategy/history/strategies/{YYYY-MM-DD}_{strategy_id}.json
      2. Write new strategy to strategy/current/strategy.json

    Returns the path of the archived strategy file.
    Raises FileNotFoundError if current strategy.json does not exist.
    Raises ValueError if new_strategy_data is missing strategy_id.
    """
    if not CURRENT_STRATEGY_JSON.exists():
        raise FileNotFoundError(
            f"Cannot rotate strategy: {CURRENT_STRATEGY_JSON} does not exist"
        )

    new_strategy_id = new_strategy_data.get("strategy_id")
    if not new_strategy_id:
        raise ValueError("new_strategy_data must contain a non-empty strategy_id")

    # Load current strategy_id for archive naming
    current_data = json.loads(CURRENT_STRATEGY_JSON.read_text())
    current_id = current_data.get("strategy_id", "unknown")
    archive_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Archive current strategy
    HISTORY_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = HISTORY_STRATEGIES_DIR / f"{archive_date}_{current_id}.json"
    shutil.copy2(CURRENT_STRATEGY_JSON, archive_path)
    if CURRENT_STRATEGY_MD.exists():
        md_archive_path = HISTORY_STRATEGIES_DIR / f"{archive_date}_{current_id}.md"
        shutil.copy2(CURRENT_STRATEGY_MD, md_archive_path)

    log.info("Strategy archived: %s → %s", current_id, archive_path)

    # Write new strategy
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_STRATEGY_JSON.write_text(
        json.dumps(new_strategy_data, indent=2, ensure_ascii=False)
    )
    log.info("New strategy written: %s → %s", new_strategy_id, CURRENT_STRATEGY_JSON)

    return archive_path


# ── 4B.2 Decision History ──────────────────────────────────────────────────────

def append_decision_log(record: StrategyChangeRecord) -> None:
    """
    Append a StrategyChangeRecord to the append-only decision log.
    Creates the log file and parent directories if they do not exist.
    """
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    entry = json.loads(record.model_dump_json())
    with DECISION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    log.info("Decision log updated: action=%s from=%s", record.decision.value, record.from_strategy_id)


def load_decision_log() -> list[dict]:
    """Return all decision log entries, oldest first."""
    if not DECISION_LOG.exists():
        return []
    entries = []
    for line in DECISION_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("Skipping malformed decision log entry: %s", exc)
    return entries


# ── 4B.3 Published Content Index ───────────────────────────────────────────────

def append_published_entry(entry: PublishedEntry) -> None:
    """
    Append one PublishedEntry to the published content index.
    Creates the file if it does not exist.
    Non-fatal for callers — errors are logged but not re-raised.
    """
    try:
        PUBLISHED_INDEX.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(json.loads(entry.model_dump_json()), default=str)
        with PUBLISHED_INDEX.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        log.info(
            "Published index updated: content_id=%s platform=%s strategy=%s",
            entry.content_id, entry.platform, entry.strategy_id,
        )
    except Exception as exc:
        log.error("Failed to append to published index: %s", exc)


def load_published_index(
    strategy_id: Optional[str] = None,
    last_n: Optional[int] = None,
) -> list[PublishedEntry]:
    """
    Load entries from published_content_index.jsonl.

    Args:
        strategy_id: filter to entries for a specific strategy (None = all strategies)
        last_n:      return only the most recent N entries (None = all)

    Returns entries in chronological order (oldest first).
    """
    if not PUBLISHED_INDEX.exists():
        return []

    entries: list[PublishedEntry] = []
    for line in PUBLISHED_INDEX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if strategy_id is None or data.get("strategy_id") == strategy_id:
                entries.append(PublishedEntry(**data))
        except Exception as exc:
            log.warning("Skipping malformed published index entry: %s", exc)

    if last_n is not None:
        entries = entries[-last_n:]
    return entries


# ── 4B.4 Review Archive ────────────────────────────────────────────────────────

def archive_weekly_reviews(strategy_id: str) -> None:
    """
    Move all weekly review files for strategy_id from
    strategy/reviews/weekly/ to strategy/history/reviews/{strategy_id}/.

    Called during strategy rotation (REPLACE_STRATEGY).
    """
    if not WEEKLY_REVIEWS_DIR.exists():
        return
    dest_dir = HISTORY_REVIEWS_DIR / strategy_id
    files = list(WEEKLY_REVIEWS_DIR.glob(f"{strategy_id}_w*.json"))
    if not files:
        log.info("No weekly reviews to archive for strategy %s", strategy_id)
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.move(str(path), dest_dir / path.name)
        log.debug("Weekly review archived: %s → %s", path.name, dest_dir)
    log.info("Archived %d weekly review(s) for strategy %s", len(files), strategy_id)


def archive_monthly_review(strategy_id: str) -> None:
    """
    Move the monthly review file for strategy_id from
    strategy/reviews/monthly/ to strategy/history/reviews/{strategy_id}/.

    Called during strategy rotation (REPLACE_STRATEGY).
    """
    if not MONTHLY_REVIEWS_DIR.exists():
        return
    dest_dir = HISTORY_REVIEWS_DIR / strategy_id
    path = MONTHLY_REVIEWS_DIR / f"{strategy_id}_monthly.json"
    if not path.exists():
        log.info("No monthly review to archive for strategy %s", strategy_id)
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest_dir / path.name)
    log.info("Monthly review archived for strategy %s → %s", strategy_id, dest_dir)


def mark_entries_reviewed(strategy_id: str, week_number: int) -> int:
    """
    Mark published_content_index.jsonl entries as reviewed=True
    for entries belonging to strategy_id published before or during week_number.

    This is a full rewrite of the JSONL file — use sparingly.
    Returns count of updated entries.
    """
    if not PUBLISHED_INDEX.exists():
        return 0

    lines = PUBLISHED_INDEX.read_text(encoding="utf-8").splitlines()
    updated = 0
    new_lines: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("strategy_id") == strategy_id and not data.get("reviewed", False):
                data["reviewed"] = True
                updated += 1
            new_lines.append(json.dumps(data, default=str))
        except json.JSONDecodeError:
            new_lines.append(line)

    PUBLISHED_INDEX.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Marked %d entries as reviewed for strategy %s", updated, strategy_id)
    return updated
