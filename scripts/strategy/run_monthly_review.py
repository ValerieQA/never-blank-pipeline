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
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from src.strategy.decision_engine import draft_monthly_review, draft_strategy_recommendation
from src.strategy.loader import load_active_strategy
from src.strategy.models import MonthlyDecision, StrategyChangeRecord, WeeklyReview
from src.utils.logger import get_logger

log = get_logger("scripts.run_monthly_review")

WEEKLY_DIR = Path("strategy/reviews/weekly")
MONTHLY_DIR = Path("strategy/reviews/monthly")
RECOMMENDATIONS_DIR = Path("strategy/reviews/recommendations")
HISTORY_STRATEGIES_DIR = Path("strategy/history/strategies")
HISTORY_REVIEWS_DIR = Path("strategy/history/reviews")
DECISIONS_DIR = Path("strategy/history/decisions")
CURRENT_STRATEGY_JSON = Path("strategy/current/strategy.json")
CURRENT_STRATEGY_MD = Path("strategy/current/strategy.md")


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


def archive_strategy(strategy_id: str, dry_run: bool) -> str:
    """Copy current strategy.json + strategy.md to strategy/history/strategies/{strategy_id}/."""
    dest_dir = HISTORY_STRATEGIES_DIR / strategy_id
    if dry_run:
        print(f"[dry-run] Would archive strategy to: {dest_dir}/")
        return str(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if CURRENT_STRATEGY_JSON.exists():
        shutil.copy2(CURRENT_STRATEGY_JSON, dest_dir / "strategy.json")
    if CURRENT_STRATEGY_MD.exists():
        shutil.copy2(CURRENT_STRATEGY_MD, dest_dir / "strategy.md")
    log.info("Strategy archived to %s", dest_dir)
    return str(dest_dir)


def archive_weekly_reviews(strategy_id: str, dry_run: bool) -> None:
    """Move weekly reviews for the strategy to strategy/history/reviews/."""
    dest_dir = HISTORY_REVIEWS_DIR / strategy_id
    if dry_run:
        print(f"[dry-run] Would archive weekly reviews to: {dest_dir}/")
        return
    if not WEEKLY_DIR.exists():
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in WEEKLY_DIR.glob(f"{strategy_id}_w*.json"):
        shutil.move(str(path), dest_dir / path.name)
    log.info("Weekly reviews archived to %s", dest_dir)


def append_decision_log(record: StrategyChangeRecord, dry_run: bool) -> None:
    """Append a StrategyChangeRecord to the decision log (append-only JSONL)."""
    log_path = DECISIONS_DIR / "decision_log.jsonl"
    if dry_run:
        print(f"[dry-run] Would append to decision log: {log_path}")
        return
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(json.loads(record.model_dump_json()), default=str) + "\n")
    log.info("Decision log updated: %s", log_path)


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
        print(f"\n⚠  REPLACE_STRATEGY — archiving current strategy cycle")
        print("   Human approval required before creating a new strategy.")

        archived_to = archive_strategy(strategy_id, args.dry_run)
        archive_weekly_reviews(strategy_id, args.dry_run)

        change_record = StrategyChangeRecord(
            record_id=f"change-{uuid.uuid4().hex[:8]}",
            changed_at=datetime.now(),
            from_strategy_id=strategy_id,
            to_strategy_id=None,
            decision=MonthlyDecision.REPLACE_STRATEGY,
            rationale=monthly_review.rationale,
            recommendation_id=recommendation.recommendation_id,
            trigger_ref=str(monthly_path),
            archived_to=archived_to,
        )
        append_decision_log(change_record, args.dry_run)

        print("\nNext steps:")
        print("  1. Review the recommendation in strategy/reviews/recommendations/")
        print("  2. Create a new strategy.json in strategy/current/")
        print("  3. Run build_monthly_plan.py for the new cycle")
    else:
        print(f"\nNo archiving required for {monthly_review.decision.value}.")


if __name__ == "__main__":
    main()
