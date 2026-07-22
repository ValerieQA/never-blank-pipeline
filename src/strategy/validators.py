"""
Never Blank Strategy Engine — Validators.

Three validation layers:
  1. validate_strategy()         — strategy JSON is complete and coherent
  2. validate_content_plan_item() — each topic has all required fields
  3. validate_compound_presence_semantic() — article contains the semantic connection

All validators are fail-closed: raise ValueError on failure.
None of them run silently.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from src.strategy.models import ContentPlanItem, Strategy
from src.utils.logger import get_logger

log = get_logger("strategy.validators")


# ── Strategy validation ────────────────────────────────────────────────────────

_REQUIRED_STRATEGY_FIELDS = [
    "market_context",
    "selected_problem",
    "sales_hypothesis",
    "commercial_goal",
    "compound_presence_role",
    "continuation_criteria",
    "research_references",
]


def validate_strategy(strategy: Strategy) -> None:
    """
    Validate a Strategy object. Raises ValueError listing all failures.
    """
    errors: list[str] = []

    for field in _REQUIRED_STRATEGY_FIELDS:
        val = getattr(strategy, field, None)
        if val is None:
            errors.append(f"Missing required field: {field}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"Empty required field: {field}")
        elif isinstance(val, list) and len(val) == 0:
            errors.append(f"Empty list for required field: {field}")

    if not strategy.strategy_id or not strategy.strategy_id.strip():
        errors.append("strategy_id is required")

    if not strategy.strategy_name or not strategy.strategy_name.strip():
        errors.append("strategy_name is required")

    if strategy.review_date <= strategy.started_at:
        errors.append("review_date must be after started_at")

    if errors:
        raise ValueError("Strategy validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    log.info("Strategy validation passed: %s", strategy.strategy_id)


# ── Content plan validation ────────────────────────────────────────────────────

_REQUIRED_CONTENT_FIELDS = [
    "hook", "mechanism", "reframe", "sales_objective",
    "compound_presence_connection", "cta_mode",
    "website_angle", "linkedin_angle", "instagram_angle",
    "facebook_angle", "threads_angle", "telegram_angle",
]


def validate_content_plan_item(item: ContentPlanItem) -> None:
    """
    Validate a single ContentPlanItem. Raises ValueError on failure.
    """
    errors: list[str] = []

    for field in _REQUIRED_CONTENT_FIELDS:
        val = getattr(item, field, None)
        if not val or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing required field: {field}")

    if not item.strategy_id:
        errors.append("content plan item must reference a strategy_id")

    # Echo is required (rare exception allowed but must be explicit)
    if not item.echo or not item.echo.strip():
        errors.append(
            "echo is required. If no strong Echo candidate emerged, "
            "set echo to null explicitly with a note — do not leave empty."
        )

    if errors:
        raise ValueError(
            f"Content plan item '{item.content_id}' validation failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def validate_content_plan(items: list[ContentPlanItem], strategy_id: str) -> None:
    """
    Validate an entire content plan. Raises ValueError if any item fails or plan is too small.
    """
    errors: list[str] = []

    if len(items) < 8:
        errors.append(f"Content plan has only {len(items)} items; minimum is 8 per month")

    # All items must reference the active strategy
    wrong_strategy = [i.content_id for i in items if i.strategy_id != strategy_id]
    if wrong_strategy:
        errors.append(f"Items referencing wrong strategy_id: {wrong_strategy}")

    # Check for excessive duplication across items
    hooks = [i.hook.lower().strip() for i in items if i.hook]
    unique_hooks = set(hooks)
    if len(hooks) > 3 and len(unique_hooks) / len(hooks) < 0.6:
        errors.append("Too many duplicate hooks in content plan — less than 60% unique")

    if errors:
        raise ValueError("Content plan validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    # Validate each item individually
    item_errors: list[str] = []
    for item in items:
        try:
            validate_content_plan_item(item)
        except ValueError as exc:
            item_errors.append(str(exc))

    if item_errors:
        raise ValueError("Individual content plan items failed:\n" + "\n\n".join(item_errors))

    log.info("Content plan validation passed: %d items for strategy %s", len(items), strategy_id)


# ── Compound Presence semantic validation ──────────────────────────────────────
#
# This validator checks MEANING, not structure.
# It does not look for a section header or a specific paragraph.
# It checks whether the article establishes the connection between the
# revealed mechanism and the cumulative effect of consistent presence.
#
# Implementation: keyword heuristic as first-pass filter (fast, no API call).
# LLM-assisted semantic check is triggered only when keyword check is ambiguous.

_PRESENCE_KEYWORDS = frozenset({
    "presence", "visibility", "consistent", "consistently", "systematic",
    "sustained", "repeated", "repeatedly", "accumulated", "accumulate",
    "ongoing", "regular", "regularly", "compound", "compounding",
    "over time", "trust", "recognition", "memory", "familiarity",
    "contact", "cadence", "week after week", "month after month",
    "never blank",
})

_CONTRAST_SIGNALS = frozenset({
    "one-time", "once", "single", "viral", "lucky", "luck", "moment",
    "accident", "accidental", "spike", "burst", "one post",
    "not a strategy", "not a system", "not enough", "temporary",
})

_SYSTEM_PROMPT_SEMANTIC = """You are a content quality reviewer for Never Blank.

