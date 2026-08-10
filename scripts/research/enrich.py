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
from src.research.providers import LLMProvider, DefaultLLMProvider

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

    Two valid evidence paths (either satisfies SOURCE_PREMISE_VERIFIED):
      1. Verified company case: REAL_COMPANY_EXAMPLE + SOURCE_FOR_CASE
      2. Verified research/data: SOURCE_FOR_CASE alone with CONFIDENCE >= medium
         (covers research on customer memory, trust, visibility without a named company)

    Returns (ready: bool, reason: str).
    """
    has_company  = bool(signal.get("REAL_COMPANY_EXAMPLE"))
    has_source   = bool(signal.get("SOURCE_FOR_CASE"))
    has_fact     = bool(signal.get("CORE_FACT", "").strip())
    confidence   = signal.get("CONFIDENCE", "low")
    signal_strength_ok = confidence in ("high", "medium")

    # Path 1: verified company case
    company_case_verified = has_company and has_source
    # Path 2: verified research/data — source present + sufficient confidence
    research_verified = has_source and signal_strength_ok

    premise_verified = company_case_verified or research_verified

    if not premise_verified:
        if not has_source:
            return False, "SOURCE_PREMISE_VERIFIED=false: missing SOURCE_FOR_CASE"
        return False, (
            "SOURCE_PREMISE_VERIFIED=false: SOURCE_FOR_CASE present but "
            f"CONFIDENCE={confidence!r} is insufficient for research path "
            "(need medium or high, or provide REAL_COMPANY_EXAMPLE)"
        )
    if not has_fact:
        return False, "missing CORE_FACT"

    # Explicit disclaimer in CORE_FACT overrides confidence-based paths.
    # Prevents research path from accepting a signal the LLM itself flagged as unverified.
    _UNVERIFIED_MARKERS = ("not verified", "unverified", "unverifiable", "unsupported", "cannot be confirmed")
    fact_lower = signal.get("CORE_FACT", "").lower()
    for marker in _UNVERIFIED_MARKERS:
        if marker in fact_lower:
            return False, f"CORE_FACT contains explicit disclaimer ({marker!r}) — claim is not verifiable"

    return True, "evidence verified" + (" (company case)" if company_case_verified else " (research/data)")


def enrich_signal(signal: dict, llm_provider: "LLMProvider | None" = None) -> dict:
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

    _chat = llm_provider.chat if llm_provider is not None else chat

    try:
        raw = _chat(prompt["system"], prompt["user"], json_mode=True, model=model_enrich())
        enriched = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(enriched, dict):
            enriched = {}
    except Exception as exc:
        log.error("Enrichment failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        enriched = {}

    merged = dict(signal)
    merged.update(enriched)

    # _NULL_CASE resets to safe defaults when no evidence source exists.
    # SOURCE_FOR_CASE is required by both evidence paths; if absent, neither
    # path can succeed. A signal without source is not article-ready.
    # Note: signals with source but no company remain eligible via research path.
    has_source_now = bool(merged.get("SOURCE_FOR_CASE"))
    if not has_source_now:
        merged.update(_NULL_CASE)
        log.info("Signal %s: no case source — marked not article-ready", signal.get("SIGNAL_ID"))

    # Deterministic readiness fields — set after all evidence is merged.
    article_ready, reason = determine_article_readiness(merged)
    # SOURCE_PREMISE_VERIFIED is true if either evidence path is satisfied:
    # path 1 — company case: REAL_COMPANY_EXAMPLE + SOURCE_FOR_CASE
    # path 2 — research/data: SOURCE_FOR_CASE + confidence >= medium
    has_source   = bool(merged.get("SOURCE_FOR_CASE"))
    has_company  = bool(merged.get("REAL_COMPANY_EXAMPLE"))
    confidence   = merged.get("CONFIDENCE", "low")
    premise_verified = (has_company and has_source) or (has_source and confidence in ("high", "medium"))
    merged["SOURCE_PREMISE_VERIFIED"] = str(premise_verified).lower()
    merged["ARTICLE_READY"]           = str(article_ready).lower()
    # Keep legacy field in sync so sheet consumers remain unaffected.
    merged["RECOMMENDED_FOR_ARTICLE"] = str(article_ready).lower()

    if not article_ready:
        log.info("Signal %s: ARTICLE_READY=false — %s", signal.get("SIGNAL_ID"), reason)

    return merged


def enrich_candidates(
    candidates: list[dict],
    llm_provider: "LLMProvider | None" = None,
) -> list[dict]:
    result = []
    for c in candidates:
        log.info("Enriching: %s", c.get("HEADLINE", "")[:60])
        result.append(enrich_signal(c, llm_provider=llm_provider))
    return result
