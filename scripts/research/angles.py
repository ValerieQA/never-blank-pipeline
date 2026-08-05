"""
Stage 5 — Angle Generation.
Generate channel-specific content angles for enriched signals.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_enrich
from src.utils.config_loader import load_prompt

log = get_logger("research.angles")

VALID_AUDIENCES = {"founder", "owner", "consultant", "service_business", "small_team", "agency", "creator"}
VALID_CHANNELS  = {"linkedin", "blog", "threads", "story", "instagram"}

def generate_angles(signal: dict) -> dict:
    prompt = load_prompt("research/angles", {
        "headline":                   signal.get("HEADLINE", ""),
        "core_fact":                  signal.get("CORE_FACT", ""),
        "core_tension":               signal.get("CORE_TENSION", ""),
        "real_company_example":       signal.get("REAL_COMPANY_EXAMPLE", "none"),
        "business_lesson":            signal.get("BUSINESS_LESSON", ""),
        "why_this_case_is_interesting": signal.get("WHY_THIS_CASE_IS_INTERESTING", ""),
        "signal_type":                signal.get("SIGNAL_TYPE", ""),
    })

    try:
        raw = chat(prompt["system"], prompt["user"], json_mode=True, model=model_enrich())
        angles = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(angles, dict):
            angles = {}
    except Exception as exc:
        log.error("Angle generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        angles = {}

    if angles.get("TARGET_AUDIENCE") not in VALID_AUDIENCES:
        angles["TARGET_AUDIENCE"] = "founder"
    if angles.get("PRIMARY_CHANNEL") not in VALID_CHANNELS:
        angles["PRIMARY_CHANNEL"] = "linkedin"

    merged = dict(signal)
    merged.update(angles)
    return merged


def add_angles(signals: list[dict]) -> list[dict]:
    return [generate_angles(s) for s in signals]
