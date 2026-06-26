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

log = get_logger("research.enrich")

_NULL_CASE = {
    "REAL_COMPANY_EXAMPLE":  None,
    "OUTCOME_IF_KNOWN":      "unknown",
    "DID_IT_WORK":           "unknown",
    "CONFIDENCE":            "low",
    "RECOMMENDED_FOR_ARTICLE": "false",
}

ENRICH_SYSTEM = """You are a business research analyst for Never Blank. Enrich business signals with verified facts.

CRITICAL RULES:
- Never invent company names, outcomes, statistics, or case sources.
- If you cannot identify a real company example from the signal, return null for REAL_COMPANY_EXAMPLE.
- If outcome is unknown, say "unknown" — do not guess.
- SOURCE_FOR_CASE must be a real URL or publication — if unknown, return null.
- CONFIDENCE: "high" only if specific sourced facts exist.

Return JSON with:
CORE_FACT, WHY_IT_MATTERS_TO_BUSINESS, BUSINESS_RESPONSES_OBSERVED, REAL_COMPANY_EXAMPLE,
PROBLEM_FACED, RESPONSE_TAKEN, OUTCOME_IF_KNOWN, SOURCE_FOR_CASE, BUSINESS_LESSON,
DID_IT_WORK, EVIDENCE_OF_OUTCOME, TIME_HORIZON, COUNTER_EXAMPLE, WHY_THIS_CASE_IS_INTERESTING,
CORE_TENSION, CONFIDENCE, NOTES"""


def enrich_signal(signal: dict) -> dict:
    user = f"""Enrich this business signal:

HEADLINE: {signal.get('HEADLINE', '')}
SOURCE: {signal.get('SOURCE_NAME', '')} — {signal.get('SOURCE_URL', '')}
DATE: {signal.get('SOURCE_DATE', '')}
SUMMARY: {signal.get('raw_summary', '')}
SIGNAL TYPE: {signal.get('SIGNAL_TYPE', '')}
REGION: {signal.get('REGION', '')}
INDUSTRY: {signal.get('INDUSTRY', '')}

If no real company case is identifiable, set REAL_COMPANY_EXAMPLE to null."""

    try:
        raw = chat(ENRICH_SYSTEM, user, json_mode=True, model=model_enrich())
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

    return merged


def enrich_candidates(candidates: list[dict]) -> list[dict]:
    result = []
    for c in candidates:
        log.info("Enriching: %s", c.get("HEADLINE", "")[:60])
        result.append(enrich_signal(c))
    return result
