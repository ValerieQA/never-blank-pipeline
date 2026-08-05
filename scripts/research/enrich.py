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

    return merged


def enrich_candidates(candidates: list[dict]) -> list[dict]:
    result = []
    for c in candidates:
        log.info("Enriching: %s", c.get("HEADLINE", "")[:60])
        result.append(enrich_signal(c))
    return result
