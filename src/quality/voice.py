"""
Voice QC check.

Validates that generated content matches Never Blank brand voice.
Rejects generic AI fluff, agency-speak, and preachy content.
Enforces: content is evidence of intelligence, not filler.

Status mapping:
  score >= 0.72 → GREEN  (passes)
  score < 0.72  → YELLOW (rewrite required)

In mock mode (no API key), returns GREEN with score=0.85.
"""

import json
import os
import re
from datetime import datetime, timezone
from src.models import QCCheckResult
from src.utils.config_loader import load_brand, load_prompt
from src.utils.logger import get_logger

log = get_logger("qc.voice")

_VOICE_THRESHOLD = 0.72   # from quality.yaml voice_drift.alert_threshold

# Auto-fail phrases — presence of any of these immediately drops score below threshold
_AUTO_FAIL_PHRASES = [
    "in today's world",
    "in today's fast-paced",
    "in today's competitive",
    "game-changer",
    "let's dive in",
    "let's unpack",
    "at the end of the day",
    "it's important to",
    "you need to",
    "here's the thing",
    "leverage",
    "hustle",
    "journey",
    "unpack",
    "game changer",
    "low-hanging fruit",
    "move the needle",
    "circle back",
    "double down",
    "deep dive",
    "drill down",
]


def _has_auto_fail(content: str) -> list[str]:
    """Return list of auto-fail phrases found in content (case-insensitive)."""
    lower = content.lower()
    return [p for p in _AUTO_FAIL_PHRASES if p in lower]


def _mock_result(check_name: str, now: str) -> QCCheckResult:
    return QCCheckResult(
        check_name=check_name,
        status="green",
        score=0.85,
        issues=[],
        guidance="",
        checked_at=now,
    )


def _fill(template: str, context: dict) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        val = context.get(key)
        if val is None:
            return match.group(0)
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)
    return re.sub(r"\{(\w+)\}", replacer, template)


def check(
    content: str,
    platform: str,
    observation_statement: str,
    check_name: str | None = None,
) -> QCCheckResult:
    """
    Evaluate content against Never Blank voice.

    platform: "blog" | "linkedin" | "instagram" | "facebook" | "threads" | "telegram"
    check_name: label for the result (e.g. "voice_blog", "voice_linkedin")
    """
    name = check_name or f"voice_{platform}"
    now  = datetime.now(timezone.utc).isoformat()

    if not content or not content.strip():
        return QCCheckResult(
            check_name=name,
            status="yellow",
            score=0.0,
            issues=["Content is empty"],
            guidance="Content was not generated. Retry generation.",
            checked_at=now,
        )

    # Fast deterministic pre-check: auto-fail phrases
    auto_fails = _has_auto_fail(content)
    if auto_fails:
        log.warning("Voice auto-fail phrases found in %s: %s", name, auto_fails)

    if not os.environ.get("NB_OPENAI_API_KEY", "").strip():
        log.debug("Voice check in mock mode (NB_OPENAI_API_KEY not set)")
        if auto_fails:
            # Even in mock mode, flag auto-fail phrases deterministically
            return QCCheckResult(
                check_name=name,
                status="yellow",
                score=0.5,
                issues=[f'Auto-fail phrase: "{p}"' for p in auto_fails[:3]],
                guidance=(
                    f"Remove the following phrases and rewrite those sections "
                    f"in direct, observational language: {auto_fails[:3]}"
                ),
                checked_at=now,
            )
        return _mock_result(name, now)

    from src.utils.llm_client import chat_qc_json

    brand  = load_brand()
    voice  = brand.get("voice", {})
    prompt = load_prompt("qc_voice")

    context = {
        "content":               content,
        "platform":              platform,
        "observation_statement": observation_statement,
        "tone_list":             ", ".join(voice.get("tone", [])),
        "avoid_list":            ", ".join(voice.get("avoid", [])),
    }
    system = prompt["system"]
    user   = _fill(prompt["user"], context)

    try:
        result = chat_qc_json(system, user)
    except Exception as exc:
        log.error("Voice QC call failed: %s — falling back to auto-fail check only", exc)
        if auto_fails:
            return QCCheckResult(
                check_name=name,
                status="yellow",
                score=0.5,
                issues=[f'Auto-fail phrase: "{p}"' for p in auto_fails[:3]],
                guidance=f"Remove auto-fail phrases: {auto_fails[:3]}",
                checked_at=now,
            )
        return _mock_result(name, now)

    score    = float(result.get("score", 0.5))
    issues   = result.get("issues", [])
    guidance = result.get("rewrite_guidance", "")
    passed   = score >= _VOICE_THRESHOLD

    # Merge auto-fail findings with LLM findings
    for phrase in auto_fails:
        auto_issue = f'Auto-fail phrase detected: "{phrase}"'
        if auto_issue not in issues:
            issues.insert(0, auto_issue)
    if auto_fails and score >= _VOICE_THRESHOLD:
        # Force fail if auto-fail phrases found regardless of LLM score
        passed = False
        score = min(score, 0.65)
        if not guidance:
            guidance = f"Remove these phrases and rewrite in direct language: {auto_fails}"

    status = "green" if passed else "yellow"
    log.info("Voice QC %s: score=%.4f status=%s issues=%d", name, score, status, len(issues))

    return QCCheckResult(
        check_name=name,
        status=status,
        score=round(score, 4),
        issues=issues,
        guidance=guidance,
        checked_at=now,
    )
