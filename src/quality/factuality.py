"""
Factual risk assessment QC check.

NOT fact-checking. Identifies claims that carry credibility, legal, or
reputational risk if they turn out to be wrong or unverifiable.

Risk levels:
  low    → GREEN  (pass)
  medium → YELLOW (rewrite: soften/remove specific claims)
  high   → ORANGE (quarantine: legal/medical/financial advice risk)

In mock mode (no API key), returns GREEN with a clearly labeled mock result.
"""

import json
import os
import re
from datetime import datetime, timezone
from src.models import QCCheckResult, ContentBrief
from src.utils.config_loader import load_prompt
from src.utils.logger import get_logger

log = get_logger("qc.factuality")

_RISK_TO_STATUS = {
    "low":    "green",
    "medium": "yellow",
    "high":   "orange",
}


def _mock_result(now: str) -> QCCheckResult:
    return QCCheckResult(
        check_name="factuality",
        status="green",
        score=1.0,
        issues=[],
        guidance="",
        risk_level="low",
        legal_risk=False,
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


def check(content: str, brief: ContentBrief) -> QCCheckResult:
    """
    Assess factual risk of content.
    Returns QCCheckResult with status green/yellow/orange.
    """
    now = datetime.now(timezone.utc).isoformat()

    if not os.environ.get("NB_OPENAI_API_KEY", "").strip():
        log.debug("Factuality check in mock mode (NB_OPENAI_API_KEY not set)")
        return _mock_result(now)

    from src.utils.llm_client import chat_qc_json

    prompt = load_prompt("qc_factuality")
    context = {
        "content":              content,
        "observation_statement": brief.observation_statement,
        "source_signals_json":  json.dumps(brief.source_signals, ensure_ascii=False),
    }
    system = prompt["system"]
    user   = _fill(prompt["user"], context)

    try:
        result = chat_qc_json(system, user)
    except Exception as exc:
        log.error("Factuality QC call failed: %s — treating as medium risk", exc)
        return QCCheckResult(
            check_name="factuality",
            status="yellow",
            score=0.5,
            issues=[f"QC call failed: {exc}"],
            guidance="QC could not be completed. Review content manually before publishing.",
            risk_level="medium",
            legal_risk=False,
            checked_at=now,
        )

    risk_level    = result.get("risk_level", "medium")
    legal_risk    = bool(result.get("legal_risk", False))
    flags         = result.get("flags", [])
    missing_attr  = result.get("missing_attribution", [])
    guidance      = result.get("guidance", "")

    # Legal risk always escalates to ORANGE
    if legal_risk:
        risk_level = "high"
    status = _RISK_TO_STATUS.get(risk_level, "yellow")

    # Score: 1.0 for low, 0.5 for medium, 0.0 for high
    score_map = {"low": 1.0, "medium": 0.5, "high": 0.0}
    score = score_map.get(risk_level, 0.5)

    issues = flags + [f"Missing attribution: {c}" for c in missing_attr]

    log.info(
        "Factuality QC: risk=%s legal=%s flags=%d status=%s",
        risk_level, legal_risk, len(flags), status,
    )
    return QCCheckResult(
        check_name="factuality",
        status=status,
        score=score,
        issues=issues,
        guidance=guidance,
        risk_level=risk_level,
        legal_risk=legal_risk,
        checked_at=now,
    )
