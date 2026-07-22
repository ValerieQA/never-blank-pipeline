"""
Never Blank Strategy Engine — Echo Memory (Phase 4C).

Prevents repetition of echoes, hooks, topics, and patterns across published
content within a strategy cycle. Memory is built from published_content_index.jsonl.

Similarity layers:
  1. Word-overlap heuristic (Jaccard) — fast, no external dependencies
  2. LLM semantic check — optional, triggered for ambiguous medium-range cases

Levels:
  HIGH   → blocks generation (Jaccard >= high_threshold)
  MEDIUM → warns, does not block (Jaccard in [medium_threshold, high_threshold))
  LOW    → noted but safe to use
  NONE   → no similarity detected

Integration:
  content_planner.py: inject format_memory_for_prompt() into generation prompts
  validators.py:      check_echo_uniqueness() as editorial guard before plan approval
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from src.strategy.history import load_published_index
from src.strategy.models import PublishedEntry
from src.utils.logger import get_logger

log = get_logger("strategy.echo_memory")


# ── Thresholds ─────────────────────────────────────────────────────────────────
#
# Echoes and hooks are short (1–2 sentences). Jaccard ≥ 0.60 means the reader
# will notice the repetition. Topics are structurally similar by design, so a
# higher threshold applies.

_ECHO_HIGH   = 0.60
_ECHO_MED    = 0.35
_HOOK_HIGH   = 0.55
_HOOK_MED    = 0.30
_TOPIC_HIGH  = 0.70   # topics legitimately overlap within a strategy; block only obvious clones
_TOPIC_MED   = 0.50

# Pattern recency: using the same pattern_id too soon makes the cycle feel repetitive
_PATTERN_BLOCK_WITHIN_LAST = 3   # same pattern_id in last 3 items → HIGH
_PATTERN_WARN_WITHIN_LAST  = 10  # same pattern_id in last 10 items → MEDIUM


# ── Models ─────────────────────────────────────────────────────────────────────

class MemoryMatch(BaseModel):
    content_id:     str
    published_at:   datetime
    field:          str    # "echo" | "hook" | "topic" | "pattern"
    score:          float  # Jaccard score (0.0–1.0); -1.0 for pattern (recency, not score)
    matched_text:   str    # the historical text that was matched
    candidate_text: str    # the new text being checked
    is_high:        bool   # True if score >= high threshold for this field


class EchoMemoryResult(BaseModel):
    echo_conflict:    bool
    hook_conflict:    bool
    topic_conflict:   bool
    pattern_conflict: bool
    matches:          list[MemoryMatch] = []
    warnings:         list[str]         = []
    blocked:          bool              # True if any HIGH conflict found


# ── Similarity utilities ───────────────────────────────────────────────────────

def _jaccard(a: str, b: str) -> float:
    """Compute Jaccard similarity on word-token sets."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _classify(score: float, high: float, medium: float) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    if score > 0.1:
        return "low"
    return "none"


# ── LLM semantic check ─────────────────────────────────────────────────────────

_SEMANTIC_SYSTEM = """You are a content quality reviewer for Never Blank.

Your task: determine whether two pieces of text are semantically equivalent —
meaning a reader would find them repetitive or interchangeable.

Texts can differ in wording and still be equivalent if they:
- Express the same insight in different words
- Use the same metaphor or comparison
- Lead the reader to the same realization

They are NOT equivalent if they:
- Address the same broad topic but make different specific points
- Use similar vocabulary but with different implications

Return JSON:
{
  "semantically_equivalent": true | false,
  "confidence": "high" | "medium" | "low",
  "reasoning": "one sentence"
}"""


