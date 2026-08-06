"""
Stage 4 — Enrichment.
Fill full signal schema via LLM. Never invents case sources, outcomes, or company examples.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_enrich
from src.utils.config_loader import load_prompt

log = get_logger("research.enrich")

_NULL_CASE = {
    "REAL_COMPANY_EXAMPLE":  None,
    "OUTCOME_IF_KNOWN":      "unknown",
    "DID_IT_WORK":           "unknown",
    "CONFIDENCE":            "low",
    "RECOMMENDED_FOR_ARTICLE": "false",
}


def determine_article_readiness(signal: dict) -> tuple[bool, str]:
    """
    Deterministic, no-LLM, no-side-effects check for factual article readiness.

    Scoring recommendation != factual article readiness.
    A signal becomes article-ready only after deterministic enrichment verification.

    Returns (ready: bool, reason: str).
    """
    has_company  = bool(signal.get("REAL_COMPANY_EXAMPLE"))
    has_source   = bool(signal.get("SOURCE_FOR_CASE"))
    has_fact     = bool(signal.get("CORE_FACT", "").strip())
    outcome_ok   = signal.get("OUTCOME_IF_KNOWN", "unknown") != "unknown"
    confidence   = signal.get("CONFIDENCE", "low")

    premise_verified = has_company and has_source
    signal_strength_ok = confidence in ("high", "medium")

    if not premise_verified:
        return False, "SOURCE_PREMISE_VERIFIED=false: missing REAL_COMPANY_EXAMPLE or SOURCE_FOR_CASE"
    if not has_fact:
        return False, "missing CORE_FACT"
    if not signal_strength_ok:
        return False, f"CONFIDENCE={confidence!r} — insufficient evidence quality"
    return True, "all evidence fields present"


def enrich_signal(signal: dict) -> dict:
    prompt = load_prompt("research/enrich", {
        "headline":    signal.get("HEADLINE", ""),
        "source_name": signal.get("SOURCE_NAME", ""),
        "source_url":  signal.get("SOURCE_URL", ""),
        "source_date": signal.get("SOURCE_DATE", ""),
        "raw_summary": signal.get("raw_summary", ""),
        "signal_type": signal.get("SIGNAL_TYPE", ""),
        "region":      signal.get("REGION", ""),
        "industry":    signal.get("INDUSTRY", ""),
    })

    try:
        raw = chat(prompt["system"], prompt["user"], json_mode=True, model=model_enrich())
        enriched = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(enriched, dict):
            enriched = {}
    except Exception as exc:
        log.error("Enrichment failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        enriched = {}

    merged = dict(signal)
    merged.update(enriched)

    if not merged.get("REAL_COMPANY_EXAMPLE") or not merged.get("SOURCE_FOR_CASE"):
        merged.update(_NULL_CASE)
        log.info("Signal %s: no case source — marked not article-ready", signal.get("SIGNAL_ID"))

    # Deterministic readiness fields — set after all evidence is merged.
    article_ready, reason = determine_article_readiness(merged)
    premise_verified = (
        bool(merged.get("REAL_COMPANY_EXAMPLE")) and bool(merged.get("SOURCE_FOR_CASE"))
    )
    merged["SOURCE_PREMISE_VERIFIED"] = str(premise_verified).lower()
    merged["ARTICLE_READY"]           = str(article_ready).lower()
    # Keep legacy field in sync so sheet consumers remain unaffected.
    merged["RECOMMENDED_FOR_ARTICLE"] = str(article_ready).lower()

    if not article_ready:
        log.info("Signal %s: ARTICLE_READY=false — %s", signal.get("SIGNAL_ID"), reason)

    return merged


def enrich_candidates(candidates: list[dict]) -> list[dict]:
    result = []
    for c in candidates:
        log.info("Enriching: %s", c.get("HEADLINE", "")[:60])
        result.append(enrich_signal(c))
    return result
