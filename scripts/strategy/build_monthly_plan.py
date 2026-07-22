"""
Never Blank Strategy Engine — Monthly plan build entry point.

End-to-end orchestration:
  1. Load active strategy from strategy/current/strategy.json
  2. Load research signals from reports/signals/ (latest enriched signals file)
  3. analyze_signals()  → PatternRecords
  4. generate_monthly_content_plan()
  5. save_content_plan() → strategy/current/content_plan.{json,csv,md}

Usage:
  python3 -m scripts.strategy.build_monthly_plan
  python3 -m scripts.strategy.build_monthly_plan --signals-file reports/signals/my_signals.json
  python3 -m scripts.strategy.build_monthly_plan --dry-run

Dry-run: generates and validates the plan, prints summary, does NOT write files.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.strategy.loader import load_active_strategy
from src.strategy.market_analyzer import analyze_signals
from src.strategy.content_planner import generate_monthly_content_plan, save_content_plan
from src.utils.logger import get_logger

log = get_logger("strategy.build_monthly_plan")

_SIGNALS_DIR = Path("reports/signals")
_OUTPUT_DIR  = Path("strategy/current")


def _find_latest_signals_file() -> Path | None:
    if not _SIGNALS_DIR.exists():
        return None
    candidates = sorted(_SIGNALS_DIR.glob("*_signals*.json"), reverse=True)
    if not candidates:
        candidates = sorted(_SIGNALS_DIR.glob("*.json"), reverse=True)
    return candidates[0] if candidates else None


def _load_signals(signals_file: Path) -> list[dict]:
    data = json.loads(signals_file.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    # Some formats wrap in {"signals": [...]}
    if isinstance(data, dict) and "signals" in data:
        return data["signals"]
    raise ValueError(f"Unexpected signals file format in {signals_file}")


def build_monthly_plan(
    signals_file: Path | None = None,
    dry_run: bool = False,
) -> None:
    # ── 1. Load active strategy ───────────────────────────────────────────────
    strategy = load_active_strategy()
    if strategy is None:
        log.error("No active strategy found at strategy/current/strategy.json — aborting")
        sys.exit(1)
    log.info("Strategy loaded: %s (status=%s)", strategy.strategy_id, strategy.status.value)

    # ── 2. Find and load signals ──────────────────────────────────────────────
    if signals_file is None:
        signals_file = _find_latest_signals_file()
    if signals_file is None or not signals_file.exists():
        log.error("No signals file found in %s — aborting", _SIGNALS_DIR)
        sys.exit(1)

    raw_signals = _load_signals(signals_file)
    log.info("Signals loaded: %d signals from %s", len(raw_signals), signals_file)

    # ── 3. Analyze signals → PatternRecords ──────────────────────────────────
    patterns, rejected = analyze_signals(raw_signals)
    log.info("Pattern analysis: %d accepted, %d rejected", len(patterns), len(rejected))

    if rejected:
        log.info("Rejected signals:")
        for r in rejected:
            log.info("  [%s] %s — %s", r.get("signal_id"), r.get("headline", "")[:60], r.get("reason", ""))

    if not patterns:
        log.error("No patterns accepted from signals — cannot generate content plan")
        sys.exit(1)

    # ── 4. Generate monthly content plan ─────────────────────────────────────
    items = generate_monthly_content_plan(strategy=strategy, patterns=patterns)

    # ── 5. Print summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Never Blank — Monthly Content Plan")
    print(f"Strategy:  {strategy.strategy_id}")
    print(f"Items:     {len(items)}")
    print(f"{'='*60}")
    for item in items:
        date_str = str(item.publication_date) if item.publication_date else "TBD"
        echo_str = f" | Echo: {item.echo[:50]!r}" if item.echo else " | Echo: null"
        print(f"  [{date_str}] W{item.week} {item.content_role.value:12s} — {item.working_title[:55]}{echo_str}")
    print(f"{'='*60}\n")

    if rejected:
        print(f"Rejected signals: {len(rejected)}")
        for r in rejected:
            print(f"  [{r.get('signal_id')}] {r.get('reason', '')[:80]}")
        print()

    # ── 6. Save (unless dry-run) ─────────────────────────────────────────────
    if dry_run:
        print("Dry-run: plan validated but NOT written to disk.")
        return

    save_content_plan(items, _OUTPUT_DIR)
    print(f"Content plan saved to {_OUTPUT_DIR}/content_plan.{{json,csv,md}}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Never Blank monthly content plan")
    parser.add_argument("--signals-file", type=Path, default=None,
                        help="Path to enriched signals JSON file (default: latest in reports/signals/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate and validate plan without writing files")
    args = parser.parse_args()

    build_monthly_plan(
        signals_file=args.signals_file,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
