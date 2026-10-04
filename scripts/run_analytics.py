"""
Never Blank Analytics — CLI entry point.

Runs BlogCollector and LinkedInCollector through the orchestrated pipeline
and prints a structured run summary.

Usage:
    python scripts/run_analytics.py [--strategy-id STRATEGY_ID] [--dry-run]

Options:
    --strategy-id   Only process entries for this strategy (default: all)
    --dry-run       Compute scores but do not write to History

Env vars required by collectors:
    NB_WIX_API_KEY         — Wix REST API key (BlogCollector)
    NB_WIX_SITE_ID         — Wix site ID (BlogCollector)
    NB_ZERNIO_API_KEY      — Zernio API key (LinkedInCollector)

Exit codes:
    0 — all collectors succeeded (or no entries to process)
    1 — one or more collectors failed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make repo root importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.registry import registered_collectors
from src.analytics.orchestrator import run_analytics_pipeline
from src.utils.logger import get_logger

log = get_logger("run_analytics")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Never Blank analytics pipeline")
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="Limit to entries for this strategy ID (default: all strategies)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute scores but do not write to History",
    )
    args = parser.parse_args()

    # From the registry rather than a literal list (NB-08s). Today this builds
    # exactly `[BlogCollector(), LinkedInCollector()]` — a test pins that — and
    # a destination that registers a collector later is picked up without
    # editing this script. The seam gets a real consumer here on purpose: a
    # registry nothing reads is how the last one ended up being an argument
    # list in a script.
    collectors = registered_collectors()

    log.info(
        "run_analytics: starting — collectors=%s strategy_id=%s dry_run=%s",
        [c.platform for c in collectors],
        args.strategy_id or "all",
        args.dry_run,
    )

    result = run_analytics_pipeline(
        collectors=collectors,
        strategy_id=args.strategy_id,
        dry_run=args.dry_run,
    )

    print(result.format_summary())

    if result.collectors_failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
