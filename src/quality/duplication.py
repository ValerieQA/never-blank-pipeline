"""
Duplication QC check.

Wraps Phase 2 semantic deduplication. Returns a QCCheckResult.

In mock mode (no API key) uses Phase 2 mock embeddings — same behavior
as Phase 2 dry-run. Safe to run without OpenAI.
"""

from datetime import datetime, timezone
from src.models import QCCheckResult
from src.internal.memory import is_duplicate
from src.utils.logger import get_logger

log = get_logger("qc.duplication")


def check(text: str, current_slug: str, threshold: float | None = None) -> QCCheckResult:
    """
    Check whether text is semantically too similar to any previously published item.

    GREEN  = no duplicate found
    ORANGE = duplicate detected (quarantine topic — do not publish this)
    """
    now = datetime.now(timezone.utc).isoformat()

    is_dup, score, matched_slug = is_duplicate(text, threshold=threshold)

    if matched_slug == current_slug:
        # The embedding of the current slug was already saved — skip self-match
        log.debug("Dedup self-match skipped for slug=%s", current_slug)
        is_dup = False

    if is_dup:
        log.warning(
            "Duplication detected: score=%.4f matched=%r current=%r",
            score, matched_slug, current_slug,
        )
        return QCCheckResult(
            check_name="duplication",
            status="orange",
            score=round(1.0 - score, 4),   # invert: lower similarity = higher score
            issues=[
                f"Semantic similarity {score:.4f} ≥ threshold "
                f"(matched: {matched_slug!r})"
            ],
            guidance=(
                f"This topic overlaps significantly with previously published content "
                f"({matched_slug!r}, similarity={score:.4f}). "
                f"Adjust the angle or choose a different topic."
            ),
            checked_at=now,
        )

    log.debug("Duplication check passed: highest similarity=%.4f", score)
    return QCCheckResult(
        check_name="duplication",
        status="green",
        score=round(1.0 - score, 4),
        issues=[],
        guidance="",
        checked_at=now,
    )
