"""
Stage 5 — Angle Generation.
Generate channel-specific content angles for enriched signals.
"""
# ─────────────────────────────────────────────────────────────────────────────
# ISOLATED WEDNESDAY RESEARCH MODULE — restored verbatim from c7d3a23 (#211).
#
# A literal port of the July 6 2026 research stage that produced the Versant /
# Full Swing signal. It is deliberately NOT the shared scripts/research module
# of the same name: those have since been retargeted at small-business feeds
# and given a selector that rejects large-company M&A by name — the two
# changes (218719a, a557855, both 2026-07-21) that made the specimen
# unreachable. Bypassing them is the point.
#
# Do not "reconcile" this file with scripts/research/. Do not refactor it into
# the shared pipeline. If the shared module changes, this file must NOT follow.
#
# Only current TECHNICAL infrastructure is used — llm_client (provider,
# per-stage model routing, call budget, retry ceilings), requests and logging.
# No current business rule reaches this module.
# ─────────────────────────────────────────────────────────────────────────────

import json
import sys
from pathlib import Path

# #211 forced deviation: this file moved deeper, so the repo root is
# four parents up rather than two. Same target, adjusted depth.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_enrich

log = get_logger("research.angles")

VALID_AUDIENCES = {"founder", "owner", "consultant", "service_business", "small_team", "agency", "creator"}
VALID_CHANNELS  = {"linkedin", "blog", "threads", "story", "instagram"}

ANGLES_SYSTEM = """You generate editorial angles for Never Blank, a content strategy practice for founders.

Never Blank does not explain events. Never Blank studies how businesses respond to events.

Style: Sharp, observational, commercially aware. Smart peer — not a consultant.

Strong hook examples:
- "The layoffs were visible. The org chart wasn't."
- "AI isn't replacing jobs. It's replacing layers."
- "Watch the structure change, not the headcount."

AVOID: generic AI narratives, "businesses need to adapt", "in today's world", vague thought leadership.

Return JSON with:
- LINKEDIN_ANGLE: observation + business lesson format
- BLOG_ANGLE: signal + case study + outcome + lesson format
- THREADS_ANGLE: provocative one-liner observation
- STORY_ANGLE: question or tension format
- POTENTIAL_HOOK: single opening sentence, concrete and uncomfortable
- INTERESTING_QUESTION: the question this signal raises for founders
- NEVER_BLANK_ANGLE: the observation that emerges from the business response
- POSSIBLE_SIGNATURE_LINE: "Never Blank: [short sharp insight]"
- TARGET_AUDIENCE: one of [founder, owner, consultant, service_business, small_team, agency, creator]
- PRIMARY_CHANNEL: one of [linkedin, blog, threads, story, instagram]"""


def generate_angles(signal: dict) -> dict:
    user = f"""Generate Never Blank content angles for this signal:

HEADLINE: {signal.get('HEADLINE', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
WHY_THIS_CASE_IS_INTERESTING: {signal.get('WHY_THIS_CASE_IS_INTERESTING', '')}
SIGNAL_TYPE: {signal.get('SIGNAL_TYPE', '')}"""

    try:
        raw = chat(ANGLES_SYSTEM, user, json_mode=True, model=model_enrich())
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
