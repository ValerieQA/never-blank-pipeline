"""
Never Blank Strategy Engine — Approve Strategy Recommendation (Phase 4B).

This is the only script that triggers actual strategy archiving.
Monthly review produces a draft recommendation; this script executes it
after explicit human approval.

For REPLACE_STRATEGY:
  1. Sets recommendation.human_approved = True, approved_at = now()
  2. Archives current strategy to history/strategies/
  3. Archives weekly + monthly reviews to history/reviews/
  4. Appends StrategyChangeRecord to decision_log.jsonl
  5. Prints instructions for creating the new strategy

For CONTINUE_WITH_ADJUSTMENTS:
  1. Sets recommendation.human_approved = True
  2. Records the approval in decision_log.jsonl (no archiving)

For CONTINUE_STRATEGY:
  Prints a warning — CONTINUE_STRATEGY recommendations do not require approval.

Usage:
  python3 -m scripts.strategy.approve_strategy_recommendation \\
    --recommendation-id rec-2026-08-presence-debt-abc12345

  # Dry run — show what would happen, do nothing:
  python3 -m scripts.strategy.approve_strategy_recommendation \\
    --recommendation-id rec-2026-08-presence-debt-abc12345 --dry-run
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.strategy.history import (
    DECISIONS_DIR,
    append_decision_log,
    archive_current_strategy,
    archive_monthly_review,
    archive_weekly_reviews,
)
from src.strategy.loader import load_active_strategy
from src.strategy.models import MonthlyDecision, StrategyChangeRecord, StrategyRecommendation
from src.utils.logger import get_logger

log = get_logger("scripts.approve_strategy_recommendation")

RECOMMENDATIONS_DIR = Path("strategy/reviews/recommendations")


def load_recommendation(recommendation_id: str) -> tuple[StrategyRecommendation, Path]:
    """Load a StrategyRecommendation by ID. Raises if not found."""
    path = RECOMMENDATIONS_DIR / f"{recommendation_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Recommendation not found: {path}\n"
            f"Run run_monthly_review.py first to generate a recommendation."
        )
    data = json.loads(path.read_text())
    return StrategyRecommendation(**data), path


def save_recommendation(rec: StrategyRecommendation, path: Path) -> None:
    path.write_text(
        json.dumps(json.loads(rec.model_dump_json()), indent=2, default=str),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Approve a strategy recommendation and execute the strategic action"
    )
    parser.add_argument(
        "--recommendation-id", required=True,
        help="recommendation_id from strategy/reviews/recommendations/"
    )
    parser.add_argument(
        "--notes", type=str, default="",
        help="Optional human notes to attach to the approval"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen; do not write any files"
    )
    args = parser.parse_args()

    recommendation, rec_path = load_recommendation(args.recommendation_id)

    if recommendation.human_approved is True:
        print(f"Recommendation {args.recommendation_id} is already approved.")
        print(f"  Approved at: {recommendation.approved_at}")
        raise SystemExit(0)

    action = recommendation.recommended_action
    strategy_id = recommendation.strategy_id

    print(f"\nRecommendation:    {args.recommendation_id}")
    print(f"Strategy:          {strategy_id}")
    print(f"Action:            {action.value}")
    print(f"Confidence:        {recommendation.confidence.value}")
    print(f"Rationale:         {recommendation.rationale}")
    if recommendation.proposed_adjustments:
        print("Adjustments:")
        for adj in recommendation.proposed_adjustments:
            print(f"  • {adj}")
    if recommendation.proposed_new_strategy_focus:
        print(f"New focus:         {recommendation.proposed_new_strategy_focus}")

    print(f"\n{'─' * 60}")

    if action == MonthlyDecision.CONTINUE_STRATEGY:
        print("CONTINUE_STRATEGY does not require explicit approval.")
        print("No archiving or rotation will occur.")
        raise SystemExit(0)

    approved_at = datetime.now(timezone.utc)

    if action == MonthlyDecision.REPLACE_STRATEGY:
        print("ACTION: REPLACE_STRATEGY")
        print("  This will:")
        print("  1. Archive current strategy to strategy/history/strategies/")
        print("  2. Archive weekly + monthly reviews to strategy/history/reviews/")
        print("  3. Append StrategyChangeRecord to decision_log.jsonl")
        print("  4. Mark recommendation as approved")
        print(f"\n{'─' * 60}")

        if not args.dry_run:
            archived_path = archive_current_strategy()
            archive_weekly_reviews(strategy_id)
            archive_monthly_review(strategy_id)

            change_record = StrategyChangeRecord(
                record_id=f"change-{uuid.uuid4().hex[:8]}",
                changed_at=approved_at,
                from_strategy_id=strategy_id,
                to_strategy_id=None,
                decision=MonthlyDecision.REPLACE_STRATEGY,
                rationale=recommendation.rationale,
                recommendation_id=recommendation.recommendation_id,
                trigger_ref=str(rec_path),
                archived_to=str(archived_path),
            )
            append_decision_log(change_record)

            updated_rec = recommendation.model_copy(update={
                "human_approved": True,
                "approved_at": approved_at,
                "notes": args.notes,
            })
            save_recommendation(updated_rec, rec_path)

            print(f"Strategy archived   → {archived_path}")
            print(f"Decision logged     → {DECISIONS_DIR / 'decision_log.jsonl'}")
            print(f"Recommendation      → approved")
            print(f"\nNext steps:")
            print(f"  1. Create a new strategy in strategy/current/strategy.json")
            print(f"     Use activate_new_strategy() from src.strategy.history for atomic write.")
            print(f"  2. Run build_monthly_plan.py for the new cycle.")
        else:
            print("[dry-run] Would archive strategy, reviews, append decision log, mark approved.")

    elif action == MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS:
        print("ACTION: CONTINUE_WITH_ADJUSTMENTS")
        print("  Recording approval. No archiving or rotation.")

        if not args.dry_run:
            change_record = StrategyChangeRecord(
                record_id=f"change-{uuid.uuid4().hex[:8]}",
                changed_at=approved_at,
                from_strategy_id=strategy_id,
                to_strategy_id=strategy_id,  # same strategy continues
                decision=MonthlyDecision.CONTINUE_WITH_ADJUSTMENTS,
                rationale=recommendation.rationale,
                recommendation_id=recommendation.recommendation_id,
                trigger_ref=str(rec_path),
            )
            append_decision_log(change_record)

            updated_rec = recommendation.model_copy(update={
                "human_approved": True,
                "approved_at": approved_at,
                "notes": args.notes,
            })
            save_recommendation(updated_rec, rec_path)

            print(f"Decision logged     → {DECISIONS_DIR / 'decision_log.jsonl'}")
            print(f"Recommendation      → approved")
        else:
            print("[dry-run] Would append decision log, mark recommendation approved.")

    elif action == MonthlyDecision.INSUFFICIENT_DATA:
        print("ACTION: INSUFFICIENT_DATA — no strategic change required.")
        print("  Collect more weekly reviews before running a monthly review.")

    print(f"\nDone.")


if __name__ == "__main__":
    main()
