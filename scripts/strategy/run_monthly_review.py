"""
Never Blank Strategy Engine — Monthly Review CLI (Phase 4A).

Aggregates all weekly reviews for the active strategy cycle,
drafts a MonthlyReview + StrategyRecommendation with LLM assistance,
and saves both to strategy/reviews/.

If the decision is REPLACE_STRATEGY, the script archives the current strategy
to strategy/history/strategies/ and appends to the decision log.

Usage:
  python3 -m scripts.strategy.run_monthly_review
  python3 -m scripts.strategy.run_monthly_review --dry-run
  python3 -m scripts.strategy.run_monthly_review --strategy-id 2026-08-presence-debt
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path

from src.strategy.decision_engine import draft_monthly_review, draft_strategy_recommendation
from src.strategy.history import (
    append_decision_log,
    archive_monthly_review,
    archive_weekly_reviews,
    rotate_strategy,
)
from src.strategy.loader import load_active_strategy
from src.strategy.models import MonthlyDecision, StrategyChangeRecord, WeeklyReview
from src.utils.logger import get_logger

log = get_logger("scripts.run_monthly_review")

WEEKLY_DIR = Path("strategy/reviews/weekly")
MONTHLY_DIR = Path("strategy/reviews/monthly")
RECOMMENDATIONS_DIR = Path("strategy/reviews/recommendations")


def load_weekly_reviews(strategy_id: str) -> list[WeeklyReview]:
    """Load all weekly reviews for the given strategy_id from strategy/reviews/weekly/."""
    if not WEEKLY_DIR.exists():
        return []
    reviews = []
    for path in sorted(WEEKLY_DIR.glob(f"{strategy_id}_w*.json")):
        try:
            data = json.loads(path.read_text())
            reviews.append(WeeklyReview(**data))
            log.info("Loaded weekly review: %s", path.name)
        except Exception as exc:
            log.warning("Failed to load %s: %s", path, exc)
    return reviews


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft and save a monthly strategy review")
    parser.add_argument("--strategy-id", type=str, default=None,
                        help="Override strategy_id (default: load from strategy/current/strategy.json)")
    parser.add_argument("--dry-run", action="store_true", help="Draft and print; do not save or archive")
    args = parser.parse_args()

    strategy = load_active_strategy()
    if strategy is None:
        print("ERROR: No active strategy found at strategy/current/strategy.json")
        raise SystemExit(1)

    strategy_id = args.strategy_id or strategy.strategy_id

    weekly_reviews = load_weekly_reviews(strategy_id)
    if not weekly_reviews:
        print(f"ERROR: No weekly reviews found for strategy {strategy_id} in {WEEKLY_DIR}/")
        print("Run run_weekly_review.py first to create weekly reviews.")
        raise SystemExit(1)

    print(f"\nLoaded {len(weekly_reviews)} weekly review(s) for {strategy_id}")
    for r in weekly_reviews:
        print(f"  Week {r.week_number}: {r.decision.value} | leads={r.leads_this_week} | trend={r.engagement_trend}")

    # Draft monthly review
    print(f"\nDrafting monthly review for {strategy.strategy_name}...")
    monthly_review = draft_monthly_review(strategy, weekly_reviews)

    # Draft recommendation (separate artifact)
    monthly_path = MONTHLY_DIR / f"{strategy_id}_monthly.json"
    print("Drafting strategy recommendation...")
    recommendation = draft_strategy_recommendation(
        strategy=strategy,
        monthly_review=monthly_review,
        trigger_ref=str(monthly_path),
    )

    # Print summary
    print(f"\n{'─' * 60}")
    print(f"MONTHLY DECISION:  {monthly_review.decision.value}")
    print(f"HYPOTHESIS:        {'confirmed' if monthly_review.hypothesis_confirmed else 'not confirmed' if monthly_review.hypothesis_confirmed is False else 'unclear'}")
    print(f"TREND:             {monthly_review.trend}")
    print(f"RATIONALE:         {monthly_review.rationale}")
    if monthly_review.lessons:
        print("LESSONS:")
        for lesson in monthly_review.lessons:
            print(f"  • {lesson}")
    print(f"\nRECOMMENDATION:    {recommendation.recommended_action.value} (confidence: {recommendation.confidence.value})")
    print(f"RATIONALE:         {recommendation.rationale}")
    if recommendation.proposed_adjustments:
        print("PROPOSED ADJUSTMENTS:")
        for adj in recommendation.proposed_adjustments:
            print(f"  • {adj}")
    if recommendation.proposed_new_strategy_focus:
        print(f"NEW STRATEGY FOCUS: {recommendation.proposed_new_strategy_focus}")
    print(f"{'─' * 60}")

    # Save
    if not args.dry_run:
        MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
        monthly_path.write_text(json.dumps(json.loads(monthly_review.model_dump_json()), indent=2, default=str))
        print(f"\nMonthly review saved → {monthly_path}")

        RECOMMENDATIONS_DIR.mkdir(parents=True, exist_ok=True)
        rec_path = RECOMMENDATIONS_DIR / f"{recommendation.recommendation_id}.json"
        rec_path.write_text(json.dumps(json.loads(recommendation.model_dump_json()), indent=2, default=str))
        print(f"Recommendation saved → {rec_path}")
    else:
        print(f"\n[dry-run] Would save monthly review to: {monthly_path}")
        print(f"[dry-run] Would save recommendation to: {RECOMMENDATIONS_DIR}/{recommendation.recommendation_id}.json")

    # Handle REPLACE_STRATEGY
    if monthly_review.decision == MonthlyDecision.REPLACE_STRATEGY:
        print(f"\n[!] REPLACE_STRATEGY — archiving current strategy cycle")
        print("    Human approval required before writing a new strategy.")

        if not args.dry_run:
            from src.strategy.history import HISTORY_STRATEGIES_DIR
            archived_path = HISTORY_STRATEGIES_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_{strategy_id}.json"
            # archive_weekly_reviews and archive_monthly_review called via history module
            archive_weekly_reviews(strategy_id)
            archive_monthly_review(strategy_id)

            change_record = StrategyChangeRecord(
                record_id=f"change-{uuid.uuid4().hex[:8]}",
                changed_at=datetime.now(),
                from_strategy_id=strategy_id,
                to_strategy_id=None,
                decision=MonthlyDecision.REPLACE_STRATEGY,
                rationale=monthly_review.rationale,
                recommendation_id=recommendation.recommendation_id,
                trigger_ref=str(monthly_path),
                archived_to=str(archived_path),
            )
            append_decision_log(change_record)
        else:
            print("[dry-run] Would archive strategy, weekly reviews, and monthly review to history/")
            print("[dry-run] Would append REPLACE_STRATEGY to decision_log.jsonl")

        print("\nNext steps:")
        print("  1. Review the recommendation in strategy/reviews/recommendations/")
        print("  2. Create a new strategy.json in strategy/current/")
        print("     (Use rotate_strategy() from src.strategy.history to do this atomically)")
        print("  3. Run build_monthly_plan.py for the new cycle")
    else:
        print(f"\nNo archiving required for {monthly_review.decision.value}.")


if __name__ == "__main__":
    main()
