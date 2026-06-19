import csv
import uuid
from pathlib import Path
from src.utils.logger import get_logger
from src.utils.config_loader import load_strategy
from src.models import TopicCandidate, ObservationType, ContentGoal

log = get_logger("topic_prioritizer")

MANUAL_QUEUE = Path(__file__).parent.parent.parent / "topics_manual.csv"


def _read_manual_queue() -> list[dict]:
    if not MANUAL_QUEUE.exists():
        return []
    with open(MANUAL_QUEUE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_manual_queue(rows: list[dict]) -> None:
    if not rows:
        return
    with open(MANUAL_QUEUE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _build_candidate_from_manual(row: dict) -> TopicCandidate:
    strategy = load_strategy()
    obs_type = ObservationType.OBSERVATION if hasattr(ObservationType, "OBSERVATION") \
        else ObservationType.PATTERN

    goal_str = row.get("content_goal", "").strip() or "educate"
    try:
        goal = ContentGoal(goal_str)
    except ValueError:
        goal = ContentGoal.EDUCATE

    platforms_raw = row.get("target_platforms", "wix,linkedin,instagram,facebook,threads,telegram")
    platforms = [p.strip() for p in platforms_raw.split(",") if p.strip()]

    return TopicCandidate(
        observation_id=str(uuid.uuid4()),
        observation_statement=row.get("angle", row.get("title", "")),
        observation_type=ObservationType.PATTERN,
        title=row.get("title", ""),
        angle=row.get("angle", ""),
        hook=row.get("angle", ""),
        content_goal=goal,
        platform_fit=platforms,
        evergreen=True,
        relevance_score=1.0,
        diversity_adjustment=0.0,
        final_score=1.0,
        source="manual",
        manual_topic_id=row.get("id"),
    )


def get_next_topic() -> TopicCandidate | None:
    """
    Return the next topic to publish.
    Priority: manual queue → Intelligence Engine (stub in Phase 7).
    """
    rows = _read_manual_queue()
    pending = [r for r in rows if r.get("status", "").strip() == "pending"]

    if pending:
        row = pending[0]
        log.info("Manual topic selected: '%s'", row.get("title", ""))
        return _build_candidate_from_manual(row)

    log.info("Manual queue empty — Intelligence Engine not wired yet (Phase 7)")
    return None


def mark_manual_topic_in_progress(topic_id: str) -> None:
    rows = _read_manual_queue()
    for row in rows:
        if row.get("id") == topic_id:
            row["status"] = "in_progress"
    _write_manual_queue(rows)


def mark_manual_topic_published(topic_id: str) -> None:
    rows = _read_manual_queue()
    for row in rows:
        if row.get("id") == topic_id:
            row["status"] = "published"
    _write_manual_queue(rows)