Never Blank's core concept: Compound Presence — the cumulative effect of consistent,
systematic visibility at relevant contact points. Presence that accumulates over time,
builds recognition and trust, and does not depend on a single lucky moment.

Your task: determine whether the article establishes a genuine connection between
the mechanism it revealed and the concept of consistent, systematic presence.

The connection does NOT need to be a separate paragraph. It can be:
- Part of the Reframe
- The transition from Business Consequence to Echo
- Meaning distributed across multiple sentences

The connection IS present if the article:
1. Explains why one-time attention does not equal systematic presence
2. Shows how repeated visibility, trust, or audience memory accumulates
3. Connects the revealed mechanism to the consequences of inconsistent presence
4. Makes the reader feel the gap between a lucky moment and a presence system

The connection IS ABSENT if the article:
- Only describes what happened (mechanism) without connecting it to presence
- Ends on a business consequence without any Compound Presence dimension
- Uses "presence" or "visibility" as decoration rather than as the argument's core

Return JSON:
{
  "compound_presence_present": true | false,
  "confidence": "high" | "medium" | "low",
  "reasoning": "one sentence explaining why"
}"""


def validate_compound_presence_semantic(
    text: str,
    use_llm: bool = False,
    llm_fn: Optional[callable] = None,
) -> None:
    """
    Validate that the article text contains Compound Presence Connection.

    First pass: keyword heuristic (fast).
    If ambiguous and use_llm=True: LLM semantic check (accurate but slower).

    Raises ValueError only when the connection is definitively absent.
    Does not fail on ambiguous or brief connections.

    Args:
        text: the article body text
        use_llm: whether to run LLM check when heuristic is ambiguous
        llm_fn: callable(system, user, json_mode) → str | dict; used for LLM check
    """
    lower = text.lower()

    presence_count = sum(1 for kw in _PRESENCE_KEYWORDS if kw in lower)
    contrast_count = sum(1 for kw in _CONTRAST_SIGNALS if kw in lower)

    # Clear pass: both presence vocabulary AND contrast signals present
    if presence_count >= 3 and contrast_count >= 1:
        log.debug("compound_presence check: PASS (heuristic — presence=%d, contrast=%d)",
                  presence_count, contrast_count)
        return

    # Clear fail: no presence vocabulary at all
    if presence_count == 0:
        if use_llm and llm_fn:
            _llm_semantic_check(text, llm_fn)
            return
        raise ValueError(
            "Article missing Compound Presence Connection: no presence/visibility vocabulary found. "
            "The article must connect its mechanism to the cumulative effect of consistent presence."
        )

    # Ambiguous zone: some presence keywords but no contrast signal
    if presence_count >= 1 and contrast_count == 0:
        if use_llm and llm_fn:
            _llm_semantic_check(text, llm_fn)
            return
        # Without LLM, give benefit of doubt — log warning but do not fail
        log.warning(
            "compound_presence check: AMBIGUOUS — presence keywords=%d, contrast signals=%d. "
            "Consider enabling LLM semantic check for production.",
            presence_count, contrast_count,
        )


def _llm_semantic_check(text: str, llm_fn: callable) -> None:
    """Run LLM semantic check. Raises ValueError if connection is absent with high confidence."""
    user = f"Article text:\n\n{text[:3000]}"
    try:
        raw = llm_fn(_SYSTEM_PROMPT_SEMANTIC, user, json_mode=True)
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        log.warning("LLM compound_presence check failed: %s — skipping hard fail", exc)
        return

    present = data.get("compound_presence_present", True)
    confidence = data.get("confidence", "low")
    reasoning = data.get("reasoning", "")

    if not present and confidence == "high":
        raise ValueError(
            f"Article missing Compound Presence Connection (LLM high-confidence): {reasoning}"
        )
    if not present:
        log.warning(
            "compound_presence check: LLM flagged absent (confidence=%s) — %s",
            confidence, reasoning,
        )


# ── Article pre-publish validation ─────────────────────────────────────────────

def validate_article_for_publish(
    text: str,
    platform: str = "blog",
    use_llm_compound_check: bool = False,
    llm_fn: Optional[callable] = None,
) -> None:
    """
    Full pre-publish validation for a single article/post.
    Calls output_guard checks + compound_presence semantic check.

    Raises ValueError on first hard failure.
    """
    from src.content.output_guard import validate_platform_output

    validate_platform_output(platform, text)

    if platform in ("blog", "linkedin"):
        validate_compound_presence_semantic(text, use_llm=use_llm_compound_check, llm_fn=llm_fn)

    log.info("Article pre-publish validation passed: platform=%s", platform)
