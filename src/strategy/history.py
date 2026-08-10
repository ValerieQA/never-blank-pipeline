"""
Never Blank Strategy Engine — History Engine (Phase 4B).

Four responsibilities:
  4B.1 Strategy Rotation  — archive current, activate new (separate ops + combined rotate)
  4B.2 Decision History   — append-only decision_log.jsonl
  4B.3 Published Index    — append-only published_content_index.jsonl
  4B.4 Review Archive     — move weekly/monthly reviews to history when strategy rotates

Layout:
  strategy/
    published_content_index.jsonl            ← 4B.3: all published entries, all strategies
    current/
      strategy.json                          ← active strategy
      strategy.md
    reviews/
      weekly/                                ← active weekly reviews
      monthly/
      recommendations/
    history/
      strategies/                            ← 4B.1: {timestamp}_{strategy_id}.json
      reviews/
        {strategy_id}/                       ← 4B.4: reviews after rotation
      decisions/
        decision_log.jsonl                   ← 4B.2: one line per strategic change
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.strategy.models import PublishedEntry, StrategyChangeRecord
from src.utils.logger import get_logger

log = get_logger("strategy.history")

# ── Path constants ─────────────────────────────────────────────────────────────

PUBLISHED_INDEX        = Path("strategy/published_content_index.jsonl")
CURRENT_DIR            = Path("strategy/current")
CURRENT_STRATEGY_JSON  = CURRENT_DIR / "strategy.json"
CURRENT_STRATEGY_MD    = CURRENT_DIR / "strategy.md"
HISTORY_STRATEGIES_DIR = Path("strategy/history/strategies")
HISTORY_REVIEWS_DIR    = Path("strategy/history/reviews")
DECISIONS_DIR          = Path("strategy/history/decisions")
DECISION_LOG           = DECISIONS_DIR / "decision_log.jsonl"
WEEKLY_REVIEWS_DIR     = Path("strategy/reviews/weekly")
MONTHLY_REVIEWS_DIR    = Path("strategy/reviews/monthly")


# ── 4B.1 Strategy Rotation ─────────────────────────────────────────────────────

def archive_current_strategy() -> Path:
    """
    Archive current strategy.json (and strategy.md if present) to
    strategy/history/strategies/{timestamp}_{strategy_id}.json.

    Does NOT write a new strategy — use when rotation happens in two steps
    (archive now, activate later once the new strategy is ready).

    Raises FileNotFoundError if current strategy.json does not exist.
    Returns the path of the archived file.
    """
    if not CURRENT_STRATEGY_JSON.exists():
        raise FileNotFoundError(
            f"Cannot archive strategy: {CURRENT_STRATEGY_JSON} does not exist"
        )

    current_data = json.loads(CURRENT_STRATEGY_JSON.read_text())
    current_id = current_data.get("strategy_id", "unknown")

    # Timestamp (not just date) prevents collision if rotated twice in one day
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    HISTORY_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

    archive_path = HISTORY_STRATEGIES_DIR / f"{timestamp}_{current_id}.json"
    if archive_path.exists():
        raise FileExistsError(f"Archive collision — file already exists: {archive_path}")

    shutil.copy2(CURRENT_STRATEGY_JSON, archive_path)
    if CURRENT_STRATEGY_MD.exists():
        md_archive = HISTORY_STRATEGIES_DIR / f"{timestamp}_{current_id}.md"
        shutil.copy2(CURRENT_STRATEGY_MD, md_archive)

    log.info("Strategy archived: %s → %s", current_id, archive_path)
    return archive_path


def activate_new_strategy(new_strategy_data: dict) -> None:
    """
    Write new_strategy_data to strategy/current/strategy.json atomically
    (temp file + os.replace — crash-safe on POSIX).

    Validates new_strategy_data with the Strategy model before writing.
    Raises ValueError if validation fails.
    Does NOT archive the current strategy — call archive_current_strategy() first.
    """
    from src.strategy.models import Strategy

    new_strategy_id = new_strategy_data.get("strategy_id")
    if not new_strategy_id or not str(new_strategy_id).strip():
        raise ValueError("new_strategy_data must contain a non-empty strategy_id")

    # Validate before touching the filesystem
    try:
        Strategy(**new_strategy_data)
    except Exception as exc:
        raise ValueError(f"New strategy data is invalid: {exc}") from exc

    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    content = json.dumps(new_strategy_data, indent=2, ensure_ascii=False)

    # Write to temp file in same directory, then atomic replace
    tmp_fd, tmp_path_str = tempfile.mkstemp(dir=CURRENT_DIR, suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, CURRENT_STRATEGY_JSON)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    log.info("New strategy activated: %s → %s", new_strategy_id, CURRENT_STRATEGY_JSON)


def rotate_strategy(new_strategy_data: dict) -> Path:
    """
    Atomic strategy rotation: archive current → activate new.

    Calls archive_current_strategy() then activate_new_strategy().
    Returns the path of the archived file.

    If activate fails after archive succeeds, the archive remains in history/
    (safe: old strategy is preserved) but current/ still holds the old file.
    """
    archive_path = archive_current_strategy()
    try:
        activate_new_strategy(new_strategy_data)
    except Exception:
        log.error(
            "activate_new_strategy failed after archive — current strategy unchanged. "
            "Archive is at: %s", archive_path,
        )
        raise
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

def append_published_entry(entry: PublishedEntry, *, policy=None) -> None:
    """
    Append one PublishedEntry to the published content index.
    Creates the file if it does not exist.

    Callers MUST validate that entry.strategy_id is non-empty before calling.
    Non-fatal: errors are logged and swallowed so publish never fails on index write.

    Policy check: if `policy` is provided, calls
        policy.check("history_write", adapter="append_published_entry")
    BEFORE any filesystem write. This produces an AuditEntry with
    blocked_before_network=True when the operation is not allowed.

    Fallback: NB_CONTROLLED_RUN=1 env-var blocks for legacy callers.
    """
    if policy is not None:
        policy.check("history_write", adapter="append_published_entry")

    if os.environ.get("NB_CONTROLLED_RUN") == "1":
        raise EnvironmentError(
            "append_published_entry blocked: NB_CONTROLLED_RUN=1 is set. "
            "Publication history writes are forbidden in controlled-run mode."
        )
    try:
        PUBLISHED_INDEX.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(json.loads(entry.model_dump_json()), default=str)
        with PUBLISHED_INDEX.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        log.info(
            "Published index updated: content_id=%s strategy=%s week=%s",
            entry.content_id, entry.strategy_id, entry.strategy_week,
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


def update_entry(content_id: str, patch: dict) -> bool:
    """
    Apply a partial update to a single entry in published_content_index.jsonl.

    Only updates the entry whose content_id matches; all other entries are
    written back unchanged. Returns True if the entry was found and updated.

    The `patch` dict is merged into the stored JSON — keys not present in
    patch are preserved. This interface is stable: the backing store can be
    replaced (SQLite, DuckDB) without changing callers.

    Primary use: write analytics fields back after scoring:
        update_entry("2026-08-test-w1-01", {
            "analytics_score": 0.74,
            "analytics_fetched_at": "2026-08-15T12:00:00+00:00",
            "analytics_version": "v1",
        })

    This is a full JSONL rewrite. Call once per scoring batch, not per row.
    """
    if not PUBLISHED_INDEX.exists():
        log.warning("update_entry: published_content_index.jsonl not found")
        return False

    lines = PUBLISHED_INDEX.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("content_id") == content_id:
                data.update(patch)
                found = True
            new_lines.append(json.dumps(data, default=str))
        except json.JSONDecodeError:
            new_lines.append(line)

    if found:
        PUBLISHED_INDEX.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        log.info("update_entry: patched content_id=%s fields=%s", content_id, list(patch.keys()))
    else:
        log.warning("update_entry: content_id=%s not found in index", content_id)

    return found


def mark_entries_reviewed(strategy_id: str, week_number: int) -> int:
    """
    Mark published_content_index.jsonl entries as reviewed=True for all entries
    belonging to strategy_id with strategy_week <= week_number.

    Entries without strategy_week (legacy entries) are always marked.
    This is a full JSONL rewrite — use sparingly.
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
                entry_week = data.get("strategy_week")
                if entry_week is None or entry_week <= week_number:
                    data["reviewed"] = True
                    updated += 1
            new_lines.append(json.dumps(data, default=str))
        except json.JSONDecodeError:
            new_lines.append(line)

    PUBLISHED_INDEX.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Marked %d entries as reviewed (strategy=%s, week<=%d)", updated, strategy_id, week_number)
    return updated