def _llm_semantic_check(
    candidate: str,
    existing: str,
    llm_fn: callable,
) -> tuple[bool, str, str]:
    """
    Returns (is_equivalent, confidence, reasoning).
    On LLM failure: returns (False, "low", "LLM check failed") — fail-open.
    """
    user = f"Text A (existing):\n{existing}\n\nText B (candidate):\n{candidate}"
    try:
        raw = llm_fn(_SEMANTIC_SYSTEM, user, json_mode=True)
        data = json.loads(raw) if isinstance(raw, str) else raw
        return (
            bool(data.get("semantically_equivalent", False)),
            data.get("confidence", "low"),
            data.get("reasoning", ""),
        )
    except Exception as exc:
        log.warning("LLM semantic check failed: %s — treating as not equivalent", exc)
        return False, "low", f"LLM check failed: {exc}"


# ── Core check ─────────────────────────────────────────────────────────────────

def check_against_memory(
    echo:        Optional[str],
    hook:        str,
    topic:       str = "",
    pattern_id:  Optional[str] = None,
    strategy_id: str = "",
    last_n:      int = 20,
    use_llm:     bool = False,
    llm_fn:      Optional[callable] = None,
) -> EchoMemoryResult:
    """
    Check echo, hook, topic, and pattern_id against recent published content.

    Loads the last `last_n` entries from published_content_index.jsonl
    (filtered by strategy_id when provided) and computes similarity.

    Returns an EchoMemoryResult with:
      - Per-field conflict flags (echo, hook, topic, pattern)
      - MemoryMatch list for any detected similarity
      - warnings list (human-readable)
      - blocked flag (True if any HIGH conflict)

    Args:
        echo:        the echo text to check (None is allowed — skips echo check)
        hook:        the hook text to check
        topic:       the article topic (optional; higher threshold)
        pattern_id:  the source pattern ID (optional; checked for recency)
        strategy_id: filter history to this strategy only (recommended)
        last_n:      how many recent entries to load from the index
        use_llm:     whether to run LLM semantic check on medium-range Jaccard hits
        llm_fn:      callable(system, user, json_mode) → str|dict; required if use_llm=True
    """
    history = load_published_index(strategy_id=strategy_id or None, last_n=last_n)

    matches: list[MemoryMatch] = []
    warnings: list[str] = []

    echo_conflict    = False
    hook_conflict    = False
    topic_conflict   = False
    pattern_conflict = False

    # ── Pattern recency check ────────────────────────────────────────────────
    if pattern_id:
        recent_patterns = [e.pattern_id for e in history if e.pattern_id]
        if pattern_id in recent_patterns[:_PATTERN_BLOCK_WITHIN_LAST]:
            pattern_conflict = True
            matches.append(MemoryMatch(
                content_id=_find_content_id_for_pattern(history, pattern_id),
                published_at=_find_published_at_for_pattern(history, pattern_id),
                field="pattern",
                score=-1.0,
                matched_text=pattern_id,
                candidate_text=pattern_id,
                is_high=True,
            ))
            warnings.append(
                f"Pattern {pattern_id!r} was used in the last {_PATTERN_BLOCK_WITHIN_LAST} items. "
                "Consider using a different pattern to avoid repetition."
            )
        elif pattern_id in recent_patterns[:_PATTERN_WARN_WITHIN_LAST]:
            matches.append(MemoryMatch(
                content_id=_find_content_id_for_pattern(history, pattern_id),
                published_at=_find_published_at_for_pattern(history, pattern_id),
                field="pattern",
                score=-1.0,
                matched_text=pattern_id,
                candidate_text=pattern_id,
                is_high=False,
            ))
            warnings.append(
                f"Pattern {pattern_id!r} was used recently (within last {_PATTERN_WARN_WITHIN_LAST} items). "
                "Reader may notice the pattern recurring."
            )

    # ── Text similarity checks ────────────────────────────────────────────────
    checks = []
    if echo:
        checks.append(("echo", echo, _ECHO_HIGH, _ECHO_MED))
    if hook:
        checks.append(("hook", hook, _HOOK_HIGH, _HOOK_MED))
    if topic:
        checks.append(("topic", topic, _TOPIC_HIGH, _TOPIC_MED))

    for field, candidate, high_t, med_t in checks:
        for entry in history:
            historical = _entry_field(entry, field)
            if not historical:
                continue

            score = _jaccard(candidate, historical)
            level = _classify(score, high_t, med_t)

            if level == "none":
                continue

            is_high = level == "high"

            # Optional LLM upgrade for medium-range hits
            if level == "medium" and use_llm and llm_fn:
                llm_eq, llm_conf, llm_reason = _llm_semantic_check(candidate, historical, llm_fn)
                if llm_eq and llm_conf == "high":
                    is_high = True
                    level = "high"
                    log.info(
                        "LLM upgraded %s similarity to HIGH for content_id=%s: %s",
                        field, entry.content_id, llm_reason,
                    )

            match = MemoryMatch(
                content_id=entry.content_id,
                published_at=entry.published_at,
                field=field,
                score=round(score, 3),
                matched_text=historical[:120],
                candidate_text=candidate[:120],
                is_high=is_high,
            )
            matches.append(match)

            if is_high:
                if field == "echo":
                    echo_conflict = True
                elif field == "hook":
                    hook_conflict = True
                elif field == "topic":
                    topic_conflict = True
                warnings.append(
                    f"HIGH {field} similarity (score={score:.2f}) with published content "
                    f"'{entry.content_id}': {historical[:80]!r}"
                )
            else:
                warnings.append(
                    f"MEDIUM {field} similarity (score={score:.2f}) with '{entry.content_id}'. "
                    f"Consider varying the approach."
                )

            # For HIGH conflicts, no need to keep scanning — first match is enough for blocking
            if is_high:
                break

    blocked = echo_conflict or hook_conflict or topic_conflict or pattern_conflict

    if blocked:
        log.warning(
            "Echo memory: BLOCKED — echo=%s hook=%s topic=%s pattern=%s",
            echo_conflict, hook_conflict, topic_conflict, pattern_conflict,
        )
    elif matches:
        log.info("Echo memory: %d similarity match(es) found, not blocked", len(matches))
    else:
        log.debug("Echo memory: no conflicts detected")

    return EchoMemoryResult(
        echo_conflict=echo_conflict,
        hook_conflict=hook_conflict,
        topic_conflict=topic_conflict,
        pattern_conflict=pattern_conflict,
        matches=matches,
        warnings=warnings,
        blocked=blocked,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _entry_field(entry: PublishedEntry, field: str) -> str:
    return getattr(entry, field, "") or ""


def _find_content_id_for_pattern(history: list[PublishedEntry], pattern_id: str) -> str:
    for e in history:
        if e.pattern_id == pattern_id:
            return e.content_id
    return "unknown"


def _find_published_at_for_pattern(history: list[PublishedEntry], pattern_id: str) -> datetime:
    for e in history:
        if e.pattern_id == pattern_id:
            return e.published_at
    return datetime.now()


# ── Prompt formatting ──────────────────────────────────────────────────────────

def format_memory_for_prompt(
    strategy_id: str,
    last_n: int = 10,
) -> str:
    """
    Format recent echo/hook history for injection into content planner prompts.

    Returns a plain-text block listing recent echoes, hooks, and patterns to avoid.
    Returns empty string if no history exists (first article in cycle).
    """
    history = load_published_index(strategy_id=strategy_id or None, last_n=last_n)
    if not history:
        return ""

    lines = ["RECENT PUBLISHED CONTENT — avoid repeating these ideas and formulations:"]
    for i, entry in enumerate(reversed(history), 1):
        lines.append(f"\n[{i}] {entry.topic} ({entry.published_at.strftime('%Y-%m-%d')})")
        if entry.hook:
            lines.append(f"    Hook:    {entry.hook[:100]}")
        if entry.echo:
            lines.append(f"    Echo:    {entry.echo[:100]}")
        if entry.pattern_id:
            lines.append(f"    Pattern: {entry.pattern_id}")
        if entry.cta_mode and entry.cta_mode != "none":
            lines.append(f"    CTA:     {entry.cta_mode}")

    lines.append(
        "\nGenerate content that is meaningfully different from the above — "
        "different insight, different angle, different hook structure."
    )
    return "\n".join(lines)
