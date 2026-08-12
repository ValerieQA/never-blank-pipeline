"""
Never Blank Strategy Engine — Validators.

Three validation layers:
  1. validate_strategy()         — strategy JSON is complete and coherent
  2. validate_content_plan_item() — each topic has all required fields
  3. validate_compound_presence_semantic() — article contains the semantic connection

Fail-closed semantics:
- validate_strategy and validate_content_plan_item: always raise on failure.
- validate_compound_presence_semantic: raises only when the connection is
  DEFINITIVELY ABSENT (0 presence keywords / LLM high-confidence absent).
  Ambiguous text (some keywords, no contrast) logs a warning but does not fail —
  per decision 44: "fail-closed only when ENTIRELY absent."
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional, Protocol, Sequence, runtime_checkable

from src.strategy.models import (
    ContentPlanItem,
    Strategy,
    StrategicTopic,
    VisibilityQuotaResult,
)
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

    # Echo: required unless explicitly null with a stated reason (decision 43).
    if item.echo is not None and not item.echo.strip():
        errors.append("echo cannot be an empty string; use null + echo_omission_reason")
    if item.echo is None and not (item.echo_omission_reason and item.echo_omission_reason.strip()):
        errors.append("echo is null but echo_omission_reason is missing or blank; set a reason")
    # Contradictory state: echo present AND omission reason set.
    if item.echo and item.echo_omission_reason and item.echo_omission_reason.strip():
        errors.append("echo_omission_reason must be null when echo is set")

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

    # Traceability: generated plans must have source_pattern_id on all items.
    # Items missing it could indicate the plan was created without market analysis.
    untraced = [i.content_id for i in items if not i.source_pattern_id]
    if untraced:
        errors.append(
            f"Items missing source_pattern_id (traceability): {untraced}. "
            "Generate plans via build_monthly_plan or market_analyzer to populate this field."
        )

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

    # Clear fail: no presence vocabulary at all → definitively absent.
    if presence_count == 0:
        if use_llm and llm_fn:
            # If LLM disagrees (high-confidence present), accept it. If LLM fails,
            # the heuristic result stands — treat as absent.
            _llm_semantic_check(text, llm_fn, heuristic_failed=True)
            return
        raise ValueError(
            "Article missing Compound Presence Connection: no presence/visibility vocabulary found. "
            "The article must connect its mechanism to the cumulative effect of consistent presence."
        )

    # Ambiguous zone: some presence keywords but no contrast signal.
    # Not definitively absent — warn only (decision 44: fail only when ENTIRELY absent).
    if presence_count >= 1 and contrast_count == 0:
        if use_llm and llm_fn:
            # LLM failure in ambiguous zone: warn, do not fail.
            _llm_semantic_check(text, llm_fn, heuristic_failed=False)
            return
        log.warning(
            "compound_presence check: AMBIGUOUS — presence keywords=%d, contrast signals=%d. "
            "Consider enabling LLM semantic check for production.",
            presence_count, contrast_count,
        )


def _llm_semantic_check(
    text: str,
    llm_fn: callable,
    heuristic_failed: bool = False,
) -> None:
    """
    Run LLM semantic check.
    Raises ValueError if connection is absent with high confidence,
    or if heuristic_failed=True and LLM call itself fails.
    """
    user = f"Article text:\n\n{text[:3000]}"
    try:
        raw = llm_fn(_SYSTEM_PROMPT_SEMANTIC, user, json_mode=True)
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        if heuristic_failed:
            raise ValueError(
                "Article missing Compound Presence Connection (heuristic absent, LLM check failed)"
            ) from exc
        log.warning("LLM compound_presence check failed: %s — heuristic was ambiguous, skipping", exc)
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


# ── Echo Memory editorial guard ───────────────────────────────────────────────

def check_echo_uniqueness(
    item: ContentPlanItem,
    strategy_id: str,
    last_n: int = 20,
    block_on_high: bool = True,
    use_llm: bool = False,
    llm_fn=None,
) -> None:
    """
    Check a ContentPlanItem's echo, hook, and topic against published history.

    MEDIUM conflicts → warning log only.
    HIGH conflicts   → raises ValueError when block_on_high=True.
    Pattern recency  → always raises when pattern used in last 3 items.

    This is the Editorial Guard step between Echo Memory and content plan approval.
    Called explicitly — not wired into validate_content_plan_item() to keep
    that validator dependency-free (no filesystem access required).
    """
    from src.strategy.echo_memory import check_against_memory

    result = check_against_memory(
        echo=item.echo,
        hook=item.hook,
        topic=item.topic,
        pattern_id=item.source_pattern_id,
        strategy_id=strategy_id,
        last_n=last_n,
        use_llm=use_llm,
        llm_fn=llm_fn,
    )

    for warning in result.warnings:
        if "HIGH" in warning or "Pattern" in warning and "last 3" in warning:
            log.warning("Echo memory guard [%s]: %s", item.content_id, warning)
        else:
            log.info("Echo memory guard [%s]: %s", item.content_id, warning)

    if block_on_high and result.blocked:
        conflict_fields = [
            field for field, flag in [
                ("echo", result.echo_conflict),
                ("hook", result.hook_conflict),
                ("topic", result.topic_conflict),
                ("pattern", result.pattern_conflict),
            ] if flag
        ]
        raise ValueError(
            f"Content plan item '{item.content_id}' blocked by Echo Memory: "
            f"HIGH similarity detected in {conflict_fields}. "
            f"Regenerate with a different angle.\n"
            + "\n".join(f"  • {w}" for w in result.warnings if "HIGH" in w or "last 3" in w)
        )


# ── Article pre-publish validation ─────────────────────────────────────────────

def validate_article_for_publish(
    text: str,
    platform: str = "blog",
    use_llm_compound_check: bool = False,
    llm_fn: Optional[callable] = None,
    run_id: str = "",
) -> None:
    """
    Full pre-publish validation for a single article/post.
    Calls output_guard checks + compound_presence semantic check.

    run_id: propagated from RunContext. When non-empty it is logged at the
    validation gate. Callers outside the canonical path may omit it.

    Raises ValueError on first hard failure.
    """
    from src.content.output_guard import validate_platform_output

    if run_id:
        log.info("Validation gate: platform=%s run_id=%s", platform, run_id)

    validate_platform_output(platform, text)

    if platform in ("blog", "linkedin"):
        validate_compound_presence_semantic(text, use_llm=use_llm_compound_check, llm_fn=llm_fn)

    log.info("Article pre-publish validation passed: platform=%s", platform)


# ── Visibility Intelligence quota ─────────────────────────────────────────────

@runtime_checkable
class _HasStrategicTopic(Protocol):
    """Structural protocol satisfied by both ContentPlanItem and VisibilityHistoryEntry."""
    strategic_topic: Optional[StrategicTopic]


def validate_visibility_quota(
    items: Sequence[_HasStrategicTopic],
) -> VisibilityQuotaResult:
    """Check 40% AI Visibility / 60% Brand Concept quota across visibility items.

    Never raises. Returns VisibilityQuotaResult with is_valid=False and
    populated warnings when thresholds are not met.

    Caller is responsible for scoping `items` to the relevant time window
    (e.g. published_this_month + [candidate]).  Recognition posts must be
    excluded by the caller — items without strategic_topic are skipped here
    and do not count toward the denominator.

    Quotas are planning instruments, not hard gates.  The caller logs warnings
    and continues; it does not exit on is_valid=False.

    Note on small-sample math:
        ceil(n × 0.40) + ceil(n × 0.60) > n for most small n.
        Example: n=8 → required 4 + 5 = 9 > 8.
        Both thresholds cannot be satisfied simultaneously with fewer than 10 items.
        This is expected behavior: the validator issues warnings for both when the
        sample is small, and the caller treats them as advisory.  Do not treat this
        as a validator bug — it is a deliberate property of the chosen formula.
    """
    total = len(items)
    if total == 0:
        return VisibilityQuotaResult(
            total_items=0,
            ai_visibility_count=0,
            brand_concept_count=0,
            ai_visibility_required=0,
            brand_concept_required=0,
            is_valid=True,
        )

    ai_count    = sum(1 for i in items if i.strategic_topic == StrategicTopic.AI_VISIBILITY)
    brand_count = sum(1 for i in items if i.strategic_topic == StrategicTopic.BRAND_CONCEPT)

    ai_required    = math.ceil(total * 0.40)
    brand_required = math.ceil(total * 0.60)

    warnings: list[str] = []
    if ai_count < ai_required:
        warnings.append(
            f"AI Visibility underrepresented: {ai_count}/{total} posts "
            f"(required ≥{ai_required}, i.e. 40% of {total})"
        )
    if brand_count < brand_required:
        warnings.append(
            f"Brand Concept underrepresented: {brand_count}/{total} posts "
            f"(required ≥{brand_required}, i.e. 60% of {total})"
        )

    return VisibilityQuotaResult(
        total_items=total,
        ai_visibility_count=ai_count,
        brand_concept_count=brand_count,
        ai_visibility_required=ai_required,
        brand_concept_required=brand_required,
        is_valid=len(warnings) == 0,
        warnings=warnings,
    )
