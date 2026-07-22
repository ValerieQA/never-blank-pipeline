"""
Never Blank Strategy Engine — Active strategy loader.

Loads strategy/current/strategy.json as the source of truth for the active cycle.
All generation passes read CTA mode, Compound Presence role, and strategy context from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.strategy.models import Strategy
from src.utils.logger import get_logger

log = get_logger("strategy.loader")

_STRATEGY_PATH = Path("strategy/current/strategy.json")


def load_active_strategy() -> Optional[Strategy]:
    """
    Load the active strategy from strategy/current/strategy.json.
    Returns None if file does not exist or cannot be parsed.
    Never raises — callers fall back to defaults if strategy is unavailable.
    """
    if not _STRATEGY_PATH.exists():
        log.warning("No active strategy found at %s — using pipeline defaults", _STRATEGY_PATH)
        return None
    try:
        data = json.loads(_STRATEGY_PATH.read_text())
        strategy = Strategy(**data)
        log.info("Active strategy loaded: %s (status=%s)", strategy.strategy_id, strategy.status.value)
        return strategy
    except Exception as exc:
        log.error("Failed to load active strategy from %s: %s", _STRATEGY_PATH, exc)
        return None


def get_cta_mode(strategy: Optional[Strategy]) -> str:
    """
    Return the CTA mode string for the current cycle.
    Uses strategy.primary_cta_intent.value if available, otherwise "none".
    Returns a plain string (not the CTAMode enum) so callers can use it directly.
    """
    if strategy is None:
        return "none"
    mode = strategy.primary_cta_intent
    value = mode.value if hasattr(mode, "value") else str(mode)
    log.debug("CTA mode from strategy %s: %s", strategy.strategy_id, value)
    return value or "none"


def get_strategy_context(strategy: Optional[Strategy]) -> dict:
    """
    Return a context dict to inject into article generation.
    Used to pass strategy framing into Editorial Engine prompts.
    """
    if strategy is None:
        return {
            "strategy_id": "none",
            "primary_message": "",
            "compound_presence_role": "",
            "desired_reader_realization": "",
            "selected_problem": "",
            "presence_debt_focus": False,
        }
    return {
        "strategy_id": strategy.strategy_id,
        "primary_message": strategy.primary_message,
        "compound_presence_role": strategy.compound_presence_role,
        "desired_reader_realization": strategy.desired_reader_realization,
        "selected_problem": strategy.selected_problem,
        "presence_debt_focus": strategy.presence_debt_focus,
    }
