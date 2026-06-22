"""
Stage 9 — Automatic archive.
Moves signals older than 60 days (not selected, not approved) to archive/.
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger

log = get_logger("research.archive")

ACTIVE_FILE   = Path("data/research/signals_active.jsonl")
SELECTED_FILE = Path("data/research/selected_signals.jsonl")
ARCHIVE_DIR   = Path("data/research/archive")
ARCHIVE_DAYS  = 60


def run_archive() -> int:
    if not ACTIVE_FILE.exists():
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)

    selected_ids: set[str] = set()
    if SELECTED_FILE.exists():
        with open(SELECTED_FILE) as f:
            for line in f:
                try:
                    selected_ids.add(json.loads(line.strip()).get("SIGNAL_ID", ""))
                except Exception:
                    pass

    keep: list[dict] = []
    to_archive: list[dict] = []

    with open(ACTIVE_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sig = json.loads(line)
            except json.JSONDecodeError:
                continue

            sig_id   = sig.get("SIGNAL_ID", "")
            date_str = sig.get("DATE_FOUND", "")
            approved = str(sig.get("APPROVED_OVERRIDE", "")).lower() in ("true", "yes", "1")
            in_queue = sig_id in selected_ids

            try:
                date_found = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                old_enough = date_found < cutoff
            except ValueError:
                old_enough = False

            if old_enough and not approved and not in_queue:
                to_archive.append(sig)
            else:
                keep.append(sig)

    if not to_archive:
        log.info("No signals to archive")
        return 0

    by_month: dict[str, list[dict]] = defaultdict(list)
    for sig in to_archive:
        try:
            dt        = datetime.strptime(sig.get("DATE_FOUND", ""), "%Y-%m-%d")
            month_key = dt.strftime("%Y_%m")
        except ValueError:
            month_key = "unknown"
        by_month[month_key].append(sig)

    for month_key, sigs in by_month.items():
        archive_path = ARCHIVE_DIR / f"signals_{month_key}.jsonl"
        with open(archive_path, "a") as f:
            for sig in sigs:
                f.write(json.dumps(sig, ensure_ascii=False) + "\n")
        log.info("Archived %d signals to %s", len(sigs), archive_path)

    with open(ACTIVE_FILE, "w") as f:
        for sig in keep:
            f.write(json.dumps(sig, ensure_ascii=False) + "\n")

    log.info("Archive complete: %d archived, %d remaining", len(to_archive), len(keep))
    return len(to_archive)


if __name__ == "__main__":
    n = run_archive()
    print(f"Archived {n} signals")
