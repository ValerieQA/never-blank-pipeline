"""
Never Blank Strategy Engine — Weekly Review CLI (Phase 4A).

Loads the active strategy, accepts weekly performance inputs,
drafts a WeeklyReview with LLM-suggested decision + rationale,
and saves it to strategy/reviews/weekly/.

Usage:
  python3 -m scripts.strategy.run_weekly_review \\
    --week 1 \\
    --start 2026-08-04 \\
    --end 2026-08-08 \\
    --posts 3 \\
    --leads-week 0 \\
    --leads-total 0 \\
    --trend flat \\
    --notes "Saves are growing, no DMs yet"

  # Dry run (draft only, no file written):
  python3 -m scripts.strategy.run_weekly_review --week 1 --posts 3 --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from src.strategy.decision_engine import draft_weekly_review
from src.strategy.loader import load_active_strategy
from src.utils.logger import get_logger

log = get_logger("scripts.run_weekly_review")

REVIEWS_DIR = Path("strategy/reviews/weekly")


def _default_period(week_number: int, strategy_started: date) -> tuple[str, str]:
    """Return ISO date strings for Mon–Fri of the given week offset from strategy start."""
    # Find the Monday of the strategy start week, then offset by (week_number - 1) weeks
    monday = strategy_started - timedelta(days=strategy_started.weekday())
    week_start = monday + timedelta(weeks=week_number - 1)
    week_end = week_start + timedelta(days=4)
    return week_start.isoformat(), week_end.isoformat()


def save_weekly_review(review_data: dict, strategy_id: str, week_number: int, dry_run: bool) -> Path | None:
    path = REVIEWS_DIR / f"{strategy_id}_w{week_number:02d}.json"
    if dry_run:
        print("\n[dry-run] Would save to:", path)
        return None
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review_data, indent=2, default=str))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft and save a weekly strategy review")
    parser.add_argument("--week", type=int, required=True, help="Week number in the strategy cycle (1–4)")
    parser.add_argument("--start", type=str, default=None, help="Period start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="Period end date (YYYY-MM-DD)")
    parser.add_argument("--posts", type=int, default=0, help="Posts published this week")
    parser.add_argument("--leads-week", type=int, default=0, dest="leads_week", help="Leads generated this week")
    parser.add_argument("--leads-total", type=int, default=0, dest="leads_total", help="Cumulative leads in cycle")
    parser.add_argument("--trend", type=str, default="insufficient_data",
                        choices=["growing", "flat", "declining", "insufficient_data"],
                        help="Engagement trend this week")
    parser.add_argument("--top", type=str, default="", help="Comma-separated top-performing content_ids")
    parser.add_argument("--notes", type=str, default="", help="Qualitative notes for this week")
    parser.add_argument("--dry-run", action="store_true", help="Draft and print; do not save")
    args = parser.parse_args()

    strategy = load_active_strategy()
    if strategy is None:
        print("ERROR: No active strategy found at strategy/current/strategy.json")
        raise SystemExit(1)

    period_start, period_end = args.start, args.end
    if not period_start or not period_end:
        period_start, period_end = _default_period(args.week, strategy.started_at)
        print(f"[auto] Period: {period_start} → {period_end}")

    top_performing = [x.strip() for x in args.top.split(",") if x.strip()]

    print(f"\nDrafting weekly review — week {args.week} of {strategy.strategy_name}...")
    review = draft_weekly_review(
        strategy=strategy,
        week_number=args.week,
        period_start=period_start,
        period_end=period_end,
        posts_published=args.posts,
        leads_this_week=args.leads_week,
        leads_cumulative=args.leads_total,
        engagement_trend=args.trend,
        top_performing=top_performing,
        qualitative_notes=args.notes,
    )

    review_data = json.loads(review.model_dump_json())

    print(f"\n{'─' * 60}")
    print(f"DECISION:  {review.decision.value}")
    print(f"RATIONALE: {review.rationale}")
    if review.adjustments:
        print("ADJUSTMENTS:")
        for adj in review.adjustments:
            print(f"  • {adj}")
    print(f"{'─' * 60}")

    saved_path = save_weekly_review(review_data, strategy.strategy_id, args.week, args.dry_run)
    if saved_path:
        print(f"\nSaved → {saved_path}")
    else:
        print("\n[dry-run] Review not saved.")


if __name__ == "__main__":
    main()
